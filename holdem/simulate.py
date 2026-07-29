"""Run N full 6-player Hold'em tournaments and print the champion histogram.

Usage:  python -m holdem.simulate [-n 100] [--seed 42]
"""
import argparse
import random
import time
from collections import Counter, defaultdict

from .engine import Tournament
from .strategies import (
    AdaptiveExploiter,
    AllInBot,
    EquityOracle,
    LooseAggressive,
    NitPushFold,
    TightAggressive,
)

ROSTER = [
    (1, AllInBot,        "if my_turn then bet = ALL IN fi"),
    (2, TightAggressive, "tight-aggressive: Chen ranges, position, c-bets"),
    (3, LooseAggressive, "loose-aggressive: bluffs, barrels, hero calls"),
    (4, EquityOracle,    "Monte Carlo equity vs pot odds, mixed sizing"),
    (5, NitPushFold,     "premium-only nit with short-stack push/fold"),
    (6, AdaptiveExploiter, "opponent modeling: exploits shove/fold rates"),
]


def run_sims(n=100, seed=42, verbose=True):
    wins = Counter()
    placements = defaultdict(list)
    total_hands = 0
    t0 = time.time()
    for i in range(n):
        rng = random.Random(seed + i * 1_000_003)
        players = [
            (pid, cls(pid, random.Random(rng.getrandbits(64))))
            for pid, cls, _ in ROSTER
        ]
        rng.shuffle(players)  # random seating every tournament
        champ, finish, hands = Tournament(players, rng).run()
        wins[champ] += 1
        total_hands += hands
        for place_from_last, pid in enumerate(reversed(finish)):
            placements[pid].append(place_from_last + 1)  # 1 = champion
        if verbose and (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{n} tournaments done ({time.time() - t0:.1f}s)")
    return wins, placements, total_hands


def report(wins, placements, total_hands, n):
    names = {pid: cls.name for pid, cls, _ in ROSTER}
    blurbs = {pid: blurb for pid, _, blurb in ROSTER}
    lines = []
    lines.append("")
    lines.append("=" * 74)
    lines.append(f"  WINNER WINNER CHICKEN DINNER — champions of {n} tournaments")
    lines.append(f"  (6 players, 1500 chips each, escalating blinds, "
                 f"avg {total_hands / n:.0f} hands/tourney)")
    lines.append("=" * 74)
    max_wins = max(wins.values()) if wins else 1
    for pid, _, _ in ROSTER:
        w = wins.get(pid, 0)
        bar = "█" * max(1, round(w * 50 / max_wins)) if w else ""
        label = f"P{pid} {names[pid]}"
        lines.append(f"  {label:<23}|{bar:<51}| {w:3d}  ({w * 100 / n:.0f}%)")
    lines.append("-" * 74)
    lines.append("  avg finishing place (1 = champion, 6 = first out):")
    for pid, _, _ in ROSTER:
        pl = placements.get(pid, [])
        avg = sum(pl) / len(pl) if pl else float("nan")
        firsts_out = sum(1 for p in pl if p == 6)
        lines.append(
            f"    P{pid} {names[pid]:<19} avg place {avg:.2f}   "
            f"busted first {firsts_out:3d}x   [{blurbs[pid]}]"
        )
    lines.append("=" * 74)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-n", type=int, default=100, help="number of tournaments")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    wins, placements, total_hands = run_sims(args.n, args.seed)
    print(report(wins, placements, total_hands, args.n))


if __name__ == "__main__":
    main()
