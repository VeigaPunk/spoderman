# Spoderman Hold'em Arena

100 winner-take-all No-Limit Texas Hold'em tournaments. Six players, equal
starting stacks (1000 chips), escalating blinds, full side-pot handling,
last player with chips takes the title. No player knows any other player's
algorithm — strategies only observe public actions and showdowns.

## The lineup

| Seat | Strategy | Idea |
|------|----------|------|
| P1 | **Leeroy Jenkins** | `if my_turn then bet = All in fi` — the entire algorithm |
| P2 | **The Professor** (TAG) | tight-aggressive: Chen-formula ranges by position, c-bets, disciplined folds |
| P3 | **The Cowboy** (LAG) | loose-aggressive: wide opens, 3-bet bluffs with blockers, multi-street barrels, river overbets |
| P4 | **The Rock** (Nit) | ultra-tight: folds for hours, stacks off only with monsters |
| P5 | **The Mathematician** (EV) | Monte Carlo equity vs pot odds — pure expected value, zero psychology |
| P6 | **The Profiler** (Exploit) | tracks opponent VPIP / all-in rate / fold-to-bet and adjusts ranges to exploit |

## Run it

```
python -m poker.selftest    # evaluator + engine sanity checks
python -m poker.simulate    # 100 tournaments, prints histogram, writes RESULTS.md
```

Deterministic (seeded) — results in [RESULTS.md](RESULTS.md).

## Files

- `cards.py` — card encoding + 5/6/7-card hand evaluator
- `engine.py` — tournament engine: betting rounds, min-raise rules, side pots, blind escalation, eliminations
- `strategies.py` — the six players
- `simulate.py` — runs the 100 sims and prints the winner histogram
- `selftest.py` — sanity checks
