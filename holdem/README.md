# Hold'em death-match 🐔🍗

Six bots, one table, 100 freeze-out tournaments, equal 1000-chip stacks,
blinds 5/10 doubling every 20 hands. Last player on the table gets the
chicken dinner.

No bot knows any other bot's algorithm. They see exactly what a human at the
table would see: their own hole cards, the board, stacks, and the public
action stream.

## The lineup

| Seat | Bot | Strategy |
|---|---|---|
| 1 | **Leeroy (ALL-IN)** | The entire spec: `if my_turn then bet = All in fi` |
| 2 | **Doyle (TAG)** | Tight-aggressive: Chen-formula ranges by position, disciplined shove-calling, c-bets, pot-odds draws, push/fold under 10bb |
| 3 | **Maverick (LAG)** | Loose-aggressive: wide opens, late-position steals, randomized 3-bet bluffs with ace blockers, semi-bluff raises, floats, river barrels |
| 4 | **The Monk (NIT)** | Ultra-tight: premiums only, calls shoves with QQ+/AK, never bluffs, waits for the maniacs to incinerate each other |
| 5 | **The Calculator (EQ)** | Pure math: fresh Monte Carlo equity simulation at every decision, compared against pot odds — no psychology, no memory |
| 6 | **The Profiler (ADAPT)** | Opponent modelling on TAG fundamentals: builds statistical profiles from observed actions, detects maniacs (calls their shoves with any equity edge vs. a random hand) and rocks (steals their blinds) |

## Run it

```bash
python3 -m holdem.simulate --sims 100 --seed 42 --out holdem/RESULTS.md
```

Dependency-free (stdlib only), deterministic per seed, ~12 seconds for 100
tournaments. Full results in [RESULTS.md](RESULTS.md).

## Engine

`engine.py` is a complete no-limit Hold'em tournament engine: escalating
blinds, heads-up button rules, min-raise enforcement, all-ins, side pots,
split pots, uncalled-bet refunds, and a chip-conservation assertion after
every hand. `strategies.py` holds the six bots behind a common
observe/act interface.

Known simplifications: an undersized all-in raise re-opens betting (real
rules cap this), and the hand-strength helpers are deliberately heuristic —
bots misread boards occasionally, just like people.

## Spoiler

Leeroy went out first in 64 of 100 tournaments and averaged 5.13th place
out of 6. Shoving blind every hand is, it turns out, not a strategy — it's
a donation schedule with extra steps.
