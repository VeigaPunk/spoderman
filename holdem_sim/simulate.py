"""Run N full 6-max Hold'em tournaments and histogram the winners.

Usage: python3 simulate.py [n_sims] [seed]
"""

import random
import sys
import time

from engine import PlayerState, Tournament
from strategies import ROSTER


def run(n_sims=100, seed=42):
    wins = {name: 0 for name, _ in ROSTER}
    t0 = time.time()
    hand_counts = []
    for sim in range(n_sims):
        rng = random.Random(seed * 100_000 + sim)
        players = []
        for pid, (name, cls) in enumerate(ROSTER):
            strat = cls(random.Random(rng.random()))
            if hasattr(strat, "name"):
                strat.name = name
            players.append(PlayerState(pid, name, strat, 1000))
        tour = Tournament(players, rng, start_chips=1000, sb=10,
                          blind_double_every=15)
        tour.button = sim % len(players)  # rotate starting button for fairness
        winner = tour.run()
        wins[winner.name] += 1
        hand_counts.append(tour.hands_played)
        if (sim + 1) % 20 == 0:
            print(f"  ... {sim + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)")
    return wins, hand_counts


def ascii_histogram(wins, n_sims):
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — tournament victories "
                 f"({n_sims} sims, 6 players, 1000 chips each)")
    lines.append("=" * 72)
    width = 50
    top = max(wins.values()) or 1
    for name, w in wins.items():
        bar = "#" * round(w / top * width)
        lines.append(f"{name:<13} | {bar:<{width}} {w:>3}  ({w / n_sims:.0%})")
    lines.append("=" * 72)
    return "\n".join(lines)


if __name__ == "__main__":
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(f"Running {n_sims} tournaments (seed={seed})...")
    wins, hand_counts = run(n_sims, seed)
    hist = ascii_histogram(wins, n_sims)
    print(hist)
    avg = sum(hand_counts) / len(hand_counts)
    print(f"\nAvg tournament length: {avg:.1f} hands "
          f"(min {min(hand_counts)}, max {max(hand_counts)})")
    with open("results.txt", "w") as f:
        f.write(hist + "\n")
        f.write(f"\nAvg tournament length: {avg:.1f} hands\n")
        f.write(f"seed={seed}, n_sims={n_sims}\n")
