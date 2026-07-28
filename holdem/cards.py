"""Card primitives, a fast 7-card evaluator, and Monte-Carlo equity.

Cards are ints 0..51: rank = card >> 2 (0 = deuce .. 12 = ace),
suit = card & 3.
"""

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_str(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def hand_str(cards):
    return " ".join(card_str(c) for c in cards)


def _straight_high(rank_set):
    rs = set(rank_set)
    if 12 in rs:  # ace also plays low for the wheel
        rs.add(-1)
    for high in range(12, 2, -1):
        if all(high - i in rs for i in range(5)):
            return high
    return -1


def eval7(cards):
    """Rank a 7-card hand. Returns a tuple; bigger tuple = better hand.

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    cnt = [0] * 13
    scnt = [0] * 4
    for c in cards:
        cnt[c >> 2] += 1
        scnt[c & 3] += 1

    flush_suit = -1
    for s in range(4):
        if scnt[s] >= 5:
            flush_suit = s
            break

    franks = None
    if flush_suit >= 0:
        franks = sorted({c >> 2 for c in cards if (c & 3) == flush_suit},
                        reverse=True)
        sf = _straight_high(franks)
        if sf >= 0:
            return (8, sf)

    uniq = sorted({c >> 2 for c in cards}, reverse=True)
    quads = [r for r in range(12, -1, -1) if cnt[r] == 4]
    trips = [r for r in range(12, -1, -1) if cnt[r] == 3]
    pairs = [r for r in range(12, -1, -1) if cnt[r] == 2]

    if quads:
        q = quads[0]
        kick = max(r for r in uniq if r != q)
        return (7, q, kick)
    if trips and (pairs or len(trips) > 1):
        t = trips[0]
        p = max(pairs[0] if pairs else -1,
                trips[1] if len(trips) > 1 else -1)
        return (6, t, p)
    if flush_suit >= 0:
        return (5,) + tuple(franks[:5])
    st = _straight_high(uniq)
    if st >= 0:
        return (4, st)
    if trips:
        t = trips[0]
        kicks = [r for r in uniq if r != t][:2]
        return (3, t) + tuple(kicks)
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kick = max(r for r in uniq if r != p1 and r != p2)
        return (2, p1, p2, kick)
    if pairs:
        p = pairs[0]
        kicks = [r for r in uniq if r != p][:3]
        return (1, p) + tuple(kicks)
    return (0,) + tuple(uniq[:5])


def estimate_equity(hole, community, n_opp, trials, rng):
    """Monte-Carlo equity of `hole` vs `n_opp` random hands.

    Ties count as split equity. Opponent ranges are uniform random —
    every strategy here works with the same imperfect information.
    """
    if n_opp <= 0:
        return 1.0
    seen = set(hole) | set(community)
    deck = [c for c in range(52) if c not in seen]
    need = 5 - len(community)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need + 2 * n_opp)
        board = list(community) + draw[:need]
        mine = eval7(list(hole) + board)
        best_opp = None
        for i in range(n_opp):
            oh = draw[need + 2 * i:need + 2 * i + 2]
            e = eval7(oh + board)
            if best_opp is None or e > best_opp:
                best_opp = e
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / trials


def chen_score(hole):
    """Bill Chen's preflop hand formula (approx). AA=20, AKs=12, 72o~=-1."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)

    def pts(r):
        v = r + 2
        return {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(v, v / 2.0)

    if r1 == r2:
        return max(5.0, pts(r1) * 2)
    score = pts(r1)
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # both below queen, close together
        score += 1
    return score
