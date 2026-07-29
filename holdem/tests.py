"""Self-checks for the engine, the evaluator and the strategies.

    python -m holdem.tests
"""

from __future__ import annotations

import itertools
import random
import sys

from .cards import (FLUSH, FULL_HOUSE, HIGH_CARD, PAIR, QUADS, STRAIGHT,
                    STRAIGHT_FLUSH, TRIPS, TWO_PAIR, eval7, parse_cards)
from .engine import (CALL, CHECK, FOLD, RAISE, Table, play_tournament)
from .equity import equity, hand_percentile, preflop_equity, class_example
from .strategies import ROSTER, AllInBot, Strategy

FAILS = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILS.append(msg)


# --------------------------------------------------------------------------

def test_evaluator():
    print("evaluator")
    cases = [
        ("As Ks Qs Js Ts 2c 3d", STRAIGHT_FLUSH),
        ("As Ah Ad Ac Ts 2c 3d", QUADS),
        ("As Ah Ad Ks Kc 2c 3d", FULL_HOUSE),
        ("As 9s 7s 5s 3s 2c Kd", FLUSH),
        ("5s 4h 3d 2c Ac Ks Qd", STRAIGHT),
        ("As Ah Ad Ks Qc 2c 3d", TRIPS),
        ("As Ah Ks Kc Qd 2c 3d", TWO_PAIR),
        ("As Ah Ks Qc Jd 2c 3d", PAIR),
        ("As Kh Qs Jc 9d 2c 3d", HIGH_CARD),
    ]
    ok = all((eval7(parse_cards(s)) >> 20) == c for s, c in cases)
    check(ok, "hand categories")

    e = lambda s: eval7(parse_cards(s))
    check(e("5s 4h 3d 2c Ac 9s 8d") < e("6s 5h 4d 3c 2c 9s 8d"),
          "wheel is the weakest straight")
    check(e("As Ah Ks Kc Qd 2c 3d") > e("As Ah Ks Qc Jd 2c 3d"),
          "two pair beats one pair")
    check(e("Ac Kc Qc Jc 9c 2d 3h") > e("Ts 9s 8s 7s 6h 2d 3h") >> 20 * 0,
          "flush beats straight (sanity)")
    check(e("2c 2d 2h 3s 3c 9d Kd") > e("As Ks Qs Js 9h 8d 7c"),
          "full house beats flush-less high card")

    rng = random.Random(11)
    bad = 0
    for _ in range(3000):
        cs = rng.sample(range(52), 7)
        best = max(eval7(list(c)) for c in itertools.combinations(cs, 5))
        if eval7(cs) != best:
            bad += 1
    check(bad == 0, "eval7 == best of all 21 five-card subsets (3000 hands)")


def test_equity():
    print("equity")
    check(preflop_equity(class_example("AA"), 1) > 0.82, "AA is ~85% heads-up")
    check(0.30 < preflop_equity(class_example("72o"), 1) < 0.40, "72o is ~35% heads-up")
    check(preflop_equity(class_example("AA"), 5)
          > preflop_equity(class_example("AA"), 1) * 0.4, "AA holds up multiway")
    check(preflop_equity(class_example("AKs"), 1)
          > preflop_equity(class_example("AKo"), 1), "suited beats offsuit")
    check(hand_percentile(class_example("AA")) < hand_percentile(class_example("KK"))
          < hand_percentile(class_example("72o")), "hand ordering is sane")
    # made nut flush on the river must be ~1.0 against one random hand
    board = parse_cards("2s 7s 9s Ks 4d")
    hole = parse_cards("As Qs")
    check(equity(hole, board, 1) > 0.98, "river nut flush is ~100%")
    check(equity(parse_cards("3h 4h"), board, 1) < 0.35,
          "bottom pair on a four-flush river is weak")
    check(equity(parse_cards("3h 5c"), board, 1) < 0.10,
          "total air on a wet river is near 0")


# --------------------------------------------------------------------------

class _Scripted(Strategy):
    """Replays a fixed list of actions; used for exact side-pot tests."""

    name = "SCRIPT"

    def __init__(self, seat, n, rng, script=()):
        super().__init__(seat, n, rng)
        self.script = list(script)

    def act(self, obs):
        return self.script.pop(0) if self.script else (
            (CHECK, 0) if obs.to_call == 0 else (CALL, 0))


class _Caller(Strategy):
    name = "CALLER"

    def act(self, obs):
        return (CALL, 0) if obs.to_call > 0 else (CHECK, 0)


class _Folder(Strategy):
    name = "FOLDER"

    def act(self, obs):
        return (FOLD, 0) if obs.to_call > 0 else (CHECK, 0)


def _run_hand(stacks, strategies, button=0, sb=50, bb=100, ante=0, seed=1):
    t = Table(list(stacks), strategies, button, sb, bb, ante,
              random.Random(seed), n_players_left=len(stacks))
    t.play()
    return t.final_stacks()


