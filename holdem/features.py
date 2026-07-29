"""Postflop hand-reading features shared by the strategies.

Everything here is a pure function of (hole, board) and is cached under the
suit-isomorphic key from :mod:`holdem.equity`, so repeated queries inside a
betting round are free.
"""

from __future__ import annotations

from dataclasses import dataclass

from .cards import (FLUSH, FULL_HOUSE, PAIR, QUADS, STRAIGHT, STRAIGHT_FLUSH,
                    TRIPS, TWO_PAIR, eval7)
from .equity import canonical, p_beat_one

_profile_cache: dict = {}
_texture_cache: dict = {}


@dataclass
class Texture:
    paired: bool
    trips_on_board: bool
    monotone: bool          # three+ of one suit
    two_tone: bool
    flush_possible: bool    # three+ of a suit on board
    straight_possible: bool
    connected: float        # 0..1, how coordinated the ranks are
    high_cards: int         # board cards T or better
    wetness: float          # 0 = dry rainbow rags, 1 = very dangerous


def texture(board) -> Texture:
    key = tuple(sorted(board))
    hit = _texture_cache.get(key)
    if hit is not None:
        return hit
    ranks = sorted((c >> 2 for c in board), reverse=True)
    suits = [0, 0, 0, 0]
    counts = {}
    for c in board:
        suits[c & 3] += 1
        counts[c >> 2] = counts.get(c >> 2, 0) + 1
    top_suit = max(suits) if board else 0
    paired = any(v >= 2 for v in counts.values())
    trips = any(v >= 3 for v in counts.values())

    gaps = 0.0
    if len(ranks) >= 2:
        spans = []
        uniq = sorted(set(ranks))
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                d = uniq[j] - uniq[i]
                if d <= 4:
                    spans.append(1.0 - (d - 1) / 4.0)
        gaps = min(1.0, sum(spans) / 3.0) if spans else 0.0

    mask = 0
    for r in set(counts):
        mask |= 1 << r
    straight_possible = False
    for r in range(13):
        if not (mask >> r) & 1:
            for r2 in range(13):
                m = mask | (1 << r) | (1 << r2)
                from .cards import _STRAIGHT  # local import: table lookup
                if _STRAIGHT[m] >= 0:
                    straight_possible = True
                    break
        if straight_possible:
            break

    high = sum(1 for r in ranks if r >= 8)
    wetness = min(1.0, 0.42 * (top_suit >= 3) + 0.22 * (top_suit == 2)
                  + 0.40 * gaps + 0.14 * paired + 0.10 * high
                  + 0.20 * straight_possible)
    t = Texture(paired, trips, top_suit >= 3, top_suit == 2, top_suit >= 3,
                straight_possible, gaps, high, wetness)
    _texture_cache[key] = t
    return t


@dataclass
class Profile:
    """A cached read of hero's hand on a given board."""

    p1: float               # P(beat one random hand) by the river
    cat: int                # current best-5 category
    board_cat: int          # category the board alone makes
    uses_hole: bool         # hero's hand beats the naked board
    hand_rank: int          # raw eval7 score
    flush_draw: bool
    nut_flush_draw: bool
    straight_outs: int      # cards that complete a straight for us
    flush_outs: int
    strong_outs: int        # cards that lift us to a better category
    overcards: int          # hole cards above every board card
    pair_type: str          # 'none'|'weak'|'second'|'top'|'over'
    top_kicker: bool

    @property
    def has_draw(self) -> bool:
        return self.flush_draw or self.straight_outs >= 4

    @property
    def strong_draw(self) -> bool:
        return self.flush_draw or self.straight_outs >= 8

    @property
    def made(self) -> bool:
        return self.cat >= PAIR and self.uses_hole


