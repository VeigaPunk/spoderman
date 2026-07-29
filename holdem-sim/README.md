# 🃏 holdem-sim — 6-max Texas Hold'em tournament simulator

100 winner-take-all sit-n-go tournaments. Six players, identical starting
stacks (1,500 chips), escalating blinds, real no-limit betting with side
pots, all-in runouts, and a proper 7-card hand evaluator. Last player with
chips gets the chicken dinner.

**No player knows any other player's strategy or hole cards.** Every
decision is made from public information only (board, pot, bets, stacks)
plus the player's own two cards.

## The lineup

| Seat | Strategy | Description |
|------|----------|-------------|
| **Player 1** | **All-In Bot** | The entire algorithm: `if my_turn then bet = All in fi` |
| Player 2 | TAG Shark | Tight-aggressive. Chen-formula preflop ranges with position awareness, continuation bets, pot-odds calls, semi-bluffs with strong draws. |
| Player 3 | The Rock | Ultra-tight nit. Premium hands only, value bets monsters, folds everything else, desperation-shoves when blinded down. |
| Player 4 | LAG Bully | Loose-aggressive. Opens wide, steals blinds, barrels every street, semi-bluffs every draw, shoves on short stacks to apply maximum pressure. |
| Player 5 | The Professor | Pot-odds mathematician. Monte-Carlo equity rollouts vs. N random opponent hands, compares equity to price, raises with an edge, push/fold when short. |
| Player 6 | Trickster | Balanced-deceptive. Limps monsters, slow-plays sets, check-raises, floats, and mixes in random bluffs so nobody can put it on a hand. |

## Run it

```bash
python3 holdem_sim.py            # 100 sims, seed 42 (reproducible)
python3 holdem_sim.py --sims 500 --seed 7
```

Pure Python 3 stdlib. No dependencies.

## Results (100 sims, seed 42)

```
  WINNER WINNER CHICKEN DINNER HISTOGRAM (championships won)

  Player 1 (All-In Bot)       |█████████████████                         12
  Player 2 (TAG Shark)        |█████████████████████████                 18
  Player 3 (The Rock)         |██████                                     4
  Player 4 (LAG Bully)        |████████████████████████████████████████  29
  Player 5 (The Professor)    |██████████████████████                    16
  Player 6 (Trickster)        |█████████████████████████████             21

  👑 Overall champion: Player 4 (LAG Bully) with 29/100 titles
```

## What the numbers say

- **The All-In Bot is not a joke — but it is a loser.** 12/100 is below the
  16.7% a coin-flip lineup would give it. Early on it steals a lot of
  blinds because nobody has a hand, but every tournament eventually someone
  wakes up with a real holding, calls, and executes it. You can't win a
  freezeout by winning 100 small pots and losing one big one.
- **Aggression wins freezeouts.** The LAG Bully's relentless pressure is
  worth more than perfection in a winner-take-all format with escalating
  blinds — it accumulates chips while others wait for permission.
- **Playing scared is the only true losing strategy.** The Rock folded its
  way to 4 titles. The blinds ate it alive. Tight is right; frozen is
  broke.

*Simulated in one shot, seeded and reproducible, side pots and all.
Suflair GPT is cordially invited to submit a seat 7 bot whenever it
finishes shuffling.* 🐔🍗
