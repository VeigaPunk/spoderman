# Hold'em Strategy Showdown 🃏🐔

A self-contained No-Limit Texas Hold'em **tournament** simulator pitting five
elaborate strategies against one player whose entire algorithm is:

```
if my_turn
then bet = All in
fi
```

## The table

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **SuflairGPT** | All-in. Every time. That's it. That's the algorithm. |
| P2 | **TheRock** | Tight-aggressive nit — premium hands only, position-aware opening ranges, never limps, c-bets as the aggressor, pays off only with two pair or better. |
| P3 | **TheMaverick** | Loose-aggressive — opens ~40% of hands, barrels relentlessly, semi-bluffs flush/straight draws, random bluff raises, but folds to real pressure without equity. |
| P4 | **TheMathematician** | Pure pot odds — Monte-Carlo equity estimation every decision, calls only when equity beats the price, thin value-raises above 62% equity. Feels nothing. |
| P5 | **TheProfessor** | Positional player — seat-based range charts (Chen formula), pot control out of position, attacks when checked to in position. |
| P6 | **TheShark** | Adaptive — profiles every opponent from *public actions only* (VPIP, raise counts, shove frequency) and adjusts: calls chronic shovers wide with any pair/big ace, tightens vs. nits. |

No player knows another player's algorithm. TheShark only ever sees the same
public table actions a human would.

## Rules of the sim

- 6 players, equal starting stacks (1000 chips), blinds 10/20 doubling every
  15 hands (so tournaments always terminate).
- Full no-limit engine: four betting streets, min-raise rules, all-ins,
  **side pots** (essential — P1 forces one nearly every hand), split pots,
  button rotation, heads-up blind rules.
- A tournament ends when one player holds all the chips; 100 independent
  tournaments are played and the winner of each is tallied.

## Run it

```bash
python3 holdem_sim.py --sims 100 --seed 1337
```

No dependencies — pure Python 3 stdlib. Chip conservation and the 7-card
evaluator are sanity-checked (royal flush, quads, wheel, two pair; 30
tournaments audited hand-by-hand for chip leaks).

## Results (100 sims, seed 1337)

```
==================================================================
  WINNER WINNER CHICKEN DINNER — 100 tournament simulations
==================================================================
  P1 SuflairGPT       █████████████████                         16  ( 16.0%)
  P2 TheRock          ████                                       4  (  4.0%)
  P3 TheMaverick      ████████████████████████████████████████  37  ( 37.0%)
  P4 TheMathematician █████████████████████████                 23  ( 23.0%)
  P5 TheProfessor     ██████                                     6  (  6.0%)
  P6 TheShark         ███████████████                           14  ( 14.0%)
==================================================================
```

## Post-game analysis

- **SuflairGPT (16%)** lands *below* the 16.7% equal-skill baseline and gets
  more than doubled up by two thinking players. The all-in bot steals a lot of
  blinds early and occasionally sun-runs an entire tournament, but the moment
  anyone wakes up with a real hand holding more chips, it's a coin flip at
  best — and it takes that coin flip every single hand until it loses one.
  Humiliation: delivered. 📉
- **TheMaverick (37%)** is the ecosystem winner: against a table where the
  maniac inflates pots and the nits over-fold, relentless aggression with
  fold equity prints chips.
- **TheMathematician (23%)** quietly cashes in by only ever paying the
  correct price — including correctly calling shoves with enough equity.
- **TheRock (4%)** and **TheProfessor (6%)** discover that waiting for aces
  while the blinds double every 15 hands is a slow-motion funeral.
- **TheShark (14%)** counters the shover well but pays a tax learning each
  opponent from scratch every tournament.

Moral: "all in every hand" is not a strategy, it's a countdown. 🐣
