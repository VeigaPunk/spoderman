#!/usr/bin/env python3
"""No-limit Texas Hold'em 6-max tournament simulator.

Player 1 runs the galaxy-brain strategy: "if my_turn then bet = All in fi".
Players 2-6 run five elaborate strategies. Nobody knows anybody's algorithm.
100 tournaments, equal starting stacks, escalating blinds, winner take all.
"""

import random
from collections import Counter, deque

RANK_NAMES = {11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
STREETS = ('preflop', 'flop', 'turn', 'river')


# ---------------------------------------------------------------- hand eval

def straight_high(uniq_desc):
    rs = list(uniq_desc)
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


def evaluate(cards):
    """Best 5-card rank from 5-7 cards. Higher tuple wins."""
    ranks = sorted((r for r, s in cards), reverse=True)
    suits = Counter(s for r, s in cards)
    flush_suit = next((s for s, c in suits.items() if c >= 5), None)
    if flush_suit:
        fr = sorted((r for r, s in cards if s == flush_suit), reverse=True)
        sf = straight_high(fr)
        if sf:
            return (8, sf)
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda x: (-x[1], -x[0]))
    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    if flush_suit:
        fr = sorted((r for r, s in cards if s == flush_suit), reverse=True)
        return (5, tuple(fr[:5]))
    st = straight_high(sorted(set(ranks), reverse=True))
    if st:
        return (4, st)
    if groups[0][1] == 3:
        t = groups[0][0]
        kickers = tuple(r for r in ranks if r != t)[:2]
        return (3, t, kickers)
    if len(groups) > 1 and groups[0][1] == 2 and groups[1][1] == 2:
        p1, p2 = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kicker)
    if groups[0][1] == 2:
        p = groups[0][0]
        kickers = tuple(r for r in ranks if r != p)[:3]
        return (1, p, kickers)
    return (0, tuple(ranks[:5]))


def fresh_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


# ---------------------------------------------------------------- helpers

