#!/usr/bin/env python3
"""Texas Hold'em tournament simulator.

Six players, identical starting stacks. Players 2-6 run elaborate strategies;
Player 1 runs the legendary algorithm:

    if my_turn
    then bet = All in
    fi

100 tournaments are simulated; the histogram of tournament winners is printed.
No strategy has access to any other player's strategy — only public actions.
"""

import random
from collections import Counter

# ---------------------------------------------------------------- evaluator

RANK_CHR = {14: 'A', 13: 'K', 12: 'Q', 11: 'J', 10: 'T'}


def straight_high(ranks):
    rs = sorted(set(ranks), reverse=True)
    if 14 in rs:
        rs.append(1)
    run = 1
    for i in range(1, len(rs)):
        if rs[i] == rs[i - 1] - 1:
            run += 1
            if run >= 5:
                return rs[i] + 4
        else:
            run = 1
    return None


def evaluate7(cards):
    """Best 5-card rank of 7 cards -> comparable tuple (higher wins)."""
    ranks = [c[0] for c in cards]
    cnt = Counter(ranks)
    suits = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in suits.items() if n >= 5), None)
    if flush_suit is not None:
        fr = [c[0] for c in cards if c[1] == flush_suit]
        sh = straight_high(fr)
        if sh:
            return (8, sh)
    groups = sorted(cnt.items(), key=lambda kv: (-kv[1], -kv[0]))
    if groups[0][1] == 4:
        quad = groups[0][0]
        return (7, quad, max(r for r in ranks if r != quad))
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    if flush_suit is not None:
        return (5,) + tuple(sorted(fr, reverse=True)[:5])
    sh = straight_high(ranks)
    if sh:
        return (4, sh)
    if groups[0][1] == 3:
        t = groups[0][0]
        return (3, t) + tuple(sorted((r for r in ranks if r != t), reverse=True)[:2])
    if groups[0][1] == 2 and groups[1][1] == 2:
        hi, lo = groups[0][0], groups[1][0]
        return (2, hi, lo, max(r for r in ranks if r not in (hi, lo)))
    if groups[0][1] == 2:
        p = groups[0][0]
        return (1, p) + tuple(sorted((r for r in ranks if r != p), reverse=True)[:3])
    return (0,) + tuple(sorted(ranks, reverse=True)[:5])


# ---------------------------------------------------------------- helpers

def full_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


def chen_score(hole):
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if s1 == s2:
        pts += 2
    gap = hi - lo - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        pts += 1
    return pts


def has_flush_draw(cards):
    return any(n == 4 for n in Counter(c[1] for c in cards).values())


def has_oesd(cards):
    rs = set(c[0] for c in cards)
    if 14 in rs:
        rs.add(1)
    return any(all(x + k in rs for k in range(4)) for x in range(1, 12))


def mc_equity(hole, board, n_opps, iters, rng):
    """Monte-Carlo equity vs random hands. Opponents capped at 2 for speed."""
    n_opps = min(n_opps, 2)
    seen = set(hole) | set(board)
    rest = [c for c in full_deck() if c not in seen]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        rng.shuffle(rest)
        k = 0
        opp_holes = []
        for _ in range(n_opps):
            opp_holes.append(rest[k:k + 2])
            k += 2
        full_board = board + rest[k:k + need_board]
        mine = evaluate7(hole + full_board)
        best_opp = max(evaluate7(h + full_board) for h in opp_holes)
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


def top_pair_or_better(hole, board):
    if not board:
        return False
    rank = evaluate7(hole + board) if len(hole + board) >= 5 else None
    if rank is None:
        return False
    if rank[0] >= 2:
        return True
    if rank[0] == 1:
        pair = rank[1]
        return pair >= max(c[0] for c in board) and any(c[0] == pair for c in hole)
    return False


# ---------------------------------------------------------------- strategies

class Strategy:
    def __init__(self, idx, rng):
        self.idx = idx
        self.rng = rng

    def act(self, st):
        return ('fold', 0)

    def observe(self, event):
        pass


