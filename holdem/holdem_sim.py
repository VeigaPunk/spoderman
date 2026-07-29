#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPODER HOLD'EM ARENA
====================

Six players. One table. 1000 chips each. No mercy.

Seat 1: "All-In Andy" — the entire strategy, verbatim:

        if my_turn
        then bet = All in
        fi

Seats 2..6 run five elaborate strategies (tight-value, pot-odds Monte
Carlo, loose-aggressive, position/Chen TAG, adaptive profiler). No player
knows any other player's algorithm — they only observe public actions.

Engine: full no-limit Texas Hold'em — blinds (escalating), betting rounds,
min-raise rules, all-ins, side pots, split pots, eliminations. A tournament
ends when one player owns every chip: winner winner chicken dinner.

Usage:
    python3 holdem_sim.py --sims 100 --seed 42
"""

from __future__ import annotations

import argparse
import random
from collections import Counter

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------
# Card = rank * 4 + suit;  rank 0..12 (2..A), suit 0..3
RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"

CATEGORY_NAMES = [
    "high card", "pair", "two pair", "trips", "straight",
    "flush", "full house", "quads", "straight flush",
]


def card_str(c: int) -> str:
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def straight_top(rankset) -> int | None:
    """Highest top-rank of a 5-card straight in rankset (wheel supported)."""
    rs = set(rankset)
    if 12 in rs:
        rs.add(-1)  # ace plays low
    for top in range(12, 2, -1):
        if all((top - k) in rs for k in range(5)):
            return top
    return None


def evaluate7(cards) -> tuple:
    """Best 5-card value of a 7 (or 5/6) card hand as a comparable tuple."""
    ranks = [c >> 2 for c in cards]
    suits = [c & 3 for c in cards]
    rank_count = Counter(ranks)
    suit_count = Counter(suits)

    flush_suit = next((s for s, n in suit_count.items() if n >= 5), None)
    if flush_suit is not None:
        franks = {r for r, s in zip(ranks, suits) if s == flush_suit}
        st = straight_top(franks)
        if st is not None:
            return (8, st)

    groups = sorted(rank_count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)
    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    if flush_suit is not None:
        top5 = sorted((r for r, s in zip(ranks, suits) if s == flush_suit), reverse=True)[:5]
        return (5, *top5)
    st = straight_top(set(ranks))
    if st is not None:
        return (4, st)
    if groups[0][1] == 3:
        trips = groups[0][0]
        ks = sorted((r for r in ranks if r != trips), reverse=True)[:2]
        return (3, trips, *ks)
    if groups[0][1] == 2 and groups[1][1] == 2:
        hi, lo = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hi and r != lo)
        return (2, hi, lo, kicker)
    if groups[0][1] == 2:
        pair = groups[0][0]
        ks = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair, *ks)
    return (0, *sorted(ranks, reverse=True)[:5])


# ---------------------------------------------------------------------------
# Shared poker-brain helpers (public knowledge: your cards + the board)
# ---------------------------------------------------------------------------

def hole_info(hole):
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    return r1, r2, suited, r1 == r2


def chen_score(hole) -> float:
    """Bill Chen's preflop hand-strength formula (approx)."""
    r1, r2, suited, pair = hole_info(hole)
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if pair:
        return max(5.0, pts * 2)
    if suited:
        pts += 2
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # connected below queen: straight potential
        pts += 1
    return pts


def estimate_equity(hole, community, n_opps, trials, rng) -> float:
    """Monte Carlo equity of `hole` vs n_opps random hands."""
    known = set(hole) | set(community)
    deck = [c for c in range(52) if c not in known]
    need_board = 5 - len(community)
    n_opps = max(1, n_opps)
    won = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need_board + 2 * n_opps)
        board = list(community) + draw[:need_board]
        mine = evaluate7(list(hole) + board)
        ties = 0
        beaten = False
        for i in range(n_opps):
            opp = draw[need_board + 2 * i: need_board + 2 * i + 2]
            val = evaluate7(opp + board)
            if val > mine:
                beaten = True
                break
            if val == mine:
                ties += 1
        if not beaten:
            won += 1.0 / (1 + ties)
    return won / trials


