"""Cards, 7-card hand evaluation, Chen formula and Monte-Carlo equity."""

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_str(c):
    return RANKS[c % 13] + SUITS[c // 13]


def hand_str(cards):
    return " ".join(card_str(c) for c in cards)


def _straight_high(rankset):
    rs = set(rankset)
    if 12 in rs:
        rs.add(-1)  # wheel: A2345
    for hi in range(12, 2, -1):
        if all(h in rs for h in range(hi, hi - 5, -1)):
            return hi
    return None


def evaluate(cards):
    """Best 5-card hand from 5-7 cards -> comparable flat tuple (bigger wins).

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    ranks = sorted((c % 13 for c in cards), reverse=True)

    # Flush (with <=7 cards a flush excludes quads/full house, so safe first)
    suit_count = [0, 0, 0, 0]
    for c in cards:
        suit_count[c // 13] += 1
    for s in range(4):
        if suit_count[s] >= 5:
            fr = sorted((c % 13 for c in cards if c // 13 == s), reverse=True)
            sh = _straight_high(fr)
            if sh is not None:
                return (8, sh)
            return (5, fr[0], fr[1], fr[2], fr[3], fr[4])

    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    sh = _straight_high(ranks)
    if sh is not None:
        return (4, sh)

    if groups[0][1] == 3:
        t = groups[0][0]
        k = [r for r in ranks if r != t]
        return (3, t, k[0], k[1])
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kicker)
    if groups[0][1] == 2:
        p = groups[0][0]
        k = [r for r in ranks if r != p]
        return (1, p, k[0], k[1], k[2])
    return (0, ranks[0], ranks[1], ranks[2], ranks[3], ranks[4])


def chen(hole):
    """Chen formula score for a starting hand (AA=20 ... 72o negative)."""
    a, b = hole
    ra, rb = a % 13, b % 13
    if ra < rb:
        ra, rb = rb, ra
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(ra, (ra + 2) / 2.0)
    if ra == rb:
        return max(5.0, pts * 2)
    if a // 13 == b // 13:
        pts += 2
    gap = ra - rb - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and ra <= 9:  # close connectors below Q can make more straights
        pts += 1
    return pts


def hand_class(hole):
    """169-class key like 'AKs', 'T9o', 'QQ'."""
    a, b = hole
    ra, rb = a % 13, b % 13
    if ra < rb:
        ra, rb = rb, ra
    if ra == rb:
        return RANKS[ra] * 2
    return RANKS[ra] + RANKS[rb] + ("s" if a // 13 == b // 13 else "o")


def estimate_equity(hole, board, n_opp, iters, rng):
    """Monte-Carlo equity of `hole` on `board` vs `n_opp` random hands."""
    n_opp = max(1, min(n_opp, 4))
    known = set(hole) | set(board)
    deck = [c for c in range(52) if c not in known]
    need = 5 - len(board)
    score = 0.0
    sample = rng.sample
    board = list(board)
    for _ in range(iters):
        draw = sample(deck, need + 2 * n_opp)
        full = board + draw[:need]
        my = evaluate(list(hole) + full)
        best = None
        for i in range(n_opp):
            r = evaluate([draw[need + 2 * i], draw[need + 2 * i + 1]] + full)
            if best is None or r > best:
                best = r
        if my > best:
            score += 1.0
        elif my == best:
            score += 0.5
    return score / iters


# Lazily-built cache of preflop all-in equity per (hand class, n_opp);
# shared across tournaments so each of the 169 classes is simulated once.
import random as _random

_PRE_RNG = _random.Random(0xC0FFEE)
_PRE_CACHE = {}


def preflop_equity(hole, n_opp):
    n_opp = max(1, min(n_opp, 4))
    key = (hand_class(hole), n_opp)
    eq = _PRE_CACHE.get(key)
    if eq is None:
        eq = estimate_equity(hole, (), n_opp, 400, _PRE_RNG)
        _PRE_CACHE[key] = eq
    return eq
