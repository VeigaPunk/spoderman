"""No-limit Texas Hold'em tournament engine.

Cards are ints 0..51: rank = card % 13 (0 = deuce .. 12 = ace), suit = card // 13.
Hands are ranked as tuples (category, tiebreakers...) — bigger tuple wins.
Categories: 8=straight flush, 7=quads, 6=full house, 5=flush, 4=straight,
3=trips, 2=two pair, 1=pair, 0=high card.
"""

import itertools

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_str(c):
    return RANKS[c % 13] + SUITS[c // 13]


def eval5(cards):
    """Rank a 5-card hand. Returns a comparable tuple."""
    ranks = sorted((c % 13 for c in cards), reverse=True)
    suits = [c // 13 for c in cards]
    flush = len(set(suits)) == 1

    # Straight detection (ace can play low: A-2-3-4-5)
    distinct = sorted(set(ranks), reverse=True)
    straight_high = -1
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_high = distinct[0]
        elif distinct == [12, 3, 2, 1, 0]:  # wheel
            straight_high = 3

    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    # Sort by (count, rank) desc → e.g. full house gives [(3, r), (2, r)]
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if flush and straight_high >= 0:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if straight_high >= 0:
        return (4, straight_high)
    if groups[0][1] == 3:
        kickers = sorted((r for r, n in groups[1:]), reverse=True)
        return (3, groups[0][0], *kickers)
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        kickers = sorted((r for r, n in groups[1:]), reverse=True)
        return (1, groups[0][0], *kickers)
    return (0, *ranks)


def eval7(cards):
    """Best 5-card rank out of 5, 6 or 7 cards."""
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(combo) for combo in itertools.combinations(cards, 5))


class GameView:
    """Everything a strategy is allowed to see: its own cards + public info.

    Strategies never see each other's hole cards or code — only observable
    table behaviour (public_stats), exactly like a live table.
    """

    __slots__ = (
        "hole", "board", "street", "pot", "to_call", "current_bet",
        "min_raise_to", "my_stack", "my_bet", "big_blind", "n_active",
        "n_players", "position", "stacks", "history", "public_stats",
    )

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw[k])

    @property
    def pot_odds(self):
        """Fraction of the final pot we must contribute to call."""
        if self.to_call <= 0:
            return 0.0
        return self.to_call / (self.pot + self.to_call)


class PlayerState:
    def __init__(self, pid, name, strategy, chips):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.chips = chips
        # public, observable-behaviour counters (any live player could track these)
        self.stats = {"hands": 0, "raises": 0, "calls": 0, "folds": 0, "allins": 0}


