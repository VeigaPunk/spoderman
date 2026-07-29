"""7-card Texas Hold'em hand evaluator.

Cards are tuples (rank, suit) with rank in 2..14 (14 = Ace) and suit in 0..3.
evaluate() accepts 5, 6 or 7 cards and returns a tuple that compares correctly:
bigger tuple == better hand.

Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
3 trips, 2 two pair, 1 pair, 0 high card.
"""

RANK_NAMES = {2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 7: '7', 8: '8',
              9: '9', 10: 'T', 11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
SUIT_NAMES = {0: 's', 1: 'h', 2: 'd', 3: 'c'}


def card_str(card):
    return RANK_NAMES[card[0]] + SUIT_NAMES[card[1]]


def _straight_high(rank_set):
    """Highest straight top-card in rank_set, or None. Ace plays low too."""
    ranks = set(rank_set)
    if 14 in ranks:
        ranks.add(1)
    for high in range(14, 4, -1):
        if all((high - i) in ranks for i in range(5)):
            return high
    return None


def evaluate(cards):
    ranks = [c[0] for c in cards]
    rank_count = {}
    for r in ranks:
        rank_count[r] = rank_count.get(r, 0) + 1
    suit_count = [0, 0, 0, 0]
    for _, s in cards:
        suit_count[s] += 1
    flush_suit = None
    for s in range(4):
        if suit_count[s] >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        flush_ranks = [r for r, s in cards if s == flush_suit]
        sf = _straight_high(flush_ranks)
        if sf is not None:
            return (8, sf)

    groups = sorted(rank_count.items(), key=lambda kv: (-kv[1], -kv[0]))
    counts = [g[1] for g in groups]

    if counts[0] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if counts[0] == 3 and len(counts) > 1 and counts[1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_suit is not None:
        top5 = sorted((r for r, s in cards if s == flush_suit), reverse=True)[:5]
        return (5,) + tuple(top5)

    st = _straight_high(ranks)
    if st is not None:
        return (4, st)

    if counts[0] == 3:
        trips = groups[0][0]
        kickers = sorted((r for r in ranks if r != trips), reverse=True)[:2]
        return (3, trips) + tuple(kickers)

    if counts[0] == 2 and len(counts) > 1 and counts[1] == 2:
        hi_pair, lo_pair = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hi_pair and r != lo_pair)
        return (2, hi_pair, lo_pair, kicker)

    if counts[0] == 2:
        pair = groups[0][0]
        kickers = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair) + tuple(kickers)

    return (0,) + tuple(sorted(ranks, reverse=True)[:5])


def fresh_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]
