"""Cards, deck, and a fast best-5-of-N hand evaluator for Texas Hold'em."""

from collections import Counter, defaultdict

RANKS = "23456789TJQKA"          # index 0 -> rank 2 ... index 12 -> rank 14 (Ace)
SUITS = "cdhs"
SUIT_GLYPHS = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}

# A card is a tuple (rank, suit) with rank in 2..14 and suit in 0..3.

CATEGORY_NAMES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
    "Flush", "Full House", "Four of a Kind", "Straight Flush",
]


def new_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


def card_str(card):
    r, s = card
    return RANKS[r - 2] + SUIT_GLYPHS[SUITS[s]]


def cards_str(cards):
    return " ".join(card_str(c) for c in cards)


def _straight_high(rank_set):
    """Highest straight top-card in a set of ranks (Ace plays low for the wheel)."""
    rs = set(rank_set)
    if 14 in rs:
        rs.add(1)
    for hi in range(14, 4, -1):
        if all(hi - k in rs for k in range(5)):
            return hi
    return 0


def evaluate_best(cards):
    """Score the best 5-card hand out of 5-7 cards.

    Returns a comparable tuple: (category, tiebreak...). Bigger is better.
    Direct rank/suit counting — no 21-combination loop — because the
    Monte Carlo strategies hammer this function millions of times.
    """
    ranks = [c[0] for c in cards]
    by_suit = defaultdict(list)
    for r, s in cards:
        by_suit[s].append(r)

    flush_ranks = None
    for rs in by_suit.values():
        if len(rs) >= 5:
            flush_ranks = sorted(rs, reverse=True)
            break

    if flush_ranks:
        sf = _straight_high(flush_ranks)
        if sf:
            return (8, sf)

    cnt = Counter(ranks)
    # groups: sorted by (count desc, rank desc)
    groups = sorted(cnt.items(), key=lambda kv: (-kv[1], -kv[0]))
    kickers = sorted(ranks, reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kick = max(r for r in ranks if r != quad)
        return (7, quad, kick)

    if groups[0][1] == 3:
        trips = groups[0][0]
        pair = max((r for r, c in cnt.items() if c >= 2 and r != trips), default=0)
        if pair:
            return (6, trips, pair)

    if flush_ranks:
        return (5, *flush_ranks[:5])

    st = _straight_high(ranks)
    if st:
        return (4, st)

    if groups[0][1] == 3:
        trips = groups[0][0]
        ks = [r for r in kickers if r != trips][:2]
        return (3, trips, *ks)

    pairs = [r for r, c in groups if c == 2]
    if len(pairs) >= 2:
        hp, lp = pairs[0], pairs[1]
        kick = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kick)

    if len(pairs) == 1:
        p = pairs[0]
        ks = [r for r in kickers if r != p][:3]
        return (1, p, *ks)

    return (0, *kickers[:5])


def category_name(score):
    return CATEGORY_NAMES[score[0]]
