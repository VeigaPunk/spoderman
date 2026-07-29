"""No-Limit Texas Hold'em tournament engine.

Supports blinds (with escalation), betting rounds, all-ins for less,
side pots, and plays a table down to a single winner. Strategies only see
public information plus their own hole cards.
"""

import random
from collections import deque

from .cards import estimate_equity, evaluate7


class PlayerState:
    def __init__(self, name, strategy, stack):
        self.name = name
        self.strategy = strategy
        self.stack = stack
        # per-hand state
        self.hole = None
        self.folded = False
        self.all_in = False
        self.committed_street = 0   # chips put in during the current street
        self.committed_hand = 0     # chips put in during the whole hand


class Tournament:
    def __init__(self, strategies, names, starting_stack=200, small_blind=1,
                 blind_double_every=10, max_hands=1000, rng=None):
        assert len(strategies) == len(names)
        self.rng = rng or random.Random()
        self.players = [PlayerState(n, s, starting_stack)
                        for n, s in zip(names, strategies)]
        self.small_blind = small_blind
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.hand_no = 0
        self.button = 0

    # ------------------------------------------------------------------ helpers

    def _alive(self):
        return [p for p in self.players if p.stack > 0 or p.committed_hand > 0]

    def _funded(self):
        return [p for p in self.players if p.stack > 0]

    def _seats_in_order(self, group, start_after):
        """Players from `group` ordered clockwise starting after seat `start_after`."""
        n = len(self.players)
        order = []
        for i in range(1, n + 1):
            p = self.players[(start_after + i) % n]
            if p in group:
                order.append(p)
        return order

    def _blinds(self):
        level = self.hand_no // self.blind_double_every
        sb = self.small_blind * (2 ** min(level, 12))
        return sb, sb * 2

    # ------------------------------------------------------------------ one hand

    def play_hand(self):
        alive = self._funded()
        if len(alive) < 2:
            return
        self.hand_no += 1
        sb_amt, bb_amt = self._blinds()

        for p in alive:
            p.folded = False
            p.all_in = False
            p.committed_street = 0
            p.committed_hand = 0

        # advance button to next funded seat
        n = len(self.players)
        for i in range(1, n + 1):
            idx = (self.button + i) % n
            if self.players[idx] in alive:
                self.button = idx
                break

        order_after_btn = self._seats_in_order(alive, self.button)
        if len(alive) == 2:  # heads-up: button posts the small blind
            sb_p, bb_p = self.players[self.button], order_after_btn[0]
        else:
            sb_p, bb_p = order_after_btn[0], order_after_btn[1]

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in alive:
            p.hole = (deck.pop(), deck.pop())
        board = []

        history = []  # public log: (name, street, action, amount)

        def post(p, amount):
            amount = min(amount, p.stack)
            p.stack -= amount
            p.committed_street += amount
            p.committed_hand += amount
            if p.stack == 0:
                p.all_in = True
            return amount

        post(sb_p, sb_amt)
        post(bb_p, bb_amt)
        history.append((sb_p.name, "preflop", "smallblind", sb_p.committed_street))
        history.append((bb_p.name, "preflop", "bigblind", bb_p.committed_street))

        def in_hand():
            return [p for p in alive if not p.folded]

        def notify(actor, street, action, amount, to_call):
            history.append((actor.name, street, action, amount))
            for p in alive:
                fn = getattr(p.strategy, "observe_action", None)
                if fn:
                    fn(actor.name, street, action, amount, to_call,
                       actor.all_in, bb_amt)

        def betting_round(street, first_after_seat, current_bet, min_raise):
            queue = deque(p for p in self._seats_in_order(in_hand(), first_after_seat)
                          if not p.all_in)
            guard = 0
            while queue and guard < 1000:
                guard += 1
                if len(in_hand()) == 1:
                    break
                p = queue.popleft()
                if p.folded or p.all_in:
                    continue
                to_call = current_bet - p.committed_street
                pot = sum(q.committed_hand for q in alive)
                view = {
                    "street": street,
                    "hole": p.hole,
                    "board": tuple(board),
                    "pot": pot,
                    "to_call": to_call,
                    "current_bet": current_bet,
                    "min_raise": min_raise,
                    "my_committed": p.committed_street,
                    "stack": p.stack,
                    "big_blind": bb_amt,
                    "num_in_hand": len(in_hand()),
                    "num_opponents": len(in_hand()) - 1,
                    "stacks": {q.name: q.stack for q in alive},
                    "history": tuple(history),
                    "my_name": p.name,
                    "rng": self.rng,
                    "equity": (lambda samples=30, _p=p:
                               estimate_equity(_p.hole, board,
                                               max(1, len(in_hand()) - 1),
                                               self.rng, samples)),
                }
                action, amount = p.strategy.act(view)

                if action == "fold" and to_call == 0:
                    action = "call"  # never fold when checking is free
                if action == "fold":
                    p.folded = True
                    notify(p, street, "fold", 0, to_call)
                    continue
                if action != "raise":
                    paid = post(p, to_call)
                    notify(p, street, "call" if to_call else "check", paid, to_call)
                    continue
                # raise: `amount` is the desired total committed for this street
                target = max(amount, current_bet + min_raise)
                target = min(target, p.committed_street + p.stack)
                if target <= current_bet:  # can't actually raise -> call all-in
                    paid = post(p, to_call)
                    notify(p, street, "call" if to_call else "check", paid, to_call)
                    continue
                raise_size = target - current_bet
                post(p, target - p.committed_street)
                current_bet = p.committed_street
                if raise_size >= min_raise:
                    min_raise = raise_size
                notify(p, street, "raise", current_bet, to_call)
                # everyone else still in the hand must respond to the raise
                queue = deque(
                    q for q in self._seats_in_order(in_hand(),
                                                    self.players.index(p))
                    if q is not p and not q.all_in)
            return current_bet

        # ---- preflop: action starts left of the big blind
        betting_round("preflop", self.players.index(bb_p), bb_amt, bb_amt)

        # ---- flop / turn / river
        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(in_hand()) < 2:
                break
            for p in alive:
                p.committed_street = 0
            board.extend(deck.pop() for _ in range(n_cards))
            if sum(1 for p in in_hand() if not p.all_in) >= 2:
                betting_round(street, self.button, 0, bb_amt)

        self._distribute(alive, board)

        for p in alive:
            fn = getattr(p.strategy, "hand_finished", None)
            if fn:
                fn({q.name: q.stack for q in self.players})

    def _distribute(self, alive, board):
        contenders = [p for p in alive if not p.folded]
        if len(contenders) == 1:
            contenders[0].stack += sum(p.committed_hand for p in alive)
            return
        # streets always finish dealing before a multi-way showdown
        scores = {p.name: evaluate7(list(p.hole) + list(board)) for p in contenders}
        levels = sorted({p.committed_hand for p in alive if p.committed_hand > 0})
        prev = 0
        for lvl in levels:
            layer = sum(min(p.committed_hand, lvl) - min(p.committed_hand, prev)
                        for p in alive)
            eligible = [p for p in contenders if p.committed_hand >= lvl]
            if not eligible:  # only folded chips at this level
                eligible = contenders
            best = max(scores[p.name] for p in eligible)
            winners = [p for p in eligible if scores[p.name] == best]
            share, rem = divmod(layer, len(winners))
            for j, w in enumerate(winners):
                w.stack += share + (1 if j < rem else 0)
            prev = lvl

    # ------------------------------------------------------------------ run

    def run(self):
        """Play until one player owns all the chips. Returns (winner, hands)."""
        for p in self.players:
            fn = getattr(p.strategy, "reset", None)
            if fn:
                fn(p.name, [q.name for q in self.players])
        while len(self._funded()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        winner = max(self.players, key=lambda p: p.stack)
        return winner.name, self.hand_no
