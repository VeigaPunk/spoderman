"""Run 100 Hold'em tournaments and print a histogram of winners."""
import json
import random
import sys
from holdem import Table, Player
from strategies import (AllInMonkey, TightAggressive, LooseAggressive,
                        Rock, MathProfessor, Profiler)

N_SIMS = 100
START_CHIPS = 1000

STRATEGY_FACTORIES = {
    1: AllInMonkey,
    2: TightAggressive,
    3: LooseAggressive,
    4: Rock,
    5: MathProfessor,
    6: Profiler,
}


def main(seed=42):
    rng = random.Random(seed)
    wins = {i: 0 for i in STRATEGY_FACTORIES}
    for sim in range(N_SIMS):
        players = [Player(idx=i, strategy=cls(), chips=START_CHIPS)
                   for i, cls in STRATEGY_FACTORIES.items()]
        table = Table(players, rng=random.Random(rng.randrange(2**32)))
        winner = table.run_tournament()
        wins[winner] += 1
        if (sim + 1) % 10 == 0:
            print(f"  ... {sim + 1}/{N_SIMS} tournaments done", file=sys.stderr)

    names = {i: cls.name for i, cls in STRATEGY_FACTORIES.items()}
    print()
    print("WINNER WINNER CHICKEN DINNER — 100 tournaments, 6 players, "
          f"{START_CHIPS} chips each")
    print("=" * 70)
    width = max(len(f"P{i} {names[i]}") for i in names)
    for i in sorted(wins, key=lambda k: -wins[k]):
        label = f"P{i} {names[i]}".ljust(width)
        bar = "#" * wins[i]
        print(f"{label} | {bar} {wins[i]}")
    print("=" * 70)

    with open("results.json", "w") as f:
        json.dump({"wins": wins, "names": names, "sims": N_SIMS,
                   "start_chips": START_CHIPS, "seed": seed}, f, indent=2)
    print("results saved to results.json")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 42)
