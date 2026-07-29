#!/usr/bin/env python3
"""
Texas Hold'em tournament simulator — 6 players, winner-take-all.

Seat 1  "SuflairGPT"          : if my_turn then bet = ALL IN fi
Seat 2  "Tightbeard (TAG)"    : tight-aggressive, Chen-formula preflop, value-bets postflop
Seat 3  "Loki (LAG)"          : loose-aggressive, c-bets, bluffs, sticky calls
Seat 4  "The Rock (Nit)"      : premium hands only, punishes with monsters
Seat 5  "Pot-Odds Professor"  : Monte-Carlo equity vs pot odds, math-first
Seat 6  "Adaptive Anna"       : observes public actions, exploits maniacs & nits

No strategy has access to another strategy's code or private cards — each one
only sees the public game state (board, bets, stacks, action history) plus its
own hole cards.

Usage:
    python3 holdem_sim.py --sims 100 --seed 42
    python3 holdem_sim.py --selftest
"""

import argparse
import random
import sys
from collections import Counter, deque

# ----------------------------------------------------------------------------
# Cards & 7-card evaluator
# ----------------------------------------------------------------------------
# A card is an int 0..51: rank = card % 13 + 2 (2..14, 14 = Ace), suit = card // 13
RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"


def card_str(c):
    return RANK_CHARS[c % 13] + SUIT_CHARS[c // 13]


def _best_straight_high(rankset):
    rs = set(rankset)
    if 14 in rs:
        rs.add(1)  # wheel
    for high in range(14, 4, -1):
        if all(high - i in rs for i in range(5)):
            return high
    return 0


def evaluate7(cards):
    """Return a comparable tuple ranking the best 5-card hand out of 7 cards.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
    3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = [c % 13 + 2 for c in cards]
    suits = [c // 13 for c in cards]

    suit_count = Counter(suits)
    flush_suit = next((s for s, n in suit_count.items() if n >= 5), None)
    if flush_suit is not None:
        flush_ranks = sorted((r for r, s in zip(ranks, suits) if s == flush_suit),
                             reverse=True)
        sf = _best_straight_high(flush_ranks)
        if sf:
            return (8, sf, 0, 0, 0, 0)

    cnt = Counter(ranks)
    # sort by (multiplicity, rank) descending
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker, 0, 0, 0)

    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0], 0, 0, 0)

    if flush_suit is not None:
        top5 = flush_ranks[:5]
        return (5, top5[0], top5[1], top5[2], top5[3], top5[4])

    st = _best_straight_high(set(ranks))
    if st:
        return (4, st, 0, 0, 0, 0)

    if groups[0][1] == 3:
        t = groups[0][0]
        ks = sorted((r for r in ranks if r != t), reverse=True)[:2]
        return (3, t, ks[0], ks[1], 0, 0)

    if groups[0][1] == 2 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kicker, 0, 0)

    if groups[0][1] == 2:
        p = groups[0][0]
        ks = sorted((r for r in ranks if r != p), reverse=True)[:3]
        return (1, p, ks[0], ks[1], ks[2], 0)

    top5 = sorted(ranks, reverse=True)[:5]
    return (0, top5[0], top5[1], top5[2], top5[3], top5[4])


# ----------------------------------------------------------------------------
# Shared, "public-information-only" helper math for strategies
# ----------------------------------------------------------------------------

def chen_score(hole):
    """Chen formula: quick preflop hand strength (~ -1 .. 20)."""
    r1, r2 = sorted((hole[0] % 13 + 2, hole[1] % 13 + 2), reverse=True)
    suited = (hole[0] // 13) == (hole[1] // 13)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(r1, r1 / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    gap = r1 - r2 - 1
    score = pts
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        score += 1
    if suited:
        score += 2
    return score


def sampled_strength(hole, board, rng, n=40):
    """Fraction of random opponent hole-card pairs we beat on the CURRENT board
    (ties count half). Pure Monte Carlo over public info + own cards."""
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    mine = evaluate7(list(hole) + list(board)) if len(board) >= 3 else None
    if mine is None:
        return 0.5
    wins = 0.0
    for _ in range(n):
        opp = rng.sample(deck, 2)
        theirs = evaluate7(opp + list(board))
        if mine > theirs:
            wins += 1.0
        elif mine == theirs:
            wins += 0.5
    return wins / n


def equity_vs_random(hole, board, rng, n=50, n_opp=1):
    """Monte-Carlo equity: complete the board to 5 cards and race against
    n_opp uniformly random hands. Returns win probability (splits pro-rated)."""
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    total = 0.0
    for _ in range(n):
        draw = rng.sample(deck, need + 2 * n_opp)
        full_board = list(board) + draw[:need]
        mine = evaluate7(list(hole) + full_board)
        best_opp = None
        n_best = 0
        for k in range(n_opp):
            opp = draw[need + 2 * k: need + 2 * k + 2]
            v = evaluate7(opp + full_board)
            if best_opp is None or v > best_opp:
                best_opp, n_best = v, 1
            elif v == best_opp:
                n_best += 1
        if mine > best_opp:
            total += 1.0
        elif mine == best_opp:
            total += 1.0 / (1 + n_best)
    return total / n


# ----------------------------------------------------------------------------
# Strategies
# ----------------------------------------------------------------------------
# A strategy implements decide(view) -> ('fold'|'call'|'raise', raise_to)
# where raise_to is the total street commitment target (engine legalizes it).
# `view` exposes ONLY public information + the strategy's own hole cards.

class AllInBot:
    """Seat 1. The whole strategy:  if my_turn: bet = ALL IN  fi"""

    name = "SuflairGPT"

    def __init__(self, rng):
        pass

    def new_hand(self, view):
        pass

    def decide(self, view):
        return ("raise", view["my_committed"] + view["my_stack"])  # ALL IN


class TightAggressive:
    """Seat 2. Classic TAG: narrow preflop range played fast, value-bets made
    hands, respects big aggression without equity."""

    name = "Tightbeard (TAG)"

    def __init__(self, rng):
        self.rng = rng

    def new_hand(self, view):
        pass

    def decide(self, view):
        hole, board = view["hole"], view["board"]
        to_call, pot = view["to_call"], view["pot"]
        bb = view["big_blind"]
        stack = view["my_stack"]

        if not board:  # ----- preflop -----
            s = chen_score(hole)
            s += 0.5 * (view["seats_behind"] == 0)  # late position bonus
            big_pressure = to_call > 4 * bb
            if big_pressure:
                # Facing a raise/shove: continue only with the top of the range.
                if s >= 11 or (to_call >= stack * 0.6 and
                               equity_vs_random(hole, board, self.rng, n=60,
                                                n_opp=1) > 0.55):
                    return ("raise", view["my_committed"] + stack)
                if s >= 9 and to_call <= stack * 0.25:
                    return ("call", 0)
                return ("fold", 0)
            if s >= 9:
                return ("raise", max(3 * bb, view["current_bet"] * 3))
            if s >= 7:
                return ("raise", 3 * bb) if to_call <= bb else ("call", 0)
            if s >= 5 and to_call <= bb:
                return ("call", 0)
            return ("fold", 0)

        # ----- postflop -----
        opp = max(1, view["num_unfolded"] - 1)
        hs = sampled_strength(hole, board, self.rng, n=45) ** opp
        if to_call == 0:
            if hs > 0.62:
                return ("raise", view["my_committed"] + max(bb, int(pot * 0.66)))
            return ("call", 0)  # check
        pot_odds = to_call / (pot + to_call)
        if hs > 0.85:
            return ("raise", view["my_committed"] + to_call + max(bb, pot))
        if hs > pot_odds + 0.05:
            return ("call", 0)
        return ("fold", 0)


class LooseAggressive:
    """Seat 3. LAG: wide range, frequent raises, continuation bets and the
    occasional pure bluff — but bails against real resistance."""

    name = "Loki (LAG)"

    def __init__(self, rng):
        self.rng = rng
        self.was_aggressor = False

    def new_hand(self, view):
        self.was_aggressor = False

    def decide(self, view):
        hole, board = view["hole"], view["board"]
        to_call, pot = view["to_call"], view["pot"]
        bb = view["big_blind"]
        stack = view["my_stack"]

        if not board:  # ----- preflop -----
            s = chen_score(hole)
            if to_call > 5 * bb:  # someone is serious
                if s >= 10 or (to_call >= stack * 0.6 and
                               equity_vs_random(hole, board, self.rng, n=60,
                                                n_opp=1) > 0.54):
                    self.was_aggressor = True
                    return ("raise", view["my_committed"] + stack)
                return ("call", 0) if (s >= 8 and to_call <= stack * 0.2) else ("fold", 0)
            if s >= 5:
                if self.rng.random() < 0.75:
                    self.was_aggressor = True
                    return ("raise", max(int(2.5 * bb), view["current_bet"] * 2 + bb))
                return ("call", 0)
            if to_call <= bb and self.rng.random() < 0.4:
                return ("call", 0)  # speculative limp/defend
            return ("fold", 0)

        # ----- postflop -----
        opp = max(1, view["num_unfolded"] - 1)
        hs = sampled_strength(hole, board, self.rng, n=40) ** opp
        if to_call == 0:
            if self.was_aggressor and self.rng.random() < 0.6:  # c-bet almost anything
                return ("raise", view["my_committed"] + max(bb, int(pot * 0.5)))
            if hs > 0.55 or self.rng.random() < 0.08:  # value or pure bluff
                return ("raise", view["my_committed"] + max(bb, int(pot * 0.6)))
            return ("call", 0)
        pot_odds = to_call / (pot + to_call)
        if hs > 0.82 or (hs > 0.6 and self.rng.random() < 0.15):
            return ("raise", view["my_committed"] + to_call + max(bb, int(pot * 0.8)))
        if hs > pot_odds - 0.02:  # sticky by nature
            return ("call", 0)
        return ("fold", 0)


class Nit:
    """Seat 4. The Rock: folds almost everything, but when it enters a pot it
    means business. Monsters get shoved."""

    name = "The Rock (Nit)"

    def __init__(self, rng):
        self.rng = rng

    def new_hand(self, view):
        pass

    def decide(self, view):
        hole, board = view["hole"], view["board"]
        to_call = view["to_call"]
        bb = view["big_blind"]
        stack = view["my_stack"]
        r1, r2 = sorted((hole[0] % 13 + 2, hole[1] % 13 + 2), reverse=True)
        pair = r1 == r2
        suited = hole[0] // 13 == hole[1] // 13

        if not board:  # ----- preflop -----
            premium = (pair and r1 >= 12) or (r1 == 14 and r2 == 13)      # QQ+/AK
            strong = (pair and r1 >= 9) or (r1 == 14 and r2 >= 12) or \
                     (r1 == 13 and r2 == 12 and suited)                    # 99+/AQ+/KQs
            if premium:
                return ("raise", view["my_committed"] + stack)  # get it in good
            if strong:
                if to_call <= stack * 0.15:
                    return ("raise", max(4 * bb, view["current_bet"] * 3))
                return ("call", 0) if to_call <= stack * 0.35 else ("fold", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)

        # ----- postflop -----
        opp = max(1, view["num_unfolded"] - 1)
        hs = sampled_strength(hole, board, self.rng, n=45) ** opp
        pot_odds = to_call / (view["pot"] + to_call) if to_call else 0.0
        if hs > 0.9:
            return ("raise", view["my_committed"] + stack)
        if to_call == 0:
            if hs > 0.7:
                return ("raise", view["my_committed"] + max(bb, view["pot"] // 2))
            return ("call", 0)
        if hs > max(0.75, pot_odds + 0.1):
            return ("call", 0)
        return ("fold", 0)


class PotOddsProfessor:
    """Seat 5. Every big decision is an equity calculation: Monte-Carlo win
    probability against random hands compared with the price being offered."""

    name = "Pot-Odds Professor"

    def __init__(self, rng):
        self.rng = rng

    def new_hand(self, view):
        pass

    def decide(self, view):
        hole, board = view["hole"], view["board"]
        to_call, pot = view["to_call"], view["pot"]
        bb = view["big_blind"]
        stack = view["my_stack"]
        opp = max(1, view["num_unfolded"] - 1)

        if not board:  # ----- preflop -----
            s = chen_score(hole)
            if to_call >= stack * 0.3:  # big money: do the real math
                eq = equity_vs_random(hole, board, self.rng, n=70, n_opp=1)
                price = to_call / (pot + to_call)
                if eq > 0.58:
                    return ("raise", view["my_committed"] + stack)
                return ("call", 0) if eq > price + 0.03 else ("fold", 0)
            if s >= 9:
                return ("raise", max(3 * bb, view["current_bet"] * 3))
            if s >= 6:
                return ("call", 0) if to_call <= 3 * bb else ("fold", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)

        # ----- postflop -----
        eq = equity_vs_random(hole, board, self.rng, n=60, n_opp=opp)
        if to_call == 0:
            if eq > 0.6:
                return ("raise", view["my_committed"] + max(bb, int(pot * 0.7)))
            return ("call", 0)
        price = to_call / (pot + to_call)
        if eq > 0.72:
            return ("raise", view["my_committed"] + to_call + max(bb, pot))
        if eq > price + 0.02:
            return ("call", 0)
        return ("fold", 0)


class AdaptiveAnna:
    """Seat 6. Watches everyone's PUBLIC actions across hands (shove rate,
    raise rate, looseness) and adjusts: waits out maniacs with real hands,
    steals from nits, calls stations thin."""

    name = "Adaptive Anna"

    def __init__(self, rng):
        self.rng = rng

    def new_hand(self, view):
        pass

    def _maniacs_in(self, view):
        """Unfolded opponents whose observed shove rate marks them as maniacs."""
        out = []
        for o in view["opponents"]:
            st = view["stats"][o["seat"]]
            if st["hands"] >= 5 and st["shoves"] / st["hands"] > 0.4 and not o["folded"]:
                out.append(o)
        return out

    def decide(self, view):
        hole, board = view["hole"], view["board"]
        to_call, pot = view["to_call"], view["pot"]
        bb = view["big_blind"]
        stack = view["my_stack"]
        maniacs = self._maniacs_in(view)

        if not board:  # ----- preflop -----
            s = chen_score(hole)
            facing_shove = to_call >= stack * 0.5
            if facing_shove and maniacs:
                # A wild shover's range is ~random: a modest hand is a favorite.
                eq = equity_vs_random(hole, board, self.rng, n=80, n_opp=1)
                if eq > 0.53:
                    return ("raise", view["my_committed"] + stack)
                return ("fold", 0)
            if facing_shove:  # a sane player shoved: respect it
                if s >= 11:
                    return ("raise", view["my_committed"] + stack)
                return ("fold", 0)
            if maniacs:
                # Maniac still to act behind: flat premium hands, dodge the rest.
                if s >= 9:
                    return ("call", 0) if to_call > 0 else ("raise", 3 * bb)
                return ("call", 0) if to_call == 0 else ("fold", 0)
            # No maniacs around: standard solid play + steal from tight tables
            tight_table = all(
                view["stats"][o["seat"]]["hands"] >= 5 and
                view["stats"][o["seat"]]["vpip"] / view["stats"][o["seat"]]["hands"] < 0.3
                for o in view["opponents"] if not o["folded"]
            )
            if s >= 9:
                return ("raise", max(3 * bb, view["current_bet"] * 3))
            if s >= 5 and tight_table and to_call <= bb:
                return ("raise", int(2.5 * bb))  # steal
            if s >= 6 and to_call <= 2 * bb:
                return ("call", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)

        # ----- postflop -----
        opp_n = max(1, view["num_unfolded"] - 1)
        hs = sampled_strength(hole, board, self.rng, n=50) ** opp_n
        # Aggressive opponents bluff more: loosen calls. Passive: tighten.
        avg_aggr = 0.0
        live = [o for o in view["opponents"] if not o["folded"]]
        for o in live:
            st = view["stats"][o["seat"]]
            if st["actions"]:
                avg_aggr += st["raises"] / st["actions"]
        avg_aggr = avg_aggr / len(live) if live else 0.0
        margin = 0.06 - min(0.08, avg_aggr * 0.2)
        if to_call == 0:
            if hs > 0.65:
                return ("raise", view["my_committed"] + max(bb, int(pot * 0.6)))
            return ("call", 0)
        pot_odds = to_call / (pot + to_call)
        if hs > 0.87:
            return ("raise", view["my_committed"] + to_call + max(bb, pot))
        if hs > pot_odds + margin:
            return ("call", 0)
        return ("fold", 0)


STRATEGY_CLASSES = [AllInBot, TightAggressive, LooseAggressive, Nit,
                    PotOddsProfessor, AdaptiveAnna]


# ----------------------------------------------------------------------------
# Tournament engine
# ----------------------------------------------------------------------------

class Table:
    def __init__(self, seed, start_stack=1000, sb=10, blind_level_hands=25,
                 max_hands=5000):
        self.rng = random.Random(seed)
        self.n = len(STRATEGY_CLASSES)
        self.stacks = [start_stack] * self.n
        self.start_stack = start_stack
        self.base_sb = sb
        self.blind_level_hands = blind_level_hands
        self.max_hands = max_hands
        self.strategies = [cls(random.Random(seed * 1000 + i))
                           for i, cls in enumerate(STRATEGY_CLASSES)]
        self.button = self.rng.randrange(self.n)
        self.hand_no = 0
        self.bust_order = []  # seats in order of elimination
        # Public per-seat action stats (visible to every strategy)
        self.stats = [{"hands": 0, "vpip": 0, "raises": 0, "actions": 0,
                       "shoves": 0} for _ in range(self.n)]

    # -- helpers ------------------------------------------------------------
    def alive(self):
        return [i for i in range(self.n) if self.stacks[i] > 0]

    def blinds(self):
        level = min(self.hand_no // self.blind_level_hands, 16)
        sb = self.base_sb * (2 ** level)
        return sb, sb * 2

    def make_view(self, seat, hole, board, committed, folded, allin, pot,
                  current_bet, big_blind, order):
        after = order[order.index(seat) + 1:]
        seats_behind = sum(1 for s in after if not folded[s] and not allin[s])
        return {
            "hole": tuple(hole[seat]),
            "board": tuple(board),
            "pot": pot,
            "to_call": current_bet - committed[seat],
            "current_bet": current_bet,
            "my_committed": committed[seat],
            "my_stack": self.stacks[seat],
            "my_seat": seat,
            "big_blind": big_blind,
            "num_unfolded": sum(1 for s in self.alive_in_hand
                                if not folded[s]),
            "seats_behind": seats_behind,
            "opponents": [
                {"seat": s, "stack": self.stacks[s], "committed": committed[s],
                 "folded": folded[s], "all_in": allin[s]}
                for s in self.alive_in_hand if s != seat
            ],
            "stats": self.stats,
        }

    # -- one hand -----------------------------------------------------------
    def play_hand(self):
        players = self.alive()
        if len(players) < 2:
            return
        self.alive_in_hand = players
        sb_amt, bb_amt = self.blinds()

        deck = list(range(52))
        self.rng.shuffle(deck)
        hole = {s: [deck.pop(), deck.pop()] for s in players}
        board = []

        # positions: seats in order starting left of the button
        order_all = []
        i = (self.button + 1) % self.n
        while len(order_all) < len(players):
            if self.stacks[i] > 0:
                order_all.append(i)
            i = (i + 1) % self.n
        if len(players) == 2:
            sb_seat, bb_seat = order_all[1], order_all[0]  # button posts SB
        else:
            sb_seat, bb_seat = order_all[0], order_all[1]

        contrib = {s: 0 for s in players}      # total across all streets
        committed = {s: 0 for s in players}    # current street
        folded = {s: False for s in players}
        allin = {s: False for s in players}

        def put(seat, amount):
            amount = min(amount, self.stacks[seat])
            self.stacks[seat] -= amount
            committed[seat] += amount
            contrib[seat] += amount
            if self.stacks[seat] == 0:
                allin[seat] = True
            return amount

        put(sb_seat, sb_amt)
        put(bb_seat, bb_amt)

        for s in players:
            self.stats[s]["hands"] += 1
            self.strategies[s].new_hand(None)

        # -- betting round mechanics ----------------------------------------
        def betting_round(start_after, current_bet, min_raise, preflop=False):
            ring = order_all
            can_act = lambda s: not folded[s] and not allin[s]
            # queue of seats that still owe an action
            pending = deque()
            start_i = ring.index(start_after)
            for k in range(len(ring)):
                s = ring[(start_i + k) % len(ring)]
                if can_act(s):
                    pending.append(s)
            while pending:
                s = pending.popleft()
                if not can_act(s):
                    continue
                if sum(1 for x in players if not folded[x]) <= 1:
                    break
                pot = sum(contrib.values())
                view = self.make_view(s, hole, board, committed, folded,
                                      allin, pot, current_bet, bb_amt, ring)
                action, raise_to = self.strategies[s].decide(view)
                to_call = current_bet - committed[s]
                self.stats[s]["actions"] += 1

                if action == "fold" and to_call == 0:
                    action = "call"  # a "fold" with nothing to call is a check
                if action == "fold":
                    folded[s] = True
                    continue
                if action == "call":
                    if to_call > 0:
                        put(s, to_call)
                        if preflop:
                            self.stats[s]["vpip"] += 1 if committed[s] > (
                                bb_amt if s == bb_seat else sb_amt if s == sb_seat else 0) else 0
                    continue
                # raise: legalize the target
                max_to = committed[s] + self.stacks[s]
                target = min(max(raise_to, current_bet + min_raise), max_to)
                if target <= current_bet:  # can't actually raise -> call/all-in
                    put(s, to_call)
                    continue
                full_raise = (target - current_bet) >= min_raise
                if full_raise:
                    min_raise = target - current_bet
                put(s, target - committed[s])
                self.stats[s]["raises"] += 1
                if preflop:
                    self.stats[s]["vpip"] += 1
                if allin[s] and preflop and not board:
                    self.stats[s]["shoves"] += 1
                new_bet = committed[s]
                if new_bet > current_bet:
                    current_bet = new_bet
                    if full_raise:  # reopen action for everyone else
                        pending.clear()
                        si = ring.index(s)
                        for k in range(1, len(ring)):
                            nxt = ring[(si + k) % len(ring)]
                            if can_act(nxt):
                                pending.append(nxt)
            return current_bet

        # -- streets --------------------------------------------------------
        def live():
            return [s for s in players if not folded[s]]

        def actors():
            return [s for s in players if not folded[s] and not allin[s]]

        # preflop
        if len(players) == 2:
            first = sb_seat
        else:
            first = order_all[2 % len(order_all)]
        if actors():
            betting_round(first if not allin[first] or True else first,
                          bb_amt, bb_amt, preflop=True)

        streets = [3, 1, 1]  # flop, turn, river
        for ncards in streets:
            if len(live()) <= 1:
                break
            for _ in range(ncards):
                board.append(deck.pop())
            if len(actors()) > 1:
                committed = {s: 0 for s in players}
                start = next(s for s in order_all
                             if not folded[s] and not allin[s])
                betting_round(start, 0, bb_amt)

        # -- resolution -----------------------------------------------------
        remaining = live()
        if len(remaining) == 1:
            self.stacks[remaining[0]] += sum(contrib.values())
        else:
            while len(board) < 5:
                board.append(deck.pop())
            ranks = {s: evaluate7(hole[s] + board) for s in remaining}
            # side pots by contribution level
            levels = sorted({contrib[s] for s in players if contrib[s] > 0})
            prev = 0
            for lvl in levels:
                pot_amt = sum(min(contrib[s], lvl) - min(contrib[s], prev)
                              for s in players)
                prev = lvl
                if pot_amt == 0:
                    continue
                eligible = [s for s in remaining if contrib[s] >= lvl]
                if not eligible:
                    # everyone at this level folded; give to overall best hand
                    eligible = remaining
                best = max(ranks[s] for s in eligible)
                winners = [s for s in eligible if ranks[s] == best]
                share, odd = divmod(pot_amt, len(winners))
                for w in winners:
                    self.stacks[w] += share
                # odd chips: first winner(s) left of the button
                for w in sorted(winners,
                                key=lambda s: order_all.index(s))[:odd]:
                    self.stacks[w] += 1

        assert sum(self.stacks) == self.start_stack * self.n, "chips leaked!"

        for s in players:
            if self.stacks[s] == 0:
                self.bust_order.append(s)

        # move the button to the next surviving seat
        for k in range(1, self.n + 1):
            cand = (self.button + k) % self.n
            if self.stacks[cand] > 0:
                self.button = cand
                break
        self.hand_no += 1

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        alive = self.alive()
        winner = alive[0] if len(alive) == 1 else max(
            alive, key=lambda s: self.stacks[s])
        return winner, self.hand_no, list(self.bust_order)


# ----------------------------------------------------------------------------
# Simulation harness & histogram
# ----------------------------------------------------------------------------

def run_sims(n_sims, seed, start_stack):
    names = [cls.name for cls in STRATEGY_CLASSES]
    wins = Counter()
    first_bust = Counter()
    hand_counts = []
    for i in range(n_sims):
        table = Table(seed=seed + i, start_stack=start_stack)
        winner, hands, busts = table.run()
        wins[winner] += 1
        if busts:
            first_bust[busts[0]] += 1
        hand_counts.append(hands)
        done = i + 1
        if done % 10 == 0:
            print(f"  ... {done}/{n_sims} tournaments done", flush=True)
    return names, wins, first_bust, hand_counts


def print_histogram(names, wins, first_bust, hand_counts, n_sims):
    width = 50
    top = max(wins.values()) if wins else 1
    lines = []
    lines.append("")
    lines.append("=" * 78)
    lines.append(" WINNER WINNER CHICKEN DINNER — tournament wins out of "
                 f"{n_sims} sims")
    lines.append("=" * 78)
    order = sorted(range(len(names)), key=lambda s: -wins[s])
    for s in order:
        w = wins[s]
        bar = "█" * max(1 if w else 0, round(w / top * width))
        lines.append(f"  P{s+1} {names[s]:<22} {w:>3} ({w / n_sims:>5.1%}) {bar}")
    lines.append("-" * 78)
    lines.append(f"  avg hands per tournament: {sum(hand_counts)/len(hand_counts):.1f}"
                 f"   (min {min(hand_counts)}, max {max(hand_counts)})")
    lines.append("")
    lines.append("  first player to bust, out of the tournaments with a bust:")
    fb_top = max(first_bust.values()) if first_bust else 1
    for s in sorted(range(len(names)), key=lambda s: -first_bust[s]):
        fb = first_bust[s]
        bar = "▒" * max(1 if fb else 0, round(fb / fb_top * 30))
        lines.append(f"  P{s+1} {names[s]:<22} {fb:>3} {bar}")
    lines.append("=" * 78)
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Self-test
# ----------------------------------------------------------------------------

def selftest():
    def cards(*ss):
        return [SUIT_CHARS.index(s[1]) * 13 + RANK_CHARS.index(s[0]) for s in ss]

    royal = evaluate7(cards("As", "Ks", "Qs", "Js", "Ts", "2d", "3c"))
    assert royal[0] == 8 and royal[1] == 14, royal
    quads = evaluate7(cards("9s", "9d", "9h", "9c", "Ks", "2d", "3c"))
    assert quads[:3] == (7, 9, 13), quads
    boat = evaluate7(cards("9s", "9d", "9h", "Kc", "Ks", "2d", "3c"))
    assert boat[:3] == (6, 9, 13), boat
    flush = evaluate7(cards("As", "9s", "7s", "4s", "2s", "Kd", "Kc"))
    assert flush[0] == 5 and flush[1] == 14, flush
    wheel = evaluate7(cards("As", "2d", "3h", "4c", "5s", "Kd", "9c"))
    assert wheel[:2] == (4, 5), wheel
    trips = evaluate7(cards("9s", "9d", "9h", "Kc", "Qs", "2d", "3c"))
    assert trips[:2] == (3, 9), trips
    twopair = evaluate7(cards("9s", "9d", "Kh", "Kc", "Qs", "2d", "3c"))
    assert twopair[:4] == (2, 13, 9, 12), twopair
    pair = evaluate7(cards("9s", "9d", "Ah", "Kc", "Qs", "2d", "3c"))
    assert pair[:2] == (1, 9), pair
    high = evaluate7(cards("9s", "7d", "Ah", "Kc", "Qs", "2d", "3c"))
    assert high[:2] == (0, 14), high
    # straight beats trips, flush beats straight
    assert wheel > trips and flush > wheel and boat > flush

    # chip conservation over a few tournaments
    for sd in range(3):
        t = Table(seed=1234 + sd, start_stack=500)
        t.run()
        assert sum(t.stacks) == 500 * t.n
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=1000)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    print(f"Running {args.sims} winner-take-all tournaments "
          f"(6 players, {args.stack} chips each, seed={args.seed})...")
    names, wins, first_bust, hand_counts = run_sims(args.sims, args.seed,
                                                    args.stack)
    report = print_histogram(names, wins, first_bust, hand_counts, args.sims)
    print(report)


if __name__ == "__main__":
    main()
