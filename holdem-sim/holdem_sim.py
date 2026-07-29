#!/usr/bin/env python3
"""
holdem_sim.py — No-limit Texas Hold'em tournament simulator.

Six players sit down with identical stacks. Seats 2-6 run five distinct
"elaborate" strategies (tight-aggressive positional play, Monte-Carlo equity
calculation, loose-aggressive bluffing, ultra-tight rock, and an adaptive
opponent-modelling exploiter). Seat 1 ("Suflair-GPT") runs the simplest
strategy in poker:

    if my_turn:
        bet = ALL IN
    fi

No strategy can see another player's cards or decision logic. Every bot only
receives public information: its own hole cards, the board, pot, stacks,
bets, and the visible action history.

Run:  python3 holdem_sim.py --sims 100 --seed 42
"""

import argparse
import random
from collections import Counter, deque
from types import SimpleNamespace

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def rank_of(c):
    return c >> 2


def suit_of(c):
    return c & 3


def card_str(c):
    return RANKS[rank_of(c)] + SUITS[suit_of(c)]


# ---------------------------------------------------------------------------
# Hand evaluation (5 to 7 cards, best 5-card hand)
# ---------------------------------------------------------------------------

def _straight_high(desc_ranks):
    """Highest straight top-rank in a DESC-sorted list of unique ranks, else None.
    Handles the wheel (A-5) via the ace-as-low sentinel."""
    r = list(desc_ranks)
    if r and r[0] == 12:  # ace also plays low
        r.append(-1)
    run = 1
    for i in range(1, len(r)):
        if r[i] == r[i - 1] - 1:
            run += 1
            if run >= 5:
                return r[i] + 4
        else:
            run = 1
    return None


def evaluate(cards):
    """Rank a 5-7 card hand. Returns a tuple; bigger tuple = better hand.
    Categories: 8 SF, 7 quads, 6 boat, 5 flush, 4 straight, 3 trips,
    2 two pair, 1 pair, 0 high card."""
    rc = [0] * 13
    sc = [0] * 4
    for c in cards:
        rc[c >> 2] += 1
        sc[c & 3] += 1
    for s in range(4):
        if sc[s] >= 5:
            fr = sorted((c >> 2 for c in cards if (c & 3) == s), reverse=True)
            sf = _straight_high(fr)
            if sf is not None:
                return (8, sf)
            return (5, fr[0], fr[1], fr[2], fr[3], fr[4])
    quads = trips = None
    pairs = []
    uniq = []
    for r in range(12, -1, -1):
        n = rc[r]
        if n:
            uniq.append(r)
        if n == 4:
            quads = r
        elif n == 3:
            if trips is None:
                trips = r
            else:
                pairs.append(r)
        elif n == 2:
            pairs.append(r)
    if quads is not None:
        return (7, quads, max(r for r in uniq if r != quads))
    if trips is not None and pairs:
        return (6, trips, pairs[0])
    st = _straight_high(uniq)
    if st is not None:
        return (4, st)
    if trips is not None:
        ks = [r for r in uniq if r != trips]
        return (3, trips, ks[0], ks[1])
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        return (2, p1, p2, max(r for r in uniq if r != p1 and r != p2))
    if len(pairs) == 1:
        p = pairs[0]
        ks = [r for r in uniq if r != p]
        return (1, p, ks[0], ks[1], ks[2])
    return (0,) + tuple(uniq[:5])


# ---------------------------------------------------------------------------
# Shared analysis helpers (public math any player could do at the table)
# ---------------------------------------------------------------------------

def chen(hole):
    """Chen formula preflop hand score."""
    a, b = sorted((rank_of(hole[0]), rank_of(hole[1])), reverse=True)
    hi = a + 2
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if a == b:
        return max(5.0, pts * 2)
    if suit_of(hole[0]) == suit_of(hole[1]):
        pts += 2
    gap = a - b - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and a < 10:  # connected cards below queen
        pts += 1
    return pts


def equity_mc(hole, board, n_opp, rng, iters=32):
    """Monte-Carlo equity of `hole` vs n_opp random hands, board run to river."""
    known = set(hole) | set(board)
    deck = [c for c in range(52) if c not in known]
    need = 5 - len(board)
    score = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, need + 2 * n_opp)
        full = list(board) + draw[:need]
        mine = evaluate(list(hole) + full)
        best = None
        for i in range(n_opp):
            oh = draw[need + 2 * i: need + 2 * i + 2]
            ov = evaluate(oh + full)
            if best is None or ov > best:
                best = ov
        if mine > best:
            score += 1.0
        elif mine == best:
            score += 0.5
    return score / iters


