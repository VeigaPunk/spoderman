# holdem-sim — 6-max Texas Hold'em tournament simulator

Winner-take-all tournament simulator, pure Python stdlib, no dependencies.

## The lineup

| Seat | Player | Strategy |
|------|--------|----------|
| P1 | **SuflairGPT** | `if my_turn then bet = ALL IN fi` — that's it, that's the strategy |
| P2 | Tightbeard (TAG) | Tight-aggressive: Chen-formula preflop ranges, value-bets made hands, folds to pressure without equity |
| P3 | Loki (LAG) | Loose-aggressive: wide ranges, c-bets, occasional pure bluffs, sticky calls |
| P4 | The Rock (Nit) | Premium hands only (QQ+/AK shoved, 99+/AQ+ played), folds the rest |
| P5 | Pot-Odds Professor | Monte-Carlo equity vs pot odds on every meaningful decision |
| P6 | Adaptive Anna | Tracks public action stats per opponent (shove rate, aggression, VPIP) and exploits: waits out maniacs, steals from nits |

No strategy can see another strategy's code or hole cards — decisions use only
public game state (board, bets, stacks, observed action history) plus own cards.

## Engine

- Full Hold'em rules: blinds, 4 betting streets, min-raise rules, all-ins,
  **side pots**, split pots with odd-chip handling
- 7-card hand evaluator (straight flush → high card, wheel included)
- Blinds escalate every 25 hands so tournaments always terminate
- Chip-conservation assert after every hand
- Deterministic per-seed; each of the 100 tournaments uses `seed + i`

## Run it

```bash
python3 holdem_sim.py --sims 100 --seed 42   # the official run
python3 holdem_sim.py --selftest              # evaluator + engine sanity checks
```

## Official results (100 tournaments, seed 42, equal 1000-chip stacks)

```
P6 Adaptive Anna           27 (27.0%) ██████████████████████████████████████████████████
P3 Loki (LAG)              25 (25.0%) ██████████████████████████████████████████████
P5 Pot-Odds Professor      19 (19.0%) ███████████████████████████████████
P2 Tightbeard (TAG)        16 (16.0%) ██████████████████████████████
P1 SuflairGPT               8 ( 8.0%) ███████████████
P4 The Rock (Nit)           5 ( 5.0%) █████████
```

SuflairGPT: 8 wins out of 100, and first player eliminated in **55** of them.
The bot that watches what everyone does and adapts (Anna) wins the most —
largely by simply waiting for a real hand before calling the all-in maniac.

Full output in [`results_seed42.txt`](results_seed42.txt).
