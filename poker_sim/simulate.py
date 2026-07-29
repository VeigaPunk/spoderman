"""
Run N full 6-max tournaments and histogram the winner-winner-chicken-dinners.

Usage:
    python -m poker_sim.simulate --sims 100 --seed 7
"""

import argparse
import random
import time
from collections import Counter, defaultdict

from .engine import Tournament
from .strategies import ROSTER


def run_sims(n_sims, seed, start_stack=200):
    master = random.Random(seed)
    wins = Counter()
    places = defaultdict(list)
    hands_played = []
    names = {pid: cls.name for pid, cls in ROSTER}

    for i in range(n_sims):
        entries = [(pid, cls(random.Random(master.getrandbits(64))))
                   for pid, cls in ROSTER]
        t = Tournament(
            entries,
            start_stack=start_stack,
            rng=random.Random(master.getrandbits(64)),
            first_button=i,  # rotate the starting button for seat fairness
        )
        result = t.run()
        wins[result["winner"]] += 1
        for pid, place in result["places"].items():
            places[pid].append(place)
        hands_played.append(result["hands"])

    return names, wins, places, hands_played


def bar(count, total, width=50):
    n = round(width * count / total) if total else 0
    return "█" * n if count == 0 or n > 0 else "▏"


def render(names, wins, places, hands_played, n_sims, seed, elapsed):
    lines = []
    add = lines.append
    add(f"6-MAX NL HOLD'EM — {n_sims} tournaments, seed {seed}, "
        f"{sum(hands_played)} hands total "
        f"(avg {sum(hands_played) / len(hands_played):.1f}/tourney, "
        f"{elapsed:.1f}s)")
    add("")
    add("WINNER WINNER CHICKEN DINNER HISTOGRAM")
    add("(tournament wins = last player with all the chips)")
    add("")
    order = sorted(names, key=lambda pid: (-wins[pid], pid))
    for pid in order:
        label = f"P{pid} {names[pid]}"
        add(f"  {label:<21}|{bar(wins[pid], n_sims)} {wins[pid]}")
    add("")
    add("  " + "-" * 60)
    add(f"  {'player':<21}{'wins':>5}{'win %':>8}{'avg finish':>12}"
        f"{'busted 1st':>12}")
    for pid in order:
        ps = places[pid]
        first_out = sum(1 for p in ps if p == len(names))
        add(f"  P{pid} {names[pid]:<17}{wins[pid]:>5}"
            f"{100 * wins[pid] / n_sims:>7.1f}%"
            f"{sum(ps) / len(ps):>12.2f}{first_out:>12}")
    add("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--stack", type=int, default=200)
    args = ap.parse_args()

    t0 = time.time()
    names, wins, places, hands_played = run_sims(args.sims, args.seed, args.stack)
    report = render(names, wins, places, hands_played, args.sims, args.seed,
                    time.time() - t0)
    print(report)
    return names, wins, places, hands_played


if __name__ == "__main__":
    main()
