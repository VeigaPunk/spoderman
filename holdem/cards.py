"""Card representation and a fast 7-card Texas Hold'em hand evaluator.

A card is a single int:  rank = card >> 2  (2..14),  suit = card & 3.
Ranks: 2..10 = pip value, 11=J, 12=Q, 13=K, 14=A.

Because ranks start at 2, the 52 real cards are the ints [8, 60) -- NOT
[0, 52). Always deal from ``FULL_DECK``; ints 0..7 decode to nonexistent
ranks 0 and 1.
"""

RANK_CHARS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
              9: "9", 10: "T", 11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_CHARS = ["s", "h", "d", "c"]

CATEGORY_NAMES = [
    "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
    "Flush", "Full House", "Four of a Kind", "Straight Flush",
]

MIN_CARD = 2 << 2          # 8   -> 2s
MAX_CARD = (14 << 2) + 4   # 60  -> one past Ac
FULL_DECK = tuple(range(MIN_CARD, MAX_CARD))


def make_card(rank, suit):
    return (rank << 2) | suit


def card_str(card):
    return RANK_CHARS[card >> 2] + SUIT_CHARS[card & 3]


def cards_str(cards):
    return " ".join(card_str(c) for c in cards)


def parse_card(text):
    """'Ah' -> card int. Accepts 'T'/'10' for ten."""
    text = text.strip()
    rank_part, suit_part = text[:-1], text[-1].lower()
    rank_part = rank_part.upper()
    lookup = {v: k for k, v in RANK_CHARS.items()}
    lookup["10"] = 10
    return make_card(lookup[rank_part], SUIT_CHARS.index(suit_part))


def _straight_high(desc_unique_ranks):
    """Highest card of a 5-straight within the given ranks, else 0.

    Ace plays low as well, so A-2-3-4-5 is detected and reported as a 5-high
    straight (the standard 'wheel').
    """
    present = set(desc_unique_ranks)
    if 14 in present:
        present.add(1)
    for high in range(14, 4, -1):
        if high in present and high - 1 in present and high - 2 in present \
                and high - 3 in present and high - 4 in present:
            return high
    return 0


def evaluate(cards):
    """Rank a 5, 6 or 7 card holding.

    Returns a tuple ``(category, tiebreakers)`` that sorts correctly against any
    other result from this function: bigger is better. ``category`` indexes into
    ``CATEGORY_NAMES``.
    """
    rank_count = [0] * 15
    suit_count = [0, 0, 0, 0]
    suit_ranks = ([], [], [], [])
    for c in cards:
        r = c >> 2
        s = c & 3
        rank_count[r] += 1
        suit_count[s] += 1
        suit_ranks[s].append(r)

    # A 7-card holding can only ever contain one 5+ card suit.
    for s in range(4):
        if suit_count[s] >= 5:
            flush_ranks = sorted(set(suit_ranks[s]), reverse=True)
            sf_high = _straight_high(flush_ranks)
            if sf_high:
                return (8, (sf_high,))
            return (5, tuple(flush_ranks[:5]))

    desc = [r for r in range(14, 1, -1) if rank_count[r]]
    quads = [r for r in desc if rank_count[r] == 4]
    trips = [r for r in desc if rank_count[r] == 3]
    pairs = [r for r in desc if rank_count[r] == 2]

    if quads:
        q = quads[0]
        kicker = max(r for r in desc if r != q)
        return (7, (q, kicker))

    if trips and (len(trips) > 1 or pairs):
        # Second set can only ever be used as the pair half of the boat.
        top = trips[0]
        partner = trips[1] if len(trips) > 1 else 0
        if pairs:
            partner = max(partner, pairs[0])
        return (6, (top, partner))

    straight = _straight_high(desc)
    if straight:
        return (4, (straight,))

    if trips:
        t = trips[0]
        kickers = [r for r in desc if r != t][:2]
        return (3, (t, *kickers))

    if len(pairs) >= 2:
        hi, lo = pairs[0], pairs[1]
        kicker = max(r for r in desc if r != hi and r != lo)
        return (2, (hi, lo, kicker))

    if pairs:
        p = pairs[0]
        kickers = [r for r in desc if r != p][:3]
        return (1, (p, *kickers))

    return (0, tuple(desc[:5]))


def describe(cards):
    cat, tie = evaluate(cards)
    return "%s (%s)" % (CATEGORY_NAMES[cat],
                        ",".join(RANK_CHARS.get(t, str(t)) for t in tie))
