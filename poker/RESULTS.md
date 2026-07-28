# Texas Hold'em Strategy Showdown — 100 Tournaments

6-max no-limit hold'em. Every player starts with 1000 chips, blinds 10/20
doubling every 15 hands, winner takes the table. No player knows any other
player's algorithm. Reproducible with `python3 holdem_sim.py` (seeded).

## The contenders

| Player | Strategy | Idea |
|---|---|---|
| P1 | **YOLO** | `if my_turn then bet = All in fi` — the whole algorithm |
| P2 | **The Rock** | Tight-aggressive: premium hands only, then max pressure |
| P3 | **The Professor** | Live Monte Carlo equity vs pot odds every street |
| P4 | **The Maniac** | Loose-aggressive: relentless bluffs and fold-equity abuse |
| P5 | **The Chameleon** | Exploitative profiler: tracks VPIP/aggression/shove rate, adapts |
| P6 | **The Banker** | Stack-pressure/ICM: M-ratio push/fold, bullies medium stacks |

## Winner histogram (100 tournaments)

```
P1 YOLO (all-in every turn)               ██████████████ 9
P2 The Rock (tight-aggressive)            ██████████ 6
P3 The Professor (Monte Carlo EV)         ████████████████████████████████ 20
P4 The Maniac (loose-aggressive)          ███████████████████████████████████ 22
P5 The Chameleon (exploitative profiler)  █████████████████████████████ 18
P6 The Banker (stack-pressure/ICM)        ████████████████████████████████████████ 25

avg tournament length: 72 hands
```

## Post-game commentary

- **The Banker (25)** takes the crown — playing the tournament structure
  (push/fold when short, bullying when big) beats playing pretty cards.
- **The Maniac (22)** proves aggression prints chips when opponents fold
  too much.
- **The Professor (20)** and **The Chameleon (18)** grind out solid,
  math-and-reads results.
- **YOLO (9)** — a three-line strategy still banked 9 titles. Variance is
  undefeated: shove often enough and sometimes you're the one holding aces.
- **The Rock (6)** — dead last among the "elaborate" bots. Waiting for the
  nuts while blinds double every 15 hands is a slow-motion funeral. Tightness
  that would be fine in a cash game gets blinded out in a turbo.

Chip conservation is asserted after every hand (no chips created or
destroyed across all 100 × ~72 hands).