def chen_score(hole):
    """Chen formula-ish preflop hand strength (roughly 0-20)."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(hi, hi / 2.0)
    if r1 == r2:
        pts = max(5, pts * 2)
    if s1 == s2:
        pts += 2
    gap = hi - lo - 1
    if r1 != r2:
        pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
        if gap <= 1 and hi < 12:
            pts += 1
    return pts


def good_vs_random(hole):
    """Is this hand a solid favorite against a random shove?"""
    (r1, _), (r2, _) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    if r1 == r2 and hi >= 7:
        return True
    if hi == 14 and lo >= 9:
        return True
    if hi >= 11 and lo >= 10:
        return True
    return False


def has_flush_draw(hole, board):
    suits = Counter(s for r, s in hole + board)
    return any(c == 4 for c in suits.values())


def has_oesd(hole, board):
    rs = set(r for r, s in hole + board)
    for start in range(2, 12):
        if all(x in rs for x in range(start, start + 4)):
            return True
    return False


def mc_equity(hole, board, n_opps, rng, iters=30):
    """Monte Carlo equity vs random hands."""
    n_opps = min(n_opps, 3)
    known = set(hole + board)
    deck = [c for c in fresh_deck() if c not in known]
    wins = 0.0
    need_board = 5 - len(board)
    for _ in range(iters):
        rng.shuffle(deck)
        idx = 0
        opp_holes = []
        for _ in range(n_opps):
            opp_holes.append(deck[idx:idx + 2])
            idx += 2
        full_board = board + deck[idx:idx + need_board]
        mine = evaluate(hole + full_board)
        best_opp = max(evaluate(oh + full_board) for oh in opp_holes)
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


def made_strength(hole, board):
    """0=air 1=pair 2=top pair+ 3=two pair/trips 4=monster."""
    cat = evaluate(hole + board)[0]
    board_ranks = [r for r, s in board]
    hole_ranks = [r for r, s in hole]
    if cat >= 4:
        return 4
    if cat == 3 or cat == 2:
        return 3
    if cat == 1:
        pair_rank = evaluate(hole + board)[1]
        if pair_rank in hole_ranks and board_ranks and pair_rank >= max(board_ranks):
            return 2
        if pair_rank in hole_ranks or hole_ranks[0] == hole_ranks[1]:
            return 1 if not board_ranks or pair_rank < max(board_ranks) else 2
        return 0  # board pair only
    return 0


# ---------------------------------------------------------------- strategies

class Strategy:
    name = 'base'

    def __init__(self, rng):
        self.rng = rng

    def act(self, s):
        raise NotImplementedError


class AllInBot(Strategy):
    """Player 1. The entire algorithm, verbatim:

        if my_turn
        Then bet = All in
        Fi
    """
    name = 'YOLO (all-in every turn)'

    def act(self, s):
        return ('raise', s['my_street_contrib'] + s['my_chips'])


class TheRock(Strategy):
    """Tight-aggressive grinder. Premium hands only, then max pressure.

    Preflop: opens big pairs and big broadway, 3-bets monsters, folds the
    rest. Refuses to pay off shoves without a near-nuts starting hand.
    Postflop: continuation-bets real equity, semi-bluffs strong draws,
    releases marginal hands to aggression.
    """
    name = 'The Rock (tight-aggressive)'

    def act(self, s):
        hole, board = s['hole'], s['community']
        to_call, pot, chips = s['to_call'], s['pot'], s['my_chips']
        bb = s['bb']
        if s['street'] == 'preflop':
            score = chen_score(hole)
            facing_shove = to_call >= chips * 0.6 or to_call > 8 * bb
            if facing_shove:
                if score >= 11 or good_vs_random(hole) and score >= 9:
                    return ('raise', s['my_street_contrib'] + chips)
                return ('fold', 0)
            if score >= 10:
                return ('raise', max(s['min_raise_to'], s['current_bet'] + 3 * bb))
            if score >= 8 and to_call <= 3 * bb:
                return ('call', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)
        strength = made_strength(hole, board)
        drawing = s['street'] != 'river' and (has_flush_draw(hole, board) or has_oesd(hole, board))
        if strength >= 3:
            target = s['current_bet'] + max(pot, bb * 2)
            return ('raise', target)
        if strength == 2:
            if to_call == 0:
                return ('raise', s['current_bet'] + int(pot * 0.66) + bb)
            if to_call <= pot * 0.75:
                return ('call', 0)
            return ('fold', 0)
        if drawing:
            pot_odds = to_call / (pot + to_call) if to_call else 0
            if to_call == 0 and self.rng.random() < 0.5:
                return ('raise', s['current_bet'] + int(pot * 0.5) + bb)
            if pot_odds < 0.28:
                return ('call', 0)
            return ('fold', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


class TheProfessor(Strategy):
    """Cold equity mathematician. Every decision is EV arithmetic.

    Preflop uses a Chen-formula range model. Postflop runs live Monte
    Carlo equity simulations against random continuing ranges and compares
    equity to pot odds with a risk margin; raises for value when equity
    dominates, calls when priced in, folds when the math says fold.
    """
    name = 'The Professor (Monte Carlo EV)'

    def act(self, s):
        hole, board = s['hole'], s['community']
        to_call, pot, chips = s['to_call'], s['pot'], s['my_chips']
        bb = s['bb']
        if s['street'] == 'preflop':
            score = chen_score(hole)
            facing_shove = to_call >= chips * 0.6
            if facing_shove:
                pot_odds = to_call / (pot + to_call)
                eq = 0.35 + 0.03 * score
                if eq > pot_odds + 0.05 or score >= 10:
                    return ('raise', s['my_street_contrib'] + chips)
                return ('fold', 0)
            if score >= 9:
                return ('raise', max(s['min_raise_to'], s['current_bet'] + 3 * bb))
            if score >= 6 and to_call <= 3 * bb:
                return ('call', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)
        eq = mc_equity(hole, board, s['num_in_hand'] - 1, self.rng)
        if to_call == 0:
            if eq > 0.5 + 0.05 * (s['num_in_hand'] - 1):
                return ('raise', s['current_bet'] + int(pot * 0.6) + bb)
            return ('call', 0)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.72:
            return ('raise', s['current_bet'] + pot)
        if eq > pot_odds + 0.04:
            return ('call', 0)
        return ('fold', 0)


class TheManiac(Strategy):
    """Loose-aggressive chaos agent. Relentless pressure, wide ranges.

    Opens over half of all hands, three-bets light, barrels flops with
    air, and leans on fold equity. Retains just enough discipline to
    release total garbage when the bets get stack-threatening.
    """
    name = 'The Maniac (loose-aggressive)'

    def act(self, s):
        hole, board = s['hole'], s['community']
        to_call, pot, chips = s['to_call'], s['pot'], s['my_chips']
        bb = s['bb']
        if s['street'] == 'preflop':
            score = chen_score(hole)
            facing_shove = to_call >= chips * 0.6
            if facing_shove:
                if score >= 8 or good_vs_random(hole) or self.rng.random() < 0.08:
                    return ('raise', s['my_street_contrib'] + chips)
                return ('fold', 0)
            if score >= 5 or self.rng.random() < 0.35:
                return ('raise', max(s['min_raise_to'], s['current_bet'] + int(bb * self.rng.uniform(2.5, 4))))
            if to_call <= 2 * bb:
                return ('call', 0)
            return ('fold', 0)
        strength = made_strength(hole, board)
        drawing = s['street'] != 'river' and (has_flush_draw(hole, board) or has_oesd(hole, board))
        if strength >= 2 or drawing:
            return ('raise', s['current_bet'] + int(pot * self.rng.uniform(0.6, 1.2)) + bb)
        if to_call == 0:
            if self.rng.random() < 0.4:
                return ('raise', s['current_bet'] + int(pot * 0.7) + bb)
            return ('call', 0)
        if to_call > chips * 0.4 and strength == 0:
            return ('fold', 0)
        if strength >= 1 or self.rng.random() < 0.25:
            return ('call', 0)
        return ('fold', 0)


class TheChameleon(Strategy):
    """Exploitative profiler. Builds a live dossier on every opponent.

    Tracks VPIP, raise frequency, and shove frequency from the public
    action stream. Versus chronic shovers it flips into trap mode and
    snap-calls with any hand that crushes a random range; versus nits it
    steals relentlessly; versus maniacs it check-calls down light.
    """
    name = 'The Chameleon (exploitative profiler)'

    def act(self, s):
        hole, board = s['hole'], s['community']
        to_call, pot, chips = s['to_call'], s['pot'], s['my_chips']
        bb = s['bb']
        stats = s['stats']

        shover_in_pot = False
        for pid in s['in_hand_ids']:
            if pid == s['my_id']:
                continue
            st = stats.get(pid, {})
            hands = max(1, st.get('hands', 0))
            if st.get('allins', 0) / hands > 0.5 and st.get('hands', 0) >= 3:
                shover_in_pot = True

        facing_shove = to_call >= chips * 0.6 and to_call > 0
        if facing_shove:
            if shover_in_pot:
                if good_vs_random(hole) or chen_score(hole) >= 8:
                    return ('raise', s['my_street_contrib'] + chips)
                return ('fold', 0)
            if chen_score(hole) >= 11 if s['street'] == 'preflop' else made_strength(hole, board) >= 3:
                return ('raise', s['my_street_contrib'] + chips)
            return ('fold', 0)

        if s['street'] == 'preflop':
            score = chen_score(hole)
            opps_tight = all(
                stats.get(pid, {}).get('vpip', 0) / max(1, stats.get(pid, {}).get('hands', 1)) < 0.3
                for pid in s['in_hand_ids'] if pid != s['my_id'] and stats.get(pid, {}).get('hands', 0) >= 5
            )
            if shover_in_pot and score < 8:
                return ('fold', 0) if to_call > 0 else ('call', 0)
            if score >= 9:
                return ('raise', max(s['min_raise_to'], s['current_bet'] + 3 * bb))
            if score >= 5 and opps_tight and s['current_bet'] <= bb:
                return ('raise', s['current_bet'] + int(2.5 * bb))
            if score >= 6 and to_call <= 2 * bb:
                return ('call', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        strength = made_strength(hole, board)
        aggressor_loose = any(
            stats.get(pid, {}).get('raises', 0) / max(1, stats.get(pid, {}).get('hands', 1)) > 1.0
            for pid in s['in_hand_ids'] if pid != s['my_id']
        )
        if strength >= 3:
            if aggressor_loose and to_call == 0:
                return ('call', 0)  # trap the maniac
            return ('raise', s['current_bet'] + max(pot, 2 * bb))
        if strength == 2:
            if to_call <= pot * (0.9 if aggressor_loose else 0.6):
                return ('call', 0) if to_call > 0 else ('raise', s['current_bet'] + int(pot * 0.5) + bb)
            return ('fold', 0)
        if strength == 1 and aggressor_loose and to_call <= pot * 0.5:
            return ('call', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


class TheBanker(Strategy):
    """Stack-pressure tactician. Plays the tournament, not just the cards.

    Computes M-ratio every decision. Short: disciplined push/fold. Big
    stack: bullies medium stacks who can't afford to call. Medium:
    survival-first tight play, avoids coin flips with covering stacks,
    commits only with near-nut equity.
    """
    name = 'The Banker (stack-pressure/ICM)'

    def act(self, s):
        hole, board = s['hole'], s['community']
        to_call, pot, chips = s['to_call'], s['pot'], s['my_chips']
        bb = s['bb']
        score = chen_score(hole)
        m_ratio = chips / max(1, s['sb'] + bb)
        avg_stack = sum(o['chips'] for o in s['players']) / len(s['players'])
        big_stack = chips > 1.5 * avg_stack

        facing_shove = to_call >= chips * 0.6 and to_call > 0
        if facing_shove:
            covered = to_call >= chips
            thresh = 10 if covered else 8
            strong_now = score >= thresh if s['street'] == 'preflop' else made_strength(hole, board) >= 3
            if strong_now:
                return ('raise', s['my_street_contrib'] + chips)
            return ('fold', 0)

        if s['street'] == 'preflop':
            if m_ratio < 5:
                if score >= 6 or hole[0][0] == hole[1][0] or max(hole[0][0], hole[1][0]) == 14:
                    return ('raise', s['my_street_contrib'] + chips)
                return ('fold', 0) if to_call > 0 else ('call', 0)
            if big_stack and score >= 5 and s['current_bet'] <= bb:
                return ('raise', s['current_bet'] + 3 * bb)
            if score >= 9:
                return ('raise', max(s['min_raise_to'], s['current_bet'] + 3 * bb))
            if score >= 7 and to_call <= 2 * bb:
                return ('call', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        strength = made_strength(hole, board)
        if strength >= 3:
            return ('raise', s['current_bet'] + max(pot, 2 * bb))
        if strength == 2:
            if to_call == 0:
                return ('raise', s['current_bet'] + int(pot * 0.5) + bb)
            if to_call <= pot * 0.5 and to_call < chips * 0.25:
                return ('call', 0)
            return ('fold', 0)
        if big_stack and to_call == 0 and self.rng.random() < 0.3:
            return ('raise', s['current_bet'] + int(pot * 0.6) + bb)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, pid, strategy, chips):
        self.pid = pid
        self.strategy = strategy
        self.chips = chips
        self.hole = None
        self.in_hand = False
        self.all_in = False


class Tournament:
    BLIND_SCHEDULE_EVERY = 15

    def __init__(self, strategy_classes, seed, start_chips=1000):
        self.rng = random.Random(seed)
        self.players = [Player(i + 1, cls(random.Random(seed * 100 + i)), start_chips)
                        for i, cls in enumerate(strategy_classes)]
        self.start_chips = start_chips
        self.button = 0
        self.hand_no = 0
        self.stats = {p.pid: {'hands': 0, 'vpip': 0, 'raises': 0, 'allins': 0}
                      for p in self.players}

    def alive(self):
        return [p for p in self.players if p.chips > 0]

    def blinds(self):
        level = self.hand_no // self.BLIND_SCHEDULE_EVERY
        sb = 10 * (2 ** min(level, 10))
        return sb, sb * 2

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < 5000:
            self.play_hand()
            self.hand_no += 1
        return self.alive()[0].pid

    def seat_order(self, start_pid_index):
        n = len(self.players)
        order = []
        for i in range(1, n + 1):
            p = self.players[(start_pid_index + i) % n]
            if p.chips > 0 or p.in_hand:
                order.append(p)
        return order

    def play_hand(self):
        alive = self.alive()
        if len(alive) < 2:
            return
        sb_amt, bb_amt = self.blinds()
        deck = fresh_deck()
        self.rng.shuffle(deck)

        for p in self.players:
            p.in_hand = False
            p.all_in = False
            p.hole = None
        for p in alive:
            p.in_hand = True
            p.hole = [deck.pop(), deck.pop()]
            self.stats[p.pid]['hands'] += 1

        alive_idx = [i for i, p in enumerate(self.players) if p.chips > 0]
        while self.players[self.button].chips <= 0:
            self.button = (self.button + 1) % len(self.players)

        n_alive = len(alive_idx)
        order_after_button = self.seat_order(self.button)
        if n_alive == 2:
            sb_p = self.players[self.button]
            bb_p = order_after_button[0]
        else:
            sb_p = order_after_button[0]
            bb_p = order_after_button[1]

        self.contrib_total = {p.pid: 0 for p in self.players}
        self.contrib_street = {p.pid: 0 for p in self.players}
        self.vpip_done = set()

        self._post(sb_p, min(sb_amt, sb_p.chips))
        self._post(bb_p, min(bb_amt, bb_p.chips))
        self.current_bet = bb_amt
        self.last_raise = bb_amt
        self.history = []

        community = []
        board_deal = {'flop': 3, 'turn': 1, 'river': 1}

        for street in STREETS:
            if street != 'preflop':
                self.current_bet = 0
                self.last_raise = bb_amt
                for pid in self.contrib_street:
                    self.contrib_street[pid] = 0
                for _ in range(board_deal[street]):
                    community.append(deck.pop())
            in_hand = [p for p in self.players if p.in_hand]
            if len(in_hand) <= 1:
                break
            if street == 'preflop':
                start = self.players.index(bb_p)
            else:
                start = self.button
            self.betting_round(street, start, community, sb_amt, bb_amt)
            if len([p for p in self.players if p.in_hand]) <= 1:
                break

        while len(community) < 5 and len([p for p in self.players if p.in_hand]) > 1:
            community.append(deck.pop())

        self.settle(community)
        self.advance_button()

    def _post(self, p, amount):
        amount = min(amount, p.chips)
        p.chips -= amount
        self.contrib_total[p.pid] += amount
        self.contrib_street[p.pid] += amount
        if p.chips == 0:
            p.all_in = True

    def advance_button(self):
        n = len(self.players)
        for i in range(1, n + 1):
            j = (self.button + i) % n
            if self.players[j].chips > 0:
                self.button = j
                return

    def betting_round(self, street, start_index, community, sb_amt, bb_amt):
        queue = deque(p for p in self.seat_order(start_index)
                      if p.in_hand and not p.all_in)
        while queue:
            in_hand = [p for p in self.players if p.in_hand]
            if len(in_hand) <= 1:
                return
            p = queue.popleft()
            if not p.in_hand or p.all_in:
                continue
            to_call = self.current_bet - self.contrib_street[p.pid]
            state = self.build_state(p, street, community, sb_amt, bb_amt, to_call)
            try:
                action, target = p.strategy.act(state)
            except Exception:
                action, target = ('fold', 0)
            raised = self.apply_action(p, action, target, street)
            if raised:
                for q in self.seat_order(self.players.index(p)):
                    if q is not p and q.in_hand and not q.all_in and q not in queue:
                        queue.append(q)

    def build_state(self, p, street, community, sb_amt, bb_amt, to_call):
        return {
            'my_id': p.pid,
            'hole': list(p.hole),
            'community': list(community),
            'street': street,
            'pot': sum(self.contrib_total.values()),
            'to_call': to_call,
            'current_bet': self.current_bet,
            'min_raise_to': self.current_bet + self.last_raise,
            'my_chips': p.chips,
            'my_street_contrib': self.contrib_street[p.pid],
            'sb': sb_amt,
            'bb': bb_amt,
            'num_in_hand': len([q for q in self.players if q.in_hand]),
            'in_hand_ids': [q.pid for q in self.players if q.in_hand],
            'players': [{'id': q.pid, 'chips': q.chips, 'in_hand': q.in_hand,
                         'all_in': q.all_in} for q in self.players if q.chips > 0 or q.in_hand],
            'stats': {pid: dict(st) for pid, st in self.stats.items()},
            'history': list(self.history),
        }

    def apply_action(self, p, action, target, street):
        to_call = self.current_bet - self.contrib_street[p.pid]
        if action == 'fold' and to_call == 0:
            action = 'call'
        if action == 'fold':
            p.in_hand = False
            self.history.append((p.pid, street, 'fold', 0))
            return False
        if action == 'call':
            pay = min(to_call, p.chips)
            self._pay(p, pay, street)
            self.history.append((p.pid, street, 'call', pay))
            return False
        # raise
        max_to = self.contrib_street[p.pid] + p.chips
        min_to = self.current_bet + self.last_raise
        target = min(int(target), max_to)
        if target <= self.current_bet:
            pay = min(to_call, p.chips)
            self._pay(p, pay, street)
            self.history.append((p.pid, street, 'call', pay))
            return False
        if target < min_to and target < max_to:
            target = min(min_to, max_to)
        pay = target - self.contrib_street[p.pid]
        self._pay(p, pay, street)
        self.last_raise = max(self.last_raise, target - self.current_bet)
        self.current_bet = target
        self.stats[p.pid]['raises'] += 1
        if p.all_in:
            self.stats[p.pid]['allins'] += 1
        self.history.append((p.pid, street, 'raise', target))
        return True

    def _pay(self, p, amount, street):
        amount = min(amount, p.chips)
        p.chips -= amount
        self.contrib_total[p.pid] += amount
        self.contrib_street[p.pid] += amount
        if amount > 0 and p.pid not in self.vpip_done:
            self.vpip_done.add(p.pid)
            self.stats[p.pid]['vpip'] += 1
        if p.chips == 0:
            p.all_in = True

    def settle(self, community):
        contrib = dict(self.contrib_total)
        in_hand = [p for p in self.players if p.in_hand]

        # refund uncalled portion of the biggest bet
        amounts = sorted(contrib.values(), reverse=True)
        if len(amounts) >= 2 and amounts[0] > amounts[1]:
            top_pid = next(pid for pid, c in contrib.items() if c == amounts[0])
            refund = amounts[0] - amounts[1]
            contrib[top_pid] -= refund
            next(p for p in self.players if p.pid == top_pid).chips += refund

        if len(in_hand) == 1:
            in_hand[0].chips += sum(contrib.values())
            return

        ranks = {p.pid: evaluate(p.hole + community) for p in in_hand}
        levels = sorted(set(contrib[p.pid] for p in in_hand if contrib[p.pid] > 0))
        prev = 0
        paid = 0
        for lvl in levels:
            pot = sum(max(0, min(c, lvl) - prev) for c in contrib.values())
            eligible = [p for p in in_hand if contrib[p.pid] >= lvl]
            if not eligible:
                continue
            best = max(ranks[p.pid] for p in eligible)
            winners = [p for p in eligible if ranks[p.pid] == best]
            share = pot // len(winners)
            for w in winners:
                w.chips += share
            winners[0].chips += pot - share * len(winners)
            paid += pot
            prev = lvl
        leftover = sum(contrib.values()) - paid
        if leftover > 0:
            in_hand[0].chips += leftover


# ---------------------------------------------------------------- main

STRATEGIES = [AllInBot, TheRock, TheProfessor, TheManiac, TheChameleon, TheBanker]


def main(n_sims=100, master_seed=42):
    wins = Counter()
    hands_played = []
    for t in range(n_sims):
        tour = Tournament(STRATEGIES, seed=master_seed * 1000 + t)
        winner = tour.run()
        total = sum(p.chips for p in tour.players)
        assert total == tour.start_chips * len(tour.players), \
            f"chip leak in sim {t}: {total}"
        wins[winner] += 1
        hands_played.append(tour.hand_no)

    print(f"\n{'=' * 62}")
    print(f"  TEXAS HOLD'EM — {n_sims} TOURNAMENTS, 6 PLAYERS, 1000 CHIPS EACH")
    print(f"{'=' * 62}\n")
    max_wins = max(wins.values()) if wins else 1
    for i, cls in enumerate(STRATEGIES):
        pid = i + 1
        w = wins.get(pid, 0)
        bar = '█' * round(w * 40 / max_wins)
        print(f"  P{pid} {cls.name:<38} {bar} {w}")
    print(f"\n  avg tournament length: {sum(hands_played) / len(hands_played):.0f} hands")
    print(f"{'=' * 62}")
    return wins


if __name__ == '__main__':
    main()
