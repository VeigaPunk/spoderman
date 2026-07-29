"""Supporting analysis: heads-up duels and a seat-fairness control.

    python -m holdem.analysis
"""

import collections
import sys

from .engine import Table
from .strategies import (MadRabbit, Ironclad, RageBaby, ThinkingTiger,
                         SkullPeaky, BlueDemon)

ELABORATE = [Ironclad, RageBaby, ThinkingTiger, SkullPeaky, BlueDemon]


def duel(cls_a, cls_b, sims, chips=10000, base_seed=555):
    """Heads-up freezeouts, alternating seats to cancel any positional edge."""
    wins_a = 0
    for i in range(sims):
        if i % 2 == 0:
            agents, a_seat = [cls_a(), cls_b()], 1
        else:
            agents, a_seat = [cls_b(), cls_a()], 2
        table = Table(agents, starting_chips=chips, seed=base_seed + i * 101,
                      max_hands=1500)
        if table.run() == a_seat:
            wins_a += 1
    return wins_a


def heads_up_matrix(sims=400):
    print("HEADS-UP: all-in bot vs each elaborate strategy (%d duels each,"
          " seats alternated)" % sims)
    print("  " + "-" * 70)
    for cls in ELABORATE:
        w = duel(MadRabbit, cls, sims)
        pct = 100.0 * w / sims
        bar = "█" * int(pct / 2)
        print("   all-in vs %-38s %5.1f%%  %s" % (cls.name[:38], pct, bar))
    print()


def seat_fairness(sims=300):
    print("CONTROL: six identical all-in bots -- the engine must not favour a seat")
    print("  " + "-" * 70)
    wins = collections.Counter()
    for i in range(sims):
        table = Table([MadRabbit() for _ in range(6)], starting_chips=10000,
                      seed=90000 + i * 13)
        wins[table.run()] += 1
    expected = sims / 6.0
    chi2 = sum((wins[p] - expected) ** 2 / expected for p in range(1, 7))
    for pid in range(1, 7):
        print("   seat %d  %4d wins  %5.1f%%  %s"
              % (pid, wins[pid], 100.0 * wins[pid] / sims,
                 "█" * int(wins[pid] * 36.0 / max(wins.values()))))
    # 5 degrees of freedom: 11.07 is the 0.05 critical value.
    print("   chi-square = %.2f (5 d.o.f., 11.07 = p0.05) -> %s"
          % (chi2, "no detectable seat bias" if chi2 < 11.07
             else "POSSIBLE SEAT BIAS"))
    print()


def main():
    seat_fairness()
    heads_up_matrix()
    return 0


if __name__ == "__main__":
    sys.exit(main())
