# holdem_sim — the All-In Andy experiment

A six-max no-limit Texas Hold'em tournament simulator, built to answer an
eternal question: what happens when one player's complete strategy document is

```
if my_turn
then bet = All in
fi
```

and the other five run elaborate, multi-factor poker brains?

## The lineup

| seat | player | strategy |
|---|---|---|
| P1 | **AllInAndy** | The sacred text above, implemented with total fidelity. |
| P2 | **GrandmasterFlush** | Tight-aggressive: Chen-formula preflop ranges widened by position, Harrington-M push/fold when short, c-bets, semi-bluffs draws on price. |
| P3 | **BluffyTheVampireSlayer** | Loose-aggressive: wide opens, randomized light 3-bets, late-position steals, barrels with pairs/draws/air — but folds air to pot-sized violence. |
| P4 | **TheGranite** | A rock. Premium-only preflop, stacks off with JJ+/AK, continues postflop only with top pair or better. |
| P5 | **CountVonCount** | Pure math: Monte Carlo equity vs. the live opponent count on every decision, compared to pot odds; bet size scales with edge. |
| P6 | **SherlockShark** | Adaptive profiler: builds a dossier of every opponent's public actions (VPIP, raise %, open-shove %) and exploits what it finds — e.g. calling chronic shovers on raw equity, stealing from rocks. |

**Information hygiene:** no player is told anyone's strategy. Strategies receive
only their own hole cards plus public state (board, pot, bets, stacks) and a
feed of public actions/showdowns — everything else must be inferred at the
table, like real poker.

## The engine

Full no-limit tournament rules: rotating button, small/big blinds doubling
every 15 hands, min-raise enforcement, all-ins, **proper side pots** (crucial —
Andy generates a lot of them), split pots, eliminations, heads-up blind order.
A chips-conservation assert runs after every hand. Pure stdlib; matplotlib is
optional for the PNG chart.

## Run it

```
python3 -m holdem_sim.simulate --sims 100 --seed 42 --chips 1000
```

Prints an ASCII championship histogram and writes
`results/RESULTS.md` + `results/winners_histogram.png`.

## Results (100 tournaments, seed 42)

```
P1 AllInAndy                 ██████████                                 8  (8%)
P2 GrandmasterFlush          █████████████████████                     17  (17%)
P3 BluffyTheVampireSlayer    █████████████████████████████             24  (24%)
P4 TheGranite                █                                          1  (1%)
P5 CountVonCount             █████████████████████                     17  (17%)
P6 SherlockShark             ████████████████████████████████████████  33  (33%)
```

The story the numbers tell:

- **SherlockShark wins the most (33%).** The only player who *learns*. After
  watching a few hands it stops respecting Andy's shoves and calls with any
  hand whose equity beats the price — Andy's chips are a subscription service.
- **AllInAndy still wins 8%.** That's the terrifying part of the strategy:
  shoving 100% of hands means nobody gets a fair fight, and sometimes the deck
  simply refuses to punish him for an entire tournament. His average finish of
  5.0/6 shows how it usually goes, though: first into the parking lot.
- **TheGranite almost never wins (1%) despite the second-best average finish
  (2.7).** Waiting for aces is a great way to outlast Andy and a terrible way
  to beat four other competent players once the blinds are huge. Surviving ≠
  winning.
- Aggression pays: the two most aggressive solid players (Sherlock, Bluffy)
  take 57% of the titles between them.
