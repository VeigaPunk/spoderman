"""Texas Hold'em tournament engine: blinds, betting rounds, side pots, busts.

Sit-and-go format: 6 players, equal stacks, escalating blinds, play until one
player holds every chip. Strategies only ever see a GameView — they never see
each other's hole cards or each other's code.
"""

import random
from dataclasses import dataclass, field

from cards import new_deck, evaluate7


@dataclass
class GameView:
    """Everything a strategy is allowed to know when acting."""
    hole: tuple
    board: tuple
    street: str                 # 'preflop' | 'flop' | 'turn' | 'river'
    pot: int
    to_call: int
    min_raise_to: int           # minimum legal total bet this street
    my_stack: int
    my_bet: int                 # what I've already put in this street
    my_seat: int
    button_seat: int
    seats_active: tuple         # seats still in the hand (not folded, incl. all-in)
    stacks: dict                # seat -> current stack (public info)
    n_players_left: int         # players still alive in the tournament
    hand_no: int
    big_blind: int
    aggression_log: tuple       # public history: (seat, action, street) this hand
    rng: random.Random          # per-hand RNG the strategy may use


@dataclass
class Seat:
    seat_no: int
    strategy: object
    stack: int
    hole: tuple = ()
    folded: bool = False
    all_in: bool = False
    bet_street: int = 0     # chips committed this street
    bet_hand: int = 0       # chips committed this hand (for side pots)
    out: bool = False


BLIND_SCHEDULE = [(10, 20), (15, 30), (25, 50), (50, 100), (75, 150),
                  (100, 200), (150, 300), (200, 400), (300, 600), (500, 1000)]
HANDS_PER_LEVEL = 8
MAX_HANDS = 400


