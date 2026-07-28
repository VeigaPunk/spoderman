"""No-limit Texas Hold'em engine: betting, side pots, tournaments.

Strategies only ever see public information (their own hole cards, the
board, stacks, bets, and the action history broadcast via observe()) —
nobody knows anybody else's algorithm.
"""

from collections import deque

from .cards import eval7

STAGES = ("preflop", "flop", "turn", "river")


class PlayerState:
    __slots__ = ("seat", "name", "strategy", "stack", "bet", "contrib",
                 "folded", "all_in", "hole", "out")

    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.out = False
        self.hole = ()
        self.bet = 0
        self.contrib = 0
        self.folded = False
        self.all_in = False

    def reset_for_hand(self):
        self.hole = ()
        self.bet = 0
        self.contrib = 0
        self.folded = False
        self.all_in = False


class Hand:
    def __init__(self, participants, order, sb, bb, rng, hand_no):
        self.participants = participants  # everyone dealt in, seat order kept
        self.order = order                # SB first, button last
        self.sb = sb
        self.bb = bb
        self.rng = rng
        self.hand_no = hand_no
        self.community = []
        self.current_bet = 0
        self.min_raise = bb

    # -- plumbing ---------------------------------------------------------
    def _pay(self, p, amount):
        amount = max(0, min(amount, p.stack))
        p.stack -= amount
        p.bet += amount
        p.contrib += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    def _pot(self):
        return sum(p.contrib for p in self.participants)

    def _unfolded(self):
        return [p for p in self.participants if not p.folded]

    def _broadcast(self, event):
        for p in self.participants:
            p.strategy.observe(event)

    def _view(self, p, stage, position, n_order):
        return {
            "hole": tuple(p.hole),
            "community": tuple(self.community),
            "stage": stage,
            "pot": self._pot(),
            "to_call": self.current_bet - p.bet,
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "my_bet": p.bet,
            "stack": p.stack,
            "seat": p.seat,
            "bb": self.bb,
            "position": position,
            "n_positions": n_order,
            "n_unfolded": len(self._unfolded()),
            "hand_no": self.hand_no,
            "opponents": [
                {"seat": q.seat, "stack": q.stack, "bet": q.bet,
                 "folded": q.folded, "all_in": q.all_in}
                for q in self.participants if q is not p
            ],
        }

    # -- betting ----------------------------------------------------------
    def _betting_round(self, acting_order, stage):
        queue = deque(p for p in acting_order
                      if not p.folded and not p.all_in)
        while queue:
            if len(self._unfolded()) <= 1:
                break
            p = queue.popleft()
            if p.folded or p.all_in:
                continue
            to_call = self.current_bet - p.bet
            pos = acting_order.index(p)
            view = self._view(p, stage, pos, len(acting_order))
            action = p.strategy.act(view)
            kind = action[0]

            if kind == "fold" and to_call == 0:
                kind = "check"
            if kind == "fold":
                p.folded = True
                self._broadcast({"type": "action", "seat": p.seat,
                                 "stage": stage, "action": "fold",
                                 "amount": 0, "all_in": False,
                                 "facing": to_call})
                continue
            if kind in ("check", "call"):
                paid = self._pay(p, to_call)
                self._broadcast({"type": "action", "seat": p.seat,
                                 "stage": stage,
                                 "action": "call" if paid else "check",
                                 "amount": paid, "all_in": p.all_in,
                                 "facing": to_call})
                continue

            # raise to a total for this street
            target = min(int(action[1]), p.bet + p.stack)
            if target <= self.current_bet:
                paid = self._pay(p, to_call)  # not actually a raise
                self._broadcast({"type": "action", "seat": p.seat,
                                 "stage": stage,
                                 "action": "call" if paid else "check",
                                 "amount": paid, "all_in": p.all_in,
                                 "facing": to_call})
                continue
            full = self.current_bet + self.min_raise
            if target < full and target < p.bet + p.stack:
                target = min(full, p.bet + p.stack)  # bump under-raises
            self._pay(p, target - p.bet)
            raise_by = p.bet - self.current_bet
            if raise_by >= self.min_raise:
                self.min_raise = raise_by
            self.current_bet = p.bet
            self._broadcast({"type": "action", "seat": p.seat,
                             "stage": stage, "action": "raise",
                             "amount": p.bet, "all_in": p.all_in,
                             "facing": to_call})
            # everyone else gets to respond, in position after the raiser
            i = acting_order.index(p)
            after = acting_order[i + 1:] + acting_order[:i]
            queue = deque(q for q in after
                          if not q.folded and not q.all_in)

        # refund any uncalled portion of the top bet
        unfolded = self._unfolded()
        if unfolded:
            top = max(p.bet for p in unfolded)
            leaders = [p for p in unfolded if p.bet == top]
            if len(leaders) == 1:
                second = max((p.bet for p in self.participants
                              if p is not leaders[0]), default=0)
                refund = top - second
                if refund > 0:
                    p = leaders[0]
                    p.stack += refund
                    p.bet -= refund
                    p.contrib -= refund
                    p.all_in = p.stack == 0

    def _reset_street(self):
        self.current_bet = 0
        self.min_raise = self.bb
        for p in self.participants:
            p.bet = 0

    # -- showdown ---------------------------------------------------------
    def _award(self):
        active = self._unfolded()
        pot_total = self._pot()
        if len(active) == 1:
            active[0].stack += pot_total
            self._broadcast({"type": "hand_end", "hand_no": self.hand_no,
                             "winners": [active[0].seat],
                             "showdown": False, "pot": pot_total})
            return

        scores = {p.seat: eval7(list(p.hole) + self.community)
                  for p in active}
        levels = sorted({p.contrib for p in active if p.contrib > 0})
        distributed = 0
        prev = 0
        order = self.order
        for lvl in levels:
            slice_amt = sum(min(p.contrib, lvl) - min(p.contrib, prev)
                            for p in self.participants)
            elig = [p for p in active if p.contrib >= lvl]
            best = max(scores[p.seat] for p in elig)
            winners = [p for p in order if p in elig
                       and scores[p.seat] == best]
            share = slice_amt // len(winners)
            rem = slice_amt - share * len(winners)
            for j, w in enumerate(winners):
                w.stack += share + (1 if j < rem else 0)
            distributed += slice_amt
            prev = lvl
        residual = pot_total - distributed
        if residual > 0:  # safety net; shouldn't happen
            best = max(scores[p.seat] for p in active)
            next(p for p in active
                 if scores[p.seat] == best).stack += residual
        self._broadcast({"type": "hand_end", "hand_no": self.hand_no,
                         "winners": [p.seat for p in active
                                     if scores[p.seat]
                                     == max(scores.values())],
                         "showdown": True, "pot": pot_total})

    # -- play -------------------------------------------------------------
    def play(self):
        for p in self.participants:
            p.reset_for_hand()
        deck = list(range(52))
        self.rng.shuffle(deck)
        for i, p in enumerate(self.order):
            p.hole = (deck[2 * i], deck[2 * i + 1])
        idx = 2 * len(self.order)

        sb_p, bb_p = self.order[0], self.order[1]
        self._pay(sb_p, self.sb)
        self._pay(bb_p, self.bb)
        self.current_bet = self.bb
        self.min_raise = self.bb

        n = len(self.order)
        preflop_order = self.order[2:] + self.order[:2]
        if n == 2:
            postflop_order = self.order[1:] + self.order[:1]
        else:
            postflop_order = self.order

        for stage in STAGES:
            if stage == "flop":
                self.community.extend(deck[idx:idx + 3])
                idx += 3
            elif stage in ("turn", "river"):
                self.community.append(deck[idx])
                idx += 1
            if stage != "preflop":
                self._reset_street()
            acting = preflop_order if stage == "preflop" else postflop_order
            can_act = [p for p in acting if not p.folded and not p.all_in]
            if len(can_act) >= 2 or any(p.bet < self.current_bet
                                        for p in can_act):
                self._betting_round(acting, stage)
            if len(self._unfolded()) == 1:
                break
        self._award()


