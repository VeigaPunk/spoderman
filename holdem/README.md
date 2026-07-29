# 🕸️ Spoderman Hold'em Thunderdome

100 full 6-max no-limit Texas Hold'em **tournaments** (not hands — each sim
plays until one player owns every chip). Everyone starts with 10,000 chips,
blinds 50/100 escalating ×1.5 every 20 hands, button rotates, side pots
handled properly. No bot can see any other bot's cards or algorithm — only
public actions.

## The roster

| Player | Strategy | Personality |
|---|---|---|
| **P1** | **YOLO All-In** | `if my_turn Then bet = All in Fi` — the entire algorithm |
| P2 | TAG Shark | Tight-aggressive: Chen-formula positional ranges, c-bets, Monte-Carlo hand strength, disciplined stack-off thresholds |
| P3 | LAG Blaze | Loose-aggressive: wide opens, steal raises, randomized bluff & double-barrel frequencies, semi-bluff shoves |
| P4 | Rock Nit | Ultra-tight value player: premiums only, never bluffs, only stacks off near the nuts |
| P5 | Math Professor | Pure EV: Monte-Carlo equity on *every* decision vs exact pot odds |
| P6 | Adaptron | Exploitative profiler: tracks VPIP / aggression / shove-frequency of opponents from public actions and targets the leaks (calls maniacs wide, steals from nits, push/fold when short) |

## Winner histogram (100 tournaments, seed 42)

```
P1 YOLO All-In       | █████████                                            7  (7%)
P2 TAG Shark         | ██████                                               5  (5%)
P3 LAG Blaze         | ██████████████████████████████████████████████████  41  (41%)
P4 Rock Nit          | ██                                                   2  (2%)
P5 Math Professor    | ██████████████████                                  15  (15%)
P6 Adaptron          | █████████████████████████████████████               30  (30%)
```

| player | wins | win% | avg finish |
|---|---|---|---|
| P1 YOLO All-In | 7 | 7% | 5.07 |
| P2 TAG Shark | 5 | 5% | 3.10 |
| P3 LAG Blaze | **41** | **41%** | 2.77 |
| P4 Rock Nit | 2 | 2% | 3.11 |
| P5 Math Professor | 15 | 15% | 4.19 |
| P6 Adaptron | **30** | **30%** | 2.76 |

17,695 hands dealt across the 100 tournaments. PNG version in
[`../results/winner_histogram.png`](../results/winner_histogram.png).

## Reading the tea leaves

- **The maniac is not zero.** P1 wins 7% of tournaments by pure variance —
  shove every hand and sometimes the deck just loves you six showdowns in a
  row. But an average finish of 5.07/6 means the usual outcome is the first
  bus home.
- **Aggression wins tournaments.** LAG Blaze (41%) and Adaptron (30%)
  dominate because escalating blinds punish passivity; Adaptron specifically
  profiles the table and calls the maniac's shoves wide.
- **Playing tight cashes, doesn't win.** Rock Nit almost never busts early
  (avg finish 3.11) but blinds away before the trophy.
- **Pot odds alone aren't enough.** The Professor plays perfect prices but
  never bluffs and never adapts, so he bleeds in the endgame.

## Run it yourself

```bash
python3 run_sims.py --sims 100 --seed 42
```

Requires only the standard library; `pip install matplotlib` for the PNG.
