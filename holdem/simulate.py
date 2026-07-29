"""Run 100 six-handed Hold'em sit-and-go tournaments and report who keeps
taking down the winner-winner-chicken-dinner.

Usage:  python3 -m holdem.simulate [n_sims] [master_seed]
"""

import json
import random
import sys
from collections import Counter
from pathlib import Path

from .engine import Tournament
from .strategies import lineup


def run_sims(n_sims=100, master_seed=42, start_stack=1000):
    winners = []
    placements = {}   # name -> list of finish positions (1 = champion)
    names = None
    for i in range(n_sims):
        rng = random.Random(master_seed * 100_000 + i)
        entries = lineup(lambda: random.Random(rng.randrange(1 << 30)))
        if names is None:
            names = [name for name, _ in entries]
        t = Tournament(entries, rng, start_stack=start_stack)
        champ = t.run()
        winners.append(champ.name)
        pid_to_name = {p.pid: p.name for p in t.players}
        for pos, pid in enumerate(reversed(t.finish_order), start=1):
            placements.setdefault(pid_to_name[pid], []).append(pos)
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"(last champion: {champ.name})")
    return names, winners, placements


def ascii_histogram(names, counts, total):
    width = 50
    peak = max(counts.values()) if counts else 1
    lines = []
    lines.append("")
    lines.append("WINNER WINNER CHICKEN DINNER — tournament wins out of "
                 f"{total}")
    lines.append("=" * 74)
    for i, name in enumerate(names, start=1):
        n = counts.get(name, 0)
        bar = "█" * max(1 if n else 0, round(n / peak * width))
        tag = "  <- the ALL-IN goblin" if i == 1 else ""
        lines.append(f"P{i} {name:<14} | {bar:<{width}} {n:>3}{tag}")
    lines.append("=" * 74)
    return "\n".join(lines)


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(f"Dealing {n_sims} six-handed sit-and-go tournaments "
          f"(seed {seed}, 1000 chips each, blinds 10/20 doubling every 8 hands)")
    names, winners, placements = run_sims(n_sims, seed)
    counts = Counter(winners)

    print(ascii_histogram(names, counts, n_sims))
    print()
    print(f"{'seat':<5}{'player':<16}{'wins':>5}{'win %':>8}{'avg finish':>12}")
    print("-" * 46)
    for i, name in enumerate(names, start=1):
        pl = placements.get(name, [])
        avg = sum(pl) / len(pl) if pl else float('nan')
        print(f"P{i:<4}{name:<16}{counts.get(name, 0):>5}"
              f"{counts.get(name, 0) / n_sims:>8.0%}{avg:>12.2f}")

    out_dir = Path(__file__).resolve().parent / "results"
    out_dir.mkdir(exist_ok=True)
    payload = {
        "n_sims": n_sims,
        "seed": seed,
        "players": [
            {"seat": f"P{i}", "name": name,
             "wins": counts.get(name, 0),
             "avg_finish": sum(placements[name]) / len(placements[name])}
            for i, name in enumerate(names, start=1)
        ],
        "winners_sequence": winners,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))
    print(f"\nSaved {out_dir / 'results.json'}")

    try:
        from .chart import render_chart
        png = render_chart(payload, out_dir / "winners.png")
        print(f"Saved {png}")
    except ImportError:
        print("matplotlib not available - skipped PNG chart")


if __name__ == "__main__":
    main()