class AllInBot(Strategy):
    """if my_turn then bet = All in fi"""

    def act(self, st):
        return ('raise', st['my_bet'] + st['stack'])


class TightAggressive(Strategy):
    """TAG: Chen-formula preflop ranges, value-betting made hands, pot-odds
    calls with draws, respects heavy aggression without the goods."""

    def act(self, st):
        hole, board = st['hole'], st['board']
        to_call, pot, stack, bb = st['to_call'], st['pot'], st['stack'], st['bb']
        if st['street'] == 'preflop':
            sc = chen_score(hole)
            if to_call > stack * 0.25 or to_call > 6 * bb:
                if sc >= 10:
                    return ('raise', st['my_bet'] + stack)
                return ('fold', 0)
            if sc >= 9:
                return ('raise', max(st['current_bet'] + st['min_raise'], 3 * bb))
            if sc >= 6.5 and to_call <= 3 * bb:
                return ('call', 0)
            return ('fold', 0)
        strong = top_pair_or_better(hole, board)
        rank = evaluate7(hole + board)
        drawing = has_flush_draw(hole + board) or has_oesd(hole + board)
        pot_odds = to_call / (pot + to_call) if to_call else 0.0
        if rank[0] >= 2:
            return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.75)))
        if strong:
            if to_call == 0:
                return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.6)))
            if pot_odds < 0.4:
                return ('call', 0)
            return ('fold', 0)
        if drawing and pot_odds < 0.32:
            if to_call == 0 and self.rng.random() < 0.4:
                return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.5)))
            return ('call', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


class LooseAggressive(Strategy):
    """LAG: opens wide in late position, c-bets relentlessly, semi-bluffs
    draws, mixes in pure bluffs, occasionally slow-plays monsters."""

    def __init__(self, idx, rng):
        super().__init__(idx, rng)
        self.aggressor = False

    def act(self, st):
        hole, board = st['hole'], st['board']
        to_call, pot, stack, bb = st['to_call'], st['pot'], st['stack'], st['bb']
        late = st['position'] >= st['n_seats'] - 2
        if st['street'] == 'preflop':
            self.aggressor = False
            sc = chen_score(hole)
            if to_call > stack * 0.3:
                if sc >= 9.5:
                    return ('raise', st['my_bet'] + stack)
                return ('fold', 0)
            thresh = 5 if late else 7
            if sc >= thresh + 2 or (sc >= thresh and self.rng.random() < 0.6):
                self.aggressor = True
                return ('raise', max(st['current_bet'] + st['min_raise'],
                                     int(2.5 * bb)))
            if sc >= thresh and to_call <= 2 * bb:
                return ('call', 0)
            return ('fold', 0)
        rank = evaluate7(hole + board)
        drawing = has_flush_draw(hole + board) or has_oesd(hole + board)
        pot_odds = to_call / (pot + to_call) if to_call else 0.0
        if rank[0] >= 3:
            if self.rng.random() < 0.2 and to_call == 0:
                return ('call', 0)
            return ('raise', st['current_bet'] + max(st['min_raise'], pot))
        if rank[0] == 2 or top_pair_or_better(hole, board):
            if pot_odds > 0.45:
                return ('call', 0)
            return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.7)))
        if drawing:
            if to_call == 0 or (pot_odds < 0.3 and self.rng.random() < 0.5):
                return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.6)))
            if pot_odds < 0.35:
                return ('call', 0)
            return ('fold', 0)
        if self.aggressor and to_call == 0 and self.rng.random() < 0.7:
            return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.55)))
        if to_call == 0:
            if self.rng.random() < 0.15:
                return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.5)))
            return ('call', 0)
        if pot_odds < 0.2 and self.rng.random() < 0.25:
            return ('call', 0)
        return ('fold', 0)


