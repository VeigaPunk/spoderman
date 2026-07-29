"""Cards, a fast 7-card hand evaluator, and a Monte-Carlo equity estimator.

Cards are ints 0..51: rank = 2 + card // 4 (2..14, ace high), suit = card % 4.
"""

from collections import Counter

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "shdc"


def card_rank(card):
    return 2 + card // 4


def card_suit(card):
    return card % 4


def card_str(card):
    return RANK_CHARS[card // 4] + SUIT_CHARS[card % 4]


def _straight_high(desc_unique_ranks):
    """Highest straight top-rank in a descending list of unique ranks, else 0."""
    run = 1
    for i in range(1, len(desc_unique_ranks)):
        if desc_unique_ranks[i] == desc_unique_ranks[i - 1] - 1:
            run += 1
            if run == 5:
                return desc_unique_ranks[i] + 4
        else:
            run = 1
    # wheel: A-5-4-3-2
    s = set(desc_unique_ranks)
    if {14, 5, 4, 3, 2} <= s:
        return 5
    return 0


# Hand categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
# 4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
def evaluate7(cards):
    """Return a comparable score tuple for the best 5-card hand out of 7 cards."""
    ranks = [2 + c // 4 for c in cards]

    suit_counts = [0, 0, 0, 0]
    for c in cards:
        suit_counts[c % 4] += 1
    for s in range(4):
        if suit_counts[s] >= 5:
            flush_ranks = sorted({2 + c // 4 for c in cards if c % 4 == s}, reverse=True)
            sf = _straight_high(flush_ranks)
            if sf:
                return (8, sf)
            return (5,) + tuple(flush_ranks[:5])

    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    uniq = sorted(counts, reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in uniq if r != quad)
        return (7, quad, kicker)
    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    st = _straight_high(uniq)
    if st:
        return (4, st)
    if groups[0][1] == 3:
        t = groups[0][0]
        k = [r for r in uniq if r != t]
        return (3, t, k[0], k[1])
    if groups[0][1] == 2 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kicker = max(r for r in uniq if r != hp and r != lp)
        return (2, hp, lp, kicker)
    if groups[0][1] == 2:
        p = groups[0][0]
        k = [r for r in uniq if r != p]
        return (1, p, k[0], k[1], k[2])
    return (0,) + tuple(uniq[:5])


def estimate_equity(hole, board, n_opponents, rng, samples=30):
    """Monte-Carlo equity of `hole` on `board` vs `n_opponents` random hands.

    Returns win probability in [0, 1]; ties count as split equity.
    """
    n_opponents = max(1, min(n_opponents, 5))
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(board)
    total = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, n_opponents * 2 + need_board)
        full_board = list(board) + draw[:need_board]
        my_score = evaluate7(list(hole) + full_board)
        best_opp = None
        idx = need_board
        for _o in range(n_opponents):
            opp = evaluate7(draw[idx:idx + 2] + full_board)
            idx += 2
            if best_opp is None or opp > best_opp:
                best_opp = opp
        if my_score > best_opp:
            total += 1.0
        elif my_score == best_opp:
            total += 0.5
    return total / samples


def preflop_strength(hole):
    """Chen-formula-ish preflop score, normalized to roughly [0, 1]."""
    r1, r2 = sorted((card_rank(hole[0]), card_rank(hole[1])), reverse=True)
    suited = card_suit(hole[0]) == card_suit(hole[1])
    high_points = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}
    score = high_points.get(r1, r1 / 2.0)
    if r1 == r2:
        score = max(5.0, score * 2.0)
    gap = r1 - r2
    if r1 != r2:
        score -= {1: 0.0, 2: 1.0, 3: 2.0, 4: 4.0}.get(gap, 5.0)
        if gap <= 2 and r1 < 12:
            score += 1.0  # connector bonus
    if suited:
        score += 2.0
    return max(0.0, min(1.0, score / 20.0))
