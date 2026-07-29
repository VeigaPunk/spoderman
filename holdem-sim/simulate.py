#!/usr/bin/env python3
"""Run N Texas Hold'em freezeout tournaments and histogram the winners.

Player 1 plays the entire strategy:  if my_turn then bet = All in fi
Players 2..6 play five elaborate strategies. Nobody knows anybody's algo.
"""

import argparse
import json
import os
import time
from collections import Counter

from holdem.engine import Tournament
from holdem.strategies import ROSTER

NAMES = [
    "P1 All-In Goblin",
    "P2 The Rock",
    "P3 TAG Professor",
    "P4 LAG Cowboy",
    "P5 The Mathematician",
    "P6 The Trapper",
]


def run(n_sims=100, start_stack=1000, base_seed=42):
    wins = Counter()
    finish_sum = [0] * 6  # sum of finishing places (1 = winner)
    t0 = time.time()
    for sim in range(n_sims):
        seed = base_seed + sim
        strategies = [cls(seed=seed * 100 + i) for i, cls in enumerate(ROSTER)]
        t = Tournament(strategies, NAMES, start_stack=start_stack, seed=seed)
        winner = t.run()
        wins[winner] += 1
        # finishing places: winner is 1st, last bust is 2nd, first bust is last
        places = {winner: 1}
        for rank, seat in enumerate(reversed(t.bust_order)):
            if seat not in places:
                places[seat] = rank + 2
        for seat in range(6):
            finish_sum[seat] += places.get(seat, 6)
        if (sim + 1) % 10 == 0:
            print(f"  ... {sim + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)")
    return wins, [s / n_sims for s in finish_sum]


def ascii_histogram(wins, n_sims):
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — tournament wins out of %d" % n_sims)
    lines.append("=" * 62)
    width = 40
    top = max(wins.values()) if wins else 1
    for seat in range(6):
        w = wins.get(seat, 0)
        bar = "█" * max(1 if w else 0, round(w / top * width))
        lines.append(f"{NAMES[seat]:<22} | {bar:<{width}} {w:>3}  ({100.0 * w / n_sims:.0f}%)")
    lines.append("=" * 62)
    return "\n".join(lines)


def save_png(wins, avg_finish, n_sims, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts = [wins.get(s, 0) for s in range(6)]
    colors = ["#d62728"] + ["#1f77b4"] * 5  # goblin in red
    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.bar(NAMES, counts, color=colors)
    for bar, c, af in zip(bars, counts, avg_finish):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{c} wins\navg finish {af:.2f}", ha="center", va="bottom",
                fontsize=9)
    ax.set_ylabel("Tournament wins (out of %d)" % n_sims)
    ax.set_title("Texas Hold'em: last player standing over %d tournaments\n"
                 "P1 = 'if my_turn then bet = All in fi'  vs  five elaborate strategies"
                 % n_sims)
    ax.set_ylim(0, max(counts) * 1.25 + 2)
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    plt.savefig(path, dpi=140)
    print(f"histogram image -> {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--stack", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"Running {args.sims} freezeout tournaments, 6 players, "
          f"{args.stack} starting chips each, blinds 10/20 doubling every 15 hands.")
    wins, avg_finish = run(args.sims, args.stack, args.seed)

    print(ascii_histogram(wins, args.sims))
    print("\nAverage finishing place (1 = winner, 6 = first out):")
    for seat in range(6):
        print(f"  {NAMES[seat]:<22} {avg_finish[seat]:.2f}")

    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "results.json"), "w") as f:
        json.dump({"sims": args.sims, "seed": args.seed,
                   "wins": {NAMES[s]: wins.get(s, 0) for s in range(6)},
                   "avg_finish": {NAMES[s]: avg_finish[s] for s in range(6)}},
                  f, indent=2)
    try:
        save_png(wins, avg_finish, args.sims, os.path.join(outdir, "histogram.png"))
    except ImportError:
        print("(matplotlib not installed; skipped PNG)")


if __name__ == "__main__":
    main()
