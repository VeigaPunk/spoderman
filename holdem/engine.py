"""No-limit Texas Hold'em tournament engine.

Full betting rounds, all-ins, side pots, uncalled-bet refunds, escalating
blinds, eliminations. One simplification vs. casino rules: an all-in raise
below the minimum raise still reopens the action (in strict rules the
players who already acted could only call). It never affects termination
and rarely affects outcomes.
"""

import random

from .poker import make_deck, best_hand


class HandPlayer:
    __slots__ = ("seat", "hole", "folded", "allin", "street_bet", "total_contrib")

    def __init__(self, seat):
        self.seat = seat
        self.hole = None
        self.folded = False
        self.allin = False
        self.street_bet = 0
        self.total_contrib = 0

    @property
    def active(self):
        return not self.folded and not self.allin


class View:
    """Everything a strategy is allowed to see when it acts."""

    def __init__(self, hp, board, street, pot, current_bet, min_raise, bb, sb,
                 opponents_in_hand, seats_after, current_aggressor, rng):
        self.hole = hp.hole
        self.board = tuple(board)
        self.street = street
        self.pot = pot
        self.to_call = max(0, current_bet - hp.street_bet)
        self.my_stack = hp.seat.chips
        self.my_street_bet = hp.street_bet
        self.big_blind = bb
        self.small_blind = sb
        self.opponents_in_hand = opponents_in_hand
        self.seats_after = seats_after
        self.current_aggressor = current_aggressor
        self.rng = rng
        self._current_bet = current_bet
        self._min_raise = min_raise

    def suggest_raise(self, mult):
        """Raise-to sized as a multiple of the current bet (or BB if unopened)."""
        base = self._current_bet if self._current_bet > 0 else self.big_blind
        return int(base * mult)

    def suggest_raise_pot(self, frac):
        """Raise-to sized as a fraction of the pot after calling."""
        return self._current_bet + max(self.big_blind, int(frac * (self.pot + self.to_call)))


class Seat:
    def __init__(self, pid, name, strategy, chips):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.chips = chips


def _post(hp, amount):
    amount = min(amount, hp.seat.chips)
    hp.seat.chips -= amount
    hp.street_bet += amount
    if hp.seat.chips == 0:
        hp.allin = True
    return amount


def _betting_round(hand, order, street, board, current_bet, min_raise, bb, sb,
                   rng, all_strategies, aggressor):
    """Run one street of betting. Mutates hand players; returns the aggressor."""
    queue = [hp for hp in order if hp.active]

    while queue:
        in_hand = [hp for hp in hand if not hp.folded]
        if len(in_hand) <= 1:
            break
        hp = queue.pop(0)
        if not hp.active:
            continue

        pot = sum(p.total_contrib + p.street_bet for p in hand)
        seats_after = sum(1 for q in queue if q.active)
        view = View(hp, board, street, pot, current_bet, min_raise, bb, sb,
                    opponents_in_hand=len(in_hand) - 1, seats_after=seats_after,
                    current_aggressor=aggressor, rng=rng)
        decision = hp.seat.strategy.decide(view)
        kind = decision[0]
        to_call = max(0, current_bet - hp.street_bet)

        # Normalize the intent into a legal action.
        if kind == "fold" and to_call == 0:
            kind = "check"
        if kind == "check" and to_call > 0:
            kind = "fold"

        if kind == "fold":
            hp.folded = True
            actual = "fold"
        elif kind == "check":
            actual = "check"
        else:
            if kind == "allin":
                target = hp.street_bet + hp.seat.chips
            elif kind == "raise":
                target = int(decision[1])
                max_target = hp.street_bet + hp.seat.chips
                if target < current_bet + min_raise:
                    target = current_bet + min_raise  # enforce min raise
                target = min(target, max_target)
                if target <= current_bet:
                    kind = "call"
            else:
                target = current_bet
            if kind == "call":
                target = min(current_bet, hp.street_bet + hp.seat.chips)
            _post(hp, target - hp.street_bet)
            if hp.street_bet > current_bet:
                raise_size = hp.street_bet - current_bet
                min_raise = max(min_raise, raise_size)
                current_bet = hp.street_bet
                aggressor = hp.seat.pid
                # everyone else active gets to respond, in order after the raiser
                idx = order.index(hp)
                rotated = order[idx + 1:] + order[:idx]
                queue = [q for q in rotated if q.active]
                actual = "allin" if hp.allin else "raise"
            else:
                actual = "call"  # includes calling all-in for less

        event = {"player": hp.seat.pid, "action": actual, "street": street,
                 "bet": hp.street_bet}
        for strat in all_strategies:
            strat.observe(event)

    for hp in hand:
        hp.total_contrib += hp.street_bet
        hp.street_bet = 0
    return aggressor


