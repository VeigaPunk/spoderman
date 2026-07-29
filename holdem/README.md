# 🕷️🃏 spoderman hold'em — 5 galaxy brains vs. 1 button

A no-limit Texas Hold'em tournament simulator built to answer one question:
what happens when five elaborate poker strategies sit down against a player
whose *entire* algorithm is

```
if my_turn
then bet = All in
fi
```

Nobody knows anybody else's strategy (or cards). Every brain receives only the
public game state — its own hole cards, the board, stacks, pot, price to call —
and the public action stream, exactly like a human at the table.

## The lineup

| Seat | Name | Strategy |
|------|------|----------|
| P1 | **Suflair GPT** | The four-line masterpiece above. All in. Every hand. Forever. |
| P2 | **The Professor** | Tight-aggressive: position-aware Chen ranges preflop, Monte Carlo equity postflop, value-bets and the occasional semi-bluff. |
| P3 | **La Loba** | Loose-aggressive: steals, c-bets ~70% of flops, semi-bluff-raises live draws, releases when the price kills the bluff. |
| P4 | **The Rock** | Ultra-tight nit: premiums only, no coin flips for stacks, only stacks off with the goods. |
| P5 | **The Actuary** | Pure math: Monte Carlo equity vs. the field compared to pot odds. No reads, no bluffs, no feelings. |
| P6 | **The Profiler** | Adaptive exploiter: builds a dossier on every opponent from public actions alone (VPIP, raise rate, **shove rate**) and re-prices its calling range — snap-calls maniacs wide. |

## The rules

- 6-max table, everyone starts with **1,000 chips**, blinds 10/20 doubling
  every 20 hands.
- Full no-limit engine: min-raise rules, correct **side pots** (essential —
  P1 creates one nearly every hand), heads-up button rules, odd-chip awards.
- 100 independent tournaments, seeded and reproducible (`--seed 42`).
- A tournament ends when one player holds all 6,000 chips: the
  winner-winner-chicken-dinner, last player on the table.

## Run it

```bash
pip install matplotlib
python3 simulate.py --sims 100 --seed 42
```

~30 seconds. Prints an ASCII histogram and writes
`results/winner_histogram.png` + `results/tournaments.csv`.

## The verdict (100 tournaments, seed 42)

```
P1 Suflair GPT (all-in)     |###################                           |  10  (10.0%)
P2 The Professor (TAG)      |############################################  |  23  (23.0%)
P3 La Loba (LAG)            |#################################             |  17  (17.0%)
P4 The Rock (nit)           |########                                      |   4  ( 4.0%)
P5 The Actuary (pot odds)   |##########################################    |  22  (22.0%)
P6 The Profiler (adaptive)  |##############################################|  24  (24.0%)
```

![winner histogram](results/winner_histogram.png)

| player | wins | avg finish | busted first |
|--------|-----:|-----------:|-------------:|
| P1 Suflair GPT | 10 | 5.07 | **61** |
| P2 The Professor | 23 | 3.15 | 3 |
| P3 La Loba | 17 | 3.63 | 8 |
| P4 The Rock | 4 | 2.58 | 3 |
| P5 The Actuary | 22 | 3.22 | 5 |
| P6 The Profiler | 24 | 3.35 | 20 |

**The humiliation, quantified.** Suflair GPT busts out *first* in 61% of
tournaments and averages dead last (5.07 of 6). Its 10 wins are pure variance —
the rare heater where six consecutive shoves hold up. Fittingly, the top
assassin is The Profiler, the one strategy that watches behavior: it clocks
P1's 100% shove rate within a few hands and starts snap-calling with anything
that beats a random hand.

Bonus insight: The Rock has the *best* average finish (2.58) but almost never
wins — folding your way to the final two is easy; folding your way to the
trophy is not. Blinds are a tax on cowardice.

## Files

- `poker.py` — cards, 7-card evaluator, Monte Carlo equity, Chen formula
- `strategies.py` — the six sealed brains
- `engine.py` — tournament engine (betting, side pots, blinds, eliminations)
- `simulate.py` — runs N tournaments, prints/renders the histograms
