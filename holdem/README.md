# holdem — 6-max no-limit Texas Hold'em strategy shootout

100 full tournaments, 6 players, 1000 chips each, escalating blinds,
last stack standing wins. No player can see anyone else's algorithm —
strategies only observe public information (boards, stacks, and the
betting action broadcast to the table).

## The lineup

| Seat | Name | Strategy |
|------|------|----------|
| P1 | **AllInAndy** | `if my_turn then bet = All in fi` — that's it, that's the whole algorithm |
| P2 | **TAG-Tina** | Tight-aggressive: Chen-formula preflop ranges, position-aware opens, Monte-Carlo equity vs pot odds postflop, value bets and pot-sized raises |
| P3 | **LAG-Lucas** | Loose-aggressive: wide opens, suited connectors, c-bets, random stabs, occasional tilt calls and rare all-in bombs |
| P4 | **Nit-Nina** | The rock: folds everything except AA–JJ/AK (plus a few "strong" hands), then plays them like a freight train |
| P5 | **PotOdds-Pete** | The mathematician: every decision is Monte-Carlo equity vs required pot odds, nothing else |
| P6 | **Exploit-Eve** | The profiler: tracks each opponent's all-in and raise frequencies, detects maniacs, calls their shoves with any live-card edge, steals from the tight players |

## Run it

```
python -m holdem.simulate            # 100 tournaments, seed 42
python -m holdem.simulate 500 7      # 500 tournaments, seed 7
```

Pure stdlib, no dependencies, ~13s for 100 tournaments.

## Results (100 tournaments, seed 42)

```
P1 AllInAndy       █████████                                  7  (7%)
P2 TAG-Tina        ████████████████████████████████████████  30  (30%)
P3 LAG-Lucas       ███████████████████████████               20  (20%)
P4 Nit-Nina        █████████                                  7  (7%)
P5 PotOdds-Pete    ████████████████                          12  (12%)
P6 Exploit-Eve     ████████████████████████████████          24  (24%)

Average finishing place (1 = champion, 6 = first bust):
  P1 AllInAndy       5.14
  P2 TAG-Tina        2.47
  P3 LAG-Lucas       3.55
  P4 Nit-Nina        2.68
  P5 PotOdds-Pete    4.30
  P6 Exploit-Eve     2.86
```

Andy's 7%: shoving blind every hand steals a lot of blinds until someone
wakes up with a premium — but he still binks the occasional tournament,
because that's poker, baby.

## Engine notes

- Full no-limit betting: blinds, min-raise rules, all-in short calls,
  uncalled-bet refunds, and proper side-pot resolution at showdown.
- Blinds start 5/10 and double every 15 hands (capped), so tournaments
  always terminate.
- Fast 7-card evaluator (rank/suit counting, no 21-combo loops); equity
  is Monte-Carlo vs uniform random hands.
- Fully deterministic per seed: table RNG and each strategy's private
  RNG are seeded independently per tournament.
