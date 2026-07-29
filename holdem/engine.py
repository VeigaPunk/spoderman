"""No-limit Texas Hold'em tournament engine.

Implements a full single-table freezeout: rotating button, escalating blinds,
four betting streets with proper min-raise rules (including the rule that a
short all-in does not reopen betting), layered side pots, and showdown with
split-pot remainders awarded left of the button.

Strategies only ever see the ``Observation`` handed to ``act``. That contains
public table state plus the strategy's own hole cards -- never another
player's cards or another player's strategy identity.
"""

import random
from collections import namedtuple

from .cards import evaluate, FULL_DECK

FOLD = "fold"
CHECK = "check"
CALL = "call"
RAISE = "raise"

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
STREET_NAMES = ["preflop", "flop", "turn", "river"]

# (small blind, big blind, ante) -- the level advances every LEVEL_LENGTH hands.
BLIND_SCHEDULE = [
    (25, 50, 0), (50, 100, 0), (75, 150, 0), (100, 200, 25),
    (150, 300, 25), (200, 400, 50), (300, 600, 75), (400, 800, 100),
    (600, 1200, 150), (800, 1600, 200), (1200, 2400, 300),
    (2000, 4000, 500), (3000, 6000, 750), (5000, 10000, 1000),
    (8000, 16000, 2000), (12000, 24000, 3000),
]
LEVEL_LENGTH = 20

# Public snapshot of one seat, as visible to every strategy.
SeatView = namedtuple("SeatView", [
    "player_id", "chips", "street_bet", "committed", "in_hand", "all_in",
])

Observation = namedtuple("Observation", [
    "player_id",       # who is being asked to act
    "hole",            # this player's two hole cards
    "board",           # 0, 3, 4 or 5 community cards
    "street",          # PREFLOP..RIVER
    "pot",             # chips already in the middle, incl. this street's bets
    "to_call",         # chips needed to match the current bet (0 = can check)
    "min_raise_to",    # smallest legal total for a raise
    "max_raise_to",    # this player's stack + their street bet (i.e. all-in)
    "chips",           # this player's remaining stack
    "street_bet",      # what this player has already put in this street
    "committed",       # what this player has put in across the whole hand
    "big_blind",
    "small_blind",
    "ante",
    "seats",           # tuple of SeatView, seat order
    "button",          # seat index of the button
    "seat_index",      # this player's seat index
    "actors_after",    # how many live players still act behind this one
    "num_in_hand",     # players who have not folded
    "action_log",      # [(player_id, street, action, amount)] for this hand
    "hand_number",
    "starting_stacks", # {player_id: chips at the start of this hand}
])


class Seat:
    __slots__ = ("player_id", "strategy", "chips", "hole", "street_bet",
                 "committed", "in_hand", "all_in", "acted")

    def __init__(self, player_id, strategy, chips):
        self.player_id = player_id
        self.strategy = strategy
        self.chips = chips
        self.hole = ()
        self.street_bet = 0
        self.committed = 0
        self.in_hand = False
        self.all_in = False
        self.acted = False

    def view(self):
        return SeatView(self.player_id, self.chips, self.street_bet,
                        self.committed, self.in_hand, self.all_in)


