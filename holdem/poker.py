"""Core poker primitives: cards, 7-card hand evaluation, Monte Carlo equity.

Cards are ints 0..51: rank = (card >> 2) + 2  (2..14, ace high), suit = card & 3.
"""

from __future__ import annotations

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"

HAND_NAMES = [
    "high card", "pair", "two pair", "trips", "straight",
    "flush", "full house", "quads", "straight flush",
]


def card_str(c: int) -> str:
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def cards_str(cs) -> str:
    return " ".join(card_str(c) for c in cs)


def _straight_high(rank_set) -> int:
    """Highest straight top-rank in a set of ranks (2..14), 0 if none. Handles the wheel."""
    rs = set(rank_set)
    if 14 in rs:
        rs.add(1)
    run = 0
    for r in range(14, 0, -1):
        if r in rs:
            run += 1
            if run >= 5:
                return r + 4
        else:
            run = 0
    return 0


def evaluate7(cards) -> tuple:
    """Best 5-card value of 7 (or 5/6) cards as a comparable tuple; bigger wins."""
    counts = [0] * 15
    suit_ranks = ([], [], [], [])
    for c in cards:
        counts[(c >> 2) + 2] += 1
        suit_ranks[c & 3].append((c >> 2) + 2)

    for sr in suit_ranks:
        if len(sr) >= 5:
            sf = _straight_high(sr)
            if sf:
                return (8, sf)
            sr.sort(reverse=True)
            return (5,) + tuple(sr[:5])

    quads = [r for r in range(14, 1, -1) if counts[r] == 4]
    trips = [r for r in range(14, 1, -1) if counts[r] == 3]
    pairs = [r for r in range(14, 1, -1) if counts[r] == 2]

    if quads:
        q = quads[0]
        kicker = max(r for r in range(2, 15) if counts[r] and r != q)
        return (7, q, kicker)
    if trips and (len(trips) > 1 or pairs):
        low = trips[1] if len(trips) > 1 else pairs[0]
        return (6, trips[0], low)

    st = _straight_high(r for r in range(2, 15) if counts[r])
    if st:
        return (4, st)

    if trips:
        t = trips[0]
        kickers = [r for r in range(14, 1, -1) if counts[r] == 1][:2]
        return (3, t) + tuple(kickers)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kicker = max(r for r in range(2, 15) if counts[r] and r != p1 and r != p2)
        return (2, p1, p2, kicker)
    if pairs:
        p = pairs[0]
        kickers = [r for r in range(14, 1, -1) if counts[r] == 1][:3]
        return (1, p) + tuple(kickers)

    highs = [r for r in range(14, 1, -1) if counts[r]][:5]
    return (0,) + tuple(highs)


def equity(hole, board, n_opps, trials, rng) -> float:
    """Monte Carlo equity of `hole` on `board` against n_opps uniformly random hands."""
    n_opps = max(1, min(3, n_opps))
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need = 5 - len(board)
    k = need + 2 * n_opps
    board = list(board)
    hole = list(hole)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, k)
        full = board + draw[:need]
        mine = evaluate7(hole + full)
        best_opp = max(
            evaluate7(draw[need + 2 * i:need + 2 * i + 2] + full)
            for i in range(n_opps)
        )
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / trials


def chen_score(hole) -> float:
    """Chen formula preflop hand strength (AA=20 down to 72o ~ -1)."""
    r1, r2 = sorted(((c >> 2) + 2 for c in hole), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    base = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(r1, r1 / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= (0, 1, 2, 4)[gap] if gap <= 3 else 5
    if gap <= 1 and r1 < 12:
        score += 1
    return score
