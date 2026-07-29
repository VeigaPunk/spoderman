"""Malmuth-Harville ICM: chip stacks -> prize equity.

Used by the ICM/Nash strategy to convert a chip decision into a payout-ladder
decision.  Small enough to run inline (<= 6 players, <= 3 paid places).
"""

from __future__ import annotations

from functools import lru_cache

DEFAULT_PAYOUTS = (0.50, 0.30, 0.20)


def icm_equity(stacks, payouts=DEFAULT_PAYOUTS):
    """Prize equity per seat under Malmuth-Harville finishing probabilities."""
    live = [(i, s) for i, s in enumerate(stacks) if s > 0]
    if not live:
        return [0.0] * len(stacks)
    if len(live) == 1:
        out = [0.0] * len(stacks)
        out[live[0][0]] = sum(payouts)
        return out

    idx = [i for i, _ in live]
    chips = tuple(s for _, s in live)
    pay = tuple(payouts[:len(live)]) + (0.0,) * max(0, len(live) - len(payouts))
    eq = _equity(chips, pay)
    out = [0.0] * len(stacks)
    for k, i in enumerate(idx):
        out[i] = eq[k]
    return out


@lru_cache(maxsize=200000)
def _equity(chips, pay):
    n = len(chips)
    total = sum(chips)
    if total <= 0:
        return tuple(0.0 for _ in chips)
    eq = [0.0] * n
    for i in range(n):
        p_first = chips[i] / total
        eq[i] += p_first * pay[0]
        if len(pay) > 1 and n > 1:
            rest = chips[:i] + chips[i + 1:]
            sub = _equity(rest, pay[1:])
            for j, v in enumerate(sub):
                k = j if j < i else j + 1
                eq[k] += p_first * v
    return tuple(eq)


def risk_premium(stacks, seat, risk, reward, payouts=DEFAULT_PAYOUTS):
    """Equity needed to profitably call off ``risk`` chips to win ``reward``.

    Returns the ICM-adjusted break-even equity.  Under a flat winner-take-all
    structure this collapses to plain pot odds; on a payout ladder it is
    strictly higher, which is the survival premium.
    """
    base = icm_equity(stacks, payouts)
    win = list(stacks)
    lose = list(stacks)
    risk = min(risk, stacks[seat])
    win[seat] += reward
    lose[seat] -= risk
    # take the chips from / give them to the field, proportionally
    others = [i for i in range(len(stacks)) if i != seat and stacks[i] > 0]
    if not others:
        return 0.5
    pool = sum(stacks[i] for i in others) or 1
    for i in others:
        share = stacks[i] / pool
        win[i] = max(0, win[i] - reward * share)
        lose[i] = lose[i] + risk * share
    up = icm_equity(win, payouts)[seat] - base[seat]
    down = base[seat] - icm_equity(lose, payouts)[seat]
    if up + down <= 0:
        return 0.5
    return down / (up + down)
