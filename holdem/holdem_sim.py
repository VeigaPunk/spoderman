#!/usr/bin/env python3
"""
SPODERMAN HOLD'EM THUNDERDOME
=============================

6-max No-Limit Texas Hold'em tournament simulator.

Seat 1 runs the entire strategy book of a certain rival chatbot:

    if my_turn:
        bet = ALL_IN
    fi

Seats 2..6 run five elaborate, hand-crafted strategies (tight-aggressive,
loose-aggressive maniac-lite, nit, pot-odds Monte Carlo, and an adaptive
profiler). No strategy knows what any other strategy is — they only see
public information: their own hole cards, the board, stacks, bets, and the
observable action history.

Run:  python3 holdem_sim.py --sims 100 --seed 42 [--plot winners.png]
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_str(c: int) -> str:
    return RANKS[c >> 2] + SUITS[c & 3]


# ---------------------------------------------------------------------------
# Hand evaluation (5-7 cards) — returns a tuple; bigger is better.
# ---------------------------------------------------------------------------

def _straight_high(mask: int) -> int:
    for high in range(12, 3, -1):
        window = 0b11111 << (high - 4)
        if mask & window == window:
            return high
    # wheel: A-2-3-4-5
    if mask & 0b1000000001111 == 0b1000000001111:
        return 3
    return -1


def _top_ranks(mask: int, n: int):
    out = []
    for r in range(12, -1, -1):
        if mask & (1 << r):
            out.append(r)
            if len(out) == n:
                break
    return tuple(out)


def evaluate(cards) -> tuple:
    """Evaluate the best 5-card hand from 5-7 cards."""
    rank_count = [0] * 13
    suit_count = [0] * 4
    for c in cards:
        rank_count[c >> 2] += 1
        suit_count[c & 3] += 1

    flush_suit = -1
    for s in range(4):
        if suit_count[s] >= 5:
            flush_suit = s
            break
    if flush_suit >= 0:
        fmask = 0
        for c in cards:
            if c & 3 == flush_suit:
                fmask |= 1 << (c >> 2)
        sf = _straight_high(fmask)
        if sf >= 0:
            return (8, sf)
        # With 7 cards a flush excludes quads/full house, so this is final.
        return (5, _top_ranks(fmask, 5))

    quads = [r for r in range(12, -1, -1) if rank_count[r] == 4]
    trips = [r for r in range(12, -1, -1) if rank_count[r] == 3]
    pairs = [r for r in range(12, -1, -1) if rank_count[r] == 2]

    if quads:
        q = quads[0]
        kicker = max(r for r in range(13) if rank_count[r] and r != q)
        return (7, q, kicker)
    if trips and (pairs or len(trips) > 1):
        t = trips[0]
        p = max(pairs[0] if pairs else -1, trips[1] if len(trips) > 1 else -1)
        return (6, t, p)

    mask = 0
    for r in range(13):
        if rank_count[r]:
            mask |= 1 << r
    st = _straight_high(mask)
    if st >= 0:
        return (4, st)
    if trips:
        t = trips[0]
        kickers = tuple(r for r in range(12, -1, -1) if rank_count[r] and r != t)[:2]
        return (3, t, kickers)
    if len(pairs) >= 2:
        hi, lo = pairs[0], pairs[1]
        kicker = max(r for r in range(13) if rank_count[r] and r not in (hi, lo))
        return (2, hi, lo, kicker)
    if pairs:
        p = pairs[0]
        kickers = tuple(r for r in range(12, -1, -1) if rank_count[r] and r != p)[:3]
        return (1, p, kickers)
    return (0, _top_ranks(mask, 5))


# ---------------------------------------------------------------------------
# Poker math helpers (public info only)
# ---------------------------------------------------------------------------

def preflop_tier(hole) -> int:
    """1 = premium ... 5 = trash."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    if r1 == r2:
        if r1 >= 10:            # QQ+
            return 1
        if r1 >= 7:             # 99-JJ
            return 2
        if r1 >= 4:             # 66-88
            return 3
        return 4                # 22-55 (set mining)
    if {r1, r2} == {12, 11}:    # AK
        return 1
    if r1 == 12 and r2 == 10:   # AQ
        return 2
    if r1 == 12 and r2 == 9:    # AJ
        return 3 if suited else 4
    if r1 == 11 and r2 == 10:   # KQ
        return 3
    if suited and r1 >= 8 and r2 >= 8:      # suited broadways
        return 3
    if r1 >= 8 and r2 >= 8:                 # offsuit broadways
        return 4
    if suited and r1 == 12:                 # any suited ace
        return 4
    if suited and abs(r1 - r2) == 1 and r2 >= 4:  # mid suited connectors
        return 4
    return 5


