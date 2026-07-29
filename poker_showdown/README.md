# Poker Showdown: 5 elaborate strategies vs. Suflair-GPT

A full no-limit Texas Hold'em **tournament** simulator: 6 players, equal
starting stacks, escalating blinds, side pots, eliminations — last player
holding all the chips gets the chicken dinner.

## The lineup

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **Suflair-GPT** | `if my_turn then bet = All in fi` — that's it, that's the whole algorithm |
| P2 | The Professor | Tight-aggressive: Chen-formula position ranges, Monte Carlo equity, pot-odds discipline, 2/3-pot value bets, semi-bluffs |
| P3 | La Cobra | Loose-aggressive: wide opens in position, light 3-bets, relentless c-bets, double barrels, spite bluff-raises |
| P4 | The Rock | Ultra-nit: premiums only, cheap set-mining, zero bluffs, stacks off only with near-nut equity |
| P5 | The Profiler | Exploitative: learns every opponent's VPIP / aggression / shove frequency from the public action log and attacks the leaks |
| P6 | The Actuary | Risk-managed small-ball with a Nash-ish push/fold gear and a survival premium on stack-threatening calls |

No player can see another player's cards or code — the Profiler has to
*discover* the maniac from observed actions alone.

## Run it

```bash
python3 tests.py            # evaluator + side-pot + chip-conservation tests
python3 simulate.py --sims 100 --seed 42
```

Deterministic per seed. Outputs an ASCII histogram, `results/results.json`,
`results/results.txt`, and (if matplotlib is installed)
`results/winner_histogram.png`.

## Official results (100 tournaments, seed 42)

```
P1 Suflair-GPT [ALL-IN]    | █████████████████████ 13 (13%)
P2 The Professor [TAG]     | ████████████████████████ 15 (15%)
P3 La Cobra [LAG]          | ███████████████████ 12 (12%)
P4 The Rock [NIT]          | █████████████████████ 13 (13%)
P5 The Profiler [EXPLOIT]  | ███████████████████████████████████ 22 (22%)
P6 The Actuary [RISK-MGMT] | ████████████████████████████████████████ 25 (25%)
```

| | avg finish (1 = win) | busted first |
|---|---|---|
| Suflair-GPT | **4.64** (worst at the table) | **56 / 100** |
| The Rock | 2.26 (best) | 0 / 100 |

The all-in bot wins below its fair share (13% < 16.7%) despite maximum
variance, finishes dead last on average, and is the first player eliminated
in the **majority** of tournaments. When it survives, it's pure coin-flip
luck; when anyone wakes up with a real hand, it donates its stack.
Humiliation: delivered. 🍗

## Layout

- `holdem/evaluator.py` — fast 7-card hand evaluator (single-int scores)
- `holdem/engine.py` — betting rounds, min-raise rules, uncalled-bet refunds, side pots, blind escalation, eliminations
- `holdem/strategies.py` — the six players
- `simulate.py` — tournament runner + histogram
- `tests.py` — sanity tests
