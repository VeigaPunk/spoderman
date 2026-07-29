"""No-limit Texas Hold'em engine: a full freezeout tournament.

Implements the parts that actually change strategy quality:

* blinds, antes and a rising level structure
* correct heads-up blind posting and action order
* min-raise tracking, and the rule that a short all-in raise does *not*
  reopen the betting for players who already acted
* layered side pots with odd chips going to the first seat left of the button
* uncalled bets returned to the bettor

Strategies see :class:`Obs`, which contains public table information plus
their own hole cards.  It never contains another player's cards or any hint
of which strategy occupies which seat.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .cards import eval7

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
STREET_NAMES = ("preflop", "flop", "turn", "river")

FOLD, CHECK, CALL, RAISE = "fold", "check", "call", "raise"

# (small blind, big blind, ante-per-player)
DEFAULT_LEVELS = [
    (50, 100, 0),
    (75, 150, 0),
    (100, 200, 25),
    (150, 300, 25),
    (200, 400, 50),
    (300, 600, 75),
    (400, 800, 100),
    (600, 1200, 150),
    (800, 1600, 200),
    (1200, 2400, 300),
    (1600, 3200, 400),
    (2400, 4800, 600),
    (4000, 8000, 1000),
    (6000, 12000, 1500),
    (10000, 20000, 2500),
    (15000, 30000, 4000),
]


@dataclass
class ActionRecord:
    seat: int
    street: int
    kind: str
    amount: int        # chips put in by this action
    to_amount: int     # the player's total street bet afterwards
    to_call: int       # what it cost to continue, before acting
    pot: int           # pot size before the action
    allin: bool = False


@dataclass
class Obs:
    """Everything a strategy is allowed to know when it acts."""

    seat: int
    hole: tuple
    board: tuple
    street: int
    pot: int                    # includes all chips committed this hand
    to_call: int
    min_raise_to: int
    max_raise_to: int
    can_raise: bool
    stacks: list                # chips behind, by seat
    street_bets: list           # chips in front, this street, by seat
    committed: list             # chips in, this hand, by seat
    in_hand: list               # dealt in and not folded
    all_in: list
    dealt: list                 # was dealt cards this hand
    button: int
    sb: int
    bb: int
    ante: int
    level: int
    hand_no: int
    history: list               # ActionRecords for this hand, all streets
    n_players_left: int         # players still alive in the tournament
    start_stacks: list          # stacks at the start of this hand

    @property
    def my_stack(self) -> int:
        return self.stacks[self.seat]

    @property
    def my_bet(self) -> int:
        return self.street_bets[self.seat]

    @property
    def opponents(self) -> list:
        return [s for s in range(len(self.stacks)) if s != self.seat and self.in_hand[s]]

    @property
    def n_opponents(self) -> int:
        return len(self.opponents)

    @property
    def n_opponents_live(self) -> int:
        """Opponents who can still put chips in."""
        return sum(
            1 for s in self.opponents if not self.all_in[s]
        )

    def pot_odds(self) -> float:
        return self.to_call / (self.pot + self.to_call) if self.to_call > 0 else 0.0

    def street_actions(self, street=None) -> list:
        street = self.street if street is None else street
        return [a for a in self.history if a.street == street]

    def relative_position(self) -> float:
        """0.0 = first to act on later streets, 1.0 = last (the button)."""
        live = [s for s in range(len(self.stacks)) if self.in_hand[s]]
        if len(live) <= 1:
            return 1.0
        order = [(s - self.button - 1) % len(self.stacks) for s in live]
        mine = (self.seat - self.button - 1) % len(self.stacks)
        return sorted(order).index(mine) / (len(live) - 1)

    def is_aggressor(self) -> Optional[int]:
        """Seat of the last player to bet or raise this hand, if any."""
        for a in reversed(self.history):
            if a.kind == RAISE:
                return a.seat
        return None

    def effective_stack(self) -> int:
        """Smallest stack among hero and the opponents still able to bet."""
        mine = self.stacks[self.seat] + self.street_bets[self.seat]
        others = [
            self.stacks[s] + self.street_bets[s]
            for s in self.opponents
        ]
        return min([mine] + others) if others else mine


@dataclass
class PlayerState:
    seat: int
    stack: int
    hole: tuple = ()
    dealt: bool = False
    folded: bool = False
    all_in: bool = False
    street_bet: int = 0
    committed: int = 0

    @property
    def contesting(self) -> bool:
        return self.dealt and not self.folded


@dataclass
class HandResult:
    hand_no: int
    board: tuple
    net: dict = field(default_factory=dict)
    shown: dict = field(default_factory=dict)
    pot: int = 0


class Table:
    """One hand of no-limit hold'em."""

    def __init__(self, stacks, strategies, button, sb, bb, ante, rng,
                 hand_no=0, level=0, n_players_left=0, log=None):
        self.n = len(stacks)
        self.players = [PlayerState(i, stacks[i]) for i in range(self.n)]
        self.start_stacks = list(stacks)
        self.strategies = strategies
        self.button = button
        self.sb, self.bb, self.ante = sb, bb, ante
        self.rng = rng
        self.hand_no = hand_no
        self.level = level
        self.n_players_left = n_players_left or sum(1 for s in stacks if s > 0)
        self.board = []
        self.history = []
        self.pot_dead = 0          # antes and blinds already collected
        self.current_bet = 0
        self.min_raise = bb
        self.street = PREFLOP
        self.log = log

    # -- helpers ---------------------------------------------------------

    def _seats_from(self, start):
        return [(start + i) % self.n for i in range(self.n)]

    def _live(self):
        return [p for p in self.players if p.contesting]

    def _pot(self):
        return sum(p.committed for p in self.players)

    def _emit(self, event):
        for s in self.strategies:
            if s is not None:
                s.observe(event)

    def _post(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_bet += amount
        p.committed += amount
        if p.stack == 0:
            p.all_in = True
        return amount

    # -- setup -----------------------------------------------------------

    def deal(self):
        deck = list(range(52))
        self.rng.shuffle(deck)
        self.deck = deck
        self.deck_i = 0
        for p in self.players:
            if p.stack > 0:
                p.hole = (deck[self.deck_i], deck[self.deck_i + 1])
                self.deck_i += 2
                p.dealt = True

    def _draw(self, k):
        cards = self.deck[self.deck_i: self.deck_i + k]
        self.deck_i += k
        return cards

    def post_blinds(self):
        dealt = [p for p in self.players if p.dealt]
        if self.ante:
            for p in dealt:
                self._post(p, self.ante)
            # antes are dead money: pull them out of the street bets
            for p in dealt:
                p.street_bet = 0

        order = [s for s in self._seats_from(self.button + 1)
                 if self.players[s].dealt]
        if len(order) == 2:
            # heads up: the button posts the small blind and acts first preflop
            sb_seat, bb_seat = order[1], order[0]
        else:
            sb_seat, bb_seat = order[0], order[1]
        self._post(self.players[sb_seat], self.sb)
        self._post(self.players[bb_seat], self.bb)
        self.current_bet = max(self.players[sb_seat].street_bet,
                               self.players[bb_seat].street_bet)
        self.min_raise = self.bb
        self.bb_seat = bb_seat
        self.sb_seat = sb_seat
        if len(order) == 2:
            self.first_to_act_pre = sb_seat
        else:
            after_bb = order.index(bb_seat)
            self.first_to_act_pre = order[(after_bb + 1) % len(order)]

    # -- observation -----------------------------------------------------

    def _obs(self, p, to_call, min_raise_to, can_raise):
        return Obs(
            seat=p.seat,
            hole=p.hole,
            board=tuple(self.board),
            street=self.street,
            pot=self._pot(),
            to_call=to_call,
            min_raise_to=min_raise_to,
            max_raise_to=p.street_bet + p.stack,
            can_raise=can_raise,
            stacks=[q.stack for q in self.players],
            street_bets=[q.street_bet for q in self.players],
            committed=[q.committed for q in self.players],
            in_hand=[q.contesting for q in self.players],
            all_in=[q.all_in for q in self.players],
            dealt=[q.dealt for q in self.players],
            button=self.button,
            sb=self.sb,
            bb=self.bb,
            ante=self.ante,
            level=self.level,
            hand_no=self.hand_no,
            history=list(self.history),
            n_players_left=self.n_players_left,
            start_stacks=list(self.start_stacks),
        )

    # -- betting ---------------------------------------------------------

    def betting_round(self, first_seat):
        acted = set()
        no_raise = set()      # players capped to call-only by a short all-in
        idx = first_seat
        guard = 0

        while True:
            guard += 1
            if guard > 400:  # pragma: no cover - structural safety net
                break
            live = self._live()
            if len(live) <= 1:
                return
            actors = [p for p in live if not p.all_in]
            if not actors:
                return
            if len(actors) == 1 and actors[0].seat in acted \
                    and actors[0].street_bet >= self.current_bet:
                return

            p = self.players[idx]
            if not p.contesting or p.all_in:
                idx = (idx + 1) % self.n
                continue
            if p.seat in acted and p.street_bet == self.current_bet:
                return  # action is closed

            to_call = min(self.current_bet - p.street_bet, p.stack)
            max_to = p.street_bet + p.stack
            min_raise_to = min(self.current_bet + self.min_raise, max_to)
            can_raise = (
                p.seat not in no_raise
                and max_to > self.current_bet
                and len([q for q in live if not q.all_in or q is p]) > 1
            )

            obs = self._obs(p, to_call, min_raise_to, can_raise)
            kind, amount = self.strategies[p.seat].act(obs)
            kind, amount = self._sanitize(kind, amount, p, to_call,
                                          min_raise_to, max_to, can_raise)

            pot_before = self._pot()
            if kind == FOLD:
                p.folded = True
                rec = ActionRecord(p.seat, self.street, FOLD, 0, p.street_bet,
                                   to_call, pot_before)
            elif kind == CHECK:
                rec = ActionRecord(p.seat, self.street, CHECK, 0, p.street_bet,
                                   0, pot_before)
            elif kind == CALL:
                put = self._post(p, to_call)
                rec = ActionRecord(p.seat, self.street, CALL, put, p.street_bet,
                                   to_call, pot_before, p.all_in)
            else:  # RAISE
                put = self._post(p, amount - p.street_bet)
                increment = p.street_bet - self.current_bet
                full = increment >= self.min_raise
                if full:
                    self.min_raise = increment
                    acted = set()
                    no_raise = set()
                else:
                    # short all-in: everyone who already acted may only call
                    no_raise |= acted
                self.current_bet = max(self.current_bet, p.street_bet)
                rec = ActionRecord(p.seat, self.street, RAISE, put, p.street_bet,
                                   to_call, pot_before, p.all_in)

            self.history.append(rec)
            acted.add(p.seat)
            if self.log is not None:
                self.log.append(rec)
            self._emit({"type": "action", "record": rec, "board": tuple(self.board),
                        "street": self.street, "n_live": len(self._live())})
            idx = (idx + 1) % self.n

    def _sanitize(self, kind, amount, p, to_call, min_raise_to, max_to, can_raise):
        """Clamp whatever a strategy returned onto the set of legal actions."""
        kind = (kind or "").lower()
        if kind in ("allin", "all-in", "all_in", "shove", "jam"):
            kind, amount = RAISE, max_to
        if kind == "bet":
            kind = RAISE
        if kind not in (FOLD, CHECK, CALL, RAISE):
            kind = CHECK if to_call == 0 else FOLD
        if kind == FOLD and to_call == 0:
            kind = CHECK                      # never fold a free option
        if kind == CHECK and to_call > 0:
            kind = FOLD
        if kind == CALL and to_call == 0:
            kind = CHECK
        if kind == RAISE:
            amount = int(amount)
            if not can_raise or max_to <= self.current_bet:
                kind = CALL if to_call > 0 else CHECK
            else:
                amount = max(amount, min_raise_to)
                amount = min(amount, max_to)
                if amount <= p.street_bet + to_call:
                    kind = CALL if to_call > 0 else CHECK
        return kind, amount

    # -- run one hand ----------------------------------------------------

    def play(self) -> HandResult:
        self.deal()
        self.post_blinds()
        self._emit({"type": "hand_start", "button": self.button,
                    "stacks": list(self.start_stacks), "bb": self.bb,
                    "ante": self.ante, "hand_no": self.hand_no,
                    "dealt": [p.dealt for p in self.players]})

        self.betting_round(self.first_to_act_pre)

        for street, n_cards in ((FLOP, 3), (TURN, 1), (RIVER, 1)):
            if len(self._live()) <= 1:
                break
            self.street = street
            self.board.extend(self._draw(n_cards))
            for p in self.players:
                p.street_bet = 0
            self.current_bet = 0
            self.min_raise = self.bb
            self._emit({"type": "street", "street": street,
                        "board": tuple(self.board)})
            if sum(1 for p in self._live() if not p.all_in) >= 2:
                first = next((s for s in self._seats_from(self.button + 1)
                              if self.players[s].contesting), self.button)
                self.betting_round(first)

        return self.showdown()

    # -- pots ------------------------------------------------------------

    def showdown(self) -> HandResult:
        contenders = self._live()
        result = HandResult(self.hand_no, tuple(self.board), pot=self._pot())

        if len(contenders) > 1:
            while len(self.board) < 5:
                self.board.extend(self._draw(1))
            result.board = tuple(self.board)
            scores = {p.seat: eval7(list(p.hole) + self.board) for p in contenders}
            result.shown = {p.seat: p.hole for p in contenders}
        else:
            scores = {contenders[0].seat: 1} if contenders else {}

        payouts = [0] * self.n
        levels = sorted({p.committed for p in self.players if p.committed > 0})
        prev = 0
        for lvl in levels:
            pot = sum(min(p.committed, lvl) - min(p.committed, prev)
                      for p in self.players)
            if pot <= 0:
                prev = lvl
                continue
            eligible = [p for p in contenders if p.committed >= lvl]
            if not eligible:
                # nobody left can win these chips: return them to contributors
                back = [p for p in self.players if p.committed >= lvl]
                for p in back:
                    payouts[p.seat] += (lvl - prev)
                prev = lvl
                continue
            best = max(scores[p.seat] for p in eligible)
            winners = [p for p in eligible if scores[p.seat] == best]
            share, odd = divmod(pot, len(winners))
            for p in winners:
                payouts[p.seat] += share
            if odd:
                order = [s for s in self._seats_from(self.button + 1)
                         if s in {w.seat for w in winners}]
                for i in range(odd):
                    payouts[order[i % len(order)]] += 1
            prev = lvl

        for p in self.players:
            p.stack += payouts[p.seat]
            result.net[p.seat] = p.stack - self.start_stacks[p.seat]

        self._emit({"type": "hand_end", "board": tuple(self.board),
                    "shown": dict(result.shown), "net": dict(result.net),
                    "stacks": [p.stack for p in self.players],
                    "pot": result.pot})
        return result

    def final_stacks(self):
        return [p.stack for p in self.players]


@dataclass
class TournamentResult:
    winner: int
    finish_order: list       # seats, best (winner) first
    hands: int
    knockouts: dict          # seat -> players it eliminated
    peak_stack: dict
    hands_survived: dict
    busted_by_hand: dict


def play_tournament(strategy_factories, seed=0, start_stack=10000,
                    levels=None, hands_per_level=20, max_hands=4000):
    """Run one freezeout to a single survivor.  Returns a TournamentResult."""
    levels = levels or DEFAULT_LEVELS
    rng = random.Random(seed)
    n = len(strategy_factories)
    strategies = [f(seat, n, random.Random(seed * 1000 + seat + 1))
                  for seat, f in enumerate(strategy_factories)]
    stacks = [start_stack] * n
    alive = [True] * n
    button = rng.randrange(n)
    finish = []                     # busted seats, first out first
    knockouts = {i: 0 for i in range(n)}
    peak = {i: start_stack for i in range(n)}
    survived = {i: 0 for i in range(n)}

    hand_no = 0
    while sum(alive) > 1 and hand_no < max_hands:
        hand_no += 1
        level = min(hand_no // hands_per_level, len(levels) - 1)
        sb, bb, ante = levels[level]
        seats_alive = [i for i in range(n) if alive[i]]
        for i in seats_alive:
            survived[i] = hand_no
        if not alive[button]:
            button = next(s for s in ((button + k) % n for k in range(1, n + 1))
                          if alive[s])

        table = Table([stacks[i] if alive[i] else 0 for i in range(n)],
                      strategies, button, sb, bb, ante, rng,
                      hand_no=hand_no, level=level, n_players_left=len(seats_alive))
        table.play()
        new_stacks = table.final_stacks()

        busted = [i for i in seats_alive if new_stacks[i] <= 0]
        if busted:
            # credit the knockout to whoever gained the most in the hand
            gainers = sorted(seats_alive, key=lambda s: new_stacks[s] - stacks[s],
                             reverse=True)
            killer = gainers[0] if new_stacks[gainers[0]] > stacks[gainers[0]] else None
            # same-hand bustouts are ranked by the stack they started with
            for s in sorted(busted, key=lambda s: stacks[s]):
                finish.append(s)
                alive[s] = False
                if killer is not None and killer != s:
                    knockouts[killer] += 1

        for i in range(n):
            stacks[i] = max(0, new_stacks[i])
            peak[i] = max(peak[i], stacks[i])

        button = next(s for s in ((button + k) % n for k in range(1, n + 1))
                      if alive[s] or sum(alive) == 0)

    if sum(alive) == 1:
        winner = alive.index(True)
    else:  # hand cap hit: the chip leader takes it
        winner = max(range(n), key=lambda i: (alive[i], stacks[i]))
        for i in range(n):
            if alive[i] and i != winner:
                finish.append(i)

    order = [winner] + list(reversed([s for s in finish if s != winner]))
    return TournamentResult(
        winner=winner,
        finish_order=order,
        hands=hand_no,
        knockouts=knockouts,
        peak_stack=peak,
        hands_survived=survived,
        busted_by_hand={s: survived[s] for s in range(n)},
    )
