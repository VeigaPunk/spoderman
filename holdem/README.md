# 🕸️ Spoder Hold'em Arena

Six bots. One table. 1000 chips each. Tournaments run until one player owns
every chip — winner winner chicken dinner.

```bash
python3 holdem_sim.py --sims 100 --seed 42     # the official run
python3 holdem_sim.py --sims 5 --verbose       # watch individual tournaments
```

Pure stdlib Python. No dependencies. No mercy.

## The roster

No player knows any other player's algorithm. They see only their own cards,
the board, and everyone's **public actions** (bets, folds, shoves) — exactly
like a real table.

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **All-In Andy** | The entire algorithm, verbatim: `if my_turn then bet = All in fi` |
| P2 | **Rock Rocco** | Ultra-tight value machine. Opens only premiums (QQ+/AK tier 1; TT–JJ/AQ/AJs+/KQs tier 2), never bluffs, stacks off only with the goods. Postflop: bets big with two-pair+, pot-controls top pair, check-folds air. |
| P3 | **Professor Potts** | Pot-odds purist. Runs a Monte Carlo equity simulation (40–60 rollouts vs N random hands) on **every decision** and compares equity to the price: shoves >82% equity, value-raises big edges, calls thin edges, folds the rest. |
| P4 | **Loose Lucy** | Loose-aggressive menace. Opens wide by design, pure-steals 15% of unopened pots, c-bets 60%, semi-bluffs flush/straight draws, occasionally check-raise-bluffs, and pot-raises two pair+. |
| P5 | **Shark Sharon** | Position TAG. Scores hands with the Chen formula, widens her opening range from early position to the button, 3-bets premiums, c-bets heads-up as the aggressor, and plays strict made-hand/draw thresholds postflop. |
| P6 | **Profiler Petra** | Adaptive exploiter. Profiles opponents purely from observed actions; anyone going all-in on >50% of hands is flagged a maniac. She then snap-calls their shoves on raw equity, **limps her premiums to trap them**, and checks strong hands to induce the inevitable shove. Solid Chen/equity poker vs everyone else. |

## Engine

Full no-limit Texas Hold'em: escalating blinds (10/20 doubling every 12
hands), min-raise rules, all-ins, **side pots**, split pots with odd-chip
handling, button rotation, eliminations. The 7-card evaluator is verified
against brute-force best-of-21 on thousands of random hands, and total chips
are asserted conserved across every tournament.

## Official results (100 tournaments, seed 42)

See [RESULTS.md](RESULTS.md) for the full histogram. Spoiler: chaos is a
ladder, but variance is not a retirement plan — Andy binks 14 titles yet
finishes dead last on average (4.87/6), busting first in most tournaments.
Loose Lucy's aggression farms the table once the maniac donates his stack.
