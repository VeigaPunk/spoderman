"""Card representation and hand evaluation.

Cards are ints 0..51: rank = c >> 2 (0='2' .. 12='A'), suit = c & 3.
evaluate() accepts 5, 6, or 7 cards and returns a comparable tuple —
higher tuple = better hand.
"""

from collections import Counter

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"


def rank_of(c):
    return c >> 2


def suit_of(c):
    return c & 3


def card_str(c):
    return RANK_CHARS[rank_of(c)] + SUIT_CHARS[suit_of(c)]


def make_deck():
    return list(range(52))


def _straight_high(rank_set):
    rs = set(rank_set)
    if 12 in rs:
        rs.add(-1)  # wheel: A2345
    for high in range(12, 2, -1):
        if all(r in rs for r in range(high - 4, high + 1)):
            return high
    return None


def evaluate(cards):
    """Best 5-card hand from 5-7 cards. Category: 8=straight flush, 7=quads,
    6=full house, 5=flush, 4=straight, 3=trips, 2=two pair, 1=pair, 0=high."""
    ranks = sorted((c >> 2 for c in cards), reverse=True)
    rank_counts = Counter(ranks)

    suit_ranks = {}
    for c in cards:
        suit_ranks.setdefault(c & 3, []).append(c >> 2)
    flush_ranks = None
    for rs in suit_ranks.values():
        if len(rs) >= 5:
            flush_ranks = sorted(rs, reverse=True)
            break

    if flush_ranks:
        sf = _straight_high(flush_ranks)
        if sf is not None:
            return (8, sf)

    groups = sorted(rank_counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_ranks:
        return (5,) + tuple(flush_ranks[:5])

    st = _straight_high(rank_counts.keys())
    if st is not None:
        return (4, st)

    if groups[0][1] == 3:
        t = groups[0][0]
        kick = [r for r in ranks if r != t][:2]
        return (3, t) + tuple(kick)

    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        p1, p2 = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kicker)

    if groups[0][1] == 2:
        p = groups[0][0]
        kick = [r for r in ranks if r != p][:3]
        return (1, p) + tuple(kick)

    return (0,) + tuple(ranks[:5])