def play_tournament(players, rng, sb0=5, bb0=10, level_every=15,
                    max_hands=2000, button_start=0):
    """Play until one player has all the chips.

    Returns (winner_seat, ranking, hands_played) where ranking is a list
    of seats from champion (index 0) to first bust (index -1).
    """
    busted_order = []  # first bust first
    button = button_start
    hand_no = 0
    while True:
        alive = [p for p in players if p.stack > 0]
        if len(alive) <= 1 or hand_no >= max_hands:
            break
        level = min(hand_no // level_every, 9)
        sb, bb = sb0 << level, bb0 << level

        # button sits on an alive player
        while players[button % len(players)].stack == 0:
            button += 1
        btn_p = players[button % len(players)]
        bi = alive.index(btn_p)
        if len(alive) == 2:
            order = alive[bi:] + alive[:bi]        # button posts SB heads-up
        else:
            order = alive[bi + 1:] + alive[:bi + 1]

        pre_stacks = {p.seat: p.stack for p in alive}
        Hand(alive, order, sb, bb, rng, hand_no).play()

        newly_busted = [p for p in alive if p.stack == 0 and not p.out]
        newly_busted.sort(key=lambda p: (pre_stacks[p.seat], p.seat))
        for p in newly_busted:
            p.out = True
            busted_order.append(p.seat)

        button += 1
        hand_no += 1

    survivors = sorted((p for p in players if p.stack > 0),
                       key=lambda p: p.stack)
    for p in survivors:
        busted_order.append(p.seat)  # richest survivor lands last = champion
    ranking = list(reversed(busted_order))
    return ranking[0], ranking, hand_no
