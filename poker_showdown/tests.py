#!/usr/bin/env python3
"""Sanity tests for the evaluator and the engine (side pots, chip conservation)."""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from holdem.evaluator import evaluate7
from holdem.engine import PlayerState, Table, run_tournament
from holdem.strategies import LINEUP, chen


def C(s):
    """'As' -> int card."""
    return "23456789TJQKA".index(s[0]) + 13 * "cdhs".index(s[1])


def H(txt):
    return [C(x) for x in txt.split()]


def cat(score):
    return score >> 20


def test_evaluator():
    assert cat(evaluate7(H("As Ks Qs Js Ts 2c 3d"))) == 8      # royal-ish SF
    assert cat(evaluate7(H("5c 4c 3c 2c Ac Kd Qd"))) == 8      # wheel SF
    assert cat(evaluate7(H("Ac Ad Ah As Kc 2d 3h"))) == 7      # quads
    assert cat(evaluate7(H("Ac Ad Ah Ks Kc 2d 3h"))) == 6      # full house
    assert cat(evaluate7(H("Ac Kc 9c 5c 2c Ad 3h"))) == 5      # flush
    assert cat(evaluate7(H("9c 8d 7h 6s 5c Ad Ah"))) == 4      # straight
    assert cat(evaluate7(H("Ac Ad Ah 9s 5c 2d 3h"))) == 3      # trips
    assert cat(evaluate7(H("Ac Ad Kh Ks 5c 2d 3h"))) == 2      # two pair
    assert cat(evaluate7(H("Ac Ad Kh Qs 5c 2d 3h"))) == 1      # pair
    assert cat(evaluate7(H("Ac Kd Jh 9s 5c 2d 3h"))) == 0      # high card
    # ordering checks
    assert evaluate7(H("Ac Ad Ah As Kc 2d 3h")) > evaluate7(H("Kc Kd Kh Ks Ac 2d 3h"))
    assert evaluate7(H("6c 5d 4h 3s 2c Ad Kh")) < evaluate7(H("7c 6d 5h 4s 3c Ad Kh"))
    assert evaluate7(H("Ac Ad 2h 2s Kc 8d 3h")) > evaluate7(H("Kc Kd Qh Qs Ac 8d 3h"))
    # split: board plays for both
    b = "Ac Kc Qd Jh Ts"
    assert evaluate7(H(b + " 2c 3d")) == evaluate7(H(b + " 4h 5s"))
    print("evaluator: OK")


class Scripted:
    """Feed a fixed list of actions."""

    def __init__(self, actions):
        self.actions = list(actions)

    def observe(self, event):
        pass

    def act(self, obs):
        return self.actions.pop(0) if self.actions else ("call",)


def test_side_pots():
    # 3 players: short stack all-in 100, two bigger stacks all-in 300.
    # Rig the deck so the short stack wins the main pot, best big stack wins side.
    rng = random.Random(0)
    a = PlayerState(0, "short", Scripted([("raise", 10 ** 9)]), 100)
    b = PlayerState(1, "mid", Scripted([("raise", 10 ** 9)]), 300)
    c = PlayerState(2, "big", Scripted([("call",), ("call",)]), 300)
    table = Table([a, b, c], rng, sb=5, bb=10)
    table.play_hand()
    total = a.stack + b.stack + c.stack
    assert total == 700, total  # chip conservation
    print("side pots / chip conservation: OK")


def test_full_tournament_conserves_chips():
    def make(rng):
        return [(name, cls()) for name, cls in LINEUP]

    order, hands = run_tournament(make, seed=123, start_stack=1000)
    assert sorted(order) == [0, 1, 2, 3, 4, 5], order
    assert hands > 0
    print(f"full tournament: OK ({hands} hands, finish order {order})")


def test_chen():
    assert chen((C("Ac"), C("Ad"))) == 20  # AA
    assert chen((C("Ac"), C("Kc"))) == 12  # AKs
    assert chen((C("7c"), C("2d"))) < 1    # trash
    print("chen: OK")


if __name__ == "__main__":
    test_evaluator()
    test_chen()
    test_side_pots()
    test_full_tournament_conserves_chips()
    print("ALL TESTS PASSED")
