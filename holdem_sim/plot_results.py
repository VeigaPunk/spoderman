"""Render results.json as a bar chart PNG (winner histogram)."""

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"

LABELS = {
    "P1-AllInAndy": 'P1 AllInAndy — "if my_turn then all-in fi"',
    "P2-GranitGarry": "P2 GranitGarry — tight-aggressive",
    "P3-BlitzBetty": "P3 BlitzBetty — loose-aggressive",
    "P4-ActuaryAda": "P4 ActuaryAda — Monte-Carlo equity",
    "P5-ProfilerPete": "P5 ProfilerPete — opponent modeling",
    "P6-SharkSally": "P6 SharkSally — tournament shark",
}


def main():
    with open("results.json") as f:
        data = json.load(f)
    counts = data["counts"]
    n = data["n_sims"]

    names = list(counts.keys())
    values = [counts[k] for k in names]
    labels = [LABELS.get(k, k) for k in names]

    fig, ax = plt.subplots(figsize=(9.5, 4.4), dpi=160)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    y = range(len(names))[::-1]
    ax.barh(list(y), values, height=0.55, color=SERIES, zorder=3)

    for yi, v in zip(y, values):
        ax.text(v + max(values) * 0.015, yi, f"{v}", va="center", ha="left",
                fontsize=10, color=INK_2)

    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9.5, color=INK)
    ax.set_xlabel(f"Tournament wins (out of {n} simulations)",
                  fontsize=9.5, color=MUTED)
    ax.set_title("Winner winner chicken dinner — 6-max NLHE, "
                 f"{n} full tournaments", fontsize=12, color=INK,
                 loc="left", pad=12)

    ax.xaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "bottom"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(BASELINE)
    ax.tick_params(colors=MUTED, length=0)
    ax.set_xlim(0, max(values) * 1.12)

    fig.tight_layout()
    fig.savefig("winner_histogram.png", facecolor=SURFACE,
                bbox_inches="tight")
    print("Saved winner_histogram.png")


if __name__ == "__main__":
    main()
