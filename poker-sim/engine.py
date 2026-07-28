"""No-limit Texas Hold'em tournament engine with side pots."""
import random
from functools import lru_cache
from itertools import combinations

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}


def new_deck():
    return [r + s for r in RANKS for s in SUITS]


@lru_cache(maxsize=400000)
def rank5(cards):
    vals = sorted((RANK_VAL[c[0]] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    uniq = sorted(set(vals), reverse=True)
    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_high = 5
    if straight_high and flush:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5,) + tuple(vals)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        return (3, groups[0][0]) + tuple(v for v, _ in groups[1:])
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return (1, groups[0][0]) + tuple(v for v, _ in groups[1:])
    return (0,) + tuple(vals)


def best7(cards):
    return max(rank5(tuple(sorted(c))) for c in combinations(cards, 5))


def chen_score(hole):
    a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
    va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
    high = {14: 10, 13: 8, 12: 7, 11: 6}.get(va, va / 2)
    if va == vb:
        return max(5, high * 2)
    score = high
    if a[1] == b[1]:
        score += 2
    gap = va - vb - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and va < 12:
        score += 1
    return score


def estimate_equity(hole, board, n_opps, rng, samples=40):
    known = set(hole) | set(board)
    deck = [c for c in new_deck() if c not in known]
    need = 5 - len(board)
    wins = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, need + 2 * n_opps)
        full_board = board + draw[:need]
        mine = best7(hole + full_board)
        opp_best = max(
            best7([draw[need + 2 * i], draw[need + 2 * i + 1]] + full_board)
            for i in range(n_opps)
        )
        if mine > opp_best:
            wins += 1
        elif mine == opp_best:
            wins += 0.5
    return wins / samples


def hand_features(hole, board):
    cards = hole + board
    cat = best7(cards)[0] if len(cards) >= 5 else 0
    board_vals = [RANK_VAL[c[0]] for c in board]
    hole_vals = [RANK_VAL[c[0]] for c in hole]
    top_board = max(board_vals) if board_vals else 0
    pocket_pair = hole_vals[0] == hole_vals[1]
    overpair = pocket_pair and hole_vals[0] > top_board
    top_pair = any(v == top_board for v in hole_vals) and not pocket_pair
    suit_counts = {}
    for c in cards:
        suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
    flush_draw = any(n == 4 for n in suit_counts.values())
    uniq = sorted(set(hole_vals + board_vals))
    oesd = any(
        len([v for v in uniq if lo <= v <= lo + 3]) == 4
        for lo in range(2, 12)
    )
    return {
        'category': cat, 'overpair': overpair, 'top_pair': top_pair,
        'flush_draw': flush_draw, 'oesd': oesd, 'pocket_pair': pocket_pair,
        'high_card': max(hole_vals),
    }


class Seat:
    def __init__(self, idx, name, strategy, stack):
        self.idx = idx
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.reset_hand()

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.committed = 0
        self.street_committed = 0

    def commit(self, amount):
        amt = min(amount, self.stack)
        self.stack -= amt
        self.committed += amt
        self.street_committed += amt
        if self.stack == 0:
            self.all_in = True
        return amt


class Stats:
    """Public per-seat action stats every player can observe."""
    def __init__(self, n):
        self.hands = [0] * n
        self.vpip = [0] * n
        self.raises = [0] * n
        self.shoves = [0] * n
        self.actions = [0] * n

    def shove_rate(self, idx):
        return self.shoves[idx] / max(1, self.hands[idx])

    def aggression(self, idx):
        return self.raises[idx] / max(1, self.actions[idx])


