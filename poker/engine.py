"""No-limit Texas Hold'em tournament engine.

Plays full tournaments (escalating blinds, side pots, eliminations) between
Strategy objects. Strategies only see public information plus their own hole
cards — they never see each other's code or hole cards before showdown.
"""

from .cards import make_deck, evaluate

BLIND_LEVELS = [
    (10, 20), (15, 30), (25, 50), (50, 100), (75, 150),
    (100, 200), (150, 300), (200, 400), (300, 600),
    (400, 800), (600, 1200), (1000, 2000),
]
HANDS_PER_LEVEL = 20
MAX_HANDS = 5000


class Tournament:
    def __init__(self, seat_players, strategies, starting_stack, rng):
        """seat_players: list of player ids in seat order.
        strategies: dict player_id -> Strategy instance."""
        self.rng = rng
        self.seats = list(seat_players)
        self.strategies = strategies
        self.stacks = {p: starting_stack for p in self.seats}
        self.button_idx = 0
        self.hand_no = 0
        self.finish_order = []  # eliminated players, first bust first

    def alive(self):
        return [p for p in self.seats if self.stacks[p] > 0]

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < MAX_HANDS:
            self.play_hand()
            self.hand_no += 1
        alive = sorted(self.alive(), key=lambda p: self.stacks[p])
        self.finish_order.extend(alive)  # chip leader last if hand cap hit
        winner = self.finish_order[-1]
        return winner, list(reversed(self.finish_order)), self.hand_no

    def blinds(self):
        lvl = min(self.hand_no // HANDS_PER_LEVEL, len(BLIND_LEVELS) - 1)
        return BLIND_LEVELS[lvl]

    def broadcast(self, event):
        for p in self.alive():
            self.strategies[p].observe(event)

    def play_hand(self):
        players = self.alive()
        self.button_idx %= len(players)
        button = players[self.button_idx]
        sb_amt, bb_amt = self.blinds()

        h = Hand(self, players, button, sb_amt, bb_amt)
        h.play()

        busted = [p for p in players if self.stacks[p] == 0]
        busted.sort(key=lambda p: players.index(p))
        self.finish_order.extend(busted)

        # advance button to next surviving player
        nxt = self.button_idx + 1
        survivors = self.alive()
        if survivors:
            for i in range(len(players)):
                cand = players[(nxt + i) % len(players)]
                if self.stacks[cand] > 0:
                    self.button_idx = survivors.index(cand)
                    break


class Hand:
    def __init__(self, tourney, players, button, sb_amt, bb_amt):
        self.t = tourney
        self.rng = tourney.rng
        self.players = players
        self.button = button
        self.sb_amt = sb_amt
        self.bb_amt = bb_amt
        self.stacks = tourney.stacks

        self.in_hand = {p: True for p in players}
        self.all_in = {p: False for p in players}
        self.contrib = {p: 0 for p in players}
        self.street_bet = {p: 0 for p in players}
        self.current_bet = 0
        self.last_raise_size = bb_amt
        self.community = []

        deck = make_deck()
        self.rng.shuffle(deck)
        self.deck = deck
        self.holes = {}
        for p in players:
            self.holes[p] = [self.deck.pop(), self.deck.pop()]

    # --- helpers ---------------------------------------------------------
    def seat_after(self, p, k=1):
        i = self.players.index(p)
        return self.players[(i + k) % len(self.players)]

    def live(self):
        return [p for p in self.players if self.in_hand[p]]

    def actives(self):
        return [p for p in self.players if self.in_hand[p] and not self.all_in[p]]

    def pot(self):
        return sum(self.contrib.values())

    def pay(self, p, amount):
        amount = min(amount, self.stacks[p])
        self.stacks[p] -= amount
        self.contrib[p] += amount
        self.street_bet[p] += amount
        if self.stacks[p] == 0:
            self.all_in[p] = True
        return amount

    # --- flow ------------------------------------------------------------
    def play(self):
        t = self.t
        heads_up = len(self.players) == 2
        sb = self.button if heads_up else self.seat_after(self.button)
        bb = self.seat_after(sb)

        for p in self.players:
            t.strategies[p].new_hand({
                "hole": list(self.holes[p]),
                "seat": p,
                "players": list(self.players),
                "button": self.button,
                "bb": self.bb_amt,
                "stacks": dict(self.stacks),
            })
        t.broadcast({"type": "hand_start", "players": list(self.players),
                     "button": self.button, "bb": self.bb_amt})

        self.pay(sb, self.sb_amt)
        self.pay(bb, self.bb_amt)
        self.current_bet = self.bb_amt

        first_preflop = sb if heads_up else self.seat_after(bb)
        self.betting_round("preflop", first_preflop)

        streets = [("flop", 3), ("turn", 1), ("river", 1)]
        first_post = bb if heads_up else self.seat_after(self.button)
        for street, ncards in streets:
            if len(self.live()) <= 1:
                break
            for _ in range(ncards):
                self.community.append(self.deck.pop())
            if len(self.actives()) >= 2:
                self.street_bet = {p: 0 for p in self.players}
                self.current_bet = 0
                self.last_raise_size = self.bb_amt
                self.betting_round(street, self.first_live_from(first_post))

        self.showdown()

    def first_live_from(self, start):
        i = self.players.index(start)
        for k in range(len(self.players)):
            p = self.players[(i + k) % len(self.players)]
            if self.in_hand[p] and not self.all_in[p]:
                return p
        return start

    def betting_round(self, street, first):
        pending = set(self.actives())
        if not pending:
            return
        order = self.players
        idx = order.index(first)

        while pending:
            if len(self.live()) <= 1:
                return
            p = None
            for k in range(len(order)):
                cand = order[(idx + k) % len(order)]
                if cand in pending:
                    p = cand
                    idx = (order.index(cand) + 1) % len(order)
                    break
            if p is None:
                return
            pending.discard(p)
            self.player_action(p, street, pending)

    def player_action(self, p, street, pending):
        t = self.t
        to_call = self.current_bet - self.street_bet[p]
        obs = {
            "street": street,
            "hole": list(self.holes[p]),
            "community": list(self.community),
            "pot": self.pot(),
            "to_call": to_call,
            "current_bet": self.current_bet,
            "min_raise_to": self.current_bet + self.last_raise_size,
            "my_street_bet": self.street_bet[p],
            "my_stack": self.stacks[p],
            "seat": p,
            "button": self.button,
            "bb": self.bb_amt,
            "num_live": len(self.live()),
            "opponents": [
                {"seat": q, "stack": self.stacks[q], "street_bet": self.street_bet[q],
                 "in_hand": self.in_hand[q], "all_in": self.all_in[q]}
                for q in self.players if q != p
            ],
        }
        try:
            action, amount = t.strategies[p].act(obs)
        except Exception:
            action, amount = ("call", 0) if to_call == 0 else ("fold", 0)

        # --- sanitize ----------------------------------------------------
        max_to = self.street_bet[p] + self.stacks[p]
        if action == "fold" and to_call == 0:
            action = "call"
        if action not in ("fold", "call", "raise"):
            action = "call" if to_call <= self.stacks[p] else "fold"

        if action == "fold":
            self.in_hand[p] = False
            paid = 0
        elif action == "call":
            paid = self.pay(p, to_call)
        else:  # raise to `amount` (total street bet)
            target = min(int(amount), max_to)
            min_to = self.current_bet + self.last_raise_size
            if target < min_to and target < max_to:
                target = min(min_to, max_to)
            if target <= self.current_bet:
                action = "call"
                paid = self.pay(p, to_call)
            else:
                paid = self.pay(p, target - self.street_bet[p])
                raise_size = self.street_bet[p] - self.current_bet
                self.current_bet = self.street_bet[p]
                if raise_size >= self.last_raise_size:
                    self.last_raise_size = raise_size
                for q in self.actives():
                    if q != p and self.street_bet[q] < self.current_bet:
                        pending.add(q)

        t.broadcast({"type": "action", "seat": p, "street": street,
                     "action": action, "paid": paid,
                     "to_call": to_call, "all_in": self.all_in[p],
                     "pot": self.pot(), "bb": self.bb_amt})

    def showdown(self):
        t = self.t
        live = self.live()
        while len(self.community) < 5 and len(live) > 1:
            self.community.append(self.deck.pop())

        if len(live) == 1:
            self.stacks[live[0]] += self.pot()
            t.broadcast({"type": "hand_end", "winners": [live[0]], "showdown": False})
            return

        for p in live:
            t.broadcast({"type": "showdown", "seat": p, "hole": list(self.holes[p]),
                         "community": list(self.community)})

        scores = {p: evaluate(self.holes[p] + self.community) for p in live}
        levels = sorted({self.contrib[p] for p in self.players if self.contrib[p] > 0})
        prev = 0
        all_winners = set()
        for lvl in levels:
            layer = sum(min(self.contrib[p], lvl) - min(self.contrib[p], prev)
                        for p in self.players)
            eligible = [p for p in live if self.contrib[p] >= lvl]
            best = max(scores[p] for p in eligible)
            winners = [p for p in eligible if scores[p] == best]
            share, rem = divmod(layer, len(winners))
            for i, w in enumerate(winners):
                self.stacks[w] += share + (1 if i < rem else 0)
            all_winners.update(winners)
            prev = lvl

        t.broadcast({"type": "hand_end", "winners": sorted(all_winners),
                     "showdown": True})
