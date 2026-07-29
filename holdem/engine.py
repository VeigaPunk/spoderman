"""No-limit Texas Hold'em tournament engine.

Runs a full sit-and-go: blinds, four betting streets, raises, all-ins,
side pots, showdowns, eliminations and escalating blinds until one player
holds every chip. Strategies receive only public information plus their
own hole cards.
"""

from .cards import new_deck, best_hand

STREETS = ('preflop', 'flop', 'turn', 'river')


class Player:
    def __init__(self, pid, name, strategy, stack):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = []
        self.in_hand = False
        self.all_in = False
        self.street_contrib = 0
        self.total_contrib = 0


class Tournament:
    def __init__(self, entries, rng, start_stack=1000, sb=10,
                 hands_per_level=8, max_hands=1000):
        self.players = []
        for i, (name, strat) in enumerate(entries):
            p = Player(f"P{i + 1}", name, strat, start_stack)
            strat.pid = p.pid
            self.players.append(p)
        self.rng = rng
        self.base_sb = sb
        self.hands_per_level = hands_per_level
        self.max_hands = max_hands
        self.button = rng.randrange(len(self.players))
        self.hand_no = 0
        self.finish_order = []  # pids, first eliminated first

    # ------------------------------------------------------------------ run
    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        survivors = sorted(self.alive(), key=lambda p: p.stack)
        for p in survivors[:-1]:
            self.finish_order.append(p.pid)
        winner = survivors[-1]
        self.finish_order.append(winner.pid)
        return winner

    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def blinds(self):
        level = self.hand_no // self.hands_per_level
        sb = self.base_sb * (2 ** min(level, 12))
        return sb, sb * 2

    # ----------------------------------------------------------- hand setup
    def play_hand(self):
        alive = self.alive()
        self.hand_no += 1
        sb_amt, bb_amt = self.blinds()
        self.bb_amt = bb_amt

        # seat order for this hand, small blind first
        self.button = self._next_alive_seat(self.button)
        btn_player = self.players[self.button]
        ordered = [p for p in self.players[self.button:] + self.players[:self.button]
                   if p.stack > 0]
        if len(alive) == 2:
            hand_players = ordered            # heads-up: button posts SB
        else:
            hand_players = ordered[1:] + ordered[:1]
        self.hand_players = hand_players

        for p in hand_players:
            p.in_hand = True
            p.all_in = False
            p.hole = []
            p.street_contrib = 0
            p.total_contrib = 0

        self._post(hand_players[0], sb_amt)
        self._post(hand_players[1], bb_amt)

        deck = new_deck()
        self.rng.shuffle(deck)
        for p in hand_players:
            p.hole = [deck.pop(), deck.pop()]
        self.board = []
        self.history = []

        n = len(hand_players)
        showdown_needed = True
        for street in STREETS:
            if street == 'flop':
                self.board += [deck.pop(), deck.pop(), deck.pop()]
            elif street in ('turn', 'river'):
                self.board.append(deck.pop())
            if street == 'preflop':
                first = 2 % n
            else:
                first = 1 if n == 2 else 0
            self._betting_round(street, first, bb_amt)
            if len([p for p in hand_players if p.in_hand]) == 1:
                showdown_needed = False
                break

        # deal any remaining board cards if everyone is all-in
        if showdown_needed:
            while len(self.board) < 5:
                self.board.append(deck.pop())

        self._settle(showdown_needed)

        for p in hand_players:
            p.in_hand = False

        busted = [p for p in hand_players if p.stack == 0]
        busted.sort(key=lambda p: p.total_contrib)
        for p in busted:
            self.finish_order.append(p.pid)

    def _next_alive_seat(self, seat):
        n = len(self.players)
        for i in range(1, n + 1):
            j = (seat + i) % n
            if self.players[j].stack > 0:
                return j
        return seat

    def _post(self, p, amount):
        pay = min(amount, p.stack)
        p.stack -= pay
        p.street_contrib += pay
        p.total_contrib += pay
        if p.stack == 0:
            p.all_in = True

    # -------------------------------------------------------- betting round
    def _betting_round(self, street, first_idx, bb_amt):
        hp = self.hand_players
        n = len(hp)
        for p in hp:
            if street != 'preflop':
                p.street_contrib = 0
        current_bet = max(p.street_contrib for p in hp)
        last_raise = bb_amt

        pending = [hp[(first_idx + i) % n] for i in range(n)]
        pending = [p for p in pending if p.in_hand and not p.all_in]

        while pending:
            if len([q for q in hp if q.in_hand]) == 1:
                return
            p = pending.pop(0)
            if not p.in_hand or p.all_in:
                continue
            to_call = current_bet - p.street_contrib
            view = self._make_view(p, street, current_bet, last_raise, to_call)
            try:
                action, amt = p.strategy.act(view)
            except Exception:
                action, amt = ('fold', 0)

            if action == 'fold' and to_call == 0:
                action = 'call'  # never fold for free

            if action == 'raise':
                max_to = p.street_contrib + p.stack
                min_to = current_bet + last_raise
                raise_to = min(int(amt), max_to)
                if raise_to <= current_bet:
                    action = 'call'
                else:
                    if raise_to < min_to and raise_to < max_to:
                        raise_to = min(min_to, max_to)
                    pay = raise_to - p.street_contrib
                    p.stack -= pay
                    p.street_contrib = raise_to
                    p.total_contrib += pay
                    if p.stack == 0:
                        p.all_in = True
                    diff = raise_to - current_bet
                    if diff >= last_raise:
                        last_raise = diff
                    current_bet = raise_to
                    self._broadcast(p, street, 'raise', raise_to, p.all_in)
                    idx = hp.index(p)
                    pending = [hp[(idx + i) % n] for i in range(1, n)]
                    pending = [q for q in pending if q.in_hand and not q.all_in]
                    continue

            if action == 'call':
                pay = min(to_call, p.stack)
                p.stack -= pay
                p.street_contrib += pay
                p.total_contrib += pay
                if p.stack == 0 and pay > 0:
                    p.all_in = True
                self._broadcast(p, street, 'call' if pay else 'check', pay,
                                p.all_in)
            else:  # fold
                p.in_hand = False
                self._broadcast(p, street, 'fold', 0, False)

    def _broadcast(self, p, street, action, amount, all_in):
        event = {'pid': p.pid, 'street': street, 'action': action,
                 'amount': amount, 'all_in': all_in}
        self.history.append(event)
        for q in self.players:
            if q.stack > 0 or q.in_hand:
                try:
                    q.strategy.on_action(event)
                except Exception:
                    pass

    # -------------------------------------------------------------- views
    def _make_view(self, p, street, current_bet, last_raise, to_call):
        hp = self.hand_players
        in_hand = [q for q in hp if q.in_hand]
        order = [q for q in in_hand if not q.all_in]
        pos = order.index(p) if p in order else 0
        return {
            'pid': p.pid,
            'hole': list(p.hole),
            'board': list(self.board),
            'street': street,
            'pot': sum(q.total_contrib for q in hp),
            'to_call': min(to_call, p.stack),
            'current_bet': current_bet,
            'min_raise_to': current_bet + last_raise,
            'my_stack': p.stack,
            'my_street_contrib': p.street_contrib,
            'big_blind': self.bb_amt,
            'players_in_hand': len(in_hand),
            'position_ratio': pos / max(1, len(order) - 1) if len(order) > 1 else 1.0,
            'opponents': [
                {'pid': q.pid, 'stack': q.stack, 'in_hand': q.in_hand,
                 'all_in': q.all_in}
                for q in hp if q is not p
            ],
            'history': list(self.history),
        }

    # ----------------------------------------------------------- settlement
    def _settle(self, showdown):
        hp = self.hand_players
        in_hand = [p for p in hp if p.in_hand]
        showdown_info = []

        if not showdown or len(in_hand) == 1:
            winner = in_hand[0]
            winner.stack += sum(p.total_contrib for p in hp)
            winners = [winner.pid]
        else:
            vals = {p.pid: best_hand(p.hole + self.board) for p in in_hand}
            showdown_info = [(p.pid, list(p.hole)) for p in in_hand]
            remaining = {p.pid: p.total_contrib for p in hp}
            winners = set()
            while True:
                live = [remaining[p.pid] for p in in_hand if remaining[p.pid] > 0]
                if not live:
                    break
                level = min(live)
                eligible = [p for p in in_hand if remaining[p.pid] >= level]
                pot = 0
                for p in hp:
                    take = min(remaining[p.pid], level)
                    remaining[p.pid] -= take
                    pot += take
                best = max(vals[p.pid] for p in eligible)
                pot_winners = [p for p in eligible if vals[p.pid] == best]
                share = pot // len(pot_winners)
                for p in pot_winners:
                    p.stack += share
                    winners.add(p.pid)
                pot_winners[0].stack += pot - share * len(pot_winners)
            leftover = sum(remaining.values())
            if leftover:  # folded chips beyond every showdown stack (rare)
                in_hand[0].stack += leftover
            winners = sorted(winners)

        info = {'winners': list(winners),
                'pot': sum(p.total_contrib for p in hp),
                'showdown': showdown_info}
        for q in self.players:
            try:
                q.strategy.on_hand_end(info)
            except Exception:
                pass
