#!/usr/bin/env python3
"""Run N full 6-max Texas Hold'em tournaments and histogram the champions.

Player 1 plays `if my_turn Then bet = All in Fi`.
Players 2..6 play five elaborate strategies (see holdem/strategies.py).
Everyone starts every tournament with identical stacks.
"""

import argparse
import json
import random
import time
from collections import Counter

from holdem.engine import play_tournament
from holdem.strategies import ROSTER

STARTING_STACK = 10_000


def label(pid, cls):
    return f"P{pid} {cls.name}"


def ascii_histogram(counts, total, out):
    width = 50
    top = max(counts.values()) if counts else 1
    out.append("")
    out.append("WINNER WINNER CHICKEN DINNER — tournament champions "
               f"({total} sims)")
    out.append("=" * 78)
    for pid, cls in ROSTER:
        name = label(pid, cls)
        n = counts.get(pid, 0)
        bar = "█" * max(1 if n else 0, round(n / top * width))
        out.append(f"{name:<20} | {bar:<{width}} {n:>3}  ({n / total:.0%})")
    out.append("=" * 78)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    factories = [(pid, lambda pid, rng, cls=cls: cls(pid, rng))
                 for pid, cls in ROSTER]

    wins = Counter()
    placements = {pid: [] for pid, _ in ROSTER}
    total_hands = 0
    t0 = time.time()

    for sim in range(args.sims):
        rng = random.Random(args.seed * 1_000_003 + sim)
        winner, finish_order, hands = play_tournament(
            factories, STARTING_STACK, rng)
        wins[winner] += 1
        total_hands += hands
        # finish_order: first bust .. champion  ->  place 6 .. 1
        for place, pid in zip(range(len(finish_order), 0, -1), finish_order):
            placements[pid].append(place)
        done = sim + 1
        if done % 10 == 0:
            print(f"  ... {done}/{args.sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", flush=True)

    out = []
    ascii_histogram(wins, args.sims, out)
    out.append("")
    out.append(f"{'player':<20} {'wins':>5} {'win%':>6} {'avg finish':>11}")
    out.append("-" * 46)
    for pid, cls in ROSTER:
        avg = sum(placements[pid]) / len(placements[pid])
        out.append(f"{label(pid, cls):<20} {wins.get(pid, 0):>5} "
                   f"{wins.get(pid, 0) / args.sims:>6.0%} {avg:>11.2f}")
    out.append("")
    out.append(f"total hands dealt: {total_hands}   "
               f"wall time: {time.time() - t0:.1f}s")
    report = "\n".join(out)
    print(report)

    with open("results/results.json", "w") as f:
        json.dump({
            "sims": args.sims,
            "seed": args.seed,
            "wins": {label(pid, cls): wins.get(pid, 0)
                     for pid, cls in ROSTER},
            "avg_finish": {label(pid, cls):
                           sum(placements[pid]) / len(placements[pid])
                           for pid, cls in ROSTER},
            "total_hands": total_hands,
        }, f, indent=2)
    with open("results/results.txt", "w") as f:
        f.write(report + "\n")

    try:
        plot(wins, args.sims)
    except ImportError:
        print("(matplotlib not installed — skipped PNG histogram)")


def plot(wins, total):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [label(pid, cls) for pid, cls in ROSTER]
    values = [wins.get(pid, 0) for pid, _ in ROSTER]
    colors = ["#d62728"] + ["#4c72b0"] * (len(names) - 1)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(names, values, color=colors)
    ax.set_ylabel("tournament wins")
    ax.set_title(f"Winner histogram — {total} full 6-max NLHE tournaments\n"
                 "(P1 = 'if my_turn Then bet = All in Fi')")
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.5, str(v),
                ha="center", fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    plt.xticks(rotation=15)
    plt.tight_layout()
    plt.savefig("results/winner_histogram.png", dpi=150)
    print("saved results/winner_histogram.png")


if __name__ == "__main__":
    import os
    os.makedirs("results", exist_ok=True)
    main()