class Rock(Strategy):
    """Nit: premium hands only, set-mines cheap with small pairs, and once
    committed with the goods, piles the chips in."""

    def act(self, st):
        hole, board = st['hole'], st['board']
        to_call, pot, stack, bb = st['to_call'], st['pot'], st['stack'], st['bb']
        (r1, _), (r2, _) = hole
        pair = r1 == r2
        if st['street'] == 'preflop':
            premium = (pair and r1 >= 10) or {r1, r2} == {14, 13} or \
                (14 in (r1, r2) and 12 in (r1, r2) and hole[0][1] == hole[1][1])
            if premium:
                if to_call > 4 * bb:
                    return ('raise', st['my_bet'] + stack)
                return ('raise', max(st['current_bet'] + st['min_raise'], 4 * bb))
            if pair and to_call <= max(bb, stack * 0.05):
                return ('call', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)
        rank = evaluate7(hole + board)
        board_top = max(c[0] for c in board)
        overpair = pair and r1 > board_top
        if rank[0] >= 3 or overpair:
            if to_call >= stack:
                return ('call', 0)
            return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.8)))
        if rank[0] >= 1 and top_pair_or_better(hole, board):
            pot_odds = to_call / (pot + to_call) if to_call else 0.0
            if pot_odds < 0.35:
                return ('call', 0)
            return ('fold', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


class MonteCarloBot(Strategy):
    """Equity machine: estimates win probability by simulation postflop and
    acts on equity vs pot odds; Chen ranges preflop to save the CPU fans."""

    def act(self, st):
        hole, board = st['hole'], st['board']
        to_call, pot, stack, bb = st['to_call'], st['pot'], st['stack'], st['bb']
        if st['street'] == 'preflop':
            sc = chen_score(hole)
            if to_call > stack * 0.3:
                eq = mc_equity(hole, [], st['n_active'] - 1, 60, self.rng)
                if eq > 0.55:
                    return ('raise', st['my_bet'] + stack)
                return ('fold', 0)
            if sc >= 8.5:
                return ('raise', max(st['current_bet'] + st['min_raise'], 3 * bb))
            if sc >= 6 and to_call <= 3 * bb:
                return ('call', 0)
            return ('fold', 0)
        eq = mc_equity(hole, board, st['n_active'] - 1, 60, self.rng)
        pot_odds = to_call / (pot + to_call) if to_call else 0.0
        if eq > 0.78:
            return ('raise', st['my_bet'] + stack)
        if eq > 0.6:
            return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.7)))
        if to_call == 0:
            if eq > 0.5:
                return ('raise', st['current_bet'] + max(st['min_raise'], int(pot * 0.5)))
            return ('call', 0)
        if eq > pot_odds + 0.05:
            return ('call', 0)
        return ('fold', 0)


class AdaptiveProfiler(Strategy):
    """Exploiter: builds per-opponent profiles from public actions (shove
    frequency, aggression) and widens calling ranges drastically against
    maniacs, while playing solid TAG poker otherwise."""

    def __init__(self, idx, rng):
        super().__init__(idx, rng)
        self.hands_seen = Counter()
        self.shoves = Counter()
        self.base = TightAggressive(idx, rng)

    def observe(self, event):
        if event[0] == 'hand_start':
            for i in event[1]:
                self.hands_seen[i] += 1
        elif event[0] == 'action':
            _, actor, street, kind, amount, all_in = event
            if kind == 'raise' and all_in:
                self.shoves[actor] += 1

    def maniac(self, i):
        seen = self.hands_seen[i]
        return seen >= 5 and self.shoves[i] / seen > 0.4

    def act(self, st):
        agg = st['aggressor']
        facing_maniac = agg is not None and agg != self.idx and self.maniac(agg)
        if facing_maniac and st['to_call'] > 0:
            hole, board = st['hole'], st['board']
            if st['street'] == 'preflop':
                sc = chen_score(hole)
                if sc >= 6.5:
                    return ('call', 0)
                return ('fold', 0)
            eq = mc_equity(hole, board, st['n_active'] - 1, 50, self.rng)
            pot_odds = st['to_call'] / (st['pot'] + st['to_call'])
            if eq > pot_odds:
                return ('call', 0)
            return ('fold', 0)
        return self.base.act(st)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, idx, name, stack, strategy):
        self.idx = idx
        self.name = name
        self.stack = stack
        self.strategy = strategy
        self.reset_hand()

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.total_bet = 0
        self.bet_round = 0
        self.acted = False


