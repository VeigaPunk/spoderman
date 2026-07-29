#!/usr/bin/env python3
"""Run N six-handed Texas Hold'em tournaments and print the winner histogram.

Seat 1 plays `if my_turn then bet = All in fi`.
Seats 2-6 play five elaborate strategies. Nobody knows anyone else's code.
"""

import argparse
import random
import time

from poker.engine import Seat, Tournament
from poker.strategies import (
    AllInBot, TightAggressive, LooseAggressive, Rock,
    Mathematician, AdaptiveExploiter,
)

LINEUP = [
    ("P1 Suflair-GPT (All-In Bot)", AllInBot),
    ("P2 Doyle (Tight-Aggressive)", TightAggressive),
    ("P3 Gus (Loose-Aggressive)", LooseAggressive),
    ("P4 The Rock (Ultra-Tight Trapper)", Rock),
    ("P5 Ada (Monte Carlo Mathematician)", Mathematician),
    ("P6 Sun-Tzu (Adaptive Exploiter)", AdaptiveExploiter),
]

START_STACK = 1000
BLINDS = (10, 20)
HANDS_PER_LEVEL = 20


def run(n_sims, base_seed, quiet=False):
    wins = [0] * len(LINEUP)
    finish_sum = [0] * len(LINEUP)
    t0 = time.time()
    for sim in range(n_sims):
        rng = random.Random(base_seed + sim)
        seats = [Seat(seat_id=i, name=name, strategy=cls(), stack=START_STACK)
                 for i, (name, cls) in enumerate(LINEUP)]
        tourney = Tournament(seats, rng, start_blinds=BLINDS,
                             hands_per_level=HANDS_PER_LEVEL)
        order = tourney.run()  # seat_ids, winner first
        wins[order[0]] += 1
        for place, seat_id in enumerate(order, start=1):
            finish_sum[seat_id] += place
        if not quiet and (sim + 1) % 10 == 0:
            print(f"  ... {sim + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", flush=True)
    return wins, [s / n_sims for s in finish_sum]


def histogram(wins, avg_finish, n_sims):
    width = max(len(name) for name, _ in LINEUP)
    lines = []
    lines.append("=" * 78)
    lines.append("  WINNER WINNER CHICKEN DINNER HISTOGRAM "
                 f"({n_sims} tournaments, winner-take-all)")
    lines.append("=" * 78)
    for i, (name, _) in enumerate(LINEUP):
        bar = "█" * wins[i]
        lines.append(f"{name:<{width}} | {bar} {wins[i]}")
    lines.append("-" * 78)
    lines.append(f"{'Player':<{width}} | {'Wins':>4} | {'Win %':>6} | avg finish")
    for i, (name, _) in enumerate(LINEUP):
        lines.append(f"{name:<{width}} | {wins[i]:>4} | {wins[i] / n_sims:>5.0%} "
                     f"| {avg_finish[i]:.2f}")
    lines.append("=" * 78)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", "--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args()

    print(f"Dealing {args.sims} six-handed tournaments "
          f"(start stack {START_STACK}, blinds {BLINDS[0]}/{BLINDS[1]} "
          f"doubling every {HANDS_PER_LEVEL} hands, seed {args.seed})...",
          flush=True)
    wins, avg_finish = run(args.sims, args.seed, args.quiet)
    print()
    print(histogram(wins, avg_finish, args.sims))


if __name__ == "__main__":
    main()
