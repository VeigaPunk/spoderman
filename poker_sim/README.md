# poker_sim — 5 elaborate brains vs 1 line of code

A complete 6-max no-limit Texas Hold'em tournament simulator in pure Python
stdlib. Five elaborate strategies (players 2–6) face one player (P1) whose
entire strategy is:

```
if my_turn
then bet = All in
fi
```

No strategy can see another's code, cards, or reasoning — each receives only a
`TableView` (public table state + its own hole cards) and a stream of public
action events, exactly like a human at the table.

## Run it

```bash
python -m poker_sim.simulate --sims 100 --seed 7
```

See [RESULTS.md](RESULTS.md) for the official 100-sim histogram, and
[results_histogram.html](results_histogram.html) for the pretty version.

## The engine (`engine.py`)

- Full no-limit betting: blinds, min-raise tracking, re-raises, all-ins.
- Side pots via contribution layering, split pots, uncalled-bet return.
- Rotating button, heads-up blind rules (button posts SB), eliminations,
  escalating blind levels (every 30 hands) so tournaments always end.
- 7-card hand evaluator (best-of-21 five-card combos, LRU-cached).
- Chip conservation asserted after every hand.

One simplification vs. casino rules: an all-in raise below the minimum raise
still reopens action to players who already acted.

## The six players (`strategies.py`)

| Seat | Name | Personality |
|---|---|---|
| P1 | **AllInAnnie** | The spec, verbatim. Shoves. Every. Hand. |
| P2 | **TheRock** | Ultra-tight nit. Premium hands only, calls all-ins only with the top of the deck, slow-plays monsters, never bluffs. |
| P3 | **TagTitan** | Textbook tight-aggressive: position-scaled Chen-formula opens, 3-bets, continuation bets, semi-bluffs strong draws, calls strictly by pot odds, stack-aware shove calls. |
| P4 | **LagLoki** | Loose-aggressive chaos merchant: wide steals, ace-blocker 3-bet bluffs, relentless semi-bluffs, double barrels, random out-of-nowhere aggression. |
| P5 | **CaseyCalculator** | No soul, only math: Monte Carlo equity simulation (60 rollouts, cached per street) compared against pot odds on every nontrivial decision. |
| P6 | **Sherlock** | Adaptive profiler: tracks every opponent's VPIP, aggression frequency and shove rate from public actions alone, then exploits — snap-calls shove-bots wide, hero-folds to nits, steals from the fold-happy. |

Shared analytical toolkit: Chen preflop scoring, hole-card-aware made-hand
tiers (air → quads), flush/straight draw detection with out counting, and a
Monte Carlo equity estimator.

## Simulation protocol (`simulate.py`)

- 100 tournaments, all players start with 200 chips (100 bb at 1/2 blinds).
- Fresh strategy instances per tournament (no cross-tournament memory).
- Starting button rotates per tournament for seat fairness.
- Deterministic given `--seed`; per-player and per-tournament RNG streams.
- Output: winner histogram, win %, average finish, busted-first counts.
