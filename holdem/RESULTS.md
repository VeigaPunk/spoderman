# Hold'em death-match: 100-tournament results

100 six-handed freeze-out tournaments. Everyone starts with 1000 chips, blinds start 5/10 and double every 20 hands. Players 2-6 run elaborate strategies; Player 1 runs, in its entirety: `if my_turn then bet = All in fi`. No bot knows any other bot's strategy - they only see the public action stream.

## Winner histogram (last player on the table)

```text
Player 1  Leeroy (ALL-IN)        ████████████████ 8
Player 2  Doyle (TAG)            ████████████████████ 10
Player 3  Maverick (LAG)         ████████████████████████████████████████████ 22
Player 4  The Monk (NIT)         ████████████████████████████████ 16
Player 5  The Calculator (EQ)    ██████████████████████████████████████████████████ 25
Player 6  The Profiler (ADAPT)   ██████████████████████████████████████ 19
```

## Average finishing place (1 = champion, 6 = first bust)

| Player | Strategy | Avg place | Wins | First-out count |
|---|---|---|---|---|
| 1 | Leeroy (ALL-IN) | 5.13 | 8 | 64 |
| 2 | Doyle (TAG) | 3.11 | 10 | 5 |
| 3 | Maverick (LAG) | 3.30 | 22 | 3 |
| 4 | The Monk (NIT) | 2.66 | 16 | 3 |
| 5 | The Calculator (EQ) | 3.50 | 25 | 13 |
| 6 | The Profiler (ADAPT) | 3.30 | 19 | 12 |

## Player 1 (Leeroy) finish distribution

```text
place 1: ████████ 8
place 2: █ 1
place 3: ████ 4
place 4: ████████ 8
place 5: ███████████████ 15
place 6: ████████████████████████████████████████████████████████████████ 64
```

Average tournament length: 106.8 hands. Base seed 42 - rerun `python3 -m holdem.simulate` to reproduce these exact numbers.
