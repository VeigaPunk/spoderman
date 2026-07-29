"""Cards, deck and 5/6/7-card hand evaluation for Texas Hold'em.

A card is a tuple ``(rank, suit)`` with rank 2..14 (14 = Ace) and suit 0..3.
Hand values are tuples ordered so that Python tuple comparison ranks hands
correctly: ``(category, tiebreaker, ...)`` with category 0 = high card up to
8 = straight flush.
"""

from collections import Counter
from itertools import combinations

RANK_CHARS = {r: c for r, c in zip(range(2, 15), "23456789TJQKA")}
SUIT_CHARS = "cdhs"


def new_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


def card_str(card):
    return RANK_CHARS[card[0]] + SUIT_CHARS[card[1]]


def eval5(cards):
    """Evaluate exactly 5 cards. Returns a comparable tuple."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda kv: (-kv[1], -kv[0]))
    uniq = sorted(cnt, reverse=True)

    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:  # wheel
            straight_high = 5

    if straight_high and flush:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4])
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        return (3, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return (1, groups[0][0], groups[1][0], groups[2][0], groups[3][0])
    return (0, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4])


def best_hand(cards):
    """Best 5-card value from 5, 6 or 7 cards."""
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(c) for c in combinations(cards, 5))


def equity_vs_random(hole, board, n_opponents, rng, rollouts=40):
    """Monte Carlo equity of ``hole`` on ``board`` against ``n_opponents``
    uniformly random hands, with random runouts. Ties count as split wins."""
    used = set(hole) | set(board)
    deck = [c for c in new_deck() if c not in used]
    missing = 5 - len(board)
    need = 2 * n_opponents + missing
    score = 0.0
    for _ in range(rollouts):
        drawn = rng.sample(deck, need)
        runout = board + drawn[:missing]
        my_val = best_hand(list(hole) + runout)
        best_opp = None
        for i in range(n_opponents):
            opp = drawn[missing + 2 * i: missing + 2 * i + 2]
            v = best_hand(opp + runout)
            if best_opp is None or v > best_opp:
                best_opp = v
        if my_val > best_opp:
            score += 1.0
        elif my_val == best_opp:
            score += 0.5
    return score / rollouts
