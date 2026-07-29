"""Run N Hold'em tournaments and histogram the champions.

    python3 simulate.py [--sims 100] [--seed 42] [--out results]

Prints an ASCII histogram and writes a PNG bar chart + CSV of raw results.
"""

from __future__ import annotations

import argparse
import csv
import os
import random
from collections import Counter

from engine import Tournament
from strategies import default_lineup

PLAYERS = {pid: s.name for pid, s in default_lineup().items()}


def run_sims(n_sims, base_seed):
    champions = Counter()
    finishes = {p: [] for p in PLAYERS}      # finishing place, 1 = champion
    hands = []
    rows = []
    for i in range(n_sims):
        rng = random.Random(base_seed + i)
        result = Tournament(default_lineup(), rng).run()
        champions[result.champion] += 1
        n = len(result.finish_order)
        for place_from_bottom, pid in enumerate(result.finish_order):
            finishes[pid].append(n - place_from_bottom)
        hands.append(result.hands_played)
        rows.append((i + 1, base_seed + i, result.champion,
                     result.hands_played, "-".join(map(str, result.finish_order))))
    return champions, finishes, hands, rows


def ascii_histogram(champions, n_sims):
    width = 46
    peak = max(champions.values()) if champions else 1
    lines = ["", f"CHAMPIONSHIPS over {n_sims} tournaments "
                 f"(winner winner chicken dinner count)", "=" * 78]
    for pid in sorted(PLAYERS):
        wins = champions.get(pid, 0)
        bar = "#" * max(1 if wins else 0, round(wins / peak * width))
        lines.append(f"P{pid} {PLAYERS[pid]:<24} |{bar:<{width}}| "
                     f"{wins:3d}  ({wins / n_sims:5.1%})")
    lines.append("=" * 78)
    return "\n".join(lines)


def summary_table(champions, finishes, hands, n_sims):
    lines = ["", f"{'player':<28}{'wins':>6}{'avg finish':>12}{'busted 1st':>12}",
             "-" * 58]
    for pid in sorted(PLAYERS):
        fs = finishes[pid]
        avg = sum(fs) / len(fs)
        busted_first = sum(1 for f in fs if f == len(PLAYERS))
        lines.append(f"P{pid} {PLAYERS[pid]:<25}{champions.get(pid, 0):>6}"
                     f"{avg:>12.2f}{busted_first:>12}")
    lines.append("-" * 58)
    lines.append(f"avg tournament length: {sum(hands) / len(hands):.0f} hands")
    return "\n".join(lines)


def render_png(champions, n_sims, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, PRIMARY, SECONDARY = "#fcfcfb", "#0b0b0b", "#52514e"
    FIELD, MANIAC = "#2a78d6", "#eb6834"        # validated adjacent-safe pair

    pids = sorted(PLAYERS)
    wins = [champions.get(p, 0) for p in pids]
    colors = [MANIAC if p == 1 else FIELD for p in pids]
    labels = [f"P{p}\n{PLAYERS[p].split(' (')[0]}" for p in pids]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.bar(range(len(pids)), wins, color=colors, width=0.62, zorder=3)
    for rect, w in zip(bars, wins):
        ax.text(rect.get_x() + rect.get_width() / 2, w + max(wins) * 0.015,
                str(w), ha="center", va="bottom", fontsize=11,
                color=PRIMARY, fontweight="bold", zorder=4)

    ax.set_title(f"Last player standing — {n_sims} full 6-max tournaments",
                 color=PRIMARY, fontsize=14, fontweight="bold", loc="left", pad=18)
    ax.text(0, 1.02, "Every player starts with 1,000 chips. "
            "P1's whole strategy: if my_turn then bet = ALL IN fi",
            transform=ax.transAxes, color=SECONDARY, fontsize=9.5)
    ax.set_ylabel("tournaments won", color=SECONDARY, fontsize=10)
    ax.set_xticks(range(len(pids)), labels, color=PRIMARY, fontsize=9.5)
    ax.tick_params(colors=SECONDARY, length=0)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8, zorder=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#d4d3cf")
    ax.margins(y=0.12)

    handles = [plt.Rectangle((0, 0), 1, 1, color=MANIAC),
               plt.Rectangle((0, 0), 1, 1, color=FIELD)]
    ax.legend(handles, ["all-in bot", "elaborate strategies"],
              frameon=False, loc="upper left", fontsize=9,
              labelcolor=SECONDARY)

    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "results"))
    args = ap.parse_args()

    print(f"Dealing {args.sims} tournaments (seed {args.seed})...")
    champions, finishes, hands, rows = run_sims(args.sims, args.seed)

    print(ascii_histogram(champions, args.sims))
    print(summary_table(champions, finishes, hands, args.sims))

    os.makedirs(args.out, exist_ok=True)
    csv_path = os.path.join(args.out, "tournaments.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sim", "seed", "champion", "hands", "finish_order_bottom_up"])
        w.writerows(rows)
    png_path = os.path.join(args.out, "winner_histogram.png")
    render_png(champions, args.sims, png_path)
    print(f"\nwrote {png_path}\nwrote {csv_path}")


if __name__ == "__main__":
    main()