class Table:
    """One freezeout tournament. Runs until a single player holds every chip."""

    def __init__(self, strategies, starting_chips=10000, seed=None,
                 max_hands=1500, log=None):
        self.rng = random.Random(seed)
        self.seats = [Seat(i + 1, s, starting_chips)
                      for i, s in enumerate(strategies)]
        self.starting_chips = starting_chips
        self.max_hands = max_hands
        self.log = log
        self.button = self.rng.randrange(len(self.seats))
        self.hand_number = 0
        self.action_log = []
        self.board = []
        self.finish_order = []      # busted first .. busted last
        self.hands_survived = {s.player_id: 0 for s in self.seats}
        self.hit_hand_cap = False

    # ---------------------------------------------------------------- helpers

    def _live(self):
        return [s for s in self.seats if s.chips > 0]

    def _blinds(self):
        level = min(self.hand_number // LEVEL_LENGTH, len(BLIND_SCHEDULE) - 1)
        return BLIND_SCHEDULE[level]

    def _broadcast(self, seat, action, amount):
        self.action_log.append((seat.player_id, self.street, action, amount))
        for other in self.seats:
            observer = getattr(other.strategy, "observe_action", None)
            if observer is not None:
                observer(seat.player_id, self.street, action, amount,
                         self.pot, self.current_bet)

    def _note(self, text):
        if self.log is not None:
            self.log.append(text)

    # ------------------------------------------------------------- tournament

    def run(self):
        while True:
            live = self._live()
            if len(live) <= 1:
                break
            if self.hand_number >= self.max_hands:
                # Safety valve. Rank the survivors by stack and stop.
                self.hit_hand_cap = True
                for s in sorted(live, key=lambda s: s.chips):
                    self.finish_order.append(s.player_id)
                break
            self.play_hand()
            self.hand_number += 1
            for s in live:
                if s.chips > 0:
                    self.hands_survived[s.player_id] += 1

        if not self.hit_hand_cap:
            survivors = self._live()
            for s in survivors:
                self.finish_order.append(s.player_id)
        winner = self.finish_order[-1] if self.finish_order else None
        return winner

    # ------------------------------------------------------------------- hand

    def play_hand(self):
        live = self._live()
        n = len(live)
        seats = live
        self.hand_seats = seats
        self.action_log = []
        self.board = []
        self.street = PREFLOP
        self.starting_stacks = {s.player_id: s.chips for s in seats}

        for s in seats:
            s.street_bet = 0
            s.committed = 0
            s.in_hand = True
            s.all_in = False
            s.acted = False

        for s in self.seats:
            hook = getattr(s.strategy, "new_hand", None)
            if hook is not None:
                hook(self.hand_number, self.starting_stacks)

        # Move the button to the next live seat.
        order = [i for i, s in enumerate(self.seats) if s.chips > 0]
        nxt = None
        for offset in range(1, len(self.seats) + 1):
            cand = (self.button + offset) % len(self.seats)
            if cand in order:
                nxt = cand
                break
        self.button = nxt
        button_pos = seats.index(self.seats[self.button])

        sb_amt, bb_amt, ante = self._blinds()
        self.small_blind, self.big_blind, self.ante = sb_amt, bb_amt, ante
        self.pot = 0

        for s in seats:
            if ante:
                # Antes are dead money: they never count as a bet to match.
                self._commit(s, min(ante, s.chips), as_bet=False)

        if n == 2:
            sb_pos, bb_pos = button_pos, (button_pos + 1) % 2
        else:
            sb_pos = (button_pos + 1) % n
            bb_pos = (button_pos + 2) % n

        self._commit(seats[sb_pos], min(sb_amt, seats[sb_pos].chips))
        self._commit(seats[bb_pos], min(bb_amt, seats[bb_pos].chips))
        self.current_bet = max(s.street_bet for s in seats)
        self.min_raise_size = bb_amt
        self.button_pos = button_pos

        deck = list(FULL_DECK)
        self.rng.shuffle(deck)
        d = 0
        for s in seats:
            s.hole = (deck[d], deck[d + 1])
            d += 2

        first = (bb_pos + 1) % n if n > 2 else sb_pos
        self._betting_round(seats, first)

        for street, cards in ((FLOP, 3), (TURN, 1), (RIVER, 1)):
            if self._still_contested(seats) is False:
                break
            self.street = street
            self.board.extend(deck[d:d + cards])
            d += cards
            for s in seats:
                s.street_bet = 0
                s.acted = False
            self.current_bet = 0
            self.min_raise_size = self.big_blind
            if self._can_still_bet(seats):
                first_post = (button_pos + 1) % n
                self._betting_round(seats, first_post)

        self._showdown(seats)

        # When several players bust on the same hand, the one who started it
        # with fewer chips finishes lower.
        busted = [s for s in seats
                  if s.chips <= 0 and s.player_id not in self.finish_order]
        busted.sort(key=lambda s: self.starting_stacks[s.player_id])
        for s in busted:
            self.finish_order.append(s.player_id)

    def _still_contested(self, seats):
        return sum(1 for s in seats if s.in_hand) > 1

    def _can_still_bet(self, seats):
        return sum(1 for s in seats if s.in_hand and not s.all_in) > 1

    def _commit(self, seat, amount, as_bet=True):
        amount = min(amount, seat.chips)
        seat.chips -= amount
        if as_bet:
            seat.street_bet += amount
        seat.committed += amount
        self.pot += amount
        if seat.chips == 0:
            seat.all_in = True
        return amount

    # --------------------------------------------------------- betting rounds

    def _betting_round(self, seats, first):
        n = len(seats)
        i = first
        guard = 0
        while True:
            guard += 1
            if guard > 400:
                break
            if not self._still_contested(seats):
                break
            if not self._needs_action(seats):
                break
            seat = seats[i]
            if seat.in_hand and not seat.all_in and \
                    (not seat.acted or seat.street_bet < self.current_bet):
                self._act(seats, seat, i)
            i = (i + 1) % n

    def _needs_action(self, seats):
        for s in seats:
            if s.in_hand and not s.all_in and \
                    (not s.acted or s.street_bet < self.current_bet):
                # A lone player with nobody left to call cannot be made to act.
                others = [o for o in seats
                          if o is not s and o.in_hand and not o.all_in]
                if not others and s.street_bet >= self.current_bet:
                    continue
                return True
        return False

    def _act(self, seats, seat, seat_pos):
        n = len(seats)
        to_call = min(self.current_bet - seat.street_bet, seat.chips)
        max_raise_to = seat.street_bet + seat.chips
        min_raise_to = self.current_bet + self.min_raise_size
        if min_raise_to > max_raise_to:
            min_raise_to = max_raise_to

        actors_after = 0
        for offset in range(1, n):
            o = seats[(seat_pos + offset) % n]
            if o.in_hand and not o.all_in:
                actors_after += 1

        obs = Observation(
            player_id=seat.player_id,
            hole=seat.hole,
            board=tuple(self.board),
            street=self.street,
            pot=self.pot,
            to_call=to_call,
            min_raise_to=min_raise_to,
            max_raise_to=max_raise_to,
            chips=seat.chips,
            street_bet=seat.street_bet,
            committed=seat.committed,
            big_blind=self.big_blind,
            small_blind=self.small_blind,
            ante=self.ante,
            seats=tuple(s.view() for s in seats),
            button=self.button_pos,
            seat_index=seat_pos,
            actors_after=actors_after,
            num_in_hand=sum(1 for s in seats if s.in_hand),
            action_log=tuple(self.action_log),
            hand_number=self.hand_number,
            starting_stacks=dict(self.starting_stacks),
        )

        try:
            decision = seat.strategy.act(obs, self.rng)
        except Exception:
            decision = (CHECK if to_call == 0 else FOLD, 0)

        action, amount = self._normalise(decision, obs)
        seat.acted = True

        if action == FOLD:
            seat.in_hand = False
            self._broadcast(seat, FOLD, 0)
            return

        if action in (CHECK, CALL):
            paid = self._commit(seat, to_call)
            self._broadcast(seat, CHECK if to_call == 0 else CALL, paid)
            return

        # RAISE: `amount` is the total this player's street bet becomes.
        previous_bet = self.current_bet
        paid = self._commit(seat, amount - seat.street_bet)
        raise_size = seat.street_bet - previous_bet
        if seat.street_bet > previous_bet:
            self.current_bet = seat.street_bet
            if raise_size >= self.min_raise_size:
                # A full raise reopens the action for everyone behind.
                self.min_raise_size = raise_size
                for o in seats:
                    if o is not seat and o.in_hand and not o.all_in:
                        o.acted = False
            # A short all-in raise does NOT reopen betting: `acted` stays set.
        self._broadcast(seat, RAISE, paid)

    def _normalise(self, decision, obs):
        """Clamp whatever a strategy returned into a legal action."""
        if isinstance(decision, str):
            action, amount = decision, 0
        else:
            action, amount = decision[0], (decision[1] if len(decision) > 1 else 0)

        if action == RAISE:
            amount = int(amount)
            if amount >= obs.max_raise_to:
                amount = obs.max_raise_to          # all-in
            elif amount < obs.min_raise_to:
                # Not enough for a legal raise -> treat as a call.
                return (CALL if obs.to_call > 0 else CHECK), 0
            if amount <= obs.street_bet:
                return (CALL if obs.to_call > 0 else CHECK), 0
            return RAISE, amount

        if action == FOLD:
            # Folding when it is free is strictly dominated; check instead.
            return (FOLD, 0) if obs.to_call > 0 else (CHECK, 0)

        if action == CHECK and obs.to_call > 0:
            return CALL, 0
        if action == CALL and obs.to_call == 0:
            return CHECK, 0
        return action, 0

    # -------------------------------------------------------------- showdown

    def _showdown(self, seats):
        contenders = [s for s in seats if s.in_hand]

        if len(contenders) == 1:
            winner = contenders[0]
            winner.chips += self.pot
            self._note("hand %d: player %d takes %d uncontested"
                       % (self.hand_number, winner.player_id, self.pot))
            self._report_hand(seats, {winner.player_id: self.pot}, showdown=False)
            self.pot = 0
            return

        # Deal out any missing community cards (everyone was all-in earlier).
        if len(self.board) < 5:
            used = set(self.board)
            for s in seats:
                used.update(s.hole)
            deck = [c for c in FULL_DECK if c not in used]
            self.rng.shuffle(deck)
            self.board.extend(deck[:5 - len(self.board)])

        strength = {}
        for s in contenders:
            strength[s.player_id] = evaluate(tuple(s.hole) + tuple(self.board))

        payouts = {}
        for amount, eligible in self._build_pots(seats):
            live_eligible = [s for s in eligible if s.in_hand]
            if not live_eligible:
                continue
            best = max(strength[s.player_id] for s in live_eligible)
            winners = [s for s in live_eligible if strength[s.player_id] == best]
            share, remainder = divmod(amount, len(winners))
            for w in winners:
                w.chips += share
                payouts[w.player_id] = payouts.get(w.player_id, 0) + share
            # Odd chips go to the first winner left of the button.
            if remainder:
                ordered = sorted(
                    winners,
                    key=lambda s: (seats.index(s) - self.button_pos - 1) % len(seats))
                ordered[0].chips += remainder
                payouts[ordered[0].player_id] = \
                    payouts.get(ordered[0].player_id, 0) + remainder

        self._report_hand(seats, payouts, showdown=True, strength=strength)
        self.pot = 0

    def _build_pots(self, seats):
        """Split the money into a main pot plus one side pot per all-in level."""
        levels = sorted({s.committed for s in seats if s.committed > 0})
        pots = []
        previous = 0
        for level in levels:
            amount = 0
            eligible = []
            for s in seats:
                contribution = min(s.committed, level)
                if contribution > previous:
                    amount += contribution - previous
                if s.committed >= level:
                    eligible.append(s)
            if amount > 0:
                pots.append((amount, eligible))
            previous = level
        return pots

    def _report_hand(self, seats, payouts, showdown, strength=None):
        for s in self.seats:
            hook = getattr(s.strategy, "observe_hand_end", None)
            if hook is not None:
                hook(payouts, showdown,
                     {x.player_id: (x.hole if showdown and x.in_hand else None)
                      for x in seats},
                     tuple(self.board))