def commit(p, amount):
    amount = min(amount, p.stack)
    p.stack -= amount
    p.bet_round += amount
    p.total_bet += amount
    return amount


def build_state(p, players, alive, board, street, current_bet, min_raise, bb,
                aggressor, position):
    contenders = [q for q in alive if not q.folded]
    return {
        'hole': p.hole, 'board': board, 'street': street,
        'pot': sum(q.total_bet for q in alive),
        'to_call': current_bet - p.bet_round,
        'current_bet': current_bet, 'min_raise': min_raise,
        'my_bet': p.bet_round, 'stack': p.stack, 'bb': bb,
        'n_active': len(contenders), 'n_seats': len(alive),
        'my_idx': p.idx, 'position': position,
        'aggressor': aggressor,
        'opp_stacks': {q.idx: q.stack for q in alive if q is not p},
    }


def betting_round(players, alive, order, board, street, current_bet, min_raise,
                  bb, aggressor, broadcast):
    for p in alive:
        p.acted = False
    n = len(order)
    i = 0
    guard = 0
    while True:
        guard += 1
        if guard > 500:
            break
        contenders = [p for p in alive if not p.folded]
        if len(contenders) <= 1:
            break
        actionable = [p for p in contenders if p.stack > 0]
        if not actionable or all(p.acted and p.bet_round == current_bet
                                 for p in actionable):
            break
        p = order[i % n]
        i += 1
        if p.folded or p.stack == 0:
            continue
        if p.acted and p.bet_round == current_bet:
            continue
        position = order.index(p)
        st = build_state(p, players, alive, board, street, current_bet,
                         min_raise, bb, aggressor, position)
        try:
            kind, amt = p.strategy.act(st)
        except Exception:
            kind, amt = 'fold', 0
        to_call = current_bet - p.bet_round
        if kind == 'fold' and to_call == 0:
            kind = 'call'
        if kind == 'raise':
            target = min(int(amt), p.bet_round + p.stack)
            max_target = p.bet_round + p.stack
            if target <= current_bet:
                kind = 'call'
            elif target < current_bet + min_raise and target < max_target:
                kind = 'call'
            else:
                paid = commit(p, target - p.bet_round)
                if p.bet_round - current_bet >= min_raise:
                    min_raise = p.bet_round - current_bet
                current_bet = p.bet_round
                aggressor = p.idx
                for q in alive:
                    if q is not p:
                        q.acted = False
                p.acted = True
                broadcast(('action', p.idx, street, 'raise', paid, p.stack == 0))
                continue
        if kind == 'call':
            paid = commit(p, to_call)
            p.acted = True
            broadcast(('action', p.idx, street, 'call', paid, p.stack == 0))
        else:
            p.folded = True
            p.acted = True
            broadcast(('action', p.idx, street, 'fold', 0, False))
    return current_bet, aggressor


def award_pots(alive, board):
    contenders = [p for p in alive if not p.folded]
    if len(contenders) == 1:
        contenders[0].stack += sum(p.total_bet for p in alive)
        return
    scores = {p.idx: evaluate7(p.hole + board) for p in contenders}
    levels = sorted(set(p.total_bet for p in alive if p.total_bet > 0))
    prev = 0
    for lvl in levels:
        layer = sum(min(p.total_bet, lvl) - min(p.total_bet, prev)
                    for p in alive)
        eligible = [p for p in contenders if p.total_bet >= lvl]
        if not eligible:
            eligible = contenders
        best = max(scores[p.idx] for p in eligible)
        winners = [p for p in eligible if scores[p.idx] == best]
        share = layer // len(winners)
        for p in winners:
            p.stack += share
        winners[0].stack += layer - share * len(winners)
        prev = lvl


