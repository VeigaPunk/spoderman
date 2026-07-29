"""Card representation: an int 0..51. rank = c % 13 (0 = deuce .. 12 = ace), suit = c // 13."""

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"


def card_str(c: int) -> str:
    return RANK_CHARS[c % 13] + SUIT_CHARS[c // 13]


def hand_str(cards) -> str:
    return " ".join(card_str(c) for c in cards)


def new_deck():
    return list(range(52))
