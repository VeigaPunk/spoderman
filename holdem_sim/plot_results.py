"""Render the winner histogram as a PNG (requires matplotlib)."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Palette (validated): blue = elaborate strategies, orange = the all-in bot
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

STRATEGY = {
    "P1 AllInAndy": "if my_turn then bet = ALL IN fi",
    "P2 TAG-Tanya": "tight-aggressive, positional ranges",
    "P3 LAG-Lars": "loose-aggressive, semi-bluffs",
    "P4 MC-Matt": "Monte Carlo equity vs pot odds",
    "P5 Nit-Nadia": "ultra-tight premium ambusher",
    "P6 Ada-Adapt": "adaptive opponent exploiter",
}


def plot(wins, n_sims, path="winners_histogram.png"):
    items = sorted(wins.items(), key=lambda kv: kv[1])  # winner at top
    names = [k for k, _ in items]
    vals = [v for _, v in items]
    colors = [ORANGE if n.startswith("P1") else BLUE for n in names]

    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.barh(range(len(names)), vals, height=0.55, color=colors, zorder=3)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(
        [f"{n}  ·  {STRATEGY[n]}" for n in names],
        fontsize=9, color=SECONDARY, family="sans-serif")

    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.015, i, f"{v}  ({v / n_sims:.0%})",
                va="center", fontsize=10, color=INK, family="sans-serif")

    ax.set_xlim(0, max(vals) * 1.18)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.tick_params(axis="y", length=0)

    ax.set_title(
        "Winner winner chicken dinner — tournament victories\n",
        loc="left", fontsize=13, color=INK, family="sans-serif",
        fontweight="bold")
    ax.text(0, 1.02,
            f"{n_sims} full 6-max NLHE tournaments · 1000 chips each · "
            "escalating blinds · orange = the all-in bot",
            transform=ax.transAxes, fontsize=9, color=MUTED,
            family="sans-serif")

    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {path}")


if __name__ == "__main__":
    import random
    from simulate import run
    import sys
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    wins, _ = run(n_sims, seed)
    plot(wins, n_sims)