def play_hand(players, button_seat, sb, bb, rng):
    alive = [p for p in players if p.stack > 0]
    for p in alive:
        p.reset_hand()
    deck = full_deck()
    rng.shuffle(deck)
    for p in alive:
        p.hole = [deck.pop(), deck.pop()]

    def broadcast(event):
        for p in players:
            p.strategy.observe(event)

    broadcast(('hand_start', [p.idx for p in alive], bb))

    b_idx = next(i for i, p in enumerate(alive) if p.idx == button_seat)
    rest = alive[b_idx + 1:] + alive[:b_idx]
    button = alive[b_idx]
    if len(alive) == 2:
        sb_p, bb_p = button, rest[0]
        pre_order = [button, rest[0]]
        post_order = [rest[0], button]
    else:
        sb_p, bb_p = rest[0], rest[1]
        pre_order = rest[2:] + [button] + rest[:2]
        post_order = rest + [button]

    commit(sb_p, sb)
    commit(bb_p, bb)
    current_bet, min_raise = bb, bb
    aggressor = bb_p.idx
    board = []

    current_bet, aggressor = betting_round(
        players, alive, pre_order, board, 'preflop', current_bet, min_raise,
        bb, aggressor, broadcast)

    for street, n_cards in (('flop', 3), ('turn', 1), ('river', 1)):
        if len([p for p in alive if not p.folded]) <= 1:
            break
        board += [deck.pop() for _ in range(n_cards)]
        for p in alive:
            p.bet_round = 0
        current_bet, aggressor = betting_round(
            players, alive, post_order, board, street, 0, bb, bb, None,
            broadcast)

    while len(board) < 5 and len([p for p in alive if not p.folded]) >= 2:
        board.append(deck.pop())
    award_pots(alive, board)


NAMES = [
    'P1 AllIn-Andy   [if my_turn then ALL IN fi]',
    'P2 TAG-Tanya    [tight-aggressive]',
    'P3 LAG-Larry    [loose-aggressive]',
    'P4 Nit-Nigel    [premium-only rock]',
    'P5 MC-Marvin    [monte-carlo equity]',
    'P6 Sherlock     [adaptive profiler]',
]

STRATS = [AllInBot, TightAggressive, LooseAggressive, Rock, MonteCarloBot,
          AdaptiveProfiler]


def run_tournament(seed, start_stack=1000):
    rng = random.Random(seed)
    players = [Player(i, NAMES[i], start_stack, STRATS[i](i, random.Random(seed * 7 + i)))
               for i in range(6)]
    total = start_stack * 6
    button = rng.randrange(6)
    hand_no = 0
    while sum(1 for p in players if p.stack > 0) > 1 and hand_no < 2000:
        level = hand_no // 20
        sb = 10 * (2 ** min(level, 7))
        play_hand(players, button, sb, 2 * sb, rng)
        assert sum(p.stack for p in players) == total, 'chips leaked'
        hand_no += 1
        for _ in range(6):
            button = (button + 1) % 6
            if players[button].stack > 0:
                break
    return max(players, key=lambda p: p.stack).idx


def main(n_sims=100):
    wins = Counter()
    for sim in range(n_sims):
        wins[run_tournament(seed=20260728 + sim)] += 1
        if (sim + 1) % 20 == 0:
            print(f'... {sim + 1}/{n_sims} tournaments done')
    print()
    print('=' * 70)
    print(f'WINNER HISTOGRAM — {n_sims} full tournaments (6 players, 1000 chips each)')
    print('=' * 70)
    peak = max(wins.values()) if wins else 1
    for i in range(6):
        w = wins[i]
        bar = '#' * round(w * 40 / peak)
        print(f'{NAMES[i]:<46} {bar} {w}')
    print('=' * 70)
    champ = max(range(6), key=lambda i: wins[i])
    print(f'WINNER WINNER CHICKEN DINNER (most titles): {NAMES[champ]}')


if __name__ == '__main__':
    main()
