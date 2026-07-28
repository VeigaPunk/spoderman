# Hold'em Strategy Battle

6-player No-Limit Texas Hold'em tournament simulator. Full engine: blinds
(escalating), 4 betting streets, min-raise rules, all-ins with side pots,
7-card hand evaluation.

## The contenders

| Seat | Strategy | Idea |
|------|----------|------|
| P1 | All-In Monkey | `if my_turn then bet = All in fi` |
| P2 | Tight-Aggressive | Chen-formula ranges by position, equity value-betting |
| P3 | Loose-Aggressive | Wide ranges, steals, bluffs, pot-odds discipline |
| P4 | Rock | Premium hands only, played for stacks |
| P5 | Math Professor | Monte Carlo equity vs pot odds every street |
| P6 | Profiler | Tracks opponents' aggression, exploits maniacs |

No strategy knows any other's algorithm — only public actions.

## Run it

```
python3 run_sims.py [seed]
```

100 tournaments, everyone starts with 1000 chips, winner = last player
with chips. Prints an ASCII histogram and writes `results.json`.
