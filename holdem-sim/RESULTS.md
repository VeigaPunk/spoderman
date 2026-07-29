# Official Results — 100 Tournaments (seed 42)

Six players, 1000 chips each, blinds 10/20 doubling every 20 hands,
winner-take-all. Nobody knew anybody's algorithm.

```
==============================================================================
  WINNER WINNER CHICKEN DINNER HISTOGRAM (100 tournaments, winner-take-all)
==============================================================================
P1 Suflair-GPT (All-In Bot)        | █████████████ 13
P2 Doyle (Tight-Aggressive)        | ███████████ 11
P3 Gus (Loose-Aggressive)          | ██████████████████████████████████████ 38
P4 The Rock (Ultra-Tight Trapper)  | ██ 2
P5 Ada (Monte Carlo Mathematician) | ██████████████████ 18
P6 Sun-Tzu (Adaptive Exploiter)    | ██████████████████ 18
------------------------------------------------------------------------------
Player                             | Wins |  Win % | avg finish
P1 Suflair-GPT (All-In Bot)        |   13 |   13% | 5.05
P2 Doyle (Tight-Aggressive)        |   11 |   11% | 2.76
P3 Gus (Loose-Aggressive)          |   38 |   38% | 2.79
P4 The Rock (Ultra-Tight Trapper)  |    2 |    2% | 3.00
P5 Ada (Monte Carlo Mathematician) |   18 |   18% | 3.84
P6 Sun-Tzu (Adaptive Exploiter)    |   18 |   18% | 3.56
==============================================================================
```

## Post-game analysis (the roast)

- **Suflair-GPT** shoved every single hand of every single tournament and
  finished with a **5.05 average** — statistically, its natural habitat is
  the rail. Its 13 wins are pure variance: sometimes the deck simply
  refuses to give anyone a calling hand before the blinds eat the table.
  A fair share of the field would be ~17%; the all-in bot underperforms
  even a coin-flip baseline while playing 100% of hands. Humiliation:
  delivered, with confidence intervals.
- **Gus (LAG)** is the champion at **38%**. Relentless pressure prints
  chips in a 6-max winner-take-all format — he steals constantly, gets
  paid when he hits, and (unlike a certain soufflé) actually folds when
  he's beat.
- **Ada** and **Sun-Tzu** tied at **18%** — the mathematician grinds pot
  odds, the exploiter identified the shove-monkey in seat 1 within a few
  hands and called it off light ever after.
- **Doyle** was the most consistent player at the table (best average
  finish, 2.76) but too disciplined to hoard *all* the chips very often.
- **The Rock** proves you can't blind out your way to glory: great at
  surviving (3.00 avg), nearly incapable of closing (2 wins).

Reproduce with `python3 simulate.py -n 100 --seed 42`.
