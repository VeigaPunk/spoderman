#!/usr/bin/env python3
"""Run N single-table Texas Hold'em tournaments and print the winner histogram.

Seat 1 plays "if my_turn then bet = All in fi". Seats 2-6 play five elaborate
strategies. Nobody is told anybody else's strategy.
"""

import argparse
import random
import time

from holdem.engine import Tournament
from holdem.strategies import default_lineup


def run(n_sims, seed, starting_stack):
    wins = {seat: 0 for seat in range(1, 7)}
    placements = {seat: [] for seat in range(1, 7)}
    hands_total = 0
    names = {}
    t0 = time.time()
    for i in range(n_sims):
        master = random.Random(seed * 1_000_003 + i)
        lineup = default_lineup(lambda: random.Random(master.random()))
        for seat, strat in enumerate(lineup, start=1):
            names[seat] = strat.name
        tourney = Tournament(lineup, rng=master, starting_stack=starting_stack)
        winner = tourney.run()
        wins[winner] += 1
        hands_total += tourney.hand_no
        # elimination_order: first bust first; place 6 = first out, 1 = winner
        for rank_from_first_out, seat in enumerate(tourney.elimination_order):
            placements[seat].append(len(tourney.elimination_order) - rank_from_first_out)
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s, avg {hands_total / (i + 1):.0f} hands/tourney)")
    return wins, placements, names, hands_total, time.time() - t0


def histogram(wins, placements, names, n_sims):
    print()
    print("=" * 66)
    print("   WINNER WINNER CHICKEN DINNER — tournament wins per player")
    print("=" * 66)
    top = max(wins.values()) or 1
    for seat in sorted(wins):
        bar = "█" * round(44 * wins[seat] / top)
        label = f"P{seat} {names[seat]:<15}"
        print(f"{label} | {bar} {wins[seat]}")
    print("-" * 66)
    print(f"{'':20}   total tournaments: {n_sims}")
    print()
    print("Average finishing place (1 = chicken dinner, 6 = first bust):")
    for seat in sorted(placements):
        avg = sum(placements[seat]) / len(placements[seat])
        print(f"  P{seat} {names[seat]:<15} {avg:.2f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=2000)
    args = ap.parse_args()

    print(f"Dealing {args.sims} tournaments (6 players, {args.stack} chips each, "
          f"blinds 10/20 doubling every 20 hands)...")
    wins, placements, names, hands, elapsed = run(args.sims, args.seed, args.stack)
    histogram(wins, placements, names, args.sims)
    print(f"\nSimulated {hands} hands in {elapsed:.1f}s. GG.")


if __name__ == "__main__":
    main()
