#!/usr/bin/env python3
"""
No-Limit Texas Hold'em tournament simulator.

Six players, identical starting stacks, escalating blinds, full betting
engine (min-raises, all-ins, side pots, uncalled-bet refunds), played
until one player holds every chip.

Seat 1 runs the simplest possible strategy:

    if my_turn:
        bet = ALL_IN

Seats 2..6 run five elaborate, mutually-unaware strategies. No strategy
can inspect another strategy object -- each one only sees the public
table state (its own hole cards, the board, stacks, pots, and the action
history that any human at the table could also observe).

Usage:
    python3 holdem_sim.py --sims 100 --seed 42
"""

import argparse
import json
import math
import os
import random
from collections import Counter, deque

# ----------------------------------------------------------------------
# Cards & 7-card hand evaluator
# ----------------------------------------------------------------------
RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"


def card_str(c):
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def rank_of(c):
    return c >> 2  # 0 = deuce .. 12 = ace


def suit_of(c):
    return c & 3


def _straight_high(rank_set):
    """Highest straight top-rank in the set, or -1. Ace plays low too."""
    rs = set(rank_set)
    if 12 in rs:
        rs.add(-1)
    best = -1
    for hi in range(12, 2, -1):
        if all(hi - k in rs for k in range(5)):
            best = hi
            break
    return best


def eval7(cards):
    """Evaluate the best 5-card hand from 5-7 cards.

    Returns a comparable tuple; bigger is better.
    Categories: 8 SF, 7 quads, 6 boat, 5 flush, 4 straight,
                3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = [c >> 2 for c in cards]
    suits = [c & 3 for c in cards]

    suit_count = Counter(suits)
    flush_suit = next((s for s, n in suit_count.items() if n >= 5), None)
    if flush_suit is not None:
        franks = sorted((r for r, s in zip(ranks, suits) if s == flush_suit),
                        reverse=True)
        sf = _straight_high(franks)
        if sf >= 0:
            return (8, sf)

    count = Counter(ranks)
    # sort by (multiplicity, rank) descending
    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_suit is not None:
        return (5,) + tuple(franks[:5])

    st = _straight_high(count.keys())
    if st >= 0:
        return (4, st)

    if groups[0][1] == 3:
        trip = groups[0][0]
        kick = sorted((r for r in ranks if r != trip), reverse=True)[:2]
        return (3, trip) + tuple(kick)

    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kicker)

    if groups[0][1] == 2:
        pair = groups[0][0]
        kick = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair) + tuple(kick)

    return (0,) + tuple(sorted(ranks, reverse=True)[:5])


# ----------------------------------------------------------------------
# Shared poker math helpers (public knowledge any player may use)
# ----------------------------------------------------------------------
def chen_score(hole):
    """Bill Chen's preflop hand-strength formula."""
    r1, r2 = sorted((rank_of(hole[0]), rank_of(hole[1])), reverse=True)
    suited = suit_of(hole[0]) == suit_of(hole[1])
    high_pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, high_pts * 2)
    score = high_pts
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # connectors/1-gappers below queen
        score += 1
    return math.ceil(score * 2) / 2.0


def monte_carlo_equity(hole, board, n_opps, iters, rng):
    """Estimated probability of winning at showdown vs n_opps random hands."""
    known = set(hole) | set(board)
    deck = [c for c in range(52) if c not in known]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, need_board + 2 * n_opps)
        full_board = list(board) + draw[:need_board]
        hero = eval7(list(hole) + full_board)
        best_opp = None
        idx = need_board
        for _o in range(n_opps):
            opp = eval7(draw[idx:idx + 2] + full_board)
            idx += 2
            if best_opp is None or opp > best_opp:
                best_opp = opp
        if hero > best_opp:
            wins += 1.0
        elif hero == best_opp:
            wins += 0.5
    return wins / iters


