import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import poker_sim


def main():
    wins, names = poker_sim.main()
    seats = list(range(1, 7))
    counts = [wins[s] for s in seats]
    labels = [f"P{s}\n{names[s]}" for s in seats]
    colors = ["#eb6834" if s == 1 else "#2a78d6" for s in seats]

    fig, ax = plt.subplots(figsize=(9, 5.2), facecolor="#fcfcfb")
    ax.set_facecolor("#fcfcfb")
    bars = ax.bar(labels, counts, color=colors, width=0.62, zorder=3)

    for bar, c in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, c + 0.6, str(c),
                ha="center", va="bottom", fontsize=11, color="#0b0b0b")

    ax.set_title("Tournament wins over 100 sims — last player standing",
                 fontsize=13, color="#0b0b0b", pad=14, loc="left")
    ax.set_ylabel("tournaments won", fontsize=10, color="#52514e")
    ax.grid(axis="y", color="#e6e5e1", linewidth=0.8, zorder=0)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#898781")
    ax.tick_params(colors="#52514e", labelsize=9.5, length=0)
    ax.set_ylim(0, max(counts) * 1.18)

    handles = [plt.Rectangle((0, 0), 1, 1, color="#eb6834"),
               plt.Rectangle((0, 0), 1, 1, color="#2a78d6")]
    ax.legend(handles, ['"if my_turn then all-in fi"', "elaborate strategy"],
              frameon=False, fontsize=9.5, loc="upper right",
              labelcolor="#52514e")

    fig.tight_layout()
    fig.savefig("winners_histogram.png", dpi=160)
    print("saved winners_histogram.png")


if __name__ == "__main__":
    main()
