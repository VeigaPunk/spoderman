#!/usr/bin/env python3
"""Texas Hold'em tournament simulator.

6 players, identical starting stacks. Players 2-6 run elaborate strategies,
Player 1 runs "if my_turn then bet = All in fi". No strategy can see another
strategy's code -- only public actions at the table (as in real poker).

Runs N full tournaments (play until one player holds every chip) and prints
a histogram of champions.
"""

import random
import sys
from collections import Counter
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i + 2 for i, r in enumerate(RANKS)}


def new_deck(rng):
    deck = [(RANK_VAL[r], s) for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck


# ---------------------------------------------------------------- hand eval

def evaluate(cards):
    """Best 5-card hand value from 5-7 cards. Higher tuple wins."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    counts = Counter(ranks)
    by_count = sorted(counts.items(), key=lambda x: (-x[1], -x[0]))

    suits = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in suits.items() if n >= 5), None)

    def straight_high(rs):
        uniq = sorted(set(rs), reverse=True)
        if 14 in uniq:
            uniq.append(1)  # wheel
        run = 1
        for i in range(1, len(uniq)):
            run = run + 1 if uniq[i] == uniq[i - 1] - 1 else 1
            if run >= 5:
                return uniq[i] + 4
        return None

    if flush_suit:
        flush_ranks = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)
        sf = straight_high(flush_ranks)
        if sf:
            return (8, sf)

    if by_count[0][1] == 4:
        quad = by_count[0][0]
        kick = max(r for r in ranks if r != quad)
        return (7, quad, kick)

    if by_count[0][1] == 3 and by_count[1][1] >= 2:
        return (6, by_count[0][0], by_count[1][0])

    if flush_suit:
        return (5, *flush_ranks[:5])

    st = straight_high(ranks)
    if st:
        return (4, st)

    if by_count[0][1] == 3:
        trip = by_count[0][0]
        kicks = [r for r in ranks if r != trip][:2]
        return (3, trip, *kicks)

    if by_count[0][1] == 2 and by_count[1][1] == 2:
        hp, lp = by_count[0][0], by_count[1][0]
        kick = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kick)

    if by_count[0][1] == 2:
        pair = by_count[0][0]
        kicks = [r for r in ranks if r != pair][:3]
        return (1, pair, *kicks)

    return (0, *ranks[:5])


def preflop_score(hole):
    """Chen-like preflop strength score, roughly 0-20."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    hi = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2)
    score = hi
    if r1 == r2:
        score = max(5, hi * 2)
    if s1 == s2:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12 and r1 != r2:
        score += 1
    return score


def equity_estimate(hole, board, n_opponents, rng, rollouts=80):
    """Monte Carlo equity vs random opponent hands."""
    dead = set(hole) | set(board)
    deck = [(RANK_VAL[r], s) for r in RANKS for s in SUITS]
    deck = [c for c in deck if c not in dead]
    wins = 0.0
    need = 5 - len(board)
    for _ in range(rollouts):
        sample = rng.sample(deck, need + 2 * n_opponents)
        runout = list(board) + sample[:need]
        mine = evaluate(list(hole) + runout)
        best = True
        tied = 1
        for i in range(n_opponents):
            opp = sample[need + 2 * i: need + 2 * i + 2]
            ov = evaluate(opp + runout)
            if ov > mine:
                best = False
                break
            if ov == mine:
                tied += 1
        if best:
            wins += 1.0 / tied
    return wins / rollouts


# ---------------------------------------------------------------- strategies
#
# Interface: decide(view, rng) -> ("fold",) | ("call",) | ("raise", raise_to)
# `view` exposes only information a real player would have at the table.

class View:
    __slots__ = ("hole", "board", "to_call", "pot", "stack", "min_raise_to",
                 "big_blind", "n_active", "position_ratio", "opp_stats",
                 "my_bet", "street")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class AllInAndy:
    """if my_turn then bet = All in fi"""
    name = "All-In Andy"

    def decide(self, view, rng):
        return ("raise", view.stack + view.my_bet)


class ProfessorTAG:
    """Tight-aggressive: positional preflop ranges, strength-driven postflop
    bets sized to the pot, folds to heavy pressure without a real hand."""
    name = "Professor TAG"

    def decide(self, v, rng):
        if v.street == "preflop":
            score = preflop_score(v.hole)
            thresh = 9 - 3 * v.position_ratio  # looser in late position
            facing_shove = v.to_call >= v.stack * 0.6
            if facing_shove:
                return ("call",) if score >= 11 else ("fold",)
            if score >= thresh + 3:
                return ("raise", min(v.stack + v.my_bet,
                                     max(v.min_raise_to, v.to_call + v.my_bet + 3 * v.big_blind)))
            if score >= thresh:
                if v.to_call <= 3 * v.big_blind:
                    return ("call",)
                return ("call",) if score >= thresh + 2 else ("fold",)
            return ("check_or_fold", )
        eq = equity_estimate(v.hole, v.board, max(1, v.n_active - 1), rng, 60)
        pot_odds = v.to_call / (v.pot + v.to_call) if v.to_call else 0
        if eq > 0.65:
            return ("raise", min(v.stack + v.my_bet, v.to_call + v.my_bet + int(v.pot * 0.75)))
        if v.to_call == 0:
            return ("raise", v.my_bet + int(v.pot * 0.5)) if eq > 0.5 else ("call",)
        return ("call",) if eq > pot_odds + 0.05 else ("fold",)


class ManiacLAG:
    """Loose-aggressive: wide ranges, frequent raises, occasional pure bluffs,
    but still bails on hopeless spots against huge bets."""
    name = "Maniac Marla"

    def decide(self, v, rng):
        if v.street == "preflop":
            score = preflop_score(v.hole)
            facing_shove = v.to_call >= v.stack * 0.6
            if facing_shove:
                return ("call",) if score >= 9 else ("fold",)
            if score >= 5 or rng.random() < 0.15:
                if rng.random() < 0.6:
                    return ("raise", min(v.stack + v.my_bet,
                                         max(v.min_raise_to, v.to_call + v.my_bet + 4 * v.big_blind)))
                return ("call",)
            return ("check_or_fold",)
        eq = equity_estimate(v.hole, v.board, max(1, v.n_active - 1), rng, 50)
        bluffing = rng.random() < 0.18
        if eq > 0.55 or (bluffing and v.to_call == 0):
            return ("raise", min(v.stack + v.my_bet, v.to_call + v.my_bet + v.pot))
        pot_odds = v.to_call / (v.pot + v.to_call) if v.to_call else 0
        if v.to_call == 0:
            return ("call",)
        return ("call",) if eq > pot_odds else ("fold",)


class NitNigel:
    """Ultra-tight rock: premium hands only, never bluffs, happily folds for
    hours and snap-calls shoves with monsters."""
    name = "Nit Nigel"

    def decide(self, v, rng):
        if v.street == "preflop":
            (r1, _), (r2, _) = sorted(v.hole, reverse=True)
            pair = r1 == r2
            premium = (pair and r1 >= 10) or (r1 == 14 and r2 >= 12)
            strong = (pair and r1 >= 7) or (r1 == 14 and r2 >= 10) or (r1 == 13 and r2 >= 12)
            if premium:
                return ("raise", min(v.stack + v.my_bet,
                                     max(v.min_raise_to, v.to_call + v.my_bet + 4 * v.big_blind)))
            if strong and v.to_call <= 2 * v.big_blind:
                return ("call",)
            return ("check_or_fold",)
        val = evaluate(list(v.hole) + list(v.board))
        board_val = evaluate(list(v.board)) if len(v.board) >= 5 else None
        strong = val[0] >= 2 or (val[0] == 1 and val[1] >= 11)
        if board_val and val <= board_val:
            strong = False
        if strong:
            return ("raise", min(v.stack + v.my_bet, v.to_call + v.my_bet + int(v.pot * 0.6)))
        return ("check_or_fold",)


class OddsOlga:
    """Pure math: Monte Carlo equity vs pot odds every street, raises for
    value when equity is a clear favorite, otherwise price-driven calls."""
    name = "Odds Olga"

    def decide(self, v, rng):
        n_opp = max(1, v.n_active - 1)
        eq = equity_estimate(v.hole, v.board, n_opp, rng, 90)
        fair = 1.0 / (n_opp + 1)
        if v.to_call >= v.stack * 0.6:  # facing effective shove
            return ("call",) if eq > max(0.40, fair + 0.12) else ("fold",)
        if eq > fair * 1.7:
            return ("raise", min(v.stack + v.my_bet, v.to_call + v.my_bet
                                 + max(3 * v.big_blind, int(v.pot * 0.7))))
        pot_odds = v.to_call / (v.pot + v.to_call) if v.to_call else 0
        if v.to_call == 0:
            return ("call",)
        return ("call",) if eq > pot_odds + 0.03 else ("fold",)


class SherlockAdaptive:
    """Exploitative: profiles opponents from public actions. Versus a serial
    shover it widens its call range dramatically; versus passives it steals."""
    name = "Sherlock"

    def decide(self, v, rng):
        shover_active = any(
            st["hands"] >= 5 and st["shoves"] / st["hands"] > 0.5
            for st in v.opp_stats.values() if st["in_hand"]
        )
        if v.street == "preflop":
            score = preflop_score(v.hole)
            facing_shove = v.to_call >= v.stack * 0.6
            if facing_shove:
                # vs a maniac who shoves everything, any decent hand is ahead
                thresh = 6 if shover_active else 11
                return ("call",) if score >= thresh else ("fold",)
            if shover_active:
                # keep pots small pre-shove; limp-trap decent hands
                return ("call",) if score >= 6 and v.to_call <= 2 * v.big_blind else ("check_or_fold",)
            if score >= 10:
                return ("raise", min(v.stack + v.my_bet,
                                     max(v.min_raise_to, v.to_call + v.my_bet + 3 * v.big_blind)))
            if score >= 7 and v.to_call <= 2 * v.big_blind:
                return ("call",)
            return ("check_or_fold",)
        eq = equity_estimate(v.hole, v.board, max(1, v.n_active - 1), rng, 70)
        pot_odds = v.to_call / (v.pot + v.to_call) if v.to_call else 0
        need = pot_odds - 0.05 if shover_active else pot_odds + 0.05
        if eq > 0.6:
            return ("raise", min(v.stack + v.my_bet, v.to_call + v.my_bet + int(v.pot * 0.8)))
        if v.to_call == 0:
            return ("call",)
        return ("call",) if eq > need else ("fold",)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack


def play_hand(players, button, big_blind, stats, rng):
    """One full hand with blinds, 4 streets, side pots. Mutates stacks."""
    sb = big_blind // 2
    n = len(players)
    order = [players[(button + 1 + i) % n] for i in range(n)]

    deck = new_deck(rng)
    hole = {p.pid: (deck.pop(), deck.pop()) for p in order}
    board = []

    contrib = {p.pid: 0 for p in order}     # total chips in this hand
    bet_round = {p.pid: 0 for p in order}   # chips in current street
    folded = set()
    all_in = set()

    def post(p, amt):
        amt = min(amt, p.stack)
        p.stack -= amt
        contrib[p.pid] += amt
        bet_round[p.pid] += amt
        if p.stack == 0:
            all_in.add(p.pid)
        return amt

    post(order[0], sb)
    post(order[1], big_blind)
    for p in order:
        stats[p.pid]["hands"] += 1
        stats[p.pid]["in_hand"] = True

    def active():
        return [p for p in order if p.pid not in folded]

    def can_act():
        return [p for p in order if p.pid not in folded and p.pid not in all_in]

    def betting_round(street, first_idx):
        current_bet = max(bet_round.values())
        min_raise_to = current_bet + (big_blind if street != "preflop" else big_blind)
        if street == "preflop":
            min_raise_to = 2 * big_blind
        actors = can_act()
        if len(active()) <= 1 or not actors:
            return
        pending = {p.pid for p in actors}
        idx = first_idx
        guard = 0
        while pending and len(active()) > 1:
            guard += 1
            if guard > 500:
                break
            p = order[idx % n]
            idx += 1
            if p.pid in folded or p.pid in all_in or p.pid not in pending:
                continue
            pending.discard(p.pid)
            to_call = current_bet - bet_round[p.pid]
            pot = sum(contrib.values())
            others = [q for q in active() if q.pid != p.pid]
            seat = order.index(p)
            view = View(
                hole=hole[p.pid], board=tuple(board), to_call=to_call,
                pot=pot, stack=p.stack, min_raise_to=min_raise_to,
                big_blind=big_blind, n_active=len(active()),
                position_ratio=seat / max(1, n - 1),
                opp_stats={q.pid: stats[q.pid] for q in others},
                my_bet=bet_round[p.pid], street=street,
            )
            action = p.strategy.decide(view, rng)
            kind = action[0]

            if kind == "check_or_fold":
                kind = "call" if to_call == 0 else "fold"
            if kind == "raise":
                target = min(action[1], bet_round[p.pid] + p.stack)
                if target <= current_bet:
                    kind = "call" if to_call <= p.stack else "fold"
                elif target < min_raise_to and target < bet_round[p.pid] + p.stack:
                    target = min(min_raise_to, bet_round[p.pid] + p.stack)

            if kind == "fold":
                if to_call == 0:
                    pass  # free check, never fold for free
                else:
                    folded.add(p.pid)
                    stats[p.pid]["in_hand"] = False
                    continue
                kind = "call"

            if kind == "call":
                post(p, to_call)
                continue

            # raise
            add = target - bet_round[p.pid]
            post(p, add)
            new_bet = bet_round[p.pid]
            if new_bet > current_bet:
                raise_size = new_bet - current_bet
                min_raise_to = new_bet + max(raise_size, big_blind)
                current_bet = new_bet
                stats[p.pid]["raises"] += 1
                if p.stack == 0 and add >= pot * 0.5:
                    stats[p.pid]["shoves"] += 1
                pending = {q.pid for q in can_act() if q.pid != p.pid}

    # preflop: first to act is seat after BB
    betting_round("preflop", 2 % n)
    for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
        if len(active()) > 1:
            deck.pop()  # burn
            board.extend(deck.pop() for _ in range(n_cards))
            for pid in bet_round:
                bet_round[pid] = 0
            if len(can_act()) > 1:
                betting_round(street, 0)

    # showdown with side pots
    live = active()
    if len(live) == 1:
        live[0].stack += sum(contrib.values())
    else:
        scores = {p.pid: evaluate(list(hole[p.pid]) + board) for p in live}
        levels = sorted({contrib[p.pid] for p in live if contrib[p.pid] > 0})
        prev = 0
        for level in levels:
            pot = 0
            for pid, c in contrib.items():
                take = max(0, min(c, level) - prev)
                pot += take
            eligible = [p for p in live if contrib[p.pid] >= level]
            best = max(scores[p.pid] for p in eligible)
            winners = [p for p in eligible if scores[p.pid] == best]
            share, rem = divmod(pot, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < rem else 0)
            prev = level
        # chips from folded players above the highest live level (rare)
        leftover = sum(max(0, c - prev) for c in contrib.values())
        if leftover:
            live[0].stack += leftover

    for pid in stats:
        stats[pid]["in_hand"] = False


def run_tournament(strategies, seed, start_stack=1000):
    rng = random.Random(seed)
    players = [Player(i + 1, s, start_stack) for i, s in enumerate(strategies)]
    stats = {p.pid: {"hands": 0, "raises": 0, "shoves": 0, "in_hand": False}
             for p in players}
    button = 0
    hand_no = 0
    elimination_order = []
    while len(players) > 1 and hand_no < 5000:
        hand_no += 1
        big_blind = 20 * (2 ** (hand_no // 25))  # escalating blinds
        big_blind = min(big_blind, 2 * start_stack * 6)
        play_hand(players, button % len(players), big_blind, stats, rng)
        busted = [p for p in players if p.stack <= 0]
        for p in sorted(busted, key=lambda q: q.stack):
            elimination_order.append(p.pid)
        players = [p for p in players if p.stack > 0]
        button += 1
    champion = max(players, key=lambda p: p.stack)
    elimination_order.extend(p.pid for p in players if p is not champion)
    elimination_order.append(champion.pid)
    return champion.pid, hand_no, elimination_order


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    strategies = [AllInAndy(), ProfessorTAG(), ManiacLAG(),
                  NitNigel(), OddsOlga(), SherlockAdaptive()]
    names = {i + 1: f"P{i + 1} {s.name}" for i, s in enumerate(strategies)}

    wins = Counter()
    placements = {pid: [] for pid in names}
    total_hands = 0
    for sim in range(n_sims):
        champ, hands, elim = run_tournament(strategies, seed=1000 + sim)
        wins[champ] += 1
        total_hands += hands
        for place, pid in enumerate(reversed(elim), start=1):
            placements[pid].append(place)
        done = sim + 1
        if done % 10 == 0:
            print(f"  ... {done}/{n_sims} tournaments done", flush=True)

    print()
    print(f"WINNER WINNER CHICKEN DINNER -- champions over {n_sims} tournaments")
    print(f"(6 players, equal 1000-chip stacks, escalating blinds, "
          f"avg {total_hands / n_sims:.0f} hands/tournament)")
    print()
    width = 50
    top = max(wins.values()) if wins else 1
    for pid in sorted(names):
        w = wins[pid]
        bar = "#" * max(1 if w else 0, round(w / top * width))
        avg_place = sum(placements[pid]) / len(placements[pid])
        print(f"{names[pid]:<22} {w:>3} wins |{bar:<{width}}| "
              f"avg finish: {avg_place:.2f}")
    print()
    andy = wins[1]
    print(f"Player 1 (all-in every hand) won {andy}/{n_sims} "
          f"({andy / n_sims:.0%}) -- the table figured him out.")


if __name__ == "__main__":
    main()
