# 🍗 Winner Winner Chicken Dinner — 100-sim results

`python -m poker_sim.simulate --sims 100 --seed 7`

100 six-max no-limit Hold'em tournaments, 20,679 hands total (avg 206.8 per
tourney, 85.5s wall clock). Everyone starts with 200 chips (100 bb), blinds
escalate every 30 hands, last player holding all the chips wins the sim.

## Winner histogram

```
P4 LagLoki           |████████████████████ 40
P6 Sherlock          |██████████████ 27
P5 CaseyCalculator   |██████████ 19
P1 AllInAnnie        |██ 5
P3 TagTitan          |██ 5
P2 TheRock           |██ 4
```

## Full standings

| Player | Strategy | Wins | Win % | Avg finish | Busted first |
|---|---|---:|---:|---:|---:|
| P4 | LagLoki (loose-aggressive) | 40 | 40% | 2.93 | 4 |
| P6 | Sherlock (adaptive profiler) | 27 | 27% | 3.27 | 22 |
| P5 | CaseyCalculator (Monte Carlo equity) | 19 | 19% | 3.69 | 11 |
| P1 | AllInAnnie (`if my_turn then bet = All in fi`) | 5 | 5% | 5.16 | 61 |
| P3 | TagTitan (tight-aggressive) | 5 | 5% | 3.14 | 1 |
| P2 | TheRock (ultra-tight nit) | 4 | 4% | 2.81 | 1 |

## Post-game commentary

- **AllInAnnie's one-liner beats two PhD theses.** The shove-bot (5 wins) ties
  TagTitan and edges out TheRock. Open-shoving 100 bb every hand steals blinds
  relentlessly, and when she gets called she still has two live cards — a
  coin-flip won five entire tournaments. She also busted first in 61/100 sims,
  the price of playing 72o for stacks.
- **Aggression is king.** LagLoki's relentless pressure (40 wins) beats every
  careful plan. In a table full of players waiting for good cards, the one who
  keeps betting takes the chips.
- **Sherlock's profiling pays.** By tracking shove rates from public actions
  alone, Sherlock deduces within a few hands that Annie shoves any two cards,
  and starts calling her off with hands as weak as A9 — 27 wins and the most
  common Annie-executioner.
- **Tightness is a slow leak.** TheRock and TagTitan have great average
  finishes (2.81, 3.14) and almost never bust first — they fold their way onto
  the podium, then arrive at heads-up too short-stacked to close. Surviving is
  not winning.
