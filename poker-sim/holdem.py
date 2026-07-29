#!/usr/bin/env python3
"""Texas Hold'em 100-tournament simulation."""

import random, json
from collections import Counter
from itertools import combinations

# ── Card Engine ───────────────────────────────────────────────────────────────
RANKS = '23456789TJQKA'
SUITS = 'cdhs'

def new_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def rv(c):
    return RANKS.index(c[0])

def score5(five):
    rs = sorted([rv(c) for c in five], reverse=True)
    ss = [c[1] for c in five]
    fl = len(set(ss)) == 1
    st = len(set(rs)) == 5 and rs[0] - rs[-1] == 4
    if set(rs) == {12, 0, 1, 2, 3}:
        st, rs = True, [3, 2, 1, 0, -1]
    cnt = Counter(rs)
    bf = sorted(rs, key=lambda r: (cnt[r], r), reverse=True)
    fq = sorted(cnt.values(), reverse=True)
    if st and fl:         return (8,) + tuple(rs)
    if fq[0] == 4:        return (7,) + tuple(bf)
    if fq[:2] == [3, 2]:  return (6,) + tuple(bf)
    if fl:                return (5,) + tuple(rs)
    if st:                return (4,) + tuple(rs)
    if fq[0] == 3:        return (3,) + tuple(bf)
    if fq[:2] == [2, 2]:  return (2,) + tuple(bf)
    if fq[0] == 2:        return (1,) + tuple(bf)
    return (0,) + tuple(rs)

def best_hand(cards):
    return max(score5(list(c)) for c in combinations(cards, 5))

# ── Hand Strength Estimators ──────────────────────────────────────────────────
def pf_str(hole):
    r = sorted([rv(c) for c in hole], reverse=True)
    suited = hole[0][1] == hole[1][1]
    if r[0] == r[1]:
        return 0.46 + r[0] / 28.0
    gap = r[0] - r[1]
    return max(0.05, min(0.92,
        (r[0] + r[1]) / 26.0 * 0.76 + (0.08 if suited else 0.0)
        - gap * 0.014 + 0.11))

def po_str(hole, comm):
    v = best_hand(hole + comm)
    return min(0.99, v[0] / 8.0 + sum(v[1:]) / (8.0 * 80.0))

def hs(hole, comm):
    return po_str(hole, comm) if comm else pf_str(hole)

# ── Six Strategies ────────────────────────────────────────────────────────────
# Args: (hole, comm, pot, to_call, stack, pos, n_active, rng)
#   to_call  = chips needed to stay in (already capped at stack by engine)
# Return: ('fold'|'check'|'call'|'raise'|'allin', raise_increment)
#   raise: engine commits min(stack, to_call + raise_increment)

def s0_maniac(hole, comm, pot, tc, stk, pos, nact, rng):
    """P1 – The Maniac: always shove."""
    return ('allin', stk)


