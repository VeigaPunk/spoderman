"""Monte Carlo equity estimation and the Chen preflop formula."""

from .evaluator import evaluate7


def estimate_equity(hole, board, n_opps, samples, rng):
    """Estimated pot share (win + split share) of `hole` on `board` versus
    `n_opps` random opponent hands run to the river."""
    if n_opps <= 0:
        return 1.0
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(board)
    need = need_board + 2 * n_opps
    hole = list(hole)
    board = list(board)
    total = 0.0
    for _ in range(samples):
        drawn = rng.sample(deck, need)
        full = board + drawn[:need_board]
        mine = evaluate7(hole + full)
        ties = 0
        beaten = False
        idx = need_board
        for _o in range(n_opps):
            ov = evaluate7(drawn[idx:idx + 2] + full)
            idx += 2
            if ov > mine:
                beaten = True
                break
            if ov == mine:
                ties += 1
        if not beaten:
            total += 1.0 / (1 + ties)
    return total / samples


def chen_score(hole):
    """Bill Chen's preflop hand formula. AA=20, KK=16, AKs=12, 72o≈-1."""
    r1, r2 = hole[0] >> 2, hole[1] >> 2
    hi, lo = (r1, r2) if r1 >= r2 else (r2, r1)
    base = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(hi, (hi + 2) / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if hole[0] & 3 == hole[1] & 3:
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 10:  # small-gap connectors below queen
        score += 1
    return score