def postflop_strength(hole, board):
    """Heuristic made-hand strength in [0, 1]."""
    cat = evaluate(list(hole) + list(board))
    c = cat[0]
    hr = [rank_of(x) for x in hole]
    br = [rank_of(x) for x in board]
    top = max(br)
    if c >= 7:
        return 0.99
    if c == 6:
        return 0.97
    if c == 5:
        return 0.92
    if c == 4:
        return 0.87
    if c == 3:
        return 0.90 if hr[0] == hr[1] else 0.80  # set beats bare trips
    if c == 2:
        using = (1 if cat[1] in hr else 0) + (1 if cat[2] in hr else 0)
        return 0.55 + 0.10 * using
    if c == 1:
        p = cat[1]
        if hr[0] == hr[1]:  # pocket pair
            return 0.62 if p > top else 0.38
        if p in hr:
            if p == top:
                kick = max(x for x in hr if x != p)
                return 0.55 + 0.10 * (kick / 12.0)
            if p >= sorted(br)[-2]:
                return 0.42
            return 0.30
        return 0.15  # the board is paired, we have nothing
    return 0.05 + 0.05 * (max(hr) / 12.0)


def draw_outs(hole, board):
    """Rough count of flush + straight outs."""
    cards = list(hole) + list(board)
    outs = 0
    sc = Counter(suit_of(c) for c in cards)
    for s, n in sc.items():
        if n == 4 and any(suit_of(h) == s for h in hole):
            outs += 9
            break
    rs = set(rank_of(c) for c in cards)
    if 12 in rs:
        rs = rs | {-1}
    missing = set()
    for lo in range(-1, 9):
        lack = set(range(lo, lo + 5)) - rs
        if len(lack) == 1:
            missing |= lack
    outs += 4 * min(len(missing), 2)
    return outs


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

class Strategy:
    def __init__(self, rng):
        self.rng = rng

    def new_hand(self):
        pass

    def observe(self, evt):
        pass

    def act(self, v):
        raise NotImplementedError


class AllInBot(Strategy):
    """Player 1 — 'Suflair-GPT'. The entire strategy:
        if my_turn: bet = ALL IN fi"""

    def act(self, v):
        return ("raise", v.my_street_bet + v.my_stack)


class TagBot(Strategy):
    """Tight-aggressive positional player: Chen-formula preflop ranges that
    widen with position, continuation bets, pot-odds discipline postflop."""

    def __init__(self, rng):
        super().__init__(rng)
        self.aggressor = False

    def new_hand(self):
        self.aggressor = False

    def act(self, v):
        if v.street == "preflop":
            return self._preflop(v)
        return self._postflop(v)

    def _preflop(self, v):
        ch = chen(v.hole)
        bb = v.bb
        if v.current_bet <= bb:  # unopened / limped pot
            thresh = 9.0 - 3.0 * v.pos_frac  # 9 in early seat, 6 on the button
            if ch >= thresh:
                self.aggressor = True
                limpers = sum(1 for o in v.opponents
                              if o["in_hand"] and o["street_bet"] >= bb)
                return ("raise", 3 * bb + bb * limpers)
            if v.to_call == 0:
                return ("call", 0)
            if ch >= 6 and v.to_call <= bb:
                return ("call", 0)
            return ("fold", 0)
        # facing a raise
        big = (v.to_call >= 0.4 * (v.my_stack + v.my_street_bet)
               or v.current_bet >= 10 * bb)
        if big:
            if ch >= 14:
                return ("raise", v.my_street_bet + v.my_stack)
            if ch >= 12 or (ch >= 10 and v.to_call <= 0.15 * v.my_stack):
                return ("call", 0)
            return ("fold", 0)
        if ch >= 11:
            self.aggressor = True
            return ("raise", v.current_bet * 3)
        need = v.to_call / (v.pot + v.to_call)
        if ch >= 8 or (ch >= 6.5 and need < 0.2):
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, v):
        s = postflop_strength(v.hole, v.board)
        outs = draw_outs(v.hole, v.board)
        streets_left = 2 if v.street == "flop" else (1 if v.street == "turn" else 0)
        draw_eq = min(0.45, outs * 0.02 * streets_left)
        pot = v.pot
        if v.to_call == 0:
            if s >= 0.55:
                return ("raise", v.current_bet + int(0.66 * pot))
            if self.aggressor and v.num_in_hand <= 3 and self.rng.random() < 0.6:
                return ("raise", v.current_bet + int(0.5 * pot))
            if draw_eq >= 0.15 and self.rng.random() < 0.4:
                return ("raise", v.current_bet + int(0.5 * pot))
            return ("call", 0)
        need = v.to_call / (pot + v.to_call)
        if s >= 0.85:
            return ("raise", max(v.min_raise_to, v.current_bet + int(0.8 * pot)))
        if max(s, draw_eq) >= need + 0.05 or s >= 0.62:
            if v.to_call >= 0.6 * v.my_stack and s < 0.75 and draw_eq < need:
                return ("fold", 0)
            return ("call", 0)
        return ("fold", 0)


