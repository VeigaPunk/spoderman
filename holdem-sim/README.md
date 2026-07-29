# holdem-sim — Suflair-GPT vs. Five Actual Poker Players

A no-limit Texas Hold'em tournament simulator: 6 players, equal starting
stacks (1000 chips), blinds 10/20 doubling every 20 hands, full betting
engine with all-ins and side pots, played winner-take-all until one
player holds every chip. 100 tournaments, then a histogram of who got
the chicken dinner.

**No player knows any other player's algorithm.** The only information a
strategy receives is what a human at the table would see: its own hole
cards, the board, stacks, the pot, and publicly observable actions
(from which the engine keeps running per-seat tendency counts — hands
played, VPIP, preflop raises, all-in frequency).

## The lineup

| Seat | Player | Strategy |
|------|--------|----------|
| 1 | **Suflair-GPT** | `if my_turn then bet = All in fi` — the entire algorithm |
| 2 | **Doyle** | Tight-aggressive: Chen-formula positional ranges, 3-bets premiums, c-bets, semi-bluffs draws, pot-odds discipline |
| 3 | **Gus** | Loose-aggressive: opens ~40% of hands, 3-bet bluffs, double-barrels, turns draws into semi-bluffs, but folds to raises without equity |
| 4 | **The Rock** | Ultra-tight trapper: premium hands only, zero bluffs, never lets go of top pair or better |
| 5 | **Ada** | Monte Carlo mathematician: simulates equity vs. random hands at every decision and compares it to pot odds — no reads, just arithmetic |
| 6 | **Sun-Tzu** | Adaptive exploiter: profiles opponents from observed actions (maniac / nit / loose / solid) and attacks — calls shove-monkeys down light with an on-the-spot equity check, steals from nits |

## Run it

```bash
cd holdem-sim
python3 simulate.py -n 100 --seed 42
```

No dependencies beyond the Python 3 standard library.

## Results

See [RESULTS.md](RESULTS.md) for the official 100-tournament histogram
(seed 42) and the post-game roast.

## Layout

- `poker/cards.py` — deck + fast 7-card hand evaluator + Monte Carlo equity
- `poker/engine.py` — betting engine, blinds, all-ins, side pots, tournament loop
- `poker/strategies.py` — the six brains
- `simulate.py` — runs N tournaments and prints the histogram