def draw_outs(hole, board):
    """Rough count of clean outs for flush / straight draws."""
    if not board or len(board) >= 5:
        return 0
    cards = list(hole) + list(board)
    outs = 0
    scount = Counter(suit_of(c) for c in cards)
    for s, n in scount.items():
        if n == 4 and any(suit_of(h) == s for h in hole):
            outs += 9
            break
    rset = set(rank_of(c) for c in cards)
    if 12 in rset:
        rset.add(-1)
    if _straight_high(rset) < 0:
        completes = 0
        for add in range(13):
            if add in rset:
                continue
            if _straight_high(rset | {add}) >= 0:
                completes += 1
        if completes >= 2:
            outs += 8   # open-ended (or double gutter)
        elif completes == 1:
            outs += 4   # gutshot
    return outs


def made_strength(hole, board):
    """Heuristic made-hand strength in [0, 1] on the current board."""
    if not board:
        return chen_score(hole) / 20.0
    rank = eval7(list(hole) + list(board))
    cat = rank[0]
    base = [0.08, 0.30, 0.62, 0.70, 0.80, 0.85, 0.92, 0.97, 0.99][cat]
    board_ranks = [rank_of(c) for c in board]
    if cat == 1:
        pair_rank = rank[1]
        hole_ranks = [rank_of(c) for c in hole]
        if pair_rank not in hole_ranks:
            base = 0.15                       # board pair, we have squat
        elif hole_ranks[0] == hole_ranks[1] and pair_rank > max(board_ranks):
            base = 0.55                       # overpair
        elif pair_rank == max(board_ranks):
            base = 0.48                       # top pair
        elif pair_rank < min(board_ranks):
            base = 0.22                       # underpair
    elif cat == 3 and rank[1] in board_ranks and \
            board_ranks.count(rank[1]) >= 3:
        base = 0.45                           # trips entirely on board
    return base


def total_strength(hole, board, street):
    streets_left = {"flop": 2, "turn": 1, "river": 0}.get(street, 0)
    made = made_strength(hole, board)
    draw_eq = min(0.35, draw_outs(hole, board) * 0.02 * streets_left)
    return min(0.99, made + draw_eq * (1.0 - made))


# ----------------------------------------------------------------------
# Strategy base + the six competitors
# ----------------------------------------------------------------------
class Strategy:
    """A strategy sees only public info + its own hole cards via `view`."""

    name = "base"

    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        raise NotImplementedError

    def on_action(self, seat, street, action, amount):
        """Public action feed -- what anyone at the table can observe."""

    def on_hand_end(self, results):
        pass


class AllInBot(Strategy):
    """The requested masterpiece:

        if my_turn:
            bet = ALL_IN
        fi
    """

    name = "SuflairGPT_AllIn"

    def act(self, view):
        return ("raise", view.my_bet + view.stack)  # ALL. IN.


class TagShark(Strategy):
    """Tight-aggressive: Chen-formula ranges, positional awareness,
    continuation bets, pot-odds folds. The textbook grinder."""

    name = "TAG_Shark"

    def __init__(self, rng):
        super().__init__(rng)
        self.was_aggressor = False

    def act(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view.hole)
        late = view.position >= view.players_dealt - 2
        open_thr = 7.0 if late else 8.5
        facing_raise = view.to_call > view.bb
        big_jam = view.to_call >= 8 * view.bb or view.to_call >= view.stack * 0.4

        if big_jam:
            # someone shoved (or close to it): premiums only, by pot odds
            pot_odds = view.to_call / (view.pot + view.to_call)
            eq = monte_carlo_equity(view.hole, view.board, 1, 60, self.rng)
            if eq > pot_odds + 0.05:
                self.was_aggressor = True
                return ("call", 0)
            return ("fold", 0)
        if facing_raise:
            if score >= 10.5:
                self.was_aggressor = True
                return ("raise", max(view.min_raise_to, view.to_call * 3))
            if score >= 8.5:
                return ("call", 0)
            return ("fold", 0)
        if score >= open_thr:
            self.was_aggressor = True
            return ("raise", max(view.min_raise_to, 3 * view.bb))
        if view.to_call == 0:
            return ("check", 0)
        if score >= 6.5 and view.to_call <= 2 * view.bb:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        s = total_strength(view.hole, view.board, view.street)
        pot_odds = view.to_call / (view.pot + view.to_call) if view.to_call else 0.0
        if view.to_call == 0:
            if s > 0.62:
                return ("raise", view.my_bet + int(0.66 * view.pot) + 1)
            if self.was_aggressor and view.street == "flop" and \
                    self.rng.random() < 0.60:
                return ("raise", view.my_bet + int(0.5 * view.pot) + 1)  # c-bet
            return ("check", 0)
        if s > 0.75:
            return ("raise", max(view.min_raise_to,
                                 view.my_bet + view.to_call + view.pot))
        if s > pot_odds + 0.08:
            return ("call", 0)
        return ("fold", 0)


