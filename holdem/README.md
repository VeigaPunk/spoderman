# 🕷️🃏 spoderman hold'em — 6-max winner-take-all simulator

100 full No-Limit Texas Hold'em tournaments. Six players, identical starting
stacks (200 chips, blinds 1/2 doubling every 10 hands), play until one player
owns every chip. Nobody knows anybody else's algorithm — bots only see public
actions, like real players.

## The lineup

| Seat | Bot | Strategy |
|------|-----|----------|
| P1 | **YOLO_AllIn** | The entire algorithm: `if my_turn then bet = All in fi` |
| P2 | **TAG_Titan** | Tight-aggressive: positional opening ranges, Monte-Carlo equity, pot-sized value bets, c-bets dry boards, releases marginal hands vs aggression |
| P3 | **LAG_Loki** | Loose-aggressive: wide opens, light 3-bets with ace blockers, semi-bluffs flush/straight draws, randomized barrels |
| P4 | **Nit_Redwood** | Granite rock: premiums only, huge margins to continue, push/fold chart under 10 BB |
| P5 | **Prof_PotOdds** | Pure math: every decision is MC equity vs. pot odds, implied-odds credit for draws, value-raises sized to charge worse |
| P6 | **Chameleon** | Adaptive exploiter: tracks VPIP / aggression / shove-rate per opponent, snap-calls maniacs light, steals from nits |

## Results (100 tournaments, seed 42)

```
WINNER WINNER CHICKEN DINNER — tournament wins out of 100 sims
========================================================================
P1_YOLO_AllIn    | ██████████████████████████████████████████████████  36  (36.0%)
P2_TAG_Titan     | ██████                                               4  ( 4.0%)
P3_LAG_Loki      | ███████████████████████████████                     22  (22.0%)
P4_Nit_Redwood   | ████                                                 3  ( 3.0%)
P5_Prof_PotOdds  | ████████████████████████                            17  (17.0%)
P6_Chameleon     | █████████████████████████                           18  (18.0%)
========================================================================
avg tournament length: 67.1 hands (min 41, max 101)
```

## The uncomfortable poker lesson

The three-line bot beat five "elaborate" strategies. This is not a bug — it's
a famous property of winner-take-all tournaments with escalating blinds:

- **Fold equity is enormous.** Shoving 100 BB into a 3 BB pot gets called only
  by premiums. Everyone folds ~2/3 of hands, so the maniac vacuums blinds
  every single orbit while the blinds double.
- **Winner-take-all flattens risk.** There's no ICM, no cashing 2nd place.
  Chip EV = win probability, so hyper-variance is nearly free.
- **Tightness is punished.** The nit (3%) and the by-the-book TAG (4%) got
  blinded into dust waiting for hands that never came. The players who
  fought back — the adaptive Chameleon (18%), the mathematician (17%), and
  the bluffing lunatic (22%) — split most of what was left.

So yes: `if my_turn then bet = All in fi` outdrew every sophisticated model
at the table. Suflair GPT would have written 400 lines of GTO solver prose
and still mucked pocket jacks to the shove. Winner winner chicken dinner. 🍗

## Run it yourself

```bash
cd holdem
python3 run_sims.py                # 100 sims, seed 42 (reproducible)
python3 run_sims.py --sims 500     # more sims
python3 run_sims.py --seed 7       # different deck destiny
```

Pure Python 3 stdlib — no dependencies. ~3 seconds for 100 tournaments.

## What's inside

- `poker/cards.py` — direct 7-card hand evaluator (no 21-combo loop) +
  Monte-Carlo equity estimator + Chen-style preflop scoring
- `poker/engine.py` — full NLHE engine: blinds & escalation, betting rounds,
  min-raise tracking, all-ins for less, **side pots**, heads-up button rules
- `poker/strategies.py` — the six bots
- `run_sims.py` — tournament runner + histogram

Seats are shuffled every tournament so no bot keeps a positional edge; each
tournament is seeded for reproducibility.
