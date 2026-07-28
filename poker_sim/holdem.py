"""Texas Hold'em engine: cards, 7-card evaluation, betting with side pots."""
import random
from dataclasses import dataclass, field

RANKS = list(range(2, 15))  # 2..14 (Ace high)
SUITS = range(4)


def new_deck(rng):
    deck = [(r, s) for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck


def evaluate7(cards):
    """Return a comparable tuple ranking the best 5-card hand out of 7 cards.

    Higher tuple = better hand. Categories:
    8=straight flush, 7=quads, 6=full house, 5=flush, 4=straight,
    3=trips, 2=two pair, 1=pair, 0=high card.
    """
    ranks = sorted((c[0] for c in cards), reverse=True)
    suits = {}
    for r, s in cards:
        suits.setdefault(s, []).append(r)

    flush_ranks = None
    for s, rs in suits.items():
        if len(rs) >= 5:
            flush_ranks = sorted(rs, reverse=True)
            break

    def straight_high(rset):
        bits = set(rset)
        if 14 in bits:
            bits.add(1)
        run = 0
        best = 0
        for r in range(14, 0, -1):
            if r in bits:
                run += 1
                if run >= 5:
                    best = max(best, r + 4)
            else:
                run = 0
        return best if best else None

    if flush_ranks:
        sf = straight_high(flush_ranks)
        if sf:
            return (8, sf)

    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    by_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))

    if by_count[0][1] == 4:
        quad = by_count[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if by_count[0][1] == 3 and len(by_count) > 1 and by_count[1][1] >= 2:
        return (6, by_count[0][0], by_count[1][0])

    if flush_ranks:
        return (5, *flush_ranks[:5])

    st = straight_high(ranks)
    if st:
        return (4, st)

    if by_count[0][1] == 3:
        t = by_count[0][0]
        kick = [r for r in ranks if r != t][:2]
        return (3, t, *kick)

    if by_count[0][1] == 2 and len(by_count) > 1 and by_count[1][1] == 2:
        p1, p2 = by_count[0][0], by_count[1][0]
        kicker = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kicker)

    if by_count[0][1] == 2:
        p = by_count[0][0]
        kick = [r for r in ranks if r != p][:3]
        return (1, p, *kick)

    return (0, *ranks[:5])


