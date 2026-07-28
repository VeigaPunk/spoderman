import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

# results from holdem_sim.py, 100 tournaments, base_seed=42
data = [
    ("P1  ALL-IN GREMLIN\n(if my_turn then all-in fi)", 6, ORANGE),
    ("P2  TAG Terminator", 12, BLUE),
    ("P3  LAG Lunatic", 12, BLUE),
    ("P4  PotOdds Professor", 11, BLUE),
    ("P5  Position Vulture", 42, BLUE),
    ("P6  Adaptive Shark", 17, BLUE),
]
data = data[::-1]  # top-to-bottom P1..P6 after invert
labels = [d[0] for d in data]
wins = [d[1] for d in data]
colors = [d[2] for d in data]

fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

bars = ax.barh(labels, wins, color=colors, height=0.62, zorder=3)
for bar, w in zip(bars, wins):
    ax.text(w + 0.7, bar.get_y() + bar.get_height() / 2, str(w),
            va="center", ha="left", fontsize=11, color=INK)

ax.set_title("Winner winner chicken dinner — tournament wins out of 100",
             loc="left", fontsize=13, color=INK, pad=14, weight="bold")
ax.text(0, 1.02, "6-max NLHE freezeouts · 1000 chips each · blinds double every 25 hands",
        transform=ax.transAxes, fontsize=9, color=INK2)

ax.set_xlim(0, 46)
ax.xaxis.set_ticks(range(0, 50, 10))
ax.tick_params(axis="x", colors=INK2, labelsize=9, length=0)
ax.tick_params(axis="y", colors=INK, labelsize=10, length=0)
ax.grid(axis="x", color="#e6e5e2", linewidth=0.8, zorder=0)
for spine in ax.spines.values():
    spine.set_visible(False)

fig.tight_layout()
fig.savefig("winner_histogram.png", facecolor=SURFACE, bbox_inches="tight")
print("saved winner_histogram.png")
