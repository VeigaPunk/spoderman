# 🕸️ SPODERPOKER — 6-max No-Limit Hold'em Tournament Simulator

Six players, equal stacks (1,000 chips), freezeout tournaments with escalating
blinds, played until one player owns every chip on the table. **No player knows
any other player's strategy** — they only observe public actions (fold / check /
call / raise amounts), like at a real table.

## The lineup

| Seat | Name | Strategy |
|------|------|----------|
| 1 | **All-In Andy** | `if my_turn: bet = ALL IN; fi` — that's it. That's the whole algorithm. |
| 2 | **The Professor** | Tight-aggressive. Chen-formula preflop ranges, position-aware opens, pot-odds discipline postflop. |
| 3 | **La Pistolera** | Loose-aggressive. Wide opens, relentless continuation bets, randomized bluffs, semi-bluffs her draws. |
| 4 | **The Rock** | Ultra-tight nit. Premiums only, pot-controls medium hands, traps with monsters, push/fold when short. |
| 5 | **The Actuary** | Pure EV machine. Estimates equity, compares to pot odds, only puts chips in when the price is right. |
| 6 | **The Chameleon** | Adaptive exploiter. Profiles every opponent live (VPIP, aggression, shove frequency) and counter-adjusts — including snap-calling habitual shovers wide. |

## Run it

```bash
python3 holdem_sim.py --sims 100 --seed 42 --json-out results_100sims.json
```

Pure standard library, no dependencies. ~1 second for 100 tournaments.

## Results — 100 tournaments (seed 42)

```
==========================================================================
  WINNER WINNER CHICKEN DINNER — championships per player (100 tournaments)
==========================================================================
  Player 1 — All-In Andy        29  ██████████████████████████████████████████████████
  Player 2 — The Professor       4  ███████
  Player 3 — La Pistolera       27  ███████████████████████████████████████████████
  Player 4 — The Rock            3  █████
  Player 5 — The Actuary        16  ████████████████████████████
  Player 6 — The Chameleon      21  ████████████████████████████████████
==========================================================================
  avg tournament length: 95 hands
```

## Post-game analysis (a.k.a. the humiliation section)

**The `if my_turn then ALL IN fi` bot beat five elaborate algorithms.** 29% of
the chicken dinners went to a strategy that fits in a tweet. This is not a bug —
it's a well-known tournament phenomenon:

- Shoving every hand forces everyone else to play for stacks with the kind of
  hands their careful thresholds say to fold. Andy steals blinds uncontested
  for whole orbits, and when he does get called it's roughly a coin flip.
- The disciplined bots (Professor, Rock) are *exploitable by chaos*: their
  tight ranges mean Andy prints money between their premium hands. The Rock
  won 3 tournaments. Three. Discipline without adaptation is just donating
  slowly.
- The bots that fought back best were exactly who you'd expect: **La Pistolera**
  (aggression meets aggression, 27 wins) and **The Chameleon** (21 wins), who
  literally profiles shove frequency and widens his calling range against
  maniacs. The Actuary's cold EV math kept him respectable at 16.

Fancy hand-reading, positional nuance, opponent modeling... and the histogram
still crowns the guy who never once looked at his cards. Poker is a beautiful,
terrible game.

## Engine notes

- Full no-limit betting engine: blinds, min-raise tracking, partial-call
  all-ins, **side pots** by contribution level, split pots with odd-chip
  handling.
- Blinds start at 5/10 and double every 15 hands (guarantees termination).
- 7-card hand evaluator (best 5 of 7), heuristic hand-strength model
  (made-hand category + draw potential + board-texture discounts) — fast
  enough that 100 tournaments run in about a second.
- Deterministic per `--seed`; each tournament gets an independent RNG stream.
