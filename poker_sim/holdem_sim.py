#!/usr/bin/env python3
"""
Texas Hold'em tournament simulator: 5 elaborate strategies vs 1 all-in bot.

Player 1 ("Suflair-GPT"):  if my_turn: bet = ALL IN  fi
Players 2..6: five distinct, elaborate strategies (tight-aggressive, loose-
aggressive, position/texture play, pot-odds mathematician, adaptive shark).
No strategy knows any other strategy's algorithm -- they only observe the
public actions at the table, like real players do.

Runs N full tournaments (everyone starts with equal chips, escalating blinds,
play until one player holds every chip) and prints a histogram of tournament
winners.
"""

import random
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------
# A card is an int 0..51: rank = card >> 2 (0='2' .. 12='A'), suit = card & 3.

RANK_CHARS = "23456789TJQKA"
SUIT_CHARS = "cdhs"


def card_str(c):
    return RANK_CHARS[c >> 2] + SUIT_CHARS[c & 3]


def _straight_high(rank_set):
    """High rank of the best straight in a set of ranks, else None (wheel ok)."""
    rs = rank_set | {-1} if 12 in rank_set else rank_set
    best = None
    run = 0
    for r in range(-1, 13):
        if r in rs:
            run += 1
            if run >= 5:
                best = r
        else:
            run = 0
    return best


def evaluate7(cards):
    """Best 5-card hand from 7 cards -> comparable tuple (bigger is better)."""
    ranks = [c >> 2 for c in cards]
    suits = [c & 3 for c in cards]

    suit_count = Counter(suits)
    flush_suit = None
    for s, n in suit_count.items():
        if n >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        flush_ranks = {r for r, s in zip(ranks, suits) if s == flush_suit}
        sf = _straight_high(flush_ranks)
        if sf is not None:
            return (8, sf)                                   # straight flush

    cnt = Counter(ranks)
    quads = [r for r, n in cnt.items() if n == 4]
    trips = sorted((r for r, n in cnt.items() if n == 3), reverse=True)
    pairs = sorted((r for r, n in cnt.items() if n == 2), reverse=True)

    if quads:
        q = quads[0]
        kicker = max(r for r in ranks if r != q)
        return (7, q, kicker)                                # four of a kind

    if trips and (pairs or len(trips) > 1):
        t = trips[0]
        fill = max(trips[1:] + pairs)
        return (6, t, fill)                                  # full house

    if flush_suit is not None:
        top5 = tuple(sorted(flush_ranks, reverse=True)[:5])
        return (5,) + top5                                   # flush

    st = _straight_high(set(ranks))
    if st is not None:
        return (4, st)                                       # straight

    if trips:
        t = trips[0]
        kickers = sorted((r for r in ranks if r != t), reverse=True)[:2]
        return (3, t) + tuple(kickers)                       # trips

    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kicker = max(r for r in ranks if r != p1 and r != p2)
        return (2, p1, p2, kicker)                           # two pair

    if pairs:
        p = pairs[0]
        kickers = sorted((r for r in ranks if r != p), reverse=True)[:3]
        return (1, p) + tuple(kickers)                       # one pair

    return (0,) + tuple(sorted(ranks, reverse=True)[:5])     # high card


# ---------------------------------------------------------------------------
# Equity estimation (Monte Carlo) -- strategies use this as their own "brain";
# it only uses information the player can legally see (own hole cards + board).
# ---------------------------------------------------------------------------

_PREFLOP_CACHE = {}
_equity_rng = random.Random(0xC0FFEE)


def estimate_equity(hole, board, n_opps, iters):
    """P(win) of `hole` + `board` vs n_opps random hands, by MC rollout."""
    if n_opps <= 0:
        return 1.0
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    score = 0.0
    rng = _equity_rng
    for _ in range(iters):
        draw = rng.sample(deck, 2 * n_opps + need_board)
        runout = board + draw[:need_board]
        mine = evaluate7(hole + runout)
        best_opp = None
        for i in range(n_opps):
            oh = draw[need_board + 2 * i: need_board + 2 * i + 2]
            ev = evaluate7(oh + runout)
            if best_opp is None or ev > best_opp:
                best_opp = ev
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters


