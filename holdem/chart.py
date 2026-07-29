"""Render the tournament-winner histogram as a PNG."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Reference dataviz palette (light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"    # elaborate strategies
ORANGE = "#eb6834"  # the ALL-IN bot


def render_chart(payload, out_path):
    players = payload["players"]
    n = payload["n_sims"]
    labels = [f"{p['seat']}\n{p['name']}" for p in players]
    wins = [p["wins"] for p in players]
    colors = [ORANGE if p["seat"] == "P1" else BLUE for p in players]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    bars = ax.bar(range(len(players)), wins, color=colors, width=0.62,
                  zorder=3)
    for bar, w in zip(bars, wins):
        ax.annotate(f"{w}", (bar.get_x() + bar.get_width() / 2, w),
                    textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=11, color=INK,
                    fontweight="bold")

    ax.set_title("Winner winner chicken dinner", loc="left", fontsize=15,
                 color=INK, fontweight="bold", pad=18)
    ax.text(0, 1.035, f"Tournament wins across {n} six-handed no-limit "
            "hold'em sit-and-gos, equal starting stacks",
            transform=ax.transAxes, fontsize=9.5, color=INK_2)

    ax.set_xticks(range(len(players)))
    ax.set_xticklabels(labels, fontsize=9, color=INK_2)
    ax.set_ylabel("tournaments won", fontsize=9.5, color=MUTED)
    ax.tick_params(colors=MUTED, length=0)
    ax.set_ylim(0, max(wins) * 1.18)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8, zorder=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)

    handles = [plt.Rectangle((0, 0), 1, 1, color=BLUE),
               plt.Rectangle((0, 0), 1, 1, color=ORANGE)]
    ax.legend(handles, ["elaborate strategy", '"if my_turn then ALL IN fi"'],
              frameon=False, fontsize=9, labelcolor=INK_2,
              loc="upper right", bbox_to_anchor=(1.0, 1.02))

    fig.tight_layout()
    fig.savefig(out_path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return out_path
