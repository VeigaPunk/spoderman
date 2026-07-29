"""Run N freezeout tournaments and print the winner histogram.

    python -m holdem.simulate --sims 100

Every tournament is seeded independently, so the run is fully reproducible
and identical whether it is executed on one core or many.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

from .engine import play_tournament
from .strategies import ROSTER

BAR = "█"


def _run_one(args):
    seed, start_stack, hands_per_level = args
    res = play_tournament(list(ROSTER), seed=seed, start_stack=start_stack,
                          hands_per_level=hands_per_level)
    return {
        "seed": seed,
        "winner": res.winner,
        "order": res.finish_order,
        "hands": res.hands,
        "knockouts": res.knockouts,
        "peak": res.peak_stack,
        "survived": res.hands_survived,
    }


def run(sims=100, seed0=1000, start_stack=10000, hands_per_level=20,
        workers=None, progress=True):
    jobs = [(seed0 + i, start_stack, hands_per_level) for i in range(sims)]
    results = []
    t0 = time.time()
    if workers is None:
        workers = max(1, (os.cpu_count() or 2))
    if workers > 1:
        import concurrent.futures as cf
        with cf.ProcessPoolExecutor(max_workers=workers) as pool:
            for i, r in enumerate(pool.map(_run_one, jobs, chunksize=1), 1):
                results.append(r)
                if progress and (i % max(1, sims // 20) == 0 or i == sims):
                    done = time.time() - t0
                    print(f"\r  simulating {i}/{sims}  ({done:5.1f}s)", end="",
                          file=sys.stderr, flush=True)
    else:
        for i, j in enumerate(jobs, 1):
            results.append(_run_one(j))
            if progress and (i % max(1, sims // 20) == 0 or i == sims):
                print(f"\r  simulating {i}/{sims}", end="", file=sys.stderr, flush=True)
    if progress:
        print(file=sys.stderr)
    results.sort(key=lambda r: r["seed"])
    return results, time.time() - t0


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def _wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - r) / d, (c + r) / d)


def report(results, width=46, out=print):
    n = len(results)
    names = [f"P{i + 1} {c.name}" for i, c in enumerate(ROSTER)]
    wins = Counter(r["winner"] for r in results)
    seats = range(len(ROSTER))

    finishes = {s: [] for s in seats}
    for r in results:
        for place, seat in enumerate(r["order"], 1):
            finishes[seat].append(place)
    ko = {s: sum(r["knockouts"][s] if isinstance(r["knockouts"], dict)
                 else r["knockouts"][str(s)] for r in results) for s in seats}
    peak = {s: max(r["peak"].get(s, r["peak"].get(str(s), 0)) for r in results)
            for s in seats}
    survived = {s: sum(r["survived"].get(s, r["survived"].get(str(s), 0))
                       for r in results) / n for s in seats}

    top = max(wins.values()) if wins else 1
    out("")
    out("=" * 78)
    out(f"  WINNER HISTOGRAM  -  {n} freezeout tournaments, 6 players, "
        f"equal starting stacks")
    out("=" * 78)
    out("")
    for s in sorted(seats, key=lambda x: -wins[x]):
        w = wins[s]
        bar = BAR * max(0, round(width * w / top)) if top else ""
        lo, hi = _wilson(w, n)
        out(f"  {names[s]:<20} {w:3d}  {w / n * 100:5.1f}%  "
            f"{bar:<{width}}  [95% CI {lo * 100:4.1f}-{hi * 100:4.1f}%]")
    out("")
    out(f"  one block = {top / width:.2f} wins;  a fair 6-way split would be "
        f"{n / 6:.1f} wins (16.7%) each")
    out("")
    out("-" * 78)
    out("  FINISHING POSITIONS (1 = winner, 6 = first one out)")
    out("-" * 78)
    out(f"  {'player':<20} " + "  ".join(f"{p:>4}" for p in range(1, 7))
        + "   avg    KOs   avg hands survived")
    for s in sorted(seats, key=lambda x: sum(finishes[x]) / max(1, len(finishes[x]))):
        counts = Counter(finishes[s])
        row = "  ".join(f"{counts.get(p, 0):>4}" for p in range(1, 7))
        avg = sum(finishes[s]) / max(1, len(finishes[s]))
        out(f"  {names[s]:<20} {row}  {avg:5.2f}  {ko[s]:5d}   {survived[s]:6.1f}")
    out("")
    hands = [r["hands"] for r in results]
    out(f"  tournament length: min {min(hands)}  median "
        f"{sorted(hands)[len(hands) // 2]}  max {max(hands)}  "
        f"mean {sum(hands) / len(hands):.1f} hands")
    out("")
    return {
        "sims": n,
        "wins": {names[s]: wins[s] for s in seats},
        "win_pct": {names[s]: wins[s] / n for s in seats},
        "avg_finish": {names[s]: sum(finishes[s]) / max(1, len(finishes[s]))
                       for s in seats},
        "knockouts": {names[s]: ko[s] for s in seats},
        "peak_stack": {names[s]: peak[s] for s in seats},
        "avg_hands_survived": {names[s]: survived[s] for s in seats},
        "hands": {"min": min(hands), "max": max(hands),
                  "mean": sum(hands) / len(hands)},
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--stack", type=int, default=10000)
    ap.add_argument("--hands-per-level", type=int, default=20)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--json", type=str, default=None,
                    help="write the full result set here")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    print(f"Texas Hold'em freezeout: {a.sims} tournaments, 6 seats, "
          f"{a.stack} chips each")
    for i, cls in enumerate(ROSTER, 1):
        print(f"  P{i}  {cls.name:<16} {cls.blurb}")
    results, elapsed = run(a.sims, a.seed, a.stack, a.hands_per_level,
                           a.workers, progress=not a.quiet)
    summary = report(results)
    summary["elapsed_sec"] = round(elapsed, 1)
    summary["config"] = {"seed0": a.seed, "start_stack": a.stack,
                         "hands_per_level": a.hands_per_level}
    print(f"  {a.sims} tournaments in {elapsed:.1f}s")
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"summary": summary, "results": results}, fh, indent=1)
        print(f"  wrote {a.json}")
    return summary


if __name__ == "__main__":
    main()
