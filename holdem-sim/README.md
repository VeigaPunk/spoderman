# holdem-sim

A self-contained no-limit Texas Hold'em sit-n-go simulator, pitting five
"elaborate" strategies against one very simple one:

```
if my_turn
then bet = All in
fi
```

## The lineup

| Seat | Bot | Strategy |
|------|-----|----------|
| P1 | **Suflair-GPT** | All-in, every hand, no exceptions |
| P2 | **TAG-Shark** | Tight-aggressive: Chen-formula ranges that widen with position, continuation bets, strict pot-odds discipline |
| P3 | **MonteCarlo-Oracle** | Estimates equity by Monte-Carlo rollout vs random hands on every decision and compares it to pot odds |
| P4 | **LAG-Hurricane** | Loose-aggressive: wide ranges, suited connectors in position, semi-bluffs draws, bluffs only opponents who can still fold |
| P5 | **Granite-Nit** | Ultra-tight rock: premiums only, push-or-fold when short |
| P6 | **Adaptive-Vulture** | Opponent modeller: tracks public preflop stats per seat, flags all-in maniacs, and calls their shoves with a much wider +EV range; steals from tight tables |

No bot can see another bot's cards or code. Every decision is made from
public information only: own hole cards, board, pot, stacks, bets, and the
visible action history.

## The engine

Full no-limit rules: blinds (doubling every 12 hands), min-raise tracking,
all-ins for less, side pots with correct eligibility, split pots with
odd-chip distribution, button rotation with eliminations, and a 7-card
evaluator (self-tested on startup). Chip conservation is asserted after
every hand.

## Run it

```sh
python3 holdem_sim.py --sims 100 --seed 42
```

Pure standard library, no dependencies. 100 tournaments take ~4 seconds.
Results of the canonical seed-42 run are in [results.md](results.md).
