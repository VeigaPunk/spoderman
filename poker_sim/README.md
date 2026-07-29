# poker_sim — 6-max Texas Hold'em tournament simulator

100 independent winner-take-all tournaments. Six players, identical starting
stacks (1000 chips), blinds 10/20 doubling every 20 hands, full no-limit
rules: side pots, split pots, uncalled-bet refunds, heads-up blind order.
No player can observe another player's strategy or hole cards — strategies
only receive the public observation dict the engine builds for each decision.

## The lineup

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **All-In Andy** | `if my_turn then bet = All in fi` — that's the whole algorithm |
| P2 | **Athena (TAG)** | Tight-aggressive: Chen-formula preflop ranges, Monte Carlo equity vs pot odds with a safety margin postflop |
| P3 | **Loki (LAG)** | Loose-aggressive: wide randomized opens, blind steals, bluffs and semi-bluff raises with live equity |
| P4 | **Granite (Nit)** | Premium-only: folds almost everything, stacks off with the top of the deck, short-stack shove mode |
| P5 | **Bayes (Odds)** | Pure EV machine: every action is Monte Carlo equity vs pot odds / fair pot share |
| P6 | **Mirror (Adaptive)** | Profiles opponents from observed actions (all-in %, VPIP, PFR) and switches gears — snap-calls detected maniacs on raw equity, steals from rocks |

## Run it

```bash
python3 run_sims.py --sims 100 --seed 42 --jobs 4
```

Prints the winner histogram, first-bust histogram and average finishing
positions; writes raw per-tournament data to `results.json`.

## Results (seed 42, 100 tournaments)

```
🏆 WINNER WINNER CHICKEN DINNER — 100 tournaments (avg 67 hands each)

  P1 All-In Andy        ████████████                                         6 (6%)
  P2 Athena (TAG)       ██████████████████████████████████████              19 (19%)
  P3 Loki (LAG)         ██████████████████████████████████████████          21 (21%)
  P4 Granite (Nit)      ████████████████                                     8 (8%)
  P5 Bayes (Odds)       ██████████████████████████████████████████          21 (21%)
  P6 Mirror (Adaptive)  ██████████████████████████████████████████████████  25 (25%)

💀 First player eliminated:

  P1 All-In Andy        ██████████████████████████████████████████████████  57 (57%)
  P2 Athena (TAG)       ████████████████                                    18 (18%)
  P3 Loki (LAG)         ██████████                                          11 (11%)
  P4 Granite (Nit)                                                           0 (0%)
  P5 Bayes (Odds)       ████                                                 5 (5%)
  P6 Mirror (Adaptive)  ████████                                             9 (9%)

📊 Average finishing position (1 = champion, 6 = first bust):

  P1 All-In Andy        5.00     P4 Granite (Nit)      2.46
  P2 Athena (TAG)       3.52     P5 Bayes (Odds)       3.25
  P3 Loki (LAG)         3.52     P6 Mirror (Adaptive)  3.25
```

The maniac busts first in 57% of tournaments and still steals 6% of titles by
winning enough coin flips in a row — variance is undefeated. The adaptive
profiler, whose whole gimmick is detecting exactly this kind of player, takes
the most crowns. The nit never busts first but rarely wins: surviving is not
the same as winning.

## Engine notes / simplifications

- One deviation from casino rules: an undersized all-in raise re-opens the
  action for players who already acted (real rules only let them call).
- Odd chips in split pots go to the first winner left of the button.
- Blinds cap at 4000/8000, guaranteeing tournaments terminate.