def made_level(hole, community) -> int:
    """0=air, 1=weak pair, 2=top pair, 3=overpair/two pair, 4=trips or better."""
    val = evaluate7(list(hole) + list(community))
    cat = val[0]
    hr = [hole[0] >> 2, hole[1] >> 2]
    board = [c >> 2 for c in community]
    if cat >= 3:
        return 4
    if cat == 2:
        return 3 if (val[1] in hr or val[2] in hr) else 1
    if cat == 1:
        pr = val[1]
        if pr not in hr:
            return 0  # the board is paired, not us
        if hr[0] == hr[1]:
            return 3 if pr > max(board) else 1  # overpair vs buried pocket pair
        return 2 if pr == max(board) else 1
    return 0


def has_flush_draw(hole, community) -> bool:
    sc = Counter(c & 3 for c in list(hole) + list(community))
    return any(n == 4 and any((h & 3) == s for h in hole) for s, n in sc.items())


def has_straight_draw(hole, community) -> bool:
    rs = {c >> 2 for c in list(hole) + list(community)}
    if 12 in rs:
        rs.add(-1)
    return any(all(lo + k in rs for k in range(4)) for lo in range(-1, 10))


# ---------------------------------------------------------------------------
# Strategies. decide(view) -> ("fold",) | ("call",) | ("raise", street_total)
# "call" with nothing to call is a check; "raise" is clamped to legality.
# ---------------------------------------------------------------------------

class Strategy:
    blurb = "?"

    def decide(self, v):  # pragma: no cover - interface
        raise NotImplementedError


class AllInAndy(Strategy):
    """if my_turn then bet = All in fi"""
    blurb = "YOLO shove bot"

    def decide(self, v):
        return ("raise", v.my_bet + v.my_stack)


class RockRocco(Strategy):
    """Ultra-tight value machine: premiums only, stacks off with the goods."""
    blurb = "ultra-tight nit"

    def decide(self, v):
        return self._preflop(v) if v.street == 0 else self._postflop(v)

    def _tier(self, v):
        r1, r2, suited, pair = hole_info(v.hole)
        if (pair and r1 >= 10) or (r1 == 12 and r2 == 11):
            return 1  # QQ+ / AK
        if (pair and r1 >= 8) or (r1 == 12 and r2 == 10) or \
           (suited and r1 == 12 and r2 >= 9) or (suited and r1 == 11 and r2 == 10):
            return 2  # TT-JJ, AQ, AJs+, KQs
        return 3

    def _preflop(self, v):
        tier = self._tier(v)
        if tier == 1:
            if v.current_bet <= v.bb:
                return ("raise", 4 * v.bb)
            return ("raise", min(v.my_bet + v.my_stack, 3 * v.current_bet))
        if tier == 2:
            if v.current_bet <= v.bb:
                return ("raise", 3 * v.bb)
            return ("call",)  # good enough to see anyone's shove, never bluffing
        return ("fold",)

    def _postflop(self, v):
        lvl = made_level(v.hole, v.community)
        if lvl >= 3:
            return ("raise", v.current_bet + max(v.bb, int(0.75 * v.pot)))
        if lvl == 2:
            if v.to_call == 0:
                return ("raise", max(v.bb, int(0.5 * v.pot)))
            return ("call",) if v.to_call <= 0.4 * v.pot else ("fold",)
        return ("call",) if v.to_call == 0 else ("fold",)


