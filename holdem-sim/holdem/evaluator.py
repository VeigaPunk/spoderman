"""7-card hand evaluator. evaluate7 returns a tuple; bigger tuple = better hand.

Category codes: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
3 trips, 2 two pair, 1 pair, 0 high card.

Note: in 7 cards a flush is mutually exclusive with quads/full house, so the
early flush/straight-flush return is safe.
"""

_WHEEL_MASK = (1 << 12) | 0b1111  # A,5,4,3,2 -> rank bits 12,3,2,1,0


def _straight_high(mask: int) -> int:
    for hi in range(12, 3, -1):
        window = 0b11111 << (hi - 4)
        if mask & window == window:
            return hi
    if mask & _WHEEL_MASK == _WHEEL_MASK:
        return 3  # five-high straight
    return -1


def evaluate7(cards):
    rc = [0] * 13
    sc = [0] * 4
    for c in cards:
        rc[c >> 2] += 1
        sc[c & 3] += 1

    for s in range(4):
        if sc[s] >= 5:
            fmask = 0
            for c in cards:
                if c & 3 == s:
                    fmask |= 1 << (c >> 2)
            hi = _straight_high(fmask)
            if hi >= 0:
                return (8, hi)
            top = []
            for r in range(12, -1, -1):
                if fmask >> r & 1:
                    top.append(r)
                    if len(top) == 5:
                        break
            return (5, top[0], top[1], top[2], top[3], top[4])

    quads = -1
    trips = -1
    pairs = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n == 4:
            quads = r
        elif n == 3:
            if trips < 0:
                trips = r
            else:
                pairs.append(r)  # second set of trips plays as a pair
        elif n == 2:
            pairs.append(r)

    if quads >= 0:
        kick = max(r for r in range(13) if rc[r] and r != quads)
        return (7, quads, kick)
    if trips >= 0 and pairs:
        return (6, trips, pairs[0])

    mask = 0
    for r in range(13):
        if rc[r]:
            mask |= 1 << r
    hi = _straight_high(mask)
    if hi >= 0:
        return (4, hi)

    if trips >= 0:
        kick = [r for r in range(12, -1, -1) if rc[r] == 1][:2]
        return (3, trips, kick[0], kick[1])
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick = max(r for r in range(13) if rc[r] and r != p1 and r != p2)
        return (2, p1, p2, kick)
    if len(pairs) == 1:
        kick = [r for r in range(12, -1, -1) if rc[r] == 1][:3]
        return (1, pairs[0], kick[0], kick[1], kick[2])

    top = [r for r in range(12, -1, -1) if rc[r]][:5]
    return (0, top[0], top[1], top[2], top[3], top[4])