class LagBluffmaster(Strategy):
    """Loose-aggressive: wide opens, 3-bet bluffs, relentless barrels and
    semi-bluffed draws. Feared in position, punished out of it."""

    name = "LAG_Bluffmaster"

    def act(self, view):
        r = self.rng.random()
        if view.street == "preflop":
            score = chen_score(view.hole)
            shove_spot = view.to_call >= view.stack * 0.35
            if shove_spot:
                eq = monte_carlo_equity(view.hole, view.board, 1, 60, self.rng)
                pot_odds = view.to_call / (view.pot + view.to_call)
                return ("call", 0) if eq > pot_odds + 0.02 else ("fold", 0)
            if view.to_call > view.bb:  # facing a raise
                if score >= 9 or (score >= 6 and r < 0.30):
                    return ("raise", max(view.min_raise_to, view.to_call * 3))
                if score >= 6:
                    return ("call", 0)
                return ("fold", 0)
            if score >= 5 or r < 0.25:
                return ("raise", max(view.min_raise_to,
                                     int(2.5 * view.bb)))
            if view.to_call == 0:
                return ("check", 0)
            return ("call", 0) if score >= 4 else ("fold", 0)

        s = total_strength(view.hole, view.board, view.street)
        outs = draw_outs(view.hole, view.board)
        if view.to_call == 0:
            if s > 0.55 or outs >= 8 or r < 0.35:
                return ("raise", view.my_bet + int(0.75 * view.pot) + 1)
            return ("check", 0)
        pot_odds = view.to_call / (view.pot + view.to_call)
        if s > 0.72 or (outs >= 8 and r < 0.5):
            return ("raise", max(view.min_raise_to,
                                 view.my_bet + view.to_call + view.pot))
        if s > pot_odds or (outs >= 4 and pot_odds < 0.25):
            return ("call", 0)
        if r < 0.10 and view.to_call < view.stack * 0.15:
            return ("call", 0)  # sticky float
        return ("fold", 0)


class RockNit(Strategy):
    """Ultra-tight rock with a short-stack push/fold gear. Folds for a
    living, then jams premium equity when the blinds force action."""

    name = "Rock_Nit"

    def act(self, view):
        bbs = view.stack / view.bb if view.bb else 99
        if view.street == "preflop":
            score = chen_score(view.hole)
            if bbs <= 10:  # push/fold mode
                jam_thr = 6.0 if bbs > 6 else 4.5
                if score >= jam_thr:
                    return ("raise", view.my_bet + view.stack)
                if view.to_call == 0:
                    return ("check", 0)
                return ("fold", 0)
            if score >= 11:
                return ("raise", max(view.min_raise_to, 3 * view.bb))
            if score >= 9:
                if view.to_call >= view.stack * 0.35:
                    eq = monte_carlo_equity(view.hole, view.board, 1, 60,
                                            self.rng)
                    pot_odds = view.to_call / (view.pot + view.to_call)
                    return ("call", 0) if eq > pot_odds + 0.04 else ("fold", 0)
                return ("call", 0) if view.to_call else \
                    ("raise", max(view.min_raise_to, 3 * view.bb))
            if view.to_call == 0:
                return ("check", 0)
            return ("fold", 0)

        s = total_strength(view.hole, view.board, view.street)
        if view.to_call == 0:
            if s > 0.68:
                return ("raise", view.my_bet + int(0.6 * view.pot) + 1)
            return ("check", 0)
        pot_odds = view.to_call / (view.pot + view.to_call)
        if s > 0.80:
            return ("raise", max(view.min_raise_to,
                                 view.my_bet + view.to_call + view.pot))
        if s > pot_odds + 0.15:
            return ("call", 0)
        return ("fold", 0)


