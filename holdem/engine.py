"""No-limit Texas Hold'em table engine: betting, side pots, showdown.

Strategies interact with the engine only through `GameView` (public
information + their own hole cards) and their returned actions, so no
player can see another player's cards or strategy.
"""

import random
from collections import deque

from .cards import best7

STREETS = ("preflop", "flop", "turn", "river")


class GameView:
    """Everything a strategy is allowed to know when acting."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Seat:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack
        self.hole = []
        self.in_hand = False
        self.total_commit = 0
        self.street_commit = 0

    @property
    def all_in(self):
        return self.in_hand and self.stack == 0

    def pay(self, amount):
        amount = min(amount, self.stack)
        self.stack -= amount
        self.total_commit += amount
        self.street_commit += amount
        return amount


class Table:
    def __init__(self, seats, small_blind, big_blind, rng):
        self.seats = seats
        self.sb = small_blind
        self.bb = big_blind
        self.rng = rng
        self.board = []
        self.street = "preflop"
        self.history = []  # (pid, street, action, amount)

    # ------------------------------------------------------------------ util

    def alive(self):
        return [s for s in self.seats if s.stack > 0 or s.in_hand]

    def in_hand_seats(self):
        return [s for s in self.seats if s.in_hand]

    def pot_total(self):
        return sum(s.total_commit for s in self.seats)

    def record(self, seat, action, amount):
        event = (seat.pid, self.street, action, amount)
        self.history.append(event)
        for s in self.seats:
            s.strategy.observe(event)

    # ------------------------------------------------------------------ hand

    def play_hand(self, button_idx):
        players = [s for s in self.seats if s.stack > 0]
        if len(players) < 2:
            return

        self.board = []
        self.history = []
        self.street = "preflop"
        for s in self.seats:
            s.hole = []
            s.in_hand = False
            s.total_commit = 0
            s.street_commit = 0

        # rotation of live players starting left of the button
        n = len(self.seats)
        order = []
        for k in range(1, n + 1):
            s = self.seats[(button_idx + k) % n]
            if s.stack > 0:
                order.append(s)
        # heads-up: button posts the small blind and acts first preflop
        if len(order) == 2:
            order = [order[1], order[0]]
        sb_seat, bb_seat = order[0], order[1]

        deck = list(range(52))
        self.rng.shuffle(deck)
        self.deck = deck
        for s in order:
            s.in_hand = True
            s.hole = [deck.pop(), deck.pop()]
            s.strategy.new_hand(s.pid, [p.pid for p in order])

        self.record(sb_seat, "small_blind", sb_seat.pay(self.sb))
        self.record(bb_seat, "big_blind", bb_seat.pay(self.bb))

        # preflop: first to act is left of the big blind
        preflop_order = order[2:] + order[:2]
        self.betting_round(preflop_order, current_bet=self.bb)

        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(self.in_hand_seats()) < 2:
                break
            self.street = street
            self.board += [deck.pop() for _ in range(n_cards)]
            for s in self.seats:
                s.street_commit = 0
            live_order = [s for s in order if s.in_hand]
            self.betting_round(live_order, current_bet=0)

        self.settle(order)

    # --------------------------------------------------------------- betting

    def betting_round(self, order, current_bet):
        contenders = self.in_hand_seats()
        if len(contenders) < 2:
            return
        if sum(1 for s in contenders if not s.all_in) < 2 and all(
            s.street_commit == current_bet or s.all_in for s in contenders
        ):
            return  # everyone effectively all-in, just run the board out

        min_raise = self.bb
        queue = deque(s for s in order if s.in_hand and s.stack > 0)
        while queue:
            seat = queue.popleft()
            if not seat.in_hand or seat.stack == 0:
                continue
            if len(self.in_hand_seats()) < 2:
                break

            to_call = current_bet - seat.street_commit
            view = self.make_view(seat, current_bet, min_raise, to_call)
            action, amount = seat.strategy.act(view)

            if action == "fold":
                if to_call == 0:
                    self.record(seat, "check", 0)
                    continue
                seat.in_hand = False
                self.record(seat, "fold", 0)
            elif action in ("check", "call"):
                if to_call == 0:
                    self.record(seat, "check", 0)
                else:
                    paid = seat.pay(to_call)
                    self.record(seat, "call", paid)
            elif action == "raise":
                # `amount` is raise-to (total street commitment target)
                max_to = seat.street_commit + seat.stack
                min_to = current_bet + min_raise
                raise_to = min(max(amount, min_to), max_to)
                if raise_to <= current_bet:  # not enough chips to raise
                    paid = seat.pay(to_call)
                    self.record(seat, "call", paid)
                else:
                    seat.pay(raise_to - seat.street_commit)
                    min_raise = max(min_raise, raise_to - current_bet)
                    current_bet = raise_to
                    label = "all_in_raise" if seat.stack == 0 else "raise"
                    self.record(seat, label, raise_to)
                    # everyone else gets to act again
                    idx = order.index(seat)
                    rotated = order[idx + 1:] + order[:idx]
                    queue = deque(
                        s for s in rotated
                        if s.in_hand and s.stack > 0
                    )
            else:  # unknown action: safest is check/fold
                if to_call == 0:
                    self.record(seat, "check", 0)
                else:
                    seat.in_hand = False
                    self.record(seat, "fold", 0)

    def make_view(self, seat, current_bet, min_raise, to_call):
        return GameView(
            pid=seat.pid,
            hole=list(seat.hole),
            board=list(self.board),
            street=self.street,
            pot=self.pot_total(),
            to_call=min(to_call, seat.stack),
            current_bet=current_bet,
            min_raise_to=current_bet + min_raise,
            my_stack=seat.stack,
            my_street_commit=seat.street_commit,
            my_total_commit=seat.total_commit,
            big_blind=self.bb,
            n_in_hand=len(self.in_hand_seats()),
            n_alive=len([s for s in self.seats if s.stack > 0 or s.in_hand]),
            opponents=[
                {
                    "pid": s.pid,
                    "stack": s.stack,
                    "in_hand": s.in_hand,
                    "all_in": s.all_in,
                    "street_commit": s.street_commit,
                }
                for s in self.seats
                if s is not seat and (s.stack > 0 or s.in_hand)
            ],
            history=list(self.history),
        )

    # -------------------------------------------------------------- showdown

    def settle(self, order):
        contenders = self.in_hand_seats()

        # refund any uncalled portion of the biggest bet
        commits = sorted((s.total_commit for s in self.seats), reverse=True)
        if len(commits) >= 2 and commits[0] > commits[1]:
            top = max(self.seats, key=lambda s: s.total_commit)
            refund = commits[0] - commits[1]
            top.stack += refund
            top.total_commit -= refund

        if len(contenders) == 1:
            contenders[0].stack += self.pot_total()
            return

        while len(self.board) < 5:  # run out the board for all-in showdowns
            self.board.append(self.deck.pop())

        scores = {s.pid: best7(s.hole + self.board) for s in contenders}

        levels = sorted({s.total_commit for s in contenders})
        prev = 0
        for level in levels:
            slice_amt = sum(
                min(s.total_commit, level) - min(s.total_commit, prev)
                for s in self.seats
            )
            prev = level
            if slice_amt == 0:
                continue
            eligible = [s for s in contenders if s.total_commit >= level]
            best = max(scores[s.pid] for s in eligible)
            winners = [s for s in eligible if scores[s.pid] == best]
            share, rem = divmod(slice_amt, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < rem else 0)


def play_tournament(strategy_factories, starting_stack, rng,
                    sb=50, bb=100, blind_level_hands=20, max_hands=3000):
    """Play one full tournament; returns (winner_pid, elimination_order).

    elimination_order lists pids from first bust to champion (last entry).
    """
    seats = [Seat(pid, factory(pid, rng), starting_stack)
             for pid, factory in strategy_factories]
    table = Table(seats, sb, bb, rng)
    busted = []
    button = rng.randrange(len(seats))
    hands = 0
    while sum(1 for s in seats if s.stack > 0) > 1 and hands < max_hands:
        if hands and hands % blind_level_hands == 0:
            table.sb = int(table.sb * 1.5)
            table.bb = int(table.bb * 1.5)
        table.play_hand(button)
        hands += 1
        busted.extend(s.pid for s in seats
                      if s.stack == 0 and s.pid not in busted)
        # move the button to the next live seat
        n = len(seats)
        for k in range(1, n + 1):
            if seats[(button + k) % n].stack > 0:
                button = (button + k) % n
                break

    survivors = sorted((s for s in seats if s.stack > 0),
                       key=lambda s: s.stack)
    winner = survivors[-1].pid
    busted.extend(s.pid for s in survivors[:-1] if s.pid not in busted)
    busted.append(winner)
    return winner, busted, hands
