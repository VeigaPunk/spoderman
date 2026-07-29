"""
Run N full Texas Hold'em tournaments (default 100) with the 6-player lineup
and print a histogram of tournament winners.

Usage:
    python3 simulate.py [n_sims] [--seed S] [--verbose-first]
"""

import json
import sys
import time
from collections import Counter

from engine import Tournament
from strategies import LINEUP

STARTING_CHIPS = 2000


def run_sims(n_sims=100, base_seed=42, verbose_first=False):
    winners = []
    t0 = time.time()
    for i in range(n_sims):
        t = Tournament(LINEUP, starting_chips=STARTING_CHIPS,
                       seed=base_seed + i, verbose=(verbose_first and i == 0))
        winners.append(t.run())
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", flush=True)
    return winners


def ascii_histogram(counts, n_sims, width=50):
    lines = []
    lines.append("")
    lines.append("=" * 72)
    lines.append("   WINNER WINNER CHICKEN DINNER — tournament wins out of "
                 f"{n_sims} sims")
    lines.append("=" * 72)
    top = max(counts.values()) if counts else 1
    for name, _cls in LINEUP:
        n = counts.get(name, 0)
        bar = "█" * max(1 if n else 0, round(n / top * width))
        pct = 100.0 * n / n_sims
        lines.append(f"{name:<16} {n:>3} ({pct:4.1f}%) |{bar}")
    lines.append("=" * 72)
    champ = max(counts, key=counts.get)
    lines.append(f"   🏆 Most chicken dinners: {champ} with {counts[champ]} wins")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    n_sims = 100
    seed = 42
    verbose_first = "--verbose-first" in args
    positional = [a for a in args if not a.startswith("--")]
    if positional:
        n_sims = int(positional[0])
    if "--seed" in args:
        seed = int(args[args.index("--seed") + 1])

    print(f"Running {n_sims} six-max NLHE tournaments "
          f"({STARTING_CHIPS} starting chips, escalating blinds, seed={seed})")
    winners = run_sims(n_sims, seed, verbose_first)
    counts = Counter(winners)

    print(ascii_histogram(counts, n_sims))

    with open("results.json", "w") as f:
        json.dump({"n_sims": n_sims, "seed": seed,
                   "counts": {name: counts.get(name, 0) for name, _ in LINEUP},
                   "winners": winners}, f, indent=2)
    print("\nSaved raw results to results.json")


if __name__ == "__main__":
    main()
