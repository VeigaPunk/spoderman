"""Card primitives and a fast 7-card Texas Hold'em hand evaluator.

Card encoding
-------------
A card is an int in ``[0, 52)``::

    rank = card >> 2      # 0..12  ->  2,3,4,5,6,7,8,9,T,J,Q,K,A
    suit = card & 3       # 0..3   ->  c,d,h,s

Hand scores
-----------
``eval7`` returns a single int.  Bigger is better, and two hands compare
correctly with plain ``<`` / ``==``.  Layout::

    category << 20 | r1 << 16 | r2 << 12 | r3 << 8 | r4 << 4 | r5

Categories: 0 high card, 1 pair, 2 two pair, 3 trips, 4 straight, 5 flush,
6 full house, 7 quads, 8 straight flush.
"""

from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"

HIGH_CARD = 0
PAIR = 1
TWO_PAIR = 2
TRIPS = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
QUADS = 7
STRAIGHT_FLUSH = 8

CATEGORY_NAMES = (
    "high card",
    "pair",
    "two pair",
    "three of a kind",
    "straight",
    "flush",
    "full house",
    "four of a kind",
    "straight flush",
)

DECK = tuple(range(52))


def make_card(rank: int, suit: int) -> int:
    return (rank << 2) | suit


def card_str(card: int) -> str:
    return RANKS[card >> 2] + SUITS[card & 3]


def cards_str(cards) -> str:
    return " ".join(card_str(c) for c in cards)


def parse_card(text: str) -> int:
    text = text.strip()
    return make_card(RANKS.index(text[0].upper()), SUITS.index(text[1].lower()))


def parse_cards(text: str):
    return [parse_card(tok) for tok in text.split()]


# --------------------------------------------------------------------------
# Lookup tables over 13-bit rank masks
# --------------------------------------------------------------------------

_POP = [0] * 8192
for _m in range(8192):
    _POP[_m] = bin(_m).count("1")

# _STRAIGHT[mask] -> rank of the straight's high card, or -1.
# The wheel (A2345) is encoded as high card 3 (a "5"), which is correct: it is
# the weakest straight.
_STRAIGHT = [-1] * 8192
_WHEEL = (1 << 12) | 0b1111  # A,5,4,3,2
for _m in range(8192):
    for _high in range(12, 3, -1):
        _pat = 0b11111 << (_high - 4)
        if _m & _pat == _pat:
            _STRAIGHT[_m] = _high
            break
    else:
        if _m & _WHEEL == _WHEEL:
            _STRAIGHT[_m] = 3

# _TOP5[mask] -> the five highest set ranks packed into five nibbles, always
# left-aligned to nibble 4 so that ``_TOP5[m] >> 4*k`` yields the top ``5-k``
# ranks even when the mask holds fewer than five bits.
_TOP5 = [0] * 8192
for _m in range(8192):
    _v = 0
    _n = 0
    _r = 12
    while _r >= 0 and _n < 5:
        if (_m >> _r) & 1:
            _v = (_v << 4) | _r
            _n += 1
        _r -= 1
    _TOP5[_m] = _v << (4 * (5 - _n))


def eval7(cards) -> int:
    """Score the best 5-card hand out of 5, 6 or 7 cards."""
    cnt = [0] * 13
    s0 = s1 = s2 = s3 = 0
    rmask = 0
    for c in cards:
        r = c >> 2
        cnt[r] += 1
        rmask |= 1 << r
        s = c & 3
        if s == 0:
            s0 |= 1 << r
        elif s == 1:
            s1 |= 1 << r
        elif s == 2:
            s2 |= 1 << r
        else:
            s3 |= 1 << r

    flush_mask = 0
    if _POP[s0] >= 5:
        flush_mask = s0
    elif _POP[s1] >= 5:
        flush_mask = s1
    elif _POP[s2] >= 5:
        flush_mask = s2
    elif _POP[s3] >= 5:
        flush_mask = s3

    if flush_mask:
        sf = _STRAIGHT[flush_mask]
        if sf >= 0:
            return (STRAIGHT_FLUSH << 20) | (sf << 16)

    quad = -1
    trips = []
    pairs = []
    for r in range(12, -1, -1):
        c = cnt[r]
        if c == 4:
            quad = r
        elif c == 3:
            trips.append(r)
        elif c == 2:
            pairs.append(r)

    if quad >= 0:
        kick = _TOP5[rmask & ~(1 << quad)] >> 16
        return (QUADS << 20) | (quad << 16) | (kick << 12)

    if trips and (len(trips) > 1 or pairs):
        top = trips[0]
        second = trips[1] if len(trips) > 1 else -1
        if pairs and pairs[0] > second:
            second = pairs[0]
        return (FULL_HOUSE << 20) | (top << 16) | (second << 12)

    if flush_mask:
        return (FLUSH << 20) | _TOP5[flush_mask]

    st = _STRAIGHT[rmask]
    if st >= 0:
        return (STRAIGHT << 20) | (st << 16)

    if trips:
        top = trips[0]
        kick = _TOP5[rmask & ~(1 << top)] >> 12  # two best kickers
        return (TRIPS << 20) | (top << 16) | (kick << 8)

    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick = _TOP5[rmask & ~(1 << p1) & ~(1 << p2)] >> 16
        return (TWO_PAIR << 20) | (p1 << 16) | (p2 << 12) | (kick << 8)

    if pairs:
        p1 = pairs[0]
        kick = _TOP5[rmask & ~(1 << p1)] >> 8  # three best kickers
        return (PAIR << 20) | (p1 << 16) | (kick << 4)

    return (HIGH_CARD << 20) | _TOP5[rmask]


def category(score: int) -> int:
    return score >> 20


def describe(score: int) -> str:
    cat = score >> 20
    name = CATEGORY_NAMES[cat]
    kick = [(score >> s) & 15 for s in (16, 12, 8, 4, 0)]
    if cat in (STRAIGHT, STRAIGHT_FLUSH):
        return f"{name}, {RANKS[kick[0]]}-high"
    if cat == QUADS:
        return f"{name}, {RANKS[kick[0]]}s"
    if cat == FULL_HOUSE:
        return f"{name}, {RANKS[kick[0]]}s full of {RANKS[kick[1]]}s"
    if cat == TRIPS:
        return f"{name}, {RANKS[kick[0]]}s"
    if cat == TWO_PAIR:
        return f"{name}, {RANKS[kick[0]]}s and {RANKS[kick[1]]}s"
    if cat == PAIR:
        return f"{name} of {RANKS[kick[0]]}s"
    return f"{name}, {RANKS[kick[0]]}-high"
