#!/usr/bin/env python3
"""Render the tournament-winner histogram from a holdem_sim.py run as a PNG."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Results of: python3 holdem_sim.py 100 42
RESULTS = [
    ("P1 Suflair-GPT\n(all-in bot)", 11),
    ("P2 The Rock\n(tight-aggro)", 29),
    ("P3 Blaze the LAG\n(loose-aggro)", 16),
    ("P4 The Professor\n(position/texture)", 10),
    ("P5 The Mathematician\n(pot odds EV)", 12),
    ("P6 The Shark\n(adaptive)", 22),
]

names = [n for n, _ in RESULTS]
wins = [w for _, w in RESULTS]
colors = ["#d4183d"] + ["#4a5568"] * 5  # the all-in bot gets called out in red

fig, ax = plt.subplots(figsize=(11, 6))
bars = ax.bar(names, wins, color=colors, edgecolor="black", linewidth=0.8)
for bar, w in zip(bars, wins):
    ax.text(bar.get_x() + bar.get_width() / 2, w + 0.5, f"{w}",
            ha="center", va="bottom", fontsize=13, fontweight="bold")

ax.set_ylabel("Tournaments won (out of 100)", fontsize=12)
ax.set_title("Winner Winner Chicken Dinner — 100 Texas Hold'em tournaments\n"
             "6 players, equal starting stacks, escalating blinds, last one standing",
             fontsize=13)
ax.set_ylim(0, max(wins) + 5)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.grid(axis="y", alpha=0.25)

plt.tight_layout()
plt.savefig("winners_histogram.png", dpi=150)
print("wrote winners_histogram.png")
