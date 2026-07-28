# Texas Hold'em Strategy Showdown — 100 Tournament Results

Six players, identical 1000-chip starting stacks, escalating blinds, full
tournaments played until one player holds every chip. No strategy can see any
other strategy's code — only public actions at the table.

## The lineup

| Seat | Strategy | Idea |
|------|----------|------|
| P1 | **All-In Andy** | `if my_turn then bet = All in fi` |
| P2 | **Professor TAG** | Tight-aggressive: positional preflop ranges, equity-driven postflop bets, folds to pressure without a hand |
| P3 | **Maniac Marla** | Loose-aggressive: wide ranges, pot-sized raises, ~18% pure bluffs, still bails vs huge bets with air |
| P4 | **Nit Nigel** | Ultra-tight rock: premium hands only, never bluffs, snap-calls shoves with monsters |
| P5 | **Odds Olga** | Pure math: Monte Carlo equity vs pot odds on every street, value-raises as a clear favorite |
| P6 | **Sherlock** | Exploitative: profiles opponents from public actions; vs a serial shover it widens its calling range dramatically |

## Winner winner chicken dinner — champions over 100 tournaments

```
P1 All-In Andy          18 wins |####################################              | avg finish: 4.74
P2 Professor TAG        10 wins |####################                              | avg finish: 3.08
P3 Maniac Marla         25 wins |##################################################| avg finish: 3.62
P4 Nit Nigel             7 wins |##############                                    | avg finish: 2.84
P5 Odds Olga            18 wins |####################################              | avg finish: 3.46
P6 Sherlock             22 wins |############################################      | avg finish: 3.26
```

(avg ~93 hands per tournament; reproducible — tournament *i* uses seed `1000+i`)

## Takeaways

- **All-In Andy wins 18% but has by far the worst average finish (4.74/6).**
  The shove-everything bot is a variance monster: either he doubles through
  the table three times in the first orbit and steamrolls, or (far more
  often) someone wakes up with a real hand and he's the first one on the
  rail. High ceiling, brutal floor.
- **Sherlock's opponent modeling pays.** Detecting the serial shover from
  public action frequencies and loosening its all-in calling range converts
  directly into eliminations and 22 titles.
- **Aggression beats patience under escalating blinds.** Maniac Marla (25)
  tops the podium while Nit Nigel (7) blinds away waiting for aces — great
  average finish, almost never the last one standing.
- Winning a *tournament* is not the same as *lasting long*: Nigel has the
  best average finish and the fewest titles; Andy the inverse.

## Reproduce

```
python3 holdem_sim.py 100
```

*Simulated, engineered, and shipped by Claude Code in one sitting — full
engine with side pots, hand evaluator, five distinct AI personalities, and
100 tournaments in 26 seconds. Your move, suflair GPT.* 🍗
