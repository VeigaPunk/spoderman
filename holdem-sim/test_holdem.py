#!/usr/bin/env python3
"""Sanity tests for the evaluator, equity, and engine. Run: python3 test_holdem.py"""

import random

from holdem.cards import make
from holdem.evaluator import evaluate7
from holdem.equity import estimate_equity, chen_score
from holdem.engine import Tournament, Player
from holdem.strategies import default_lineup, AllInAndy


def cards(*specs):
    return [make(s[0], s[1]) for s in specs]


def test_evaluator():
    royal = evaluate7(cards("As", "Ks", "Qs", "Js", "Ts", "2c", "3d"))
    quads = evaluate7(cards("9c", "9d", "9h", "9s", "Ac", "2c", "3d"))
    boat = evaluate7(cards("Kc", "Kd", "Kh", "2s", "2c", "7c", "8d"))
    flush = evaluate7(cards("Ah", "Th", "7h", "4h", "2h", "Kc", "Kd"))
    wheel = evaluate7(cards("Ac", "2d", "3h", "4s", "5c", "Kc", "Kd"))
    trips = evaluate7(cards("Qc", "Qd", "Qh", "9s", "7c", "4c", "2d"))
    twop = evaluate7(cards("Jc", "Jd", "8h", "8s", "Ac", "4c", "2d"))
    pair = evaluate7(cards("Tc", "Td", "Ah", "8s", "6c", "4c", "2d"))
    high = evaluate7(cards("Ac", "Jd", "9h", "7s", "5c", "4c", "2d"))
    order = [royal, quads, boat, flush, wheel, trips, twop, pair, high]
    assert order == sorted(order, reverse=True), order
    assert royal[0] == 8 and quads[0] == 7 and boat[0] == 6 and flush[0] == 5
    assert wheel == (4, 3)  # five-high straight

    # kicker matters
    a = evaluate7(cards("Tc", "Td", "Ah", "8s", "6c", "4c", "2d"))
    b = evaluate7(cards("Th", "Ts", "Kh", "8d", "6h", "4d", "2h"))
    assert a > b

    # identical boards split
    board = cards("Ac", "Kd", "Qh", "Js", "Tc")
    assert evaluate7(cards("2c", "3d") + board) == evaluate7(cards("4h", "5s") + board)
    print("evaluator ok")


def test_equity():
    rng = random.Random(1)
    aa = cards("As", "Ac")
    e = estimate_equity(aa, [], 1, 600, rng)
    assert 0.80 < e < 0.90, e  # AA vs one random hand ~85%
    e72 = estimate_equity(cards("7c", "2d"), [], 1, 600, rng)
    assert 0.28 < e72 < 0.42, e72
    assert chen_score(aa) == 20
    assert chen_score(cards("Kh", "Ks")) == 16
    print("equity ok")


def test_side_pots():
    """3 players: short stack all-in wins main pot only."""
    lineup = [AllInAndy(random.Random(i)) for i in range(3)]
    t = Tournament(lineup, rng=random.Random(0), starting_stack=100)
    a, b, c = t.players
    a.stack, b.stack, c.stack = 0, 0, 0
    a.contributed, b.contributed, c.contributed = 100, 300, 300
    a.hole = cards("As", "Ac")           # wins overall
    b.hole = cards("Ks", "Kc")
    c.hole = cards("2s", "7c")
    board = cards("3d", "8h", "Jc", "Qd", "4s")
    t._settle([a, b, c], board)
    assert a.stack == 300, a.stack       # main pot only: 3 x 100
    assert b.stack == 400, b.stack       # side pot: 2 x 200
    assert c.stack == 0, c.stack
    print("side pots ok")


def test_chip_conservation_and_termination():
    for i in range(5):
        master = random.Random(i)
        lineup = default_lineup(lambda: random.Random(master.random()))
        t = Tournament(lineup, rng=master, starting_stack=1000)
        winner = t.run()
        total = sum(p.stack for p in t.players)
        assert total == 6000, total
        wp = next(p for p in t.players if p.seat == winner)
        assert wp.stack == 6000, (winner, wp.stack)
        assert len(t.elimination_order) == 6
        assert t.elimination_order[-1] == winner
    print("engine ok (chips conserved, tournaments terminate)")


if __name__ == "__main__":
    test_evaluator()
    test_equity()
    test_side_pots()
    test_chip_conservation_and_termination()
    print("all tests passed")
