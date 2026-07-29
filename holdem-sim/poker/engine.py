"""No-limit Texas Hold'em tournament engine.

Supports 2-9 players, blinds that escalate, all-ins and side pots.
Strategies only see public information (their own hole cards, the board,
stacks, pot, and a running table of observed opponent tendencies) — they
never see each other's code or cards.
"""

from dataclasses import dataclass, field
from .cards import new_deck, evaluate


@dataclass
class Observation:
    """Everything a strategy is allowed to know when it acts."""
    street: str                # 'preflop' | 'flop' | 'turn' | 'river'
    hole: tuple
    board: list
    pot: int                   # total chips in the middle (all contributions)
    to_call: int
    current_bet: int           # highest street contribution so far
    min_raise: int
    big_blind: int
    stack: int                 # chips behind (not counting street_contrib)
    street_contrib: int
    my_seat: int
    position: str              # 'sb' | 'bb' | 'early' | 'middle' | 'late' | 'button'
    n_in_hand: int             # players still contesting the pot
    n_alive: int               # players still in the tournament
    opp_stacks: dict           # seat -> stack, for everyone still in the hand
    stats: dict                # seat -> observed tendencies (public actions only)
    last_aggressor: int | None # seat of the last bettor/raiser this street
    rng: object                # tournament RNG (for mixed strategies)

    @property
    def pot_odds(self):
        return self.to_call / (self.pot + self.to_call) if self.to_call > 0 else 0.0


@dataclass
class Seat:
    seat_id: int
    name: str
    strategy: object
    stack: int


@dataclass
class HandPlayer:
    seat: Seat
    hole: tuple = None
    in_hand: bool = True
    all_in: bool = False
    street_contrib: int = 0
    total_contrib: int = 0
    vpip_counted: bool = False


def _blank_stats():
    return {"hands": 0, "vpip": 0, "pfr": 0, "allins": 0, "showdowns": 0}


