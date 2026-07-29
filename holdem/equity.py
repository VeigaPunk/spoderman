"""Hand-strength tools shared by the elaborate strategies.

Nothing here knows anything about who is sitting at the table -- these are pure
functions of cards, so a strategy using them still learns nothing about its
opponents' algorithms.
"""

from .cards import evaluate, FULL_DECK

# Cached preflop equities: (canonical hand, opponent count) -> win share.
_PREFLOP_CACHE = {}
# Cached postflop equities keyed by the exact cards involved.
_POSTFLOP_CACHE = {}


def canonical_preflop(hole):
    """'AKs', 'AKo', 'TT' -- the 169 distinct starting hands."""
    a, b = hole
    ra, rb = a >> 2, b >> 2
    suited = (a & 3) == (b & 3)
    hi, lo = max(ra, rb), min(ra, rb)
    from .cards import RANK_CHARS
    if hi == lo:
        return RANK_CHARS[hi] + RANK_CHARS[lo]
    return RANK_CHARS[hi] + RANK_CHARS[lo] + ("s" if suited else "o")


def chen_score(hole):
    """Bill Chen's starting-hand formula. Roughly -1.5 (72o) to 20 (AA)."""
    a, b = hole
    ra, rb = a >> 2, b >> 2
    suited = (a & 3) == (b & 3)
    hi, lo = max(ra, rb), min(ra, rb)

    base = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if hi == lo:
        score = max(base * 2, 5.0)          # pairs, minimum 5 (22 -> 5)
    else:
        score = base
        if suited:
            score += 2.0
        gap = hi - lo - 1
        score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
        if gap <= 1 and hi < 12:
            score += 1                       # 0/1-gap straight bonus
    import math
    return math.ceil(score * 2) / 2.0


def monte_carlo_equity(hole, board, num_opponents, iterations, rng):
    """Share of the pot this hand wins against `num_opponents` random hands.

    Ties count as a fractional win. This is equity against a *random* range,
    which is deliberately naive -- each strategy layers its own read on top.
    """
    if num_opponents <= 0:
        return 1.0

    key = (tuple(sorted(hole)), tuple(sorted(board)), num_opponents)
    cached = _POSTFLOP_CACHE.get(key) if board else _PREFLOP_CACHE.get(
        (canonical_preflop(hole), num_opponents))
    if cached is not None:
        return cached

    known = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    board = list(board)
    need_board = 5 - len(board)
    total = 0.0

    for _ in range(iterations):
        drawn = rng.sample(deck, need_board + 2 * num_opponents)
        full_board = board + drawn[:need_board]
        mine = evaluate(tuple(hole) + tuple(full_board))
        best_other = None
        ties = 0
        pos = need_board
        for _ in range(num_opponents):
            other = evaluate((drawn[pos], drawn[pos + 1], *full_board))
            pos += 2
            if best_other is None or other > best_other:
                best_other = other
                ties = 1
            elif other == best_other:
                ties += 1
        if mine > best_other:
            total += 1.0
        elif mine == best_other:
            total += 1.0 / (ties + 1)

    equity = total / iterations
    if board:
        if len(_POSTFLOP_CACHE) < 200000:
            _POSTFLOP_CACHE[key] = equity
    else:
        _PREFLOP_CACHE[(canonical_preflop(hole), num_opponents)] = equity
    return equity


def board_texture(board):
    """Coarse read on how wet a board is: 0 (dry) .. 1 (soaking)."""
    if not board:
        return 0.0
    ranks = sorted({c >> 2 for c in board}, reverse=True)
    suits = [c & 3 for c in board]
    score = 0.0
    for s in range(4):
        n = suits.count(s)
        if n >= 3:
            score += 0.45
        elif n == 2:
            score += 0.2
    span = 0
    for i in range(len(ranks) - 1):
        if ranks[i] - ranks[i + 1] <= 2:
            span += 1
    score += min(span, 3) * 0.15
    if len(ranks) < len(board):
        score += 0.1                         # paired board
    return min(score, 1.0)


def made_hand_class(hole, board):
    """Category index of the current best five cards (0 high card .. 8 SF)."""
    if not board:
        return -1
    return evaluate(tuple(hole) + tuple(board))[0]


def draw_strength(hole, board):
    """Flush/straight draw detection -> extra equity worth semi-bluffing."""
    if len(board) not in (3, 4):
        return 0.0
    cards = list(hole) + list(board)
    suits = [c & 3 for c in cards]
    bonus = 0.0
    for s in range(4):
        if suits.count(s) == 4 and any((c & 3) == s for c in hole):
            bonus += 0.35                    # four to a flush, using our cards
    ranks = {c >> 2 for c in cards}
    if 14 in ranks:
        ranks.add(1)
    best_run = 0
    for high in range(14, 4, -1):
        hits = sum(1 for i in range(5) if high - i in ranks)
        best_run = max(best_run, hits)
    if best_run == 4:
        bonus += 0.25                        # open-ender or gutshot family
    return min(bonus, 0.5)
