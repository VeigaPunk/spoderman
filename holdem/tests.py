"""Self-checks. Run with: python -m holdem.tests"""

import random
import sys

from .cards import evaluate, parse_card, CATEGORY_NAMES, FULL_DECK, card_str
from .engine import Table
from .strategies import build_agents

FAILURES = []


def check(condition, label):
    if condition:
        print("  ok   %s" % label)
    else:
        print("  FAIL %s" % label)
        FAILURES.append(label)


def hand(text):
    return [parse_card(t) for t in text.split()]


def test_deck():
    print("deck integrity")
    check(len(FULL_DECK) == 52, "52 cards")
    check(len(set(FULL_DECK)) == 52, "all distinct")
    ranks = sorted({c >> 2 for c in FULL_DECK})
    suits = sorted({c & 3 for c in FULL_DECK})
    check(ranks == list(range(2, 15)), "ranks are exactly 2..14, got %r" % ranks)
    check(suits == [0, 1, 2, 3], "four suits")
    counts = {r: sum(1 for c in FULL_DECK if c >> 2 == r) for r in ranks}
    check(set(counts.values()) == {4}, "four cards of every rank")
    # Round trip through the text form.
    check(all(parse_card(card_str(c)) == c for c in FULL_DECK),
          "card_str/parse_card round trip")
    # Every dealt hand must be evaluable; ints below MIN_CARD are not cards.
    rng = random.Random(7)
    ok = True
    for _ in range(3000):
        try:
            evaluate(rng.sample(FULL_DECK, 7))
        except Exception as ex:
            ok = False
            print("     %r" % ex)
            break
    check(ok, "3000 random 7-card deals all evaluate")


def test_evaluator():
    print("hand evaluator")
    cases = [
        ("As Ks Qs Js Ts 2h 3d", 8, "royal flush"),
        ("9s 8s 7s 6s 5s Ah Ad", 8, "straight flush beats trip aces present"),
        ("5s 4s 3s 2s As Kh Qd", 8, "steel wheel straight flush"),
        ("7c 7d 7h 7s 2c 3d 4h", 7, "quads"),
        ("8c 8d 8h 3s 3c 4h 5d", 6, "full house"),
        ("Ah Kh 9h 5h 2h 3c 4d", 5, "flush"),
        ("Ah 2d 3c 4s 5h Kd Qc", 4, "wheel straight"),
        ("Th Jd Qc Ks 9h 2d 3c", 4, "broadway-ish straight"),
        ("9c 9d 9h 2s 4c 7h Kd", 3, "trips"),
        ("Ac Ad 7h 7s 2c 4d 9h", 2, "two pair"),
        ("Ac Ad 7h 9s 2c 4d Ts", 1, "one pair"),
        ("Ac Kd 9h 7s 5c 3d 2h", 0, "high card"),
    ]
    for text, expected, label in cases:
        cat = evaluate(hand(text))[0]
        check(cat == expected,
              "%s -> %s" % (label, CATEGORY_NAMES[cat]))

    # Ordering.
    check(evaluate(hand("As Ks Qs Js Ts 2h 3d")) >
          evaluate(hand("9s 8s 7s 6s 5s Ah Ad")), "royal > lower str8 flush")
    check(evaluate(hand("7c 7d 7h 7s 2c 3d 4h")) >
          evaluate(hand("8c 8d 8h 3s 3c 4h 5d")), "quads > boat")
    check(evaluate(hand("8c 8d 8h 3s 3c 4h 5d")) >
          evaluate(hand("Ah Kh 9h 5h 2h 3c 4d")), "boat > flush")
    check(evaluate(hand("Ah Kh 9h 5h 2h 3c 4d")) >
          evaluate(hand("Ah 2d 3c 4s 5h Kd Qc")), "flush > straight")
    # Two sets make a full house using the higher set as the trips.
    boat = evaluate(hand("9c 9d 9h 8s 8c 8d 2h"))
    check(boat[0] == 6 and boat[1] == (9, 8), "two sets -> 999 over 88")
    # Kicker resolution.
    check(evaluate(hand("Ac Ad Kh 9s 2c 4d 7h")) >
          evaluate(hand("Ac Ad Qh 9s 2c 4d 7h")), "pair kicker matters")
    # A 5-high straight must not be read as ace-high.
    wheel = evaluate(hand("Ah 2d 3c 4s 5h Kd Qc"))
    check(wheel == (4, (5,)), "wheel is 5-high, not ace-high")


