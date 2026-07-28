import csv

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SURFACE = '#fcfcfb'
INK = '#0b0b0b'
INK2 = '#52514e'
MUTED = '#898781'
BLUE = '#2a78d6'
ORANGE = '#eb6834'

rows = list(csv.DictReader(open('sim_results.csv')))
players = [int(r['player']) for r in rows]
strategies = [r['strategy'] for r in rows]
wins = [int(r['wins']) for r in rows]

fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

colors = [ORANGE if p == 1 else BLUE for p in players]
bars = ax.bar(range(len(players)), wins, width=0.55, color=colors, zorder=3)

for i, (b, w) in enumerate(zip(bars, wins)):
    ax.text(b.get_x() + b.get_width() / 2, w + 0.8, str(w),
            ha='center', va='bottom', fontsize=11, color=INK, fontweight='bold')

labels = [f"P{p}\n{s}" + ("\n(all-in bot)" if p == 1 else "") for p, s in zip(players, strategies)]
ax.set_xticks(range(len(players)))
ax.set_xticklabels(labels, fontsize=9, color=INK2)

ax.yaxis.grid(True, color='#e8e7e3', linewidth=1, zorder=0)
ax.set_axisbelow(True)
for spine in ('top', 'right', 'left'):
    ax.spines[spine].set_visible(False)
ax.spines['bottom'].set_color(MUTED)
ax.tick_params(axis='y', colors=MUTED, length=0, labelsize=9)
ax.tick_params(axis='x', length=0)

ax.set_ylabel('Tournament wins', fontsize=10, color=INK2)
ax.set_title('Winner winner chicken dinner — 100 NLHE tournaments, 6 players',
             fontsize=13, color=INK, pad=14, loc='left', fontweight='bold')
ax.set_ylim(0, max(wins) * 1.15)

fig.tight_layout()
fig.savefig('winners_histogram.png', facecolor=SURFACE, bbox_inches='tight')
print('saved winners_histogram.png')