def s1_calculator(hole, comm, pot, tc, stk, pos, nact, rng):
    """P2 – The Calculator: pot-odds + equity; size bets proportionally."""
    s = hs(hole, comm)
    if tc > 0:
        odds = tc / (pot + tc + 1)
        if s < odds * 0.88:
            return ('fold', 0)
    if s > 0.75:
        inc = max(pot // 2, tc + 1)
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if s > 0.58:
        if tc > 0:
            return ('call', tc)
        inc = max(1, pot // 3)
        return ('allin', stk) if inc >= stk else ('raise', inc)
    if s > 0.38:
        if tc == 0:
            return ('check', 0)
        if tc <= pot // 3 + 1:
            return ('call', tc)
        return ('fold', 0)
    return ('check', 0) if tc == 0 else ('fold', 0)


def s2_tag(hole, comm, pot, tc, stk, pos, nact, rng):
    """P3 – TAG (Tight-Aggressive): premium range only, heavy sizing."""
    s = hs(hole, comm)
    if not comm:                       # pre-flop
        if s < 0.44:
            return ('fold', 0) if tc > 0 else ('check', 0)
        inc = max(tc * 2 + 1, pot // 2 + 1)
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if s > 0.625:
        inc = max(tc + 1, int(pot * 0.65))
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if s > 0.375:
        if tc == 0:
            return ('check', 0)
        if tc <= pot // 3 + 1:
            return ('call', tc)
        return ('fold', 0)
    return ('check', 0) if tc == 0 else ('fold', 0)


def s3_bluffer(hole, comm, pot, tc, stk, pos, nact, rng):
    """P4 – The Bluffer: polarised range — value-bet monsters, bluff air."""
    s = hs(hole, comm)
    bluff = rng.random() < 0.28 and s < 0.22
    if s > 0.625 or bluff:
        inc = max(tc + 1, int(pot * 0.85))
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if 0.30 < s <= 0.625:
        if tc == 0:
            return ('check', 0)
        if tc <= pot // 3 + 1:
            return ('call', tc)
        return ('fold', 0)
    return ('check', 0) if tc == 0 else ('fold', 0)


def s4_station(hole, comm, pot, tc, stk, pos, nact, rng):
    """P5 – Calling Station: never folds under 65% stack, raises only monsters."""
    s = hs(hole, comm)
    if s > 0.75:
        inc = max(tc + 1, int(pot * 0.60))
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if tc <= int(stk * 0.65):
        return ('call', tc) if tc > 0 else ('check', 0)
    if s > 0.42:
        return ('call', min(tc, stk))
    return ('fold', 0)


def s5_position(hole, comm, pot, tc, stk, pos, nact, rng):
    """P6 – Position Player: range scales with seat, steals blinds in late."""
    ratio = pos / max(1, nact - 1)   # 0 = UTG, 1 = button
    s = hs(hole, comm)
    if not comm:
        thresh = 0.52 - ratio * 0.22
        if s < thresh:
            if tc == 0 and ratio >= 0.70:
                steal = max(3, int(pot * 0.90))
                return ('allin', stk) if steal >= stk else ('raise', steal)
            return ('fold', 0) if tc > 0 else ('check', 0)
        inc = max(tc * 3 + 1, int(pot * (0.60 + ratio * 0.30)))
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    thresh = 0.50 - ratio * 0.15
    if s > thresh:
        inc = max(1, int(pot * (0.45 + ratio * 0.40)))
        if tc > 0 and inc <= tc:
            return ('call', tc)
        return ('allin', stk) if tc + inc >= stk else ('raise', inc)
    if tc == 0:
        return ('check', 0)
    if tc <= pot // 3 + 1:
        return ('call', tc)
    return ('fold', 0)


STRATS = [s0_maniac, s1_calculator, s2_tag, s3_bluffer, s4_station, s5_position]
NAMES  = [
    "P1: The Maniac (All-In)",
    "P2: The Calculator",
    "P3: TAG (Tight-Aggressive)",
    "P4: The Bluffer",
    "P5: Calling Station",
    "P6: Position Player",
]

# ── Player ────────────────────────────────────────────────────────────────────
class P:
    __slots__ = ['pid','strat','stack','hole','folded','allin','bet','invested']
    def __init__(self, pid, strat, stack):
        self.pid=pid; self.strat=strat; self.stack=stack
        self.hole=[]; self.folded=False; self.allin=False
        self.bet=0; self.invested=0

# ── Betting Round ─────────────────────────────────────────────────────────────
def run_bet(players, pot, max_bet, order, comm, rng):
    queue  = [p for p in order if not p.folded and not p.allin and p.stack > 0]
    in_q   = {p.pid for p in queue}

    while queue:
        p = queue.pop(0)
        in_q.discard(p.pid)
        if p.folded or p.allin or p.stack == 0:
            continue

        tc = min(max(0, max_bet - p.bet), p.stack)
        n_act  = sum(1 for x in players if not x.folded)
        active = [x for x in players if not x.folded]
        pos    = next((i for i,x in enumerate(active) if x.pid==p.pid), 0)

        action, amt = p.strat(p.hole, comm, pot, tc, p.stack, pos, n_act, rng)

        if action == 'fold':
            p.folded = True

        elif action == 'allin':
            c = p.stack
            p.stack=0; p.bet+=c; p.invested+=c; pot+=c; p.allin=True
            if p.bet > max_bet:
                max_bet = p.bet
                for o in players:
                    if (o.pid!=p.pid and not o.folded and not o.allin
                            and o.stack>0 and o.pid not in in_q):
                        queue.append(o); in_q.add(o.pid)

        elif action == 'raise':
            inc = max(1, int(amt))
            c   = min(tc + inc, p.stack)
            p.stack-=c; p.bet+=c; p.invested+=c; pot+=c
            if p.stack == 0: p.allin = True
            if p.bet > max_bet:
                max_bet = p.bet
                for o in players:
                    if (o.pid!=p.pid and not o.folded and not o.allin
                            and o.stack>0 and o.pid not in in_q):
                        queue.append(o); in_q.add(o.pid)

        else:  # call / check
            c = min(tc, p.stack)
            p.stack-=c; p.bet+=c; p.invested+=c; pot+=c
            if p.stack == 0: p.allin = True

    return pot, max_bet

# ── Side-Pot Award ────────────────────────────────────────────────────────────
def award_pots(players, community):
    all_inv = [(p.pid, p.invested) for p in players if p.invested > 0]
    if not all_inv:
        return
    levels = sorted(set(v for _,v in all_inv))
    prev   = 0
    for level in levels:
        layer    = level - prev
        c_pids   = {pid for pid,v in all_inv if v >= level}
        pot_size = layer * len(c_pids)
        cands    = [p for p in players if p.pid in c_pids and not p.folded]
        if not cands:
            cands = [p for p in players if not p.folded]
        if cands and pot_size > 0:
            eligible = [p for p in cands if len(p.hole + community) >= 5]
            if not eligible:
                cands[0].stack += pot_size
            else:
                scored = [(best_hand(p.hole + community), p) for p in eligible]
                top    = max(sc for sc,_ in scored)
                wins   = [p for sc,p in scored if sc == top]
                each   = pot_size // len(wins)
                rem    = pot_size %  len(wins)
                for w in wins: w.stack += each
                if rem: wins[0].stack += rem
        prev = level

# ── Single Hand ───────────────────────────────────────────────────────────────
def play_hand(players, dealer_idx, sb, bb, rng):
    n = len(players)
    for p in players:
        p.hole=[]; p.folded=(p.stack<=0); p.allin=False; p.bet=0; p.invested=0

    alive = [p for p in players if not p.folded]
    if len(alive) <= 1:
        return

    deck = new_deck(); rng.shuffle(deck)
    for p in alive:
        p.hole = [deck.pop(), deck.pop()]

    def next_after(idx):
        for i in range(1, n+1):
            q = players[(idx+i) % n]
            if not q.folded and q.stack > 0:
                return (idx+i) % n, q
        return idx, None

    sb_idx, sb_p = next_after(dealer_idx)
    bb_idx, bb_p = next_after(sb_idx)
    if sb_p is None or bb_p is None:
        return

    pot = 0
    def blind(p, amt):
        nonlocal pot
        c = min(amt, p.stack)
        p.stack-=c; p.bet=c; p.invested=c; pot+=c
        if p.stack == 0: p.allin = True

    blind(sb_p, sb); blind(bb_p, bb)
    max_bet = bb_p.bet

    def ao_after(idx):        # action starting after idx
        order = []
        for i in range(1, n+1):
            q = players[(idx+i) % n]
            if not q.folded and not q.allin and q.stack > 0:
                order.append(q)
        return order

    def ao_from(idx):         # action starting from idx
        order = []
        for i in range(n):
            q = players[(idx+i) % n]
            if not q.folded and not q.allin and q.stack > 0:
                order.append(q)
        return order

    def active_count():
        return sum(1 for p in players if not p.folded)

    # Pre-flop (UTG = left of BB acts first)
    pot, max_bet = run_bet(players, pot, max_bet, ao_after(bb_idx), [], rng)
    for p in players: p.bet = 0

    community = []
    for n_cards in [3, 1, 1]:      # flop / turn / river
        if active_count() <= 1:
            break
        community += [deck.pop() for _ in range(n_cards)]
        pot, _ = run_bet(players, pot, 0, ao_from(sb_idx), community, rng)
        for p in players: p.bet = 0

    # Award
    nf = [p for p in players if not p.folded]
    if len(nf) == 1:
        nf[0].stack += pot
    else:
        award_pots(players, community)

# ── Tournament ────────────────────────────────────────────────────────────────
def run_tournament(starting_stack, rng):
    players     = [P(i, STRATS[i], starting_stack) for i in range(6)]
    dealer_idx  = 0
    MAX_HANDS   = 8000

    for hand_num in range(MAX_HANDS):
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1:
            return alive[0].pid

        # Blind escalation: double every 30 hands
        level = hand_num // 30
        sb = 5 * (2 ** level)
        bb = 10 * (2 ** level)

        play_hand(players, dealer_idx, sb, bb, rng)

        dealer_idx = (dealer_idx + 1) % 6
        steps = 0
        while players[dealer_idx].stack <= 0 and steps < 6:
            dealer_idx = (dealer_idx + 1) % 6
            steps += 1

    # Hit hand limit — chip leader wins
    return max(range(6), key=lambda i: players[i].stack)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    rng  = random.Random(42)
    wins = [0] * 6

    print("Running 100 Texas Hold'em tournaments …", flush=True)
    for sim in range(100):
        w = run_tournament(1000, rng)
        wins[w] += 1
        if (sim + 1) % 25 == 0:
            print(f"  {sim+1}/100 done", flush=True)

    print("\n=== RESULTS ===")
    for i, (name, w) in enumerate(zip(NAMES, wins)):
        bar = "█" * w
        print(f"  {name:<30} {w:>3}  {bar}")

    with open('/tmp/claude-0/-home-user-spoderman/ad000742-a71f-5d30-a2b2-c86bd5679d34/scratchpad/results.json', 'w') as f:
        json.dump({'names': NAMES, 'wins': wins}, f)
    print("\nSaved results.json")

if __name__ == '__main__':
    main()