class MonteCarloBot(Strategy):
    """Pure equity machine: estimates win probability by Monte-Carlo rollouts
    against random hands and compares it to the pot odds on every decision."""

    def act(self, v):
        n_opp = max(1, min(v.num_in_hand - 1, 3))
        eq = equity_mc(v.hole, v.board, n_opp, self.rng, iters=32)
        pot, tc = v.pot, v.to_call
        if tc == 0:
            fair = 1.0 / max(2, v.num_in_hand)
            if eq > fair + 0.15:
                return ("raise", v.current_bet + max(2 * v.bb, int(0.7 * pot)))
            if eq > fair + 0.05 and self.rng.random() < 0.5:
                return ("raise", v.current_bet + max(2 * v.bb, int(0.5 * pot)))
            return ("call", 0)
        need = tc / (pot + tc)
        margin = 0.06 if tc >= 0.5 * v.my_stack else 0.0
        if v.street != "preflop" and eq >= 0.62:
            return ("raise", max(v.min_raise_to, v.current_bet + int(0.8 * pot)))
        if v.street == "preflop" and eq >= 0.5 and v.current_bet <= 4 * v.bb:
            return ("raise", v.current_bet * 3)
        if eq >= need + margin + 0.02:
            return ("call", 0)
        return ("fold", 0)


class LagBot(Strategy):
    """Loose-aggressive: wide preflop ranges (especially suited connectors in
    position), heavy continuation betting, semi-bluffs draws, and outright
    bluffs — but only against opponents who are still able to fold."""

    def __init__(self, rng):
        super().__init__(rng)
        self.aggr = False

    def new_hand(self):
        self.aggr = False

    def act(self, v):
        r = self.rng.random()
        if v.street == "preflop":
            ch = chen(v.hole)
            suited = suit_of(v.hole[0]) == suit_of(v.hole[1])
            gap = abs(rank_of(v.hole[0]) - rank_of(v.hole[1]))
            spec = suited and 1 <= gap <= 2  # speculative suited connectors
            if v.current_bet <= v.bb:
                if ch >= 8 or (ch >= 5 and v.pos_frac > 0.4) or (spec and r < 0.8):
                    self.aggr = True
                    return ("raise", 3 * v.bb)
                if v.to_call == 0:
                    return ("call", 0)
                if ch >= 5 or spec:
                    return ("call", 0)
                return ("fold", 0)
            if v.to_call >= 0.5 * v.my_stack:  # someone is playing for stacks
                return ("call", 0) if ch >= 11 else ("fold", 0)
            if ch >= 9 and r < 0.35:
                self.aggr = True
                return ("raise", v.current_bet * 3)
            need = v.to_call / (v.pot + v.to_call)
            if ch >= 7 or (spec and need < 0.25):
                return ("call", 0)
            return ("fold", 0)
        s = postflop_strength(v.hole, v.board)
        outs = draw_outs(v.hole, v.board)
        streets_left = 2 if v.street == "flop" else (1 if v.street == "turn" else 0)
        draw_eq = min(0.45, outs * 0.02 * streets_left)
        pot = v.pot
        if v.to_call == 0:
            if s >= 0.5 or draw_eq >= 0.16:
                return ("raise", v.current_bet + int(0.75 * pot))
            if v.opp_can_fold and ((self.aggr and r < 0.65) or r < 0.18):
                return ("raise", v.current_bet + int(0.66 * pot))
            return ("call", 0)
        need = v.to_call / (pot + v.to_call)
        if s >= 0.8:
            return ("raise", max(v.min_raise_to, v.current_bet + int(pot)))
        if v.opp_can_fold and v.num_in_hand == 2 and v.street != "river" and r < 0.08:
            return ("raise", max(v.min_raise_to, v.current_bet + int(pot)))
        if max(s, draw_eq + (0.1 if v.opp_can_fold else 0)) >= need:
            if v.to_call >= 0.55 * v.my_stack and s < 0.7:
                return ("fold", 0)
            return ("call", 0)
        return ("fold", 0)


