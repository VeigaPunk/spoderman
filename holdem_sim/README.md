# Hold'em Strategy Thunderdome

A zero-dependency (pure Python stdlib) no-limit Texas Hold'em tournament
simulator that pits five elaborate strategies against one player whose entire
algorithm is:

```
if my_turn
then bet = All in
fi
```

## The lineup

| Seat | Name           | Strategy |
|------|----------------|----------|
| P1   | All-In Andy    | The pseudocode above. That's it. That's the strategy. |
| P2   | The Accountant | Tight-aggressive. Chen-formula preflop ranges by position, disciplined pot-odds accounting postflop, push/fold when short-stacked. |
| P3   | The Cowboy     | Loose-aggressive. Wide opening ranges, relentless continuation bets, semi-bluffs every flush/straight draw. |
| P4   | The Professor  | Pure math. Monte Carlo equity estimation vs. random hands on every single decision, compared against pot odds with a risk margin. Never bluffs — considers it undignified. |
| P5   | The Trickster  | Randomized mixed strategy. Slowplays monsters, bluffs scary boards, limps premiums, check-raises for fun. Deliberately unreadable. |
| P6   | The Shark      | Adaptive opponent modeler. Tracks each opponent's observed VPIP / raise rate / jam rate from public actions only, then exploits: calls hyper-aggressive shovers wide with equity edges, respects tight players' raises, steals from the fearful. |

No player knows any other player's algorithm — strategies only see public
information (board, pot, bets, stacks, action history) plus their own hole
cards. Anything the Shark "knows" about Andy it learned by watching him shove.

## The rules

- 6 players, identical starting stacks (1,000 chips), blinds 10/20 doubling
  every 25 hands.
- Full no-limit engine: four streets, min-raise rules, all-ins, **side pots**
  (mandatory when someone shoves every hand), uncalled-bet refunds, split pots,
  eliminations, heads-up blind handling.
- A tournament ends when one player has all 6,000 chips. That player is the
  winner-winner-chicken-dinner. 100 tournaments are played.

## Run it

```
python3 -m holdem_sim.simulate --sims 100 --seed 42
```

Deterministic for a given seed. Takes ~20s for 100 tournaments (~10k hands).

## Results (100 sims, seed 42)

```
  P1 All-In Andy      █████████████████████████ 16
  P2 The Accountant   ██████████████ 9
  P3 The Cowboy       ██████████████████████████████████████████████████ 32
  P4 The Professor    ████████████████████ 13
  P5 The Trickster    ████████████████████████████ 18
  P6 The Shark        ███████████████████ 12

  Average finishing position (1 = chicken dinner, 6 = first bust):
  P1 All-In Andy      4.80   <- boom or bust personified
  P2 The Accountant   2.86
  P3 The Cowboy       3.02
  P4 The Professor    3.53
  P5 The Trickster    3.24
  P6 The Shark        3.55
```

The poker lesson in one paragraph: All-In Andy wins 16% of tournaments —
roughly his fair 1-in-6 share — because open-shoving 50 big blinds steals
blinds uncontested for hours and occasionally he doubles through a cooler. But
his **average finish is 4.80**, by far the worst at the table: he busts first
or second in most tournaments, because sooner or later somebody wakes up with
a real hand and a receipt. Meanwhile the Cowboy's relentless aggression prints
the most chicken dinners, and the Accountant almost never busts early but
plays too honestly to close.

## Files

- `evaluator.py` — 7-card hand evaluator (straight flush down to high card)
- `engine.py` — tournament engine: betting, side pots, blinds, eliminations
- `strategies.py` — the six players
- `simulate.py` — runs N tournaments, prints the winner histogram
- `results/simulation_results.txt` — the committed output of the 100-sim run