class ProfessorPotts(Strategy):
    """Pot-odds purist: Monte Carlo equity vs required price, every street."""
    blurb = "pot-odds Monte Carlo"

    def decide(self, v):
        n_opps = max(1, v.n_live - 1)
        trials = 40 if v.street == 0 else 60
        eq = estimate_equity(v.hole, v.community, n_opps, trials, v.rng)
        pot, to_call = v.pot, v.to_call
        if to_call == 0:
            fair_share = 1.0 / v.n_live
            if eq > 1.9 * fair_share and eq > 0.42:
                return ("raise", v.current_bet + max(v.bb, int(0.66 * pot)))
            return ("call",)  # check
        need = to_call / (pot + to_call)
        edge = eq - need
        if eq > 0.82:
            return ("raise", v.my_bet + v.my_stack)
        if edge > 0.18 and eq > 0.55:
            return ("raise", v.current_bet + to_call + int(0.75 * (pot + to_call)))
        if edge > 0.03:
            return ("call",)
        if edge > -0.02 and to_call <= v.bb:
            return ("call",)  # peel the cheap ones
        return ("fold",)


class LooseLucy(Strategy):
    """LAG: attacks wide, c-bets relentlessly, semi-bluffs draws, steals."""
    blurb = "loose-aggressive"

    def decide(self, v):
        return self._preflop(v) if v.street == 0 else self._postflop(v)

    def _preflop(self, v):
        r1, r2, suited, pair = hole_info(v.hole)
        rng = v.rng
        playable = pair or (r1 >= 10 and r2 >= 7) or r1 == 12 or \
            (suited and r1 - r2 <= 2 and r2 >= 3)
        strong = (pair and r1 >= 7) or (r1 >= 11 and r2 >= 9) or \
            (suited and r1 == 12 and r2 >= 8)
        if v.current_bet <= v.bb:
            if playable:
                return ("raise", (3 if rng.random() < 0.8 else 2) * v.bb)
            if rng.random() < 0.15:
                return ("raise", 2 * v.bb)  # pure steal
            return ("fold",) if v.to_call else ("call",)
        big = v.to_call > 0.25 * (v.my_stack + v.my_bet)
        if strong:
            if rng.random() < 0.35:
                return ("raise", min(v.my_bet + v.my_stack, 3 * v.current_bet))
            if not big or (pair and r1 >= 9) or (r1 == 12 and r2 >= 10):
                return ("call",)
            return ("fold",)
        if playable and not big:
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        rng = v.rng
        lvl = made_level(v.hole, v.community)
        draw = v.street < 3 and (has_flush_draw(v.hole, v.community) or
                                 has_straight_draw(v.hole, v.community))
        pot, to_call = v.pot, v.to_call
        if to_call == 0:
            if lvl >= 2 or draw:
                return ("raise", v.current_bet + max(v.bb, int(0.7 * pot)))
            if v.i_am_aggressor and rng.random() < 0.6:
                return ("raise", v.current_bet + max(v.bb, int(0.55 * pot)))  # c-bet
            if rng.random() < 0.12:
                return ("raise", v.current_bet + max(v.bb, int(0.5 * pot)))  # pure bluff
            return ("call",)
        if lvl >= 3:
            return ("raise", v.current_bet + to_call + pot)
        if lvl == 2:
            return ("call",) if to_call <= 0.6 * pot else ("fold",)
        if draw:
            need = to_call / (pot + to_call)
            if need < 0.32:
                return ("call",)
            if rng.random() < 0.12:
                return ("raise", v.current_bet + to_call + int(0.8 * (pot + to_call)))
            return ("fold",)
        if lvl == 1 and to_call <= 0.25 * pot:
            return ("call",)
        return ("fold",)


