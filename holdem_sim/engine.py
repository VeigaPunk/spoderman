"""No-limit Texas Hold'em tournament engine: blinds, betting, side pots, eliminations.

Information hygiene: strategies only ever receive
  * a `view` dict of public table state plus their own hole cards, and
  * `observe(event)` calls describing public actions and showdowns.
Nobody is told what anybody else's strategy is — they can only infer it
from behaviour at the table, exactly like a real game.
"""

import random
from collections import deque

from .cards import new_deck, evaluate_best

STREETS = [("flop", 3), ("turn", 1), ("river", 1)]


class Seat:
    def __init__(self, name, strategy, stack):
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = []
        self.folded = True
        self.all_in = False
        self.street_bet = 0   # chips put in on the current street
        self.total_bet = 0    # chips put in over the whole hand


class Tournament:
    def __init__(self, entries, chips=1000, base_sb=10, double_every=15,
                 seed=0, max_hands=3000, verbose=False):
        """entries: list of (name, strategy) in seat order."""
        self.seats = [Seat(name, strat, chips) for name, strat in entries]
        self.chips_total = chips * len(entries)
        self.base_sb = base_sb
        self.double_every = double_every
        self.rng = random.Random(seed)
        self.max_hands = max_hands
        self.verbose = verbose
        self.button = -1
        self.hand_no = 0
        self.placements = {}          # name -> finishing place (1 = champion)
        for i, seat in enumerate(self.seats):
            try:
                seat.strategy.reset(random.Random(seed * 7919 + i))
            except Exception:
                pass

    # ------------------------------------------------------------------ utils

    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def emit(self, event):
        if self.verbose:
            print("   ", event)
        for seat in self.seats:
            try:
                seat.strategy.observe(dict(event))
            except Exception:
                pass  # a strategy crashing on gossip is its own problem

    def not_folded(self):
        return [s for s in self.seats if not s.folded]

    # ------------------------------------------------------------ tournament

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.max_hands:
            self.play_hand()
        survivors = self.alive()
        champion = max(survivors, key=lambda s: s.stack)
        for s in survivors:  # max_hands failsafe: rank leftovers by stack
            if s is not champion and s.name not in self.placements:
                self.placements[s.name] = 2
        self.placements[champion.name] = 1
        return {
            "champion": champion.name,
            "placements": dict(self.placements),
            "hands": self.hand_no,
        }

    # ------------------------------------------------------------------ hand

    def play_hand(self):
        self.hand_no += 1
        level = (self.hand_no - 1) // self.double_every
        sb_amt = self.base_sb * (2 ** level)
        bb_amt = sb_amt * 2

        # ring: alive players in seat order starting from the (rotated) button
        n_seats = len(self.seats)
        for step in range(1, n_seats + 1):
            idx = (self.button + step) % n_seats
            if self.seats[idx].stack > 0:
                self.button = idx
                break
        ring = []
        for step in range(n_seats):
            seat = self.seats[(self.button + step) % n_seats]
            if seat.stack > 0:
                ring.append(seat)

        start_stacks = {s.name: s.stack for s in ring}

        for s in self.seats:
            s.hole, s.folded, s.all_in = [], True, False
            s.street_bet, s.total_bet = 0, 0
        for s in ring:
            s.folded = False

        deck = new_deck()
        self.rng.shuffle(deck)
        for s in ring:
            s.hole = [deck.pop(), deck.pop()]

        if len(ring) == 2:          # heads-up: button posts the small blind
            sb_seat, bb_seat = ring[0], ring[1]
        else:
            sb_seat, bb_seat = ring[1], ring[2]
        self._post(sb_seat, sb_amt)
        self._post(bb_seat, bb_amt)
        self.emit({"type": "blinds", "hand": self.hand_no, "sb": sb_amt, "bb": bb_amt,
                   "sb_player": sb_seat.name, "bb_player": bb_seat.name})

        bb_idx = ring.index(bb_seat)
        preflop_order = ring[bb_idx + 1:] + ring[:bb_idx + 1]
        postflop_order = ring[1:] + ring[:1]
        self._positions = {s.name: (i / max(1, len(postflop_order) - 1))
                           for i, s in enumerate(postflop_order)}

        board = []
        self._betting_round(preflop_order, "preflop", board,
                            current_bet=bb_amt, last_raise=bb_amt, bb_amt=bb_amt)

        for street, n_cards in STREETS:
            if len(self.not_folded()) <= 1:
                break
            board += [deck.pop() for _ in range(n_cards)]
            for s in self.seats:
                s.street_bet = 0
            can_act = [s for s in self.not_folded() if not s.all_in]
            if len(can_act) >= 2:
                self._betting_round(postflop_order, street, board,
                                    current_bet=0, last_raise=bb_amt, bb_amt=bb_amt)
            else:
                self.emit({"type": "runout", "hand": self.hand_no,
                           "street": street, "board_size": len(board)})

        self._showdown(board, ring)

        assert sum(s.stack for s in self.seats) == self.chips_total, "chips leaked!"

        busted = [s for s in ring if s.stack == 0]
        if busted:
            busted.sort(key=lambda s: start_stacks[s.name])  # shortest stack busts lowest
            remaining = len(self.alive()) + len(busted)
            for i, s in enumerate(busted):
                self.placements[s.name] = remaining - i
                self.emit({"type": "elimination", "hand": self.hand_no,
                           "player": s.name, "place": remaining - i})

    def _post(self, seat, amount):
        pay = min(amount, seat.stack)
        seat.stack -= pay
        seat.street_bet += pay
        seat.total_bet += pay
        if seat.stack == 0:
            seat.all_in = True

    def pot(self):
        return sum(s.total_bet for s in self.seats)

    # --------------------------------------------------------------- betting

    def _betting_round(self, order, street, board, current_bet, last_raise, bb_amt):
        pending = deque(s for s in order if not s.folded and not s.all_in)
        while pending:
            if len(self.not_folded()) <= 1:
                return
            seat = pending.popleft()
            if seat.folded or seat.all_in:
                continue
            to_call = current_bet - seat.street_bet
            view = self._make_view(seat, street, board, current_bet, last_raise,
                                   to_call, bb_amt)
            action = self._safe_act(seat, view)

            if action[0] == "fold" and to_call > 0:
                seat.folded = True
                self.emit(self._ev(seat, street, board, "fold", 0, current_bet))
                continue

            raise_to = None
            if action[0] == "raise":
                max_to = seat.street_bet + seat.stack
                raise_to = min(int(action[1]), max_to)
                if raise_to <= current_bet:
                    raise_to = None  # can't beat the bet: it's a call (maybe all-in)
                else:
                    min_to = current_bet + last_raise
                    if raise_to < min_to and raise_to < max_to:
                        raise_to = min(min_to, max_to)

            if raise_to is None:  # check / call
                pay = min(max(0, to_call), seat.stack)
                seat.stack -= pay
                seat.street_bet += pay
                seat.total_bet += pay
                if seat.stack == 0:
                    seat.all_in = True
                what = "check" if pay == 0 else ("allin_call" if seat.all_in else "call")
                self.emit(self._ev(seat, street, board, what, pay, current_bet))
                continue

            pay = raise_to - seat.street_bet
            seat.stack -= pay
            seat.street_bet = raise_to
            seat.total_bet += pay
            if seat.stack == 0:
                seat.all_in = True
            last_raise = max(last_raise, raise_to - current_bet)
            current_bet = raise_to
            what = "allin_raise" if seat.all_in else "raise"
            self.emit(self._ev(seat, street, board, what, pay, current_bet))
            i = order.index(seat)
            rot = order[i + 1:] + order[:i]
            pending = deque(q for q in rot if not q.folded and not q.all_in)

    def _ev(self, seat, street, board, what, pay, current_bet):
        return {"type": "action", "hand": self.hand_no, "street": street,
                "player": seat.name, "action": what, "paid": pay,
                "bet_level": current_bet, "pot": self.pot(),
                "board_size": len(board)}

    def _make_view(self, seat, street, board, current_bet, last_raise, to_call, bb_amt):
        return {
            "my_name": seat.name,
            "hole": list(seat.hole),
            "board": list(board),
            "street": street,
            "pot": self.pot(),
            "to_call": max(0, to_call),
            "current_bet": current_bet,
            "my_street_bet": seat.street_bet,
            "my_stack": seat.stack,
            "min_raise_to": current_bet + last_raise,
            "big_blind": bb_amt,
            "num_in_hand": len(self.not_folded()),
            "opp_stacks": {s.name: s.stack for s in self.alive() if s is not seat},
            "position": self._positions.get(seat.name, 0.5),
            "hand_no": self.hand_no,
        }

    def _safe_act(self, seat, view):
        to_call = view["to_call"]
        try:
            action = seat.strategy.act(view)
            if not isinstance(action, tuple) or action[0] not in ("fold", "call", "raise"):
                raise ValueError(action)
            if action[0] == "raise":
                int(action[1])
            return action
        except Exception:
            return ("call",) if to_call == 0 else ("fold",)

    # -------------------------------------------------------------- showdown

    def _showdown(self, board, ring):
        contenders = self.not_folded()
        if len(contenders) == 1:
            winner = contenders[0]
            winner.stack += self.pot()
            for s in self.seats:
                s.total_bet = 0
            self.emit({"type": "hand_end", "hand": self.hand_no,
                       "winners": [winner.name], "showdown": False})
            return

        scores = {s.name: evaluate_best(s.hole + board) for s in contenders}
        for s in contenders:
            self.emit({"type": "showdown", "hand": self.hand_no, "player": s.name,
                       "hole": list(s.hole), "score": scores[s.name]})

        # ----- side pots
        contribs = {s: s.total_bet for s in self.seats if s.total_bet > 0}
        pots = []
        while True:
            positive = [s for s, c in contribs.items() if c > 0]
            if not positive:
                break
            m = min(contribs[s] for s in positive)
            amount = 0
            for s in positive:
                contribs[s] -= m
                amount += m
            eligible = [s for s in positive if not s.folded]
            if eligible:
                pots.append((amount, eligible))
            elif pots:
                pots[-1] = (pots[-1][0] + amount, pots[-1][1])
            else:  # everyone at this level folded (can't happen with >1 contender)
                pots.append((amount, contenders))

        winners_overall = set()
        for amount, eligible in pots:
            best = max(scores[s.name] for s in eligible)
            winners = [s for s in eligible if scores[s.name] == best]
            winners.sort(key=lambda s: ring.index(s))
            share, rem = divmod(amount, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < rem else 0)
                winners_overall.add(w.name)
        for s in self.seats:
            s.total_bet = 0
        self.emit({"type": "hand_end", "hand": self.hand_no,
                   "winners": sorted(winners_overall), "showdown": True})
