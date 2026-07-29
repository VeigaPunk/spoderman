"""Cards, deck utilities and a 5/7-card poker hand evaluator.

Cards are ints 0..51: rank = card % 13 (0 = deuce ... 12 = ace),
suit = card // 13.
"""

from itertools import combinations

RANK_NAMES = "23456789TJQKA"
SUIT_NAMES = "shdc"


def card_str(c: int) -> str:
    return RANK_NAMES[c % 13] + SUIT_NAMES[c // 13]


def eval5(cards):
    """Score a 5-card hand. Returns a comparable tuple (higher = better).

    Category: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = sorted((c % 13 for c in cards), reverse=True)
    suits = [c // 13 for c in cards]
    is_flush = suits[0] == suits[1] == suits[2] == suits[3] == suits[4]

    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    # groups sorted by (count desc, rank desc)
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    straight_high = -1
    if len(counts) == 5:
        if ranks[0] - ranks[4] == 4:
            straight_high = ranks[0]
        elif ranks == [12, 3, 2, 1, 0]:  # wheel A-5
            straight_high = 3

    if straight_high >= 0 and is_flush:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if is_flush:
        return (5, *ranks)
    if straight_high >= 0:
        return (4, straight_high)
    if groups[0][1] == 3:
        return (3, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return (1, groups[0][0], groups[1][0], groups[2][0], groups[3][0])
    return (0, *ranks)


def best7(cards):
    """Best 5-card score from 5, 6 or 7 cards."""
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(c) for c in combinations(cards, 5))


def equity_estimate(hole, board, n_opps, rng, iters=48):
    """Monte Carlo equity of `hole` on `board` vs n_opps random hands.

    Ties are credited proportionally to a split.
    """
    if n_opps <= 0:
        return 1.0
    dead = set(hole) | set(board)
    stub = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    need = need_board + 2 * n_opps
    total = 0.0
    for _ in range(iters):
        draw = rng.sample(stub, need)
        sim_board = list(board) + draw[:need_board]
        mine = best7(list(hole) + sim_board)
        ties = 1  # count myself among the split
        lost = False
        for i in range(n_opps):
            opp = draw[need_board + 2 * i: need_board + 2 * i + 2]
            score = best7(opp + sim_board)
            if score > mine:
                lost = True
                break
            if score == mine:
                ties += 1
        if not lost:
            total += 1.0 / ties
    return total / iters


def chen_score(hole):
    """Chen formula preflop hand strength (roughly -1 .. 20)."""
    r1, r2 = sorted((c % 13 for c in hole), reverse=True)
    suited = hole[0] // 13 == hole[1] // 13

    def high_card_value(r):
        return {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r, (r + 2) / 2.0)

    score = high_card_value(r1)
    if r1 == r2:
        return max(5.0, score * 2)
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # small connected cards can make straights
        score += 1
    return score
