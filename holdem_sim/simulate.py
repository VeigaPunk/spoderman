"""Run N full-table tournaments and histogram the winner-winner-chicken-dinners.

Usage:  python3 -m holdem_sim.simulate [--sims 100] [--seed 42] [--chips 1000]
"""

import argparse
import time
from collections import Counter, defaultdict

from .engine import Tournament
from .strategies import LINEUP

BAR = "█"


def run_sims(n_sims=100, seed=42, chips=1000, base_sb=10, double_every=15):
    champs = Counter()
    placements = defaultdict(list)
    total_hands = 0
    t0 = time.time()
    for i in range(n_sims):
        # fresh strategy objects every tournament: no memory carries over,
        # and nobody is ever told what anybody else is running.
        entries = [(name, cls()) for name, cls in LINEUP]
        tour = Tournament(entries, chips=chips, base_sb=base_sb,
                          double_every=double_every, seed=seed * 100_003 + i)
        result = tour.run()
        champs[result["champion"]] += 1
        for name, place in result["placements"].items():
            placements[name].append(place)
        total_hands += result["hands"]
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", flush=True)
    return champs, placements, total_hands, time.time() - t0


def ascii_histogram(champs, names, n_sims, width=40):
    lines = []
    top = max(champs.values()) if champs else 1
    for name in names:
        wins = champs.get(name, 0)
        bar = BAR * max(1 if wins else 0, round(wins / top * width))
        pct = 100.0 * wins / n_sims
        lines.append(f"{name:<28} {bar:<{width}} {wins:3d}  ({pct:.0f}%)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--chips", type=int, default=1000)
    args = ap.parse_args()

    names = [name for name, _ in LINEUP]
    print(f"Dealing {args.sims} six-max tournaments "
          f"({args.chips} chips each, blinds 10/20 doubling every 15 hands)...")
    champs, placements, total_hands, elapsed = run_sims(
        n_sims=args.sims, seed=args.seed, chips=args.chips)

    print()
    print("=" * 78)
    print("  WINNER WINNER CHICKEN DINNER HISTOGRAM  (championships per player)")
    print("=" * 78)
    print(ascii_histogram(champs, names, args.sims))
    print("-" * 78)
    print(f"{'player':<28} {'avg finish':>10} {'best':>6} {'worst':>6}")
    for name in names:
        pl = placements[name]
        print(f"{name:<28} {sum(pl) / len(pl):>10.2f} {min(pl):>6} {max(pl):>6}")
    print("-" * 78)
    print(f"{total_hands} hands dealt across {args.sims} tournaments "
          f"in {elapsed:.1f}s")

    write_report(champs, placements, names, args, total_hands)
    try:
        write_png(champs, names, args.sims)
        print("chart:  holdem_sim/results/winners_histogram.png")
    except ImportError:
        print("(matplotlib not installed — skipped the PNG chart)")
    print("report: holdem_sim/results/RESULTS.md")


def write_report(champs, placements, names, args, total_hands):
    import os
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(here, exist_ok=True)
    with open(os.path.join(here, "RESULTS.md"), "w") as fh:
        fh.write("# Winner Winner Chicken Dinner — results\n\n")
        fh.write(f"{args.sims} six-max no-limit hold'em tournaments, "
                 f"{args.chips} starting chips each, blinds 10/20 doubling "
                 f"every 15 hands, seed {args.seed}. "
                 f"{total_hands} hands dealt in total.\n\n")
        fh.write("Player 1 runs the sacred text `if my_turn then bet = All in fi`. "
                 "Players 2–6 run elaborate strategies. Nobody knows anybody "
                 "else's algorithm.\n\n")
        fh.write("## Championships\n\n```\n")
        fh.write(ascii_histogram(champs, names, args.sims))
        fh.write("\n```\n\n## Finishing positions\n\n")
        fh.write("| player | championships | avg finish | best | worst |\n")
        fh.write("|---|---|---|---|---|\n")
        for name in names:
            pl = placements[name]
            fh.write(f"| {name} | {champs.get(name, 0)} "
                     f"| {sum(pl) / len(pl):.2f} | {min(pl)} | {max(pl)} |\n")
        fh.write("\n![histogram](winners_histogram.png)\n")


def write_png(champs, names, n_sims):
    import os
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    wins = [champs.get(n, 0) for n in names]
    colors = ["#D4574E" if n.startswith("P1") else "#4E79A7" for n in names]
    fig, ax = plt.subplots(figsize=(11, 5))
    bars = ax.bar(range(len(names)), wins, color=colors)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace(" ", "\n", 1) for n in names], fontsize=8)
    ax.set_ylabel("tournaments won")
    ax.set_title(f"Winner winner chicken dinner — {n_sims} tournaments\n"
                 "(red = the all-in guy)")
    for b, w in zip(bars, wins):
        ax.annotate(str(w), (b.get_x() + b.get_width() / 2, w),
                    ha="center", va="bottom", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
    os.makedirs(here, exist_ok=True)
    fig.savefig(os.path.join(here, "winners_histogram.png"), dpi=150)


if __name__ == "__main__":
    main()
