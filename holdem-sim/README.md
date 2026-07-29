# Hold'em Strategy Deathmatch

Six-max No-Limit Texas Hold'em freezeout simulator. Six players, identical
starting stacks (1000 chips), blinds 10/20 doubling every 12 hands, full
betting engine (min-raises, all-ins, side pots, uncalled-bet refunds),
played until one player has every chip.

No strategy can see another strategy's code — each one only observes what a
human at the table could: its own hole cards, the board, stacks, pot sizes,
and the public action feed.

## The lineup

| Seat | Strategy | Idea |
|---|---|---|
| P1 | **SuflairGPT_AllIn** | `if my_turn: bet = ALL IN` — that's it, that's the strategy |
| P2 | **TAG_Shark** | Tight-aggressive: Chen-formula ranges, positional opens, c-bets, pot-odds folds |
| P3 | **LAG_Bluffmaster** | Loose-aggressive: wide opens, 3-bet bluffs, semi-bluffed draws, barrels |
| P4 | **Rock_Nit** | Ultra-tight premium-only rock with a short-stack push/fold gear |
| P5 | **EquityNerd** | Monte-Carlo equity vs. pot odds on every single decision |
| P6 | **Adaptive_Hustler** | Profiles opponents from the public action feed; tightens vs. maniacs, steals vs. nits |

## Run it

```bash
python3 holdem_sim.py --sims 100 --seed 42   # prints ASCII histogram, writes results/results.json
python3 make_chart.py                        # renders results/winner_histogram.png
```

## Result (100 sims, seed 42)

```
  WINNER WINNER CHICKEN DINNER -- tournament wins (100 sims)
  ----------------------------------------------------------------
  P1 SuflairGPT_AllIn     7 | ############ <- if my_turn: ALL IN
  P2 TAG_Shark           13 | ######################
  P3 LAG_Bluffmaster     29 | ################################################
  P4 Rock_Nit            21 | ###################################
  P5 EquityNerd          15 | #########################
  P6 Adaptive_Hustler    15 | #########################
  ----------------------------------------------------------------
```

The all-in bot wins 7% of tournaments and finishes with the worst average
placement at the table (4.95 of 6). It occasionally sun-runs a stack of
preflop coin flips into a title — variance is undefeated — but over 100
freezeouts every elaborate strategy beats it, and the loose-aggressive
bluffer laps it 4×. Shoving every hand is not a personality, it's a leak.
