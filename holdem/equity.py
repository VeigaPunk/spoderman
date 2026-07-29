"""Hand-equity estimation.

Two layers:

``preflop_equity``
    Table lookup over the 169 preflop hand classes, built once by Monte
    Carlo and cached on disk (``preflop_equity.json``).

``equity``
    Postflop.  Estimates ``p1`` = P(hero beats one random hand at showdown)
    by Monte Carlo over the remaining runout, then approximates equity
    against ``n`` opponents as ``p1 ** n``.

Every Monte Carlo run is seeded from a canonical, suit-isomorphic key for
the situation, so the cache is a pure function of its input: results are
byte-identical no matter how the work is sharded across processes.
"""

from __future__ import annotations

import json
import os
import random
import zlib

from .cards import RANKS, eval7, make_card

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE_PATH = os.path.join(_HERE, "preflop_equity.json")

# Monte Carlo sample counts by number of board cards.
TRIALS_BY_STREET = {3: 220, 4: 180, 5: 160}

_p1_cache: dict = {}


# --------------------------------------------------------------------------
# canonical keys
# --------------------------------------------------------------------------

def canonical(hole, board):
    """Suit-isomorphic canonical form of (hole, board).

    Suits are relabelled by order of first appearance, so ``AsKs`` on a
    ``2s 7h Td`` board and ``AcKc`` on ``2c 7d Th`` share one cache entry.
    """
    seq = tuple(sorted(hole)) + tuple(sorted(board))
    mapping = {}
    out = []
    for c in seq:
        s = c & 3
        m = mapping.get(s)
        if m is None:
            m = len(mapping)
            mapping[s] = m
        out.append(((c >> 2) << 2) | m)
    return tuple(out)


def hand_class(hole) -> str:
    """``(As, Kh)`` -> ``'AKo'``; ``(7c, 7d)`` -> ``'77'``."""
    a, b = hole
    ra, rb = a >> 2, b >> 2
    if ra < rb:
        ra, rb = rb, ra
    if ra == rb:
        return RANKS[ra] * 2
    return RANKS[ra] + RANKS[rb] + ("s" if (a & 3) == (b & 3) else "o")


CLASS_COMBOS = {}
for _i in range(13):
    CLASS_COMBOS[RANKS[_i] * 2] = 6
    for _j in range(_i):
        CLASS_COMBOS[RANKS[_i] + RANKS[_j] + "s"] = 4
        CLASS_COMBOS[RANKS[_i] + RANKS[_j] + "o"] = 12

ALL_CLASSES = tuple(CLASS_COMBOS)
TOTAL_COMBOS = 1326


def class_example(cls):
    """A representative two-card holding for a hand class."""
    r1 = RANKS.index(cls[0])
    r2 = RANKS.index(cls[1])
    if len(cls) == 2:
        return (make_card(r1, 0), make_card(r2, 1))
    if cls[2] == "s":
        return (make_card(r1, 0), make_card(r2, 0))
    return (make_card(r1, 0), make_card(r2, 1))


# --------------------------------------------------------------------------
# Monte Carlo
# --------------------------------------------------------------------------

def _seeded_rng(key) -> random.Random:
    return random.Random(zlib.crc32(repr(key).encode()) ^ 0x5EED)


def _simulate_p1(hole, board, trials, rng) -> float:
    """P(hero wins) + P(tie)/2 versus one uniformly random opponent hand."""
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need = 5 - len(board)
    draw = need + 2
    board = list(board)
    hole = list(hole)
    sample = rng.sample
    ev = eval7
    score = 0.0
    for _ in range(trials):
        cards = sample(deck, draw)
        run = board + cards[:need]
        h = ev(hole + run)
        o = ev(cards[need:] + run)
        if h > o:
            score += 1.0
        elif h == o:
            score += 0.5
    return score / trials


def p_beat_one(hole, board, trials=None) -> float:
    """Cached P(hero beats a single random hand by the river)."""
    key = canonical(hole, board)
    hit = _p1_cache.get(key)
    if hit is not None:
        return hit
    if trials is None:
        trials = TRIALS_BY_STREET.get(len(board), 200)
    val = _simulate_p1(hole, board, trials, _seeded_rng(key))
    _p1_cache[key] = val
    return val


# --------------------------------------------------------------------------
# preflop table
# --------------------------------------------------------------------------

_PREFLOP = None


