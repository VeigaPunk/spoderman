# 🃏 HOLD'EM ROYALE

A 6-max No-Limit Texas Hold'em **tournament simulator** — full betting engine
(blinds, min-raise rules, all-ins, side pots, 7-card hand evaluator), six
players, equal starting stacks (1000 chips), escalating blinds, play until one
player owns everything.

Zero dependencies. Pure Python 3 stdlib.

```bash
python3 holdem.py --sims 100 --seed 2026
```

## The contestants

No player knows any other player's algorithm.

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **LEEROY (ALL-IN)** | `if my_turn: bet = ALL_IN fi` — that's it. That's the whole strategy. |
| P2 | **The Professor** | Tight-aggressive: Chen-formula preflop ranges by position, continuation bets, pot-odds-disciplined calls, push/fold when short. |
| P3 | **The Cowboy** | Loose-aggressive: wide ranges, blind steals, 3-bets, triple barrels, semi-bluffed draws, randomized bluff frequency. |
| P4 | **The Actuary** | Pure math: Monte-Carlo equity simulation on every decision, only puts chips in when equity beats pot odds by a margin. |
| P5 | **The Rock** | Ultra-tight nit: premium hands only, slow-plays monsters to trap, set-mines small pairs when cheap, push/fold short-stacked. |
| P6 | **The Shark** | Adaptive exploiter: profiles opponents from *observed actions only* (all-in rate, aggression, fold rate), then snap-calls detected maniacs with any hand that beats a random hand, steals from tight tables, and scales bluff frequency to fold rates. |

## Results — 100 tournaments, seed 2026

```
==============================================================
  HOLD'EM ROYALE — WINNER HISTOGRAM (100 tournaments, seed 2026)
==============================================================
  LEEROY (ALL-IN) | ████████████████ 14
  The Professor   | ███████████ 10
  The Cowboy      | ████████████████████████████████████████ 36
  The Actuary     | ███████████████████ 17
  The Rock        | ██████████ 9
  The Shark       | ████████████████ 14
--------------------------------------------------------------
  avg tournament length: 125 hands

  avg finishing position (1 = chicken dinner, 6 = first bust):
  LEEROY (ALL-IN) | avg 4.98   first-out 67x
  The Professor   | avg 3.18   first-out 4x
  The Cowboy      | avg 2.71   first-out 4x
  The Actuary     | avg 3.68   first-out 6x
  The Rock        | avg 3.14   first-out 7x
  The Shark       | avg 3.31   first-out 12x
==============================================================
```

## What the histogram teaches

- **The Cowboy (LAG) crushes** with 36 wins. In fast-blind tournaments,
  relentless aggression prints money: every steal is free equity, and the
  tight players hand over their blinds.
- **LEEROY is a variance monster**: first player eliminated in **67 of 100**
  tournaments (avg finish 4.98/6)… and *still* wins 14% of them. Shoving
  blind forces everyone else into coin-flips, and if you win the first few
  flips you own half the table's chips. This is genuinely why casinos love
  maniacs: they don't win often, but they make the game insane.
- **The Actuary's cold math** takes second place — never bluffing, never
  paying more than equity is worth.
- **The Rock survives** (rarely busts early) but blinds away too much to win
  — tight-passive is a slow death when blinds escalate.
- **The Shark's** maniac-detection works (it snap-calls Leeroy light), but it
  needs a few observed hands to profile anyone — and Leeroy often gets his
  double-ups in before the read is locked in.
