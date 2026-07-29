"""Cards and a 7-card hand evaluator for Texas Hold'em.

A card is an int 0..51: rank = card >> 2 (0=deuce .. 12=ace), suit = card & 3.
eval7() returns a tuple that compares correctly: higher tuple = better hand.
"""

from collections import Counter

RANKS = "23456789TJQKA"
SUITS = "shdc"


def new_deck():
    return list(range(52))


def card_str(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def hand_str(cards):
    return " ".join(card_str(c) for c in cards)


def _straight_high(rankset):
    """Highest rank completing a 5-card straight, or None. Handles the wheel."""
    for hi in range(12, 2, -1):
        if all((hi - i) in rankset for i in range(5)):
            return hi
    if {12, 0, 1, 2, 3} <= rankset:
        return 3
    return None


def eval7(cards):
    """Evaluate the best 5-card hand out of 7 cards.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = sorted((c >> 2 for c in cards), reverse=True)
    scnt = Counter(c & 3 for c in cards)
    flush_suit = next((s for s, n in scnt.items() if n >= 5), None)

    if flush_suit is not None:
        franks = {c >> 2 for c in cards if (c & 3) == flush_suit}
        sh = _straight_high(franks)
        if sh is not None:
            return (8, sh)

    rc = Counter(ranks)
    groups = sorted(rc.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kick = max(r for r in ranks if r != quad)
        return (7, quad, kick)

    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_suit is not None:
        top5 = sorted((c >> 2 for c in cards if (c & 3) == flush_suit), reverse=True)[:5]
        return (5, tuple(top5))

    sh = _straight_high(set(ranks))
    if sh is not None:
        return (4, sh)

    if groups[0][1] == 3:
        t = groups[0][0]
        kicks = tuple(r for r in ranks if r != t)[:2]
        return (3, t, kicks)

    if groups[0][1] == 2 and groups[1][1] == 2:
        p1, p2 = groups[0][0], groups[1][0]
        kick = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kick)

    if groups[0][1] == 2:
        p = groups[0][0]
        kicks = tuple(r for r in ranks if r != p)[:3]
        return (1, p, kicks)

    return (0, tuple(ranks[:5]))
