"""Cards, deck and a fast 7-card hand evaluator for Texas Hold'em.

A card is a tuple ``(rank, suit)`` with rank 2..14 (14 = Ace) and suit 0..3.
``evaluate`` accepts 5, 6 or 7 cards and returns a comparable tuple:
bigger tuple == better hand.
"""

from collections import Counter

RANKS = list(range(2, 15))
SUITS = list(range(4))
RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_NAMES = "shdc"

# Hand categories (first element of the evaluation tuple)
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

CATEGORY_NAMES = [
    "high card", "pair", "two pair", "trips", "straight",
    "flush", "full house", "quads", "straight flush",
]


def new_deck():
    return [(r, s) for r in RANKS for s in SUITS]


def card_str(card):
    r, s = card
    return f"{RANK_NAMES.get(r, str(r))}{SUIT_NAMES[s]}"


def _straight_high(rank_set):
    """Highest straight top-card in a set of ranks, or None (handles the wheel)."""
    rs = set(rank_set)
    if 14 in rs:
        rs.add(1)
    for high in range(14, 4, -1):
        if all(r in rs for r in range(high - 4, high + 1)):
            return high
    return None


def evaluate(cards):
    """Best 5-card hand value from 5-7 cards, as a comparable tuple."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    rank_counts = Counter(ranks)
    suit_counts = Counter(c[1] for c in cards)

    flush_suit = None
    for s, n in suit_counts.items():
        if n >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        flush_ranks = [c[0] for c in cards if c[1] == flush_suit]
        sf_high = _straight_high(flush_ranks)
        if sf_high is not None:
            return (STRAIGHT_FLUSH, sf_high)

    # groups sorted by (count desc, rank desc)
    groups = sorted(rank_counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in rank_counts if r != quad)
        return (QUADS, quad, kicker)

    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (FULL_HOUSE, groups[0][0], groups[1][0])

    if flush_suit is not None:
        top5 = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)[:5]
        return (FLUSH, *top5)

    st_high = _straight_high(rank_counts.keys())
    if st_high is not None:
        return (STRAIGHT, st_high)

    if groups[0][1] == 3:
        trip = groups[0][0]
        kickers = sorted((r for r in rank_counts if r != trip), reverse=True)[:2]
        return (TRIPS, trip, *kickers)

    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        p_hi, p_lo = groups[0][0], groups[1][0]
        kicker = max(r for r in rank_counts if r not in (p_hi, p_lo))
        return (TWO_PAIR, p_hi, p_lo, kicker)

    if groups[0][1] == 2:
        pair = groups[0][0]
        kickers = sorted((r for r in rank_counts if r != pair), reverse=True)[:3]
        return (PAIR, pair, *kickers)

    return (HIGH_CARD, *ranks[:5])


def estimate_equity(hole, board, n_opponents, rng, iters=60):
    """Monte Carlo equity of ``hole`` vs ``n_opponents`` random hands."""
    known = set(hole) | set(board)
    deck = [c for c in new_deck() if c not in known]
    need_board = 5 - len(board)
    score = 0.0
    for _ in range(iters):
        drawn = rng.sample(deck, need_board + 2 * n_opponents)
        full_board = list(board) + drawn[:need_board]
        mine = evaluate(list(hole) + full_board)
        best_opp = None
        for i in range(n_opponents):
            oh = drawn[need_board + 2 * i: need_board + 2 * i + 2]
            v = evaluate(oh + full_board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters
