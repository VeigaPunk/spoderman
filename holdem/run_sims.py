#!/usr/bin/env python3
"""Run N full 6-max Texas Hold'em tournaments and print a winner histogram.

Every player starts with the same stack. Player 1 plays "if my_turn then
bet = All in fi". Players 2..6 each run an elaborate strategy. Seats are
shuffled every tournament so nobody keeps a positional edge.
"""

import argparse
import random
import time
from collections import Counter

from poker.engine import Tournament
from poker.strategies import ROSTER


def run(n_sims=100, starting_stack=200, seed=42, verbose=True):
    winners = Counter()
    hand_counts = []
    t0 = time.time()
    for i in range(n_sims):
        rng = random.Random(seed * 100_000 + i)
        seats = list(ROSTER)
        rng.shuffle(seats)  # fresh seating draw every tournament
        names = [name for name, _cls in seats]
        strategies = [cls() for _name, cls in seats]
        tour = Tournament(strategies, names, starting_stack=starting_stack,
                          small_blind=1, blind_double_every=10, rng=rng)
        winner, hands = tour.run()
        winners[winner] += 1
        hand_counts.append(hands)
        if verbose and (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)")
    return winners, hand_counts


def histogram(winners, n_sims, width=50):
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — tournament wins "
                 f"out of {n_sims} sims")
    lines.append("=" * 72)
    top = max(winners.values()) if winners else 1
    for name, _cls in ROSTER:
        w = winners.get(name, 0)
        bar = "█" * max(1 if w else 0, round(w / top * width))
        pct = 100.0 * w / n_sims
        lines.append(f"{name:<16} | {bar:<{width}} {w:>3}  ({pct:4.1f}%)")
    lines.append("=" * 72)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--stack", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"Running {args.sims} tournaments: 6 players, {args.stack} chips "
          f"each, blinds 1/2 doubling every 10 hands...")
    winners, hand_counts = run(args.sims, args.stack, args.seed)
    print(histogram(winners, args.sims))
    avg = sum(hand_counts) / len(hand_counts)
    print(f"avg tournament length: {avg:.1f} hands "
          f"(min {min(hand_counts)}, max {max(hand_counts)})")


if __name__ == "__main__":
    main()