class NitBot(Strategy):
    """The rock: folds almost everything, stacks off only with premiums, and
    switches to push-or-fold when short. Survives by attrition."""

    def act(self, v):
        if v.street == "preflop":
            ch = chen(v.hole)
            short = v.my_stack <= 8 * v.bb
            if v.current_bet <= v.bb:
                if short and ch >= 8:
                    return ("raise", v.my_street_bet + v.my_stack)
                if ch >= 10:
                    return ("raise", 3 * v.bb)
                return ("call", 0) if v.to_call == 0 else ("fold", 0)
            facing_shove = v.to_call >= 0.5 * (v.my_stack + v.my_street_bet)
            if facing_shove:
                return ("call", 0) if ch >= (10 if short else 14) else ("fold", 0)
            if ch >= 14:
                return ("raise", v.current_bet * 3)
            if ch >= 11:
                return ("call", 0)
            return ("fold", 0)
        s = postflop_strength(v.hole, v.board)
        pot = v.pot
        if v.to_call == 0:
            if s >= 0.62:
                return ("raise", v.current_bet + int(0.6 * pot))
            return ("call", 0)
        need = v.to_call / (pot + v.to_call)
        if s >= 0.85:
            return ("raise", max(v.min_raise_to, v.current_bet + int(0.9 * pot)))
        if s >= 0.62 and (need < 0.4 or s >= 0.75):
            return ("call", 0)
        if s >= need + 0.15:
            return ("call", 0)
        return ("fold", 0)


class ExploitBot(Strategy):
    """Adaptive opponent modeller. Tracks every seat's public preflop behaviour
    (hands seen, raises, all-in shoves). When a seat shoves more than half of
    its hands, it is flagged as a maniac and this bot calls its all-ins with a
    dramatically wider — but still +EV — range. It also steals from tight
    tables in late position. Baseline play delegates to solid TAG logic."""

    def __init__(self, rng):
        super().__init__(rng)
        self.default = TagBot(rng)
        self.stats = {}

    def _st(self, seat):
        return self.stats.setdefault(seat, {"hands": 0, "pre_allin": 0, "pre_raise": 0})

    def new_hand(self):
        self.default.new_hand()

    def observe(self, evt):
        t = evt.get("type")
        if t == "hand_start":
            for s in evt["seats"]:
                self._st(s)["hands"] += 1
        elif t == "action" and evt.get("street") == "preflop":
            st = self._st(evt["seat"])
            if evt["action"] == "raise":
                st["pre_raise"] += 1
                if evt.get("all_in"):
                    st["pre_allin"] += 1

    def _maniacs(self):
        return {s for s, st in self.stats.items()
                if st["hands"] >= 4 and st["pre_allin"] / st["hands"] > 0.5}

    def act(self, v):
        maniacs = self._maniacs()
        if v.street == "preflop":
            ch = chen(v.hole)
            aggressors = [o for o in v.opponents
                          if o["in_hand"] and v.current_bet > v.bb
                          and o["street_bet"] == v.current_bet]
            facing_big = v.to_call > 0 and v.to_call >= 0.35 * (v.my_stack + v.my_street_bet)
            if facing_big and aggressors and all(o["seat"] in maniacs for o in aggressors):
                behind = sum(1 for o in v.opponents
                             if o["in_hand"] and not o["all_in"]
                             and o["street_bet"] < v.current_bet)
                thresh = 7.5 if behind == 0 else 9.5
                return ("call", 0) if ch >= thresh else ("fold", 0)
            if v.current_bet <= v.bb and v.pos_frac >= 0.6 and ch >= 6:
                return ("raise", 3 * v.bb)
            return self.default.act(v)
        if v.to_call > 0 and not v.opp_can_fold:
            live = [o for o in v.opponents if o["in_hand"]]
            if live and all(o["seat"] in maniacs for o in live):
                s = postflop_strength(v.hole, v.board)
                need = v.to_call / (v.pot + v.to_call)
                return ("call", 0) if (s >= need - 0.02 or s >= 0.45) else ("fold", 0)
        return self.default.act(v)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, pid, name, strategy, stack):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack


