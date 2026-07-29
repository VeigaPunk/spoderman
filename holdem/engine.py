"""No-limit Texas Hold'em tournament engine.

Six-max table, escalating blinds, correct side pots, standard heads-up rules.
Strategies see only a public `view` and receive public events via `observe()`
— hole cards stay sealed until showdown.
"""

from __future__ import annotations

from types import SimpleNamespace

from poker import evaluate7

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
STREET_CARDS = {FLOP: 3, TURN: 1, RIVER: 1}


class Tournament:
    def __init__(self, strategies, rng, starting_stack=1000, sb=10, bb=20,
                 blind_double_every=20, max_hands=2000):
        self.strategies = strategies
        self.rng = rng
        self.seat_order = sorted(strategies)
        self.stacks = {p: starting_stack for p in self.seat_order}
        self.base_sb, self.base_bb = sb, bb
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.button = self.seat_order[rng.randrange(len(self.seat_order))]
        self.finish_order = []          # first bust first
        self.hand_no = 0

    # -- public API ---------------------------------------------------------
    def run(self):
        while len(self._alive()) > 1 and self.hand_no < self.max_hands:
            self.hand_no += 1
            self._play_hand()
        alive = sorted(self._alive(), key=lambda p: self.stacks[p])
        self.finish_order.extend(alive)          # chip-count order if capped
        champion = self.finish_order[-1]
        return SimpleNamespace(
            champion=champion,
            finish_order=list(self.finish_order),   # index 0 busted first
            hands_played=self.hand_no,
        )

    # -- internals ----------------------------------------------------------
    def _alive(self):
        return [p for p in self.seat_order if self.stacks[p] > 0]

    def _blinds(self):
        level = (self.hand_no - 1) // self.blind_double_every
        mult = 2 ** min(level, 10)
        return self.base_sb * mult, self.base_bb * mult

    def _broadcast(self, event):
        for s in self.strategies.values():
            s.observe(event)

    def _play_hand(self):
        alive = self._alive()
        n = len(alive)
        rng = self.rng
        sb_amt, bb_amt = self._blinds()

        if self.button not in alive:
            idx = self.seat_order.index(self.button)
            for step in range(1, len(self.seat_order) + 1):
                cand = self.seat_order[(idx + step) % len(self.seat_order)]
                if cand in alive:
                    self.button = cand
                    break
        bi = alive.index(self.button)

        if n == 2:
            sb_p, bb_p = alive[bi], alive[(bi + 1) % 2]
            preflop_order = [sb_p, bb_p]
            postflop_order = [bb_p, sb_p]
        else:
            sb_p = alive[(bi + 1) % n]
            bb_p = alive[(bi + 2) % n]
            preflop_order = [alive[(bi + 3 + i) % n] for i in range(n)]
            postflop_order = [alive[(bi + 1 + i) % n] for i in range(n)]

        deck = list(range(52))
        rng.shuffle(deck)
        holes = {}
        for p in alive:
            holes[p] = (deck.pop(), deck.pop())
        board_stock = [deck.pop() for _ in range(5)]

        contrib = {p: 0 for p in alive}          # whole-hand totals
        street_commit = {p: 0 for p in alive}
        folded, allin = set(), set()
        start_stacks = dict(self.stacks)

        for s in self.strategies.values():
            s.new_hand(self.hand_no)
        self._broadcast(("hand_start", self.hand_no, list(alive),
                         dict(self.stacks), self.button))

        def pay(p, amount):
            amount = min(amount, self.stacks[p])
            self.stacks[p] -= amount
            contrib[p] += amount
            street_commit[p] += amount
            if self.stacks[p] == 0:
                allin.add(p)
            return amount

        pay(sb_p, sb_amt)
        pay(bb_p, bb_amt)
        self._broadcast(("blinds", sb_p, bb_p, sb_amt, bb_amt))

        board = []
        current_bet = bb_amt
        min_raise = bb_amt

        def live_players():
            return [p for p in alive if p not in folded]

        def betting_round(order, street):
            nonlocal current_bet, min_raise
            actors = [p for p in order if p not in folded and p not in allin]
            if len(actors) == 0:
                return
            if len(actors) == 1 and street_commit[actors[0]] >= current_bet:
                return
            need_to_act = set(actors)
            pos, guard = 0, 0
            while need_to_act and len(live_players()) > 1:
                guard += 1
                if guard > 500:
                    break
                p = order[pos % len(order)]
                pos += 1
                if p not in need_to_act or p in folded or p in allin:
                    need_to_act.discard(p)
                    continue

                view = self._make_view(p, holes[p], board, street, contrib,
                                       street_commit, folded, alive,
                                       current_bet, min_raise, order,
                                       sb_amt, bb_amt)
                try:
                    action = self.strategies[p].act(view)
                except Exception:
                    action = ("fold",)

                kind = action[0]
                to_call = current_bet - street_commit[p]

                if kind == "fold" and to_call <= 0:
                    kind = "check"
                if kind == "check" and to_call > 0:
                    kind = "call"

                if kind == "fold":
                    folded.add(p)
                    self._broadcast(("action", p, street, "fold", 0, False))
                elif kind == "check":
                    self._broadcast(("action", p, street, "check", 0, False))
                elif kind == "call":
                    paid = pay(p, to_call)
                    self._broadcast(("action", p, street, "call", paid, p in allin))
                else:  # raise to a total street commitment
                    target = int(action[1])
                    max_total = street_commit[p] + self.stacks[p]
                    target = min(target, max_total)
                    if target <= current_bet:
                        paid = pay(p, to_call)   # can't raise: becomes a call
                        self._broadcast(("action", p, street, "call", paid, p in allin))
                        need_to_act.discard(p)
                        continue
                    full_min = current_bet + min_raise
                    if target < full_min and target < max_total:
                        target = min(full_min, max_total)
                    paid = pay(p, target - street_commit[p])
                    new_bet = street_commit[p]
                    if new_bet - current_bet >= min_raise:
                        min_raise = new_bet - current_bet
                    current_bet = new_bet
                    self._broadcast(("action", p, street, "raise", paid, p in allin))
                    need_to_act = {q for q in order
                                   if q not in folded and q not in allin and q != p
                                   and street_commit[q] < current_bet}
                need_to_act.discard(p)

        # ---- streets ----
        betting_round(preflop_order, PREFLOP)
        for street in (FLOP, TURN, RIVER):
            if len(live_players()) <= 1:
                break
            board.extend(board_stock[:STREET_CARDS[street]])
            board_stock[:STREET_CARDS[street]] = []
            self._broadcast(("board", street, list(board)))
            can_bet = [p for p in live_players() if p not in allin]
            if len(can_bet) > 1:
                current_bet = 0
                min_raise = bb_amt
                for p in alive:
                    street_commit[p] = 0
                betting_round(postflop_order, street)
        while len(live_players()) > 1 and len(board) < 5:
            board.append(board_stock.pop(0))     # run out the board for all-ins

        self._settle(alive, holes, board, contrib, folded, postflop_order)

        busted = [p for p in alive if self.stacks[p] == 0]
        busted.sort(key=lambda p: start_stacks[p])
        self.finish_order.extend(busted)
        self._broadcast(("hand_end", self.hand_no, dict(self.stacks)))

        idx = self.seat_order.index(self.button)
        for step in range(1, len(self.seat_order) + 1):
            cand = self.seat_order[(idx + step) % len(self.seat_order)]
            if self.stacks[cand] > 0:
                self.button = cand
                break

    def _make_view(self, p, hole, board, street, contrib, street_commit,
                   folded, alive, current_bet, min_raise, order, sb_amt, bb_amt):
        active = [q for q in alive if q not in folded]
        after = 0
        seen = False
        for q in order:
            if q == p:
                seen = True
            elif seen and q in active:
                after += 1
        return SimpleNamespace(
            pid=p,
            hole=tuple(hole),
            board=tuple(board),
            street=street,
            pot=sum(contrib.values()),
            to_call=max(0, current_bet - street_commit[p]),
            current_bet=current_bet,
            min_raise_to=current_bet + min_raise,
            my_stack=self.stacks[p],
            my_committed=street_commit[p],
            stacks={q: self.stacks[q] for q in alive},
            n_active=len(active),
            to_act_after=after,
            button=self.button,
            blinds=(sb_amt, bb_amt),
            hand_no=self.hand_no,
            rng=self.rng,
        )

    def _settle(self, alive, holes, board, contrib, folded, order):
        live = [p for p in alive if p not in folded]
        total = sum(contrib.values())
        if len(live) == 1:
            self.stacks[live[0]] += total
            return

        scores = {p: evaluate7(list(holes[p]) + board) for p in live}
        self._broadcast(("showdown", [(p, holes[p]) for p in live], tuple(board)))

        levels = sorted({contrib[p] for p in alive if contrib[p] > 0})
        prev = 0
        for lvl in levels:
            amount = sum(min(contrib[p], lvl) - min(contrib[p], prev) for p in alive)
            prev = lvl
            eligible = [p for p in live if contrib[p] >= lvl]
            if not eligible or amount == 0:
                continue
            best = max(scores[p] for p in eligible)
            winners = [p for p in eligible if scores[p] == best]
            share, odd = divmod(amount, len(winners))
            for p in winners:
                self.stacks[p] += share
            for p in order:                      # odd chips left of the button
                if odd == 0:
                    break
                if p in winners:
                    self.stacks[p] += 1
                    odd -= 1