class EquityNerd(Strategy):
    """The pot-odds mathematician: Monte-Carlo equity vs. price on every
    single decision. Emotionless, unexploitable-ish, slightly face-up."""

    name = "EquityNerd"

    def act(self, view):
        n_opps = max(1, view.players_in_hand - 1)
        iters = 80 if view.street == "preflop" else 100
        eq = monte_carlo_equity(view.hole, view.board, n_opps, iters, self.rng)
        pot = view.pot
        if view.to_call > 0:
            pot_odds = view.to_call / (pot + view.to_call)
            if eq > 0.72 and view.street != "preflop":
                return ("raise", max(view.min_raise_to,
                                     view.my_bet + view.to_call + pot))
            if eq > 0.60 and view.street == "preflop":
                return ("raise", max(view.min_raise_to, view.to_call * 3))
            if eq > pot_odds + 0.03:
                return ("call", 0)
            return ("fold", 0)
        # free look available
        if eq > 0.65:
            return ("raise", view.my_bet + max(view.bb * 2,
                                               int(0.7 * pot)) + 1)
        if eq > 0.5 and self.rng.random() < 0.5:
            return ("raise", view.my_bet + max(view.bb * 2,
                                               int(0.5 * pot)))
        return ("check", 0)


class AdaptiveHustler(Strategy):
    """Exploitative profiler: builds per-seat stats from the public action
    feed (shove frequency, raise frequency, fold-to-raise) and re-tunes
    its thresholds -- tightens vs. maniacs, steals vs. nits, traps the
    all-in guy with premiums only."""

    name = "Adaptive_Hustler"

    def __init__(self, rng):
        super().__init__(rng)
        self.stats = {}  # seat -> Counter

    def _st(self, seat):
        return self.stats.setdefault(seat, Counter())

    def on_action(self, seat, street, action, amount):
        st = self._st(seat)
        st["actions"] += 1
        st[action] += 1
        if action == "allin":
            st["shoves"] += 1

    def _table_mania(self, view):
        """Average shove-happiness of the live opponents."""
        rates = []
        for seat in view.live_opponents:
            st = self._st(seat)
            if st["actions"] >= 8:
                rates.append(st["shoves"] / st["actions"])
        return max(rates) if rates else 0.15

    def act(self, view):
        mania = self._table_mania(view)
        vs_maniac = mania > 0.30
        if view.street == "preflop":
            score = chen_score(view.hole)
            facing_jam = view.to_call >= view.stack * 0.35 or \
                view.to_call >= 8 * view.bb
            if facing_jam:
                # vs a chronic shover, random-hand equity is the truth
                eq = monte_carlo_equity(view.hole, view.board, 1, 90, self.rng)
                pot_odds = view.to_call / (view.pot + view.to_call)
                edge = 0.03 if vs_maniac else 0.08
                return ("call", 0) if eq > pot_odds + edge else ("fold", 0)
            if vs_maniac:
                # flat premium hands to induce the shove behind us
                if score >= 9:
                    return ("call", 0) if view.to_call else \
                        ("raise", max(view.min_raise_to, 2 * view.bb))
                if view.to_call == 0:
                    return ("check", 0)
                return ("fold", 0) if view.to_call > view.bb else \
                    ("call", 0) if score >= 7 else ("fold", 0)
            # vs sane table: steal wide from late position
            late = view.position >= view.players_dealt - 2
            thr = 6.0 if late else 8.0
            if score >= thr and view.to_call <= view.bb:
                return ("raise", max(view.min_raise_to,
                                     int(2.5 * view.bb)))
            if score >= 9 and view.to_call:
                return ("call", 0)
            if view.to_call == 0:
                return ("check", 0)
            return ("fold", 0)

        s = total_strength(view.hole, view.board, view.street)
        pot_odds = view.to_call / (view.pot + view.to_call) \
            if view.to_call else 0.0
        cushion = -0.05 if vs_maniac else 0.08
        if view.to_call == 0:
            if s > (0.70 if vs_maniac else 0.58):
                return ("raise", view.my_bet + int(0.6 * view.pot) + 1)
            return ("check", 0)
        if s > 0.78:
            return ("raise", max(view.min_raise_to,
                                 view.my_bet + view.to_call + view.pot))
        if s > pot_odds + cushion:
            return ("call", 0)
        return ("fold", 0)


