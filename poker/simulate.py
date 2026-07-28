"""Run 100 Texas Hold'em tournaments and print the winner histogram.

Player 1 runs `if my_turn then bet = All in fi`. Players 2-6 run elaborate
strategies. Nobody knows anyone else's algorithm. Everyone starts with the
same stack. Last player with chips wins the tournament.

Run: python -m poker.simulate
"""

import random
from collections import Counter, defaultdict

from .engine import Tournament
from .strategies import ROSTER

N_SIMS = 100
STARTING_STACK = 1000
MASTER_SEED = 20260728


def run_all():
    wins = Counter()
    finish_sum = defaultdict(int)
    bust_hands = defaultdict(list)
    hands_total = 0

    for sim in range(N_SIMS):
        rng = random.Random(MASTER_SEED + sim)
        seats = list(ROSTER.keys())
        rng.shuffle(seats)  # random seating every tournament
        strategies = {p: ROSTER[p](p, random.Random(MASTER_SEED * 7 + sim * 13 + p))
                      for p in seats}
        t = Tournament(seats, strategies, STARTING_STACK, rng)
        winner, order, hands = t.run()
        wins[winner] += 1
        hands_total += hands
        for place, p in enumerate(order, start=1):  # 1 = winner
            finish_sum[p] += place
        if order[-1] == 1 or 1 in order:
            pos = order.index(1) + 1
            if pos > 1:
                bust_hands[1].append(hands)
    return wins, finish_sum, hands_total


def bar(count, max_count, width=50):
    n = round(width * count / max_count) if max_count else 0
    return "█" * n


def report(wins, finish_sum, hands_total):
    lines = []
    add = lines.append
    add("=" * 74)
    add("  TEXAS HOLD'EM — 100 TOURNAMENTS, 6 PLAYERS, WINNER TAKE ALL")
    add("  histogram of the winner winner chicken dinner")
    add("=" * 74)
    add("")
    max_count = max(wins.values()) if wins else 1
    for p in sorted(ROSTER.keys()):
        name = ROSTER[p].NAME
        w = wins.get(p, 0)
        add(f"  P{p} {name:<28} | {bar(w, max_count)} {w}")
    add("")
    add(f"  avg tournament length: {hands_total / N_SIMS:.1f} hands")
    add("")
    add("  average finishing place (1 = winner, 6 = first bust):")
    for p in sorted(ROSTER.keys()):
        add(f"    P{p} {ROSTER[p].NAME:<28} {finish_sum[p] / N_SIMS:.2f}")
    add("")
    champ = max(wins, key=wins.get)
    add(f"  overall champion: P{champ} {ROSTER[champ].NAME} "
        f"with {wins[champ]}/100 titles")
    add("=" * 74)
    return "\n".join(lines)


def main():
    wins, finish_sum, hands_total = run_all()
    text = report(wins, finish_sum, hands_total)
    print(text)
    with open("poker/RESULTS.md", "w") as f:
        f.write("# Winner Histogram — 100 Tournament Simulations\n\n")
        f.write("```\n")
        f.write(text)
        f.write("\n```\n")


if __name__ == "__main__":
    main()
