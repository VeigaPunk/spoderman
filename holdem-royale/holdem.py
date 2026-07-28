#!/usr/bin/env python3
"""
HOLD'EM ROYALE — 6-max No-Limit Texas Hold'em tournament simulator.

Six players, equal starting stacks, escalating blinds, play until one
player owns every chip ("winner winner chicken dinner").

Player 1 runs the world's simplest strategy:

    if my_turn:
        bet = ALL_IN
    fi

Players 2..6 run five elaborate, mutually-unaware strategies:

    P2 "The Professor"  — tight-aggressive: Chen-formula ranges by position,
                          continuation bets, pot-odds discipline.
    P3 "The Cowboy"     — loose-aggressive: wide ranges, 3-bets, barrels,
                          semi-bluffs draws, randomized bluff frequency.
    P4 "The Actuary"    — Monte-Carlo equity vs. pot odds on every street;
                          only puts chips in with a mathematical edge.
    P5 "The Rock"       — ultra-tight nit that slow-plays monsters and
                          set-mines cheap; push/fold when short.
    P6 "The Shark"      — adaptive exploiter: profiles each opponent's
                          aggression / all-in frequency from observed
                          actions only, then adjusts calling ranges,
                          steal frequency and bluff frequency.

No strategy knows any other player's algorithm. The Shark only learns from
publicly observable actions, like a human would.

Usage:  python3 holdem.py [--sims 100] [--seed 2026]
"""

import argparse
import random
import sys
from collections import Counter

# ----------------------------------------------------------------------------
# Cards & hand evaluation
# ----------------------------------------------------------------------------
# Card = int 0..51.  rank = card // 4 + 2  (2..14, ace high), suit = card % 4.

RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_NAMES = "shdc"


def card_str(c):
    r = c // 4 + 2
    return f"{RANK_NAMES.get(r, r)}{SUIT_NAMES[c % 4]}"


def _straight_high(uniq_desc):
    """Highest straight top-card in a desc-sorted unique rank list, else None."""
    rs = list(uniq_desc)
    if 14 in uniq_desc:
        rs.append(1)  # wheel
    run = 1
    for i in range(1, len(rs)):
        if rs[i] == rs[i - 1] - 1:
            run += 1
            if run >= 5:
                return rs[i] + 4
        else:
            run = 1
    return None