class SharkSharon(Strategy):
    """Position TAG: Chen-formula ranges widened by position, c-bets, pot control."""
    blurb = "position TAG (Chen)"

    def decide(self, v):
        return self._preflop(v) if v.street == 0 else self._postflop(v)

    def _preflop(self, v):
        score = chen_score(v.hole)
        open_threshold = 9.5 - 2.5 * v.pos_frac  # 9.5 early -> 7.0 on the button
        if v.current_bet <= v.bb:
            if score >= 12:
                return ("raise", 3 * v.bb)
            if score >= open_threshold:
                return ("raise", int(2.5 * v.bb))
            return ("fold",) if v.to_call else ("call",)
        if score >= 13:
            return ("raise", min(v.my_bet + v.my_stack, 3 * v.current_bet))
        if score >= 12:
            return ("call",)
        if score >= 10 and v.to_call <= 0.08 * max(1, v.my_stack):
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        rng = v.rng
        lvl = made_level(v.hole, v.community)
        draw = v.street < 3 and (has_flush_draw(v.hole, v.community) or
                                 has_straight_draw(v.hole, v.community))
        pot, to_call = v.pot, v.to_call
        if to_call == 0:
            if lvl >= 3:
                return ("raise", v.current_bet + max(v.bb, int(0.66 * pot)))
            if lvl == 2:
                return ("raise", v.current_bet + max(v.bb, int(0.6 * pot)))
            if v.i_am_aggressor and v.n_live <= 3 and rng.random() < 0.65:
                return ("raise", v.current_bet + max(v.bb, int(0.5 * pot)))  # c-bet
            if draw and rng.random() < 0.5:
                return ("raise", v.current_bet + max(v.bb, int(0.5 * pot)))  # semi-bluff
            return ("call",)
        if lvl >= 4:
            return ("raise", v.current_bet + to_call + pot)
        if lvl == 3:
            return ("call",)
        if lvl == 2:
            return ("call",) if to_call <= 0.45 * pot else ("fold",)
        if draw and to_call / (pot + to_call) < 0.3:
            return ("call",)
        return ("fold",)


class ProfilerPetra(Strategy):
    """Adaptive exploiter: profiles opponents from observed actions only.

    Spots shove-happy maniacs (>50% of hands ending all-in), snap-calls them
    with any decent equity, traps premiums instead of raising them out, and
    plays solid Chen/equity poker against the rest.
    """
    blurb = "adaptive profiler"

    @staticmethod
    def _maniacs(v):
        out = set()
        for seat, st in v.stats.items():
            if seat != v.seat and st["hands"] >= 4 and \
                    st["allins"] / st["hands"] > 0.5:
                out.add(seat)
        return out

    def decide(self, v):
        maniacs = self._maniacs(v)
        return self._preflop(v, maniacs) if v.street == 0 else self._postflop(v, maniacs)

    def _preflop(self, v, maniacs):
        score = chen_score(v.hole)
        to_call = v.to_call
        if to_call > 0 and v.last_raiser_allin and v.last_raiser_seat is not None:
            eq = estimate_equity(v.hole, v.community, v.n_live - 1, 50, v.rng)
            if v.last_raiser_seat in maniacs:
                need = to_call / (v.pot + to_call)
                return ("call",) if eq > need + 0.04 else ("fold",)
            return ("call",) if (eq > 0.60 or score >= 14) else ("fold",)
        maniac_lurking = any((not o["folded"]) and (not o["allin"]) and
                             o["stack"] > 0 and o["seat"] in maniacs
                             for o in v.opps)
        if maniac_lurking:
            # Trap: flat premiums to induce the shove, dodge marginal spots.
            if score >= 13:
                return ("call",)
            if score >= 10 and to_call <= 2 * v.bb:
                return ("call",)
            return ("fold",) if to_call else ("call",)
        if v.current_bet <= v.bb:
            if score >= 8.5 - 1.5 * v.pos_frac:
                return ("raise", int(2.5 * v.bb))
            return ("fold",) if to_call else ("call",)
        if score >= 14:
            return ("raise", min(v.my_bet + v.my_stack, 3 * v.current_bet))
        if score >= 12:
            return ("call",)
        if score >= 9.5 and to_call <= 0.07 * max(1, v.my_stack):
            return ("call",)
        return ("fold",)

    def _postflop(self, v, maniacs):
        eq = estimate_equity(v.hole, v.community, max(1, v.n_live - 1), 45, v.rng)
        pot, to_call = v.pot, v.to_call
        if to_call == 0:
            maniac_live = any((not o["folded"]) and (not o["allin"]) and
                              o["seat"] in maniacs for o in v.opps)
            if eq > 0.65:
                if maniac_live:
                    return ("call",)  # check to induce the inevitable shove
                return ("raise", v.current_bet + max(v.bb, int(0.6 * pot)))
            return ("call",)
        need = to_call / (pot + to_call)
        shover_is_maniac = v.last_raiser_allin and v.last_raiser_seat in maniacs
        buffer = 0.02 if shover_is_maniac else 0.08
        if eq > 0.85:
            return ("raise", v.my_bet + v.my_stack)
        if eq > need + buffer:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Table engine
