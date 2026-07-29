"""Cards and hand evaluation for Texas Hold'em.

Cards are ints 0..51: rank = (c >> 2) + 2  (2..14, ace high), suit = c & 3.
Hand ranks are tuples that compare correctly with < / > / ==.
"""
from collections import Counter
from functools import lru_cache
from itertools import combinations

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"


def rank_of(c):
    return (c >> 2) + 2


def suit_of(c):
    return c & 3


def card_str(c):
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


@lru_cache(maxsize=400_000)
def eval5(cards):
    """Rank a 5-card hand. Higher tuple = better hand.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    rs = sorted(((c >> 2) + 2 for c in cards), reverse=True)
    flush = len({c & 3 for c in cards}) == 1
    uniq = sorted(set(rs), reverse=True)
    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:  # the wheel
            straight_high = 5
    if straight_high and flush:
        return (8, straight_high)
    groups = sorted(Counter(rs).items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *rs)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        return (3, groups[0][0], *(r for r in rs if r != groups[0][0]))
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return (1, groups[0][0], *(r for r in rs if r != groups[0][0]))
    return (0, *rs)


@lru_cache(maxsize=250_000)
def _best_sorted(cards):
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(combo) for combo in combinations(cards, 5))


def best_hand(cards):
    """Best 5-card rank from 5, 6 or 7 cards."""
    return _best_sorted(tuple(sorted(cards)))


def mc_equity(hole, board, n_opponents, rng, samples=32):
    """Monte Carlo equity of `hole` on `board` vs n random opponent hands."""
    n_opponents = max(1, n_opponents)
    known = set(hole) | set(board)
    deck = [c for c in range(52) if c not in known]
    need = 5 - len(board)
    hole = tuple(hole)
    board = tuple(board)
    wins = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, 2 * n_opponents + need)
        full_board = board + tuple(draw[:need])
        mine = best_hand(hole + full_board)
        idx = need
        best_opp = None
        for _o in range(n_opponents):
            opp = best_hand((draw[idx], draw[idx + 1]) + full_board)
            idx += 2
            if best_opp is None or opp > best_opp:
                best_opp = opp
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / samples


def chen_score(hole):
    """Chen formula for preflop hand strength (AA=20, AKs=12, 72o≈-1)."""
    a, b = hole
    ra, rb = (a >> 2) + 2, (b >> 2) + 2
    hi, lo = max(ra, rb), min(ra, rb)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if hi == lo:
        return max(pts * 2, 5.0)
    if (a & 3) == (b & 3):
        pts += 2
    gap = hi - lo - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        pts += 1
    return round(pts)
