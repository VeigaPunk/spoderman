"""Shared hand-reading heuristics used by the strategy bots.

None of this peeks at hidden information: every function only consumes a
bot's own hole cards plus the public board.
"""

import math
from collections import Counter

from .cards import best_hand


def chen_score(hole):
    """Bill Chen's preflop hand formula. AA=20, KK=16, AKs=12, 72o=-1 ..."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        pts = max(5.0, pts * 2)
    if s1 == s2:
        pts += 2
    if r1 != r2:
        gap = hi - lo - 1
        pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
        if gap <= 1 and hi < 12:
            pts += 1
    return math.ceil(pts)


def made_strength(hole, board):
    """Rough 0..1 strength of the current made hand, discounted when the
    board itself supplies most of it."""
    cards = list(hole) + list(board)
    cat = best_hand(cards)[0]
    branks = [c[0] for c in board]
    bcnt = Counter(branks)
    board_paired = max(bcnt.values()) >= 2
    h1, h2 = hole[0][0], hole[1][0]
    pocket = h1 == h2
    top = max(branks)
    hits = sum(1 for h in {h1, h2} if h in bcnt)

    if cat == 8:
        return 1.0
    if cat == 7:
        return 0.97
    if cat == 6:
        return 0.93
    if cat == 5:
        return 0.90
    if cat == 4:
        return 0.85
    if cat == 3:  # trips
        if pocket:
            return 0.88  # a set
        return 0.78 if hits else 0.50
    if cat == 2:  # two pair
        if pocket and h1 > top:
            return 0.70  # overpair beside a paired board
        if hits == 2:
            return 0.72
        if board_paired and (hits or pocket):
            our = h1 if h1 in bcnt else (h2 if h2 in bcnt else h1)
            return 0.55 if our == top else 0.40
        if board_paired:
            return 0.22  # playing the board
        return 0.65
    if cat == 1:  # one pair
        if pocket:
            if h1 > top:
                return 0.68  # overpair
            return 0.42 if h1 > sorted(branks)[len(branks) // 2] else 0.32
        if hits:
            our = h1 if h1 in bcnt else h2
            kicker = h2 if our == h1 else h1
            if our == top:
                return 0.62 if kicker >= 11 else 0.54
            return 0.38 if our >= sorted(branks, reverse=True)[1] else 0.30
        return 0.18  # the pair is on the board; we hold high cards only
    return 0.15 if 14 in (h1, h2) else 0.07


def detect_draws(hole, board):
    """Return (flush_draw, straight_draw) where straight_draw is
    None | 'gutshot' | 'oesd'. Only meaningful before the river."""
    if len(board) >= 5:
        return False, None
    cards = list(hole) + list(board)
    suits = Counter(c[1] for c in cards)
    flush_draw = any(
        n == 4 and any(c[1] == s for c in hole)
        for s, n in suits.items()
    )
    ranks = {c[0] for c in cards}
    if 14 in ranks:
        ranks.add(1)
    straight = None
    for low in range(1, 11):
        window = [low + i in ranks for i in range(5)]
        n = sum(window)
        if n == 5:
            return flush_draw, None  # already made
        if n == 4:
            if window[0] and window[1] and window[2] and window[3]:
                straight = 'oesd'
            elif window[1] and window[2] and window[3] and window[4]:
                straight = 'oesd' if straight is None else straight
            else:
                straight = straight or 'gutshot'
    return flush_draw, straight


def draw_equity_bonus(hole, board):
    """Approximate extra equity from draws (rule of 2 and 4, halved-ish)."""
    flush_draw, straight = detect_draws(hole, board)
    streets_left = 2 if len(board) == 3 else 1
    bonus = 0.0
    if flush_draw:
        bonus += 0.09 * streets_left * 2
    if straight == 'oesd':
        bonus += 0.08 * streets_left * 2
    elif straight == 'gutshot':
        bonus += 0.04 * streets_left * 2
    return min(bonus, 0.36)


def pot_odds(view):
    to_call = view['to_call']
    if to_call <= 0:
        return 0.0
    return to_call / (view['pot'] + to_call)
