# Texas Hold'em: five elaborate strategies vs one all-in bot

A no-limit Hold'em freezeout simulator. Six seats, identical starting stacks,
no rebuys, last player standing wins. Seats 2–6 run elaborate strategies; seat 1
runs three lines of pseudocode.

```
python -m holdem.tests                  # correctness checks
python -m holdem.simulate --sims 100    # the tournament series + histogram
python -m holdem.analysis               # heads-up duels + seat-fairness control
```

## The table

| Seat | Agent | Strategy |
|---|---|---|
| **1** | COELHO DOIDO | `if my_turn then bet = ALL IN fi` |
| 2 | GORILA ALADO | Tight-aggressive: Chen-scored preflop range, Monte-Carlo equity vs pot odds postflop |
| 3 | BEBE RAIVA | Loose-aggressive: wide opens, light 3-bets, high c-bet frequency, semi-bluffs |
| 4 | TIGRE PENSADOR | Balanced: equity buckets → mixed action distributions, minimum-defence-frequency calling, polarised sizing |
| 5 | CAVEIRA PEAKY | Exploitative: builds per-opponent VPIP/aggression/shove stats and discounts the credibility of aggression it has seen too often |
| 6 | DEMONIO AZUL | Stack-depth: M-ratio regimes (push-fold / steal / deep) plus an ICM bubble factor that declines marginal coinflips |

## Information isolation

No agent is told which strategy any other agent runs. The engine hands each
agent an `Observation` namedtuple containing public table state plus *its own*
hole cards. `SeatView` — the per-opponent record inside it — carries chips,
bets and status, never cards. Seat 5 is the only adaptive agent, and it has to
infer everything from observed betting. `tests.py::test_no_strategy_leakage`
asserts this structurally.

## Engine

Full NLHE rules: rotating button, escalating blinds and antes, heads-up blind
reversal, four betting streets, correct min-raise tracking, the rule that a
short all-in does **not** reopen betting, layered side pots, and odd-chip
remainders awarded left of the button. Illegal or malformed agent returns are
clamped to the nearest legal action rather than trusted.

Verified by `tests.py`: hand-evaluator ground truth (including wheel straights,
two-sets-make-a-boat, kicker resolution), chip conservation across 25 complete
tournaments, side-pot construction including uncalled-overbet return, and deck
integrity.

### Card encoding

`rank = card >> 2` with ranks 2..14, so the 52 real cards are the ints
**`[8, 60)`**, not `[0, 52)`. Deal only from `cards.FULL_DECK`. Dealing from
`range(52)` produces rank-0 and rank-1 cards that silently corrupt evaluation —
`test_deck` guards this.

## Results (100 freezeouts, seed 20260729)

| Seat | Agent | Wins | Avg. finish |
|---|---|---:|---:|
| 6 | DEMONIO AZUL | 22 | 3.27 |
| 2 | GORILA ALADO | 21 | 2.90 |
| 5 | CAVEIRA PEAKY | 18 | 3.16 |
| 3 | BEBE RAIVA | 15 | 3.65 |
| 4 | TIGRE PENSADOR | 14 | 3.42 |
| **1** | **COELHO DOIDO (all-in)** | **10** | **4.60** |

Confirmed over 1000 freezeouts: the all-in bot wins 8.2%, busts first 61.0%,
and averages 5th place. Chance-level for six players is 16.7%.

The single-number summary is misleading on its own, though: the all-in bot
finishes **last on average** while still winning ~1 tournament in 10. Shoving
every hand does not produce a small edge, it produces a fat right tail. It is
out first 61% of the time and survives ~25 hands against ~100–120 for the
disciplined agents.

## A leak the analysis found

The first version of this simulation had the all-in bot beating the two
*tightest* strategies heads-up **81.5%** and **86.2%** of the time. That was not
the bot being clever — it was a bug in my strategies. Facing an all-in they
folded everything below a premium hand, which against an opponent who shoves
100% of hands means donating the blinds one orbit at a time until the stack is
gone. Folding is not a defence against a maniac; calling by pot odds is.

Both now treat being put all-in as a price question (Monte-Carlo equity vs the
pot odds being laid) rather than a range question:

| Heads-up, 400 duels, seats alternated | all-in bot win rate before | after |
|---|---:|---:|
| vs GORILA ALADO (TAG) | 81.5% | **47.2%** |
| vs TIGRE PENSADOR (balanced) | 86.2% | **47.0%** |
| vs DEMONIO AZUL (ICM) | 46.5% | 44.8% |
| vs BEBE RAIVA (LAG) | 41.5% | 41.5% |
| vs CAVEIRA PEAKY (exploitative) | 37.5% | 39.5% |

The two agents that already reasoned about all-ins explicitly — the exploitative
modeller and the ICM agent — were never exploitable in the first place.

## Fairness control

Six identical all-in bots, 300 tournaments: 54/42/57/54/48/45 wins by seat,
chi-square 3.48 on 5 d.o.f. (p0.05 critical value 11.07). No detectable seat
bias, so the results above are strategy effects, not position effects.
