"""Run N sit-and-go tournaments and print the winner histogram.

Usage: python3 simulate.py [n_sims] [base_seed]
"""

import sys
import time
from collections import Counter

from engine import Tournament
from strategies import make_lineup, STRATEGY_NAMES


def run(n_sims=100, base_seed=42, starting_stack=1000):
    wins = Counter()
    t0 = time.time()
    for i in range(n_sims):
        tourney = Tournament(make_lineup(), starting_stack, seed=base_seed + i)
        winner = tourney.run()
        wins[winner] += 1
        done = i + 1
        if done % 10 == 0:
            print(f"  ... {done}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", flush=True)
    return wins


def histogram(wins, n_sims):
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — last player standing, "
                 f"{n_sims} tournaments")
    lines.append("=" * 74)
    max_wins = max(wins.values()) if wins else 1
    for seat in range(1, 7):
        w = wins.get(seat, 0)
        bar = "█" * round(w / max_wins * 40)
        label = f"P{seat} {STRATEGY_NAMES[seat]}"
        lines.append(f"{label:<38}|{bar:<41}{w:>3}  ({w / n_sims:.0%})")
    lines.append("=" * 74)
    champ = max(wins, key=wins.get)
    lines.append(f"Overall champion: P{champ} {STRATEGY_NAMES[champ]} "
                 f"with {wins[champ]}/{n_sims} chicken dinners")
    return "\n".join(lines)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(f"Dealing {n} six-max sit-and-go tournaments (seed {seed})...")
    wins = run(n, seed)
    out = histogram(wins, n)
    print(out)
    with open("results.txt", "w") as f:
        f.write(out + "\n")