class Table:
    def __init__(self, seats, rng):
        self.seats = seats
        self.rng = rng
        self.stats = Stats(len(seats))
        self.button = 0

    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def play_hand(self, sb, bb):
        alive = self.alive()
        n = len(alive)
        if n < 2:
            return
        self.button %= n
        deck = new_deck()
        self.rng.shuffle(deck)
        for s in alive:
            s.reset_hand()
            s.hole = [deck.pop(), deck.pop()]
            self.stats.hands[s.idx] += 1

        if n == 2:
            sb_i, bb_i = self.button, (self.button + 1) % n
            first_pre = sb_i
        else:
            sb_i, bb_i = (self.button + 1) % n, (self.button + 2) % n
            first_pre = (self.button + 3) % n
        alive[sb_i].commit(sb)
        alive[bb_i].commit(bb)

        board = []
        order_pre = [alive[(first_pre + i) % n] for i in range(n)]
        first_post = sb_i if n > 2 else bb_i
        order_post = [alive[(first_post + i) % n] for i in range(n)]

        self._betting(order_pre, board, bb, bb, sb, bb, preflop=True)
        for street_cards in (3, 1, 1):
            if self._hand_over(alive):
                break
            board += [deck.pop() for _ in range(street_cards)]
            live = [s for s in alive if not s.folded and not s.all_in]
            if len(live) >= 2:
                for s in alive:
                    s.street_committed = 0
                self._betting(order_post, board, 0, bb, sb, bb, preflop=False)
        while len(board) < 5 and len([s for s in alive if not s.folded]) >= 2:
            board.append(deck.pop())
        self._settle(alive, board)
        self.button = (self.button + 1) % max(1, len(self.alive()))

    def _hand_over(self, alive):
        return len([s for s in alive if not s.folded]) <= 1

    def _betting(self, order, board, current_bet, min_raise, sb, bb, preflop):
        acted = set()
        idx = 0
        guard = 0
        while guard < 200:
            guard += 1
            unfolded = [s for s in order if not s.folded]
            if len(unfolded) <= 1:
                return
            live = [s for s in unfolded if not s.all_in]
            if live and all(
                id(s) in acted and s.street_committed == current_bet for s in live
            ):
                break
            if not live:
                break
            s = order[idx % len(order)]
            idx += 1
            if s.folded or s.all_in:
                continue
            if id(s) in acted and s.street_committed == current_bet:
                continue
            to_call = current_bet - s.street_committed
            pot = sum(x.committed for x in self.seats)
            view = {
                'hole': list(s.hole), 'board': list(board), 'pot': pot,
                'to_call': to_call, 'min_raise': min_raise, 'stack': s.stack,
                'bb': bb, 'my_index': s.idx,
                'num_in_hand': len(unfolded),
                'num_alive': len(self.alive()),
                'street_committed': s.street_committed,
                'committed': s.committed,
                'current_bet': current_bet,
                'preflop': preflop,
                'stats': self.stats,
                'opponents': [x.idx for x in unfolded if x is not s],
                'rng': self.rng,
            }
            action = s.strategy.act(view)
            kind = action[0]
            self.stats.actions[s.idx] += 1
            if kind == 'fold' and to_call > 0:
                s.folded = True
                continue
            if kind == 'raise' and s.stack > to_call:
                raise_by = min(action[1], s.stack - to_call)
                if raise_by >= min_raise or to_call + raise_by == s.stack:
                    paid = s.commit(to_call + raise_by)
                    actual_raise = s.street_committed - current_bet
                    if actual_raise > 0:
                        if actual_raise >= min_raise:
                            min_raise = actual_raise
                        current_bet = s.street_committed
                        acted = {id(s)}
                    else:
                        acted.add(id(s))
                    self.stats.vpip[s.idx] += 1
                    self.stats.raises[s.idx] += 1
                    if s.all_in:
                        self.stats.shoves[s.idx] += 1
                    continue
            s.commit(to_call)
            if to_call > 0:
                self.stats.vpip[s.idx] += 1
            acted.add(id(s))

    def _settle(self, alive, board):
        contenders = [s for s in alive if not s.folded]
        total = sum(s.committed for s in alive)
        if len(contenders) == 1:
            contenders[0].stack += total
            return
        ranks = {id(s): best7(s.hole + board) for s in contenders}
        levels = sorted({s.committed for s in contenders})
        prev = 0
        for lvl in levels:
            amt = sum(min(s.committed, lvl) - min(s.committed, prev) for s in alive)
            prev = lvl
            if amt == 0:
                continue
            eligible = [s for s in contenders if s.committed >= lvl]
            best = max(ranks[id(s)] for s in eligible)
            winners = [s for s in eligible if ranks[id(s)] == best]
            share = amt // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += amt - share * len(winners)


def play_tournament(strategy_factories, names, seed, start_stack=1000):
    rng = random.Random(seed)
    seats = [
        Seat(i, names[i], strategy_factories[i](random.Random(seed * 1000 + i)), start_stack)
        for i in range(len(names))
    ]
    table = Table(seats, rng)
    sb, bb = 10, 20
    hand_no = 0
    while len(table.alive()) > 1 and hand_no < 3000:
        hand_no += 1
        if hand_no % 25 == 0:
            sb, bb = sb * 2, bb * 2
        table.play_hand(sb, bb)
    alive = table.alive()
    winner = max(alive, key=lambda s: s.stack)
    return winner.idx, hand_no
