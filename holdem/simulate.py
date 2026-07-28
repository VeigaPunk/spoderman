"""Run N full 6-max tournaments and histogram the champions.

Usage:  python -m holdem.simulate [n_sims] [seed]
"""

import random
import sys
from collections import Counter, defaultdict

from .engine import PlayerState, play_tournament
from .strategies import lineup

START_CHIPS = 1000


def run(n_sims=100, seed=42):
    classes = lineup()
    names = [f"P{i + 1} {cls.name}" for i, cls in enumerate(classes)]
    wins = Counter()
    finishes = defaultdict(list)
    hands_played = []

    for sim in range(n_sims):
        rng = random.Random(seed * 100_003 + sim)
        players = []
        for i, cls in enumerate(classes):
            strat_rng = random.Random(seed * 1_000_003 + sim * 7 + i)
            players.append(PlayerState(i + 1, names[i],
                                       cls(i + 1, strat_rng), START_CHIPS))
        winner, ranking, hands = play_tournament(
            players, rng, button_start=sim % 6)
        wins[winner] += 1
        hands_played.append(hands)
        for place, seat in enumerate(ranking, start=1):
            finishes[seat].append(place)

    return names, wins, finishes, hands_played


def histogram(names, wins, n_sims, width=40):
    lines = []
    top = max(wins.values()) if wins else 1
    for seat in range(1, 7):
        w = wins.get(seat, 0)
        bar = "█" * max(1 if w else 0, round(w / top * width))
        lines.append(f"{names[seat - 1]:<18} {bar:<{width}} {w:>3}"
                     f"  ({100 * w / n_sims:.0f}%)")
    return "\n".join(lines)


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    names, wins, finishes, hands = run(n_sims, seed)

    print(f"WINNER WINNER CHICKEN DINNER — {n_sims} six-max tournaments, "
          f"{START_CHIPS} chips each, escalating blinds")
    print(f"(seed {seed}; avg tournament length "
          f"{sum(hands) / len(hands):.0f} hands)\n")
    print(histogram(names, wins, n_sims))
    print("\nAverage finishing place (1 = champion, 6 = first bust):")
    for seat in range(1, 7):
        f = finishes[seat]
        print(f"  {names[seat - 1]:<18} {sum(f) / len(f):.2f}")


if __name__ == "__main__":
    main()