class Tournament:
    def __init__(self, players, rng, start_chips=1000, sb=10,
                 blind_double_every=15, max_hands=1000):
        self.rng = rng
        self.players = players
        for p in self.players:
            p.chips = start_chips
        self.sb0 = sb
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.button = 0
        self.hands_played = 0

    def blinds(self):
        level = self.hands_played // self.blind_double_every
        sb = self.sb0 * (2 ** min(level, 12))
        return sb, sb * 2

    def alive(self):
        return [p for p in self.players if p.chips > 0]

    def run(self):
        """Play until one player holds all chips. Returns the winner."""
        while len(self.alive()) > 1 and self.hands_played < self.max_hands:
            self.play_hand()
            self.hands_played += 1
        survivors = self.alive()
        return max(survivors, key=lambda p: p.chips)

    # ------------------------------------------------------------------ hand
    def play_hand(self):
        alive = self.alive()
        n = len(alive)
        self.button %= len(self.players)
        while self.players[self.button].chips <= 0:
            self.button = (self.button + 1) % len(self.players)

        # Seat order for this hand, starting left of the button
        order = []
        i = (self.button + 1) % len(self.players)
        while len(order) < n:
            if self.players[i].chips > 0:
                order.append(self.players[i])
            i = (i + 1) % len(self.players)
        btn_player = self.players[self.button]

        # Heads-up: the button posts the small blind and acts first preflop
        if n == 2:
            sb_p, bb_p = btn_player, order[0] if order[0] is not btn_player else order[1]
        else:
            sb_p, bb_p = order[0], order[1]

        sb_amt, bb_amt = self.blinds()
        deck = list(range(52))
        self.rng.shuffle(deck)

        contrib = {p.pid: 0 for p in alive}       # whole-hand contributions
        folded = set()
        holes = {}
        for p in alive:
            holes[p.pid] = (deck.pop(), deck.pop())
            p.stats["hands"] += 1

        def post(p, amt):
            amt = min(amt, p.chips)
            p.chips -= amt
            contrib[p.pid] += amt
            return amt

        street_bets = {p.pid: 0 for p in alive}
        street_bets[sb_p.pid] = post(sb_p, sb_amt)
        street_bets[bb_p.pid] = post(bb_p, bb_amt)

        board = []
        history = []

        def active_can_bet():
            return [p for p in alive if p.pid not in folded and p.chips > 0]

        def not_folded():
            return [p for p in alive if p.pid not in folded]

        def betting_round(street, first_actors):
            nonlocal street_bets
            current_bet = max(street_bets.values()) if street_bets else 0
            last_raise = bb_amt
            queue = [p for p in first_actors if p.pid not in folded and p.chips > 0]
            acted = set()
            while queue:
                p = queue.pop(0)
                if p.pid in folded or p.chips == 0:
                    continue
                if len(not_folded()) == 1:
                    return
                to_call = current_bet - street_bets[p.pid]
                pot = sum(contrib.values())
                view = GameView(
                    hole=holes[p.pid], board=tuple(board), street=street,
                    pot=pot, to_call=to_call, current_bet=current_bet,
                    min_raise_to=current_bet + last_raise, my_stack=p.chips,
                    my_bet=street_bets[p.pid], big_blind=bb_amt,
                    n_active=len(not_folded()), n_players=n,
                    position=order.index(p),
                    stacks={q.name: q.chips for q in alive},
                    history=tuple(history),
                    public_stats={q.name: dict(q.stats) for q in alive},
                )
                action, amount = p.strategy.act(view)

                if action == "fold" and to_call == 0:
                    action = "call"  # never fold for free; treat as check
                if action == "raise":
                    # raise TO `amount` this street; clamp to legality
                    max_to = street_bets[p.pid] + p.chips
                    amount = min(amount, max_to)
                    if amount < view.min_raise_to and amount < max_to:
                        # not a legal raise size and not all-in → make it a call
                        action = "call"
                    elif amount <= current_bet:
                        action = "call"

                if action == "fold":
                    folded.add(p.pid)
                    p.stats["folds"] += 1
                    history.append((p.name, street, "fold", 0))
                elif action == "raise":
                    add = amount - street_bets[p.pid]
                    add = post(p, add)
                    street_bets[p.pid] += add
                    raise_size = street_bets[p.pid] - current_bet
                    if raise_size > 0:
                        last_raise = max(last_raise, raise_size)
                        current_bet = street_bets[p.pid]
                        acted = set()  # everyone gets to respond to a raise
                    p.stats["raises"] += 1
                    if p.chips == 0:
                        p.stats["allins"] += 1
                    history.append((p.name, street, "raise", street_bets[p.pid]))
                else:  # call / check
                    add = post(p, to_call)
                    street_bets[p.pid] += add
                    p.stats["calls"] += 1
                    if p.chips == 0 and to_call > 0:
                        p.stats["allins"] += 1
                    history.append(
                        (p.name, street, "check" if to_call == 0 else "call",
                         street_bets[p.pid]))

                acted.add(p.pid)
                # refill queue with players who still owe action
                if not queue:
                    pending = [q for q in active_can_bet()
                               if q.pid not in acted
                               or street_bets[q.pid] < current_bet]
                    pending = [q for q in pending if q.chips > 0]
                    if pending:
                        start = (order.index(p) + 1) % len(order)
                        rotated = order[start:] + order[:start]
                        queue = [q for q in rotated if q in pending]

        # --- preflop: first to act is left of the BB (heads-up: the button/SB)
        if n == 2:
            preflop_order = [sb_p, bb_p]
        else:
            idx = (order.index(bb_p) + 1) % len(order)
            preflop_order = order[idx:] + order[:idx]
        betting_round("preflop", preflop_order)

        # --- postflop streets: first to act is left of the button
        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(not_folded()) <= 1:
                break
            for _ in range(ncards):
                board.append(deck.pop())
            if len(active_can_bet()) > 1:
                street_bets = {p.pid: 0 for p in alive}
                betting_round(street, list(order))
            # else: everyone all-in or matched — just run the board out

        self.showdown(alive, contrib, folded, holes, board, deck, order)

    # ------------------------------------------------------------- showdown
    def showdown(self, alive, contrib, folded, holes, board, deck, order):
        contenders = [p for p in alive if p.pid not in folded]

        # Refund any uncalled excess bet
        if contrib:
            tops = sorted(contrib.values(), reverse=True)
            if len(tops) > 1 and tops[0] > tops[1]:
                over = tops[0] - tops[1]
                for p in alive:
                    if contrib[p.pid] == tops[0]:
                        contrib[p.pid] -= over
                        p.chips += over
                        break

        if len(contenders) == 1:
            contenders[0].chips += sum(contrib.values())
            return

        while len(board) < 5:  # run out the board if betting ended early
            board.append(deck.pop())

        scores = {p.pid: eval7(list(holes[p.pid]) + board) for p in contenders}

        # Build side pots from contribution levels
        levels = sorted({v for v in contrib.values() if v > 0})
        prev = 0
        for lvl in levels:
            pot = sum(min(c, lvl) - min(c, prev) for c in contrib.values())
            prev = lvl
            eligible = [p for p in contenders if contrib[p.pid] >= lvl]
            if not eligible or pot == 0:
                continue
            best = max(scores[p.pid] for p in eligible)
            winners = [p for p in eligible if scores[p.pid] == best]
            share, odd = divmod(pot, len(winners))
            winners.sort(key=lambda p: order.index(p))
            for i, w in enumerate(winners):
                w.chips += share + (1 if i < odd else 0)