def profile(hole, board) -> Profile:
    key = canonical(hole, board)
    hit = _profile_cache.get(key)
    if hit is not None:
        return hit

    hole = list(hole)
    board = list(board)
    seen = set(hole) | set(board)
    rank = eval7(hole + board)
    # the board playing itself is only defined with five cards; before that
    # every holding necessarily "uses" the hole cards
    bcat = _board_only_category(board)
    cat = rank >> 20

    suits = [0, 0, 0, 0]
    hole_suits = [0, 0, 0, 0]
    for c in board:
        suits[c & 3] += 1
    for c in hole:
        suits[c & 3] += 1
        hole_suits[c & 3] += 1
    fd_suit = -1
    for s in range(4):
        if suits[s] == 4 and hole_suits[s] >= 1:
            fd_suit = s
    flush_draw = fd_suit >= 0 and len(board) < 5
    nut_fd = False
    if flush_draw:
        mine = max((c >> 2) for c in hole if (c & 3) == fd_suit)
        higher = [r for r in range(mine + 1, 13)
                  if ((r << 2) | fd_suit) not in seen]
        nut_fd = not higher

    straight_outs = 0
    flush_outs = 0
    strong_outs = 0
    if len(board) < 5:
        for c in range(52):
            if c in seen:
                continue
            new = eval7(hole + board + [c])
            ncat = new >> 20
            if ncat > cat:
                if ncat == STRAIGHT and cat < STRAIGHT:
                    straight_outs += 1
                if ncat in (FLUSH, STRAIGHT_FLUSH) and cat < FLUSH:
                    flush_outs += 1
                if ncat >= TWO_PAIR or (ncat == PAIR and cat < PAIR):
                    strong_outs += 1

    board_ranks = sorted((c >> 2 for c in board), reverse=True)
    hole_ranks = sorted((c >> 2 for c in hole), reverse=True)
    overcards = sum(1 for r in hole_ranks if not board_ranks or r > board_ranks[0])
    pair_type = "none"
    top_kicker = False
    if board_ranks:
        if hole_ranks[0] == hole_ranks[1]:
            if hole_ranks[0] > board_ranks[0]:
                pair_type = "over"
            elif hole_ranks[0] > (board_ranks[1] if len(board_ranks) > 1 else -1):
                pair_type = "second"
            else:
                pair_type = "weak"
        else:
            hits = [r for r in hole_ranks if r in board_ranks]
            if hits:
                h = max(hits)
                if h == board_ranks[0]:
                    pair_type = "top"
                    kicker = [r for r in hole_ranks if r != h]
                    top_kicker = bool(kicker) and kicker[0] >= 11
                elif len(board_ranks) > 1 and h == sorted(set(board_ranks),
                                                          reverse=True)[1:2][0]:
                    pair_type = "second"
                else:
                    pair_type = "weak"

    prof = Profile(
        p1=p_beat_one(hole, board),
        cat=cat,
        board_cat=bcat,
        uses_hole=rank > _board_only_rank(board),
        hand_rank=rank,
        flush_draw=flush_draw,
        nut_flush_draw=nut_fd,
        straight_outs=straight_outs,
        flush_outs=flush_outs,
        strong_outs=strong_outs,
        overcards=overcards,
        pair_type=pair_type,
        top_kicker=top_kicker,
    )
    _profile_cache[key] = prof
    return prof


def _board_only_rank(board):
    """Score of the board playing itself (needs 5 cards; else -1)."""
    if len(board) < 5:
        return -1
    return eval7(list(board))


def _board_only_category(board):
    if len(board) < 5:
        return -1
    return eval7(list(board)) >> 20


NUTTY = (STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH)


def strength_bucket(prof: Profile) -> str:
    """Coarse label used by several strategies for line selection."""
    if prof.cat >= FULL_HOUSE:
        return "monster"
    if prof.cat in (STRAIGHT, FLUSH, TRIPS):
        return "strong"
    if prof.cat == TWO_PAIR:
        return "strong"
    if prof.cat == PAIR and prof.pair_type in ("over", "top"):
        return "good"
    if prof.strong_draw:
        return "draw"
    if prof.cat == PAIR:
        return "marginal"
    if prof.straight_outs >= 4 or prof.overcards >= 2:
        return "weak"
    return "air"
