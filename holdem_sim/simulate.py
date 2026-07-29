"""Run N full 6-player tournaments and print the winner histogram.

Usage:  python3 -m holdem_sim.simulate [--sims 100] [--seed 42]
"""

import argparse
import random
import sys
import time

from .engine import Player, Tournament
from .strategies import ROSTER


def run_tournament(seed):
    rng = random.Random(seed)
    players = [Player(pid, cls(random.Random(seed * 1000 + pid)))
               for pid, cls in ROSTER]
    t = Tournament(players, rng, start_stack=1000, sb=10, bb=20,
                   escalate_every=25)
    winner, finishing = t.run()
    return winner, finishing, t.hand_no


def histogram(wins, names, total, width=50):
    lines = []
    peak = max(wins.values()) if wins else 1
    for pid in sorted(names):
        n = wins.get(pid, 0)
        bar = '█' * max(0, round(n / peak * width))
        if n > 0 and not bar:
            bar = '▏'
        lines.append(f"  P{pid} {names[pid]:<16} {bar} {n}")
    return '\n'.join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sims', type=int, default=100)
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args(argv)

    names = {pid: cls.name for pid, cls in ROSTER}
    wins = {pid: 0 for pid in names}
    finish_sum = {pid: 0 for pid in names}
    hands_total = 0

    t0 = time.time()
    for i in range(args.sims):
        winner, finishing, hands = run_tournament(args.seed + i)
        wins[winner.id] += 1
        hands_total += hands
        for pos, p in enumerate(finishing, start=1):
            finish_sum[p.id] += pos
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{args.sims} tournaments done "
                  f"({time.time() - t0:.1f}s)", file=sys.stderr)

    print()
    print(f"WINNER WINNER CHICKEN DINNER — tournament wins over "
          f"{args.sims} sims ({hands_total} hands total)")
    print()
    print(histogram(wins, names, args.sims))
    print()
    print("  Average finishing position (1 = chicken dinner, 6 = first bust):")
    for pid in sorted(names):
        avg = finish_sum[pid] / args.sims
        print(f"  P{pid} {names[pid]:<16} {avg:.2f}")
    print()
    print(f"  Elapsed: {time.time() - t0:.1f}s")
    return wins, finish_sum


if __name__ == '__main__':
    main()