def evaluate(cards):
    """Rank a hand of 3..7 cards. Returns a tuple; bigger tuple = better hand.
    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
    3 trips, 2 two pair, 1 pair, 0 high card."""
    ranks = sorted((c // 4 + 2 for c in cards), reverse=True)
    cnt = Counter(ranks)
    scnt = Counter(c % 4 for c in cards)
    flush_suit = next((s for s, n in scnt.items() if n >= 5), None)

    franks = None
    if flush_suit is not None:
        franks = sorted({c // 4 + 2 for c in cards if c % 4 == flush_suit},
                        reverse=True)
        sf = _straight_high(franks)
        if sf:
            return (8, sf)

    uniq = sorted(cnt, reverse=True)
    quads = [r for r, n in cnt.items() if n == 4]
    trips = sorted((r for r, n in cnt.items() if n == 3), reverse=True)
    pairs = sorted((r for r, n in cnt.items() if n == 2), reverse=True)

    if quads:
        q = quads[0]
        kick = max((r for r in uniq if r != q), default=0)
        return (7, q, kick)
    if trips and (pairs or len(trips) > 1):
        t = trips[0]
        p = max(pairs + trips[1:])
        return (6, t, p)
    if franks is not None:
        return (5,) + tuple(franks[:5])
    st = _straight_high(uniq)
    if st:
        return (4, st)
    if trips:
        t = trips[0]
        kicks = [r for r in uniq if r != t][:2]
        return (3, t) + tuple(kicks)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick = max((r for r in uniq if r not in (p1, p2)), default=0)
        return (2, p1, p2, kick)
    if pairs:
        p = pairs[0]
        kicks = [r for r in uniq if r != p][:3]
        return (1, p) + tuple(kicks)
    return (0,) + tuple(uniq[:5])


# ----------------------------------------------------------------------------
# Strategy helper heuristics
# ----------------------------------------------------------------------------

def chen_score(hole):
    """Bill Chen's preflop hand-strength formula (roughly 0..20)."""
    c1, c2 = hole
    r1, r2 = c1 // 4 + 2, c2 // 4 + 2
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    score = pts
    if c1 % 4 == c2 % 4:
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        score += 1
    return score


def made_strength(hole, board):
    """Cheap made-hand strength in [0, 1], discounting board-only hands."""
    me = evaluate(list(hole) + list(board))
    bd = evaluate(list(board))
    cat = me[0]
    base = {0: 0.10, 1: 0.40, 2: 0.58, 3: 0.72, 4: 0.80,
            5: 0.86, 6: 0.93, 7: 0.98, 8: 1.00}[cat]
    if me <= bd:                       # our hole cards add nothing
        return base * 0.30
    if cat == 1:                       # pairs: is it top pair or better?
        pair_rank = me[1]
        board_top = max(c // 4 + 2 for c in board)
        hole_ranks = {c // 4 + 2 for c in hole}
        if pair_rank in hole_ranks and pair_rank > board_top:
            base = 0.52               # overpair
        elif pair_rank >= board_top:
            base = 0.47               # top pair
        else:
            base = 0.33               # middle/bottom pair
    return base


def draw_bonus(hole, board):
    """Equity bonus for flush / open-ended straight draws (flop & turn only)."""
    if len(board) >= 5 or not board:
        return 0.0
    cards = list(hole) + list(board)
    bonus = 0.0
    scnt = Counter(c % 4 for c in cards)
    for s, n in scnt.items():
        if n == 4 and any(c % 4 == s for c in hole):
            bonus += 0.18
            break
    uniq = sorted({c // 4 + 2 for c in cards})
    if 14 in uniq:
        uniq = [1] + uniq
    run = 1
    for i in range(1, len(uniq)):
        run = run + 1 if uniq[i] == uniq[i - 1] + 1 else 1
        if run >= 4:
            bonus += 0.15
            break
    if len(board) == 4:                # one card to come, not two
        bonus *= 0.55
    return min(bonus, 0.30)


def mc_equity(hole, board, n_opps, iters, rng):
    """Monte-Carlo equity of `hole` vs n_opps random hands."""
    n_opps = max(1, n_opps)
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(board)
    total = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, 2 * n_opps + need_board)
        full = list(board) + draw[:need_board]
        mine = evaluate(list(hole) + full)
        best_opp = max(evaluate([draw[need_board + 2 * i],
                                 draw[need_board + 2 * i + 1]] + full)
                       for i in range(n_opps))
        if mine > best_opp:
            total += 1.0
        elif mine == best_opp:
            total += 0.5
    return total / iters


def pot_odds(state):
    tc = state["to_call"]
    return tc / (state["pot"] + tc) if tc > 0 else 0.0


ALL_IN = 10 ** 9  # engine clamps raises to stack size


# ----------------------------------------------------------------------------
# Strategies.  act(state) -> ("fold" | "call" | "raise", raise_to_total)
# "call" with to_call == 0 is a check; "raise" amount is total chips committed
# this street.  The engine clamps every action to something legal.
# ----------------------------------------------------------------------------

class AllInManiac:
    """Player 1's entire poker career:  if my_turn: bet = ALL IN. fi"""
    name = "LEEROY (ALL-IN)"

    def act(self, state):
        return ("raise", ALL_IN)


class Professor:
    """Tight-aggressive. Chen ranges by position, c-bets, pot-odds calls."""
    name = "The Professor"

    def act(self, state):
        rng = state["rng"]
        bb = state["bb"]
        if not state["board"]:
            return self._preflop(state, rng, bb)
        return self._postflop(state, rng, bb)

    def _preflop(self, state, rng, bb):
        ch = chen_score(state["hole"])
        stack_bb = state["my_stack"] / bb
        late = state["position"] >= state["num_players"] - 2
        if stack_bb < 12:                                   # push/fold mode
            return ("raise", ALL_IN) if ch >= 8.5 - (2 if late else 0) else ("fold", 0)
        big_bet = state["to_call"] > 3 * bb
        if big_bet:                                         # facing a raise/shove
            if ch >= 11:
                return ("raise", ALL_IN)
            if ch >= 9.5 and pot_odds(state) < 0.45:
                return ("call", 0)
            return ("fold", 0)
        if ch >= 9:
            return ("raise", state["current_bet"] + 3 * bb)
        if ch >= 7 and late:
            return ("raise", state["current_bet"] + 2 * bb) if rng.random() < 0.6 else ("call", 0)
        if ch >= 6 and state["to_call"] <= bb:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, state, rng, bb):
        s = made_strength(state["hole"], state["board"]) + draw_bonus(state["hole"], state["board"])
        pot = state["pot"]
        if state["to_call"] == 0:
            if s >= 0.65:
                return ("raise", state["my_committed"] + int(pot * 0.6) + bb)
            if state["was_aggressor"] and (s >= 0.40 or rng.random() < 0.25):
                return ("raise", state["my_committed"] + int(pot * 0.5) + bb)  # c-bet
            return ("call", 0)
        if s >= 0.75:
            return ("raise", state["current_bet"] + max(int(pot * 0.7), bb))
        if s * 0.92 > pot_odds(state):
            return ("call", 0)
        return ("fold", 0)


class Cowboy:
    """Loose-aggressive. Wide ranges, 3-bets, steals, barrels, semi-bluffs."""
    name = "The Cowboy"

    def act(self, state):
        rng = state["rng"]
        bb = state["bb"]
        if not state["board"]:
            return self._preflop(state, rng, bb)
        return self._postflop(state, rng, bb)

    def _preflop(self, state, rng, bb):
        ch = chen_score(state["hole"])
        late = state["position"] >= state["num_players"] - 2
        if state["my_stack"] / bb < 10:
            return ("raise", ALL_IN) if ch >= 7 else ("fold", 0)
        if state["to_call"] > 3 * bb:
            if ch >= 10.5:
                return ("raise", ALL_IN)
            if ch >= 8 and pot_odds(state) < 0.42:
                return ("call", 0)
            return ("fold", 0)
        if state["num_raises"] == 0 and late and rng.random() < 0.45:
            return ("raise", state["current_bet"] + int(2.5 * bb))       # steal
        if ch >= 7:
            if state["num_raises"] >= 1 and rng.random() < 0.20:
                return ("raise", state["current_bet"] + 3 * bb)          # 3-bet
            return ("raise", state["current_bet"] + int(2.5 * bb))
        if ch >= 5 and pot_odds(state) < 0.30:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, state, rng, bb):
        dr = draw_bonus(state["hole"], state["board"])
        s = made_strength(state["hole"], state["board"]) + dr
        pot = state["pot"]
        if state["to_call"] == 0:
            if s >= 0.60 or dr >= 0.15:
                return ("raise", state["my_committed"] + int(pot * 0.8) + bb)
            if rng.random() < 0.35:
                return ("raise", state["my_committed"] + int(pot * 0.6) + bb)  # bluff
            return ("call", 0)
        if s >= 0.70 or (dr >= 0.15 and rng.random() < 0.5):
            return ("raise", state["current_bet"] + max(int(pot * 0.8), bb))
        if s > pot_odds(state):
            return ("call", 0)
        if rng.random() < 0.08 and state["to_call"] < pot * 0.5:
            return ("call", 0)                                            # float
        return ("fold", 0)


class Actuary:
    """Pure pot-odds mathematician: Monte-Carlo equity on every decision."""
    name = "The Actuary"

    def act(self, state):
        rng = state["rng"]
        bb = state["bb"]
        n_opps = max(1, state["num_active"] - 1)
        iters = 25 if not state["board"] else 45
        eq = mc_equity(state["hole"], state["board"], n_opps, iters, rng)
        pot = state["pot"]
        fair_share = 1.0 / state["num_active"]
        if state["my_stack"] / bb < 10 and not state["board"]:
            return ("raise", ALL_IN) if eq > fair_share + 0.10 else ("fold", 0)
        if state["to_call"] == 0:
            if eq > fair_share + 0.18:
                return ("raise", state["my_committed"] + int(pot * 0.65) + bb)
            if eq > fair_share + 0.08:
                return ("raise", state["my_committed"] + int(pot * 0.4) + bb)
            return ("call", 0)
        po = pot_odds(state)
        if eq > 0.55 and eq - po > 0.20:
            return ("raise", state["current_bet"] + max(int(pot * 0.75), bb))
        if eq > po + 0.06:
            return ("call", 0)
        return ("fold", 0)


class Rock:
    """Ultra-tight trapper: premium hands only, slow-plays monsters,
    set-mines small pairs cheaply, push/fold when short."""
    name = "The Rock"

    def act(self, state):
        rng = state["rng"]
        bb = state["bb"]
        hole = state["hole"]
        if not state["board"]:
            ch = chen_score(hole)
            is_pair = hole[0] // 4 == hole[1] // 4
            if state["my_stack"] / bb < 8:
                return ("raise", ALL_IN) if ch >= 7 else ("fold", 0)
            if ch >= 10:
                if state["to_call"] > 3 * bb:
                    return ("raise", ALL_IN)
                return ("raise", state["current_bet"] + 3 * bb)
            if ch >= 8 and state["to_call"] <= 2 * bb:
                return ("call", 0)
            if is_pair and state["to_call"] <= max(bb, state["my_stack"] // 20):
                return ("call", 0)                                # set-mine
            return ("fold", 0)
        s = made_strength(hole, state["board"])
        pot = state["pot"]
        street = len(state["board"])
        if s >= 0.85:                                             # monster: trap
            if street == 3 and state["to_call"] == 0 and rng.random() < 0.6:
                return ("call", 0)                                # slow-play flop
            if state["to_call"] > 0:
                return ("raise", state["current_bet"] + max(int(pot * 1.0), bb))
            return ("raise", state["my_committed"] + int(pot * 0.8) + bb)
        if s >= 0.62:
            if state["to_call"] == 0:
                return ("raise", state["my_committed"] + int(pot * 0.5) + bb)
            return ("call", 0) if pot_odds(state) < 0.40 else ("fold", 0)
        if state["to_call"] == 0:
            return ("call", 0)
        dr = draw_bonus(hole, state["board"])
        if dr > 0 and pot_odds(state) < dr:
            return ("call", 0)
        return ("fold", 0)


class Shark:
    """Adaptive exploiter. Profiles opponents from observed actions only:
    all-in frequency, aggression, fold rate — then adjusts its ranges.
    Notably: detects all-in maniacs and snap-calls them with any hand that
    beats a random hand."""
    name = "The Shark"

    def act(self, state):
        rng = state["rng"]
        bb = state["bb"]
        stats = state["opp_stats"]
        aggressor = state["aggressor"]
        agg_stats = stats.get(aggressor) if aggressor is not None else None
        maniac_bet = (agg_stats is not None and agg_stats["acts"] >= 5
                      and agg_stats["allins"] / agg_stats["acts"] > 0.40)

        if not state["board"]:
            return self._preflop(state, rng, bb, maniac_bet)
        return self._postflop(state, rng, bb, maniac_bet, stats)

    def _preflop(self, state, rng, bb, maniac_bet):
        ch = chen_score(state["hole"])
        hole = state["hole"]
        r1, r2 = sorted((hole[0] // 4 + 2, hole[1] // 4 + 2), reverse=True)
        is_pair = r1 == r2
        facing_shove = state["to_call"] >= state["my_stack"] * 0.6
        if facing_shove and maniac_bet:
            # He shoves random cards; call with anything ahead of random.
            good = is_pair and r1 >= 6
            good = good or (r1 == 14 and r2 >= 9)
            good = good or (r1 == 13 and r2 >= 11)
            good = good or ch >= 8
            return ("call", 0) if good else ("fold", 0)
        if state["my_stack"] / bb < 11:
            late = state["position"] >= state["num_players"] - 2
            return ("raise", ALL_IN) if ch >= (7 if late else 8.5) else ("fold", 0)
        if state["to_call"] > 3 * bb:
            if ch >= 11:
                return ("raise", ALL_IN)
            if ch >= 9 and pot_odds(state) < 0.42:
                return ("call", 0)
            return ("fold", 0)
        # steal wide if the table has been folding a lot
        opp = state["opp_stats"]
        folds = sum(s["folds"] for s in opp.values())
        acts = max(1, sum(s["acts"] for s in opp.values()))
        tight_table = folds / acts > 0.5
        late = state["position"] >= state["num_players"] - 2
        if state["num_raises"] == 0 and late and tight_table and ch >= 5:
            return ("raise", state["current_bet"] + int(2.5 * bb))
        if ch >= 8.5:
            return ("raise", state["current_bet"] + 3 * bb)
        if ch >= 6.5 and state["to_call"] <= 2 * bb:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, state, rng, bb, maniac_bet, stats):
        s = made_strength(state["hole"], state["board"])
        dr = draw_bonus(state["hole"], state["board"])
        pot = state["pot"]
        if maniac_bet and state["to_call"] > 0:
            # vs a maniac's bet our made hands are way ahead of random
            eq = mc_equity(state["hole"], state["board"], 1, 40, state["rng"])
            return ("call", 0) if eq > pot_odds(state) + 0.03 else ("fold", 0)
        if state["to_call"] == 0:
            if s >= 0.62:
                return ("raise", state["my_committed"] + int(pot * 0.65) + bb)
            # bluff more into opponents who fold a lot
            folds = sum(t["folds"] for t in stats.values())
            acts = max(1, sum(t["acts"] for t in stats.values()))
            bluff_freq = 0.15 + 0.25 * (folds / acts)
            if state["was_aggressor"] and rng.random() < bluff_freq:
                return ("raise", state["my_committed"] + int(pot * 0.55) + bb)
            return ("call", 0)
        if s >= 0.72:
            return ("raise", state["current_bet"] + max(int(pot * 0.75), bb))
        if (s + dr) * 0.95 > pot_odds(state):
            return ("call", 0)
        return ("fold", 0)


# ----------------------------------------------------------------------------
# Table engine — no-limit betting, side pots, blinds, eliminations
# ----------------------------------------------------------------------------

class Player:
    def __init__(self, pid, name, strategy, stack):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = None


def play_hand(seats, button, sb_amt, bb_amt, rng, table_stats):
    """Play one hand among `seats` (all stacks > 0). Mutates stacks."""
    n = len(seats)
    deck = list(range(52))
    rng.shuffle(deck)
    for p in seats:
        p.hole = (deck.pop(), deck.pop())

    contrib = {p.pid: 0 for p in seats}          # total this hand
    round_commit = {p.pid: 0 for p in seats}     # this street
    folded, allin = set(), set()

    def commit(p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        contrib[p.pid] += amount
        round_commit[p.pid] += amount
        if p.stack == 0:
            allin.add(p.pid)
        return amount

    if n == 2:
        sb_i, bb_i = button, (button + 1) % 2
    else:
        sb_i, bb_i = (button + 1) % n, (button + 2) % n
    commit(seats[sb_i], sb_amt)
    commit(seats[bb_i], bb_amt)

    board = []
    aggressor = {"pid": None}

    def active():
        return [p for p in seats if p.pid not in folded]

    def betting_round(start, current_bet, preflop):
        min_raise = bb_amt
        num_raises = 0
        order = [seats[(start + i) % n] for i in range(n)]
        pending = [p for p in order
                   if p.pid not in folded and p.pid not in allin]
        while pending:
            p = pending.pop(0)
            if p.pid in folded or p.pid in allin:
                continue
            if len(active()) <= 1:
                break
            to_call = current_bet - round_commit[p.pid]
            st = table_stats[p.pid]
            state = {
                "hole": p.hole, "board": board,
                "pot": sum(contrib.values()),
                "to_call": to_call, "current_bet": current_bet,
                "my_stack": p.stack, "my_committed": round_commit[p.pid],
                "bb": bb_amt, "sb": sb_amt,
                "num_players": n, "num_active": len(active()),
                "position": order.index(p),
                "num_raises": num_raises,
                "aggressor": aggressor["pid"],
                "was_aggressor": aggressor["pid"] == p.pid,
                "opp_stats": {q.pid: table_stats[q.pid]
                              for q in seats if q.pid != p.pid},
                "rng": rng,
            }
            action, amt = p.strategy.act(state)
            st["acts"] += 1

            if action == "fold" and to_call == 0:
                action = "call"                               # check instead
            if action == "raise":
                max_to = round_commit[p.pid] + p.stack
                raise_to = min(amt, max_to)
                min_to = current_bet + min_raise
                if raise_to <= current_bet or (raise_to < min_to
                                               and raise_to < max_to):
                    action = "call"
                else:
                    increment = raise_to - current_bet
                    commit(p, raise_to - round_commit[p.pid])
                    if increment >= min_raise:
                        min_raise = increment
                    current_bet = raise_to
                    num_raises += 1
                    aggressor["pid"] = p.pid
                    st["raises"] += 1
                    if p.pid in allin:
                        st["allins"] += 1
                    j = order.index(p)
                    pending = [order[(j + 1 + k) % n] for k in range(n - 1)]
                    pending = [q for q in pending if q.pid not in folded
                               and q.pid not in allin]
                    continue
            if action == "call":
                if to_call > 0:
                    commit(p, to_call)
                    st["calls"] += 1
                    if p.pid in allin:
                        st["allins"] += 1
                continue
            folded.add(p.pid)
            st["folds"] += 1

    # Pre-flop
    start = button if n == 2 else (button + 3) % n
    betting_round(start, bb_amt, True)

    # Flop, turn, river
    for n_cards in (3, 1, 1):
        if len(active()) <= 1:
            break
        board.extend(deck.pop() for _ in range(n_cards))
        can_act = [p for p in active() if p.pid not in allin]
        if len(can_act) >= 2 or (len(can_act) == 1 and any(
                round_commit[q.pid] for q in active())):
            pass
        for pid in round_commit:
            round_commit[pid] = 0
        aggressor["pid"] = None
        if len(can_act) >= 2:
            betting_round(bb_i if n == 2 else (button + 1) % n, 0, False)

    # Showdown / pot distribution with side pots
    live = active()
    total_pot = sum(contrib.values())
    if len(live) == 1:
        live[0].stack += total_pot
        return

    scores = {p.pid: evaluate(list(p.hole) + board) for p in live}
    levels = sorted({contrib[p.pid] for p in live})
    prev = 0
    for lvl in levels:
        pot = sum(min(c, lvl) - min(c, prev) for c in contrib.values())
        prev = lvl
        if pot == 0:
            continue
        eligible = [p for p in live if contrib[p.pid] >= lvl]
        best = max(scores[p.pid] for p in eligible)
        winners = [p for p in eligible if scores[p.pid] == best]
        share, odd = divmod(pot, len(winners))
        for i, w in enumerate(winners):
            w.stack += share + (1 if i < odd else 0)


BLIND_SCHEDULE = [(10, 20), (15, 30), (25, 50), (40, 80), (60, 120),
                  (100, 200), (150, 300), (250, 500), (400, 800),
                  (600, 1200), (1000, 2000)]
HANDS_PER_LEVEL = 20
START_STACK = 1000


def make_players():
    return [
        Player(1, "LEEROY (ALL-IN)", AllInManiac(), START_STACK),
        Player(2, "The Professor", Professor(), START_STACK),
        Player(3, "The Cowboy", Cowboy(), START_STACK),
        Player(4, "The Actuary", Actuary(), START_STACK),
        Player(5, "The Rock", Rock(), START_STACK),
        Player(6, "The Shark", Shark(), START_STACK),
    ]


def run_tournament(seed):
    rng = random.Random(seed)
    players = make_players()
    total_chips = sum(p.stack for p in players)
    table_stats = {p.pid: {"acts": 0, "raises": 0, "calls": 0,
                           "folds": 0, "allins": 0} for p in players}
    finish_order = []                  # first eliminated ... first
    button = rng.randrange(len(players))
    hand_no = 0
    while True:
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1:
            break
        level = min(hand_no // HANDS_PER_LEVEL, len(BLIND_SCHEDULE) - 1)
        sb, bb = BLIND_SCHEDULE[level]
        button = button % len(alive)
        play_hand(alive, button, sb, bb, rng, table_stats)
        assert sum(p.stack for p in players) == total_chips, "chips leaked!"
        busted = [p for p in alive if p.stack == 0]
        busted.sort(key=lambda p: p.pid)
        finish_order.extend(busted)
        button = (button + 1) % max(1, len([p for p in players if p.stack > 0]))
        hand_no += 1
        if hand_no > 5000:             # unreachable safety net
            break
    winner = max(players, key=lambda p: p.stack)
    finish_order.append(winner)
    finish_order.reverse()             # index 0 = champion
    return winner, finish_order, hand_no


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    wins = Counter()
    placements = {p.pid: [] for p in make_players()}
    hands_total = 0
    for i in range(args.sims):
        winner, order, hands = run_tournament(args.seed + i)
        wins[winner.name] += 1
        hands_total += hands
        for place, p in enumerate(order, start=1):
            placements[p.pid].append(place)

    names = [p.name for p in make_players()]
    print()
    print("=" * 62)
    print("  HOLD'EM ROYALE — WINNER HISTOGRAM "
          f"({args.sims} tournaments, seed {args.seed})")
    print("=" * 62)
    width = max(len(n) for n in names)
    top = max(wins.values()) if wins else 1
    for name in names:
        w = wins.get(name, 0)
        bar = "█" * max(1, round(w * 40 / top)) if w else ""
        print(f"  {name:<{width}} | {bar} {w}")
    print("-" * 62)
    print(f"  avg tournament length: {hands_total / args.sims:.0f} hands")
    print()
    print("  avg finishing position (1 = chicken dinner, 6 = first bust):")
    for pid, name in zip(range(1, 7), names):
        pl = placements[pid]
        avg = sum(pl) / len(pl)
        busts = sum(1 for x in pl if x == 6)
        print(f"  {name:<{width}} | avg {avg:.2f}   first-out {busts}x")
    print("=" * 62)


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
