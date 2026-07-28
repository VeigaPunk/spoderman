"""No-limit Texas Hold'em tournament engine: blinds, betting rounds,
min-raise rules, uncalled-bet refunds, side pots, showdowns, eliminations.

Strategies see only a GameView: their own cards, public table state, and
anonymous per-seat behavioral stats. No strategy identities are exposed.
"""

from collections import deque
from dataclasses import dataclass, field

from .evaluator import evaluate7


@dataclass
class SeatStats:
    """Public behavioral record of a seat, observable by anyone at the table."""
    hands: int = 0
    vpip: int = 0        # hands where the seat voluntarily put money in preflop
    raises: int = 0
    calls: int = 0
    folds: int = 0
    shoves: int = 0      # open-shove or shove-raise count

    @property
    def shove_freq(self):
        return self.shoves / self.hands if self.hands else 0.0

    @property
    def vpip_freq(self):
        return self.vpip / self.hands if self.hands else 0.0

    @property
    def aggression(self):
        acted = self.raises + self.calls + self.folds
        return self.raises / acted if acted else 0.0


@dataclass
class GameView:
    """Everything a strategy is allowed to know when acting."""
    hole: tuple
    board: tuple
    street: str            # 'preflop' | 'flop' | 'turn' | 'river'
    pot: int               # total chips committed by everyone so far
    to_call: int
    current_bet: int       # highest bet this street
    my_bet_street: int
    my_stack: int
    min_raise_to: int      # smallest legal raise target (engine clamps anyway)
    bb: int
    hand_no: int
    my_seat: int
    n_live: int            # non-folded players including me
    pos_frac: float        # 0.0 = first to act this street, 1.0 = last
    last_aggressor_seat: int   # seat of last bettor/raiser this street, -1 if none
    opponents: list        # list of dicts: seat, stack, bet_street, folded, all_in
    stats: dict            # seat -> SeatStats (includes my own seat)

    @property
    def all_in_target(self):
        return self.my_bet_street + self.my_stack


@dataclass
class Player:
    seat: int
    strategy: object
    stack: int
    hole: tuple = ()
    folded: bool = False
    all_in: bool = False
    bet_street: int = 0
    contributed: int = 0
    vpip_this_hand: bool = field(default=False, repr=False)


