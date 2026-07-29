"""Texas Hold'em tournament engine.

Cards are ints 0..51: rank = card >> 2 (0 => deuce ... 12 => ace),
suit = card & 3. Supports blinds, escalating blind levels, all-ins,
side pots, split pots and uncalled-bet refunds.

Strategies only ever see the observation dict built in `_build_obs` —
they never see another player's hole cards or strategy object, so no
player "knows" anyone else's algorithm.
"""

from __future__ import annotations

import random

RANK_NAMES = "23456789TJQKA"


def card_str(c: int) -> str:
    return RANK_NAMES[c >> 2] + "cdhs"[c & 3]


# ---------------------------------------------------------------------------
# 7-card hand evaluator
# ---------------------------------------------------------------------------

def _straight_high(rank_set):
    """Top rank of the best straight in rank_set, or -1. Wheel returns 3 (the five)."""
    bits = 0
    for r in rank_set:
        bits |= 1 << r
    run = 0b11111
    for high in range(12, 3, -1):
        mask = run << (high - 4)
        if (bits & mask) == mask:
            return high
    wheel = 0b1000000001111
    if (bits & wheel) == wheel:  # A-2-3-4-5
        return 3
    return -1


def evaluate7(cards):
    """Return a comparable tuple ranking the best 5-card hand out of 7 cards.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    counts = [0] * 13
    suits = ([], [], [], [])
    for c in cards:
        counts[c >> 2] += 1
        suits[c & 3].append(c >> 2)

    flush_ranks = None
    for s in range(4):
        if len(suits[s]) >= 5:
            flush_ranks = suits[s]
            break

    if flush_ranks is not None:
        sf = _straight_high(set(flush_ranks))
        if sf >= 0:
            return (8, sf)

    quads = trips = -1
    pairs = []
    for r in range(12, -1, -1):
        n = counts[r]
        if n == 4:
            quads = r
        elif n == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)  # second trips plays as the pair of a full house
        elif n == 2:
            pairs.append(r)

    if quads >= 0:
        kicker = max(r for r in range(13) if counts[r] and r != quads)
        return (7, quads, kicker)
    if trips >= 0 and pairs:
        return (6, trips, pairs[0])
    if flush_ranks is not None:
        return (5,) + tuple(sorted(flush_ranks, reverse=True)[:5])
    st = _straight_high({r for r in range(13) if counts[r]})
    if st >= 0:
        return (4, st)
    singles = [r for r in range(12, -1, -1) if counts[r] == 1]
    if trips >= 0:
        return (3, trips) + tuple(singles[:2])
    if len(pairs) >= 2:
        kicker = max(r for r in range(13) if counts[r] and r not in pairs[:2])
        return (2, pairs[0], pairs[1], kicker)
    if pairs:
        return (1, pairs[0]) + tuple(singles[:3])
    return (0,) + tuple(singles[:5])


# ---------------------------------------------------------------------------
# Monte Carlo equity
# ---------------------------------------------------------------------------

_PREFLOP_CACHE = {}


def preflop_equity(hole, n_opp, rollouts=160):
    """Cached MC equity of a starting hand vs n_opp random hands."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    key = (r1, r2, suited, n_opp)
    hit = _PREFLOP_CACHE.get(key)
    if hit is None:
        rng = random.Random(str(key))
        hit = equity_mc(hole, [], n_opp, rng, rollouts)
        _PREFLOP_CACHE[key] = hit
    return hit