# ---------------------------------------------------------------------------

class Player:
    __slots__ = ("seat", "name", "strategy", "stack", "hole", "bet",
                 "contrib", "folded", "allin", "start_stack")

    def __init__(self, seat, name, strategy):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = 0


class View:
    """What a strategy is allowed to see: its cards + public information."""
    __slots__ = ("hole", "community", "street", "pot", "to_call", "current_bet",
                 "min_raise_to", "my_bet", "my_stack", "bb", "seat", "n_live",
                 "pos_frac", "i_am_aggressor", "last_raiser_seat",
                 "last_raiser_allin", "opps", "stats", "rng")


def make_view(p, idx, order, street, community, current_bet, mrs, bb, rng,
              stats, aggr):
    v = View()
    v.hole = p.hole
    v.community = community
    v.street = street
    v.pot = sum(q.contrib for q in order)
    v.to_call = max(0, current_bet - p.bet)
    v.current_bet = current_bet
    v.min_raise_to = bb if current_bet == 0 else current_bet + mrs
    v.my_bet = p.bet
    v.my_stack = p.stack
    v.bb = bb
    v.seat = p.seat
    v.n_live = sum(1 for q in order if not q.folded)
    v.pos_frac = idx / (len(order) - 1) if len(order) > 1 else 1.0
    v.i_am_aggressor = aggr["seat"] == p.seat
    v.last_raiser_seat = aggr["seat"]
    v.last_raiser_allin = aggr["allin"]
    v.opps = [{"seat": q.seat, "stack": q.stack, "bet": q.bet,
               "folded": q.folded, "allin": q.allin}
              for q in order if q is not p]
    v.stats = stats
    v.rng = rng
    return v


def apply_action(p, action, current_bet, mrs, bb, stats, aggr):
    """Returns (current_bet, mrs, reopened)."""
    kind = action[0]
    to_call = current_bet - p.bet
    if kind == "fold" and to_call <= 0:
        kind = "call"  # checking is free; never fold the option

    if kind == "fold":
        p.folded = True
        stats[p.seat]["folds"] += 1
        return current_bet, mrs, False

    if kind == "raise":
        max_to = p.bet + p.stack
        target = min(int(action[1]), max_to)
        min_open = bb if current_bet == 0 else current_bet + mrs
        if target > current_bet:
            if target < min_open and target < max_to:
                target = min(min_open, max_to)
            pay = target - p.bet
            p.stack -= pay
            p.bet = target
            p.contrib += pay
            stats[p.seat]["raises"] += 1
            if p.stack == 0:
                p.allin = True
                stats[p.seat]["allins"] += 1
            reopened = target >= min_open
            if reopened:
                mrs = max(bb, target - current_bet)
            aggr["seat"] = p.seat
            aggr["allin"] = p.allin
            return target, mrs, reopened
        kind = "call"  # couldn't legally raise -> flat

    # call / check
    pay = max(0, min(to_call, p.stack))
    p.stack -= pay
    p.bet += pay
    p.contrib += pay
    stats[p.seat]["calls"] += 1
    if p.stack == 0 and pay > 0:
        p.allin = True
        stats[p.seat]["allins"] += 1
    return current_bet, mrs, False