def equity_montecarlo(hole, board, n_opponents, rng, samples=60):
    """Estimate win probability of `hole` vs n_opponents random hands."""
    known = set(hole) | set(board)
    remaining = [(r, s) for r in RANKS for s in SUITS if (r, s) not in known]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(samples):
        draw = rng.sample(remaining, need_board + 2 * n_opponents)
        full_board = list(board) + draw[:need_board]
        my = evaluate7(list(hole) + full_board)
        best_opp = None
        for i in range(n_opponents):
            opp = draw[need_board + 2 * i: need_board + 2 * i + 2]
            v = evaluate7(opp + full_board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if my > best_opp:
            wins += 1
        elif my == best_opp:
            wins += 0.5
    return wins / samples


def chen_score(hole):
    """Chen formula preflop hand strength."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2)
    if r1 == r2:
        return max(5, pts * 2)
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        pts += 1
    if s1 == s2:
        pts += 2
    return pts


@dataclass(eq=False)
class Player:
    idx: int
    strategy: object
    chips: int
    hole: tuple = None
    in_hand: bool = False
    bet_this_round: int = 0
    total_committed: int = 0
    all_in: bool = False


@dataclass
class HandState:
    """Read-only view passed to strategies. No opponent strategy info."""
    hole: tuple
    board: list
    pot: int
    to_call: int
    my_chips: int
    my_bet: int
    min_raise: int
    n_active: int
    position: int          # seats after me until button (0 = button)
    n_players: int
    big_blind: int
    street: str            # preflop/flop/turn/river
    history: list = field(default_factory=list)  # (player_idx, action) this hand


class Table:
    def __init__(self, players, small_blind=10, big_blind=20, rng=None):
        self.players = players
        self.sb = small_blind
        self.bb = big_blind
        self.button = 0
        self.rng = rng or random.Random()
        self.hand_no = 0

    def alive(self):
        return [p for p in self.players if p.chips > 0]

    def play_hand(self):
        self.hand_no += 1
        # blinds escalate so tournaments terminate
        level = self.hand_no // 25
        sb, bb = self.sb * (2 ** level), self.bb * (2 ** level)

        alive = self.alive()
        if len(alive) < 2:
            return
        deck = new_deck(self.rng)
        board = []
        history = []

        for p in self.players:
            p.in_hand = p.chips > 0
            p.bet_this_round = 0
            p.total_committed = 0
            p.all_in = False
            p.hole = None
        seats = [p for p in self.players if p.in_hand]
        n = len(seats)

        # rotate button among alive players
        order = sorted(seats, key=lambda p: p.idx)
        self.button = (self.button + 1) % len(order)
        btn = order[self.button]
        ordered = order[order.index(btn):] + order[:order.index(btn)]
        # ordered[0]=button, then sb, bb, ...
        sb_p = ordered[1 % n]
        bb_p = ordered[2 % n]

        for p in seats:
            p.hole = (deck.pop(), deck.pop())

        def post(p, amt):
            amt = min(amt, p.chips)
            p.chips -= amt
            p.bet_this_round += amt
            p.total_committed += amt
            if p.chips == 0:
                p.all_in = True
            return amt

        pot = post(sb_p, sb) + post(bb_p, bb)
        current_bet = bb
        min_raise = bb

        def active():
            return [p for p in seats if p.in_hand]

        def betting_round(street, first_seat_offset):
            nonlocal pot, current_bet, min_raise
            live = active()
            if len([p for p in live if not p.all_in]) <= 1 and \
               all(p.bet_this_round == current_bet or p.all_in for p in live):
                return
            start = ordered[first_seat_offset % n:] + ordered[:first_seat_offset % n]
            queue = [p for p in start if p.in_hand and not p.all_in]
            acted = set()
            i = 0
            while True:
                live = [p for p in seats if p.in_hand]
                if len(live) <= 1:
                    return
                pending = [p for p in live if not p.all_in and
                           (p.bet_this_round < current_bet or p not in acted)]
                if not pending:
                    return
                p = queue[i % len(queue)] if queue else None
                i += 1
                if p is None or not p.in_hand or p.all_in:
                    if p in pending:
                        pending.remove(p)
                    if not any(q.in_hand and not q.all_in for q in queue):
                        return
                    continue
                if p.bet_this_round == current_bet and p in acted:
                    continue
                to_call = current_bet - p.bet_this_round
                pos = (ordered.index(p) - 0) % n  # 0 = button acts last postflop
                state = HandState(
                    hole=p.hole, board=list(board), pot=pot, to_call=to_call,
                    my_chips=p.chips, my_bet=p.bet_this_round,
                    min_raise=min_raise, n_active=len(live), position=pos,
                    n_players=n, big_blind=bb, street=street, history=history,
                )
                action, amount = p.strategy.act(state, self.rng)
                acted.add(p)
                if action == 'fold' and to_call > 0:
                    p.in_hand = False
                    history.append((p.idx, 'fold', 0))
                elif action == 'raise' and p.chips > to_call:
                    raise_to = max(current_bet + min_raise,
                                   min(amount, p.bet_this_round + p.chips))
                    add = min(raise_to - p.bet_this_round, p.chips)
                    pot += post(p, add)
                    if p.bet_this_round > current_bet:
                        min_raise = max(min_raise, p.bet_this_round - current_bet)
                        current_bet = p.bet_this_round
                        acted = {p}
                    history.append((p.idx, 'raise', p.bet_this_round))
                else:  # call / check
                    add = min(to_call, p.chips)
                    pot += post(p, add)
                    history.append((p.idx, 'call' if to_call else 'check',
                                    p.bet_this_round))

        # preflop: first to act after BB
        betting_round('preflop', 3 % n if n > 2 else 0)
        streets = [('flop', 3), ('turn', 1), ('river', 1)]
        for street, ncards in streets:
            if len(active()) <= 1:
                break
            deck.pop()  # burn
            for _ in range(ncards):
                board.append(deck.pop())
            for p in seats:
                p.bet_this_round = 0
            current_bet = 0
            min_raise = bb
            if len([p for p in active() if not p.all_in]) > 1:
                betting_round(street, 1 % n)

        # deal remaining board if hand ran out via all-ins
        while len(board) < 5 and len(active()) > 1:
            deck.pop()
            board.append(deck.pop())

        self._showdown(seats, board, pot)

    def _showdown(self, seats, board, pot):
        contenders = [p for p in seats if p.in_hand]
        if len(contenders) == 1:
            contenders[0].chips += pot
            return
        scores = {p.idx: evaluate7(list(p.hole) + board) for p in contenders}
        # side pots by contribution levels
        levels = sorted({p.total_committed for p in seats if p.total_committed > 0})
        prev = 0
        for lvl in levels:
            layer = 0
            for p in seats:
                layer += max(0, min(p.total_committed, lvl) - prev)
            eligible = [p for p in contenders if p.total_committed >= lvl]
            if eligible and layer:
                best = max(scores[p.idx] for p in eligible)
                winners = [p for p in eligible if scores[p.idx] == best]
                share = layer // len(winners)
                for w in winners:
                    w.chips += share
                winners[0].chips += layer - share * len(winners)
            prev = lvl

    def run_tournament(self, max_hands=2000):
        while len(self.alive()) > 1 and self.hand_no < max_hands:
            self.play_hand()
        alive = self.alive()
        return max(alive, key=lambda p: p.chips).idx
