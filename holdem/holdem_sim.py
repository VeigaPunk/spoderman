#!/usr/bin/env python3
"""Six-max no-limit Texas Hold'em tournament simulator.

Player 1 plays the entire strategy spec:  if my_turn then bet = all-in fi
Players 2-6 play five distinct elaborate strategies (they cannot see each
other's logic; each only receives the public game state).

Runs 100 tournaments (everyone starts with equal chips, escalating blinds,
last player with chips wins) and prints a histogram of tournament winners.
"""

import random
from collections import Counter, deque

# ---------------------------------------------------------------- cards

RANKS = range(2, 15)  # 14 = Ace
SUITS = range(4)
FULL_DECK = [(r, s) for r in RANKS for s in SUITS]


def evaluate(cards):
    """Best poker hand rank tuple for 5-7 cards. Higher tuple wins."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    cnt = Counter(ranks)
    suit_cnt = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in suit_cnt.items() if n >= 5), None)

    def straight_high(rs):
        rset = set(rs)
        if 14 in rset:
            rset.add(1)
        for hi in range(14, 4, -1):
            if all(hi - i in rset for i in range(5)):
                return hi
        return 0

    if flush_suit is not None:
        flush_ranks = [c[0] for c in cards if c[1] == flush_suit]
        sh = straight_high(flush_ranks)
        if sh:
            return (8, sh)

    groups = sorted(cnt.items(), key=lambda kv: (-kv[1], -kv[0]))
    if groups[0][1] == 4:
        quad = groups[0][0]
        return (7, quad, max(r for r in ranks if r != quad))
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    if flush_suit is not None:
        top5 = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)[:5]
        return (5, *top5)
    sh = straight_high(ranks)
    if sh:
        return (4, sh)
    if groups[0][1] == 3:
        t = groups[0][0]
        kick = [r for r in ranks if r != t][:2]
        return (3, t, *kick)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        return (2, hp, lp, max(r for r in ranks if r not in (hp, lp)))
    if groups[0][1] == 2:
        p = groups[0][0]
        kick = [r for r in ranks if r != p][:3]
        return (1, p, *kick)
    return (0, *ranks[:5])


def chen_score(hole):
    """Chen formula preflop hand strength (~ -1 .. 20)."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    high_pts = {14: 10, 13: 8, 12: 7, 11: 6}
    score = high_pts.get(r1, r1 / 2)
    if r1 == r2:
        return max(5, score * 2)
    if s1 == s2:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        score += 1
    return score


def estimate_equity(hole, board, n_opp, rng, trials=40):
    """Monte Carlo win probability vs n_opp random hands."""
    seen = set(hole) | set(board)
    remaining = [c for c in FULL_DECK if c not in seen]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(trials):
        drawn = rng.sample(remaining, n_opp * 2 + need_board)
        full_board = list(board) + drawn[:need_board]
        mine = evaluate(list(hole) + full_board)
        best_opp = max(
            evaluate(list(drawn[need_board + 2 * i:need_board + 2 * i + 2]) + full_board)
            for i in range(n_opp)
        )
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / trials


# ---------------------------------------------------------------- strategies


class Strategy:
    name = "?"

    def __init__(self, seed):
        self.rng = random.Random(seed)

    def act(self, s):
        """Return ('fold',) | ('call',) | ('raise', street_total_target)."""
        raise NotImplementedError


class AllInAndrey(Strategy):
    """The whole algorithm: if my_turn then bet = all-in fi."""
    name = "P1 AllIn-Andrey"

    def act(self, s):
        return ('raise', s['my_street_put'] + s['stack'])