def betting_round(order, street, community, current_bet, mrs, bb, first, rng,
                  stats, aggr):
    n = len(order)
    acted = [False] * n
    i = first
    for _ in range(400):  # hard guard against pathological loops
        if sum(1 for p in order if not p.folded) <= 1:
            break
        idxs = [j for j, p in enumerate(order) if not p.folded and not p.allin]
        if not idxs:
            break
        if all(acted[j] and order[j].bet == current_bet for j in idxs):
            break
        j = i % n
        i += 1
        p = order[j]
        if p.folded or p.allin or (acted[j] and p.bet == current_bet):
            continue
        view = make_view(p, j, order, street, community, current_bet, mrs, bb,
                         rng, stats, aggr)
        action = p.strategy.decide(view)
        acted[j] = True
        current_bet, mrs, reopened = apply_action(p, action, current_bet, mrs,
                                                  bb, stats, aggr)
        if reopened:
            for k, q in enumerate(order):
                if k != j and not q.folded and not q.allin:
                    acted[k] = False
    return current_bet, mrs


def distribute_pots(order, community):
    live = [p for p in order if not p.folded]
    total = sum(p.contrib for p in order)
    if len(live) == 1:
        live[0].stack += total
        return
    scores = {p.seat: evaluate7(list(p.hole) + list(community)) for p in live}
    paid = 0
    prev = 0
    for level in sorted({p.contrib for p in live}):
        slice_amt = sum(max(0, min(p.contrib, level) - min(p.contrib, prev))
                        for p in order)
        prev = level
        if slice_amt == 0:
            continue
        eligible = [p for p in live if p.contrib >= level] or live
        best = max(scores[p.seat] for p in eligible)
        winners = [p for p in eligible if scores[p.seat] == best]
        share, rem = divmod(slice_amt, len(winners))
        for k, w in enumerate(winners):
            w.stack += share + (1 if k < rem else 0)
        paid += slice_amt
    if paid < total:  # folded chips above every live level (edge case)
        best = max(scores[p.seat] for p in live)
        top = max((p for p in live if scores[p.seat] == best),
                  key=lambda p: p.contrib)
        top.stack += total - paid


def play_hand(alive, button_seat, sb, bb, rng, stats):
    # Seat order rotated so index 0 sits just after the button.
    seats = sorted(p.seat for p in alive)
    by_seat = {p.seat: p for p in alive}
    start = next(s for s in seats + seats if s > button_seat) \
        if any(s > button_seat for s in seats) else seats[0]
    k = seats.index(start)
    order = [by_seat[s] for s in seats[k:] + seats[:k]]
    n = len(order)

    deck = list(range(52))
    rng.shuffle(deck)
    for p in order:
        p.hole = [deck.pop(), deck.pop()]
        p.bet = 0
        p.contrib = 0
        p.folded = False
        p.allin = False
        p.start_stack = p.stack
        stats[p.seat]["hands"] += 1
    board = [deck.pop() for _ in range(5)]

    sb_p, bb_p = (order[1], order[0]) if n == 2 else (order[0], order[1])
    for blind_p, amt in ((sb_p, sb), (bb_p, bb)):
        pay = min(amt, blind_p.stack)
        blind_p.stack -= pay
        blind_p.bet += pay
        blind_p.contrib += pay
        if blind_p.stack == 0:
            blind_p.allin = True

    current_bet, mrs = bb, bb
    aggr = {"seat": bb_p.seat, "allin": False}

    community = []
    for street in range(4):
        if street > 0:
            community = board[: street + 2]
            for p in order:
                p.bet = 0
            current_bet, mrs = 0, bb
        live = [p for p in order if not p.folded]
        if len(live) <= 1:
            break
        can_act = [p for p in live if not p.allin]
        must_bet = len(can_act) >= 2 or (
            street == 0 and len(can_act) == 1 and can_act[0].bet < current_bet)
        if must_bet:
            first = (1 if n == 2 else 2 % n) if street == 0 else 0
            current_bet, mrs = betting_round(order, street, community,
                                             current_bet, mrs, bb, first, rng,
                                             stats, aggr)
    # If >1 player is still live, all five board cards play (all-in runouts
    # fall through every street above); with one live player the board is moot.
    distribute_pots(order, board)


