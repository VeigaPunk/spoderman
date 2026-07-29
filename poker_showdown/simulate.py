#!/usr/bin/env python3
"""Run N full 6-player Texas Hold'em tournaments and histogram the winners.

Seat 1 is Suflair-GPT running, in its entirety:

    if my_turn
    then bet = All in
    fi

Seats 2..6 run five elaborate strategies. Everyone starts with equal chips;
blinds escalate; a tournament ends when one player holds all the chips.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from holdem.engine import run_tournament
from holdem.strategies import LINEUP

BAR = "█"


def make_players(rng):
    return [(name, cls()) for name, cls in LINEUP]


def ascii_histogram(wins, names, total):
    lines = []
    width = max(len(n) for n in names)
    maxw = max(wins.values()) if wins else 1
    for seat, (name, _) in enumerate(LINEUP):
        w = wins.get(seat, 0)
        bar = BAR * max(1, round(w / max(1, maxw) * 40)) if w else ""
        lines.append(f"  P{seat + 1} {name:<{width}} | {bar} {w} ({100 * w / total:.0f}%)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=2000)
    args = ap.parse_args()

    names = [name for name, _ in LINEUP]
    wins = {i: 0 for i in range(len(LINEUP))}
    placements = {i: [] for i in range(len(LINEUP))}
    hands_played = []

    t0 = time.time()
    for i in range(args.sims):
        order, n_hands = run_tournament(make_players, seed=args.seed * 100_000 + i,
                                        start_stack=args.stack)
        winner = order[-1]
        wins[winner] += 1
        hands_played.append(n_hands)
        for place, seat in enumerate(reversed(order)):  # place 0 = winner
            placements[seat].append(place + 1)
        done = i + 1
        if done % 10 == 0:
            print(f"  ... {done}/{args.sims} tournaments done "
                  f"({time.time() - t0:.0f}s)", flush=True)

    total = args.sims
    avg_place = {s: sum(v) / len(v) for s, v in placements.items()}
    busted_first = {s: sum(1 for p in v if p == len(LINEUP))
                    for s, v in placements.items()}

    report = []
    report.append("=" * 72)
    report.append(f"  WINNER WINNER CHICKEN DINNER — {total} tournaments, "
                  f"6 players, {args.stack} starting chips")
    report.append("=" * 72)
    report.append(ascii_histogram(wins, names, total))
    report.append("-" * 72)
    report.append("  avg finishing place (1 = chicken dinner, 6 = first out) "
                  "| times busted first:")
    for seat, name in enumerate(names):
        report.append(f"    P{seat + 1} {name:<26} {avg_place[seat]:.2f}"
                      f"   | busted first {busted_first[seat]}x")
    report.append(f"\n  avg hands per tournament: "
                  f"{sum(hands_played) / total:.0f}, "
                  f"total time {time.time() - t0:.0f}s")
    print()
    print("\n".join(report))

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump({"sims": total, "seed": args.seed,
                   "wins": {names[s]: w for s, w in wins.items()},
                   "avg_place": {names[s]: round(p, 3) for s, p in avg_place.items()},
                   "busted_first": {names[s]: b for s, b in busted_first.items()},
                   "avg_hands": sum(hands_played) / total}, f, indent=2)
    with open(os.path.join(out_dir, "results.txt"), "w") as f:
        f.write("\n".join(report) + "\n")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5.5))
        colors = ["#d62728" if s == 0 else "#4c78a8" for s in range(len(names))]
        vals = [wins[s] for s in range(len(names))]
        labels = [f"P{s + 1}\n" + n.replace(" [", "\n[") for s, n in enumerate(names)]
        bars = ax.bar(labels, vals, color=colors)
        ax.tick_params(axis="x", labelsize=9)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.5, str(v),
                    ha="center", fontweight="bold")
        ax.set_ylabel(f"tournament wins (out of {total})")
        ax.set_title("Winner-winner-chicken-dinner histogram — "
                     "last player standing per tournament")
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        png = os.path.join(out_dir, "winner_histogram.png")
        fig.savefig(png, dpi=150)
        print(f"  histogram PNG: {png}")
    except ImportError:
        print("  (matplotlib not installed — ASCII histogram only)")


if __name__ == "__main__":
    main()