class Tournament:
    def __init__(self, strategies, starting_stack=1000, seed=0):
        self.rng = random.Random(seed)
        self.seats = [Seat(i + 1, s, starting_stack) for i, s in enumerate(strategies)]
        self.button = self.rng.randrange(len(self.seats))
        self.hand_no = 0

    # ------------------------------------------------------------------ helpers
    def alive(self):
        return [s for s in self.seats if not s.out]

    def _next_alive(self, idx):
        n = len(self.seats)
        j = idx
        while True:
            j = (j + 1) % n
            if not self.seats[j].out:
                return j

    def blinds(self):
        level = min(self.hand_no // HANDS_PER_LEVEL, len(BLIND_SCHEDULE) - 1)
        return BLIND_SCHEDULE[level]

    # ------------------------------------------------------------------ betting
    def _post(self, seat, amount):
        pay = min(amount, seat.stack)
        seat.stack -= pay
        seat.bet_street += pay
        seat.bet_hand += pay
        if seat.stack == 0:
            seat.all_in = True
        return pay

    def _betting_round(self, street, board, first_idx, current_bet, log):
        """Run one street of betting. Returns True if hand continues."""
        seats = self.seats
        in_hand = [s for s in seats if not s.out and not s.folded]
        if len([s for s in in_hand if not s.all_in]) <= 1 and all(
                s.bet_street == current_bet or s.all_in for s in in_hand):
            return True

        sb, bb = self.blinds()
        last_raise_size = bb
        idx = first_idx
        # Every non-all-in player must act at least once and match the bet.
        pending = {s.seat_no for s in in_hand if not s.all_in}

        guard = 0
        while pending:
            guard += 1
            if guard > 200:  # safety net; should never trigger
                break
            seat = seats[idx]
            idx = self._next_alive(idx)
            if seat.out or seat.folded or seat.all_in or seat.seat_no not in pending:
                continue

            pot = sum(s.bet_hand for s in seats)
            to_call = current_bet - seat.bet_street
            min_raise_to = current_bet + last_raise_size
            view = GameView(
                hole=seat.hole, board=tuple(board), street=street, pot=pot,
                to_call=to_call, min_raise_to=min_raise_to,
                my_stack=seat.stack, my_bet=seat.bet_street, my_seat=seat.seat_no,
                button_seat=self.seats[self.button].seat_no,
                seats_active=tuple(s.seat_no for s in seats if not s.out and not s.folded),
                stacks={s.seat_no: s.stack for s in seats if not s.out},
                n_players_left=len(self.alive()), hand_no=self.hand_no,
                big_blind=bb, aggression_log=tuple(log), rng=self.rng,
            )
            action = seat.strategy.act(view)
            pending.discard(seat.seat_no)

            kind = action[0]
            if kind == "fold" and to_call > 0:
                seat.folded = True
                log.append((seat.seat_no, "fold", street))
            elif kind == "fold":  # free check instead of nonsense fold
                log.append((seat.seat_no, "check", street))
            elif kind == "call":
                self._post(seat, to_call)
                log.append((seat.seat_no, "call" if to_call else "check", street))
            elif kind == "raise":
                target = int(action[1])
                max_to = seat.bet_street + seat.stack
                target = min(max(target, min_raise_to), max_to)
                if target <= current_bet:  # can't actually raise -> call
                    self._post(seat, to_call)
                    log.append((seat.seat_no, "call", street))
                else:
                    add = target - seat.bet_street
                    self._post(seat, add)
                    if seat.bet_street > current_bet:
                        last_raise_size = max(seat.bet_street - current_bet, bb)
                        current_bet = seat.bet_street
                        log.append((seat.seat_no, "raise", street))
                        pending = {s.seat_no for s in seats
                                   if not s.out and not s.folded and not s.all_in
                                   and s.seat_no != seat.seat_no}

            if len([s for s in seats if not s.out and not s.folded]) == 1:
                return True
        return True

    # ------------------------------------------------------------------ payout
    def _payout(self, board):
        seats = self.seats
        contenders = [s for s in seats if not s.out and not s.folded]
        contributions = {s.seat_no: s.bet_hand for s in seats if s.bet_hand > 0}

        if len(contenders) == 1:
            contenders[0].stack += sum(contributions.values())
            return

        scores = {s.seat_no: evaluate7(list(s.hole) + list(board)) for s in contenders}

        # Build side pots from contribution levels.
        levels = sorted({v for v in contributions.values()})
        prev = 0
        for lv in levels:
            pot_amount = 0
            eligible = []
            for sn, contrib in contributions.items():
                take = max(0, min(contrib, lv) - prev)
                pot_amount += take
            for s in contenders:
                if contributions.get(s.seat_no, 0) >= lv:
                    eligible.append(s)
            prev = lv
            if pot_amount == 0:
                continue
            if not eligible:  # everyone at this level folded; give to best contender
                eligible = contenders
            best = max(scores[s.seat_no] for s in eligible if s.seat_no in scores)
            winners = [s for s in eligible if scores.get(s.seat_no) == best]
            share, odd = divmod(pot_amount, len(winners))
            for w in winners:
                w.stack += share
            winners[0].stack += odd  # odd chip to first winner

    # ------------------------------------------------------------------ one hand
    def play_hand(self):
        self.hand_no += 1
        seats = self.seats
        alive = self.alive()
        for s in seats:
            s.hole, s.folded, s.all_in = (), False, False
            s.bet_street = s.bet_hand = 0

        deck = new_deck(self.rng)
        for s in alive:
            s.hole = (deck.pop(), deck.pop())

        sb_amt, bb_amt = self.blinds()
        self.button = self._next_alive(self.button)
        log = []

        if len(alive) == 2:  # heads-up: button posts SB
            sb_idx = self.button
        else:
            sb_idx = self._next_alive(self.button)
        bb_idx = self._next_alive(sb_idx)
        self._post(seats[sb_idx], sb_amt)
        self._post(seats[bb_idx], bb_amt)
        first_preflop = self._next_alive(bb_idx)

        board = []
        self._betting_round("preflop", board, first_preflop, bb_amt, log)

        def live():
            return [s for s in seats if not s.out and not s.folded]

        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(live()) <= 1:
                break
            deck.pop()  # burn
            board.extend(deck.pop() for _ in range(ncards))
            for s in seats:
                s.bet_street = 0
            if len([s for s in live() if not s.all_in]) > 1:
                first = self._next_alive(self.button)
                while seats[first].out or seats[first].folded or seats[first].all_in:
                    first = self._next_alive(first)
                self._betting_round(street, board, first, 0, log)

        while len(board) < 5 and len(live()) > 1:
            deck.pop()
            board.append(deck.pop())

        self._payout(board)

        for s in seats:
            if not s.out and s.stack == 0:
                s.out = True

    # ------------------------------------------------------------------ run
    def run(self):
        """Play until one player remains. Returns winner seat number."""
        while len(self.alive()) > 1 and self.hand_no < MAX_HANDS:
            self.play_hand()
        survivors = self.alive()
        return max(survivors, key=lambda s: s.stack).seat_no