def blinds_for(hand_no):
    sb = 10 * (2 ** min(hand_no // 12, 10))
    return sb, 2 * sb


def play_tournament(players, rng):
    """Runs until one player has all chips. Returns names best-place-first."""
    stats = {p.seat: {"hands": 0, "raises": 0, "calls": 0, "folds": 0,
                      "allins": 0} for p in players}
    button = rng.randrange(len(players))
    busted = []
    hand_no = 0
    while True:
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1 or hand_no >= 500:
            break
        seats_alive = sorted(p.seat for p in alive)
        button = next((s for s in seats_alive if s > button), seats_alive[0])
        sb, bb = blinds_for(hand_no)
        play_hand(alive, button, sb, bb, rng, stats)
        hand_no += 1
        newly_busted = [p for p in alive if p.stack == 0]
        # Bigger stack at the start of the hand = better finishing place.
        for p in sorted(newly_busted, key=lambda q: (q.start_stack, q.seat)):
            busted.append(p)
    survivors = sorted((p for p in players if p.stack > 0),
                       key=lambda p: p.stack)
    finish_order = busted + survivors  # first-out first, champion last
    return [p.name for p in reversed(finish_order)], hand_no


# ---------------------------------------------------------------------------
# The arena
# ---------------------------------------------------------------------------

ROSTER = [
    ("P1 All-In Andy", AllInAndy),
    ("P2 Rock Rocco", RockRocco),
    ("P3 Professor Potts", ProfessorPotts),
    ("P4 Loose Lucy", LooseLucy),
    ("P5 Shark Sharon", SharkSharon),
    ("P6 Profiler Petra", ProfilerPetra),
]


def run(sims, seed, chips, verbose=False):
    wins = Counter()
    places = {name: [] for name, _ in ROSTER}
    total_hands = 0
    for sim in range(sims):
        rng = random.Random(seed * 1_000_003 + sim)
        players = [Player(i, name, cls()) for i, (name, cls) in enumerate(ROSTER)]
        for p in players:
            p.stack = chips
        finish, hands = play_tournament(players, rng)
        total_hands += hands
        wins[finish[0]] += 1
        for place, name in enumerate(finish, start=1):
            places[name].append(place)
        if verbose:
            print(f"  sim {sim + 1:3d}: {finish[0]} wins after {hands} hands")
    return wins, places, total_hands


def histogram(wins, places, sims, total_hands):
    lines = []
    bar_unit = max(1, max(wins.values())) / 46
    lines.append("=" * 74)
    lines.append("🏆 WINNER HISTOGRAM — winner winner chicken dinner "
                 f"({sims} tournaments)")
    lines.append("=" * 74)
    blurbs = {name: cls.blurb for name, cls in ROSTER}
    for name, _ in ROSTER:
        w = wins.get(name, 0)
        bar = "█" * max(w and 1, round(w / bar_unit))
        lines.append(f"{name:<20} {'(' + blurbs[name] + ')':<24}|{bar} {w}")
    lines.append("-" * 74)
    lines.append(f"{'':45}avg finish   podium(top-3)")
    for name, _ in ROSTER:
        pl = places[name]
        avg = sum(pl) / len(pl)
        podium = sum(1 for x in pl if x <= 3)
        lines.append(f"{name:<20} {'':<24} {avg:10.2f}   {podium:8d}/{sims}")
    lines.append("-" * 74)
    lines.append(f"avg tournament length: {total_hands / sims:.1f} hands")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Spoder Hold'em Arena")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chips", type=int, default=1000)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    print("🕸️  SPODER HOLD'EM ARENA")
    print(f"    {args.sims} tournaments · 6 players · {args.chips} chips each · "
          f"blinds 10/20 doubling every 12 hands")
    print("    P1 strategy, in full:  if my_turn then bet = All in fi")
    print("    P2..P6: five elaborate strategies. Nobody knows anybody's code.")
    print()
    wins, places, total_hands = run(args.sims, args.seed, args.chips,
                                    args.verbose)
    print(histogram(wins, places, args.sims, total_hands))
    print()
    print("🐔🍗 Simulated in pure stdlib Python, one shot, no imports harmed.")
    print("    Meanwhile a certain soufflé-flavored GPT is still on step 1,")
    print("    asking if you'd like a high-level overview of what poker is.")


if __name__ == "__main__":
    main()
