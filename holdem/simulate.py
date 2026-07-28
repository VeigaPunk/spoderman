"""Run N six-player Hold'em tournaments and histogram the winners.

Usage: python -m holdem.simulate [n_sims]
"""

import json
import os
import sys
import time
from collections import Counter, defaultdict

from .engine import Tournament, START_STACK
from .strategies import LINEUP


def run_sims(n_sims):
    names = [s.name for s in LINEUP]
    factories = [(lambda rng, cls=cls: cls(rng)) for cls in LINEUP]
    wins = Counter()
    placements_sum = defaultdict(int)
    first_bust = Counter()
    hand_counts = []
    t0 = time.time()

    for seed in range(1, n_sims + 1):
        t = Tournament(factories, names, seed)
        winner, placements, hands = t.run()
        total = sum(p.stack for p in t.players)
        assert total == START_STACK * len(names), f"chips leaked: {total}"
        wins[winner] += 1
        for pid, place in placements.items():
            placements_sum[pid] += place
        first_bust[t.eliminated[0]] += 1
        hand_counts.append(hands)
        if seed % 20 == 0:
            print(f"  ... {seed}/{n_sims} tournaments "
                  f"({time.time() - t0:.1f}s)", flush=True)

    return {
        "n_sims": n_sims,
        "names": names,
        "wins": {pid: wins.get(pid, 0) for pid in range(1, len(names) + 1)},
        "avg_place": {pid: placements_sum[pid] / n_sims
                      for pid in range(1, len(names) + 1)},
        "first_bust": {pid: first_bust.get(pid, 0)
                       for pid in range(1, len(names) + 1)},
        "avg_hands": sum(hand_counts) / len(hand_counts),
        "elapsed_s": time.time() - t0,
    }


def ascii_histogram(res):
    lines = ["", "🏆 WINNER WINNER CHICKEN DINNER — "
             f"tournament wins out of {res['n_sims']}", ""]
    peak = max(res["wins"].values()) or 1
    for pid in range(1, len(res["names"]) + 1):
        w = res["wins"][pid]
        bar = "█" * round(40 * w / peak)
        tag = "  <- the one-liner" if pid == 1 else ""
        lines.append(f"  P{pid} {res['names'][pid - 1]:<12} {bar:<40} "
                     f"{w:>3} ({100 * w / res['n_sims']:.0f}%){tag}")
    lines.append("")
    lines.append(f"  avg finishing place: " + ", ".join(
        f"P{pid} {res['avg_place'][pid]:.2f}"
        for pid in range(1, len(res["names"]) + 1)))
    lines.append(f"  first player eliminated: " + ", ".join(
        f"P{pid} x{res['first_bust'][pid]}"
        for pid in range(1, len(res["names"]) + 1)))
    lines.append(f"  avg hands per tournament: {res['avg_hands']:.0f}   "
                 f"total runtime: {res['elapsed_s']:.1f}s")
    return "\n".join(lines)


def plot(res, out_png):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
    BLUE, ORANGE = "#2a78d6", "#eb6834"   # validated categorical slots 1 & 2

    wins = {int(k): v for k, v in res["wins"].items()}  # survives JSON round-trip
    labels = [f"P{i}\n{n}" for i, n in enumerate(res["names"], 1)]
    values = [wins[i] for i in range(1, len(res["names"]) + 1)]
    colors = [ORANGE] + [BLUE] * 5

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    bars = ax.bar(labels, values, color=colors, width=0.62, zorder=3)
    for b, val in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, val + max(values) * 0.02,
                str(val), ha="center", va="bottom", fontsize=11,
                color=INK, fontweight="bold")
    ax.set_title(f"Winner-winner chicken dinner — {res['n_sims']} six-player "
                 "Hold'em tournaments", color=INK, fontsize=13, pad=14,
                 loc="left", fontweight="bold")
    ax.set_ylabel("tournaments won", color=INK2, fontsize=10)
    ax.tick_params(colors=MUTED, labelsize=9)
    for lbl in ax.get_xticklabels():
        lbl.set_color(INK2)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.yaxis.grid(True, color="#f0efec", zorder=0)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(values) * 1.28)
    handles = [plt.Rectangle((0, 0), 1, 1, color=ORANGE),
               plt.Rectangle((0, 0), 1, 1, color=BLUE)]
    ax.legend(handles, ['"if my_turn then bet = All in fi"',
                        "elaborate strategy"],
              frameon=False, fontsize=9, labelcolor=INK2, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_png, facecolor=SURFACE)
    print(f"  chart saved to {out_png}")


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print(f"Running {n_sims} tournaments: 6 players, {START_STACK} chips each, "
          "escalating blinds, winner takes the table...")
    res = run_sims(n_sims)
    print(ascii_histogram(res))

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(res, f, indent=2)
    try:
        plot(res, os.path.join(out_dir, "winner_histogram.png"))
    except ImportError:
        print("  (matplotlib not available; skipped PNG)")


if __name__ == "__main__":
    main()
