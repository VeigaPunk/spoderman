"""No-limit Texas Hold'em tournament engine: betting rounds, side pots,
escalating blinds, eliminations. Strategies only ever see public info +
their own hole cards — nobody knows anyone else's algorithm."""

import random
from collections import deque
from types import SimpleNamespace

from .cards import evaluate

BLIND_LEVELS = [(10, 20), (15, 30), (25, 50), (50, 100), (75, 150),
                (100, 200), (150, 300), (250, 500), (400, 800), (600, 1200)]
HANDS_PER_LEVEL = 15
START_STACK = 2000


class PlayerState:
    def __init__(self, pid, name, strategy, stack):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = None
        self.folded = True
        self.all_in = False
        self.round_bet = 0    # committed this betting round
        self.total_bet = 0    # committed this hand

    def can_act(self):
        return not self.folded and not self.all_in and self.stack > 0


class Tournament:
    def __init__(self, strategy_factories, names, seed):
        self.rng = random.Random(seed)
        self.players = [PlayerState(i + 1, names[i], strategy_factories[i](self.rng), START_STACK)
                        for i in range(len(names))]
        self.button = self.rng.randrange(len(self.players))
        self.hand_no = 0
        self.eliminated = []  # pids in bust order

    # ---- helpers -------------------------------------------------------
    def blinds(self):
        lvl = self.hand_no // HANDS_PER_LEVEL
        if lvl < len(BLIND_LEVELS):
            return BLIND_LEVELS[lvl]
        sb, bb = BLIND_LEVELS[-1]
        mult = 2 ** (lvl - len(BLIND_LEVELS) + 1)
        return sb * mult, bb * mult

    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def emit(self, ev):
        for p in self.players:
            p.strategy.observe(ev)

    # ---- main loop -----------------------------------------------------
    def run(self, max_hands=5000):
        while len(self.alive()) > 1 and self.hand_no < max_hands:
            self.play_hand()
            self.hand_no += 1
        survivors = sorted(self.alive(), key=lambda p: p.stack)
        for p in survivors[:-1]:
            self.eliminated.append(p.pid)
        winner = survivors[-1]
        placements = {winner.pid: 1}
        for i, pid in enumerate(reversed(self.eliminated)):
            placements[pid] = i + 2
        return winner.pid, placements, self.hand_no

    # ---- one hand ------------------------------------------------------
    def play_hand(self):
        # advance button to next living seat
        n_seats = len(self.players)
        for step in range(1, n_seats + 1):
            s = (self.button + step) % n_seats
            if self.players[s].stack > 0:
                self.button = s
                break

        order = []
        for step in range(n_seats):
            p = self.players[(self.button + step) % n_seats]
            if p.stack > 0:
                order.append(p)
        n = len(order)
        start_stacks = {p.pid: p.stack for p in order}

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in order:
            p.hole = (deck.pop(), deck.pop())
            p.folded = False
            p.all_in = False
            p.round_bet = 0
            p.total_bet = 0
        full_board = [deck.pop() for _ in range(5)]

        sb_amt, bb_amt = self.blinds()
        self.bb_amt = bb_amt
        if n == 2:
            sb_p, bb_p = order[0], order[1]   # heads-up: button posts SB
            preflop_first = 0
        else:
            sb_p, bb_p = order[1], order[2]
            preflop_first = 3 % n
        self._post(sb_p, min(sb_amt, sb_p.stack))
        self._post(bb_p, min(bb_amt, bb_p.stack))
        self.current_bet = bb_amt
        self.min_raise = bb_amt
        self.last_raiser = None
        self.emit({"type": "hand_start", "pids": [p.pid for p in order]})

        self.board = []
        self._betting_round(order, "preflop", preflop_first)
        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if sum(1 for p in order if not p.folded) <= 1:
                break
            self.board += full_board[len(self.board):len(self.board) + ncards]
            if sum(1 for p in order if p.can_act()) >= 2:
                for p in order:
                    p.round_bet = 0
                self.current_bet = 0
                self.min_raise = bb_amt
                self.last_raiser = None
                self._betting_round(order, street, 1 % n)

        live = [p for p in order if not p.folded]
        if len(live) >= 2:
            self.board = full_board  # run out the board for all-ins
        self._distribute(order, live)

        for p in sorted((p for p in order if p.stack == 0),
                        key=lambda p: start_stacks[p.pid]):
            self.eliminated.append(p.pid)
        self.emit({"type": "hand_end"})

    def _post(self, p, amount):
        p.stack -= amount
        p.round_bet += amount
        p.total_bet += amount
        if p.stack == 0:
            p.all_in = True

    # ---- betting -------------------------------------------------------
    def _betting_round(self, order, stage, first_idx):
        n = len(order)
        acting = [order[(first_idx + i) % n] for i in range(n)]
        for i, p in enumerate(acting):
            p._pos_frac = i / max(1, n - 1)
        pending = deque(p for p in acting if p.can_act())

        while pending:
            if sum(1 for x in order if not x.folded) <= 1:
                return
            p = pending.popleft()
            if not p.can_act():
                continue
            action = p.strategy.act(self._view(p, order, stage))
            self._apply(p, action, order, stage, pending)

    def _view(self, p, order, stage):
        pot = sum(x.total_bet for x in order)
        to_call = min(self.current_bet - p.round_bet, p.stack)
        return SimpleNamespace(
            hole=p.hole,
            board=tuple(self.board),
            stage=stage,
            pot=pot,
            to_call=to_call,
            current_bet=self.current_bet,
            my_round_bet=p.round_bet,
            stack=p.stack,
            min_raise=self.min_raise,
            bb=self.bb_amt,
            n_opp=sum(1 for x in order if not x.folded) - 1,
            n_alive=len(order),
            pos_frac=p._pos_frac,
            hand_no=self.hand_no,
            my_pid=p.pid,
            aggressor_pid=self.last_raiser,
            opponents=[(x.pid, x.stack, x.folded, x.all_in, x.round_bet)
                       for x in order if x is not p],
            rng=self.rng,
        )

    def _apply(self, p, action, order, stage, pending):
        kind = action[0]
        to_call = self.current_bet - p.round_bet

        if kind == "fold":
            if to_call <= 0:  # never fold when checking is free
                kind = "call"
            else:
                p.folded = True
                self.emit({"type": "action", "pid": p.pid, "stage": stage,
                           "kind": "fold", "amount": 0, "allin": False})
                return

        if kind == "raise":
            target = int(action[1])
            max_target = p.round_bet + p.stack
            target = min(target, max_target)
            if target <= self.current_bet:
                kind = "call"  # can't actually raise -> call (possibly all-in)
            else:
                full_min = self.current_bet + self.min_raise
                if target < full_min and target < max_target:
                    target = min(full_min, max_target)
                pay = target - p.round_bet
                self._post(p, pay)
                inc = target - self.current_bet
                if inc >= self.min_raise:
                    self.min_raise = inc
                self.current_bet = target
                self.last_raiser = p.pid
                # everyone else gets to act again, in order after the raiser
                n = len(order)
                i = order.index(p)
                pending.clear()
                for step in range(1, n):
                    q = order[(i + step) % n]
                    if q.can_act():
                        pending.append(q)
                self.emit({"type": "action", "pid": p.pid, "stage": stage,
                           "kind": "raise", "amount": target, "allin": p.all_in})
                return

        # call / check
        pay = min(max(to_call, 0), p.stack)
        self._post(p, pay)
        self.emit({"type": "action", "pid": p.pid, "stage": stage,
                   "kind": "call" if pay > 0 else "check",
                   "amount": pay, "allin": p.all_in})

    # ---- payout with side pots -----------------------------------------
    def _distribute(self, order, live):
        # refund final uncalled excess to the deepest contributor
        contribs = sorted(p.total_bet for p in order)
        if len(contribs) >= 2 and contribs[-1] > contribs[-2]:
            top = max(order, key=lambda p: p.total_bet)
            refund = contribs[-1] - contribs[-2]
            top.stack += refund
            top.total_bet -= refund
            if top.stack > 0:
                top.all_in = False

        if len(live) == 1:
            live[0].stack += sum(p.total_bet for p in order)
            return

        ranks = {p.pid: evaluate(list(p.hole) + self.board) for p in live}
        levels = sorted({p.total_bet for p in order if p.total_bet > 0})
        prev = 0
        for level in levels:
            pot = sum(min(p.total_bet, level) - min(p.total_bet, prev)
                      for p in order)
            eligible = [p for p in live if p.total_bet >= level]
            best = max(ranks[p.pid] for p in eligible)
            winners = [p for p in eligible if ranks[p.pid] == best]
            share, rem = divmod(pot, len(winners))
            for w in winners:
                w.stack += share
            winners[0].stack += rem
            prev = level