def _build_preflop_row(cls, trials, max_opp=5):
    hole = list(class_example(cls))
    dead = set(hole)
    deck = [c for c in range(52) if c not in dead]
    rng = _seeded_rng(("preflop", cls))
    row = []
    for n in range(1, max_opp + 1):
        wins = 0.0
        need = 5 + 2 * n
        for _ in range(trials):
            cards = rng.sample(deck, need)
            board = cards[:5]
            mine = eval7(hole + board)
            best = 0
            ties = 0
            for k in range(n):
                o = eval7(cards[5 + 2 * k: 7 + 2 * k] + board)
                if o > best:
                    best = o
                    ties = 1
                elif o == best:
                    ties += 1
            if mine > best:
                wins += 1.0
            elif mine == best:
                wins += 1.0 / (ties + 1)
        row.append(wins / trials)
    return cls, row


def build_preflop_table(trials=2500, workers=None, verbose=True):
    """Build (and cache to disk) the 169 x 5 preflop equity table."""
    import concurrent.futures as cf

    if workers is None:
        workers = max(1, (os.cpu_count() or 2))
    table = {}
    if workers > 1:
        with cf.ProcessPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(_build_preflop_row, c, trials) for c in ALL_CLASSES]
            for i, f in enumerate(cf.as_completed(futs), 1):
                cls, row = f.result()
                table[cls] = row
                if verbose and i % 20 == 0:
                    print(f"  preflop table {i}/{len(ALL_CLASSES)}", flush=True)
    else:
        for cls in ALL_CLASSES:
            c, row = _build_preflop_row(cls, trials)
            table[c] = row
    with open(_TABLE_PATH, "w") as fh:
        json.dump({"trials": trials, "table": table}, fh, indent=0, sort_keys=True)
    return table


def _load_preflop():
    global _PREFLOP
    if _PREFLOP is None:
        if not os.path.exists(_TABLE_PATH):
            raise RuntimeError(
                "preflop_equity.json is missing - run `python -m holdem.equity` "
                "to build it."
            )
        with open(_TABLE_PATH) as fh:
            _PREFLOP = json.load(fh)["table"]
    return _PREFLOP


def preflop_equity(hole, n_opp: int) -> float:
    """Equity of a starting hand against ``n_opp`` uniformly random hands."""
    row = _load_preflop()[hand_class(hole)]
    if n_opp < 1:
        return 1.0
    if n_opp <= len(row):
        return row[n_opp - 1]
    # extrapolate geometrically past the tabulated range
    ratio = row[-1] / row[-2] if row[-2] > 0 else 1.0
    val = row[-1]
    for _ in range(n_opp - len(row)):
        val *= ratio
    return val


def equity(hole, board, n_opp: int) -> float:
    """Hero's equity against ``n_opp`` random hands, at any street."""
    if n_opp <= 0:
        return 1.0
    if not board:
        return preflop_equity(hole, n_opp)
    p1 = p_beat_one(hole, board)
    return p1 ** n_opp


# --------------------------------------------------------------------------
# preflop hand ordering (used by the range-based strategies)
# --------------------------------------------------------------------------

_RANK_ORDER = None


def _build_rank_order():
    """Map each hand class to its top-of-range percentile in [0, 1].

    Classes are sorted by a blend of heads-up equity (raw strength) and
    6-way equity (multiway playability), then assigned percentiles weighted
    by combination count, so "top 15%" means 15% of the 1326 combos.
    """
    global _RANK_ORDER
    if _RANK_ORDER is not None:
        return _RANK_ORDER
    table = _load_preflop()
    scored = sorted(
        ALL_CLASSES,
        key=lambda c: -(0.55 * table[c][0] + 0.45 * table[c][4]),
    )
    order = {}
    seen = 0
    for cls in scored:
        seen += CLASS_COMBOS[cls]
        order[cls] = seen / TOTAL_COMBOS  # percentile of the *worst* combo
    _RANK_ORDER = order
    return order


def hand_percentile(hole) -> float:
    """0.0 = the very best starting hand, 1.0 = the very worst."""
    return _build_rank_order()[hand_class(hole)]


def top_n_percent(hole, pct: float) -> bool:
    """Is this holding inside the top ``pct`` fraction of all starting hands?"""
    return hand_percentile(hole) <= pct


if __name__ == "__main__":  # pragma: no cover
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2500
    print(f"building preflop equity table ({n} trials/class/opponent-count)...")
    build_preflop_table(trials=n)
    _PREFLOP = None
    order = _build_rank_order()
    best = sorted(order, key=lambda c: order[c])[:12]
    print("wrote", _TABLE_PATH)
    print("strongest classes:", " ".join(best))
    for c in ("AA", "AKs", "72o", "JTs", "22"):
        eqs = " ".join(f"{preflop_equity(class_example(c), n):.3f}" for n in (1, 5))
        print(f"  {c:>4}  pct={order[c]:.3f}  eq(1opp,5opp)= {eqs}")