# ----------------------------------------------------------------------
# Table engine
# ----------------------------------------------------------------------
class View:
    """Read-only snapshot of public state + the acting player's own cards."""
    __slots__ = ("hole", "board", "street", "pot", "to_call", "my_bet",
                 "min_raise_to", "stack", "bb", "position", "players_dealt",
                 "players_in_hand", "live_opponents")


class Seat:
    def __init__(self, idx, name, strategy):
        self.idx = idx
        self.name = name
        self.strategy = strategy
        self.stack = 0
        self.hole = None
        self.in_hand = False
        self.all_in = False
        self.bet_round = 0
        self.contrib = 0


class Tournament:
    START_STACK = 1000
    SB0, BB0 = 10, 20
    HANDS_PER_LEVEL = 12
    MAX_HANDS = 600

    def __init__(self, strategy_factories, seed):
        self.rng = random.Random(seed)
        self.seats = [
            Seat(i, name, factory(random.Random(seed * 977 + i)))
            for i, (name, factory) in enumerate(strategy_factories)
        ]
        for s in self.seats:
            s.stack = self.START_STACK
        self.button = self.rng.randrange(len(self.seats))
        self.hand_no = 0
        self.finish_order = []  # seat idx, first busted first

    # -- helpers -------------------------------------------------------
    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def blinds(self):
        level = self.hand_no // self.HANDS_PER_LEVEL
        mult = 2 ** min(level, 9)
        return self.SB0 * mult, self.BB0 * mult

    def next_alive(self, idx):
        n = len(self.seats)
        j = idx
        while True:
            j = (j + 1) % n
            if self.seats[j].stack > 0:
                return j

    def order_from(self, start_idx, pool):
        n = len(self.seats)
        out = []
        j = start_idx
        for _ in range(n):
            if self.seats[j] in pool:
                out.append(self.seats[j])
            j = (j + 1) % n
        return out

    def first_after(self, idx, pool):
        """First seat index after `idx` belonging to `pool` (stack-agnostic,
        safe mid-hand when all-in players sit on zero chips)."""
        n = len(self.seats)
        j = idx
        for _ in range(n):
            j = (j + 1) % n
            if self.seats[j] in pool:
                return j
        return idx

    def broadcast(self, actor, street, action, amount):
        for s in self.seats:
            s.strategy.on_action(actor.idx, street, action, amount)

    # -- hand ----------------------------------------------------------
    def play_hand(self):
        self.hand_no += 1
        sb_amt, bb_amt = self.blinds()
        players = self.alive()
        for s in players:
            s.in_hand = True
            s.all_in = False
            s.bet_round = 0
            s.contrib = 0

        btn = self.button
        if len(players) == 2:
            sb_seat = self.seats[btn]
            bb_seat = self.seats[self.next_alive(btn)]
        else:
            sb_seat = self.seats[self.next_alive(btn)]
            bb_seat = self.seats[self.next_alive(sb_seat.idx)]

        for seat, amt in ((sb_seat, sb_amt), (bb_seat, bb_amt)):
            pay = min(amt, seat.stack)
            seat.stack -= pay
            seat.bet_round += pay
            seat.contrib += pay
            if seat.stack == 0:
                seat.all_in = True

        deck = list(range(52))
        self.rng.shuffle(deck)
        for i, s in enumerate(players):
            s.hole = (deck[2 * i], deck[2 * i + 1])
        board_cards = deck[2 * len(players):2 * len(players) + 5]

        pool = set(players)
        pos_of = {s.idx: i for i, s in
                  enumerate(self.order_from(self.first_after(btn, pool),
                                            players))}

        board = []
        first_postflop = self.first_after(btn, pool)
        streets = (("preflop", 0, self.first_after(bb_seat.idx, pool)),
                   ("flop", 3, first_postflop),
                   ("turn", 4, first_postflop),
                   ("river", 5, first_postflop))

        for street, n_board, first in streets:
            board = board_cards[:n_board]
            if self.in_hand_count(players) < 2:
                break
            self.run_betting(street, first, players, board, bb_amt,
                             pos_of, len(players))
            if self.in_hand_count(players) < 2:
                break

        self.settle(players, board_cards)

        busted = [s for s in players if s.stack == 0]
        busted.sort(key=lambda s: s.contrib)  # smaller stack finishes lower
        for s in busted:
            self.finish_order.append(s.idx)

    def in_hand_count(self, players):
        return sum(1 for s in players if s.in_hand)

    def run_betting(self, street, first_idx, players, board, bb_amt,
                    pos_of, players_dealt):
        hand = [s for s in players if s.in_hand]
        current_bet = max((s.bet_round for s in hand), default=0)
        if street != "preflop":
            for s in players:
                s.bet_round = 0
            current_bet = 0
        min_raise = bb_amt

        need = deque(s for s in self.order_from(first_idx, hand)
                     if not s.all_in)
        if len(need) == 1 and current_bet <= need[0].bet_round:
            return  # nobody can be bet into

        guard = 0
        while need:
            guard += 1
            if guard > 500:
                break
            p = need.popleft()
            if not p.in_hand or p.all_in:
                continue
            if self.in_hand_count(players) < 2:
                break
            to_call = current_bet - p.bet_round

            view = View()
            view.hole = p.hole
            view.board = tuple(board)
            view.street = street
            view.pot = sum(s.contrib for s in players)
            view.to_call = to_call
            view.my_bet = p.bet_round
            view.min_raise_to = current_bet + min_raise
            view.stack = p.stack
            view.bb = bb_amt
            view.position = pos_of[p.idx]
            view.players_dealt = players_dealt
            view.players_in_hand = self.in_hand_count(players)
            view.live_opponents = tuple(s.idx for s in players
                                        if s.in_hand and s is not p)

            try:
                action, amount = p.strategy.act(view)
            except Exception:
                action, amount = ("fold", 0)

            if action == "fold" and to_call == 0:
                action = "check"

            if action == "fold":
                p.in_hand = False
                self.broadcast(p, street, "fold", 0)
                continue

            if action in ("check", "call") or action != "raise":
                pay = min(to_call, p.stack)
                p.stack -= pay
                p.bet_round += pay
                p.contrib += pay
                if p.stack == 0 and pay > 0:
                    p.all_in = True
                    self.broadcast(p, street, "allin", pay)
                else:
                    self.broadcast(p, street,
                                   "call" if pay else "check", pay)
                continue

            # raise: `amount` = desired total bet this round
            max_total = p.bet_round + p.stack
            target = min(int(amount), max_total)
            min_total = current_bet + min_raise
            if target < min_total and target < max_total:
                target = min(min_total, max_total)
            if target <= current_bet:  # cannot even raise -> call/all-in
                pay = min(to_call, p.stack)
                p.stack -= pay
                p.bet_round += pay
                p.contrib += pay
                if p.stack == 0:
                    p.all_in = True
                    self.broadcast(p, street, "allin", pay)
                else:
                    self.broadcast(p, street, "call", pay)
                continue

            pay = target - p.bet_round
            p.stack -= pay
            p.bet_round = target
            p.contrib += pay
            raise_size = target - current_bet
            if raise_size >= min_raise:
                min_raise = raise_size
            current_bet = target
            if p.stack == 0:
                p.all_in = True
                self.broadcast(p, street, "allin", pay)
            else:
                self.broadcast(p, street, "raise", pay)
            need = deque(s for s in
                         self.order_from(self.first_after(p.idx, set(hand)),
                                         hand)
                         if s is not p and s.in_hand and not s.all_in)

    def settle(self, players, board_cards):
        # refund any uncalled excess to the deepest contributor
        contribs = sorted(players, key=lambda s: s.contrib, reverse=True)
        if len(contribs) >= 2 and contribs[0].contrib > contribs[1].contrib:
            refund = contribs[0].contrib - contribs[1].contrib
            contribs[0].stack += refund
            contribs[0].contrib -= refund

        in_hand = [s for s in players if s.in_hand]
        if len(in_hand) == 1:
            in_hand[0].stack += sum(s.contrib for s in players)
            return

        board = board_cards[:5]
        ranks = {s.idx: eval7(list(s.hole) + board) for s in in_hand}
        remaining = {s.idx: s.contrib for s in players}
        seat_by_idx = {s.idx: s for s in players}
        while True:
            positive = [i for i, v in remaining.items() if v > 0]
            if not positive:
                break
            m = min(remaining[i] for i in positive)
            pot = 0
            for i in positive:
                remaining[i] -= m
                pot += m
            eligible = [i for i in positive if seat_by_idx[i].in_hand]
            if not eligible:
                continue
            best = max(ranks[i] for i in eligible)
            winners = sorted(i for i in eligible if ranks[i] == best)
            share, odd = divmod(pot, len(winners))
            for k, i in enumerate(winners):
                seat_by_idx[i].stack += share + (1 if k < odd else 0)

    # -- run to completion --------------------------------------------
    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.MAX_HANDS:
            self.button = self.next_alive(self.button)
            self.play_hand()
        survivors = sorted(self.alive(), key=lambda s: s.stack)
        for s in survivors[:-1]:
            self.finish_order.append(s.idx)
        champion = survivors[-1]
        self.finish_order.append(champion.idx)
        return champion.idx, self.hand_no


