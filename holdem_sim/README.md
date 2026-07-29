# 🃏 Hold'em Royale: 5 Galaxy Brains vs. 1 Goblin

Six-max Texas Hold'em sit-and-go simulator. Six players, equal stacks (1000
chips), escalating blinds, full betting rounds with side pots, play until one
player owns every chip. **No player can see any other player's strategy** —
each bot only receives the public `GameView` (its own hole cards, the board,
pot, stacks, and the public action log).

## The lineup

| Seat | Strategy | Philosophy |
|------|----------|------------|
| P1 | **The Goblin** | `if my_turn then bet = All in fi` |
| P2 | **The Rock** | Tight-aggressive: Chen-formula preflop ranges by position, Monte Carlo equity vs. pot odds postflop, pays off shoves only with monsters |
| P3 | **The Maniac** | Loose-aggressive: wide opens, randomized bluffs, semi-bluffs draws, relentless pressure |
| P4 | **The Professor** | Pot-odds purist: every action is an EV inequality (Monte Carlo equity vs. price), never bluffs, never tilts |
| P5 | **The Shark** | Position player: steals from the button, c-bets heads-up, tightens out of position, push/fold when short-stacked |
| P6 | **The Profiler** | Adaptive: profiles opponents' raise frequency from the public log, tightens vs. maniacs, snaps off wild shoves with premium equity |

## Run it

```bash
python3 simulate.py            # 100 tournaments, seed 42
python3 simulate.py 500 7      # 500 tournaments, seed 7
```

Pure standard library, no dependencies.

## Results (100 tournaments, seed 42)

```
WINNER WINNER CHICKEN DINNER — last player standing, 100 tournaments
==========================================================================
P1 The Goblin (ALL-IN)                |█████████████████                         12  (12%)
P2 The Rock (tight-aggressive)        |████████████                               9  (9%)
P3 The Maniac (loose-aggressive)      |█████████████████████████████             21  (21%)
P4 The Professor (pot-odds purist)    |██████████████████████                    16  (16%)
P5 The Shark (position player)        |████████████████████████████████████████  29  (29%)
P6 The Profiler (adaptive)            |██████████████████                        13  (13%)
==========================================================================
Overall champion: P5 The Shark (position player) with 29/100 chicken dinners
```

## Post-game analysis

- **The Shark eats.** Position + blind-stealing + push/fold discipline when
  short is exactly what wins escalating-blind sit-and-gos.
- **The Goblin is not a joke — it's a below-average player.** 12% vs. the
  16.7% random baseline. Open-shoving every hand steals a lot of blinds and
  occasionally sun-runs a whole table, but five opponents who only call with
  premium equity grind it down. Chaos is a ladder, not a strategy.
- **The Rock got rocked.** Ultra-tight play bleeds out under escalating
  blinds — survival-first poker finishes second a lot and first rarely.
- **Aggression pays.** The Maniac (21%) outran three of the four "solid"
  strategies. In fast-blind formats, fold equity is real money.

## Files

- `cards.py` — deck, 7-card hand evaluator, Monte Carlo equity, Chen formula
- `engine.py` — tournament engine: blinds, betting, side pots, showdowns
- `strategies.py` — the six minds
- `simulate.py` — runs N tournaments, prints the histogram, writes `results.txt`
