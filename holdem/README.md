# Texas Hold'em: five elaborate strategies vs. one very simple one

A complete no-limit Texas Hold'em tournament engine plus six agents, and a
100-tournament freezeout to answer one question: **how often does the dumbest
possible strategy actually win?**

```
python -m holdem.tests                    # engine / evaluator self-checks
python -m holdem.simulate --sims 100      # the experiment
```

Pure standard library. No dependencies. ~2.5s for 100 tournaments on 4 cores.

## The setup

Six seats, 10,000 chips each, freezeout (no rebuys) to a single survivor.
Blinds rise every 20 hands through a 16-level structure with antes from level
3. Button rotates, heads-up posts correctly, and the last player at the table
is the winner.

**Seat 1 plays the strategy from the brief, verbatim:**

```python
class AllInBot(Strategy):
    """if my_turn then bet = All in fi"""
    def act(self, obs):
        if obs.can_raise:
            return (RAISE, obs.max_raise_to)   # shove
        return (CALL, 0)                       # already all-in for less: call
```

**Seats 2-6 play five elaborate strategies:**

| # | Agent | Core idea |
|---|-------|-----------|
| P2 | `SOLVERLITE` | Percentile range charts by position; postflop it defends at minimum-defence frequency, bets polarised, and bluffs at exactly `alpha = b/(1+2b)` for its chosen size so its bluff-to-value ratio keeps opponents indifferent. Mixed (randomised) frequencies throughout. Tries to be *unexploitable*. |
| P3 | `BAYES-EXPLOIT` | Keeps Beta posteriors per seat over VPIP, PFR, postflop aggression, fold-to-bet and all-in frequency. Converts each opponent's observed frequency into an estimated **range width** `w`, then re-prices its own equity as `p1^(1 + 1.7(1-w))`. Picks the max-EV line from an explicit fold-equity model. Tries to be *maximally exploitative*. |
| P4 | `ICM-GRINDER` | Push/fold charts by effective stack, Harrington M-zones, and a **Malmuth-Harville ICM risk premium** on every all-in decision, so it needs a real edge before risking its tournament life. Plays the payout ladder, not the chips. |
| P5 | `PRESSURE-LAG` | Loose-aggressive. Wide opens, light 3-bets in position, double and triple barrels driven by an explicit fold-equity model, polarised river overbets — with a discipline valve that refuses to stack off with air. |
| P6 | `TRAP-ROCK` | Top ~12% preflop, then lets the aggressive players bet into it: checks monsters to induce, springs check-raises, pot-controls medium hands, calls down against opponents it has measured as over-aggressive. |

**No agent is told which strategy sits in which seat.** The `Obs` object an
agent receives at decision time contains public table state (stacks, bets,
board, action history, position, blind level) plus *its own* hole cards, and
nothing else. Everything P3 knows about the others it learned by watching
public actions and showdowns — the same information a human at the table has.

## Results: 100 tournaments

```
  P3 BAYES-EXPLOIT      37   37.0%  ██████████████████████████████████████████████
  P2 SOLVERLITE         22   22.0%  ███████████████████████████
  P4 ICM-GRINDER        16   16.0%  ████████████████████
  P5 PRESSURE-LAG       12   12.0%  ███████████████
  P6 TRAP-ROCK           7    7.0%  █████████
  P1 JAM-O-TRON          6    6.0%  ███████
```

A fair six-way split would be 16.7% each.

| player | 1st | 2nd | 3rd | 4th | 5th | 6th | avg finish | KOs | avg hands survived |
|---|---|---|---|---|---|---|---|---|---|
| P3 BAYES-EXPLOIT | 37 | 15 | 13 | 21 | 14 | 0 | 2.60 | 113 | 86.8 |
| P4 ICM-GRINDER | 16 | 29 | 18 | 14 | 12 | 11 | 3.10 | 81 | 89.5 |
| P2 SOLVERLITE | 22 | 17 | 13 | 20 | 23 | 5 | 3.20 | 90 | 73.5 |
| P6 TRAP-ROCK | 7 | 23 | 30 | 13 | 11 | 16 | 3.46 | 59 | 78.6 |
| P5 PRESSURE-LAG | 12 | 13 | 22 | 24 | 17 | 12 | 3.57 | 81 | 57.9 |
| P1 JAM-O-TRON | 6 | 3 | 4 | 8 | 23 | **56** | 5.07 | 76 | **11.4** |