class Accountant(Strategy):
    """Tight-aggressive: Chen-formula ranges, equity + pot-odds postflop."""
    name = "P2 Accountant (TAG)"

    def act(self, s):
        pot, to_call, bb = s['pot'], s['to_call'], s['bb']
        if s['street'] == 'preflop':
            c = chen_score(s['hole'])
            open_thresh = 8.5 - 2.5 * s['position_frac']
            if s['unopened']:
                if c >= open_thresh:
                    return ('raise', s['current_bet'] + int(2.5 * bb))
                if to_call == 0:
                    return ('call',)
                if c >= open_thresh - 2 and to_call <= bb:
                    return ('call',)
                return ('fold',)
            if c >= 11:
                return ('raise', s['current_bet'] * 3)
            if c >= 8.5 and to_call <= s['stack'] // 3:
                return ('call',)
            if c >= 6.5 and to_call <= max(bb, pot // 4):
                return ('call',)
            return ('fold',)

        eq = estimate_equity(s['hole'], s['board'], s['n_opp'], self.rng, 30)
        if to_call == 0:
            if eq > 0.55 or (s['am_aggressor'] and eq > 0.42):
                return ('raise', s['my_street_put'] + max(bb, int(0.65 * pot)))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.78:
            return ('raise', s['current_bet'] + pot)
        if eq > pot_odds + 0.08:
            return ('call',)
        return ('fold',)


class Loki(Strategy):
    """Loose-aggressive: wide ranges, semi-bluffs draws, random bluff raises."""
    name = "P3 Loki (LAG)"

    def act(self, s):
        pot, to_call, bb = s['pot'], s['to_call'], s['bb']
        if s['street'] == 'preflop':
            c = chen_score(s['hole'])
            if s['unopened']:
                if c >= 5.5 - 2 * s['position_frac'] or self.rng.random() < 0.15:
                    return ('raise', s['current_bet'] + int(2.5 * bb))
                if to_call == 0:
                    return ('call',)
                return ('fold',)
            if c >= 10 or (c >= 7 and self.rng.random() < 0.3):
                return ('raise', s['current_bet'] * 3)
            if c >= 6 and to_call <= s['stack'] // 4:
                return ('call',)
            return ('fold',)

        eq = estimate_equity(s['hole'], s['board'], s['n_opp'], self.rng, 30)
        semi_bluff = 0.32 < eq < 0.52 and self.rng.random() < 0.35
        if to_call == 0:
            if eq > 0.5 or semi_bluff or self.rng.random() < 0.12:
                return ('raise', s['my_street_put'] + max(bb, int(0.75 * pot)))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.72 or semi_bluff:
            return ('raise', s['current_bet'] + pot)
        if eq > pot_odds + 0.02:
            return ('call',)
        return ('fold',)


class Nitalie(Strategy):
    """Rock/nit: premiums only, never bluffs, needs a real hand to continue."""
    name = "P4 Nitalie (Rock)"

    def act(self, s):
        pot, to_call, bb = s['pot'], s['to_call'], s['bb']
        if s['street'] == 'preflop':
            c = chen_score(s['hole'])
            if c >= 10:
                return ('raise', max(s['current_bet'] * 3, s['current_bet'] + 3 * bb))
            if c >= 8 and to_call <= s['stack'] // 5:
                return ('call',)
            if to_call == 0:
                return ('call',)
            return ('fold',)

        made = evaluate(list(s['hole']) + list(s['board']))[0]
        eq = estimate_equity(s['hole'], s['board'], s['n_opp'], self.rng, 25)
        strong = made >= 2 or eq > 0.72
        if to_call == 0:
            if strong:
                return ('raise', s['my_street_put'] + max(bb, pot // 2))
            return ('call',)
        if made >= 3 or eq > 0.8:
            return ('raise', s['current_bet'] + pot)
        if strong:
            return ('call',)
        return ('fold',)


class Blade(Strategy):
    """Position bandit: steals unopened pots in late position, c-bets as
    aggressor vs few opponents, otherwise strict pot-odds discipline."""
    name = "P5 Blade (Position)"

    def act(self, s):
        pot, to_call, bb = s['pot'], s['to_call'], s['bb']
        if s['street'] == 'preflop':
            c = chen_score(s['hole'])
            late = s['position_frac'] > 0.55
            if s['unopened']:
                if late and (c >= 4 or self.rng.random() < 0.25):
                    return ('raise', s['current_bet'] + int(2.5 * bb))
                if c >= 8:
                    return ('raise', s['current_bet'] + int(2.5 * bb))
                if to_call == 0:
                    return ('call',)
                if c >= 6 and to_call <= bb:
                    return ('call',)
                return ('fold',)
            if c >= 10.5:
                return ('raise', s['current_bet'] * 3)
            if c >= 7.5 and to_call <= s['stack'] // 4:
                return ('call',)
            return ('fold',)

        eq = estimate_equity(s['hole'], s['board'], s['n_opp'], self.rng, 30)
        if to_call == 0:
            if s['am_aggressor'] and s['n_opp'] <= 2 and self.rng.random() < 0.7:
                return ('raise', s['my_street_put'] + max(bb, int(0.55 * pot)))
            if eq > 0.58:
                return ('raise', s['my_street_put'] + max(bb, int(0.6 * pot)))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.75:
            return ('raise', s['current_bet'] + pot)
        if eq > pot_odds + 0.06:
            return ('call',)
        return ('fold',)


class Neo(Strategy):
    """Pure calculator: Monte Carlo equity vs field, strict EV decisions."""
    name = "P6 Neo (Calculator)"

    def act(self, s):
        pot, to_call, bb = s['pot'], s['to_call'], s['bb']
        eq = estimate_equity(s['hole'], s['board'], s['n_opp'], self.rng, 45)
        if s['street'] == 'preflop':
            if eq > 1.35 / (s['n_opp'] + 1):
                return ('raise', s['current_bet'] + int(2.5 * bb))
            if to_call == 0:
                return ('call',)
            if eq > to_call / (pot + to_call) + 0.05 and to_call <= s['stack'] // 3:
                return ('call',)
            return ('fold',)
        if to_call == 0:
            if eq > 0.7:
                return ('raise', s['my_street_put'] + max(bb, pot))
            if eq > 0.55:
                return ('raise', s['my_street_put'] + max(bb, int(0.6 * pot)))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.75:
            return ('raise', s['current_bet'] + pot)
        if eq > pot_odds + 0.04:
            return ('call',)
        return ('fold',)


# ---------------------------------------------------------------- engine


class Tournament:
    START_CHIPS = 1000
    BASE_SB = 10
    BLIND_UP_EVERY = 15  # hands per blind level (doubles each level)
    MAX_HANDS = 3000

    def __init__(self, strategies, seed):
        self.strategies = strategies  # seat -> Strategy
        self.rng = random.Random(seed)
        self.stacks = {p: self.START_CHIPS for p in strategies}
        self.button = 0

    # -- one full tournament ------------------------------------------------
    def run(self):
        hand = 0
        while len(self.alive()) > 1 and hand < self.MAX_HANDS:
            level = min(hand // self.BLIND_UP_EVERY, 10)
            self.sb = self.BASE_SB * (2 ** level)
            self.bb = self.sb * 2
            self.play_hand()
            hand += 1
            self.button += 1
        alive = self.alive()
        return max(alive, key=lambda p: self.stacks[p])

    def alive(self):
        return [p for p in self.stacks if self.stacks[p] > 0]

    # -- one hand -----------------------------------------------------------
    def play_hand(self):
        seats = self.alive()
        n = len(seats)
        btn = seats[self.button % n]
        order = seats[seats.index(btn):] + seats[:seats.index(btn)]  # btn first

        deck = FULL_DECK[:]
        self.rng.shuffle(deck)
        self.hole = {p: (deck.pop(), deck.pop()) for p in order}
        self.board = []
        self.folded = {p: False for p in order}
        self.allin = {p: False for p in order}
        self.street_put = {p: 0 for p in order}
        self.total_put = {p: 0 for p in order}
        self.pot = 0
        self.aggressor = None

        if n == 2:
            sb_seat, bb_seat = order[0], order[1]
        else:
            sb_seat, bb_seat = order[1], order[2]
        self.current_bet = 0
        self.min_raise = self.bb
        self._put(sb_seat, min(self.sb, self.stacks[sb_seat]))
        self._put(bb_seat, min(self.bb, self.stacks[bb_seat]))
        self.current_bet = self.bb

        bb_idx = order.index(bb_seat)
        preflop_order = order[bb_idx + 1:] + order[:bb_idx + 1]
        postflop_order = order[1:] + order[:1]  # first after button

        self.betting_round('preflop', preflop_order)
        for street, n_cards in (('flop', 3), ('turn', 1), ('river', 1)):
            if len(self.live()) <= 1:
                break
            self.board += [deck.pop() for _ in range(n_cards)]
            self.current_bet = 0
            self.min_raise = self.bb
            self.street_put = {p: 0 for p in self.street_put}
            if sum(1 for p in self.live() if not self.allin[p]) >= 2:
                self.betting_round(street, postflop_order)
        # run out remaining board for all-in showdowns
        while len(self.live()) > 1 and len(self.board) < 5:
            self.board.append(deck.pop())
        self.payout()

    def live(self):
        return [p for p in self.folded if not self.folded[p]]

    def _put(self, p, amount):
        amount = min(amount, self.stacks[p])
        self.stacks[p] -= amount
        self.street_put[p] += amount
        self.total_put[p] += amount
        self.pot += amount
        if self.stacks[p] == 0:
            self.allin[p] = True

    def betting_round(self, street, order):
        pending = deque(p for p in order
                        if not self.folded[p] and not self.allin[p])
        while pending:
            if len(self.live()) <= 1:
                return
            p = pending.popleft()
            if self.folded[p] or self.allin[p]:
                continue
            to_call = self.current_bet - self.street_put[p]
            others_can_act = any(not self.folded[q] and not self.allin[q]
                                 for q in self.folded if q != p)
            if to_call == 0 and not others_can_act:
                return
            action = self.strategies[p].act(self._state(p, street, order))
            reopened = self._apply(p, action, to_call)
            if reopened:
                self.aggressor = p
                idx = order.index(p)
                after = order[idx + 1:] + order[:idx]
                pending = deque(q for q in after
                                if not self.folded[q] and not self.allin[q])

    def _apply(self, p, action, to_call):
        kind = action[0]
        if kind == 'fold':
            if to_call > 0:
                self.folded[p] = True
                return False
            kind = 'call'
        if kind == 'call':
            self._put(p, to_call)
            return False
        target = int(action[1])
        max_total = self.street_put[p] + self.stacks[p]
        min_total = (self.current_bet + self.min_raise
                     if self.current_bet > 0 else self.bb)
        target = min(target, max_total)
        if target <= self.current_bet:
            self._put(p, to_call)  # short all-in call or capped
            return False
        if target < min_total and target < max_total:
            target = min(min_total, max_total)
        raise_size = target - self.current_bet
        self._put(p, target - self.street_put[p])
        if raise_size >= self.min_raise:
            self.min_raise = raise_size
        self.current_bet = target
        return True

    def _state(self, p, street, order):
        live_after_btn = [q for q in order if not self.folded[q]]
        pos = live_after_btn.index(p) if p in live_after_btn else 0
        n_live = len(live_after_btn)
        return {
            'street': street,
            'hole': self.hole[p],
            'board': tuple(self.board),
            'pot': self.pot,
            'to_call': self.current_bet - self.street_put[p],
            'current_bet': self.current_bet,
            'min_raise': self.min_raise,
            'my_street_put': self.street_put[p],
            'stack': self.stacks[p],
            'bb': self.bb,
            'n_live': n_live,
            'n_opp': max(1, n_live - 1),
            'position_frac': pos / max(1, n_live - 1),
            'am_aggressor': self.aggressor == p,
            'unopened': street == 'preflop' and self.current_bet <= self.bb,
        }

    def payout(self):
        live = self.live()
        contrib = self.total_put
        if len(live) == 1:
            self.stacks[live[0]] += self.pot
            return
        scores = {p: evaluate(list(self.hole[p]) + self.board) for p in live}
        levels = sorted(set(contrib[p] for p in contrib if contrib[p] > 0))
        prev = 0
        for lv in levels:
            slice_pot = sum(min(contrib[q], lv) - min(contrib[q], prev)
                            for q in contrib)
            prev = lv
            if slice_pot == 0:
                continue
            elig = [p for p in live if contrib[p] >= lv]
            if not elig:  # overpay from a folded player above all live stakes
                top = max(contrib[p] for p in live)
                elig = [p for p in live if contrib[p] == top]
            best = max(scores[p] for p in elig)
            winners = [p for p in elig if scores[p] == best]
            share, rem = divmod(slice_pot, len(winners))
            for i, w in enumerate(winners):
                self.stacks[w] += share + (1 if i < rem else 0)


# ---------------------------------------------------------------- sim runner

STRATEGY_CLASSES = [AllInAndrey, Accountant, Loki, Nitalie, Blade, Neo]


def run_sims(n_sims=100, master_seed=42):
    wins = Counter()
    names = {i + 1: cls.name for i, cls in enumerate(STRATEGY_CLASSES)}
    for sim in range(n_sims):
        strategies = {i + 1: cls(seed=master_seed * 100_000 + sim * 10 + i)
                      for i, cls in enumerate(STRATEGY_CLASSES)}
        t = Tournament(strategies, seed=master_seed + sim)
        wins[t.run()] += 1
        if (sim + 1) % 20 == 0:
            print(f"  ... {sim + 1}/{n_sims} tournaments done")
    return wins, names


def print_histogram(wins, names, n_sims):
    print()
    print("=" * 66)
    print(f" WINNER HISTOGRAM — {n_sims} six-max tournaments "
          "(winner winner chicken dinner)")
    print("=" * 66)
    width = 40
    top = max(wins.values()) if wins else 1
    for seat in sorted(names):
        w = wins.get(seat, 0)
        bar = '#' * round(w / top * width)
        print(f" {names[seat]:<22} | {bar:<{width}} {w:>3}  ({w / n_sims:.0%})")
    print("=" * 66)


if __name__ == '__main__':
    N = 100
    print(f"Running {N} tournaments: 6 players, {Tournament.START_CHIPS} chips "
          f"each, blinds {Tournament.BASE_SB}/{Tournament.BASE_SB * 2} "
          f"doubling every {Tournament.BLIND_UP_EVERY} hands...")
    wins, names = run_sims(N)
    print_histogram(wins, names, N)
