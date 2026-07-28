#!/usr/bin/env python3
"""
holdem-showdown: 6-player no-limit Texas Hold'em tournament simulator.

Seat 1 plays the deeply sophisticated strategy:

    if my_turn:
        bet = ALL_IN
    fi

Seats 2..6 play five elaborate, mutually-unknown strategies (tight-aggressive,
loose-aggressive, nit, pot-odds machine, adaptive exploiter). No strategy can
see another strategy's code — only public actions at the table.

Runs N sit-and-go tournaments (everyone starts with equal chips, blinds
escalate, play down to a single survivor) and prints/plots a histogram of
tournament winners.

Usage:
    python3 holdem.py --sims 100 --seed 42 --out results/
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import Counter
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------
# Card encoding: integer 0..51, rank = (c >> 2) + 2 in [2..14], suit = c & 3.

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"


def card_str(c: int) -> str:
    return RANK_CHARS[(c >> 2)] + SUIT_CHARS[c & 3]


def _straight_high(rank_set) -> int:
    rs = set(rank_set)
    if 14 in rs:
        rs.add(1)
    for hi in range(14, 4, -1):
        if all(hi - k in rs for k in range(5)):
            return hi
    return 0


def best7(cards) -> tuple:
    """Rank of the best 5-card hand out of 7 cards. Bigger tuple = better hand.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
    3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = [(c >> 2) + 2 for c in cards]
    suits = [c & 3 for c in cards]

    sc = Counter(suits)
    flush_suit = next((s for s, n in sc.items() if n >= 5), None)
    if flush_suit is not None:
        fr = sorted((r for r, s in zip(ranks, suits) if s == flush_suit), reverse=True)
        sh = _straight_high(fr)
        if sh:
            return (8, sh)
        return (5, fr[0], fr[1], fr[2], fr[3], fr[4])

    rc = Counter(ranks)
    groups = sorted(rc.items(), key=lambda kv: (-kv[1], -kv[0]))
    r0, n0 = groups[0]
    if n0 == 4:
        return (7, r0, max(r for r in rc if r != r0))
    if n0 == 3:
        pair = max((r for r, n in groups[1:] if n >= 2), default=0)
        if pair:
            return (6, r0, pair)
    sh = _straight_high(rc.keys())
    if sh:
        return (4, sh)
    if n0 == 3:
        k = sorted((r for r in rc if r != r0), reverse=True)
        return (3, r0, k[0], k[1])
    if n0 == 2:
        pairs = [r for r, n in groups if n == 2]
        if len(pairs) >= 2:
            p1, p2 = pairs[0], pairs[1]
            kick = max(r for r in rc if r != p1 and r != p2)
            return (2, p1, p2, kick)
        k = sorted((r for r in rc if r != r0), reverse=True)
        return (1, r0, k[0], k[1], k[2])
    tops = sorted(rc.keys(), reverse=True)
    return (0, tops[0], tops[1], tops[2], tops[3], tops[4])


