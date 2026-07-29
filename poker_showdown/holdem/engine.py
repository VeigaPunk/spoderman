"""No-limit Texas Hold'em tournament engine.

Strategies only ever see public information (their own hole cards, the board,
stacks, bets, and the public action log) — no strategy can see another
player's cards or code, so nobody knows anybody's algorithm.
"""

import random

from .evaluator import evaluate7


class PlayerState:
    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack
        # per-hand state
        self.hole = None
        self.in_hand = False
        self.all_in = False
        self.street_commit = 0
        self.total_commit = 0


class Table:
    def __init__(self, players, rng: random.Random, sb=10, bb=20,
                 blind_double_every=25):
        self.players = players  # list[PlayerState], seat order
        self.rng = rng
        self.base_sb = sb
        self.base_bb = bb
        self.blind_double_every = blind_double_every
        self.hand_no = 0
        self.button = 0
        self.finish_order = []  # seats, first busted first

    # ---------------------------------------------------------------- helpers
    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def _next_alive(self, seat):
        n = len(self.players)
        i = (seat + 1) % n
        while self.players[i].stack <= 0 and i != seat:
            i = (i + 1) % n
        return i

    def _broadcast(self, event):
        for p in self.players:
            if p.stack > 0 or p.in_hand:
                p.strategy.observe(event)

    def blinds(self):
        mult = 2 ** (self.hand_no // self.blind_double_every)
        return self.base_sb * mult, self.base_bb * mult

    # ------------------------------------------------------------------ hand
    def play_hand(self):
        alive = self.alive()
        if len(alive) < 2:
            return
        self.hand_no += 1
        sb_amt, bb_amt = self.blinds()

        for p in self.players:
            p.hole = None
            p.in_hand = False
            p.all_in = False
            p.street_commit = 0
            p.total_commit = 0

        # positions (heads-up: button posts the small blind)
        if len(alive) == 2:
            sb_seat = self.button if self.players[self.button].stack > 0 \
                else self._next_alive(self.button)
            bb_seat = self._next_alive(sb_seat)
        else:
            sb_seat = self._next_alive(self.button)
            bb_seat = self._next_alive(sb_seat)

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in alive:
            p.in_hand = True
            p.hole = (deck.pop(), deck.pop())
        board = []

        self._broadcast({"type": "hand_start", "hand": self.hand_no,
                         "button": self.button, "bb": bb_amt,
                         "stacks": {p.seat: p.stack for p in alive}})

        self._pay(self.players[sb_seat], min(sb_amt, self.players[sb_seat].stack))
        self._pay(self.players[bb_seat], min(bb_amt, self.players[bb_seat].stack))

        streets = [("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)]
        for street, ncards in streets:
            for _ in range(ncards):
                board.append(deck.pop())
            if street == "preflop":
                first = self._next_alive(bb_seat)
                current_bet = max(p.street_commit for p in self.players)
                current_bet = max(current_bet, bb_amt)
            else:
                for p in self.players:
                    p.street_commit = 0
                first = self._next_alive(self.button)
                current_bet = 0
            self._betting_round(street, board, first, current_bet, bb_amt)
            if len([p for p in self.players if p.in_hand]) <= 1:
                break

        self._award_pots(board)
        self._check_eliminations()
        self.button = self._next_alive(self.button)

    def _pay(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_commit += amount
        p.total_commit += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    # -------------------------------------------------------------- betting
    def _betting_round(self, street, board, first_seat, current_bet, bb_amt):
        in_hand = [p for p in self.players if p.in_hand]
        actionable = [p for p in in_hand if not p.all_in]
        if len(in_hand) <= 1:
            return
        if not actionable:
            return
        if len(actionable) == 1 and current_bet <= actionable[0].street_commit:
            return

        last_raise = bb_amt

        def order_from(seat):
            out = []
            i = seat
            for _ in range(len(self.players)):
                p = self.players[i]
                if p.in_hand and not p.all_in:
                    out.append(p)
                i = (i + 1) % len(self.players)
            return out

        pending = order_from(first_seat)
        while pending:
            p = pending.pop(0)
            if not p.in_hand or p.all_in:
                continue
            if len([q for q in self.players if q.in_hand]) <= 1:
                break
            to_call = current_bet - p.street_commit
            obs = self._observation(p, street, board, current_bet,
                                    last_raise, bb_amt)
            action = p.strategy.act(obs)

            kind = action[0]
            if kind == "raise":
                target = int(action[1])
                max_to = p.street_commit + p.stack
                target = min(target, max_to)
                min_to = current_bet + last_raise
                if target < min_to and target < max_to:
                    # illegal undersized raise that isn't all-in: bump or downgrade
                    target = min(min_to, max_to)
                if target <= current_bet:
                    kind = "call"
                else:
                    paid = self._pay(p, target - p.street_commit)
                    if p.street_commit >= current_bet + last_raise:
                        last_raise = p.street_commit - current_bet
                    current_bet = p.street_commit
                    self._broadcast({"type": "action", "hand": self.hand_no,
                                     "street": street, "seat": p.seat,
                                     "action": "raise", "to": current_bet,
                                     "paid": paid, "all_in": p.all_in,
                                     "facing_bet": to_call > 0})
                    rest = order_from(self._next_alive(p.seat))
                    pending = [q for q in rest if q is not p]
                    continue
            if kind == "fold":
                if to_call <= 0:
                    kind = "call"  # never fold when checking is free
                else:
                    p.in_hand = False
                    self._broadcast({"type": "action", "hand": self.hand_no,
                                     "street": street, "seat": p.seat,
                                     "action": "fold", "all_in": False,
                                     "facing_bet": True})
                    continue
            # call / check
            paid = self._pay(p, max(to_call, 0))
            self._broadcast({"type": "action", "hand": self.hand_no,
                             "street": street, "seat": p.seat,
                             "action": "call" if to_call > 0 else "check",
                             "paid": paid, "all_in": p.all_in,
                             "facing_bet": to_call > 0})

        # refund any uncalled portion of the highest bet
        commits = sorted((q.street_commit for q in self.players), reverse=True)
        if len(commits) >= 2 and commits[0] > commits[1]:
            top = max((q for q in self.players if q.in_hand),
                      key=lambda q: q.street_commit, default=None)
            if top and top.street_commit == commits[0]:
                refund = commits[0] - commits[1]
                top.stack += refund
                top.street_commit -= refund
                top.total_commit -= refund
                if top.stack > 0:
                    top.all_in = False

    def _observation(self, p, street, board, current_bet, last_raise, bb_amt):
        pot = sum(q.total_commit for q in self.players)
        to_call = max(0, current_bet - p.street_commit)
        aggressor = None
        aggressor_all_in = False
        if current_bet > 0:
            for q in self.players:
                if q.in_hand and q.street_commit == current_bet and q is not p:
                    aggressor = q.seat
                    aggressor_all_in = q.all_in
                    break
        in_hand = [q for q in self.players if q.in_hand]
        # players still to act behind me this street
        behind = 0
        i = self._next_alive(p.seat)
        while i != p.seat:
            q = self.players[i]
            if q.in_hand and not q.all_in and q.street_commit < max(current_bet, 1):
                behind += 1
            if i == self.button:
                break
            i = self._next_alive(i)
        return {
            "street": street,
            "hole": p.hole,
            "board": tuple(board) if street != "preflop" else tuple(),
            "pot": pot,
            "to_call": min(to_call, p.stack),
            "current_bet": current_bet,
            "min_raise_to": current_bet + last_raise,
            "my_stack": p.stack,
            "my_street_commit": p.street_commit,
            "my_total_commit": p.total_commit,
            "my_seat": p.seat,
            "button": self.button,
            "bb": bb_amt,
            "n_in_hand": len(in_hand),
            "n_alive": len(self.alive()),
            "players_behind": behind,
            "aggressor_seat": aggressor,
            "aggressor_all_in": aggressor_all_in,
            "opponents": [{"seat": q.seat, "stack": q.stack,
                           "street_commit": q.street_commit,
                           "in_hand": q.in_hand, "all_in": q.all_in}
                          for q in self.players if q is not p and
                          (q.stack > 0 or q.in_hand)],
            "hand_no": self.hand_no,
            "rng": self.rng,
        }

    # -------------------------------------------------------------- payouts
    def _award_pots(self, board):
        in_hand = [p for p in self.players if p.in_hand]
        remaining = {p.seat: p.total_commit for p in self.players}
        total = sum(remaining.values())
        if len(in_hand) == 1:
            in_hand[0].stack += total
            return

        scores = {p.seat: evaluate7(list(p.hole) + list(board)) for p in in_hand}
        self._broadcast({"type": "showdown", "hand": self.hand_no,
                         "board": tuple(board),
                         "holes": {p.seat: p.hole for p in in_hand}})

        pots = []  # (amount, eligible_seats)
        while True:
            live = [remaining[p.seat] for p in in_hand if remaining[p.seat] > 0]
            if not live:
                break
            level = min(live)
            eligible = [p.seat for p in in_hand if remaining[p.seat] > 0]
            amount = 0
            for seat, c in remaining.items():
                take = min(c, level)
                amount += take
                remaining[seat] -= take
            pots.append((amount, eligible))
        leftover = sum(remaining.values())  # over-contributions from folders
        if leftover and pots:
            pots[-1] = (pots[-1][0] + leftover, pots[-1][1])

        seat_of = {p.seat: p for p in self.players}
        for amount, eligible in pots:
            best = max(scores[s] for s in eligible)
            winners = [s for s in eligible if scores[s] == best]
            # order winners from left of button for odd-chip distribution
            ordered = sorted(winners,
                             key=lambda s: (s - self.button - 1) % len(self.players))
            share = amount // len(winners)
            extra = amount - share * len(winners)
            for i, s in enumerate(ordered):
                seat_of[s].stack += share + (1 if i < extra else 0)

    def _check_eliminations(self):
        busted = [p for p in self.players
                  if p.stack <= 0 and p.seat not in self.finish_order]
        # players with more chips at hand start bust "later" (better finish);
        # ties broken by seat distance from the button
        busted.sort(key=lambda p: p.total_commit)
        for p in busted:
            self.finish_order.append(p.seat)


def run_tournament(make_players, seed, start_stack=2000, sb=10, bb=20,
                   blind_double_every=25, max_hands=3000):
    """make_players(rng) -> list[(name, strategy)]. Returns finish order of
    seats, last entry is the winner."""
    rng = random.Random(seed)
    entries = make_players(rng)
    players = [PlayerState(i, name, strat, start_stack)
               for i, (name, strat) in enumerate(entries)]
    table = Table(players, rng, sb=sb, bb=bb,
                  blind_double_every=blind_double_every)
    while len(table.alive()) > 1 and table.hand_no < max_hands:
        table.play_hand()
    survivors = sorted(table.alive(), key=lambda p: p.stack)
    return table.finish_order + [p.seat for p in survivors], table.hand_no
