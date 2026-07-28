# Hold'em Bot Battle — 5 elaborate strategies vs `if my_turn then bet = ALL IN fi`

A self-contained Texas Hold'em tournament simulator (`holdem_sim.py`, stdlib only):
full 7-card hand evaluation, blinds with escalation, betting rounds, all-ins and
side pots, winner-take-all tournaments. No bot knows any other bot's strategy.

## The lineup

| Seat | Player | Strategy |
|------|--------|----------|
| 1 | **LEEROY (ALL-IN)** | `if my_turn: bet = ALL_IN fi` — the whole thing |
| 2 | **The Professor (TAG)** | Chen-formula positional ranges, Monte Carlo equity vs pot odds, 2/3-pot value bets, semi-bluffs, equity-based shove calling |
| 3 | **Maniac Picasso (LAG)** | Wide positional opens, steals, c-bets, randomized bluff raises, light shove calls |
| 4 | **The Rock (Nit)** | Premiums only, bets them hard, never bluffs |
| 5 | **Pot-Odds Oracle (Math)** | Pure EV: Monte Carlo equity on every decision, calls exactly when equity beats pot odds, zero bluffs |
| 6 | **The Profiler (Adaptive)** | Tracks every opponent's raise frequency; snap-calls maniacs with real equity, respects the tight players |

## Run it

```
python3 holdem_sim.py 100
```

100 tournaments, 6 players, 1,000 chips each, blinds 10/20 escalating ×1.5 every
12 hands, until one player holds everything.

## Results (100 tournaments, seed 31337)

```
LEEROY (ALL-IN)            █████████████████████████ 12
The Professor (TAG)        ████████████████████████████████████████ 19
Maniac Picasso (LAG)       ██████████████████████████████████████████████████ 24
The Rock (Nit)             ███████████████████████ 11
Pot-Odds Oracle (Math)     █████████████████████████████ 14
The Profiler (Adaptive)    ██████████████████████████████████████████ 20
```

| Player | Wins | Avg finish | Busted first |
|--------|-----:|-----------:|-------------:|
| Maniac Picasso (LAG) | 24 | 3.72 | 16 |
| The Profiler (Adaptive) | 20 | 3.31 | 14 |
| The Professor (TAG) | 19 | 3.51 | 11 |
| Pot-Odds Oracle (Math) | 14 | 3.45 | 11 |
| **LEEROY (ALL-IN)** | **12** | **4.82** | **47** |
| The Rock (Nit) | 11 | 2.19 | 1 |

## Takeaways

- **LEEROY still wins 12%** — a one-line strategy stealing tournaments off five
  engineered opponents is exactly the variance monster all-in poker is. Every
  hand he either takes the blinds uncontested or flips his tournament life; run
  hot for 20 minutes and the trophy is yours.
- **But he busts first in 47% of tournaments** and averages a 4.82/6 finish —
  the shove-everything tax is savage the moment anyone wakes up with a premium
  and an equity calculator.
- **Aggression with a brain wins the most**: the LAG's pressure (24 wins) and
  the Profiler's opponent-modeling (20) top the table.
- **Survival ≠ winning**: The Rock almost never busts first (1/100) and has the
  best average finish (2.19), yet wins the fewest tournaments — folding your way
  to the final two doesn't leave you chips to win with.

`results.html` is a rendered histogram + standings page of the same run.