class Tournament:
    """One sit-and-go: play hands until a single player holds all the chips."""

    def __init__(self, strategies, rng, starting_stack=2000, base_bb=20,
                 blind_double_every=20, max_hands=3000):
        self.players = [Player(seat=i + 1, strategy=s, stack=starting_stack)
                        for i, s in enumerate(strategies)]
        self.rng = rng
        self.base_bb = base_bb
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.stats = {p.seat: SeatStats() for p in self.players}
        self.hand_no = 0
        self.button_seat = self.players[rng.randrange(len(self.players))].seat
        self.elimination_order = []  # seats, first eliminated first

    # ------------------------------------------------------------------ utils

    def alive(self):
        return [p for p in self.players if p.stack > 0 or p.bet_street > 0 or p.contributed > 0]

    def _alive_players(self):
        return [p for p in self.players if p.stack > 0]

    def _next_alive_after(self, seat, alive):
        seats = [p.seat for p in alive]
        n = len(seats)
        if seat in seats:
            i = seats.index(seat)
            return alive[(i + 1) % n]
        # previous button busted: find first alive seat after it, wrapping
        for offset in range(1, 7):
            target = (seat + offset - 1) % 6 + 1
            if target in seats:
                return alive[seats.index(target)]
        return alive[0]

    def current_bb(self):
        level = self.hand_no // self.blind_double_every
        return self.base_bb * (2 ** level)

    # ------------------------------------------------------------- main loop

    def run(self):
        while len(self._alive_players()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        survivors = self._alive_players()
        winner = max(survivors, key=lambda p: p.stack)
        for p in survivors:
            if p is not winner:
                self.elimination_order.append(p.seat)
        self.elimination_order.append(winner.seat)
        return winner.seat

    # ------------------------------------------------------------- one hand

    def play_hand(self):
        alive = self._alive_players()
        n = len(alive)
        bb = self.current_bb()
        sb = bb // 2
        self.hand_no += 1

        for p in alive:
            p.hole = ()
            p.folded = False
            p.all_in = False
            p.bet_street = 0
            p.contributed = 0
            p.vpip_this_hand = False
            self.stats[p.seat].hands += 1

        btn = self._next_alive_after(self.button_seat, alive)
        self.button_seat = btn.seat
        order_from_btn = self._rotate(alive, btn)
        if n == 2:
            sb_p, bb_p = order_from_btn[0], order_from_btn[1]   # button is SB
            preflop_order = [sb_p, bb_p]
            postflop_order = [bb_p, sb_p]
        else:
            sb_p, bb_p = order_from_btn[1], order_from_btn[2]
            preflop_order = order_from_btn[3:] + order_from_btn[:3]  # UTG first
            postflop_order = order_from_btn[1:] + order_from_btn[:1]  # SB first

        self._post_blind(sb_p, sb)
        self._post_blind(bb_p, bb)

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in preflop_order:
            p.hole = (deck.pop(), deck.pop())

        board = []
        current_bet = self._betting_round(preflop_order, board, 'preflop',
                                          current_bet=bb, last_raise=bb, bb=bb,
                                          blind_seats={sb_p.seat: sb, bb_p.seat: bb})
        streets = (('flop', 3), ('turn', 1), ('river', 1))
        for street, n_cards in streets:
            if self._hand_over(alive):
                break
            deck.pop()  # burn, for flavor
            for _ in range(n_cards):
                board.append(deck.pop())
            for p in alive:
                p.bet_street = 0
            if not self._only_all_ins_left(alive):
                self._betting_round(postflop_order, board, street,
                                    current_bet=0, last_raise=bb, bb=bb)

        self._settle(alive, board)

        for p in list(alive):
            if p.stack == 0:
                self.elimination_order.append(p.seat)

    def _rotate(self, alive, btn):
        i = alive.index(btn)
        return alive[i:] + alive[:i]

    def _post_blind(self, p, amount):
        pay = min(amount, p.stack)
        p.stack -= pay
        p.bet_street += pay
        p.contributed += pay
        if p.stack == 0:
            p.all_in = True

    def _hand_over(self, alive):
        return sum(1 for p in alive if not p.folded) <= 1

    def _only_all_ins_left(self, alive):
        can_act = [p for p in alive if not p.folded and not p.all_in]
        return len(can_act) <= 1

    # ------------------------------------------------------- betting rounds

    def _betting_round(self, order, board, street, current_bet, last_raise, bb,
                       blind_seats=None):
        blind_seats = blind_seats or {}
        active = [p for p in order if not p.folded and not p.all_in]
        if not active:
            return current_bet
        if len(active) == 1 and current_bet - active[0].bet_street <= 0:
            return current_bet
        last_aggressor = -1
        queue = deque(active)
        while queue:
            p = queue.popleft()
            if p.folded or p.all_in:
                continue
            to_call = current_bet - p.bet_street
            view = self._make_view(p, order, board, street, current_bet,
                                   last_raise, bb, to_call, last_aggressor)
            action = self._normalize(p.strategy.act(view), view)

            if action[0] == 'fold':
                p.folded = True
                self.stats[p.seat].folds += 1
                if self._hand_over(order):
                    break
            elif action[0] == 'call':
                pay = min(to_call, p.stack)
                p.stack -= pay
                p.bet_street += pay
                p.contributed += pay
                if p.stack == 0:
                    p.all_in = True
                if pay > 0:
                    self.stats[p.seat].calls += 1
                    if street == 'preflop':
                        self._mark_vpip(p, blind_seats)
            else:  # ('raise', target)
                target = action[1]
                delta = target - p.bet_street
                p.stack -= delta
                p.bet_street = target
                p.contributed += delta
                if p.stack == 0:
                    p.all_in = True
                self.stats[p.seat].raises += 1
                if p.all_in:
                    self.stats[p.seat].shoves += 1
                if street == 'preflop':
                    self._mark_vpip(p, blind_seats)
                if target > current_bet:
                    last_raise = max(last_raise, target - current_bet)
                    current_bet = target
                    last_aggressor = p.seat
                    queue = deque(q for q in self._cyclic_after(order, p)
                                  if not q.folded and not q.all_in)
        self._refund_uncalled(order)
        return current_bet

    def _mark_vpip(self, p, blind_seats):
        if not p.vpip_this_hand:
            p.vpip_this_hand = True
            self.stats[p.seat].vpip += 1

    def _cyclic_after(self, order, p):
        i = order.index(p)
        return order[i + 1:] + order[:i]

    def _normalize(self, action, view):
        """Clamp a strategy's action to a legal one."""
        if not isinstance(action, tuple) or not action:
            action = ('call',) if view.to_call == 0 else ('fold',)
        kind = action[0]
        if kind == 'fold':
            return ('call',) if view.to_call <= 0 else ('fold',)
        if kind in ('call', 'check'):
            return ('call',)
        if kind == 'raise':
            target = int(action[1]) if len(action) > 1 else view.all_in_target
            all_in_t = view.all_in_target
            target = min(target, all_in_t)
            if target <= view.current_bet:
                return ('call',)
            min_target = view.current_bet + max(view.min_raise_to - view.current_bet, 1)
            if target < min_target:
                target = min(min_target, all_in_t)
            if target <= view.current_bet:
                return ('call',)
            return ('raise', target)
        return ('call',) if view.to_call == 0 else ('fold',)

    def _make_view(self, p, order, board, street, current_bet, last_raise, bb,
                   to_call, last_aggressor):
        pot = sum(q.contributed for q in self.players)
        actors = [q for q in order if not q.folded]
        idx = order.index(p)
        pos_frac = idx / (len(order) - 1) if len(order) > 1 else 1.0
        opponents = [dict(seat=q.seat, stack=q.stack, bet_street=q.bet_street,
                          folded=q.folded, all_in=q.all_in)
                     for q in order if q is not p]
        return GameView(
            hole=p.hole, board=tuple(board), street=street, pot=pot,
            to_call=max(0, to_call), current_bet=current_bet,
            my_bet_street=p.bet_street, my_stack=p.stack,
            min_raise_to=current_bet + last_raise, bb=bb, hand_no=self.hand_no,
            my_seat=p.seat, n_live=len(actors), pos_frac=pos_frac,
            last_aggressor_seat=last_aggressor, opponents=opponents,
            stats=self.stats,
        )

    def _refund_uncalled(self, order):
        live = [p for p in order if not p.folded]
        if not live:
            return
        top = max(p.bet_street for p in live)
        leaders = [p for p in live if p.bet_street == top]
        if len(leaders) != 1:
            return
        leader = leaders[0]
        others = [p.bet_street for p in order if p is not leader]
        matched = max(others) if others else 0
        refund = top - matched
        if refund > 0:
            leader.stack += refund
            leader.bet_street -= refund
            leader.contributed -= refund
            if leader.stack > 0:
                leader.all_in = False

    # ------------------------------------------------------------ settlement

    def _settle(self, alive, board):
        live = [p for p in alive if not p.folded]
        if len(live) == 1:
            live[0].stack += sum(p.contributed for p in alive)
            for p in alive:
                p.contributed = 0
            return
        while len(board) < 5:
            board.append(self._fresh_card(alive, board))
        scores = {p.seat: evaluate7(list(p.hole) + board) for p in live}
        levels = sorted(set(p.contributed for p in live))
        prev = 0
        pots = []
        for lvl in levels:
            amount = sum(min(p.contributed, lvl) - min(p.contributed, prev)
                         for p in alive)
            eligible = [p for p in live if p.contributed >= lvl]
            pots.append((amount, eligible))
            prev = lvl
        leftover = sum(max(0, p.contributed - prev) for p in alive)
        if leftover and pots:
            amount, eligible = pots[-1]
            pots[-1] = (amount + leftover, eligible)
        for amount, eligible in pots:
            if amount <= 0:
                continue
            best = max(scores[p.seat] for p in eligible)
            winners = [p for p in eligible if scores[p.seat] == best]
            share = amount // len(winners)
            odd = amount - share * len(winners)
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < odd else 0)
        for p in alive:
            p.contributed = 0

    def _fresh_card(self, alive, board):
        used = set(board)
        for p in alive:
            used.update(p.hole)
        deck = [c for c in range(52) if c not in used]
        return self.rng.choice(deck)
