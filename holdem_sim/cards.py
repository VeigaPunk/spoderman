"""Card primitives and a fast 7-card Texas Hold'em hand evaluator.

Cards are (rank, suit) tuples: rank in 2..14 (14 = Ace), suit in 0..3.
evaluate7() returns a comparable tuple — bigger tuple wins.
"""

import random
from itertools import combinations

RANKS = range(2, 15)
SUITS = range(4)
RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_NAMES = "♠♥♦♣"


def card_str(card):
    r, s = card
    return f"{RANK_NAMES.get(r, r)}{SUIT_NAMES[s]}"


def new_deck(rng: random.Random):
    deck = [(r, s) for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck


def _best_straight(rankset):
    """Highest straight top-card in a set of ranks, or 0. Handles the wheel."""
    ranks = rankset | ({1} if 14 in rankset else set())
    for top in range(14, 4, -1):
        if all(top - i in ranks for i in range(5)):
            return top
    return 0


def evaluate7(cards):
    """Best 5-card hand value from 7 cards.

    Returns a tuple (category, tiebreak...) where category is:
    8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
    3 trips, 2 two pair, 1 one pair, 0 high card.
    """
    ranks = [c[0] for c in cards]
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1

    suit_cards = [[], [], [], []]
    for r, s in cards:
        suit_cards[s].append(r)

    flush_ranks = None
    for sc in suit_cards:
        if len(sc) >= 5:
            flush_ranks = sorted(sc, reverse=True)
            break

    if flush_ranks:
        sf = _best_straight(set(flush_ranks))
        if sf:
            return (8, sf)

    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if by_count[0][1] == 4:
        quad = by_count[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if by_count[0][1] == 3 and len(by_count) > 1 and by_count[1][1] >= 2:
        return (6, by_count[0][0], by_count[1][0])

    if flush_ranks:
        return (5, *flush_ranks[:5])

    straight = _best_straight(set(ranks))
    if straight:
        return (4, straight)

    if by_count[0][1] == 3:
        trip = by_count[0][0]
        kickers = sorted((r for r in ranks if r != trip), reverse=True)[:2]
        return (3, trip, *kickers)

    if by_count[0][1] == 2 and len(by_count) > 1 and by_count[1][1] == 2:
        hi, lo = by_count[0][0], by_count[1][0]
        kicker = max(r for r in ranks if r != hi and r != lo)
        return (2, hi, lo, kicker)

    if by_count[0][1] == 2:
        pair = by_count[0][0]
        kickers = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair, *kickers)

    return (0, *sorted(ranks, reverse=True)[:5])


def equity_vs_random(hole, board, n_opponents, rng, trials=60):
    """Monte Carlo equity of `hole` + `board` versus random opponent hands.

    Returns win probability in [0, 1]; ties count as fractional wins.
    """
    dead = set(hole) | set(board)
    stub = [(r, s) for r in RANKS for s in SUITS if (r, s) not in dead]
    need_board = 5 - len(board)
    opp = max(1, min(n_opponents, 3))  # cap for speed; 3 randoms is plenty tight
    score = 0.0

    for _ in range(trials):
        sample = rng.sample(stub, need_board + 2 * opp)
        full_board = list(board) + sample[:need_board]
        mine = evaluate7(list(hole) + full_board)
        best_opp = None
        for i in range(opp):
            h = sample[need_board + 2 * i: need_board + 2 * i + 2]
            v = evaluate7(h + full_board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5

    return score / trials


def chen_score(hole):
    """Bill Chen's preflop hand formula (classic poker-book heuristic)."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    high = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2)
    score = high
    if r1 == r2:
        score = max(5, high * 2)
    if s1 == s2:
        score += 2
    gap = r1 - r2 - 1
    if r1 != r2:
        score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
        if gap <= 1 and r1 < 12:
            score += 1
    return score
