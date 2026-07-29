"""Run N full tournaments and chart who ends up as the last player standing.

Usage:  python -m holdem.simulate [--sims 100] [--seed 42] [--out winners.png]
"""

import argparse
from collections import Counter

from .engine import play_tournament
from .strategies import build_lineup

PLAYER_NAMES = [
    "P1 YOLO all-in",
    "P2 tight-aggro",
    "P3 loose-aggro",
    "P4 nit/rock",
    "P5 pot-odds EV",
    "P6 adaptive",
]


def run(sims, seed):
    wins = Counter()
    total_hands = 0
    for i in range(sims):
        lineup = build_lineup()  # fresh strategy state (no memory across tournaments)
        winner, hands = play_tournament(lineup, PLAYER_NAMES, seed=seed + i)
        wins[winner] += 1
        total_hands += hands
    return wins, total_hands


def ascii_histogram(wins, sims):
    width = 40
    peak = max(wins.values()) if wins else 1
    lines = ["", f"WINNER WINNER CHICKEN DINNER — {sims} tournaments", "=" * 66]
    for pid in range(1, 7):
        n = wins.get(pid, 0)
        bar = "█" * max(0, round(n / peak * width)) or ("▏" if n else "")
        lines.append(f"{PLAYER_NAMES[pid - 1]:<16} {bar:<{width}} {n:>3}  ({n / sims:.0%})")
    lines.append("=" * 66)
    return "\n".join(lines)


def png_histogram(wins, sims, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink2 = "#fcfcfb", "#0b0b0b", "#52514e"
    blue, orange = "#2a78d6", "#eb6834"  # validated categorical pair

    counts = [wins.get(pid, 0) for pid in range(1, 7)]
    colors = [orange] + [blue] * 5

    fig, ax = plt.subplots(figsize=(8.5, 4.6), dpi=160)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)

    bars = ax.bar(range(6), counts, color=colors, width=0.62, zorder=3)
    for bar, n in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, n + max(counts) * 0.02,
                str(n), ha="center", va="bottom", fontsize=11, color=ink)

    ax.set_xticks(range(6))
    ax.set_xticklabels([n.replace(" ", "\n", 1) for n in PLAYER_NAMES],
                       fontsize=9, color=ink2)
    ax.set_ylabel("tournaments won", fontsize=10, color=ink2)
    ax.set_ylim(0, max(counts) * 1.15 or 1)
    ax.tick_params(colors=ink2, length=0)
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.8, zorder=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#d8d7d2")

    ax.set_title(f"Last player standing across {sims} Hold'em tournaments",
                 fontsize=13, color=ink, pad=14, loc="left")
    handles = [plt.Rectangle((0, 0), 1, 1, color=orange),
               plt.Rectangle((0, 0), 1, 1, color=blue)]
    ax.legend(handles, ['"if my_turn then all-in fi"', "elaborate strategy"],
              frameon=False, fontsize=9, labelcolor=ink2, loc="upper right")

    fig.tight_layout()
    fig.savefig(path, facecolor=surface)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="winners.png")
    args = ap.parse_args()

    wins, total_hands = run(args.sims, args.seed)
    print(ascii_histogram(wins, args.sims))
    print(f"avg tournament length: {total_hands / args.sims:.1f} hands")
    try:
        png_histogram(wins, args.sims, args.out)
        print(f"histogram saved to {args.out}")
    except ImportError:
        print("(matplotlib not installed — skipped PNG histogram)")


if __name__ == "__main__":
    main()
