# Texas Hold'em — 100 Tournament Simulation Results

6 players, 1000 chips each, blinds start 10/20 and double every 20 hands.
Last player with chips takes the tournament. No strategy knows any other
strategy's logic — they only observe public actions at the table.

## The lineup

| Player | Strategy | Idea |
|---|---|---|
| P1 | **AllInAndy** | `if my_turn then bet = All in fi` |
| P2 | **TagTitan** | Tight-aggressive: positional Chen-formula ranges preflop, Monte-Carlo equity value betting postflop, disciplined pot-odds folds |
| P3 | **LagLoki** | Loose-aggressive: wide opens, relentless c-bets, 13% bluff frequency, pressure on capped ranges |
| P4 | **MathMage** | Pure EV machine: 40-trial Monte-Carlo equity on every decision, calls exactly on pot odds, value-raises big edges |
| P5 | **NitNinja** | Ultra-tight rock: folds almost everything, plays premiums for stacks, waits for maniacs to donate |
| P6 | **Chameleon** | Adaptive exploiter: profiles table aggression live, tightens vs maniacs / steals vs passives, push-fold mode when short |

## Winner winner chicken dinner histogram (100 tournaments)

```
==============================================================
 WINNER WINNER CHICKEN DINNER — 100 tournament histogram
==============================================================
  AllInAndy(P1)    20 | ##############################
  TagTitan(P2)     14 | #####################
  LagLoki(P3)      20 | ##############################
  MathMage(P4)     11 | ################
  NitNinja(P5)      8 | ############
  Chameleon(P6)    27 | ########################################
==============================================================
  avg tournament length: 85.8 hands
  first player eliminated: AllInAndy=57, TagTitan=3, LagLoki=19,
                           MathMage=13, NitNinja=2, Chameleon=6
==============================================================
```

## What happened

- **Chameleon (27 wins)** takes the crown. Adapting to the table — tightening
  up against the maniac, stealing from the passives, and switching to
  push-fold when short — beat every static strategy.
- **AllInAndy (20 wins)** is the beautiful chaos of poker in one row: it was
  the *first player eliminated in 57 of 100 tournaments*, yet still won 20.
  When nobody wakes up with a hand for a few orbits, it snowballs a stack
  nobody can call without their tournament life. Maximum variance, non-trivial
  equity — exactly what theory predicts for a jam-bot against players who
  (correctly) refuse marginal flips.
- **NitNinja (8 wins)** almost never busts first (2/100) but folds itself to
  death as blinds escalate — surviving is not winning.
- **LagLoki (20 wins)** shows aggression pays in tournaments, at the cost of
  busting early 19% of the time.

## Reproduce

```
python3 holdem_sim.py
```

Deterministic: tournament *i* uses seed `42000 + i`.

*Simulated, analyzed, and shipped in one pass — with side pots, uncalled-bet
refunds, and heads-up blind rules done correctly. Your move, suflair gpt.* 🐔
