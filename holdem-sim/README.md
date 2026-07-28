# holdem-sim 🃏🍗

A dependency-free (pure Python stdlib) no-limit Texas Hold'em tournament
simulator. Six players, equal starting stacks, blinds double every 20 hands,
play until one player owns every chip. Full engine: betting rounds, min-raise
rules, uncalled-bet refunds, all-ins, layered side pots, split pots.

## The lineup

Nobody is told anybody else's strategy — bots see only public table state and
observable behavior, like at a real table.

| Seat | Bot | Strategy |
|------|-----|----------|
| P1 | **AllInAndy** | The entire spec: `if my_turn then bet = All in fi` |
| P2 | **TAG Tycoon** | Tight-aggressive: Chen-formula positional ranges, pot-odds calls with margin, value bets, short-stack push/fold |
| P3 | **LAG Lucia** | Loose-aggressive: wide positional opens, light 3-bets, relentless c-bets, randomized bluffs and floats |
| P4 | **Rock Reginald** | Ultra-tight nit: premiums only, never bluffs, calls all-ins only with a monster. Lets maniacs hang themselves |
| P5 | **Odds Oracle** | Pure math: Monte Carlo equity vs pot odds every decision, risk-scaled margins, small balancing bluff frequency |
| P6 | **Profiler Petra** | Adaptive exploitation: live-profiles every seat (VPIP / aggression / shove rate), snap-calls maniac shoves with any equity edge, folds to nits, steals from tight tables |

## Run it

```bash
python3 test_holdem.py            # sanity tests (evaluator, side pots, chip conservation)
python3 run_sims.py               # 100 tournaments, seed 42
python3 run_sims.py --sims 500 --seed 7
```

## Results — 100 tournaments, seed 42

```
==================================================================
   WINNER WINNER CHICKEN DINNER — tournament wins per player
==================================================================
P1 AllInAndy       | ██████ 4
P2 TAG Tycoon      | ████████████████████████████████ 21
P3 LAG Lucia       | ███████████████████████████████████████ 26
P4 Rock Reginald   | ████████ 5
P5 Odds Oracle     | ███████████████████████ 15
P6 Profiler Petra  | ████████████████████████████████████████████ 29
------------------------------------------------------------------
                       total tournaments: 100

Average finishing place (1 = chicken dinner, 6 = first bust):
  P1 AllInAndy       5.11
  P2 TAG Tycoon      3.01
  P3 LAG Lucia       3.41
  P4 Rock Reginald   2.72
  P5 Odds Oracle     3.52
  P6 Profiler Petra  3.23
```

11,993 hands dealt in ~11 seconds.

## Post-game commentary

- **AllInAndy** wins 4% of tournaments — pure variance. His average finish is
  dead last (5.11): shoving 72o into a table that eventually wakes up is not
  a retirement plan. He does occasionally sun-run five double-ups in a row,
  which is why the 4 is not a 0.
- **Profiler Petra** takes the trophy count (29). Profiling pays: she detects
  the maniac within a few hands and starts snap-calling his jams with any
  decent hand while everyone else waits for aces.
- **LAG Lucia** (26) over-performs her average finish — aggression converts
  chip leads into closed-out tournaments.
- **Rock Reginald** is the funniest result: *best* average finish (2.72),
  almost no wins (5). Folding your way to 2nd place, the nit lifestyle.
- Deterministic: same `--seed` → same 100 tournaments, card for card.

*Built and shipped in one conversation, engine + 6 bots + tests + 100 sims in
11 seconds of compute. Your move, suflair GPT.* 💅🍗