def chen_score(hole) -> float:
    """Bill Chen's preflop formula."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if suited:
        pts += 2
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:
        pts += 1
    return pts


def count_outs(hole, board) -> int:
    """Rough draw outs from flush/straight draws (post-flop only)."""
    if not board or len(board) >= 5:
        return 0
    cards = list(hole) + list(board)
    outs = 0
    suit_count = [0] * 4
    for c in cards:
        suit_count[c & 3] += 1
    if any(sc == 4 for sc in suit_count):
        outs += 9
    mask = 0
    for c in cards:
        mask |= 1 << (c >> 2)
    ace_low = mask | ((mask >> 12) & 1)  # ace also plays low
    best_window = 0
    for lo in range(0, 9):
        window = bin((ace_low >> lo) & 0b11111).count("1")
        best_window = max(best_window, window)
    if best_window == 4 and _straight_high(mask) < 0:
        outs += 6  # blend of OESD (8) and gutshot (4)
    return min(outs, 15)


def made_category(hole, board):
    """(category, is_top_pair_or_better_pair) for heuristic bots."""
    ev = evaluate(list(hole) + list(board))
    cat = ev[0]
    good_pair = False
    if cat == 1:
        pair_rank = ev[1]
        board_ranks = [c >> 2 for c in board]
        hole_ranks = [c >> 2 for c in hole]
        top_board = max(board_ranks)
        overpair = hole_ranks[0] == hole_ranks[1] == pair_rank and pair_rank > top_board
        top_pair = pair_rank == top_board and pair_rank in hole_ranks
        good_pair = overpair or top_pair
    if cat == 2:
        hole_ranks = {hole[0] >> 2, hole[1] >> 2}
        good_pair = ev[1] in hole_ranks or ev[2] in hole_ranks
    return cat, good_pair


def mc_equity(hole, board, n_opp, rng, iters=60) -> float:
    """Monte Carlo equity of `hole` vs n_opp random hands."""
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    score = 0.0
    for _ in range(iters):
        drawn = rng.sample(deck, need + 2 * n_opp)
        full_board = list(board) + drawn[:need]
        mine = evaluate(list(hole) + full_board)
        best_opp = None
        for i in range(n_opp):
            opp = drawn[need + 2 * i: need + 2 * i + 2]
            ev = evaluate(opp + full_board)
            if best_opp is None or ev > best_opp:
                best_opp = ev
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters


# ---------------------------------------------------------------------------
# Strategy interface — sees ONLY public info + own hole cards
# ---------------------------------------------------------------------------

@dataclass
class View:
    """Everything a player is allowed to know when acting."""
    my_id: int
    hole: tuple
    board: list
    street: str                  # preflop/flop/turn/river
    pot: int                     # total chips in the middle (incl. street bets)
    to_call: int                 # extra chips needed to call (capped by stack)
    min_raise_to: int            # minimum legal total street bet if raising
    my_street_bet: int
    my_stack: int                # chips behind (not yet committed)
    big_blind: int
    n_in_hand: int               # players not folded
    n_alive: int                 # players still in tournament
    seats_after_me: int          # players still to act behind this street
    history: list                # public action log for this hand
    stacks: dict                 # player_id -> chips behind


class Strategy:
    name = "?"

    def __init__(self, pid: int, rng: random.Random):
        self.pid = pid
        self.rng = rng

    def act(self, v: View):
        """Return ('fold',), ('call',) or ('raise', total_street_bet)."""
        raise NotImplementedError

    def observe(self, event: dict):
        """Public action broadcast — all players receive the same feed."""


# --- Seat 1: the entire GPT strategy document -------------------------------

class AllInMonkey(Strategy):
    """if my_turn then bet = All in fi"""
    name = "AllInMonkey"

    def act(self, v: View):
        return ("raise", v.my_street_bet + v.my_stack)


# --- Seat 2: tight-aggressive machine ---------------------------------------

class TagAccountant(Strategy):
    """Positional TAG: tiered preflop ranges, c-bets, pot-odds draw calls."""
    name = "TAG-Accountant"

    def __init__(self, pid, rng):
        super().__init__(pid, rng)
        self.aggressor = False

    def act(self, v: View):
        if v.street == "preflop":
            return self._preflop(v)
        return self._postflop(v)

    def _preflop(self, v: View):
        tier = preflop_tier(v.hole)
        self.aggressor = False
        pot_open = v.to_call <= v.big_blind  # unraised pot
        late = v.seats_after_me <= 1
        shove_facing = v.to_call >= v.my_stack * 0.6 or v.to_call > 12 * v.big_blind
        short = v.my_stack <= 12 * v.big_blind

        if shove_facing:
            if tier == 1 or (short and tier <= 2):
                return ("raise", v.my_street_bet + v.my_stack)
            return ("fold",)
        if tier == 1:
            self.aggressor = True
            return ("raise", max(v.min_raise_to, 3 * v.big_blind + v.to_call))
        if tier == 2:
            if pot_open:
                self.aggressor = True
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if v.to_call <= max(4 * v.big_blind, v.my_stack // 10):
                return ("call",)
            return ("fold",)
        if tier == 3:
            if pot_open:
                self.aggressor = True
                return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind)))
            if v.to_call <= 2 * v.big_blind:
                return ("call",)
            return ("fold",)
        if tier == 4 and pot_open and late:
            return ("raise", max(v.min_raise_to, int(2.2 * v.big_blind)))
        if v.to_call == 0:
            return ("call",)
        return ("fold",)

    def _postflop(self, v: View):
        cat, good_pair = made_category(v.hole, v.board)
        outs = count_outs(v.hole, v.board)
        pot = max(v.pot, v.big_blind)

        if cat >= 2:  # two pair or better: value bet / raise
            target = v.to_call + v.my_street_bet + int(pot * 0.75)
            return ("raise", max(v.min_raise_to, target))
        if cat == 1 and good_pair:
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.6)))
            if v.to_call <= pot * 0.6 or v.to_call >= v.my_stack:
                return ("call",) if v.to_call <= v.my_stack * 0.5 else ("fold",)
            return ("fold",)
        if outs >= 8:  # big draw: semi-bluff or price in
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.5)))
            equity = outs * (0.04 if v.street == "flop" else 0.02)
            if v.to_call / (pot + v.to_call) < equity:
                return ("call",)
            return ("fold",)
        if v.to_call == 0:
            if self.aggressor and v.street == "flop" and v.n_in_hand <= 3:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.5)))
            return ("call",)  # check
        if outs >= 4 and v.to_call <= pot * 0.2:
            return ("call",)
        return ("fold",)


# --- Seat 3: loose-aggressive gremlin ---------------------------------------

class ChaosGremlin(Strategy):
    """LAG: wide ranges, positional steals, semi-bluffs, random barrels."""
    name = "ChaosGremlin"

    def act(self, v: View):
        if v.street == "preflop":
            return self._preflop(v)
        return self._postflop(v)

    def _preflop(self, v: View):
        tier = preflop_tier(v.hole)
        pot_open = v.to_call <= v.big_blind
        late = v.seats_after_me <= 1
        shove_facing = v.to_call >= v.my_stack * 0.6

        if shove_facing:
            if tier <= 2 or (tier == 3 and v.my_stack <= 10 * v.big_blind):
                return ("raise", v.my_street_bet + v.my_stack)
            return ("fold",)
        if tier <= 2:
            return ("raise", max(v.min_raise_to, 3 * v.big_blind + v.to_call))
        if tier <= 4:
            if pot_open and (late or self.rng.random() < 0.35):
                return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind)))
            if v.to_call <= 3 * v.big_blind:
                return ("call",)
            return ("fold",)
        if pot_open and late and self.rng.random() < 0.45:  # pure steal
            return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind)))
        if v.to_call == 0:
            return ("call",)
        return ("fold",)

    def _postflop(self, v: View):
        cat, good_pair = made_category(v.hole, v.board)
        outs = count_outs(v.hole, v.board)
        pot = max(v.pot, v.big_blind)

        if cat >= 3 or (cat == 2 and good_pair):
            if v.to_call == 0 and self.rng.random() < 0.25:
                return ("call",)  # trap check
            return ("raise", max(v.min_raise_to, v.to_call + v.my_street_bet + int(pot * 0.9)))
        if outs >= 8:  # aggressive semi-bluff
            if v.to_call <= v.my_stack * 0.35:
                return ("raise", max(v.min_raise_to, v.to_call + v.my_street_bet + int(pot * 0.8)))
            return ("call",) if v.to_call <= pot else ("fold",)
        if cat == 1:
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.55)))
            if good_pair and v.to_call <= pot * 0.8:
                return ("call",)
            if v.to_call <= pot * 0.35:
                return ("call",)
            return ("fold",)
        if v.to_call == 0:
            if self.rng.random() < 0.30 and v.n_in_hand <= 3:  # naked bluff
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.6)))
            return ("call",)
        if v.to_call <= pot * 0.15 and self.rng.random() < 0.4:
            return ("call",)  # float
        return ("fold",)


# --- Seat 4: the nit --------------------------------------------------------

class NitRock(Strategy):
    """Plays only premiums, continues only with strong made hands."""
    name = "NitRock"

    def act(self, v: View):
        if v.street == "preflop":
            tier = preflop_tier(v.hole)
            short = v.my_stack <= 8 * v.big_blind
            if tier == 1:
                if v.to_call >= v.my_stack * 0.5:
                    return ("raise", v.my_street_bet + v.my_stack)
                return ("raise", max(v.min_raise_to, 4 * v.big_blind + v.to_call))
            if tier == 2:
                if v.to_call <= 3 * v.big_blind:
                    return ("raise", max(v.min_raise_to, 3 * v.big_blind))
                if short:
                    return ("raise", v.my_street_bet + v.my_stack)
                return ("fold",)
            if short and tier == 3 and v.to_call <= v.big_blind:
                return ("raise", v.my_street_bet + v.my_stack)
            if v.to_call == 0:
                return ("call",)
            return ("fold",)

        cat, good_pair = made_category(v.hole, v.board)
        pot = max(v.pot, v.big_blind)
        if cat >= 2:
            return ("raise", max(v.min_raise_to, v.to_call + v.my_street_bet + int(pot * 0.8)))
        if cat == 1 and good_pair:
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.6)))
            if v.to_call <= pot * 0.7:
                return ("call",)
            return ("fold",)
        if v.to_call == 0:
            return ("call",)
        return ("fold",)


# --- Seat 5: pot-odds Monte Carlo professor ---------------------------------

class MathProfessor(Strategy):
    """Chen formula preflop; Monte Carlo equity vs pot odds postflop."""
    name = "MathProfessor"

    def act(self, v: View):
        pot = max(v.pot, v.big_blind)
        if v.street == "preflop":
            score = chen_score(v.hole)
            short = v.my_stack <= 10 * v.big_blind
            if v.to_call >= v.my_stack * 0.5:
                # Big decision: run the numbers instead of guessing.
                eq = mc_equity(v.hole, v.board, max(1, v.n_in_hand - 1), self.rng, 80)
                need = v.to_call / (pot + v.to_call)
                return ("raise", v.my_street_bet + v.my_stack) if eq > need + 0.05 else ("fold",)
            if score >= 10 or (short and score >= 8):
                return ("raise", max(v.min_raise_to, 3 * v.big_blind + v.to_call))
            if score >= 8:
                return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind))) \
                    if v.to_call <= v.big_blind else ("call",)
            if score >= 6 and v.to_call <= 2 * v.big_blind:
                return ("call",)
            if v.to_call == 0:
                return ("call",)
            return ("fold",)

        eq = mc_equity(v.hole, v.board, max(1, v.n_in_hand - 1), self.rng, 60)
        if v.to_call == 0:
            if eq > 0.62:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.66)))
            if eq > 0.45 and self.rng.random() < 0.3:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.4)))
            return ("call",)
        need = v.to_call / (pot + v.to_call)
        if eq > need + 0.22:
            return ("raise", max(v.min_raise_to, v.to_call + v.my_street_bet + int(pot * 0.8)))
        if eq > need + 0.03:
            return ("call",)
        return ("fold",)


# --- Seat 6: adaptive profiler ----------------------------------------------

class AdaptiveProfiler(Strategy):
    """Tracks opponents' observable tendencies and exploits them.

    Knows nothing about the other bots' code — it only counts what it sees.
    If someone keeps open-shoving preflop, it widens its calling range
    against *that* player; against tight tables it steals more.
    """
    name = "AdaptiveProfiler"

    def __init__(self, pid, rng):
        super().__init__(pid, rng)
        self.stats = defaultdict(lambda: {"pf_acts": 0, "pf_shoves": 0,
                                          "raises": 0, "acts": 0})

    def observe(self, event: dict):
        pid = event["player"]
        if pid == self.pid:
            return
        s = self.stats[pid]
        s["acts"] += 1
        if event["action"] == "raise":
            s["raises"] += 1
        if event["street"] == "preflop":
            s["pf_acts"] += 1
            if event["all_in"] and event["action"] == "raise":
                s["pf_shoves"] += 1

    def _shover_ids(self):
        out = set()
        for pid, s in self.stats.items():
            if s["pf_acts"] >= 3 and s["pf_shoves"] / s["pf_acts"] > 0.5:
                out.add(pid)
        return out

    def _wide_value_hand(self, hole) -> bool:
        """Range that crushes a random shoving range: 66+, A9+, KQ, KJs, QJs."""
        r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
        suited = (hole[0] & 3) == (hole[1] & 3)
        if r1 == r2 and r1 >= 4:
            return True
        if r1 == 12 and r2 >= 7:
            return True
        if r1 == 11 and (r2 == 10 or (suited and r2 == 9)):
            return True
        if suited and r1 == 10 and r2 == 9:
            return True
        return False

    def act(self, v: View):
        pot = max(v.pot, v.big_blind)
        if v.street == "preflop":
            return self._preflop(v, pot)
        return self._postflop(v, pot)

    def _preflop(self, v: View, pot: int):
        tier = preflop_tier(v.hole)
        shovers = self._shover_ids()
        # Who is behind the current bet? If a known maniac shoved, exploit.
        facing_maniac_jam = any(
            e["action"] == "raise" and e["all_in"] and e["player"] in shovers
            for e in v.history if e["street"] == "preflop"
        ) and v.to_call > 0
        short = v.my_stack <= 10 * v.big_blind

        if facing_maniac_jam:
            # Maniac range is random — call wide-but-solid and print money.
            if self._wide_value_hand(v.hole) or (short and tier <= 4):
                return ("raise", v.my_street_bet + v.my_stack)
            return ("fold",)
        if v.to_call >= v.my_stack * 0.6:  # big jam from a normal player
            return ("raise", v.my_street_bet + v.my_stack) if tier == 1 else ("fold",)
        if tier == 1:
            return ("raise", max(v.min_raise_to, 3 * v.big_blind + v.to_call))
        if tier == 2:
            if v.to_call <= v.big_blind:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if v.to_call <= 5 * v.big_blind:
                return ("call",)
            return ("fold",)
        # Steal wider once the table has proven tight (low observed raise rate).
        table_raise_rate = 0.0
        total_acts = sum(s["acts"] for s in self.stats.values())
        if total_acts >= 20:
            table_raise_rate = sum(s["raises"] for s in self.stats.values()) / total_acts
        stealy = table_raise_rate < 0.25 and v.seats_after_me <= 2
        if tier == 3 or (tier == 4 and stealy):
            if v.to_call <= v.big_blind:
                return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind)))
            if tier == 3 and v.to_call <= 2 * v.big_blind:
                return ("call",)
            return ("fold",)
        if v.to_call == 0:
            return ("call",)
        return ("fold",)

    def _postflop(self, v: View, pot: int):
        cat, good_pair = made_category(v.hole, v.board)
        outs = count_outs(v.hole, v.board)
        if cat >= 2:
            return ("raise", max(v.min_raise_to, v.to_call + v.my_street_bet + int(pot * 0.8)))
        if cat == 1 and good_pair:
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.6)))
            if v.to_call <= pot * 0.7:
                return ("call",)
            return ("fold",)
        if outs >= 8:
            if v.to_call == 0:
                return ("raise", max(v.min_raise_to, v.my_street_bet + int(pot * 0.5)))
            if v.to_call / (pot + v.to_call) < outs * (0.04 if v.street == "flop" else 0.02):
                return ("call",)
            return ("fold",)
        if v.to_call == 0:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

STREETS = ("preflop", "flop", "turn", "river")


class Tournament:
    def __init__(self, strategies: dict, seed: int,
                 start_stack=2000, sb=10, bb=20, level_hands=20, verbose=False):
        self.rng = random.Random(seed)
        self.strategies = strategies
        self.stacks = {pid: start_stack for pid in strategies}
        self.sb0, self.bb0 = sb, bb
        self.level_hands = level_hands
        self.verbose = verbose
        self.eliminated = []          # pids in order of elimination
        self.hands_played = 0

    def blinds(self):
        level = self.hands_played // self.level_hands
        mult = 2 ** min(level, 12)
        return self.sb0 * mult, self.bb0 * mult

    def alive(self):
        return [p for p in self.strategies if self.stacks[p] > 0]

    def run(self, max_hands=3000) -> int:
        order = list(self.strategies)
        dealer = 0
        while len(self.alive()) > 1 and self.hands_played < max_hands:
            alive = [p for p in order if self.stacks[p] > 0]
            dealer %= len(alive)
            self.play_hand(alive, dealer)
            self.hands_played += 1
            # bust-outs, in worst-stack-first order for tie stability
            for p in list(self.strategies):
                if self.stacks[p] == 0 and p not in self.eliminated:
                    self.eliminated.append(p)
            dealer += 1
        winner = self.alive()[0]
        self.eliminated.append(winner)
        return winner

    # -- one hand ------------------------------------------------------------

    def play_hand(self, alive, dealer):
        sb_amt, bb_amt = self.blinds()
        n = len(alive)
        deck = list(range(52))
        self.rng.shuffle(deck)
        holes = {p: (deck.pop(), deck.pop()) for p in alive}
        board = []

        contrib = {p: 0 for p in alive}       # whole-hand contributions
        folded = {p: False for p in alive}
        all_in = {p: False for p in alive}
        history = []

        if n == 2:
            sb_p, bb_p = alive[dealer], alive[(dealer + 1) % n]
            preflop_first = dealer            # dealer acts first heads-up
            postflop_first = (dealer + 1) % n
        else:
            sb_p, bb_p = alive[(dealer + 1) % n], alive[(dealer + 2) % n]
            preflop_first = (dealer + 3) % n
            postflop_first = (dealer + 1) % n

        street_bets = {p: 0 for p in alive}

        def commit(p, amount):
            amount = min(amount, self.stacks[p])
            self.stacks[p] -= amount
            street_bets[p] += amount
            contrib[p] += amount
            if self.stacks[p] == 0:
                all_in[p] = True

        commit(sb_p, sb_amt)
        commit(bb_p, bb_amt)

        def broadcast(pid, action, amount, street, facing):
            event = {"player": pid, "action": action, "amount": amount,
                     "street": street, "all_in": all_in[pid], "facing": facing}
            history.append(event)
            for s in self.strategies.values():
                s.observe(event)

        def betting_round(street, first_idx):
            max_bet = max(street_bets.values())
            min_raise = bb_amt
            acted = set()
            i = first_idx
            for _ in range(1000):
                actionable = [p for p in alive if not folded[p] and not all_in[p]]
                in_hand = [p for p in alive if not folded[p]]
                if len(in_hand) <= 1:
                    return
                if actionable and all(p in acted and street_bets[p] == max_bet
                                      for p in actionable):
                    return
                if not actionable:
                    return
                p = alive[i % n]
                i += 1
                if folded[p] or all_in[p]:
                    continue
                if p in acted and street_bets[p] == max_bet:
                    continue

                to_call = min(max_bet - street_bets[p], self.stacks[p])
                seats_after = sum(
                    1 for j in range(1, n)
                    if not folded[alive[(i - 1 + j) % n]]
                    and not all_in[alive[(i - 1 + j) % n]]
                    and alive[(i - 1 + j) % n] not in acted
                )
                view = View(
                    my_id=p, hole=holes[p], board=list(board), street=street,
                    pot=sum(contrib.values()), to_call=to_call,
                    min_raise_to=max_bet + min_raise,
                    my_street_bet=street_bets[p], my_stack=self.stacks[p],
                    big_blind=bb_amt,
                    n_in_hand=len(in_hand), n_alive=len(alive),
                    seats_after_me=seats_after, history=list(history),
                    stacks={q: self.stacks[q] for q in alive},
                )
                try:
                    decision = self.strategies[p].act(view)
                except Exception:
                    decision = ("fold",)

                kind = decision[0]
                if kind == "raise":
                    target = int(decision[1])
                    cap = street_bets[p] + self.stacks[p]
                    target = min(target, cap)
                    if target <= max_bet:                      # can't raise: call
                        kind = "call"
                    else:
                        if target < max_bet + min_raise and target < cap:
                            target = min(max_bet + min_raise, cap)
                        raise_size = target - max_bet
                        commit(p, target - street_bets[p])
                        if raise_size >= min_raise:
                            min_raise = raise_size
                        max_bet = street_bets[p]
                        acted = {p}
                        broadcast(p, "raise", street_bets[p], street, to_call > 0)
                        continue
                if kind == "call":
                    commit(p, to_call)
                    acted.add(p)
                    broadcast(p, "call" if to_call else "check",
                              street_bets[p], street, to_call > 0)
                    continue
                # fold (or check when free)
                if to_call == 0:
                    acted.add(p)
                    broadcast(p, "check", street_bets[p], street, False)
                else:
                    folded[p] = True
                    acted.add(p)
                    broadcast(p, "fold", 0, street, True)

        # preflop
        betting_round("preflop", preflop_first)
        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            in_hand = [p for p in alive if not folded[p]]
            if len(in_hand) <= 1:
                break
            board.extend(deck.pop() for _ in range(ncards))
            street_bets = {p: 0 for p in alive}
            actionable = [p for p in in_hand if not all_in[p]]
            if len(actionable) >= 2:
                betting_round(street, postflop_first)

        self.settle(alive, holes, board, contrib, folded, deck)

    def settle(self, alive, holes, board, contrib, folded, deck):
        in_hand = [p for p in alive if not folded[p]]
        if len(in_hand) == 1:
            self.stacks[in_hand[0]] += sum(contrib.values())
            return
        while len(board) < 5:
            board.append(deck.pop())
        scores = {p: evaluate(list(holes[p]) + board) for p in in_hand}

        # layered side pots
        levels = sorted({contrib[p] for p in in_hand})
        paid = {p: 0 for p in contrib}
        prev = 0
        remainder_carry = 0
        for lvl in levels:
            pot = sum(min(contrib[p], lvl) - min(contrib[p], prev) for p in contrib)
            pot += remainder_carry
            remainder_carry = 0
            eligible = [p for p in in_hand if contrib[p] >= lvl]
            best = max(scores[p] for p in eligible)
            winners = [p for p in eligible if scores[p] == best]
            share, rem = divmod(pot, len(winners))
            for w in winners:
                paid[w] += share
            remainder_carry = rem  # odd chips roll into the next layer
            prev = lvl
        if remainder_carry:      # odd chip from the final layer: first winner
            best = max(scores[p] for p in in_hand)
            first = next(p for p in in_hand if scores[p] == best)
            paid[first] += remainder_carry
        for p, amt in paid.items():
            self.stacks[p] += amt


# ---------------------------------------------------------------------------
# Simulation runner + histogram
# ---------------------------------------------------------------------------

ROSTER = [
    (1, AllInMonkey),
    (2, TagAccountant),
    (3, ChaosGremlin),
    (4, NitRock),
    (5, MathProfessor),
    (6, AdaptiveProfiler),
]


def run_sims(n_sims: int, seed: int, verbose=False):
    results = []
    for sim in range(n_sims):
        sim_seed = seed * 100_000 + sim
        strategies = {
            pid: cls(pid, random.Random(sim_seed * 10 + pid))
            for pid, cls in ROSTER
        }
        t = Tournament(strategies, seed=sim_seed)
        winner = t.run()
        results.append({
            "sim": sim + 1,
            "winner": winner,
            "hands": t.hands_played,
            "placements": list(reversed(t.eliminated)),  # 1st, 2nd, ...
        })
        if verbose:
            names = {pid: cls.name for pid, cls in ROSTER}
            print(f"sim {sim+1:3d}: winner P{winner} ({names[winner]}) "
                  f"after {t.hands_played} hands")
    return results


def ascii_histogram(results):
    names = {pid: cls.name for pid, cls in ROSTER}
    wins = {pid: 0 for pid, _ in ROSTER}
    for r in results:
        wins[r["winner"]] += 1
    total = len(results)
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — tournament wins out of "
                 f"{total} sims")
    lines.append("=" * 66)
    width = 44
    top = max(wins.values()) or 1
    for pid, _ in ROSTER:
        bar = "█" * max(1 if wins[pid] else 0, round(wins[pid] / top * width))
        tag = f"P{pid} {names[pid]:<17}"
        lines.append(f"{tag}|{bar:<{width}} {wins[pid]:3d}  ({wins[pid]/total:5.1%})")
    lines.append("=" * 66)
    return "\n".join(lines), wins


def main():
    ap = argparse.ArgumentParser(description="Spoderman Hold'em Thunderdome")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--plot", type=str, default=None,
                    help="write a PNG histogram (needs matplotlib)")
    ap.add_argument("--json", type=str, default=None,
                    help="write raw results as JSON")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    results = run_sims(args.sims, args.seed, verbose=args.verbose)
    hist, wins = ascii_histogram(results)
    print(hist)

    names = {pid: cls.name for pid, cls in ROSTER}
    avg_place = {pid: 0.0 for pid in names}
    for r in results:
        for place, pid in enumerate(r["placements"], start=1):
            avg_place[pid] += place
    print("\nAverage finishing position (1 = winner, 6 = first bust):")
    for pid in names:
        print(f"  P{pid} {names[pid]:<17} {avg_place[pid]/len(results):.2f}")
    avg_hands = sum(r["hands"] for r in results) / len(results)
    print(f"\nAverage tournament length: {avg_hands:.0f} hands")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"wins": {names[p]: w for p, w in wins.items()},
                       "results": results}, f, indent=2)
        print(f"raw results -> {args.json}")

    if args.plot:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not installed; skipping PNG plot")
            return
        # Palette: validated pair — blue #2a78d6 (pros), orange #eb6834 (P1)
        surface, ink, muted, grid, base = ("#fcfcfb", "#0b0b0b", "#898781",
                                           "#e1e0d9", "#c3c2b7")
        labels = [f"P{pid}\n{names[pid]}" for pid, _ in ROSTER]
        values = [wins[pid] for pid, _ in ROSTER]
        colors = ["#eb6834"] + ["#2a78d6"] * 5
        fig, ax = plt.subplots(figsize=(9, 5.2))
        fig.patch.set_facecolor(surface)
        ax.set_facecolor(surface)
        ax.yaxis.grid(True, color=grid, linewidth=0.8, zorder=0)
        ax.set_axisbelow(True)
        bars = ax.bar(labels, values, color=colors, width=0.62, zorder=3)
        for b, val in zip(bars, values):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + 0.6,
                    str(val), ha="center", fontsize=11, fontweight="bold",
                    color=ink)
        ax.set_title("Hold'em Thunderdome — tournament winners over "
                     f"{len(results)} sims  (P1 = all-in every hand)",
                     fontsize=12.5, color=ink, pad=14)
        ax.set_ylabel("tournaments won", color=muted)
        ax.tick_params(colors=muted, length=0)
        for spine in ("top", "right", "left"):
            ax.spines[spine].set_visible(False)
        ax.spines["bottom"].set_color(base)
        fig.tight_layout()
        fig.savefig(args.plot, dpi=150, facecolor=surface)
        print(f"histogram -> {args.plot}")


if __name__ == "__main__":
    main()
