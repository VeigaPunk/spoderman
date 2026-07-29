"""
No-limit Texas Hold'em tournament engine (6-max), pure stdlib.

Rules implemented:
  - Rotating dealer button, small/big blinds (heads-up: button posts SB).
  - Four betting streets (preflop/flop/turn/river) with min-raise tracking.
  - All-ins, side pots via contribution layering, split pots.
  - Escalating blind levels so every tournament terminates.
  - Players are eliminated at 0 chips; last player standing wins.

Information hygiene: strategies receive only a TableView (public info +
their own hole cards) and a stream of public action events. No strategy
ever sees another strategy's code, cards, or reasoning.
"""

import random
from collections import Counter, deque
from functools import lru_cache
from itertools import combinations

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"
FULL_DECK = tuple((r, s) for r in range(2, 15) for s in range(4))

HAND_NAMES = [
    "high card", "pair", "two pair", "trips", "straight",
    "flush", "full house", "quads", "straight flush",
]


def card_str(card):
    r, s = card
    return RANK_CHARS[r - 2] + SUIT_CHARS[s]


@lru_cache(maxsize=1_000_000)
def eval5(cards):
    """Score a 5-card hand as a comparable tuple (category, tiebreakers...)."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    rc = Counter(ranks)
    uniq = sorted(rc, reverse=True)

    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:  # wheel
            straight_high = 5

    by_count = sorted(rc.items(), key=lambda kv: (-kv[1], -kv[0]))
    shape = sorted(rc.values(), reverse=True)

    if flush and straight_high:
        return (8, straight_high)
    if shape[0] == 4:
        return (7, by_count[0][0], by_count[1][0])
    if shape == [3, 2]:
        return (6, by_count[0][0], by_count[1][0])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if shape[0] == 3:
        return (3, by_count[0][0], by_count[1][0], by_count[2][0])
    if shape == [2, 2, 1]:
        return (2, by_count[0][0], by_count[1][0], by_count[2][0])
    if shape[0] == 2:
        return (1, by_count[0][0], by_count[1][0], by_count[2][0], by_count[3][0])
    return (0, *ranks)


def best7(cards):
    """Best 5-card score from 5, 6, or 7 cards."""
    cards = tuple(sorted(cards))
    return max(eval5(combo) for combo in combinations(cards, 5))


class TableView:
    """Everything a strategy is allowed to know at decision time."""

    __slots__ = (
        "pid", "hole", "board", "street", "pot", "to_call", "current_bet",
        "min_raise_to", "my_stack", "my_street_commit", "my_total_commit",
        "small_blind", "big_blind", "stacks", "live_pids", "num_live",
        "num_actors", "pos_frac", "history", "raises_this_street",
    )


class PlayerState:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack
        self.hole = None
        self.folded = False
        self.all_in = False
        self.street_commit = 0
        self.total_commit = 0

    def reset_for_hand(self):
        self.hole = None
        self.folded = False
        self.all_in = False
        self.street_commit = 0
        self.total_commit = 0


class Tournament:
    def __init__(self, entries, start_stack=200, hands_per_level=30,
                 max_hands=2000, rng=None, first_button=0):
        """entries: ordered list of (pid, strategy)."""
        self.players = [PlayerState(pid, strat, start_stack) for pid, strat in entries]
        self.start_stack = start_stack
        self.total_chips = start_stack * len(self.players)
        self.blind_levels = [(1, 2), (2, 4), (3, 6), (5, 10), (8, 16), (12, 24),
                             (20, 40), (30, 60), (50, 100), (75, 150), (100, 200)]
        self.hands_per_level = hands_per_level
        self.max_hands = max_hands
        self.rng = rng or random.Random()
        self.button_seat = first_button % len(self.players)
        self.hand_no = 0
        self.finish_order = []  # pids in order of elimination (first out first)

    # ------------------------------------------------------------------ utils

    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def blinds(self):
        level = min(self.hand_no // self.hands_per_level, len(self.blind_levels) - 1)
        return self.blind_levels[level]

    def broadcast(self, event):
        for p in self.players:
            if p.stack > 0 or not p.folded:
                p.strategy.observe(event)

    # ------------------------------------------------------------------ hand

    def play_hand(self):
        alive = self.alive()
        n = len(alive)
        if n < 2:
            return
        self.hand_no += 1
        sb_amt, bb_amt = self.blinds()

        # Advance button to the next living seat.
        seats = [i for i, p in enumerate(self.players) if p.stack > 0]
        nxt = [s for s in seats if s > self.button_seat]
        self.button_seat = nxt[0] if nxt else seats[0]
        btn_idx = seats.index(self.button_seat)
        ring_seats = seats[btn_idx:] + seats[:btn_idx]  # button first
        ring = [self.players[s] for s in ring_seats]

        for p in ring:
            p.reset_for_hand()

        if n == 2:
            sb_p, bb_p = ring[0], ring[1]          # heads-up: button is SB
            postflop_ring = [bb_p, sb_p]
        else:
            sb_p, bb_p = ring[1], ring[2]
            postflop_ring = ring[1:] + ring[:1]    # SB first, button last

        self.broadcast({"type": "hand_start", "hand_no": self.hand_no,
                        "pids": [p.pid for p in ring],
                        "button": ring[0].pid, "sb": sb_p.pid, "bb": bb_p.pid,
                        "blinds": (sb_amt, bb_amt)})

        history = []

        def commit(p, amount):
            amount = min(amount, p.stack)
            p.stack -= amount
            p.street_commit += amount
            p.total_commit += amount
            if p.stack == 0:
                p.all_in = True
            return amount

        for p, amt in ((sb_p, sb_amt), (bb_p, bb_amt)):
            paid = commit(p, amt)
            history.append(("preflop", p.pid, "blind", paid))
            self.broadcast({"type": "action", "street": "preflop", "pid": p.pid,
                            "action": "blind", "amount": paid, "all_in": p.all_in})

        deck = list(FULL_DECK)
        self.rng.shuffle(deck)
        for p in ring:
            p.hole = (deck.pop(), deck.pop())

        board = []
        streets = (("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1))
        for street, n_cards in streets:
            board.extend(deck.pop() for _ in range(n_cards))
            live = [p for p in ring if not p.folded]
            if len(live) == 1:
                break
            if street == "preflop":
                order = ring[3:] + ring[:3] if n > 2 else [ring[0], ring[1]]
            else:
                for p in ring:
                    p.street_commit = 0
                order = [p for p in postflop_ring]
            self._betting_round(street, ring, order, board, history,
                                bb_amt, sb_amt, preflop=(street == "preflop"))

        self._settle(ring, board)

        busted = [p for p in ring if p.stack == 0]
        # Simultaneous busts: bigger stack entering the hand finishes higher,
        # i.e. is eliminated later in the ordering.
        busted.sort(key=lambda p: p.total_commit)
        for p in busted:
            self.finish_order.append(p.pid)
            self.broadcast({"type": "elimination", "pid": p.pid,
                            "hand_no": self.hand_no})

        assert sum(p.stack for p in self.players) == self.total_chips, \
            "chip conservation violated"

    # ---------------------------------------------------------------- betting

    def _betting_round(self, street, ring, order, board, history, bb_amt, sb_amt,
                       preflop):
        current_bet = max((p.street_commit for p in ring), default=0)
        last_inc = bb_amt
        actors = [p for p in order if not p.folded and not p.all_in]
        needs_action = any(current_bet - p.street_commit > 0 for p in actors)
        if len(actors) < 2 and not needs_action:
            return
        pending = deque(actors)
        raises_this_street = 0
        guard = 0

        while pending:
            guard += 1
            if guard > 1000:
                raise RuntimeError("betting round failed to terminate")
            p = pending.popleft()
            if p.folded or p.all_in:
                continue
            live = [q for q in ring if not q.folded]
            if len(live) == 1:
                return
            to_call = current_bet - p.street_commit
            open_actors = [q for q in live if not q.all_in]
            if to_call <= 0 and len(open_actors) < 2:
                # Nobody left who could call a bet; betting is moot.
                history.append((street, p.pid, "check", 0))
                continue

            view = self._make_view(p, street, ring, order, board, history,
                                   current_bet, last_inc, to_call,
                                   sb_amt, bb_amt, raises_this_street)
            try:
                action, amount = p.strategy.act(view)
            except Exception:
                action, amount = ("fold", 0)

            max_total = p.street_commit + p.stack
            min_raise_to = current_bet + last_inc

            if action == "raise":
                target = max(0, min(int(amount), max_total))
                if target <= current_bet:
                    action = "call"
                elif target < min_raise_to and target < max_total:
                    # Undersized non-all-in raise: bump to min raise if
                    # affordable, otherwise flatten to a call.
                    if min_raise_to <= max_total:
                        target = min_raise_to
                    else:
                        action = "call"

            if action == "raise":
                paid = target - p.street_commit
                p.stack -= paid
                p.street_commit = target
                p.total_commit += paid
                if p.stack == 0:
                    p.all_in = True
                last_inc = max(last_inc, target - current_bet)
                current_bet = target
                raises_this_street += 1
                label = "allin_raise" if p.all_in else "raise"
                history.append((street, p.pid, label, target))
                self.broadcast({"type": "action", "street": street, "pid": p.pid,
                                "action": "raise", "amount": target,
                                "all_in": p.all_in})
                for q in order:
                    if (q is not p and not q.folded and not q.all_in
                            and q not in pending):
                        pending.append(q)
            elif action == "fold" and to_call > 0:
                p.folded = True
                history.append((street, p.pid, "fold", 0))
                self.broadcast({"type": "action", "street": street, "pid": p.pid,
                                "action": "fold", "amount": 0, "all_in": False})
            else:  # call / check (a "fold" facing no bet is a check)
                paid = min(to_call, p.stack)
                p.stack -= paid
                p.street_commit += paid
                p.total_commit += paid
                if p.stack == 0:
                    p.all_in = True
                label = "check" if paid == 0 else "call"
                history.append((street, p.pid, label, paid))
                self.broadcast({"type": "action", "street": street, "pid": p.pid,
                                "action": label, "amount": paid,
                                "all_in": p.all_in})

    def _make_view(self, p, street, ring, order, board, history,
                   current_bet, last_inc, to_call, sb_amt, bb_amt,
                   raises_this_street):
        v = TableView()
        v.pid = p.pid
        v.hole = p.hole
        v.board = tuple(board)
        v.street = street
        v.pot = sum(q.total_commit for q in ring)
        v.to_call = max(0, to_call)
        v.current_bet = current_bet
        v.min_raise_to = current_bet + last_inc
        v.my_stack = p.stack
        v.my_street_commit = p.street_commit
        v.my_total_commit = p.total_commit
        v.small_blind = sb_amt
        v.big_blind = bb_amt
        v.stacks = {q.pid: q.stack for q in ring}
        v.live_pids = [q.pid for q in ring if not q.folded]
        v.num_live = len(v.live_pids)
        open_order = [q for q in order if not q.folded and not q.all_in]
        v.num_actors = len(open_order)
        if p in open_order and len(open_order) > 1:
            v.pos_frac = open_order.index(p) / (len(open_order) - 1)
        else:
            v.pos_frac = 1.0
        v.history = tuple(history)
        v.raises_this_street = raises_this_street
        return v

    # ---------------------------------------------------------------- payout

    def _settle(self, ring, board):
        live = [p for p in ring if not p.folded]
        remaining = {p.pid: p.total_commit for p in ring}
        by_pid = {p.pid: p for p in ring}

        if len(live) == 1:
            live[0].stack += sum(remaining.values())
            return

        while len(board) < 5:  # everyone all-in early: board was dealt in play_hand
            break

        scores = {p.pid: best7(p.hole + tuple(board)) for p in live}
        self.broadcast({"type": "showdown",
                        "reveals": [(p.pid, tuple(map(card_str, p.hole)))
                                    for p in live]})

        while True:
            positive = [pid for pid, v in remaining.items() if v > 0]
            if not positive:
                break
            layer = min(remaining[pid] for pid in positive)
            pot = layer * len(positive)
            for pid in positive:
                remaining[pid] -= layer
            eligible = [p for p in live if p.pid in positive]
            if not eligible:  # layer funded only by folders -> best live hand
                eligible = live
            best = max(scores[p.pid] for p in eligible)
            winners = [p for p in eligible if scores[p.pid] == best]
            share, odd = divmod(pot, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < odd else 0)

    # ------------------------------------------------------------------- run

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        alive = self.alive()
        if len(alive) > 1:  # hit the hand cap: rank by stack
            alive.sort(key=lambda p: (p.stack, self.rng.random()))
            for p in alive[:-1]:
                self.finish_order.append(p.pid)
            alive = [alive[-1]]
        winner = alive[0]
        self.finish_order.append(winner.pid)
        places = {pid: len(self.players) - i
                  for i, pid in enumerate(self.finish_order)}
        return {"winner": winner.pid, "hands": self.hand_no, "places": places}
