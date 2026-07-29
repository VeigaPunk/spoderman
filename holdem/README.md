# holdem — 6-bot no-limit Texas Hold'em tournament simulator

Six bots sit at a table with **1500 chips each**, escalating blinds, full
no-limit betting with side pots and eliminations. Nobody knows anybody
else's algorithm — every bot sees only its own hole cards and the public
action stream. Last stack standing is the winner winner chicken dinner.

## The lineup

| Seat | Bot | Strategy |
|------|-----|----------|
| P1 | **Spoderman** | The entire algorithm: `if my_turn then bet = ALL IN fi` |
| P2 | **TAG_Titan** | Tight-aggressive: Chen-formula ranges, position awareness, 3-bets, c-bets, pot-odds draw calls |
| P3 | **LAG_Lunatic** | Loose-aggressive: wide opens, 3-bet bluffs, barrels, semi-bluff raises, hero calls |
| P4 | **EquityOracle** | Monte Carlo equity at every decision vs pot odds, mixed bet sizing |
| P5 | **NitNorris** | Premium-only nit, set-mining, Sklansky-style push/fold when short |
| P6 | **AdaptiveAdversary** | Opponent modeling: tracks shove/raise/fold rates from public actions and exploits them (calls maniacs wide, steals from folders) |

## Run it

```bash
python3 -m holdem.simulate            # 100 tournaments, seed 42
python3 -m holdem.simulate -n 500 --seed 7
```

## Results (100 tournaments, seed 42)

```
  P1 Spoderman           |██████████████████████████                         |  13  (13%)
  P2 TAG_Titan           |██████████                                         |   5  (5%)
  P3 LAG_Lunatic         |████████████████████████████████████████████       |  22  (22%)
  P4 EquityOracle        |██████████████████████████████████████             |  19  (19%)
  P5 NitNorris           |████████████████████████████████                   |  16  (16%)
  P6 AdaptiveAdversary   |██████████████████████████████████████████████████ |  25  (25%)
```

The all-in gremlin busts out **first in 55/100 tournaments** (avg finishing
place 4.85 of 6) — but still ships 13 titles, because when you shove every
hand, sometimes the deck simply refuses to stop hitting you. The
opponent-modeling bot wins the most: it notices the shove rate and starts
calling with anything that beats a random hand. Poker is a beautiful game.

Layout: `cards.py` (evaluator + Monte Carlo equity + Chen formula),
`engine.py` (betting, side pots, blinds, eliminations), `strategies.py`
(the six brains), `simulate.py` (tournament loop + histogram).

*Built by Claude Code in one shot — no notebook, no "as an AI language
model I cannot shove preflop". Your move, suflair gpt.* 🕷️🐔