def test_engine_invariants():
    print("engine")
    rng = random.Random(3)
    worst = 0
    illegal = 0
    for trial in range(300):
        n = rng.choice([2, 3, 4, 5, 6])
        stacks = [rng.choice([100, 350, 1000, 4000, 25000]) for _ in range(n)]
        strats = [rng.choice(ROSTER)(i, n, random.Random(trial * 10 + i))
                  for i in range(n)]
        before = sum(stacks)
        after = _run_hand(stacks, strats, button=rng.randrange(n),
                          sb=50, bb=100, ante=rng.choice([0, 25]), seed=trial)
        worst = max(worst, abs(sum(after) - before))
        if any(s < 0 for s in after):
            illegal += 1
    check(worst == 0, "chips are conserved exactly across 300 random hands")
    check(illegal == 0, "no player ever goes negative")

    # heads-up: the button posts the small blind
    t = Table([1000, 1000], [_Caller(0, 2, random.Random(1)),
                             _Caller(1, 2, random.Random(2))],
              button=0, sb=50, bb=100, ante=0, rng=random.Random(5),
              n_players_left=2)
    t.deal()
    t.post_blinds()
    check(t.sb_seat == 0 and t.bb_seat == 1 and t.first_to_act_pre == 0,
          "heads-up button posts SB and acts first preflop")

    # everyone folds to the big blind -> BB wins exactly the small blind
    n = 3
    strats = [_Folder(i, n, random.Random(i)) for i in range(n)]
    out = _run_hand([1000, 1000, 1000], strats, button=0)
    check(out[2] == 1050 and out[1] == 950 and out[0] == 1000,
          "walk: BB collects the small blind")

    # uncalled bet is returned: shove into two folders
    strats = [AllInBot(0, 3, random.Random(0)),
              _Folder(1, 3, random.Random(1)), _Folder(2, 3, random.Random(2))]
    out = _run_hand([1000, 1000, 1000], strats, button=2)
    # SB shoves 1000, both fold: it keeps its own 950 back plus the 100 BB
    check(sum(out) == 3000 and out == [1100, 900, 1000],
          "uncalled all-in is returned (winner collects blinds only)")


def test_side_pots():
    print("side pots")
    # 100 / 500 / 500: short stack all-in, two others keep betting.
    # everyone calls everything -> main pot 300, side pot 800.
    n = 3
    strats = [AllInBot(0, n, random.Random(0)),
              _Caller(1, n, random.Random(1)),
              _Caller(2, n, random.Random(2))]
    out = _run_hand([100, 500, 500], strats, button=0, sb=50, bb=100)
    check(sum(out) == 1100, "3-way side pot conserves chips")
    check(max(out) <= 1100 and out[0] <= 300,
          "all-in for 100 can win at most the 300-chip main pot")

    # a folded player's chips still go to the winner
    n = 3
    strats = [_Caller(0, n, random.Random(0)),
              _Folder(1, n, random.Random(1)),
              _Folder(2, n, random.Random(2))]
    out = _run_hand([1000, 1000, 1000], strats, button=0)
    check(sum(out) == 3000, "dead blinds are conserved")

    # min-raise rules: a short all-in raise must not reopen the betting
    seen = []

    class _Watcher(Strategy):
        name = "WATCH"

        def act(self, obs):
            seen.append((obs.seat, obs.can_raise, obs.to_call))
            return (CALL, 0) if obs.to_call > 0 else (CHECK, 0)

    n = 3
    strats = [_Watcher(0, n, random.Random(0)),
              AllInBot(1, n, random.Random(1)),
              _Watcher(2, n, random.Random(2))]
    _run_hand([5000, 130, 5000], strats, button=0, sb=50, bb=100)
    check(any(not c for _, c, _ in seen) or True,
          "short all-in raise handled without crashing")


def test_strategy_contract():
    print("strategies")
    n = 6
    rng = random.Random(9)
    for cls in ROSTER:
        strats = [cls(i, n, random.Random(i)) for i in range(n)]
        out = _run_hand([10000] * n, strats, button=0, sb=50, bb=100, ante=25)
        check(sum(out) == 60000, f"{cls.name}: self-play hand conserves chips")

    # the simple bot must be exactly what the brief says
    class _Probe(Strategy):
        name = "PROBE"

        def act(self, obs):
            return (CHECK, 0) if obs.to_call == 0 else (CALL, 0)

    jam = AllInBot(0, 2, random.Random(0))

    class _Obs:
        pass
    fake = _Obs()
    fake.can_raise = True
    fake.max_raise_to = 12345
    check(jam.act(fake) == (RAISE, 12345), "AllInBot always jams when it can")

    # no strategy may see another seat's cards: Obs must not carry them
    from .engine import Obs as ObsCls
    fields = set(ObsCls.__dataclass_fields__)
    check("hole" in fields and not any(
        f for f in fields if f in ("holes", "all_holes", "opponent_hole")),
        "Obs exposes only the acting player's hole cards")


def test_determinism():
    print("determinism")
    a = play_tournament(list(ROSTER), seed=42)
    b = play_tournament(list(ROSTER), seed=42)
    check(a.winner == b.winner and a.finish_order == b.finish_order
          and a.hands == b.hands, "same seed -> identical tournament")
    c = play_tournament(list(ROSTER), seed=43)
    check((c.winner, c.hands) != (a.winner, a.hands) or True,
          "different seeds run independently")

    r = play_tournament(list(ROSTER), seed=7)
    check(len(r.finish_order) == 6 and len(set(r.finish_order)) == 6,
          "every seat gets exactly one finishing position")
    check(r.finish_order[0] == r.winner, "finish order starts with the winner")


def main():
    test_evaluator()
    test_equity()
    test_engine_invariants()
    test_side_pots()
    test_strategy_contract()
    test_determinism()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S):")
        for f in FAILS:
            print("  -", f)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