def chen_score(hole) -> float:
    """Bill Chen's preflop hand-strength formula."""
    r1, r2 = sorted(((c >> 2) + 2 for c in hole), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(r1, r1 / 2.0)
    score = pts
    if r1 == r2:
        return max(5.0, pts * 2)
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        score += 1
    return score


def mc_equity(hole, board, n_opps, rng, samples) -> float:
    """Monte Carlo equity of `hole` vs n_opps uniformly random hands."""
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    hole = tuple(hole)
    board = tuple(board)
    score = 0.0
    for _ in range(samples):
        rng.shuffle(deck)
        sim_board = board + tuple(deck[:need])
        mine = best7(hole + sim_board)
        idx = need
        ties = 1
        beaten = False
        for _k in range(n_opps):
            ov = best7((deck[idx], deck[idx + 1]) + sim_board)
            idx += 2
            if ov > mine:
                beaten = True
                break
            if ov == mine:
                ties += 1
        if not beaten:
            score += 1.0 / ties
    return score / samples


# ---------------------------------------------------------------------------
# Table state
# ---------------------------------------------------------------------------

@dataclass
class PlayerState:
    seat: int
    stack: int
    hole: tuple = ()
    folded: bool = False
    all_in: bool = False
    bet_round: int = 0      # chips committed on the current street
    contributed: int = 0    # chips committed over the whole hand


@dataclass
class View:
    """Everything a strategy is allowed to see when acting. Public info only."""
    seat: int
    hole: tuple
    board: tuple
    street: str             # 'preflop' | 'flop' | 'turn' | 'river'
    pot: int                # all chips committed by everyone so far
    to_call: int
    current_bet: int
    min_raise_to: int       # smallest legal raise target (bet_round total)
    my_bet_round: int
    my_stack: int
    bb: int
    n_in_hand: int
    pos_frac: float         # 0.0 = first to act this street, 1.0 = last
    last_aggressor: int     # seat of last bettor/raiser this street, -1 if none
    opponents: list         # public dicts: seat/stack/bet_round/folded/all_in
    rng: random.Random

    def pot_odds_needed(self) -> float:
        if self.to_call <= 0:
            return 0.0
        return self.to_call / (self.pot + self.to_call)

    @property
    def max_target(self) -> int:
        return self.my_bet_round + self.my_stack


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class Strategy:
    name = "base"

    def new_hand(self):
        pass

    def observe(self, event):
        """event: (seat, street, kind, amount, was_facing_bet, went_all_in)."""

    def decide(self, view: View):
        raise NotImplementedError

    # -- shared helpers ----------------------------------------------------
    @staticmethod
    def opp_cap(view: View) -> int:
        return max(1, min(3, view.n_in_hand - 1))

    @staticmethod
    def equity(view: View, samples=70) -> float:
        return mc_equity(view.hole, view.board, Strategy.opp_cap(view),
                         view.rng, samples)


class AllInAndy(Strategy):
    """Player 1. The entire strategy, verbatim:

        if my_turn:
            bet = ALL_IN
        fi
    """
    name = "All-In Andy"

    def decide(self, view: View):
        return ("raise", view.max_target)


class TagTanya(Strategy):
    """Player 2 — classic tight-aggressive.

    Positional Chen-formula opening ranges, 3-bets premiums, continuation-bets,
    values pot odds postflop, and switches to push/fold when short-stacked.
    """
    name = "TAG Tanya"

    def decide(self, view: View):
        v = view
        if v.street == "preflop":
            ch = chen_score(v.hole)
            bb_stacks = v.my_stack / v.bb
            if bb_stacks < 8:  # short stack: push/fold
                return ("raise", v.max_target) if ch >= 7 else self._fold(v)
            facing_allin = any(o["all_in"] for o in v.opponents if not o["folded"])
            if v.to_call > 2.5 * v.bb or facing_allin:  # facing a raise/shove
                if ch >= 11:
                    return ("raise", v.max_target)
                if ch >= 9.5:
                    eq = mc_equity(v.hole, v.board, 1, v.rng, 120)
                    if eq > v.pot_odds_needed() + 0.08:
                        return ("call",)
                return self._fold(v)
            need = 8.0 - 2.0 * v.pos_frac  # looser in later position
            if ch >= 10:
                return ("raise", min(v.max_target, v.current_bet + 3 * v.bb))
            if ch >= need:
                return ("raise", min(v.max_target, v.current_bet + int(2.5 * v.bb)))
            return self._fold(v)

        eq = self.equity(v)
        need = v.pot_odds_needed()
        if v.to_call == 0:
            if eq > 0.55 + 0.04 * (v.n_in_hand - 2):
                return ("raise", v.my_bet_round + max(v.bb, (2 * v.pot) // 3))
            return ("check",)
        if eq > 0.72 and eq > need + 0.25:
            return ("raise", min(v.max_target, v.current_bet + v.pot))
        if eq > need + 0.05:
            return ("call",)
        return ("fold",)

    @staticmethod
    def _fold(v):
        return ("check",) if v.to_call == 0 else ("fold",)


class LagLarry(Strategy):
    """Player 3 — loose-aggressive maniac-lite.

    Opens wide, 3-bet bluffs, barrels when checked to, semi-bluffs draws,
    and only folds when the math is clearly against him.
    """
    name = "LAG Larry"

    def decide(self, view: View):
        v = view
        if v.street == "preflop":
            ch = chen_score(v.hole)
            if v.my_stack / v.bb < 10:
                return ("raise", v.max_target) if ch >= 5 else self._fold(v)
            facing_allin = any(o["all_in"] for o in v.opponents if not o["folded"])
            if facing_allin:
                if ch >= 10:
                    return ("call",)
                return self._fold(v)
            if v.to_call > 2.5 * v.bb:
                if ch >= 9 or v.rng.random() < 0.12:
                    return ("raise", min(v.max_target, v.current_bet + 2 * v.pot // 2 + 2 * v.bb))
                if ch >= 6.5:
                    return ("call",)
                return self._fold(v)
            if ch >= 5 or (v.pos_frac > 0.6 and v.rng.random() < 0.30):
                return ("raise", min(v.max_target, v.current_bet + 3 * v.bb))
            return self._fold(v)

        eq = self.equity(v)
        need = v.pot_odds_needed()
        if v.to_call == 0:
            if eq > 0.48 or v.rng.random() < 0.25:  # value bet or stab
                return ("raise", v.my_bet_round + max(v.bb, (2 * v.pot) // 3))
            return ("check",)
        if eq > need + 0.20 or (0.34 < eq < 0.50 and v.rng.random() < 0.25):
            return ("raise", min(v.max_target, v.current_bet + v.pot))  # value / semi-bluff
        if eq > need - 0.04:
            return ("call",)
        return ("fold",)

    @staticmethod
    def _fold(v):
        return ("check",) if v.to_call == 0 else ("fold",)


class RockRita(Strategy):
    """Player 4 — ultra-tight nit.

    Plays only premium hands, never bluffs, folds to aggression without a
    monster, and stacks off only near the nuts.
    """
    name = "Rock Rita"

    def decide(self, view: View):
        v = view
        if v.street == "preflop":
            ch = chen_score(v.hole)
            if v.my_stack / v.bb < 6:
                return ("raise", v.max_target) if ch >= 8 else self._fold(v)
            if v.to_call > 2.5 * v.bb:
                if ch >= 11:
                    return ("raise", v.max_target)
                if ch >= 10:
                    return ("call",)
                return self._fold(v)
            if ch >= 9:
                return ("raise", min(v.max_target, v.current_bet + 3 * v.bb))
            return self._fold(v)

        eq = self.equity(v)
        need = v.pot_odds_needed()
        if v.to_call == 0:
            if eq > 0.85:
                return ("raise", v.max_target)
            if eq > 0.72:
                return ("raise", v.my_bet_round + max(v.bb, v.pot // 2))
            return ("check",)
        if eq > 0.85:
            return ("raise", v.max_target)
        if eq > need + 0.15 and eq > 0.60:
            return ("call",)
        return ("fold",)

    @staticmethod
    def _fold(v):
        return ("check",) if v.to_call == 0 else ("fold",)


class OddsOtto(Strategy):
    """Player 5 — the pot-odds mathematician.

    Pure expected-value machine: Monte Carlo equity vs required pot odds on
    every single decision. Never bluffs, never folds a +EV call.
    """
    name = "Odds Otto"

    def decide(self, view: View):
        v = view
        samples = 90 if v.street == "preflop" else 80
        eq = mc_equity(v.hole, v.board, self.opp_cap(v), v.rng, samples)
        need = v.pot_odds_needed()
        fair_share = 1.0 / max(2, v.n_in_hand)
        if v.to_call == 0:
            if eq > fair_share + 0.22:
                return ("raise", v.my_bet_round + max(v.bb, (3 * v.pot) // 4))
            return ("check",)
        if eq > max(need + 0.18, fair_share + 0.25):
            return ("raise", min(v.max_target, v.current_bet + v.pot))
        if eq > need + 0.02:
            return ("call",)
        return ("fold",)


class AdaptiveAda(Strategy):
    """Player 6 — the exploiter.

    Tracks every opponent's public aggression across the tournament and
    re-prices their bets: a serial shover's all-in is treated as a random
    hand; a nit's raise is treated as the top of the deck. Solid TAG
    baseline underneath, plus late-position steals against tight tables.
    """
    name = "Adaptive Ada"

    def __init__(self):
        self.stats = {}  # seat -> {'acts': n, 'raises': n}

    def observe(self, event):
        seat, _street, kind, _amt, _facing, _allin = event
        st = self.stats.setdefault(seat, {"acts": 0, "raises": 0})
        st["acts"] += 1
        if kind == "raise":
            st["raises"] += 1

    def _margin_vs(self, seat) -> float:
        """Extra equity margin required against this opponent's aggression."""
        st = self.stats.get(seat)
        if not st or st["acts"] < 8:
            return 0.10                       # unknown: stay careful
        aggr = st["raises"] / st["acts"]
        if aggr > 0.75:
            return 0.01                       # maniac: their bet means nothing
        if aggr > 0.45:
            return 0.06
        if aggr < 0.12:
            return 0.22                       # nit: their bet means the world
        return 0.12

    def decide(self, view: View):
        v = view
        margin = self._margin_vs(v.last_aggressor) if v.last_aggressor >= 0 else 0.10
        if v.street == "preflop":
            ch = chen_score(v.hole)
            if v.my_stack / v.bb < 8:
                return ("raise", v.max_target) if ch >= 6.5 else self._fold(v)
            if v.to_call > 2.5 * v.bb:  # facing a raise or shove
                eq = mc_equity(v.hole, v.board, 1, v.rng, 130)
                if eq > v.pot_odds_needed() + margin:
                    aggressive = margin <= 0.06
                    if eq > 0.62 and aggressive:
                        return ("raise", v.max_target)
                    return ("call",)
                return self._fold(v)
            if ch >= 10:
                return ("raise", min(v.max_target, v.current_bet + 3 * v.bb))
            if ch >= 7.5 - 1.5 * v.pos_frac:
                return ("raise", min(v.max_target, v.current_bet + int(2.5 * v.bb)))
            if v.pos_frac > 0.7 and ch >= 5:  # late-position steal
                return ("raise", min(v.max_target, v.current_bet + int(2.5 * v.bb)))
            return self._fold(v)

        eq = self.equity(v, samples=80)
        need = v.pot_odds_needed()
        if v.to_call == 0:
            if eq > 0.58:
                return ("raise", v.my_bet_round + max(v.bb, (2 * v.pot) // 3))
            return ("check",)
        if eq > need + margin + 0.12 and eq > 0.68:
            return ("raise", min(v.max_target, v.current_bet + v.pot))
        if eq > need + margin:
            return ("call",)
        return ("fold",)

    @staticmethod
    def _fold(v):
        return ("check",) if v.to_call == 0 else ("fold",)


STRATEGY_ROSTER = [AllInAndy, TagTanya, LagLarry, RockRita, OddsOtto, AdaptiveAda]


# ---------------------------------------------------------------------------
# Hand engine
# ---------------------------------------------------------------------------

STREETS = ("preflop", "flop", "turn", "river")


class HandEngine:
    def __init__(self, players, strategies, button, sb, bb, rng):
        self.players = players            # alive PlayerStates, seat order
        self.strategies = strategies      # seat -> Strategy
        self.button = button              # index into self.players
        self.sb, self.bb = sb, bb
        self.rng = rng
        self.board = ()
        self.street = "preflop"
        self.current_bet = 0
        self.min_raise = bb
        self.last_aggressor = -1

    # -- helpers -----------------------------------------------------------
    def in_hand(self):
        return [p for p in self.players if not p.folded]

    def pot(self):
        return sum(p.contributed for p in self.players)

    def _pay(self, p: PlayerState, amount: int):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.bet_round += amount
        p.contributed += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    def _order_from(self, start_idx):
        n = len(self.players)
        return [self.players[(start_idx + k) % n] for k in range(n)]

    def _broadcast(self, seat, kind, amount, facing, allin):
        ev = (seat, self.street, kind, amount, facing, allin)
        for s in self.strategies.values():
            s.observe(ev)

    # -- betting -----------------------------------------------------------
    def _make_view(self, p: PlayerState, order) -> View:
        actionable = [q for q in order if not q.folded]
        pos = actionable.index(p)
        denom = max(1, len(actionable) - 1)
        opps = [{"seat": q.seat, "stack": q.stack, "bet_round": q.bet_round,
                 "folded": q.folded, "all_in": q.all_in,
                 "contributed": q.contributed}
                for q in self.players if q is not p]
        return View(
            seat=p.seat, hole=p.hole, board=self.board, street=self.street,
            pot=self.pot(), to_call=self.current_bet - p.bet_round,
            current_bet=self.current_bet,
            min_raise_to=self.current_bet + self.min_raise,
            my_bet_round=p.bet_round, my_stack=p.stack, bb=self.bb,
            n_in_hand=len(self.in_hand()), pos_frac=pos / denom,
            last_aggressor=self.last_aggressor, opponents=opps, rng=self.rng,
        )

    def betting_round(self, first_idx):
        for p in self.players:
            p.bet_round = 0 if self.street != "preflop" else p.bet_round
        if self.street != "preflop":
            self.current_bet = 0
            self.min_raise = self.bb
            self.last_aggressor = -1

        order = self._order_from(first_idx)
        need = {p.seat: (not p.folded and not p.all_in) for p in order}
        idx = 0
        guard = 0
        while any(need.values()):
            guard += 1
            if guard > 10_000:
                raise RuntimeError("betting round failed to terminate")
            p = order[idx % len(order)]
            idx += 1
            if p.folded or p.all_in or not need[p.seat]:
                continue
            if len(self.in_hand()) == 1:
                return
            need[p.seat] = False
            to_call = self.current_bet - p.bet_round
            view = self._make_view(p, order)
            action = self.strategies[p.seat].decide(view)
            kind = action[0]

            if kind in ("fold", "check") and to_call > 0 and kind == "check":
                kind = "fold"
            if kind == "fold" and to_call == 0:
                kind = "check"

            if kind == "fold":
                p.folded = True
                self._broadcast(p.seat, "fold", 0, to_call > 0, False)
            elif kind == "check":
                self._broadcast(p.seat, "check", 0, False, False)
            elif kind == "call":
                paid = self._pay(p, to_call)
                self._broadcast(p.seat, "call", paid, to_call > 0, p.all_in)
            elif kind == "raise":
                target = int(action[1])
                max_target = p.bet_round + p.stack
                target = min(target, max_target)
                if target <= self.current_bet:  # can't top the bet: all-in call
                    paid = self._pay(p, to_call)
                    self._broadcast(p.seat, "call", paid, to_call > 0, p.all_in)
                else:
                    min_target = self.current_bet + self.min_raise
                    if target < min_target:
                        target = min(min_target, max_target)
                    raise_size = target - self.current_bet
                    self._pay(p, target - p.bet_round)
                    self.current_bet = p.bet_round
                    if raise_size >= self.min_raise:
                        self.min_raise = raise_size
                    self.last_aggressor = p.seat
                    for q in order:
                        if q is not p and not q.folded and not q.all_in:
                            need[q.seat] = True
                    self._broadcast(p.seat, "raise", raise_size, to_call > 0,
                                    p.all_in)
            else:
                raise ValueError(f"bad action {action!r} from seat {p.seat}")

    # -- full hand ---------------------------------------------------------
    def play(self, deck):
        n = len(self.players)
        # blinds (heads-up: button is the small blind)
        sb_idx = (self.button + (0 if n == 2 else 1)) % n
        bb_idx = (sb_idx + 1) % n
        self._pay(self.players[sb_idx], self.sb)
        self._pay(self.players[bb_idx], self.bb)
        self.current_bet = self.bb
        self.last_aggressor = self.players[bb_idx].seat

        di = 0
        for p in self.players:
            p.hole = (deck[di], deck[di + 1])
            di += 2

        first_preflop = (bb_idx + 1) % n
        first_post = (self.button + 1) % n

        for street in STREETS:
            self.street = street
            if street == "flop":
                self.board = tuple(deck[di:di + 3]); di += 3
            elif street in ("turn", "river"):
                self.board = self.board + (deck[di],); di += 1
            if len(self.in_hand()) == 1:
                break
            actionable = [p for p in self.in_hand() if not p.all_in]
            if street == "preflop" or len(actionable) >= 2:
                self.betting_round(first_preflop if street == "preflop"
                                   else first_post)
            if len(self.in_hand()) == 1:
                break

        # ensure a full board exists for multiway all-in showdowns
        while len(self.board) < 5 and len(self.in_hand()) > 1:
            self.board = self.board + (deck[di],); di += 1

        self._settle()

    def _settle(self):
        players = self.players
        contribs = {p.seat: p.contributed for p in players}
        live = [p for p in players if not p.folded]

        # refund any uncalled portion of the top bet
        top = max(live, key=lambda p: contribs[p.seat])
        others_max = max((contribs[q.seat] for q in players if q is not top),
                        default=0)
        excess = contribs[top.seat] - others_max
        if excess > 0:
            top.stack += excess
            contribs[top.seat] -= excess

        if len(live) == 1:
            live[0].stack += sum(contribs.values())
            return

        ranks = {p.seat: best7(p.hole + self.board) for p in live}
        order_after_btn = self._order_from((self.button + 1) % len(players))

        prev = 0
        for level in sorted({contribs[p.seat] for p in live}):
            pot = sum(min(contribs[q.seat], level) - min(contribs[q.seat], prev)
                      for q in players)
            prev = level
            if pot == 0:
                continue
            eligible = [p for p in live if contribs[p.seat] >= level]
            best = max(ranks[p.seat] for p in eligible)
            winners = [p for p in order_after_btn
                       if p in eligible and ranks[p.seat] == best]
            share, odd = divmod(pot, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < odd else 0)


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------

STARTING_STACK = 1000
BASE_SB, BASE_BB = 10, 20
HANDS_PER_LEVEL = 12
MAX_HANDS = 3000


def run_tournament(seed: int):
    rng = random.Random(seed)
    players = [PlayerState(seat=s, stack=STARTING_STACK) for s in range(6)]
    strategies = {s: STRATEGY_ROSTER[s]() for s in range(6)}
    total_chips = 6 * STARTING_STACK
    finish_order = []          # seats in elimination order (first out first)
    button_seat = rng.randrange(6)
    deck_proto = list(range(52))

    for hand_no in range(1, MAX_HANDS + 1):
        alive = [p for p in players if p.stack > 0]
        if len(alive) <= 1:
            break
        level = (hand_no - 1) // HANDS_PER_LEVEL
        mult = 2 ** min(level, 9)
        sb, bb = BASE_SB * mult, BASE_BB * mult

        alive_seats = [p.seat for p in alive]
        # rotate the button to the next surviving seat
        while button_seat not in alive_seats:
            button_seat = (button_seat + 1) % 6
        button_idx = alive_seats.index(button_seat)

        for p in alive:
            p.folded = p.all_in = False
            p.bet_round = p.contributed = 0
        for s in strategies.values():
            s.new_hand()

        deck = deck_proto[:]
        rng.shuffle(deck)
        HandEngine(alive, strategies, button_idx, sb, bb, rng).play(deck)

        if sum(p.stack for p in players) != total_chips:
            raise RuntimeError(f"chip leak on hand {hand_no}")

        busted = [p for p in alive if p.stack == 0]
        busted.sort(key=lambda p: (p.contributed, p.seat))  # shortest out first
        finish_order.extend(p.seat for p in busted)

        nxt = (alive_seats.index(button_seat) + 1) % len(alive_seats)
        button_seat = alive_seats[nxt]

    survivors = [p for p in players if p.stack > 0]
    survivors.sort(key=lambda p: p.stack)
    finish_order.extend(p.seat for p in survivors)
    winner_seat = finish_order[-1]
    return winner_seat, finish_order, hand_no


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def player_label(seat: int) -> str:
    return f"P{seat + 1} {STRATEGY_ROSTER[seat].name}"


def ascii_histogram(wins: Counter, sims: int) -> str:
    lines = []
    width = 46
    top = max(wins.values()) if wins else 1
    for seat in range(6):
        n = wins.get(seat, 0)
        bar = "█" * max(0, round(width * n / top))
        lines.append(f"{player_label(seat):<22} {bar} {n}")
    lines.append(f"{'':<22} ({sims} tournaments)")
    return "\n".join(lines)


def plot_histogram(wins: Counter, sims: int, path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, text1, text2 = "#fcfcfb", "#0b0b0b", "#52514e"
    blue, orange = "#2a78d6", "#eb6834"

    labels = [f"P{s + 1}\n{STRATEGY_ROSTER[s].name}" for s in range(6)]
    values = [wins.get(s, 0) for s in range(6)]
    colors = [orange if s == 0 else blue for s in range(6)]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)

    bars = ax.bar(range(6), values, width=0.62, color=colors, zorder=3)
    for rect, val in zip(bars, values):
        ax.annotate(str(val), (rect.get_x() + rect.get_width() / 2, val),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", va="bottom", fontsize=11, color=text1,
                    fontweight="bold")

    ax.set_xticks(range(6), labels, fontsize=9, color=text1)
    ax.tick_params(axis="y", labelsize=9, colors=text2, length=0)
    ax.tick_params(axis="x", length=0)
    ax.yaxis.grid(True, color="#e7e6e2", linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#d8d7d3")

    ax.set_title(f"Winner winner chicken dinner — {sims} six-handed "
                 f"hold'em tournaments",
                 fontsize=13, color=text1, loc="left", pad=16,
                 fontweight="bold")
    ax.set_ylabel("Tournaments won", fontsize=10, color=text2)

    handles = [plt.Rectangle((0, 0), 1, 1, color=orange),
               plt.Rectangle((0, 0), 1, 1, color=blue)]
    ax.legend(handles, ['"if my_turn then bet = all-in fi"',
                        "Elaborate strategies"],
              frameon=False, fontsize=9, labelcolor=text1, loc="upper left",
              bbox_to_anchor=(0.02, 1.0))

    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="results")
    ap.add_argument("--no-plot", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    master = random.Random(args.seed)
    seeds = [master.randrange(2 ** 31) for _ in range(args.sims)]

    wins = Counter()
    finishes = {s: [] for s in range(6)}
    records = []
    total_hands = 0
    for i, seed in enumerate(seeds, 1):
        winner, order, hands = run_tournament(seed)
        wins[winner] += 1
        total_hands += hands
        for place, seat in enumerate(reversed(order), 1):  # 1 = winner
            finishes[seat].append(place)
        records.append({"sim": i, "seed": seed,
                        "winner": player_label(winner),
                        "finish_order_last_to_first":
                            [player_label(s) for s in reversed(order)],
                        "hands": hands})
        if i % 10 == 0:
            print(f"  {i}/{args.sims} tournaments done "
                  f"(leader: {player_label(wins.most_common(1)[0][0])} "
                  f"with {wins.most_common(1)[0][1]})")

    print()
    print("=" * 70)
    print("WINNER HISTOGRAM — last player standing")
    print("=" * 70)
    print(ascii_histogram(wins, args.sims))
    print()
    print(f"{'player':<22}{'wins':>6}{'avg finish':>12}{'best':>6}{'worst':>7}")
    for s in range(6):
        f = finishes[s]
        print(f"{player_label(s):<22}{wins.get(s, 0):>6}"
              f"{sum(f) / len(f):>12.2f}{min(f):>6}{max(f):>7}")
    print(f"\navg tournament length: {total_hands / args.sims:.1f} hands")

    summary = {
        "sims": args.sims, "seed": args.seed,
        "starting_stack": STARTING_STACK,
        "blinds": f"{BASE_SB}/{BASE_BB}, doubling every {HANDS_PER_LEVEL} hands",
        "wins": {player_label(s): wins.get(s, 0) for s in range(6)},
        "avg_finish": {player_label(s): round(sum(f) / len(f), 3)
                       for s, f in finishes.items()},
        "tournaments": records,
    }
    json_path = os.path.join(args.out, "results.json")
    with open(json_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"results written to {json_path}")

    if not args.no_plot:
        png_path = os.path.join(args.out, "winner_histogram.png")
        plot_histogram(wins, args.sims, png_path)
        print(f"histogram written to {png_path}")


if __name__ == "__main__":
    main()