def test_chip_conservation():
    print("engine: chip conservation and termination")
    total_start = 6 * 10000
    ok_chips = True
    ok_finish = True
    ok_winner = True
    for seed in range(25):
        table = Table(build_agents(), starting_chips=10000, seed=seed,
                      max_hands=1500)
        winner = table.run()
        total = sum(s.chips for s in table.seats)
        if total != total_start:
            ok_chips = False
            print("     seed %d: chips %d != %d" % (seed, total, total_start))
        if sorted(table.finish_order) != [1, 2, 3, 4, 5, 6]:
            ok_finish = False
            print("     seed %d: finish order %r" % (seed, table.finish_order))
        if not table.hit_hand_cap:
            survivors = [s for s in table.seats if s.chips > 0]
            if len(survivors) != 1 or survivors[0].player_id != winner:
                ok_winner = False
                print("     seed %d: winner mismatch" % seed)
    check(ok_chips, "no chips created or destroyed over 25 tournaments")
    check(ok_finish, "every player is ranked exactly once")
    check(ok_winner, "declared winner holds all the chips")


def test_side_pots():
    print("engine: side pot construction")
    from .engine import Seat

    table = Table(build_agents(), starting_chips=10000, seed=1)
    seats = [Seat(i + 1, None, 0) for i in range(3)]
    seats[0].committed, seats[0].in_hand = 1000, True   # short all-in
    seats[1].committed, seats[1].in_hand = 5000, True
    seats[2].committed, seats[2].in_hand = 5000, True
    pots = table._build_pots(seats)
    amounts = [amount for amount, _ in pots]
    check(amounts == [3000, 8000], "main 3000 + side 8000, got %r" % amounts)
    check(len(pots[0][1]) == 3 and len(pots[1][1]) == 2,
          "eligibility 3 then 2")

    # An uncalled overbet must come straight back as a one-player side pot.
    seats = [Seat(1, None, 0), Seat(2, None, 0)]
    seats[0].committed, seats[0].in_hand = 9000, True
    seats[1].committed, seats[1].in_hand = 2500, True
    pots = table._build_pots(seats)
    check([a for a, _ in pots] == [5000, 6500], "uncalled remainder isolated")
    check(len(pots[1][1]) == 1 and pots[1][1][0].player_id == 1,
          "remainder returns to the overbettor")


def test_all_in_bot_is_simple():
    print("agents: seat 1 really does only one thing")
    from .strategies import MadRabbit
    from .engine import Observation, SeatView, RAISE

    bot = MadRabbit()
    rng = random.Random(0)
    saw = set()
    for to_call in (0, 50, 4000):
        for street in range(4):
            obs = Observation(
                player_id=1, hole=(56, 33), board=(), street=street, pot=300,
                to_call=to_call, min_raise_to=100, max_raise_to=7777,
                chips=7777, street_bet=0, committed=0, big_blind=50,
                small_blind=25, ante=0,
                seats=(SeatView(1, 7777, 0, 0, True, False),), button=0,
                seat_index=0, actors_after=1, num_in_hand=2, action_log=(),
                hand_number=0, starting_stacks={1: 7777})
            saw.add(bot.act(obs, rng))
    check(saw == {(RAISE, 7777)}, "always (RAISE, entire stack): %r" % saw)


def test_no_strategy_leakage():
    print("fairness: observations carry no opponent cards or identities")
    from .engine import Observation
    fields = set(Observation._fields)
    check("hole" in fields, "observation includes own hole cards")
    banned = {"strategies", "opponent_hole", "strategy", "agents"}
    check(not (fields & banned), "observation exposes no strategy handles")
    # SeatView must not carry cards.
    from .engine import SeatView
    check("hole" not in SeatView._fields,
          "public seat view has no hole cards")


def main():
    test_deck()
    test_evaluator()
    test_chip_conservation()
    test_side_pots()
    test_all_in_bot_is_simple()
    test_no_strategy_leakage()
    print("")
    if FAILURES:
        print("%d FAILURE(S): %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
