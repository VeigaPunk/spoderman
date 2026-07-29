"""No-limit Texas Hold'em tournament engine.

Supports blinds with escalation, full betting rounds, all-ins, side pots
and eliminations. Strategies only ever see public information plus their
own hole cards — nobody is told what algorithm anyone else runs.
"""
from collections import deque

from .cards import best_hand

BLIND_LEVELS = [
    (10, 20), (15, 30), (20, 40), (30, 60), (50, 100), (75, 150),
    (100, 200), (150, 300), (200, 400), (300, 600), (500, 1000),
    (800, 1600), (1300, 2600), (2000, 4000), (3000, 6000),
]
HANDS_PER_LEVEL = 8


class Seat:
    __slots__ = ("pid", "stack", "strategy")

    def __init__(self, pid, stack, strategy):
        self.pid = pid
        self.stack = stack
        self.strategy = strategy


class HandPlayer:
    __slots__ = ("seat", "hole", "bet", "contrib", "folded", "allin")

    def __init__(self, seat, hole):
        self.seat = seat
        self.hole = hole
        self.bet = 0          # committed this betting round
        self.contrib = 0      # committed this hand (for side pots)
        self.folded = False
        self.allin = False


class Tournament:
    def __init__(self, players, rng, start_stack=1500):
        """players: list of (pid, strategy) in seating order."""
        self.rng = rng
        self.seats = [Seat(pid, start_stack, strat) for pid, strat in players]
        self.hand_events = []
        self.bb = 0

    def blinds_for(self, hand_no):
        return BLIND_LEVELS[min(hand_no // HANDS_PER_LEVEL, len(BLIND_LEVELS) - 1)]

    def run(self):
        """Play until one player has all the chips.

        Returns (champion_pid, finish_order_worst_to_best, hands_played).
        """
        alive = list(self.seats)
        button = 0
        hand_no = 0
        finish = []
        while len(alive) > 1 and hand_no < 3000:
            sb, bb = self.blinds_for(hand_no)
            self.play_hand(alive, button % len(alive), sb, bb)
            busted = sorted((s for s in alive if s.stack <= 0), key=lambda s: s.pid)
            finish.extend(s.pid for s in busted)
            alive = [s for s in alive if s.stack > 0]
            button += 1
            hand_no += 1
        finish.extend(s.pid for s in sorted(alive, key=lambda s: s.stack))
        return finish[-1], finish, hand_no

    # ------------------------------------------------------------------ hands

    def play_hand(self, alive, button, sb, bb):
        n = len(alive)
        deck = list(range(52))
        self.rng.shuffle(deck)
        ps = [HandPlayer(s, (deck.pop(), deck.pop())) for s in alive]
        self.bb = bb
        self.hand_events = []

        if n == 2:  # heads-up: button posts SB and acts first preflop
            sb_i, bb_i, pre_start = button, (button + 1) % n, button
        else:
            sb_i, bb_i = (button + 1) % n, (button + 2) % n
            pre_start = (button + 3) % n
        post_start = (button + 1) % n

        self._emit_all(ps, {
            "type": "hand_start",
            "pids": [hp.seat.pid for hp in ps],
            "button_pid": ps[button].seat.pid,
            "sb": sb, "bb": bb,
            "stacks": {hp.seat.pid: hp.seat.stack for hp in ps},
        })

        for i, amount in ((sb_i, sb), (bb_i, bb)):
            hp = ps[i]
            pay = min(amount, hp.seat.stack)
            hp.seat.stack -= pay
            hp.bet += pay
            hp.contrib += pay
            if hp.seat.stack == 0:
                hp.allin = True

        board = []
        self.betting_round(ps, pre_start, board, "preflop", bb, button)
        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if sum(1 for hp in ps if not hp.folded) < 2:
                break
            for _ in range(ncards):
                board.append(deck.pop())
            for hp in ps:
                hp.bet = 0
            self.betting_round(ps, post_start, board, street, bb, button)
        if sum(1 for hp in ps if not hp.folded) >= 2:
            while len(board) < 5:  # all-in runout
                board.append(deck.pop())
        self.showdown(ps, board)

    # ---------------------------------------------------------------- betting

    def betting_round(self, ps, start, board, street, bb, button):
        n = len(ps)
        order = [ps[(start + i) % n] for i in range(n)]
        current_bet = max(hp.bet for hp in ps)
        min_raise = bb
        pending = deque(hp for hp in order if not hp.folded and not hp.allin)

        while pending:
            hp = pending.popleft()
            if hp.folded or hp.allin:
                continue
            if sum(1 for q in ps if not q.folded) == 1:
                break
            to_call = current_bet - hp.bet
            others_can_act = any(
                q is not hp and not q.folded and not q.allin for q in ps
            )
            if not others_can_act and to_call <= 0:
                break

            view = self.make_view(hp, ps, board, street, current_bet, min_raise, button)
            action = hp.seat.strategy.act(view)
            kind, amount = (action, 0) if isinstance(action, str) else action

            if kind == "fold" and to_call <= 0:
                kind = "check"
            if kind == "check" and to_call > 0:
                kind = "fold"

            if kind == "fold":
                hp.folded = True
                self._emit_action(ps, street, hp, "fold", 0)
            elif kind == "check":
                self._emit_action(ps, street, hp, "check", 0)
            elif kind == "call":
                pay = min(to_call, hp.seat.stack)
                hp.seat.stack -= pay
                hp.bet += pay
                hp.contrib += pay
                if hp.seat.stack == 0:
                    hp.allin = True
                self._emit_action(ps, street, hp, "call", pay)
            elif kind == "raise":
                max_to = hp.bet + hp.seat.stack
                if max_to <= current_bet:  # can't actually raise: call all-in
                    pay = hp.seat.stack
                    hp.seat.stack = 0
                    hp.bet += pay
                    hp.contrib += pay
                    hp.allin = True
                    self._emit_action(ps, street, hp, "call", pay)
                else:
                    target = min(max(amount, current_bet + min_raise), max_to)
                    pay = target - hp.bet
                    hp.seat.stack -= pay
                    hp.bet = target
                    hp.contrib += pay
                    if hp.seat.stack == 0:
                        hp.allin = True
                    min_raise = max(min_raise, target - current_bet)
                    current_bet = target
                    i = order.index(hp)
                    pending = deque()
                    for k in range(1, n):
                        q = order[(i + k) % n]
                        if not q.folded and not q.allin:
                            pending.append(q)
                    self._emit_action(ps, street, hp, "raise", target)
            else:
                raise ValueError(f"unknown action {kind!r}")

    # --------------------------------------------------------------- showdown

    def showdown(self, ps, board):
        live = [hp for hp in ps if not hp.folded]
        winners = {}
        if len(live) == 1:
            total = sum(hp.contrib for hp in ps)
            live[0].seat.stack += total
            winners[live[0].seat.pid] = total
        else:
            ranks = {hp: best_hand(hp.hole + tuple(board)) for hp in live}
            levels = sorted({hp.contrib for hp in live})
            prev = 0
            for lvl in levels:
                pot = sum(min(hp.contrib, lvl) - min(hp.contrib, prev) for hp in ps)
                prev = lvl
                if pot <= 0:
                    continue
                eligible = [hp for hp in live if hp.contrib >= lvl]
                best = max(ranks[hp] for hp in eligible)
                pot_winners = [hp for hp in eligible if ranks[hp] == best]
                share, rem = divmod(pot, len(pot_winners))
                for j, hp in enumerate(pot_winners):
                    amt = share + (rem if j == 0 else 0)
                    hp.seat.stack += amt
                    winners[hp.seat.pid] = winners.get(hp.seat.pid, 0) + amt
        self._emit_all(ps, {
            "type": "hand_end",
            "winners": winners,
            "board": tuple(board),
            "revealed": {hp.seat.pid: hp.hole for hp in live} if len(live) > 1 else {},
        })

    # ------------------------------------------------------------------ views

    def make_view(self, hp, ps, board, street, current_bet, min_raise, button):
        i = ps.index(hp)
        n = len(ps)
        return {
            "pid": hp.seat.pid,
            "hole": hp.hole,
            "board": tuple(board),
            "street": street,
            "pot": sum(q.contrib for q in ps),
            "to_call": max(0, current_bet - hp.bet),
            "current_bet": current_bet,
            "my_bet": hp.bet,
            "stack": hp.seat.stack,
            "min_raise_to": current_bet + min_raise,
            "bb": self.bb,
            "num_live": sum(1 for q in ps if not q.folded),
            "late": i == button or i == (button - 1) % n,
            "stacks": {q.seat.pid: q.seat.stack for q in ps if not q.folded},
            "history": self.hand_events,
        }

    def _emit_action(self, ps, street, hp, action, amount):
        self._emit_all(ps, {
            "type": "action",
            "street": street,
            "pid": hp.seat.pid,
            "action": action,
            "amount": amount,
            "allin": hp.allin,
            "pot": sum(q.contrib for q in ps),
        })

    def _emit_all(self, ps, event):
        self.hand_events.append(event)
        for hp in ps:
            hp.seat.strategy.observe(event)
