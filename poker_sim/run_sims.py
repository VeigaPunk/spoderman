"""Run N independent 6-player Texas Hold'em tournaments and print a
histogram of tournament winners.

Seat 1: All-In Andy      -> if my_turn then bet = All in fi
Seat 2: Athena (TAG)     -> tight-aggressive, Chen ranges + equity margins
Seat 3: Loki (LAG)       -> loose-aggressive, steals, bluffs, semi-bluffs
Seat 4: Granite (Nit)    -> premium-only, stacks off with the goods
Seat 5: Bayes (Odds)     -> pure pot-odds / Monte Carlo EV machine
Seat 6: Mirror (Adaptive)-> profiles opponents from observed actions

Usage: python3 run_sims.py [--sims 100] [--seed 42] [--jobs 4]
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor

from engine import Table
from strategies import LINEUP


def run_one(seed: int):
    rng = random.Random(seed)
    strategies = [cls(seed=rng.randrange(2**30)) for cls in LINEUP]
    table = Table(strategies, rng)
    winner = table.run()
    return {
        "seed": seed,
        "winner": winner,
        "hands": table.hand_no,
        "elimination_order": table.elimination_order,
    }


def histogram(counter, names, total, width=50):
    lines = []
    peak = max(counter.values()) if counter else 1
    for seat in range(len(names)):
        n = counter.get(seat, 0)
        bar = "█" * max(round(n / peak * width), 1 if n else 0)
        lines.append(
            f"  P{seat + 1} {names[seat]:<18} {bar:<{width}} {n:>3} ({n / total:.0%})"
        )
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()

    seeds = [args.seed * 1_000_003 + i for i in range(args.sims)]
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(run_one, seeds, chunksize=4))

    names = [cls.name for cls in LINEUP]
    wins = Counter(r["winner"] for r in results)
    first_out = Counter(r["elimination_order"][0] for r in results)
    finish = [[] for _ in names]
    for r in results:
        # elimination_order is bust order; winner finishes 1st
        placing = list(reversed(r["elimination_order"] + [r["winner"]]))
        seen = set()
        for place, seat in enumerate(placing, start=1):
            if seat not in seen:
                seen.add(seat)
                finish[seat].append(place)

    total = len(results)
    avg_hands = sum(r["hands"] for r in results) / total

    print(f"\n🏆 WINNER WINNER CHICKEN DINNER — {total} tournaments "
          f"(avg {avg_hands:.0f} hands each)\n")
    print(histogram(wins, names, total))
    print("\n💀 First player eliminated:\n")
    print(histogram(first_out, names, total))
    print("\n📊 Average finishing position (1 = champion, 6 = first bust):\n")
    for seat, places in enumerate(finish):
        avg = sum(places) / len(places)
        print(f"  P{seat + 1} {names[seat]:<18} {avg:.2f}")

    with open(args.out, "w") as f:
        json.dump(results, f)
    print(f"\nRaw results written to {args.out}")


if __name__ == "__main__":
    main()