def equity_mc(hole, board, n_opp, rng, rollouts=30):
    """MC estimate of win probability vs n_opp random hands (ties split)."""
    n_opp = max(1, n_opp)
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    score = 0.0
    for _ in range(rollouts):
        sample = rng.sample(deck, 2 * n_opp + need_board)
        full_board = list(board) + sample[:need_board]
        mine = evaluate7(list(hole) + full_board)
        best_opp = None
        for i in range(n_opp):
            opp = sample[need_board + 2 * i:need_board + 2 * i + 2]
            v = evaluate7(opp + full_board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / rollouts


def chen_score(hole):
    """Chen formula for preflop starting-hand strength (max 20 for AA)."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    high = r1 + 2
    if high == 14:
        pts = 10.0
    elif high == 13:
        pts = 8.0
    elif high == 12:
        pts = 7.0
    elif high == 11:
        pts = 6.0
    else:
        pts = high / 2.0
    if r1 == r2:
        pts = max(pts * 2, 5.0)
    if (hole[0] & 3) == (hole[1] & 3):
        pts += 2.0
    gap = r1 - r2 - 1
    if r1 != r2:
        if gap == 1:
            pts -= 1.0
        elif gap == 2:
            pts -= 2.0
        elif gap == 3:
            pts -= 4.0
        elif gap >= 4:
            pts -= 5.0
        if gap <= 1 and high < 12:
            pts += 1.0
    return pts


# ---------------------------------------------------------------------------
# Tournament table
# ---------------------------------------------------------------------------

class Table:
    """One tournament: fixed seats, escalating blinds, play until one player
    holds all the chips."""

    SEATS = 6
    START_STACK = 1000
    BASE_SB = 10
    BLIND_DOUBLE_EVERY = 20  # hands per blind level, keeps tournaments finite
    MAX_HANDS = 2000

    def __init__(self, strategies, rng: random.Random):
        assert len(strategies) == self.SEATS
        self.strategies = strategies
        self.rng = rng
        self.stacks = [self.START_STACK] * self.SEATS
        self.button = rng.randrange(self.SEATS)
        self.hand_no = 0
        self.elimination_order = []  # seats, first busted first
        # Public per-seat stats any observant player could keep from watching
        # the action (no hole cards, no strategy identities).
        self.stats = [
            {"hands": 0, "vpip": 0, "pfr": 0, "allin": 0, "showdowns": 0}
            for _ in range(self.SEATS)
        ]

    # -- helpers ------------------------------------------------------------

    def _alive(self):
        return [s for s in range(self.SEATS) if self.stacks[s] > 0]

    def _next_alive(self, seat):
        s = seat
        while True:
            s = (s + 1) % self.SEATS
            if self.stacks[s] > 0:
                return s

    def _blinds(self):
        sb = self.BASE_SB * (2 ** (self.hand_no // self.BLIND_DOUBLE_EVERY))
        sb = min(sb, 4 * self.START_STACK)
        return sb, 2 * sb

    # -- one hand -----------------------------------------------------------

    def play_hand(self):
        self.hand_no += 1
        alive = self._alive()
        n = len(alive)
        self.button = self._next_alive(self.button)
        sb_amt, bb_amt = self._blinds()

        # Acting order for the whole hand, starting left of the button.
        order = []
        s = self.button
        for _ in range(n):
            s = self._next_alive(s)
            order.append(s)
        if n == 2:
            sb_seat, bb_seat = self.button, order[0]
            preflop_order = [sb_seat, bb_seat]
            postflop_order = [bb_seat, sb_seat]
        else:
            sb_seat, bb_seat = order[0], order[1]
            preflop_order = order[2:] + order[:2]
            postflop_order = order

        self.in_hand = {s: True for s in alive}
        self.all_in = {s: False for s in alive}
        self.bet = {s: 0 for s in alive}       # chips in front this street
        self.contrib = {s: 0 for s in alive}   # chips in the pot this hand
        self._put_vpip = set()

        self._commit(sb_seat, sb_amt)
        self._commit(bb_seat, bb_amt)

        deck = list(range(52))
        self.rng.shuffle(deck)
        self.hole = {s: (deck.pop(), deck.pop()) for s in alive}
        self.board = []
        for s in alive:
            self.stats[s]["hands"] += 1

        streets = (("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1))
        for street, n_cards in streets:
            for _ in range(n_cards):
                self.board.append(deck.pop())
            if street == "preflop":
                self._betting_round(street, preflop_order, bb_amt, bb_amt)
            else:
                for s in alive:
                    self.bet[s] = 0
                self._betting_round(street, postflop_order, 0, bb_amt)
            if sum(self.in_hand.values()) == 1:
                break

        self._settle()
        for s in alive:
            if self.stacks[s] == 0:
                self.elimination_order.append(s)

    def _commit(self, seat, amount):
        pay = min(amount, self.stacks[seat])
        self.stacks[seat] -= pay
        self.bet[seat] += pay
        self.contrib[seat] += pay
        if self.stacks[seat] == 0:
            self.all_in[seat] = True
        return pay

    # -- betting ------------------------------------------------------------

    def _betting_round(self, street, order, current_bet, min_raise):
        need = {s for s in order if self.in_hand[s] and not self.all_in[s]}
        if sum(self.in_hand.values()) < 2 or not need:
            return
        # Nobody left to respond to an all-in and no bet outstanding: run out.
        if len(need) == 1 and current_bet <= self.bet[next(iter(need))]:
            live_opps = sum(
                1 for s in order if self.in_hand[s] and s not in need
            )
            if live_opps == 0:
                return

        idx = 0
        while need:
            seat = order[idx % len(order)]
            idx += 1
            if seat not in need:
                continue
            if sum(self.in_hand.values()) == 1:
                return
            need.discard(seat)

            obs = self._build_obs(seat, street, current_bet, min_raise)
            action, amount = self.strategies[seat].act(obs)
            to_call = current_bet - self.bet[seat]

            if action == "fold":
                if to_call > 0:
                    self.in_hand[seat] = False
                continue  # a "fold" facing no bet is a check

            if action == "raise":
                target = min(int(amount), self.bet[seat] + self.stacks[seat])
                if target <= current_bet:
                    action = "call"
                else:
                    self._commit(seat, target - self.bet[seat])
                    self._record_voluntary(seat, street, raised=True)
                    raise_size = self.bet[seat] - current_bet
                    current_bet = self.bet[seat]
                    min_raise = max(min_raise, raise_size)
                    need = {
                        s for s in order
                        if self.in_hand[s] and not self.all_in[s] and s != seat
                    }
                    continue

            # call / check
            if to_call > 0:
                self._commit(seat, to_call)
                self._record_voluntary(seat, street, raised=False)

    def _record_voluntary(self, seat, street, raised):
        if street == "preflop" and seat not in self._put_vpip:
            self._put_vpip.add(seat)
            self.stats[seat]["vpip"] += 1
        if raised and street == "preflop":
            self.stats[seat]["pfr"] += 1
        if self.all_in[seat]:
            self.stats[seat]["allin"] += 1

    def _build_obs(self, seat, street, current_bet, min_raise):
        opp_stats = {
            s: dict(self.stats[s])
            for s in self.in_hand
            if s != seat and self.in_hand[s]
        }
        order_alive = sum(self.in_hand.values())
        return {
            "seat": seat,
            "street": street,
            "hole": self.hole[seat],
            "board": tuple(self.board),
            "pot": sum(self.contrib.values()),
            "current_bet": current_bet,
            "my_bet": self.bet[seat],
            "to_call": current_bet - self.bet[seat],
            "min_raise": min_raise,
            "stack": self.stacks[seat],
            "big_blind": self._blinds()[1],
            "n_in_hand": order_alive,
            "n_players": len(self._alive()) or 1,
            "opp_stats": opp_stats,
            "hand_no": self.hand_no,
        }

    # -- settlement ---------------------------------------------------------

    def _settle(self):
        live = [s for s in self.contrib if self.in_hand[s]]

        # Refund any uncalled portion of the top bet.
        top = max(live, key=lambda s: self.contrib[s])
        others = [self.contrib[s] for s in self.contrib if s != top]
        cap = max(others) if others else 0
        if self.contrib[top] > cap:
            refund = self.contrib[top] - cap
            self.contrib[top] -= refund
            self.stacks[top] += refund

        if len(live) == 1:
            self.stacks[live[0]] += sum(self.contrib.values())
            return

        for s in live:
            self.stats[s]["showdowns"] += 1
        scores = {s: evaluate7(list(self.hole[s]) + self.board) for s in live}

        levels = sorted({self.contrib[s] for s in self.contrib if self.contrib[s] > 0})
        prev = 0
        for level in levels:
            pot = sum(
                min(c, level) - prev
                for c in self.contrib.values()
                if c > prev
            )
            eligible = [s for s in live if self.contrib[s] >= level]
            prev = level
            if pot == 0 or not eligible:
                continue
            best = max(scores[s] for s in eligible)
            winners = [s for s in eligible if scores[s] == best]
            share, odd = divmod(pot, len(winners))
            # Deterministic odd-chip assignment: first winner left of button.
            winners.sort(key=lambda s: (s - self.button - 1) % self.SEATS)
            for i, w in enumerate(winners):
                self.stacks[w] += share + (1 if i < odd else 0)

    # -- tournament loop ----------------------------------------------------

    def run(self):
        """Play until one seat has all the chips. Returns the winning seat."""
        while len(self._alive()) > 1 and self.hand_no < self.MAX_HANDS:
            self.play_hand()
        alive = self._alive()
        winner = max(alive, key=lambda s: self.stacks[s])
        for s in sorted(alive, key=lambda s: self.stacks[s]):
            if s != winner:
                self.elimination_order.append(s)
        return winner
