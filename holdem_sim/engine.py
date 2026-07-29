"""No-limit Texas Hold'em tournament engine.

Supports blinds, four betting streets, min-raise rules, all-ins, side pots,
uncalled-bet refunds, split pots, blind escalation and eliminations.
Strategies interact only through sanitized public views and broadcasts.
"""

from collections import deque

from .evaluator import evaluate, fresh_deck

STREETS = ('preflop', 'flop', 'turn', 'river')


class Player:
    def __init__(self, pid, strategy):
        self.id = pid
        self.name = strategy.name
        self.strategy = strategy
        self.stack = 0
        # per-hand state
        self.hole = None
        self.folded = False
        self.all_in = False
        self.committed_street = 0
        self.committed_total = 0

    def reset_for_hand(self):
        self.hole = None
        self.folded = False
        self.all_in = False
        self.committed_street = 0
        self.committed_total = 0


class Tournament:
    def __init__(self, players, rng, start_stack=1000, sb=10, bb=20,
                 escalate_every=25, max_hands=3000):
        self.players = players
        self.rng = rng
        self.sb = sb
        self.bb = bb
        self.escalate_every = escalate_every
        self.max_hands = max_hands
        self.hand_no = 0
        self.eliminated = []           # in order of elimination (first out first)
        for p in players:
            p.stack = start_stack
        self.button = rng.randrange(len(players))

    # ------------------------------------------------------------------
    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.max_hands:
            self.hand_no += 1
            if self.hand_no % self.escalate_every == 0:
                self.sb *= 2
                self.bb *= 2
            self.play_hand()
        survivors = sorted(self.alive(), key=lambda p: p.stack)
        finishing = self.eliminated + survivors      # worst finish first
        winner = finishing[-1]
        return winner, list(reversed(finishing))     # best finish first

    def alive(self):
        return [p for p in self.players if p.stack > 0]

    # ------------------------------------------------------------------
    def play_hand(self):
        seats = self.alive()
        self.button %= len(seats)
        # order seats so index 0 is the button
        order = seats[self.button:] + seats[:self.button]
        n = len(order)

        for p in order:
            p.reset_for_hand()
        self.history = []
        for p in order:
            p.strategy.new_hand(self.hand_no, [q.id for q in order])

        deck = fresh_deck()
        self.rng.shuffle(deck)
        for p in order:
            p.hole = [deck.pop(), deck.pop()]
        self.board = []

        # blinds (heads-up: button is the small blind)
        if n == 2:
            sb_p, bb_p = order[0], order[1]
        else:
            sb_p, bb_p = order[1], order[2]
        self._commit(sb_p, min(self.sb, sb_p.stack))
        self._commit(bb_p, min(self.bb, bb_p.stack))

        # preflop action starts left of the big blind, BB acts last
        bb_idx = order.index(bb_p)
        pre_order = order[bb_idx + 1:] + order[:bb_idx + 1]
        contested = self._betting_round('preflop', pre_order,
                                        current_bet=self.bb, min_raise=self.bb)

        post_order = order[1:] + order[:1]           # left of button first
        for street, n_cards in (('flop', 3), ('turn', 1), ('river', 1)):
            if not contested:
                break
            self.board.extend(deck.pop() for _ in range(n_cards))
            if len([p for p in order if not p.folded and not p.all_in]) >= 2:
                contested = self._betting_round(street, post_order,
                                                current_bet=0, min_raise=self.bb)
            else:
                contested = len([p for p in order if not p.folded]) >= 2

        # run out the board if we stopped early because everyone is all in
        while contested and len(self.board) < 5:
            self.board.append(deck.pop())

        self._settle(order)
        self._process_eliminations(order)
        self.button = (self.button + 1) % max(1, len(self.alive()))

    # ------------------------------------------------------------------
    def _commit(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.committed_street += amount
        p.committed_total += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    def _pot(self, order):
        return sum(p.committed_total for p in order)

    def _view(self, p, order, street, current_bet, min_raise, queue):
        return {
            'my_id': p.id,
            'street': street,
            'hole': list(p.hole),
            'board': list(self.board),
            'pot': self._pot(order),
            'to_call': max(0, current_bet - p.committed_street),
            'current_bet': current_bet,
            'min_raise': min_raise,
            'my_stack': p.stack,
            'my_committed_street': p.committed_street,
            'big_blind': self.bb,
            'num_in_hand': len([q for q in order if not q.folded]),
            'players_behind': len(queue),
            'opponents': [{'id': q.id, 'stack': q.stack,
                           'committed_street': q.committed_street,
                           'folded': q.folded, 'all_in': q.all_in}
                          for q in order if q is not p],
            'history': list(self.history),
        }

    def _broadcast(self, order, event):
        self.history.append(event)
        for p in order:
            p.strategy.observe(dict(event))

    # ------------------------------------------------------------------
    def _betting_round(self, street, act_order, current_bet, min_raise):
        """Returns True if the hand is still contested (>=2 unfolded)."""
        eligible = [p for p in act_order if not p.folded and not p.all_in]
        queue = deque(eligible)

        while queue:
            if len([p for p in act_order if not p.folded]) < 2:
                break
            p = queue.popleft()
            if p.folded or p.all_in:
                continue
            view = self._view(p, act_order, street, current_bet, min_raise, queue)
            action = p.strategy.act(view)
            to_call = max(0, current_bet - p.committed_street)
            kind = action[0]

            if kind == 'fold' and to_call > 0:
                p.folded = True
                self._broadcast(act_order, {
                    'player': p.id, 'street': street, 'action': 'fold',
                    'paid': 0, 'all_in': False, 'voluntary': True})
                continue

            if kind in ('fold', 'call', 'check'):
                paid = self._commit(p, to_call)
                self._broadcast(act_order, {
                    'player': p.id, 'street': street,
                    'action': 'call' if to_call > 0 else 'check',
                    'paid': paid, 'all_in': p.all_in,
                    'voluntary': to_call > 0})
                continue

            # raise: action[1] is the desired total street commitment
            target = int(action[1])
            max_target = p.committed_street + p.stack
            min_target = current_bet + min_raise
            if target >= max_target:
                target = max_target                      # all-in
            elif target < min_target:
                if to_call >= p.stack:
                    target = max_target                  # forced all-in call
                else:
                    target = min(min_target, max_target)
            if target <= current_bet:                    # can't actually raise
                paid = self._commit(p, min(to_call, p.stack))
                self._broadcast(act_order, {
                    'player': p.id, 'street': street,
                    'action': 'call' if to_call > 0 else 'check',
                    'paid': paid, 'all_in': p.all_in,
                    'voluntary': to_call > 0})
                continue

            paid = self._commit(p, target - p.committed_street)
            raise_size = p.committed_street - current_bet
            if raise_size >= min_raise:
                min_raise = raise_size
            current_bet = p.committed_street
            self._broadcast(act_order, {
                'player': p.id, 'street': street, 'action': 'raise',
                'paid': paid, 'to_amount': current_bet,
                'all_in': p.all_in, 'voluntary': True})
            # action reopens for everyone else still able to act
            in_queue = set(id(q) for q in queue)
            for q in act_order:
                if q is not p and not q.folded and not q.all_in \
                        and id(q) not in in_queue:
                    queue.append(q)
                    in_queue.add(id(q))

        return len([p for p in act_order if not p.folded]) >= 2

    # ------------------------------------------------------------------
    def _settle(self, order):
        unfolded = [p for p in order if not p.folded]

        # refund any uncalled excess to the (unique) largest contributor
        conts = sorted(order, key=lambda p: p.committed_total, reverse=True)
        if len(conts) >= 2 and conts[0].committed_total > conts[1].committed_total:
            top = conts[0]
            excess = top.committed_total - conts[1].committed_total
            top.committed_total -= excess
            top.stack += excess
            if top.stack > 0:
                top.all_in = False

        if len(unfolded) == 1:
            winner = unfolded[0]
            winner.stack += sum(p.committed_total for p in order)
            return

        # side pots: peel off contribution layers from smallest up
        remaining = {p: p.committed_total for p in order if p.committed_total > 0}
        pots = []
        carry = 0
        while remaining:
            layer = min(remaining.values())
            payers = list(remaining.keys())
            amount = layer * len(payers) + carry
            eligible = [p for p in payers if not p.folded]
            if eligible:
                pots.append((amount, eligible))
                carry = 0
            else:
                carry = amount
            for p in payers:
                remaining[p] -= layer
                if remaining[p] == 0:
                    del remaining[p]
        if carry and pots:
            pots[-1] = (pots[-1][0] + carry, pots[-1][1])

        scores = {p: evaluate(p.hole + self.board) for p in unfolded}
        for amount, eligible in pots:
            best = max(scores[p] for p in eligible)
            winners = [p for p in eligible if scores[p] == best]
            share = amount // len(winners)
            for w in winners:
                w.stack += share
            # odd chips to the winner seated earliest after the button
            leftover = amount - share * len(winners)
            if leftover:
                for p in order:
                    if p in winners:
                        p.stack += leftover
                        break

    def _process_eliminations(self, order):
        busted = [p for p in order if p.stack == 0]
        # players who started the hand with fewer chips finish lower
        busted.sort(key=lambda p: p.committed_total)
        self.eliminated.extend(busted)
