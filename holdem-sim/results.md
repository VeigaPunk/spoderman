# Hold'em Simulation Results — 100 tournaments

Config: 6 players, 1000 starting chips each, blinds 10/20 doubling every 12
hands, winner-take-all sit-n-go format. Deterministic seed `42`
(reproduce with `python3 holdem_sim.py --sims 100 --seed 42`).

No bot knows any other bot's strategy — all reads come from public actions only.

## Winner histogram (winner winner chicken dinner count)

```
P1 Suflair-GPT [all-in]    |██████████████████████████████████████████        |  22  (22%)
P2 TAG-Shark               |███████████████████                               |  10  (10%)
P3 MonteCarlo-Oracle       |██████████████████████████████████████████████████|  26  (26%)
P4 LAG-Hurricane           |██████████████████████████████████████████████    |  24  (24%)
P5 Granite-Nit             |████                                              |   2  (2%)
P6 Adaptive-Vulture        |███████████████████████████████                   |  16  (16%)
```

## Finishing-position distribution

```
player                         1st   2nd   3rd   4th   5th   6th   avg
P1 Suflair-GPT [all-in]         22     0     1     3    10    64  4.71
P2 TAG-Shark                    10    39    17    20     7     7  2.96
P3 MonteCarlo-Oracle            26     8     8    16    29    13  3.53
P4 LAG-Hurricane                24     9    14    14    34     5  3.40
P5 Granite-Nit                   2    26    42    23     7     0  3.07
P6 Adaptive-Vulture             16    18    18    24    13    11  3.33
```

Total hands dealt: 6424 (avg 64.2 per tournament).

## The humiliation report

Suflair-GPT finished **dead last in 64 of 100 tournaments** — by far the most
frequent first bust-out at the table — and posted the **worst average finish
(4.71)** of all six players. It never once finished second: it either owns the
chicken dinner or gets carried out of the casino in the first orbit. In any
format that pays more than one place, this strategy is a chip-shredding
catastrophe.

The asterisk science demands: in a **winner-take-all** format, shoving every
hand converts pure variance into equity. When the maniac wins one early
coin-flip it becomes a table-bullying chip leader, which is why it still
banked 22% of the trophies — above the fair-share 16.7%, but well behind
MonteCarlo-Oracle (26%) and LAG-Hurricane (24%). Second place is worth
nothing here, and Suflair-GPT's 0 runner-up finishes show it understood the
assignment in the only degenerate way it knows how.
