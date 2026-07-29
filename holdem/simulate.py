"""Run N Hold'em freeze-out tournaments and histogram the champions.

Usage:  python3 -m holdem.simulate [--sims 100] [--seed 42]
"""

import argparse
import time
from collections import Counter, defaultdict

from .engine import Tournament
from .strategies import build_lineup

BAR = "█"


def run_sims(n_sims=100, base_seed=42, start_stack=1000):
    winners = Counter()
    finishes = defaultdict(list)  # player number -> list of finish places
    hands_hist = []
    lineup_names = [s.name for s in build_lineup(0)]

    t0 = time.time()
    for i in range(n_sims):
        seed = base_seed + i
        strategies = build_lineup(seed)
        tourney = Tournament(strategies, start_stack=start_stack, seed=seed)
        result = tourney.run()
        winners[result["winner_seat"]] += 1
        hands_hist.append(result["hands_played"])
        n = len(strategies)
        for place_from_last, seat in enumerate(result["finish_order"]):
            finishes[seat].append(n - place_from_last)  # 1 = champion
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done "
                  f"({time.time() - t0:.1f}s)")
    elapsed = time.time() - t0
    return winners, finishes, hands_hist, lineup_names, elapsed


def histogram_lines(winners, lineup_names, n_sims):
    lines = []
    max_wins = max(winners.values()) if winners else 1
    scale = 50 / max(1, max_wins)
    for seat, name in enumerate(lineup_names):
        w = winners.get(seat, 0)
        bar = BAR * max(1 if w else 0, round(w * scale))
        label = f"Player {seat + 1}  {name:<22}"
        lines.append(f"{label} {bar} {w}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=1000)
    ap.add_argument("--out", default=None,
                    help="optional path to write a Markdown report")
    args = ap.parse_args()

    print(f"Running {args.sims} six-handed freeze-out tournaments "
          f"(equal {args.stack}-chip stacks, escalating blinds)...")
    winners, finishes, hands_hist, names, elapsed = run_sims(
        args.sims, args.seed, args.stack)

    print()
    title = "WINNER WINNER CHICKEN DINNER HISTOGRAM (tournaments won)"
    print(title)
    print("=" * len(title))
    hist = histogram_lines(winners, names, args.sims)
    for line in hist:
        print(line)
    print()

    print("Average finishing place (1 = champion, 6 = first bust):")
    avg_rows = []
    for seat, name in enumerate(names):
        fl = finishes.get(seat, [])
        avg = sum(fl) / len(fl) if fl else float("nan")
        firsts_out = sum(1 for f in fl if f == len(names))
        avg_rows.append((seat, name, avg, firsts_out))
        print(f"  Player {seat + 1}  {name:<22} avg place {avg:.2f}   "
              f"first out of the room: {firsts_out}x")
    print(f"\nAvg hands per tournament: "
          f"{sum(hands_hist) / len(hands_hist):.1f}   "
          f"(total wall time {elapsed:.1f}s)")

    leeroy_places = Counter(finishes.get(0, []))
    print("\nLeeroy (Player 1, the `if my_turn then bet = All in fi` bot) "
          "finish distribution:")
    for place in range(1, len(names) + 1):
        c = leeroy_places.get(place, 0)
        print(f"  place {place}: {BAR * c if c else ''} {c}")

    if args.out:
        write_report(args.out, args, winners, finishes, hands_hist, names,
                     hist, avg_rows, leeroy_places)
        print(f"\nReport written to {args.out}")


def write_report(path, args, winners, finishes, hands_hist, names, hist,
                 avg_rows, leeroy_places):
    n = args.sims
    lines = [
        "# Hold'em death-match: 100-tournament results",
        "",
        f"{n} six-handed freeze-out tournaments. Everyone starts with "
        f"{args.stack} chips, blinds start 5/10 and double every 20 hands. "
        "Players 2-6 run elaborate strategies; Player 1 runs, in its "
        "entirety: `if my_turn then bet = All in fi`. No bot knows any "
        "other bot's strategy - they only see the public action stream.",
        "",
        "## Winner histogram (last player on the table)",
        "",
        "```text",
        *hist,
        "```",
        "",
        "## Average finishing place (1 = champion, 6 = first bust)",
        "",
        "| Player | Strategy | Avg place | Wins | First-out count |",
        "|---|---|---|---|---|",
    ]
    for seat, name, avg, firsts_out in avg_rows:
        lines.append(f"| {seat + 1} | {name} | {avg:.2f} | "
                     f"{winners.get(seat, 0)} | {firsts_out} |")
    lines += [
        "",
        "## Player 1 (Leeroy) finish distribution",
        "",
        "```text",
    ]
    for place in range(1, len(names) + 1):
        c = leeroy_places.get(place, 0)
        lines.append(f"place {place}: {BAR * c if c else ''} {c}")
    lines += [
        "```",
        "",
        f"Average tournament length: "
        f"{sum(hands_hist) / len(hands_hist):.1f} hands. "
        f"Base seed {args.seed} - rerun `python3 -m holdem.simulate` to "
        "reproduce these exact numbers.",
        "",
    ]
    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
