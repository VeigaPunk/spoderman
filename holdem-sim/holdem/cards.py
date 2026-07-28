"""Card representation: a card is an int 0..51, rank = card >> 2 (0=deuce .. 12=ace),
suit = card & 3."""

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"

FULL_DECK = list(range(52))


def rank(card: int) -> int:
    return card >> 2


def suit(card: int) -> int:
    return card & 3


def make(rank_char: str, suit_char: str) -> int:
    return RANK_CHARS.index(rank_char) * 4 + SUIT_CHARS.index(suit_char)


def to_str(card: int) -> str:
    return RANK_CHARS[card >> 2] + SUIT_CHARS[card & 3]


def hand_str(cards) -> str:
    return " ".join(to_str(c) for c in cards)
