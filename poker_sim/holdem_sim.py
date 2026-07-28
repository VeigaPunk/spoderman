"""Texas Hold'em tournament simulator: 5 elaborate strategies vs 1 all-in maniac.

100 tournaments, 6 players, equal starting stacks. Strategies are mutually
blind to each other's logic. Output: histogram of tournament winners.
"""

import random
import itertools
from collections import Counter

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}

STARTING_STACK = 1000
SMALL_BLIND = 10
BLIND_DOUBLE_EVERY = 25
MAX_HANDS = 3000


def new_deck(rng):
    deck = [r + s for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck


# ---------------------------------------------------------------- evaluation

def eval5(cards):
    vals = sorted((RANK_VAL[c[0]] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    counts = Counter(vals)
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    uniq = sorted(set(vals), reverse=True)

    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_high = 5

    if flush and straight_high:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *vals)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        kickers = [v for v in vals if v != groups[0][0]]
        return (3, groups[0][0], *kickers)
    if groups[0][1] == 2 and groups[1][1] == 2:
        kicker = [v for v in vals if counts[v] == 1][0]
        return (2, groups[0][0], groups[1][0], kicker)
    if groups[0][1] == 2:
        kickers = [v for v in vals if v != groups[0][0]]
        return (1, groups[0][0], *kickers)
    return (0, *vals)


def eval7(cards):
    return max(eval5(c) for c in itertools.combinations(cards, 5))


def equity(hole, community, n_opponents, rng, samples=60):
    """Monte Carlo equity vs random opponent hands."""
    n_opponents = max(1, n_opponents)
    known = set(hole) | set(community)
    remaining = [r + s for r in RANKS for s in SUITS if r + s not in known]
    need_board = 5 - len(community)
    wins = 0.0
    for _ in range(samples):
        draw = rng.sample(remaining, need_board + 2 * n_opponents)
        board = list(community) + draw[:need_board]
        mine = eval7(hole + board)
        best_opp = max(
            eval7(draw[need_board + 2 * i:need_board + 2 * i + 2] + board)
            for i in range(n_opponents)
        )
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / samples


def chen_score(hole):
    """Chen formula for preflop hand strength."""
    a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
    va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
    base = {14: 10, 13: 8, 12: 7, 11: 6}.get(va, va / 2)
    score = base
    if va == vb:
        score = max(base * 2, 5)
    if a[1] == b[1]:
        score += 2
    gap = va - vb - 1
    if va != vb:
        score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
        if gap <= 1 and va < 12:
            score += 1
    return score


# ---------------------------------------------------------------- strategies
# Each strategy sees only: its hole cards, community cards, pot, amount to
# call, own stack, number of live opponents, position, and blind level.
# Return: ('fold', 0) | ('call', 0) | ('raise', extra_over_call)

class Strategy:
    name = "?"

    def act(self, view, rng):
        raise NotImplementedError


class YoloAllIn(Strategy):
    """Player 1. The entire algorithm: if my_turn then bet = All in fi."""
    name = "YOLO_AllIn"

    def act(self, view, rng):
        return ("raise", view["stack"] - view["to_call"]) if view["stack"] > view["to_call"] else ("call", 0)


class TagTitan(Strategy):
    """Tight-aggressive: Chen-formula preflop ranges, equity-driven value
    betting postflop, respects pot odds, 3-bets premiums."""
    name = "TAG_Titan"

    def act(self, view, rng):
        pot, to_call, stack = view["pot"], view["to_call"], view["stack"]
        if not view["community"]:
            score = chen_score(view["hole"])
            if score >= 10:
                return ("raise", min(stack - to_call, max(3 * view["big_blind"], pot)))
            if score >= 7.5 and to_call <= stack * 0.15:
                return ("call", 0)
            if to_call == 0:
                return ("call", 0)
            return ("fold", 0)
        eq = equity(view["hole"], view["community"], view["n_opponents"], rng)
        pot_odds = to_call / (pot + to_call) if to_call else 0
        if eq > 0.75:
            return ("raise", min(stack - to_call, int(pot * 0.8)))
        if eq > 0.55 and to_call < stack * 0.3:
            return ("raise", min(stack - to_call, int(pot * 0.5))) if to_call == 0 else ("call", 0)
        if eq > pot_odds + 0.05:
            return ("call", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)


class LagLunatic(Strategy):
    """Loose-aggressive: wide opening range, frequent bluffs, barrels
    scare cards, but folds to big aggression without equity."""
    name = "LAG_Lunatic"

    def act(self, view, rng):
        pot, to_call, stack = view["pot"], view["to_call"], view["stack"]
        if not view["community"]:
            score = chen_score(view["hole"])
            if score >= 6 or rng.random() < 0.25:
                if to_call > stack * 0.35:
                    return ("call", 0) if score >= 9 else ("fold", 0)
                if rng.random() < 0.6:
                    return ("raise", min(stack - to_call, max(3 * view["big_blind"], int(pot * 0.75))))
                return ("call", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)
        eq = equity(view["hole"], view["community"], view["n_opponents"], rng)
        bluffing = rng.random() < 0.2
        if eq > 0.6 or (bluffing and to_call == 0):
            return ("raise", min(stack - to_call, int(pot * 0.7)))
        if eq > 0.4 and to_call <= stack * 0.25:
            return ("call", 0)
        pot_odds = to_call / (pot + to_call) if to_call else 0
        if eq > pot_odds:
            return ("call", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)


class MathMonk(Strategy):
    """Pure expected-value machine: Monte Carlo equity vs pot odds every
    street, bet sizing proportional to edge, zero emotion."""
    name = "Math_Monk"

    def act(self, view, rng):
        pot, to_call, stack = view["pot"], view["to_call"], view["stack"]
        n = view["n_opponents"]
        eq = equity(view["hole"], view["community"], n, rng, samples=80)
        fair_share = 1.0 / (n + 1)
        pot_odds = to_call / (pot + to_call) if to_call else 0
        edge = eq - fair_share
        if edge > 0.25:
            return ("raise", min(stack - to_call, int(pot * (0.5 + edge))))
        if edge > 0.1 and to_call == 0:
            return ("raise", min(stack - to_call, int(pot * 0.5)))
        if eq > pot_odds + 0.03:
            return ("call", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)


class PositionPirate(Strategy):
    """Position is power: near-nit in early position, wide and thieving on
    the button, punishes limpers, steals blinds relentlessly."""
    name = "Position_Pirate"

    def act(self, view, rng):
        pot, to_call, stack = view["pot"], view["to_call"], view["stack"]
        late = view["position"] >= 0.6  # 0 = first to act, 1 = last
        if not view["community"]:
            score = chen_score(view["hole"])
            threshold = 6 if late else 9
            if score >= threshold:
                steal = late and to_call <= view["big_blind"]
                if steal or score >= 10:
                    return ("raise", min(stack - to_call, max(3 * view["big_blind"], int(pot * 0.8))))
                if to_call <= stack * 0.2:
                    return ("call", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)
        eq = equity(view["hole"], view["community"], view["n_opponents"], rng)
        boost = 0.05 if late else 0.0
        if eq + boost > 0.65:
            return ("raise", min(stack - to_call, int(pot * 0.75)))
        pot_odds = to_call / (pot + to_call) if to_call else 0
        if eq + boost > pot_odds + 0.05:
            return ("call", 0)
        if late and to_call == 0 and rng.random() < 0.3:
            return ("raise", min(stack, int(pot * 0.5)))
        return ("call", 0) if to_call == 0 else ("fold", 0)


class NitNinja(Strategy):
    """Ultra-tight trapper: folds everything but premiums, then strikes with
    max aggression. Slow-plays monsters, never pays off without the goods."""
    name = "Nit_Ninja"

    def act(self, view, rng):
        pot, to_call, stack = view["pot"], view["to_call"], view["stack"]
        if not view["community"]:
            score = chen_score(view["hole"])
            if score >= 11:
                return ("raise", stack - to_call)  # premium: jam
            if score >= 9 and to_call <= stack * 0.1:
                return ("call", 0)
            return ("call", 0) if to_call == 0 else ("fold", 0)
        eq = equity(view["hole"], view["community"], view["n_opponents"], rng)
        if eq > 0.85:
            if to_call == 0 and rng.random() < 0.5:
                return ("call", 0)  # trap
            return ("raise", stack - to_call)
        if eq > 0.65:
            pot_odds = to_call / (pot + to_call) if to_call else 0
            if eq > pot_odds + 0.1:
                return ("call", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, pid, strategy):
        self.pid = pid
        self.strategy = strategy
        self.stack = STARTING_STACK
        self.hole = []
        self.folded = False
        self.committed = 0  # total chips into pot this hand


def betting_round(players, order, community, pot_total, big_blind, rng, current_bets):
    """Run one betting street. current_bets: pid -> chips bet this street."""
    live = [p for p in order if not p.folded and p.stack > 0]
    if len([p for p in order if not p.folded]) <= 1:
        return
    highest = max(current_bets.values()) if current_bets else 0
    need_action = {p.pid for p in live}
    idx = 0
    safety = 0
    while need_action and safety < 200:
        safety += 1
        if len([q for q in order if not q.folded]) <= 1:
            break
        p = order[idx % len(order)]
        idx += 1
        if p.folded or p.stack == 0 or p.pid not in need_action:
            continue
        to_call = highest - current_bets.get(p.pid, 0)
        street_pot = pot_total + sum(current_bets.values())
        active = [q for q in order if not q.folded]
        view = {
            "hole": p.hole,
            "community": list(community),
            "pot": street_pot,
            "to_call": min(to_call, p.stack),
            "stack": p.stack,
            "n_opponents": len(active) - 1,
            "position": order.index(p) / max(1, len(order) - 1),
            "big_blind": big_blind,
        }
        action, extra = p.strategy.act(view, rng)
        need_action.discard(p.pid)
        if action == "fold" and to_call > 0:
            p.folded = True
            continue
        pay = min(to_call, p.stack)
        if action == "raise" and extra > 0 and p.stack > to_call:
            extra = min(extra, p.stack - to_call)
            pay = to_call + extra
            highest += extra
            need_action = {q.pid for q in order
                           if not q.folded and q.stack > 0 and q.pid != p.pid}
        p.stack -= pay
        current_bets[p.pid] = current_bets.get(p.pid, 0) + pay
        p.committed += pay


def award_pots(players, board):
    """Distribute chips with proper side pots based on committed amounts."""
    contenders = [p for p in players if p.committed > 0]
    scores = {}
    for p in contenders:
        if not p.folded:
            scores[p.pid] = eval7(p.hole + board)
    levels = sorted({p.committed for p in contenders})
    prev = 0
    for lvl in levels:
        pot = sum(min(p.committed, lvl) - min(p.committed, prev) for p in contenders)
        prev = lvl
        eligible = [p for p in contenders if not p.folded and p.committed >= lvl]
        if not eligible:
            eligible = [p for p in contenders if not p.folded]
        if not eligible or pot == 0:
            continue
        best = max(scores[p.pid] for p in eligible)
        winners = [p for p in eligible if scores[p.pid] == best]
        share, rem = divmod(pot, len(winners))
        for i, w in enumerate(winners):
            w.stack += share + (1 if i < rem else 0)


def play_hand(players, button, small_blind, rng):
    order = [p for p in players if p.stack > 0]
    if len(order) < 2:
        return
    order = order[button % len(order):] + order[:button % len(order)]
    deck = new_deck(rng)
    for p in order:
        p.hole = [deck.pop(), deck.pop()]
        p.folded = False
        p.committed = 0

    big_blind = small_blind * 2
    bets = {}
    sb, bb = order[0], order[1]
    for blinder, amt in ((sb, small_blind), (bb, big_blind)):
        pay = min(amt, blinder.stack)
        blinder.stack -= pay
        blinder.committed += pay
        bets[blinder.pid] = pay

    community = []
    pot_total = 0
    preflop_order = order[2:] + order[:2]
    betting_round(players, preflop_order, community, pot_total, big_blind, rng, bets)
    pot_total += sum(bets.values())

    for n_cards in (3, 1, 1):
        if len([p for p in order if not p.folded]) <= 1:
            break
        deck.pop()  # burn
        community.extend(deck.pop() for _ in range(n_cards))
        if len([p for p in order if not p.folded and p.stack > 0]) >= 2:
            bets = {}
            betting_round(players, order, community, pot_total, big_blind, rng, bets)
            pot_total += sum(bets.values())

    while len(community) < 5 and len([p for p in order if not p.folded]) >= 2:
        deck.pop()
        community.append(deck.pop())

    active = [p for p in order if not p.folded]
    if len(active) == 1:
        active[0].stack += sum(p.committed for p in order)
    else:
        award_pots(order, community)


def run_tournament(seed):
    rng = random.Random(seed)
    players = [
        Player(1, YoloAllIn()),
        Player(2, TagTitan()),
        Player(3, LagLunatic()),
        Player(4, MathMonk()),
        Player(5, PositionPirate()),
        Player(6, NitNinja()),
    ]
    rng.shuffle(players)
    button = 0
    for hand_no in range(MAX_HANDS):
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1:
            return alive[0]
        sb = SMALL_BLIND * (2 ** (hand_no // BLIND_DOUBLE_EVERY))
        play_hand(players, button, sb, rng)
        button += 1
    return max(players, key=lambda p: p.stack)


def main():
    n_sims = 100
    wins = Counter()
    for i in range(n_sims):
        winner = run_tournament(seed=i)
        wins[winner.strategy.name] += 1
        print(f"sim {i + 1:3d}/100 -> winner: P{winner.pid} {winner.strategy.name}")

    names = ["YOLO_AllIn", "TAG_Titan", "LAG_Lunatic", "Math_Monk",
             "Position_Pirate", "Nit_Ninja"]
    print("\n" + "=" * 62)
    print("  WINNER WINNER CHICKEN DINNER — 100 TOURNAMENT HISTOGRAM")
    print("=" * 62)
    for i, name in enumerate(names, start=1):
        w = wins[name]
        bar = "█" * w
        print(f"  P{i} {name:<16} {w:3d} |{bar}")
    print("=" * 62)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        labels = [f"P{i}\n{n}" for i, n in enumerate(names, start=1)]
        counts = [wins[n] for n in names]
        colors = ["#d62728" if n == "YOLO_AllIn" else "#1f77b4" for n in names]
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(labels, counts, color=colors)
        ax.bar_label(bars)
        ax.set_ylabel("Tournament wins (out of 100)")
        ax.set_title("Winner Winner Chicken Dinner — 100 Hold'em Tournaments\n"
                     "(P1 = all-in every hand; P2–P6 = elaborate strategies)")
        fig.tight_layout()
        fig.savefig("poker_sim/winner_histogram.png", dpi=120)
        print("saved poker_sim/winner_histogram.png")
    except ImportError:
        print("(matplotlib not available — ASCII histogram above is the output)")


if __name__ == "__main__":
    main()
