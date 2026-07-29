"""Fast 7-card hand evaluator.

evaluate7(cards) returns a single int score; a higher score always beats a
lower one. Encoding: category << 20 | five 4-bit kicker slots (rank values
0..12, most significant kicker first).

Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
3 trips, 2 two pair, 1 one pair, 0 high card.
"""

WHEEL_MASK = 0b1000000001111  # A,5,4,3,2


def _straight_high(mask: int) -> int:
    """Highest straight top-rank in a rank bitmask, or -1."""
    for hi in range(12, 3, -1):
        if (mask >> (hi - 4)) & 0b11111 == 0b11111:
            return hi
    if mask & WHEEL_MASK == WHEEL_MASK:
        return 3  # five-high straight
    return -1


def _pack(ranks) -> int:
    v = 0
    for i in range(5):
        v = (v << 4) | (ranks[i] if i < len(ranks) else 0)
    return v


def evaluate7(cards) -> int:
    rank_count = [0] * 13
    suit_count = [0] * 4
    for c in cards:
        rank_count[c % 13] += 1
        suit_count[c // 13] += 1

    flush_suit = -1
    for s in range(4):
        if suit_count[s] >= 5:
            flush_suit = s
            break

    if flush_suit >= 0:
        fmask = 0
        for c in cards:
            if c // 13 == flush_suit:
                fmask |= 1 << (c % 13)
        sf = _straight_high(fmask)
        if sf >= 0:
            return (8 << 20) | _pack([sf])
        top = []
        for r in range(12, -1, -1):
            if (fmask >> r) & 1:
                top.append(r)
                if len(top) == 5:
                    break
        return (5 << 20) | _pack(top)

    quads = trips = -1
    pairs = []
    rmask = 0
    for r in range(12, -1, -1):
        n = rank_count[r]
        if n:
            rmask |= 1 << r
        if n == 4:
            quads = r
        elif n == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)  # second trips plays as a pair
        elif n == 2:
            pairs.append(r)

    if quads >= 0:
        kicker = max(r for r in range(13) if rank_count[r] and r != quads)
        return (7 << 20) | _pack([quads, kicker])

    if trips >= 0 and pairs:
        return (6 << 20) | _pack([trips, pairs[0]])

    straight = _straight_high(rmask)
    if straight >= 0:
        return (4 << 20) | _pack([straight])

    singles = [r for r in range(12, -1, -1) if rank_count[r] == 1]

    if trips >= 0:
        return (3 << 20) | _pack([trips] + singles[:2])

    if len(pairs) >= 2:
        kicker = max(r for r in range(13) if rank_count[r] and r not in pairs[:2])
        return (2 << 20) | _pack(pairs[:2] + [kicker])

    if len(pairs) == 1:
        return (1 << 20) | _pack(pairs[:1] + singles[:3])

    return _pack(singles[:5])
