"""
No-Limit Texas Hold'em tournament engine.

Cards are ints 0..51:  rank = card >> 2  (0=Two .. 12=Ace),  suit = card & 3.

The engine runs full NLHE tournaments: rotating button, escalating blinds,
proper betting rounds (preflop/flop/turn/river), all-ins and side pots,
split pots, and eliminations. Strategies only ever see a `View` — their own
hole cards, the public board, pot state, and *observed* public actions of
opponents. Nobody is told anybody else's algorithm.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

RANKS = "23456789TJQKA"
SUITS = "shdc"


def card_str(c: int) -> str:
    return RANKS[c >> 2] + SUITS[c & 3]


# ---------------------------------------------------------------------------
# Hand evaluation: best 5-card hand out of 5/6/7 cards.
# Returns a tuple that compares correctly: (category, tiebreak ranks...).
# Categories: 8=straight flush, 7=quads, 6=full house, 5=flush,
#             4=straight, 3=trips, 2=two pair, 1=pair, 0=high card.
# ---------------------------------------------------------------------------

def _straight_high(rank_set: set) -> int:
    for high in range(12, 2, -1):
        if all((high - i) in rank_set for i in range(5)):
            return high
    if {12, 0, 1, 2, 3} <= rank_set:  # wheel: A-2-3-4-5
        return 3
    return -1


def evaluate(cards) -> tuple:
    ranks = [c >> 2 for c in cards]
    suit_bins = [[], [], [], []]
    for c in cards:
        suit_bins[c & 3].append(c >> 2)

    flush_ranks = None
    for sb in suit_bins:
        if len(sb) >= 5:
            flush_ranks = sorted(sb, reverse=True)
            break

    if flush_ranks:
        sf = _straight_high(set(flush_ranks))
        if sf >= 0:
            return (8, sf)

    count = {}
    for r in ranks:
        count[r] = count.get(r, 0) + 1
    # sort by (multiplicity, rank) descending
    groups = sorted(count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_ranks:
        return (5, *flush_ranks[:5])

    st = _straight_high(set(ranks))
    if st >= 0:
        return (4, st)

    if groups[0][1] == 3:
        trip = groups[0][0]
        kickers = sorted((r for r in ranks if r != trip), reverse=True)[:2]
        return (3, trip, *kickers)

    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hp and r != lp)
        return (2, hp, lp, kicker)

    if groups[0][1] == 2:
        pair = groups[0][0]
        kickers = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair, *kickers)

    return (0, *sorted(ranks, reverse=True)[:5])


def equity_montecarlo(hole, board, n_opps, iters, rng) -> float:
    """Monte-Carlo equity of `hole` on `board` vs n_opps random hands."""
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, need_board + 2 * n_opps)
        full_board = board + draw[:need_board]
        mine = evaluate(hole + full_board)
        best_opp = None
        idx = need_board
        for _o in range(n_opps):
            oh = draw[idx:idx + 2]
            idx += 2
            ov = evaluate(oh + full_board)
            if best_opp is None or ov > best_opp:
                best_opp = ov
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


# ---------------------------------------------------------------------------
# Players, views, public stats
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, name: str, strategy):
        self.name = name
        self.strategy = strategy
        self.chips = 0
        self.hole = []
        self.folded = False
        self.all_in = False
        self.round_bet = 0      # chips put in during current street
        self.committed = 0      # chips put in during current hand

    def __repr__(self):
        return f"{self.name}({self.chips})"


@dataclass
class View:
    """Everything a strategy is allowed to know when acting."""
    hole: list
    board: list
    street: str              # 'preflop' | 'flop' | 'turn' | 'river'
    pot: int                 # total chips committed by everyone this hand
    to_call: int
    current_bet: int         # highest round bet on this street
    min_raise_to: int        # smallest legal raise-to amount
    my_stack: int            # chips behind (not yet committed)
    my_round_bet: int
    big_blind: int
    small_blind: int
    seats_to_button: int     # 0 = I am the button
    n_players: int           # players dealt into this hand
    n_unfolded: int
    n_can_act: int           # unfolded and not all-in (me included)
    opp_stacks: list         # stacks of unfolded opponents
    hand_no: int
    was_aggressor: bool      # did I make the last raise on the previous street?
    facing_all_in: bool      # is any opponent all-in for the current bet?
    opp_stats: dict          # public observed action counts, keyed by name
    aggressor_name: str      # who made the current highest bet ('' if none)
    rng: random.Random


def blank_stats():
    return {"hands": 0, "vpip": 0, "raises": 0, "calls": 0,
            "folds": 0, "allins": 0, "actions": 0}


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------

BLIND_LEVELS = [(10, 20), (15, 30), (25, 50), (50, 100), (75, 150),
                (100, 200), (150, 300), (250, 500), (400, 800), (600, 1200)]
HANDS_PER_LEVEL = 12
MAX_HANDS = 500


class Tournament:
    def __init__(self, strategies, starting_chips=2000, seed=0, verbose=False):
        self.rng = random.Random(seed)
        self.players = []
        for name, strat_cls in strategies:
            p = Player(name, strat_cls())
            p.chips = starting_chips
            self.players.append(p)
        self.button = self.rng.randrange(len(self.players))
        self.hand_no = 0
        self.verbose = verbose
        self.stats = {p.name: blank_stats() for p in self.players}
        self.elimination_order = []   # first busted first

    # -- helpers ------------------------------------------------------------

    def alive(self):
        return [p for p in self.players if p.chips > 0]

    def log(self, msg):
        if self.verbose:
            print(msg)

    def blinds(self):
        level = min(self.hand_no // HANDS_PER_LEVEL, len(BLIND_LEVELS) - 1)
        return BLIND_LEVELS[level]

    def _order_from(self, seat_players, start_idx):
        n = len(seat_players)
        return [seat_players[(start_idx + i) % n] for i in range(n)]

    def _post(self, p, amount):
        amount = min(amount, p.chips)
        p.chips -= amount
        p.round_bet += amount
        p.committed += amount
        if p.chips == 0:
            p.all_in = True
        return amount

    def _record(self, p, action, voluntary=True):
        s = self.stats[p.name]
        s["actions"] += 1
        s[action] += 1
        if voluntary and action in ("calls", "raises"):
            s["vpip"] += 1

    # -- betting ------------------------------------------------------------

    def _betting_round(self, hand_players, order, current_bet, min_raise,
                       street, board, aggressor):
        sb, bb = self.blinds()
        pending = [p for p in order if not p.folded and not p.all_in]

        while pending:
            p = pending.pop(0)
            if p.folded or p.all_in:
                continue
            unfolded = [q for q in hand_players if not q.folded]
            if len(unfolded) <= 1:
                break
            to_call = current_bet - p.round_bet
            # No decision needed if nobody can respond and nothing to call
            can_respond = [q for q in unfolded
                           if q is not p and not q.all_in]
            if to_call <= 0 and not can_respond:
                break

            pot = sum(q.committed for q in hand_players)
            opps = [q for q in unfolded if q is not p]
            view = View(
                hole=list(p.hole), board=list(board), street=street,
                pot=pot, to_call=to_call, current_bet=current_bet,
                min_raise_to=current_bet + min_raise,
                my_stack=p.chips, my_round_bet=p.round_bet,
                big_blind=bb, small_blind=sb,
                seats_to_button=self._seats_to_button(p, hand_players),
                n_players=len(hand_players), n_unfolded=len(unfolded),
                n_can_act=1 + len(can_respond),
                opp_stacks=[q.chips for q in opps],
                hand_no=self.hand_no,
                was_aggressor=(aggressor[0] is p),
                facing_all_in=any(q.all_in and q.round_bet >= current_bet
                                  for q in opps),
                opp_stats={q.name: dict(self.stats[q.name]) for q in opps},
                aggressor_name=aggressor[0].name if aggressor[0] else "",
                rng=self.rng,
            )
            try:
                action, amount = p.strategy.decide(view)
            except Exception:
                action, amount = "fold", 0

            if action == "raise":
                target = min(int(amount), p.round_bet + p.chips)  # clamp to stack
                all_in_target = p.round_bet + p.chips
                legal_min = current_bet + min_raise
                if target <= current_bet:
                    action = "call"          # not actually a raise
                elif target < legal_min and target < all_in_target:
                    target = min(legal_min, all_in_target)

            if action == "raise":
                raise_size = target - current_bet
                self._post(p, target - p.round_bet)
                if raise_size >= min_raise:
                    min_raise = raise_size
                current_bet = target
                aggressor[0] = p
                self._record(p, "raises")
                if p.all_in:
                    self.stats[p.name]["allins"] += 1
                self.log(f"    {p.name} raises to {target}"
                         + (" (ALL IN)" if p.all_in else ""))
                nxt = []
                idx = hand_players.index(p)
                n = len(hand_players)
                for i in range(1, n):
                    q = hand_players[(idx + i) % n]
                    if not q.folded and not q.all_in and q is not p:
                        nxt.append(q)
                pending = nxt
            elif action == "call" or (action == "fold" and to_call <= 0):
                if to_call > 0:
                    self._post(p, to_call)
                    self._record(p, "calls")
                    if p.all_in:
                        self.stats[p.name]["allins"] += 1
                    self.log(f"    {p.name} calls {to_call}"
                             + (" (ALL IN)" if p.all_in else ""))
                else:
                    self.log(f"    {p.name} checks")
            else:
                p.folded = True
                self._record(p, "folds")
                self.log(f"    {p.name} folds")

    def _seats_to_button(self, p, hand_players):
        # seats after me until the button acts (0 = I am the button = best pos)
        idx = hand_players.index(p)
        btn = len(hand_players) - 1  # hand_players is ordered SB..button
        return (btn - idx) % len(hand_players)

    # -- one hand -----------------------------------------------------------

    def play_hand(self):
        alive = self.alive()
        if len(alive) < 2:
            return
        sb_amt, bb_amt = self.blinds()
        self.hand_no += 1

        # rotate button among alive players
        n_all = len(self.players)
        for _ in range(n_all):
            self.button = (self.button + 1) % n_all
            if self.players[self.button].chips > 0:
                break
        btn_player = self.players[self.button]

        # seat order starting left of button, button last: SB, BB, ..., BTN
        alive_idx = [i for i in range(n_all) if self.players[i].chips > 0]
        bpos = alive_idx.index(self.button)
        ordered = [self.players[alive_idx[(bpos + 1 + i) % len(alive_idx)]]
                   for i in range(len(alive_idx))]
        if len(ordered) == 2:
            # heads-up: button is the small blind
            ordered = [btn_player, [p for p in ordered if p is not btn_player][0]]
            sb_p, bb_p = ordered[0], ordered[1]
            hand_players = [bb_p, sb_p]   # SB..button ordering => [BB, BTN/SB]
        else:
            sb_p, bb_p = ordered[0], ordered[1]
            hand_players = ordered        # SB first ... button last

        for p in hand_players:
            p.folded = False
            p.all_in = False
            p.round_bet = 0
            p.committed = 0
            self.stats[p.name]["hands"] += 1

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in hand_players:
            p.hole = [deck.pop(), deck.pop()]
        board = []

        self.log(f"\n-- Hand {self.hand_no} (blinds {sb_amt}/{bb_amt}) "
                 f"button={btn_player.name}")
        for p in hand_players:
            self.log(f"    {p.name}: {card_str(p.hole[0])}{card_str(p.hole[1])}"
                     f" ({p.chips})")

        self._post(sb_p, sb_amt)
        self._post(bb_p, bb_amt)

        aggressor = [bb_p]
        # preflop: first to act is left of BB
        bb_idx = hand_players.index(bb_p)
        order = [hand_players[(bb_idx + 1 + i) % len(hand_players)]
                 for i in range(len(hand_players))]
        self._betting_round(hand_players, order, bb_amt, bb_amt,
                            "preflop", board, aggressor)

        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            unfolded = [p for p in hand_players if not p.folded]
            if len(unfolded) <= 1:
                break
            deck.pop()  # burn
            board.extend(deck.pop() for _ in range(n_cards))
            self.log(f"  {street}: " + " ".join(card_str(c) for c in board))
            for p in hand_players:
                p.round_bet = 0
            can_act = [p for p in unfolded if not p.all_in]
            if len(can_act) >= 2:
                street_aggr = [None]
                self._betting_round(hand_players, hand_players, 0, self.blinds()[1],
                                    street, board, street_aggr)
                aggressor = street_aggr if street_aggr[0] else aggressor

        self._award_pots(hand_players, board)

        for p in list(hand_players):
            if p.chips == 0:
                self.elimination_order.append(p.name)
                self.log(f"  ** {p.name} is ELIMINATED **")

    # -- pot resolution with side pots --------------------------------------

    def _award_pots(self, hand_players, board):
        unfolded = [p for p in hand_players if not p.folded]
        contrib = {p: p.committed for p in hand_players}

        if len(unfolded) == 1:
            winner = unfolded[0]
            total = sum(contrib.values())
            winner.chips += total
            self.log(f"  {winner.name} wins {total} uncontested")
            return

        # run out the board if needed (everyone all-in earlier)
        scores = {p: evaluate(p.hole + board) for p in unfolded}

        levels = sorted({c for c in contrib.values() if c > 0})
        prev = 0
        winnings = {p: 0 for p in hand_players}
        for lvl in levels:
            layer = 0
            for p, c in contrib.items():
                layer += max(0, min(c, lvl) - prev)
            eligible = [p for p in unfolded if contrib[p] >= lvl]
            if not eligible:      # folded money below everyone: goes to best hand
                eligible = unfolded
            best = max(scores[p] for p in eligible)
            winners = [p for p in eligible if scores[p] == best]
            share = layer // len(winners)
            rem = layer - share * len(winners)
            for i, w in enumerate(winners):
                winnings[w] += share + (1 if i < rem else 0)
            prev = lvl

        for p, amt in winnings.items():
            if amt:
                p.chips += amt
                self.log(f"  {p.name} wins {amt} with "
                         f"{[card_str(c) for c in p.hole]}")

    # -- run to completion ---------------------------------------------------

    def run(self) -> str:
        while len(self.alive()) > 1 and self.hand_no < MAX_HANDS:
            self.play_hand()
        survivors = self.alive()
        winner = max(survivors, key=lambda p: p.chips)
        return winner.name