class Tournament:
    def __init__(self, seats, rng, start_blinds=(10, 20), hands_per_level=20,
                 max_hands=2000):
        self.seats = seats
        self.rng = rng
        self.start_blinds = start_blinds
        self.hands_per_level = hands_per_level
        self.max_hands = max_hands
        self.stats = {s.seat_id: _blank_stats() for s in seats}
        self.bust_order = []  # seat_ids in the order they busted

    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def run(self):
        """Play until one player has all the chips. Returns finishing order,
        winner first."""
        button = self.rng.randrange(len(self.seats))
        hand_no = 0
        while len(self.alive()) > 1 and hand_no < self.max_hands:
            level = hand_no // self.hands_per_level
            sb = self.start_blinds[0] * (2 ** level)
            bb = self.start_blinds[1] * (2 ** level)
            alive = self.alive()
            # find the button among alive seats (nearest seat >= button marker)
            alive_ids = [s.seat_id for s in alive]
            while button not in alive_ids:
                button = (button + 1) % len(self.seats)
            self._play_hand(alive, alive_ids.index(button), sb, bb)
            hand_no += 1
            # record busts from this hand (stable order by stack-at-zero)
            for s in self.seats:
                if s.stack == 0 and s.seat_id not in self.bust_order:
                    self.bust_order.append(s.seat_id)
            button = (button + 1) % len(self.seats)

        survivors = sorted(self.alive(), key=lambda s: s.stack)
        for s in survivors:  # if hand cap hit, rank remaining by stack
            if s.seat_id not in self.bust_order:
                self.bust_order.append(s.seat_id)
        return list(reversed(self.bust_order))  # winner first

    # ------------------------------------------------------------------ #

    def _play_hand(self, alive, button_idx, sb, bb):
        n = len(alive)
        for s in alive:
            self.stats[s.seat_id]["hands"] += 1

        if n == 2:
            # heads-up: button posts the small blind and acts first preflop
            sb_i, bb_i = button_idx, (button_idx + 1) % 2
            table_order = [alive[sb_i], alive[bb_i]]
        else:
            rot = alive[button_idx + 1:] + alive[:button_idx + 1]
            table_order = rot  # [sb, bb, utg, ..., button]

        players = [HandPlayer(seat=s) for s in table_order]
        sb_p, bb_p = players[0], players[1]

        deck = new_deck()
        self.rng.shuffle(deck)
        for p in players:
            p.hole = (deck.pop(), deck.pop())

        self._post(sb_p, sb)
        self._post(bb_p, bb)

        board = []
        positions = self._positions(players)

        if n == 2:
            preflop_order = [players[0], players[1]]   # sb (button) first
            postflop_order = [players[1], players[0]]  # bb first
        else:
            preflop_order = players[2:] + players[:2]  # utg ... button, sb, bb
            postflop_order = players                   # sb first

        # betting streets
        streets = [("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)]
        for street, n_cards in streets:
            for _ in range(n_cards):
                board.append(deck.pop())
            if street == "preflop":
                current_bet, min_raise = bb, bb
                order = preflop_order
            else:
                current_bet, min_raise = 0, bb
                order = postflop_order
                for p in players:
                    p.street_contrib = 0
            contenders = [p for p in players if p.in_hand]
            if len(contenders) <= 1:
                break
            if all(p.all_in for p in contenders) or \
               sum(1 for p in contenders if not p.all_in) <= 1 and current_bet == 0:
                continue  # everyone is committed, just run out the board
            self._betting_round(players, order, street, board, current_bet,
                                min_raise, bb, positions)

        self._showdown(players, board)

    def _positions(self, players):
        n = len(players)
        pos = {}
        for i, p in enumerate(players):
            if n == 2:
                pos[p.seat.seat_id] = "button" if i == 0 else "bb"
            elif i == 0:
                pos[p.seat.seat_id] = "sb"
            elif i == 1:
                pos[p.seat.seat_id] = "bb"
            elif i == n - 1:
                pos[p.seat.seat_id] = "button"
            elif i < 1 + (n - 2) / 2:
                pos[p.seat.seat_id] = "early"
            elif i < n - 2:
                pos[p.seat.seat_id] = "middle"
            else:
                pos[p.seat.seat_id] = "late"
        return pos

    def _post(self, p, amount):
        pay = min(amount, p.seat.stack)
        p.seat.stack -= pay
        p.street_contrib += pay
        p.total_contrib += pay
        if p.seat.stack == 0:
            p.all_in = True

    def _betting_round(self, players, order, street, board, current_bet,
                       min_raise, bb, positions):
        last_aggressor = None
        queue = [p for p in order if p.in_hand and not p.all_in]
        guard = 0
        while queue:
            guard += 1
            if guard > 500:  # safety valve; cannot happen with sane strategies
                break
            p = queue.pop(0)
            if not p.in_hand or p.all_in:
                continue
            if sum(1 for q in players if q.in_hand) == 1:
                break

            to_call = current_bet - p.street_contrib
            obs = Observation(
                street=street,
                hole=p.hole,
                board=list(board),
                pot=sum(q.total_contrib for q in players),
                to_call=to_call,
                current_bet=current_bet,
                min_raise=min_raise,
                big_blind=bb,
                stack=p.seat.stack,
                street_contrib=p.street_contrib,
                my_seat=p.seat.seat_id,
                position=positions[p.seat.seat_id],
                n_in_hand=sum(1 for q in players if q.in_hand),
                n_alive=len(players),
                opp_stacks={q.seat.seat_id: q.seat.stack for q in players
                            if q.in_hand and q is not p},
                stats=self.stats,
                last_aggressor=last_aggressor,
                rng=self.rng,
            )
            action = p.seat.strategy.act(obs)

            if action == "fold" and to_call == 0:
                action = "check_call"  # never fold for free

            if action == "fold":
                p.in_hand = False
                continue

            if action == "check_call":
                pay = min(to_call, p.seat.stack)
                self._commit(p, pay, street)
                continue

            # ('raise', raise_to_total_for_this_street)
            _, raise_to = action
            max_to = p.street_contrib + p.seat.stack
            raise_to = min(int(raise_to), max_to)
            if raise_to <= current_bet:  # cannot actually raise -> call
                pay = min(to_call, p.seat.stack)
                self._commit(p, pay, street)
                continue
            if raise_to < current_bet + min_raise and raise_to < max_to:
                raise_to = min(current_bet + min_raise, max_to)
            pay = raise_to - p.street_contrib
            self._commit(p, pay, street)
            if raise_to - current_bet >= min_raise:
                min_raise = raise_to - current_bet
            current_bet = raise_to
            last_aggressor = p.seat.seat_id
            st = self.stats[p.seat.seat_id]
            if street == "preflop":
                st["pfr"] += 1
            # everyone else still live gets to act again, in table order after p
            idx = order.index(p)
            rot = order[idx + 1:] + order[:idx]
            queue = [q for q in rot if q.in_hand and not q.all_in]

    def _commit(self, p, pay, street):
        p.seat.stack -= pay
        p.street_contrib += pay
        p.total_contrib += pay
        st = self.stats[p.seat.seat_id]
        if street == "preflop" and pay > 0 and not p.vpip_counted:
            st["vpip"] += 1
            p.vpip_counted = True
        if p.seat.stack == 0:
            p.all_in = True
            st["allins"] += 1

    def _showdown(self, players, board):
        contenders = [p for p in players if p.in_hand]
        if len(contenders) == 1:
            contenders[0].seat.stack += sum(p.total_contrib for p in players)
            return

        for p in contenders:
            self.stats[p.seat.seat_id]["showdowns"] += 1
        values = {id(p): evaluate(list(p.hole) + board) for p in contenders}

        # build main + side pots from contribution levels
        levels = sorted({p.total_contrib for p in players if p.total_contrib > 0})
        prev = 0
        for lvl in levels:
            pot = sum(min(p.total_contrib, lvl) - min(p.total_contrib, prev)
                      for p in players)
            prev = lvl
            eligible = [p for p in contenders if p.total_contrib >= lvl]
            if not eligible or pot == 0:
                continue
            best = max(values[id(p)] for p in eligible)
            winners = [p for p in eligible if values[id(p)] == best]
            share, rem = divmod(pot, len(winners))
            for i, w in enumerate(winners):
                w.seat.stack += share + (1 if i < rem else 0)