def _distribute(hand, board, button_order):
    """Refund uncalled excess, build side pots, pay winners."""
    for hp in hand:  # sweep in blinds/bets from any skipped betting round
        hp.total_contrib += hp.street_bet
        hp.street_bet = 0
    contribs = {hp: hp.total_contrib for hp in hand}
    in_hand = [hp for hp in hand if not hp.folded]

    # Refund the uncalled portion of the largest bet.
    top = max(contribs.values())
    top_players = [hp for hp in hand if contribs[hp] == top]
    if len(top_players) == 1:
        second = max((v for hp, v in contribs.items() if hp is not top_players[0]),
                     default=0)
        refund = top - second
        if refund > 0:
            top_players[0].seat.chips += refund
            contribs[top_players[0]] -= refund

    if len(in_hand) == 1:
        in_hand[0].seat.chips += sum(contribs.values())
        return

    # Side pots: peel off contribution layers from the bottom.
    remaining = dict(contribs)
    pots = []  # (amount, eligible players)
    while True:
        live = [hp for hp in in_hand if remaining[hp] > 0]
        if not live:
            break
        level = min(remaining[hp] for hp in live)
        amount = 0
        for hp in hand:
            take = min(remaining[hp], level)
            remaining[hp] -= take
            amount += take
        pots.append((amount, list(live)))
    leftover = sum(remaining.values())
    if leftover and pots:  # folded money above the top all-in level
        pots[-1] = (pots[-1][0] + leftover, pots[-1][1])

    ranks = {hp: best_hand(list(hp.hole) + list(board)) for hp in in_hand}
    for amount, eligible in pots:
        best = max(ranks[hp] for hp in eligible)
        winners = [hp for hp in eligible if ranks[hp] == best]
        share, odd = divmod(amount, len(winners))
        for hp in winners:
            hp.seat.chips += share
        if odd:  # odd chips to the earliest winner in position order
            for hp in button_order:
                if hp in winners:
                    hp.seat.chips += odd
                    break


def play_hand(seats, button_pid, sb, bb, rng):
    """Play one full hand among the given seats (all with chips > 0)."""
    hand = [HandPlayer(s) for s in seats]
    n = len(hand)
    strategies = [s.strategy for s in seats]

    deck = make_deck()
    rng.shuffle(deck)
    for hp in hand:
        hp.hole = (deck.pop(), deck.pop())

    btn_idx = next(i for i, hp in enumerate(hand) if hp.seat.pid == button_pid)
    after_btn = hand[btn_idx + 1:] + hand[:btn_idx + 1]  # SB first, button last

    if n == 2:  # heads-up: button posts SB and acts first preflop
        sb_p, bb_p = hand[btn_idx], after_btn[0]
        preflop_order = [sb_p, bb_p]
        postflop_order = [bb_p, sb_p]
    else:
        sb_p, bb_p = after_btn[0], after_btn[1]
        preflop_order = after_btn[2:] + [sb_p, bb_p]
        postflop_order = after_btn  # SB first, button last
    _post(sb_p, sb)
    _post(bb_p, bb)

    board = []
    streets = [("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)]
    for street, n_cards in streets:
        deck and n_cards and board.extend(deck.pop() for _ in range(n_cards))
        in_hand = [hp for hp in hand if not hp.folded]
        if len(in_hand) <= 1:
            continue
        active = [hp for hp in in_hand if not hp.allin]
        street_bet_to_match = bb if street == "preflop" else 0
        if not active:
            continue  # everyone is all-in; just run out the board
        if len(active) == 1 and active[0].street_bet >= min(
                street_bet_to_match, max(hp.street_bet for hp in in_hand)):
            continue  # lone active player has nothing left to call
        if street == "preflop":
            _betting_round(hand, preflop_order, street, board,
                           current_bet=bb, min_raise=bb, bb=bb, sb=sb,
                           rng=rng, all_strategies=strategies, aggressor=None)
        else:
            _betting_round(hand, postflop_order, street, board,
                           current_bet=0, min_raise=bb, bb=bb, sb=sb,
                           rng=rng, all_strategies=strategies, aggressor=None)

    _distribute(hand, board, postflop_order)


def play_tournament(lineup, names, starting_chips=1000, seed=0):
    """Play a full tournament; returns (winner_pid, hands_played)."""
    rng = random.Random(seed)
    seats = [Seat(i + 1, names[i], lineup[i], starting_chips)
             for i in range(len(lineup))]

    button = seats[rng.randrange(len(seats))].pid
    hands = 0
    while True:
        alive = [s for s in seats if s.chips > 0]
        if len(alive) == 1:
            return alive[0].pid, hands
        if not alive:  # cannot happen (pot always pays out), but never loop forever
            return max(seats, key=lambda s: s.chips).pid, hands

        level = hands // 10  # blinds double every 10 hands: termination guaranteed
        sb, bb = 10 * (2 ** level), 20 * (2 ** level)

        # move the button to the next living player
        pids = [s.pid for s in alive]
        later = [p for p in pids if p > button]
        button = min(later) if later else min(pids)

        play_hand(alive, button, sb, bb, rng)
        hands += 1
        if hands > 5000:  # unreachable with doubling blinds; hard safety stop
            return max(seats, key=lambda s: s.chips).pid, hands
