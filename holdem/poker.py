"""Core poker primitives: cards, deck, and 5/7-card hand evaluation."""

from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

# Hand categories, higher is better
HIGH_CARD, PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

CATEGORY_NAMES = {
    HIGH_CARD: "high card", PAIR: "pair", TWO_PAIR: "two pair", TRIPS: "three of a kind",
    STRAIGHT: "straight", FLUSH: "flush", FULL_HOUSE: "full house", QUADS: "four of a kind",
    STRAIGHT_FLUSH: "straight flush",
}


def make_deck():
    return [r + s for r in RANKS for s in SUITS]


def rank_of(card):
    return RANK_VALUE[card[0]]


def suit_of(card):
    return card[1]


def _straight_high(values):
    """High card of the best straight in a set of distinct rank values, else 0."""
    vals = set(values)
    if 14 in vals:  # wheel: ace plays low
        vals.add(1)
    best = 0
    for high in range(14, 4, -1):
        if all(v in vals for v in range(high - 4, high + 1)):
            best = high
            break
    return best


def evaluate5(cards):
    """Rank a 5-card hand. Returns a tuple; larger tuples beat smaller ones."""
    values = sorted((rank_of(c) for c in cards), reverse=True)
    suits = [suit_of(c) for c in cards]
    is_flush = len(set(suits)) == 1
    sh = _straight_high(values)

    if is_flush and sh:
        return (STRAIGHT_FLUSH, sh)

    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    # sort by (count, value) descending so groups come first
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = tuple(g[1] for g in groups)
    ordered = tuple(g[0] for g in groups)

    if shape == (4, 1):
        return (QUADS,) + ordered
    if shape == (3, 2):
        return (FULL_HOUSE,) + ordered
    if is_flush:
        return (FLUSH,) + tuple(values)
    if sh:
        return (STRAIGHT, sh)
    if shape == (3, 1, 1):
        return (TRIPS,) + ordered
    if shape == (2, 2, 1):
        return (TWO_PAIR,) + ordered
    if shape == (2, 1, 1, 1):
        return (PAIR,) + ordered
    return (HIGH_CARD,) + tuple(values)


def best_hand(cards):
    """Best 5-card rank from 5, 6 or 7 cards."""
    if len(cards) == 5:
        return evaluate5(cards)
    return max(evaluate5(c) for c in combinations(cards, 5))


def best_hand_with_combo(cards):
    """Best rank plus the 5-card combo that achieves it."""
    best = None
    best_combo = None
    for combo in combinations(cards, 5):
        r = evaluate5(combo)
        if best is None or r > best:
            best, best_combo = r, combo
    return best, best_combo


def chen_score(hole):
    """Chen formula for preflop hand strength. Roughly -1..20; AA=20, 72o≈-1."""
    a, b = sorted(hole, key=rank_of, reverse=True)
    hi, lo = rank_of(a), rank_of(b)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if hi == lo:
        return max(5.0, pts * 2)
    score = pts
    if suit_of(a) == suit_of(b):
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:  # straight-friendly connectors
        score += 1
    return score


def _draw_bonus(hole, board):
    """Bonus for flush/straight draws when more cards are coming."""
    cards = hole + board
    bonus = 0.0
    suit_counts = {}
    for c in cards:
        suit_counts[suit_of(c)] = suit_counts.get(suit_of(c), 0) + 1
    if any(n == 4 for n in suit_counts.values()):
        bonus += 0.16  # flush draw
    vals = set(rank_of(c) for c in cards)
    if 14 in vals:
        vals.add(1)
    # count open-ended / gutshot straight draws
    outs = 0
    for high in range(14, 4, -1):
        window = set(range(high - 4, high + 1))
        missing = window - vals
        if len(missing) == 1:
            outs += 1
    if outs >= 2:
        bonus += 0.13  # open-ended or double gutter
    elif outs == 1:
        bonus += 0.06  # gutshot
    return min(bonus, 0.2)


def hand_strength(hole, board):
    """Heuristic strength in [0, 1] for hole cards on a given board.

    Preflop it is a normalized Chen score; postflop it grades the made hand,
    discounts hands that merely play the board, and credits live draws.
    """
    if not board:
        return max(0.0, min(1.0, (chen_score(hole) + 1.5) / 21.5))

    rank, combo = best_hand_with_combo(list(hole) + list(board))
    cat = rank[0]
    hole_used = sum(1 for c in hole if c in combo)

    board_max = max(rank_of(c) for c in board)
    base = 0.0
    if cat == HIGH_CARD:
        base = 0.05 + 0.10 * (rank[1] - 2) / 12
    elif cat == PAIR:
        pair_rank = rank[1]
        if pair_rank >= board_max:
            base = 0.42 + 0.13 * (pair_rank - 2) / 12  # top pair / overpair
        else:
            base = 0.22 + 0.12 * (pair_rank - 2) / 12  # middle/bottom pair
    elif cat == TWO_PAIR:
        base = 0.62
    elif cat == TRIPS:
        base = 0.72
    elif cat == STRAIGHT:
        base = 0.80
    elif cat == FLUSH:
        base = 0.85
    elif cat == FULL_HOUSE:
        base = 0.92
    else:
        base = 0.97

    if hole_used == 0:
        base *= 0.45  # we are playing the board; anyone matches us

    if len(board) < 5:
        base += _draw_bonus(list(hole), list(board))

    return max(0.0, min(1.0, base))