def preflop_equity(hole, n_opps):
    """Cached preflop equity keyed by the 169 canonical hand classes."""
    r1, r2 = hole[0] >> 2, hole[1] >> 2
    suited = (hole[0] & 3) == (hole[1] & 3)
    key = (min(r1, r2), max(r1, r2), suited, n_opps)
    if key not in _PREFLOP_CACHE:
        _PREFLOP_CACHE[key] = estimate_equity(hole, [], n_opps, 400)
    return _PREFLOP_CACHE[key]


def chen_score(hole):
    """Bill Chen's preflop hand-strength formula."""
    r1, r2 = hole[0] >> 2, hole[1] >> 2
    suited = (hole[0] & 3) == (hole[1] & 3)
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(hi, (hi + 2) / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if suited:
        pts += 2
    gap = hi - lo - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi <= 9:      # connected low cards can make sneaky straights
        pts += 1
    return pts


# ---------------------------------------------------------------------------
# Strategy framework
# ---------------------------------------------------------------------------

class View:
    """Everything a player is allowed to see when it's their turn."""
    __slots__ = ("stage", "hole", "board", "pot", "to_call", "current_bet",
                 "min_raise", "my_stack", "my_bet_round", "big_blind",
                 "n_in_hand", "n_seated", "position", "stats", "hand_actions",
                 "rng")


class Strategy:
    name = "?"

    def act(self, v):
        """Return ('fold', 0) | ('call', 0) | ('raise', raise_to_total)."""
        raise NotImplementedError

    # -- shared helpers ----------------------------------------------------
    @staticmethod
    def pot_odds(v):
        return v.to_call / (v.pot + v.to_call) if v.to_call > 0 else 0.0

    @staticmethod
    def raise_to_frac_pot(v, frac):
        target = v.current_bet + max(v.min_raise, int(frac * (v.pot + v.to_call)))
        return min(target, v.my_bet_round + v.my_stack)

    @staticmethod
    def facing_all_in_shove(v):
        """A bet at least as big as our remaining stack is effectively a shove."""
        return v.to_call >= v.my_stack


class SuflairGPT(Strategy):
    """Player 1. The entire strategy, verbatim:

        if my_turn
        then bet = All in
        fi
    """
    name = "Suflair-GPT"

    def act(self, v):
        my_turn = True
        if my_turn:
            return ("raise", v.my_bet_round + v.my_stack)   # All in
        # fi


class TheRock(Strategy):
    """Tight-aggressive. Chen-formula preflop ranges tightened by position,
    postflop plays only real equity, value-bets big, never bluffs."""
    name = "The Rock"

    def act(self, v):
        if v.stage == "preflop":
            score = chen_score(v.hole)
            late = v.position <= 1                       # button or cutoff
            if self.facing_all_in_shove(v) and v.to_call > 4 * v.big_blind:
                eq = preflop_equity(v.hole, max(1, v.n_in_hand - 1))
                return ("call", 0) if score >= 10 or eq > 0.62 else ("fold", 0)
            if score >= 9:
                return ("raise", self.raise_to_frac_pot(v, 1.0))
            if score >= 7 or (late and score >= 6):
                if v.to_call <= 3 * v.big_blind:
                    return ("call", 0)
                eq = preflop_equity(v.hole, max(1, v.n_in_hand - 1))
                return ("call", 0) if eq > self.pot_odds(v) + 0.08 else ("fold", 0)
            return ("call", 0) if v.to_call == 0 else ("fold", 0)

        eq = estimate_equity(v.hole, v.board, max(1, v.n_in_hand - 1), 60)
        if eq > 0.72:
            return ("raise", self.raise_to_frac_pot(v, 0.75))
        if eq > 0.55 and v.to_call <= 0.5 * v.pot:
            return ("call", 0) if v.to_call > 0 else ("raise", self.raise_to_frac_pot(v, 0.5))
        if v.to_call == 0:
            return ("call", 0)                            # check
        return ("call", 0) if eq > self.pot_odds(v) + 0.05 else ("fold", 0)


class BlazeLAG(Strategy):
    """Loose-aggressive. Wide opens, relentless continuation bets, semi-bluffs
    with live equity, random pure bluffs -- but can release vs heavy action."""
    name = "Blaze the LAG"

    def act(self, v):
        r = v.rng
        if v.stage == "preflop":
            score = chen_score(v.hole)
            if self.facing_all_in_shove(v) and v.to_call > 5 * v.big_blind:
                eq = preflop_equity(v.hole, max(1, v.n_in_hand - 1))
                return ("call", 0) if eq > 0.58 else ("fold", 0)
            if score >= 8 or (score >= 5 and r.random() < 0.6):
                if v.to_call <= 4 * v.big_blind:
                    return ("raise", self.raise_to_frac_pot(v, 0.8))
                eq = preflop_equity(v.hole, max(1, v.n_in_hand - 1))
                return ("call", 0) if eq > self.pot_odds(v) else ("fold", 0)
            if score >= 5 and v.to_call <= 2 * v.big_blind:
                return ("call", 0)
            return ("call", 0) if v.to_call == 0 else ("fold", 0)

        eq = estimate_equity(v.hole, v.board, max(1, v.n_in_hand - 1), 50)
        big_action = v.to_call > 0.8 * v.pot
        if eq > 0.62:
            return ("raise", self.raise_to_frac_pot(v, 0.9))
        if v.to_call == 0:
            if eq > 0.35 or r.random() < 0.30:            # c-bet / pure bluff
                return ("raise", self.raise_to_frac_pot(v, 0.6))
            return ("call", 0)
        if big_action:
            return ("call", 0) if eq > self.pot_odds(v) + 0.04 else ("fold", 0)
        if eq > self.pot_odds(v) - 0.03 or r.random() < 0.12:
            return ("call", 0)
        return ("fold", 0)


class TheProfessor(Strategy):
    """Position & board-texture player. Opens tight early / wide on the button,
    slowplays monsters on dry boards, shuts down on wet boards without equity."""
    name = "The Professor"

    @staticmethod
    def board_wet(board):
        ranks = sorted(c >> 2 for c in board)
        suits = [c & 3 for c in board]
        flushy = max(Counter(suits).values()) >= max(2, len(board) - 1)
        paired = len(set(ranks)) < len(ranks)
        connected = any(b - a <= 2 for a, b in zip(ranks, ranks[1:]))
        return flushy or paired or connected

    def act(self, v):
        r = v.rng
        if v.stage == "preflop":
            score = chen_score(v.hole)
            late = v.position <= 1
            threshold = 6 if late else 8
            if self.facing_all_in_shove(v) and v.to_call > 4 * v.big_blind:
                eq = preflop_equity(v.hole, max(1, v.n_in_hand - 1))
                return ("call", 0) if eq > 0.60 else ("fold", 0)
            if score >= threshold + 2:
                return ("raise", self.raise_to_frac_pot(v, 0.9))
            if score >= threshold and v.to_call <= 3 * v.big_blind:
                return ("call", 0)
            suited_conn = (abs((v.hole[0] >> 2) - (v.hole[1] >> 2)) == 1
                           and (v.hole[0] & 3) == (v.hole[1] & 3))
            if late and suited_conn and v.to_call <= 2 * v.big_blind:
                return ("call", 0)
            return ("call", 0) if v.to_call == 0 else ("fold", 0)

        eq = estimate_equity(v.hole, v.board, max(1, v.n_in_hand - 1), 50)
        wet = self.board_wet(v.board)
        if eq > 0.80:
            if not wet and v.to_call == 0 and v.stage != "river" and r.random() < 0.5:
                return ("call", 0)                        # slowplay the monster
            return ("raise", self.raise_to_frac_pot(v, 1.0 if wet else 0.6))
        if eq > 0.58:
            if v.to_call == 0:
                return ("raise", self.raise_to_frac_pot(v, 0.5))
            return ("call", 0) if v.to_call <= 0.7 * v.pot else \
                (("call", 0) if eq > self.pot_odds(v) + 0.06 else ("fold", 0))
        if v.to_call == 0:
            if v.position <= 1 and not wet and r.random() < 0.35:
                return ("raise", self.raise_to_frac_pot(v, 0.5))   # positional stab
            return ("call", 0)
        return ("call", 0) if eq > self.pot_odds(v) + (0.08 if wet else 0.04) else ("fold", 0)


class TheMathematician(Strategy):
    """Pure expected-value machine: Monte-Carlo equity vs pot odds, bet sizing
    proportional to edge, zero bluffs, zero emotions."""
    name = "The Mathematician"

    def act(self, v):
        n_opps = max(1, v.n_in_hand - 1)
        if v.stage == "preflop":
            eq = preflop_equity(v.hole, n_opps)
        else:
            eq = estimate_equity(v.hole, v.board, n_opps, 70)

        breakeven = self.pot_odds(v)
        random_share = 1.0 / v.n_in_hand                  # equity of a random hand
        edge = eq - random_share

        if self.facing_all_in_shove(v):
            return ("call", 0) if eq > breakeven + 0.03 else ("fold", 0)
        if edge > 0.22:
            return ("raise", self.raise_to_frac_pot(v, min(1.2, 0.4 + 2.5 * edge)))
        if edge > 0.10 and v.to_call <= 2 * v.big_blind:
            return ("raise", self.raise_to_frac_pot(v, 0.5))
        if v.to_call == 0:
            return ("call", 0)
        return ("call", 0) if eq > breakeven + 0.02 else ("fold", 0)


class TheShark(Strategy):
    """Adaptive opponent modeler. Tracks each opponent's observed shove/raise/fold
    frequencies from public actions only, then exploits: snap-calls chronic
    shovers with decent equity, steals from tight tables, respects real raises."""
    name = "The Shark"

    def act(self, v):
        r = v.rng
        n_opps = max(1, v.n_in_hand - 1)

        # Who put in the last aggressive action this hand?
        aggressor = None
        for pname, act, _amt, _stage in reversed(v.hand_actions):
            if act == "raise":
                aggressor = pname
                break
        agg_stats = v.stats.get(aggressor) if aggressor else None
        maniac = bool(agg_stats and agg_stats["decisions"] >= 8 and
                      agg_stats["shoves"] / agg_stats["decisions"] > 0.5)
        table_tight = all(
            s["decisions"] < 6 or (s["folds"] / s["decisions"]) > 0.55
            for n, s in v.stats.items() if n != self.name
        )

        if v.stage == "preflop":
            eq = preflop_equity(v.hole, n_opps)
            if self.facing_all_in_shove(v) and v.to_call > 3 * v.big_blind:
                # vs a chronic shover, a merely-good hand is way ahead of random
                need = 0.52 if maniac else 0.62
                return ("call", 0) if eq > need else ("fold", 0)
            if chen_score(v.hole) >= 9:
                return ("raise", self.raise_to_frac_pot(v, 1.0))
            if table_tight and v.position <= 1 and v.to_call <= v.big_blind \
                    and chen_score(v.hole) >= 5:
                return ("raise", self.raise_to_frac_pot(v, 0.8))   # steal
            if eq > self.pot_odds(v) + 0.10 and v.to_call <= 3 * v.big_blind:
                return ("call", 0)
            return ("call", 0) if v.to_call == 0 else ("fold", 0)

        eq = estimate_equity(v.hole, v.board, n_opps, 60)
        if self.facing_all_in_shove(v):
            need = self.pot_odds(v) + (0.0 if maniac else 0.06)
            return ("call", 0) if eq > need else ("fold", 0)
        if eq > 0.70:
            return ("raise", self.raise_to_frac_pot(v, 0.8))
        if eq > 0.52:
            if v.to_call == 0:
                return ("raise", self.raise_to_frac_pot(v, 0.55))
            return ("call", 0) if eq > self.pot_odds(v) + 0.03 else ("fold", 0)
        if v.to_call == 0:
            if table_tight and r.random() < 0.30:
                return ("raise", self.raise_to_frac_pot(v, 0.5))
            return ("call", 0)
        return ("call", 0) if eq > self.pot_odds(v) + 0.06 else ("fold", 0)


# ---------------------------------------------------------------------------
# Table / tournament engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, name, strategy, stack):
        self.name = name
        self.strategy = strategy
        self.stack = stack
        # per-hand state
        self.hole = []
        self.in_hand = False
        self.bet_round = 0
        self.contrib = 0


class Tournament:
    BLIND_SCHEDULE_HANDS = 12         # blinds double every N hands
    MAX_HANDS = 1000

    def __init__(self, players, seed):
        self.players = players        # list[Player], seat order
        self.rng = random.Random(seed)
        self.button = 0
        self.hand_no = 0
        self.sb, self.bb = 10, 20
        # public, observable-by-anyone action stats (what a human would remember)
        self.stats = {p.name: {"decisions": 0, "shoves": 0, "raises": 0,
                               "folds": 0, "calls": 0} for p in players}
        self.eliminations = []        # names, in order of busting

    # -- helpers -----------------------------------------------------------
    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def next_alive(self, idx):
        n = len(self.players)
        for k in range(1, n + 1):
            p = self.players[(idx + k) % n]
            if p.stack > 0:
                return (idx + k) % n
        return idx

    def post(self, p, amount):
        pay = min(amount, p.stack)
        p.stack -= pay
        p.bet_round += pay
        p.contrib += pay
        return pay

    # -- one hand ----------------------------------------------------------
    def play_hand(self):
        alive = self.alive()
        self.hand_no += 1
        level = self.hand_no // self.BLIND_SCHEDULE_HANDS
        self.sb, self.bb = 10 * (2 ** level), 20 * (2 ** level)

        deck = list(range(52))
        self.rng.shuffle(deck)

        for p in self.players:
            p.in_hand = p.stack > 0
            p.bet_round = 0
            p.contrib = 0
            p.hole = []
        for p in alive:
            p.hole = [deck.pop(), deck.pop()]

        # blinds
        if len(alive) == 2:
            sb_idx = self.button if self.players[self.button].stack > 0 \
                else self.next_alive(self.button)
        else:
            sb_idx = self.next_alive(self.button)
        bb_idx = self.next_alive(sb_idx)
        self.post(self.players[sb_idx], self.sb)
        self.post(self.players[bb_idx], self.bb)

        board = []
        hand_actions = []
        current_bet = self.bb
        min_raise = self.bb

        def in_hand():
            return [p for p in self.players if p.in_hand]

        def betting_round(stage, first_idx):
            nonlocal current_bet, min_raise
            order = []
            idx = first_idx
            n = len(self.players)
            for _ in range(n):
                p = self.players[idx]
                if p.in_hand and p.stack > 0:
                    order.append(p)
                idx = (idx + 1) % n
            queue = list(order)
            while queue:
                p = queue.pop(0)
                if not p.in_hand or p.stack == 0:
                    continue
                if len(in_hand()) <= 1:
                    return
                to_call = current_bet - p.bet_round
                # nobody left to contest: no need to act
                others_can_pay = any(q is not p and q.in_hand and
                                     (q.stack > 0 or q.bet_round > p.bet_round)
                                     for q in self.players)
                if to_call == 0 and not others_can_pay:
                    continue

                v = View()
                v.stage = stage
                v.hole = p.hole
                v.board = board
                v.pot = sum(q.contrib for q in self.players)
                v.to_call = to_call
                v.current_bet = current_bet
                v.min_raise = min_raise
                v.my_stack = p.stack
                v.my_bet_round = p.bet_round
                v.big_blind = self.bb
                v.n_in_hand = len(in_hand())
                v.n_seated = len(self.alive())
                v.position = (self.button - self.players.index(p)) % len(self.players)
                v.stats = self.stats
                v.hand_actions = hand_actions
                v.rng = self.rng

                action, amount = p.strategy.act(v)
                st = self.stats[p.name]
                st["decisions"] += 1

                if action == "fold" and to_call == 0:
                    action = "call"                       # never fold for free
                if action == "raise":
                    target = min(int(amount), p.bet_round + p.stack)
                    if target <= current_bet:
                        action = "call"
                    elif target < current_bet + min_raise and \
                            target < p.bet_round + p.stack:
                        action = "call"                   # sub-min raise -> call
                    else:
                        pay = target - p.bet_round
                        self.post(p, pay)
                        if p.bet_round - current_bet >= min_raise:
                            min_raise = p.bet_round - current_bet
                        current_bet = p.bet_round
                        st["raises"] += 1
                        if p.stack == 0:
                            st["shoves"] += 1
                        hand_actions.append((p.name, "raise", p.bet_round, stage))
                        # everyone else gets to respond
                        queue = [q for q in order
                                 if q is not p and q.in_hand and q.stack > 0]
                        continue
                if action == "call":
                    pay = min(to_call, p.stack)
                    self.post(p, pay)
                    st["calls"] += 1
                    if p.stack == 0 and pay > 0:
                        st["shoves"] += 1
                    hand_actions.append((p.name, "call" if pay else "check",
                                         p.bet_round, stage))
                else:  # fold
                    p.in_hand = False
                    st["folds"] += 1
                    hand_actions.append((p.name, "fold", 0, stage))

        # pre-flop
        first = self.next_alive(bb_idx)
        betting_round("preflop", first)

        for stage, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(in_hand()) <= 1:
                break
            deck.pop()                                    # burn
            for _ in range(ncards):
                board.append(deck.pop())
            if sum(1 for p in in_hand() if p.stack > 0) >= 2:
                current_bet = 0
                min_raise = self.bb
                for p in self.players:
                    p.bet_round = 0
                betting_round(stage, self.next_alive(self.button))

        # run out remaining board for all-in showdowns
        while len(in_hand()) >= 2 and len(board) < 5:
            deck.pop()
            board.append(deck.pop())

        self.settle(board)

        # eliminations & button
        for p in self.players:
            if p.stack == 0 and p.name not in self.eliminations:
                self.eliminations.append(p.name)
        self.button = self.next_alive(self.button)

    def settle(self, board):
        live = [p for p in self.players if p.in_hand]
        contrib = {p: p.contrib for p in self.players}
        if len(live) == 1:
            winner = live[0]
            winner.stack += sum(contrib.values())
            return
        scores = {p: evaluate7(p.hole + board) for p in live}
        levels = sorted({c for c in contrib.values() if c > 0})
        prev = 0
        for lvl in levels:
            layer = sum(min(c, lvl) - prev for c in contrib.values() if c > prev)
            eligible = [p for p in live if contrib[p] >= lvl]
            if layer > 0 and eligible:
                best = max(scores[p] for p in eligible)
                winners = [p for p in eligible if scores[p] == best]
                share, rem = divmod(layer, len(winners))
                for i, w in enumerate(winners):
                    w.stack += share + (1 if i < rem else 0)
            prev = lvl

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < self.MAX_HANDS:
            self.play_hand()
        survivors = self.alive()
        champ = max(survivors, key=lambda p: p.stack)
        for p in sorted(survivors, key=lambda p: p.stack):
            if p is not champ and p.name not in self.eliminations:
                self.eliminations.append(p.name)
        return champ.name, self.hand_no, list(self.eliminations)


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

ROSTER = [
    ("P1", SuflairGPT),
    ("P2", TheRock),
    ("P3", BlazeLAG),
    ("P4", TheProfessor),
    ("P5", TheMathematician),
    ("P6", TheShark),
]
START_STACK = 1000


def run_sims(n_sims=100, master_seed=42):
    master = random.Random(master_seed)
    wins = Counter()
    first_out = Counter()
    hands_played = []
    finish_pos_sum = Counter()      # 1 = champion .. 6 = first bust

    for sim in range(n_sims):
        seed = master.getrandbits(64)
        players = [Player(f"{pid} {strat.name}", strat(), START_STACK)
                   for pid, strat in ROSTER]
        # random seats each tournament so no strategy owns a lucky chair
        random.Random(seed ^ 0xABCDEF).shuffle(players)
        t = Tournament(players, seed)
        champ, hands, elims = t.run()
        wins[champ] += 1
        hands_played.append(hands)
        if elims:
            first_out[elims[0]] += 1
        n = len(ROSTER)
        for rank, name in enumerate(elims):
            finish_pos_sum[name] += n - rank    # first out -> place 6
        finish_pos_sum[champ] += 1
        done = sim + 1
        if done % 10 == 0:
            print(f"  ... {done}/{n_sims} tournaments done", file=sys.stderr)

    return wins, first_out, hands_played, finish_pos_sum


def histogram(wins, n_sims):
    names = [f"{pid} {strat.name}" for pid, strat in ROSTER]
    width = max(len(n) for n in names)
    lines = []
    lines.append("TOURNAMENT WINS -- winner winner chicken dinner  "
                 f"({n_sims} sims, 6 players, {START_STACK} chips each)")
    lines.append("=" * (width + 50))
    top = max(wins.values()) if wins else 1
    for name in names:
        w = wins.get(name, 0)
        bar = "█" * max(1, round(w / top * 40)) if w else ""
        lines.append(f"{name:<{width}} | {bar:<40} {w:>3}  ({w / n_sims:.0%})")
    return "\n".join(lines)


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    print(f"Running {n_sims} tournaments (seed={seed})...", file=sys.stderr)
    wins, first_out, hands, fpos = run_sims(n_sims, seed)

    print()
    print(histogram(wins, n_sims))
    print()
    names = [f"{pid} {strat.name}" for pid, strat in ROSTER]
    width = max(len(n) for n in names)
    print("Average finishing place (1 = champion, 6 = first bust) "
          "and times busting first:")
    for name in names:
        avg = fpos.get(name, 0) / n_sims
        print(f"{name:<{width}} | avg place {avg:.2f} | first out {first_out.get(name, 0):>3}x")
    print(f"\nAvg tournament length: {sum(hands) / len(hands):.0f} hands")


if __name__ == "__main__":
    main()