class Hand:
    def __init__(self, players, button, sb, bb, rng):
        self.players = players
        self.n = len(players)
        self.button = button
        self.sb, self.bb = sb, bb
        self.rng = rng
        self.in_hand = [True] * self.n
        self.all_in = [False] * self.n
        self.street_bet = [0] * self.n
        self.committed = [0] * self.n
        self.board = []
        self.holes = [None] * self.n
        self.start_stacks = {p: p.stack for p in players}

    def broadcast(self, evt):
        for p in self.players:
            try:
                p.strategy.observe(evt)
            except Exception:
                pass

    def pay(self, i, amt):
        amt = min(amt, self.players[i].stack)
        self.players[i].stack -= amt
        self.street_bet[i] += amt
        self.committed[i] += amt
        if self.players[i].stack == 0:
            self.all_in[i] = True
        return amt

    def make_view(self, i, street, current, last_raise):
        p = self.players[i]
        n = self.n
        opp = [{"seat": self.players[j].pid, "stack": self.players[j].stack,
                "street_bet": self.street_bet[j], "committed": self.committed[j],
                "in_hand": self.in_hand[j], "all_in": self.all_in[j]}
               for j in range(n) if j != i]
        return SimpleNamespace(
            street=street,
            hole=list(self.holes[i]),
            board=list(self.board),
            pot=sum(self.committed),
            to_call=max(0, current - self.street_bet[i]),
            current_bet=current,
            my_street_bet=self.street_bet[i],
            min_raise_to=current + last_raise,
            my_stack=p.stack,
            bb=self.bb,
            my_seat=p.pid,
            num_in_hand=sum(self.in_hand),
            pos_frac=((i - self.button - 1) % n) / (n - 1) if n > 1 else 1.0,
            opponents=opp,
            opp_can_fold=any(self.in_hand[j] and not self.all_in[j]
                             for j in range(n) if j != i),
        )

    def get_action(self, i, view):
        try:
            a = self.players[i].strategy.act(view)
            if isinstance(a, tuple) and len(a) == 2:
                return a[0], a[1]
            return (str(a), 0)
        except Exception:
            return ("fold", 0) if view.to_call > 0 else ("call", 0)

    def betting(self, street, first):
        n = self.n
        if street == "preflop":
            current = max(self.street_bet)
            last_raise = self.bb
        else:
            self.street_bet = [0] * n
            current = 0
            last_raise = self.bb

        def actionable(j):
            return self.in_hand[j] and not self.all_in[j] and self.players[j].stack > 0

        pending = deque(j for j in ((first + k) % n for k in range(n)) if actionable(j))
        guard = 0
        while pending:
            guard += 1
            if guard > 5000:
                break
            i = pending.popleft()
            if not actionable(i):
                continue
            if sum(self.in_hand) <= 1:
                break
            to_call = max(0, current - self.street_bet[i])
            others_can_act = any(self.in_hand[j] and not self.all_in[j]
                                 for j in range(n) if j != i)
            if to_call == 0 and not others_can_act:
                continue  # no one left to bet against
            view = self.make_view(i, street, current, last_raise)
            kind, amt = self.get_action(i, view)
            pid = self.players[i].pid
            if kind == "fold":
                if to_call > 0:
                    self.in_hand[i] = False
                    self.broadcast({"type": "action", "street": street, "seat": pid,
                                    "action": "fold", "all_in": False})
                    continue
                kind = "call"  # never fold for free
            if kind == "raise":
                max_to = self.street_bet[i] + self.players[i].stack
                target = min(int(amt), max_to)
                min_to = current + last_raise
                if target <= current:
                    kind = "call"
                else:
                    if target < min_to:
                        target = min(min_to, max_to)
                    self.pay(i, target - self.street_bet[i])
                    if self.street_bet[i] > current:
                        rsize = self.street_bet[i] - current
                        if rsize >= last_raise:
                            last_raise = rsize
                        current = self.street_bet[i]
                        pending = deque(j for j in ((i + k) % n for k in range(1, n))
                                        if actionable(j))
                    self.broadcast({"type": "action", "street": street, "seat": pid,
                                    "action": "raise", "to": self.street_bet[i],
                                    "all_in": self.all_in[i]})
                    continue
            # call / check
            self.pay(i, min(to_call, self.players[i].stack))
            self.broadcast({"type": "action", "street": street, "seat": pid,
                            "action": "check" if to_call == 0 else "call",
                            "to": self.street_bet[i], "all_in": self.all_in[i]})

    def play(self):
        n = self.n
        deck = list(range(52))
        self.rng.shuffle(deck)
        for k in range(n):
            i = (self.button + 1 + k) % n
            self.holes[i] = [deck.pop(), deck.pop()]
        for p in self.players:
            try:
                p.strategy.new_hand()
            except Exception:
                pass
        self.broadcast({"type": "hand_start",
                        "seats": [p.pid for p in self.players], "bb": self.bb})
        if n == 2:
            sb_i, bb_i = self.button, (self.button + 1) % n
        else:
            sb_i, bb_i = (self.button + 1) % n, (self.button + 2) % n
        self.pay(sb_i, self.sb)
        self.pay(bb_i, self.bb)
        self.betting("preflop", (bb_i + 1) % n)
        for street, k in (("flop", 3), ("turn", 1), ("river", 1)):
            if sum(self.in_hand) <= 1:
                break
            for _ in range(k):
                self.board.append(deck.pop())
            if sum(1 for j in range(n) if self.in_hand[j] and not self.all_in[j]) >= 2:
                self.betting(street, (self.button + 1) % n)
        self.resolve()

    def resolve(self):
        live = [i for i in range(self.n) if self.in_hand[i]]
        if len(live) == 1:
            self.players[live[0]].stack += sum(self.committed)
            return
        scores = {i: evaluate(self.holes[i] + self.board) for i in live}
        levels = sorted(set(self.committed[i] for i in live))
        pots = []
        prev = 0
        for lvl in levels:
            amt = sum(max(0, min(self.committed[j], lvl) - prev)
                      for j in range(self.n))
            elig = [i for i in live if self.committed[i] >= lvl]
            if amt > 0:
                pots.append([amt, elig])
            prev = lvl
        resid = sum(max(0, self.committed[j] - prev)
                    for j in range(self.n) if not self.in_hand[j])
        if resid:
            pots[-1][0] += resid
        for amt, elig in pots:
            best = max(scores[i] for i in elig)
            winners = sorted((i for i in elig if scores[i] == best),
                             key=lambda i: (i - self.button - 1) % self.n)
            share, rem = divmod(amt, len(winners))
            for k, i in enumerate(winners):
                self.players[i].stack += share + (1 if k < rem else 0)