### What the numbers say

**The shove-bot is not zero.** 6 wins in 100. Shoving every hand is a real
strategy with real fold equity — when five opponents each have to make a
correct call-off decision every single hand, sometimes nobody has a hand, and
JAM-O-TRON picks up blinds and antes uncontested until it is chip leader. It
also collected **76 knockouts**, more than TRAP-ROCK, because every pot it
plays is for someone's stack.

**But it dies first 56% of the time and lasts 11.4 hands on average**, versus
~90 for the tournament-minded agents. Its average finish is 5.07 out of 6.
Given six seats, "random" would be 16.7% wins and a 3.5 average finish — the
simple strategy is roughly a third as good as chance.

**Adaptation beats balance.** P3 wins more than twice as often as it should
and — the striking number — **never once busted first in 100 tournaments**.
Its edge is mechanical: it *measures* that seat 1 raises 100% of hands, so its
model assigns seat 1 a range width of 1.0, and prices seat 1's all-in against
literally random cards. That turns every JAM-O-TRON shove into a simple pot-odds
problem, which it solves correctly. P2, playing fixed unexploitable charts, calls
the same shoves with a fixed top-7.5% range and leaves money on the table. This
is the classic GTO-vs-exploitative result, reproduced: against a maximally
unbalanced opponent, an exploitative agent strictly outperforms a balanced one.

**Survival isn't the same as winning.** P4 survives longest of anyone (89.5
hands) and takes 2nd place more often than any other agent (29 times), but
converts only 16 of those deep runs into a win. That is its ICM risk premium
working exactly as designed and being *wrong for this contest*: the premium
optimises a payout ladder, and here only first place pays, so declining
marginal +chipEV spots to protect a finish is a pure leak. P6 shows the same
pathology harder — 30 third-place finishes, 7 wins.

**Tournament length:** min 10 hands, median 136, max 230.

### Signal vs. noise

100 tournaments is not many. The 95% intervals in the histogram overlap for
everything in the middle, so re-running the same 100-sim experiment at 20x
scale (2000 tournaments, seeds 500000-501999, `results_2000_summary.json`):

```
  P3 BAYES-EXPLOIT     634   31.7%   [95% CI 29.7-33.8%]
  P2 SOLVERLITE        419   20.9%   [95% CI 19.2-22.8%]
  P5 PRESSURE-LAG      375   18.8%   [95% CI 17.1-20.5%]
  P4 ICM-GRINDER       260   13.0%   [95% CI 11.6-14.5%]
  P6 TRAP-ROCK         209   10.4%   [95% CI  9.2-11.9%]
  P1 JAM-O-TRON        103    5.1%   [95% CI  4.3- 6.2%]
```

The two claims that matter survive: **P3 first by a wide margin, P1 last.**
P3 busts first in 6 of 2000 tournaments (0.3%); P1 busts first in 1206 of 2000
(60.3%) and averages 11.7 hands of life. The middle of the field — P5 vs. P4
in particular, which swap places between the two runs — is inside the noise at
n=100, and the honest reading is that P2/P5 and P4/P6 are not separated by
this experiment.

## Engine

`engine.py` implements the parts that actually change strategy quality:

* min-raise tracking, and the rule that a **short all-in raise does not reopen
  betting** for players who already acted
* layered **side pots**, odd chips to the first seat left of the button
* **uncalled bets returned** to the bettor
* correct heads-up blind posting and action order
* every action returned by a strategy is clamped onto the legal action set,
  so a buggy agent can't corrupt the game state

`cards.py` has a 7-card evaluator (~300k hands/sec, pure Python), verified
against brute-force enumeration of all 21 five-card subsets.

`equity.py` estimates equity by Monte Carlo, seeded from a **suit-isomorphic
canonical key** for the situation — so the cache is a pure function of its
input and a run is bit-identical no matter how the work is sharded across
cores. Preflop equity comes from a 169x5 table built once and cached in
`preflop_equity.json`.

## Reproducing

```
python -m holdem.tests                                  # 30 self-checks
python -m holdem.simulate --sims 100 --json out.json    # the run above
```

Seeds 1000-1099. Same seed, same result, every time, on any number of cores.
`python -m holdem.equity` rebuilds the preflop table from scratch.
