"""Run the tournament series and print the winner histogram.

    python -m holdem.simulate [--sims 100] [--chips 10000] [--seed 20260729]
"""

import argparse
import collections
import json
import os
import sys
import time

from .engine import Table
from .strategies import build_agents

BAR_WIDTH = 46
BLOCKS = "▏▎▍▌▋▊▉█"


def run_one(args):
    """Play a single freezeout. Returns a result dict (picklable)."""
    index, seed, chips, max_hands = args
    agents = build_agents()
    table = Table(agents, starting_chips=chips, seed=seed, max_hands=max_hands)
    winner = table.run()
    order = table.finish_order
    places = {pid: len(order) - i for i, pid in enumerate(order)}
    return {
        "index": index,
        "seed": seed,
        "winner": winner,
        "places": places,
        "hands": table.hand_number,
        "hands_survived": table.hands_survived,
        "hit_cap": table.hit_hand_cap,
        "names": {i + 1: a.name for i, a in enumerate(agents)},
    }


def bar(count, total, width=BAR_WIDTH):
    if total <= 0:
        return ""
    filled = count / float(total) * width
    whole = int(filled)
    remainder = filled - whole
    out = "█" * whole
    if remainder > 0.02 and whole < width:
        out += BLOCKS[min(int(remainder * 8), 7)]
    return out


def render(results, names, elapsed, sims, chips):
    wins = collections.Counter(r["winner"] for r in results)
    place_sums = collections.defaultdict(int)
    survived = collections.defaultdict(int)
    for r in results:
        for pid, place in r["places"].items():
            place_sums[pid] += place
        for pid, h in r["hands_survived"].items():
            survived[pid] += h

    ordered = sorted(names, key=lambda pid: (-wins[pid], pid))
    peak = max(wins.values()) if wins else 1

    lines = []
    add = lines.append
    add("")
    add("=" * 78)
    add("  WINNER WINNER CHICKEN DINNER  --  last player standing, %d freezeouts"
        % sims)
    add("  6 seats | %s chips each | blinds escalate every 20 hands | no rebuys"
        % f"{chips:,}")
    add("=" * 78)
    add("")
    add("  seat  strategy                              wins   share  histogram")
    add("  " + "-" * 74)
    for pid in ordered:
        n = wins.get(pid, 0)
        share = 100.0 * n / sims
        marker = "*" if pid == 1 else " "
        add("  %s#%d  %-36s %4d  %5.1f%%  %s"
            % (marker, pid, names[pid][:36], n, share, bar(n, peak)))
    add("")
    add("  * = seat 1, the 'if my_turn then bet = ALL IN fi' bot")
    add("")

    add("  average finishing place (1 = won, 6 = busted first)")
    add("  " + "-" * 74)
    for pid in sorted(names, key=lambda p: place_sums[p] / float(sims)):
        avg_place = place_sums[pid] / float(sims)
        avg_hands = survived[pid] / float(sims)
        add("   #%d  %-36s  %.2f   survived %5.1f hands"
            % (pid, names[pid][:36], avg_place, avg_hands))
    add("")

    finishes = collections.Counter()
    for r in results:
        finishes[r["places"].get(1, 6)] += 1
    add("  seat 1 (all-in bot) finishing distribution")
    add("  " + "-" * 74)
    for place in range(1, 7):
        n = finishes.get(place, 0)
        label = {1: "1st (WON)", 2: "2nd", 3: "3rd", 4: "4th",
                 5: "5th", 6: "6th (out first)"}[place]
        add("   %-16s %4d  %5.1f%%  %s"
            % (label, n, 100.0 * n / sims, bar(n, sims, 34)))
    add("")

    total_hands = sum(r["hands"] for r in results)
    capped = sum(1 for r in results if r["hit_cap"])
    add("  %d hands dealt across %d tournaments (avg %.0f per tournament)"
        % (total_hands, sims, total_hands / float(sims)))
    if capped:
        add("  %d tournament(s) hit the hand cap and were settled on chip count"
            % capped)
    add("  wall clock: %.1fs" % elapsed)
    add("=" * 78)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=100)
    parser.add_argument("--chips", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--max-hands", type=int, default=1500)
    parser.add_argument("--jobs", type=int, default=0,
                        help="worker processes; 0 = auto")
    parser.add_argument("--json", type=str, default="",
                        help="also write raw results to this path")
    opts = parser.parse_args(argv)

    jobs = opts.jobs or max(1, (os.cpu_count() or 2))
    tasks = [(i, opts.seed + i * 7919, opts.chips, opts.max_hands)
             for i in range(opts.sims)]

    start = time.time()
    if jobs > 1 and opts.sims > 1:
        import multiprocessing
        with multiprocessing.Pool(jobs) as pool:
            results = pool.map(run_one, tasks, chunksize=1)
    else:
        results = [run_one(t) for t in tasks]
    elapsed = time.time() - start

    names = results[0]["names"]
    report = render(results, names, elapsed, opts.sims, opts.chips)
    print(report)

    if opts.json:
        with open(opts.json, "w") as fh:
            json.dump({"results": results, "names": names}, fh, indent=2)
    return report


if __name__ == "__main__":
    main(sys.argv[1:])