class Tournament:
    def __init__(self, players, rng, sb0=10, hands_per_level=12, max_level=12):
        self.players = players
        self.rng = rng
        self.sb0 = sb0
        self.hands_per_level = hands_per_level
        self.max_level = max_level

    def run(self):
        total_chips = sum(p.stack for p in self.players)
        alive = list(self.players)
        button = self.rng.randrange(len(alive))
        finishes = {}
        hand_no = 0
        while len(alive) > 1 and hand_no < 1000:
            level = min(hand_no // self.hands_per_level, self.max_level)
            sb = self.sb0 * (2 ** level)
            hand = Hand(alive, button, sb, 2 * sb, self.rng)
            hand.play()
            hand_no += 1
            assert sum(p.stack for p in self.players) == total_chips, "chips leaked"
            busted = [p for p in alive if p.stack == 0]
            if busted:
                busted.sort(key=lambda p: hand.start_stacks[p])
                place = len(alive)
                for p in busted:
                    finishes[p.name] = place
                    place -= 1
                old = alive[:]
                nb = None
                for k in range(1, len(old) + 1):
                    cand = old[(button + k) % len(old)]
                    if cand.stack > 0:
                        nb = cand
                        break
                alive = [p for p in alive if p.stack > 0]
                button = alive.index(nb) if len(alive) > 1 else 0
            else:
                button = (button + 1) % len(alive)
        winner = max(alive, key=lambda p: p.stack)
        finishes[winner.name] = 1
        for p in alive:
            if p is not winner:
                finishes.setdefault(p.name, 2)
        return winner, finishes, hand_no


# ---------------------------------------------------------------------------
# Simulation driver
# ---------------------------------------------------------------------------

LINEUP = [
    ("P1 Suflair-GPT [all-in]", AllInBot),
    ("P2 TAG-Shark", TagBot),
    ("P3 MonteCarlo-Oracle", MonteCarloBot),
    ("P4 LAG-Hurricane", LagBot),
    ("P5 Granite-Nit", NitBot),
    ("P6 Adaptive-Vulture", ExploitBot),
]


def selftest():
    def c(s):
        return RANKS.index(s[0]) * 4 + SUITS.index(s[1])

    def hand(txt):
        return [c(x) for x in txt.split()]

    assert evaluate(hand("Ah Kh Qh Jh Th 2c 3d"))[0] == 8
    assert evaluate(hand("Ah Ad Ac As Th 2c 3d"))[0] == 7
    w = evaluate(hand("Ah 2d 3c 4s 5h 9c Kd"))
    assert w[0] == 4 and w[1] == 3  # wheel, five-high
    fh = evaluate(hand("Ah Ad Ks Kd Kc 2c 3d"))
    assert fh == (6, 11, 12)  # kings full of aces
    assert evaluate(hand("Ah 9h 5h 3h 2h Kd Qc"))[0] == 5
    assert evaluate(hand("Ah Ad Kc Ks Qh 2c 3d"))[0] == 2
    assert evaluate(hand("2h 7d 9c Js Qh Kd 3h"))[0] == 0
    assert (evaluate(hand("Ah Kd Qc Js Th 2c 2d"))
            > evaluate(hand("9h 8d 7c 6s 5h Ac Ad")))
    assert chen(hand("Ah Ad")) == 20
    assert chen(hand("Ah Kh")) == 12


def run_sims(n_sims, seed, start_stack=1000):
    winners = Counter()
    places = {name: Counter() for name, _ in LINEUP}
    hands_total = 0
    for t in range(n_sims):
        rng = random.Random(seed * 1_000_003 + t)
        players = [Player(k + 1, name, cls(random.Random(rng.randrange(1 << 30))),
                          start_stack)
                   for k, (name, cls) in enumerate(LINEUP)]
        winner, finishes, nh = Tournament(players, rng).run()
        winners[winner.name] += 1
        for nm, pl in finishes.items():
            places[nm][pl] += 1
        hands_total += nh
        if (t + 1) % 10 == 0:
            print(f"  ... {t + 1}/{n_sims} tournaments done")
    return winners, places, hands_total


def histogram(winners, n_sims, width=50):
    mx = max(winners.values()) if winners else 1
    lines = []
    for name, _ in LINEUP:
        w = winners.get(name, 0)
        bar = "█" * (round(w / mx * width) if w else 0)
        lines.append(f"{name:<26} |{bar:<{width}}| {w:3d}  ({100.0 * w / n_sims:.0f}%)")
    return "\n".join(lines)


def finish_table(places, n_sims):
    hdr = "player                      " + "".join(f"{p:>6}" for p in
                                                   ["1st", "2nd", "3rd", "4th", "5th", "6th"]) + "   avg"
    lines = [hdr]
    for name, _ in LINEUP:
        row = places[name]
        avg = sum(pl * ct for pl, ct in row.items()) / max(1, sum(row.values()))
        lines.append(f"{name:<28}" + "".join(f"{row.get(p, 0):>6}" for p in range(1, 7))
                     + f"  {avg:.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="6-max NLHE tournament simulator")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=1000)
    args = ap.parse_args()

    selftest()
    print(f"Running {args.sims} tournaments (seed={args.seed}, "
          f"start stack={args.stack}, blinds 10/20 doubling every 12 hands)\n")
    winners, places, hands_total = run_sims(args.sims, args.seed, args.stack)

    print("\n=== WINNER WINNER CHICKEN DINNER — tournament wins over "
          f"{args.sims} sims ===\n")
    print(histogram(winners, args.sims))
    print("\n=== Finishing-position distribution ===\n")
    print(finish_table(places, args.sims))
    print(f"\nTotal hands dealt: {hands_total} "
          f"(avg {hands_total / args.sims:.1f} per tournament)")


if __name__ == "__main__":
    main()