# ----------------------------------------------------------------------
# Simulation runner & reporting
# ----------------------------------------------------------------------
ROSTER = [
    ("SuflairGPT_AllIn", AllInBot),        # Player 1 -- the "strategy"
    ("TAG_Shark", TagShark),               # Player 2
    ("LAG_Bluffmaster", LagBluffmaster),   # Player 3
    ("Rock_Nit", RockNit),                 # Player 4
    ("EquityNerd", EquityNerd),            # Player 5
    ("Adaptive_Hustler", AdaptiveHustler), # Player 6
]


def run_sims(n_sims, seed):
    wins = Counter()
    placements = {name: [] for name, _ in ROSTER}
    hands_played = []
    for k in range(n_sims):
        t = Tournament(ROSTER, seed=seed * 100003 + k)
        champ_idx, hands = t.run()
        wins[ROSTER[champ_idx][0]] += 1
        hands_played.append(hands)
        for place_from_bottom, idx in enumerate(t.finish_order):
            place = len(ROSTER) - place_from_bottom
            placements[ROSTER[idx][0]].append(place)
    return wins, placements, hands_played


def ascii_histogram(wins, n_sims):
    lines = []
    width = 48
    top = max(wins.values()) if wins else 1
    lines.append("")
    lines.append("  WINNER WINNER CHICKEN DINNER -- tournament wins "
                 f"({n_sims} sims)")
    lines.append("  " + "-" * 64)
    for i, (name, _) in enumerate(ROSTER):
        w = wins.get(name, 0)
        bar = "#" * max(1 if w else 0, round(w / top * width))
        tag = " <- if my_turn: ALL IN" if i == 0 else ""
        lines.append(f"  P{i+1} {name:<18} {w:>3} | {bar}{tag}")
    lines.append("  " + "-" * 64)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    print(f"Dealing {args.sims} six-max freezeout tournaments "
          f"(seed={args.seed})...")
    wins, placements, hands = run_sims(args.sims, args.seed)

    print(ascii_histogram(wins, args.sims))
    print(f"\n  avg tournament length: {sum(hands)/len(hands):.1f} hands")
    print("  avg finish position (1 = champion):")
    for i, (name, _) in enumerate(ROSTER):
        pl = placements[name]
        print(f"    P{i+1} {name:<18} {sum(pl)/len(pl):.2f}")

    os.makedirs(args.out, exist_ok=True)
    payload = {
        "sims": args.sims,
        "seed": args.seed,
        "wins": dict(wins),
        "avg_finish": {n: sum(p) / len(p) for n, p in placements.items()},
        "avg_hands": sum(hands) / len(hands),
    }
    path = os.path.join(args.out, "results.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  results written to {path}")


if __name__ == "__main__":
    main()
