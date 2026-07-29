# Texas Hold'em: 5 elaborate strategies vs the all-in bot

A self-contained no-limit Texas Hold'em tournament simulator. Six players,
equal starting stacks (1000 chips), escalating blinds (doubling every 12
hands), full betting rounds, side pots, eliminations — play continues until
one player holds every chip. No strategy knows any other strategy's
algorithm; they only observe public actions at the table.

## The lineup

| Seat | Strategy | Style |
|------|----------|-------|
| P1 | **Suflair-GPT** | `if my_turn then bet = All in fi` — the entire algorithm |
| P2 | **The Rock** | Tight-aggressive: Chen-formula preflop ranges by position, only plays real equity postflop, never bluffs |
| P3 | **Blaze the LAG** | Loose-aggressive: wide opens, relentless c-bets, semi-bluffs, random pure bluffs, can still fold to heavy action |
| P4 | **The Professor** | Position & board-texture play: tight early / wide on the button, slowplays monsters on dry boards, shuts down on wet ones |
| P5 | **The Mathematician** | Pure EV machine: Monte-Carlo equity vs pot odds, bet sizing proportional to edge, zero bluffs |
| P6 | **The Shark** | Adaptive opponent modeler: tracks observed shove/fold frequencies and exploits them — snap-calls chronic shovers with decent equity, steals from tight tables |

## Run it

```bash
python3 holdem_sim.py            # 100 tournaments, seed 42 (the canonical run)
python3 holdem_sim.py 500 123    # custom sim count and seed
python3 plot_results.py          # renders winners_histogram.png (needs matplotlib)
```

## Results (100 tournaments, seed 42)

```
P1 Suflair-GPT       | ███████████████                           11  (11%)
P2 The Rock          | ████████████████████████████████████████  29  (29%)
P3 Blaze the LAG     | ██████████████████████                    16  (16%)
P4 The Professor     | ██████████████                            10  (10%)
P5 The Mathematician | █████████████████                         12  (12%)
P6 The Shark         | ██████████████████████████████            22  (22%)

Average finishing place (1 = champion, 6 = first bust) and times busting first:
P1 Suflair-GPT       | avg place 4.80 | first out  53x
P2 The Rock          | avg place 2.81 | first out  10x
P3 Blaze the LAG     | avg place 3.50 | first out   8x
P4 The Professor     | avg place 3.01 | first out   5x
P5 The Mathematician | avg place 3.64 | first out  17x
P6 The Shark         | avg place 3.24 | first out   7x
```

The all-in bot busts first in over half of all tournaments and averages a
4.80 finish — but variance is undefeated, so it still steals 11 chicken
dinners by winning enough coin flips in a row before anyone picks up a real
hand.
