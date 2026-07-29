#!/usr/bin/env python3
"""Render the tournament-winner histogram from results/results.json."""

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))

# palette (validated: CVD dE 24.7, contrast >= 3:1 on this surface)
SURFACE = "#fcfcfb"
SERIES = "#2a78d6"      # the five real strategies
HIGHLIGHT = "#eb6834"   # the all-in bot
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"

LABELS = [
    "P1\nSuflairGPT\n(all-in bot)",
    "P2\nTAG Shark",
    "P3\nLAG\nBluffmaster",
    "P4\nRock Nit",
    "P5\nEquity Nerd",
    "P6\nAdaptive\nHustler",
]
ORDER = ["SuflairGPT_AllIn", "TAG_Shark", "LAG_Bluffmaster",
         "Rock_Nit", "EquityNerd", "Adaptive_Hustler"]


def main():
    with open(os.path.join(HERE, "results", "results.json")) as f:
        data = json.load(f)
    wins = [data["wins"].get(name, 0) for name in ORDER]
    sims = data["sims"]

    fig, ax = plt.subplots(figsize=(9.6, 5.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    colors = [HIGHLIGHT] + [SERIES] * 5
    bars = ax.bar(range(6), wins, width=0.62, color=colors, zorder=3)

    for rect, w in zip(bars, wins):
        ax.text(rect.get_x() + rect.get_width() / 2, w + 0.6, str(w),
                ha="center", va="bottom", fontsize=12, color=INK,
                fontweight="bold")

    ax.set_xticks(range(6))
    ax.set_xticklabels(LABELS, fontsize=9, color=INK_2)
    ax.set_ylabel("tournaments won", fontsize=10, color=MUTED)
    ax.set_ylim(0, max(wins) * 1.22)
    ax.yaxis.set_tick_params(labelsize=9, colors=MUTED, length=0)
    ax.xaxis.set_tick_params(length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)

    ax.set_title(
        f"Winner winner chicken dinner — last player standing "
        f"({sims} six-max freezeouts)",
        fontsize=13, color=INK, pad=14, loc="left", fontweight="bold")
    ax.text(0, 1.015,
            'orange = "if my_turn: bet = ALL IN"  ·  blue = the five '
            "elaborate strategies  ·  same starting stacks, escalating blinds",
            transform=ax.transAxes, fontsize=9, color=INK_2, va="bottom")

    out = os.path.join(HERE, "results", "winner_histogram.png")
    fig.tight_layout()
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    print("wrote", out)


if __name__ == "__main__":
    main()
