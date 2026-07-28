"""Sanity checks for the evaluator and engine. Run: python -m poker.selftest"""

import random

from .cards import evaluate, RANK_CHARS, SUIT_CHARS
from .engine import Tournament
from .strategies import ROSTER


def card(s):
    return RANK_CHARS.index(s[0]) * 4 + SUIT_CHARS.index(s[1])


def hand(*ss):
    return [card(s) for s in ss]


def test_evaluator():
    royal = evaluate(hand("As", "Ks", "Qs", "Js", "Ts", "2c", "3d"))
    assert royal[0] == 8 and royal[1] == 12, royal

    wheel = evaluate(hand("Ah", "2s", "3c", "4d", "5h", "9c", "Kd"))
    assert wheel[0] == 4 and wheel[1] == 3, wheel

    quads = evaluate(hand("9c", "9d", "9h", "9s", "Ac", "2c", "3c"))
    assert quads[0] == 7 and quads[1] == 7 and quads[2] == 12, quads

    boat = evaluate(hand("Kc", "Kd", "Kh", "2s", "2c", "7c", "8c"))
    assert boat[0] == 6 and boat[1] == 11 and boat[2] == 0, boat

    flush = evaluate(hand("Ac", "Jc", "9c", "5c", "2c", "Kd", "Kh"))
    assert flush[0] == 5, flush

    two_pair = evaluate(hand("Ac", "Ad", "Kc", "Kd", "2h", "3h", "5s"))
    assert two_pair[0] == 2 and two_pair[1] == 12 and two_pair[2] == 11, two_pair

    # pair vs pair kicker
    a = evaluate(hand("Ac", "Kd", "7h", "7s", "2c", "9d", "Jh"))
    b = evaluate(hand("Qc", "Kd", "7h", "7s", "2c", "9d", "Jh"))
    assert a > b

    # straight beats trips
    st = evaluate(hand("6c", "7d", "8h", "9s", "Tc", "2c", "2d"))
    tr = evaluate(hand("6c", "6d", "6h", "9s", "Tc", "2c", "Kd"))
    assert st > tr

    # 5-card and 6-card inputs work
    assert evaluate(hand("Ac", "Ad", "2h", "3s", "4c"))[0] == 1
    assert evaluate(hand("Ac", "Ad", "Ah", "3s", "4c", "3d"))[0] == 6
    print("evaluator: OK")


def test_tournament_conservation():
    for seed in range(5):
        rng = random.Random(seed)
        seats = list(ROSTER.keys())
        rng.shuffle(seats)
        strategies = {p: ROSTER[p](p, random.Random(seed * 100 + p))
                      for p in seats}
        t = Tournament(seats, strategies, 1000, rng)
        winner, order, hands = t.run()
        total = sum(t.stacks.values())
        assert total == 6000, f"chips leaked: {total}"
        assert t.stacks[winner] == 6000, (winner, t.stacks)
        assert sorted(order) == sorted(seats)
        assert order[0] == winner
    print("tournament chip conservation: OK")


if __name__ == "__main__":
    test_evaluator()
    test_tournament_conservation()
    print("all checks passed")
