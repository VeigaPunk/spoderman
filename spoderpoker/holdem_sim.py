#!/usr/bin/env python3
"""
SPODERPOKER — No-Limit Texas Hold'em tournament simulator.

Six players sit down with equal stacks and play freezeout tournaments
(escalating blinds) until one player owns every chip. Nobody knows anybody
else's strategy — they only see public actions, like at a real table.

  Player 1  "ALL-IN ANDY"     : if my_turn: bet = ALL IN; fi
  Player 2  "THE PROFESSOR"   : tight-aggressive, Chen formula, position-aware
  Player 3  "LA PISTOLERA"    : loose-aggressive, c-bets, semi-bluffs, pressure
  Player 4  "THE ROCK"        : ultra-tight nit, premiums only, traps
  Player 5  "THE ACTUARY"     : pot-odds/EV machine, calls only when priced in
  Player 6  "THE CHAMELEON"   : adaptive exploiter, models opponents live

Run:  python3 holdem_sim.py --sims 100 --seed 42
"""

import argparse
import json
import random
from collections import Counter, defaultdict
from itertools import combinations

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}

def new_deck():
    return [(RANK_VAL[r], s) for r in RANKS for s in SUITS]

def card_str(c):
    return RANKS[c[0] - 2] + c[1]

HAND_NAMES = ["high card", "pair", "two pair", "trips", "straight",
              "flush", "full house", "quads", "straight flush"]

def evaluate5(cards):
    """Rank a 5-card hand. Returns a comparable tuple (category, tiebreaks...)."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    distinct = sorted(counts, reverse=True)

    straight_high = 0
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_high = distinct[0]
        elif distinct == [14, 5, 4, 3, 2]:  # wheel
            straight_high = 5

    if flush and straight_high:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        kickers = [r for r in ranks if r != groups[0][0]]
        return (3, groups[0][0], *kickers)
    if groups[0][1] == 2 and groups[1][1] == 2:
        kicker = [r for r in ranks if counts[r] == 1][0]
        return (2, groups[0][0], groups[1][0], kicker)
    if groups[0][1] == 2:
        kickers = [r for r in ranks if r != groups[0][0]]
        return (1, groups[0][0], *kickers)
    return (0, *ranks)

def evaluate_best(cards):
    """Best 5-card hand out of 5..7 cards."""
    if len(cards) == 5:
        return evaluate5(cards)
    return max(evaluate5(c) for c in combinations(cards, 5))

# ---------------------------------------------------------------------------
# Hand-strength heuristics (fast, no Monte Carlo)
# ---------------------------------------------------------------------------

def chen_score(hole):
    """Chen formula for preflop hand strength (max 20)."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if s1 == s2:
        pts += 2
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        pts += 1
    return pts

def preflop_strength(hole):
    """Normalize Chen score to ~0..1."""
    return max(0.0, min(1.0, (chen_score(hole) + 1.5) / 21.5))

def _draw_bonus(hole, board):
    """Extra strength for flush/straight draws (only before the river)."""
    if len(board) >= 5:
        return 0.0
    cards = hole + board
    scale = 1.0 if len(board) == 3 else 0.5
    bonus = 0.0
    suit_counts = Counter(c[1] for c in cards)
    best_suit = max(suit_counts.values())
    if best_suit == 4 and any(c[1] for c in hole if suit_counts[c[1]] == 4):
        bonus += 0.18 * scale
    ranks = set(c[0] for c in cards)
    if 14 in ranks:
        ranks.add(1)
    outs = 0
    for high in range(5, 15):
        window = set(range(high - 4, high + 1))
        missing = window - ranks
        if len(missing) == 1:
            outs = max(outs, 2)  # one card completes a straight
        elif len(missing) == 0:
            outs = 0
            break
    if outs:
        bonus += 0.13 * scale
    return bonus

def postflop_strength(hole, board):
    """Heuristic hand strength 0..1 for hole+board (3-5 board cards)."""
    my = evaluate_best(hole + board)
    cat = my[0]
    base = [0.10, 0.35, 0.60, 0.72, 0.80, 0.85, 0.93, 0.98, 1.00][cat]

    # Rank quality inside the category (e.g. top pair vs bottom pair).
    if cat in (1, 2, 3):
        board_ranks = [c[0] for c in board]
        top_board = max(board_ranks)
        pair_rank = my[1]
        if pair_rank >= top_board:
            base += 0.10
        elif pair_rank < min(board_ranks):
            base -= 0.12
        # kicker sweetener
        base += (max(h[0] for h in hole) - 8) * 0.004

    # Discount hands the board makes for everyone (e.g. board pair, board flush).
    if len(board) >= 5:
        board_eval = evaluate5(board)
        if my <= board_eval:
            base = 0.15
    elif len(board) >= 3:
        board_counts = Counter(c[0] for c in board)
        if cat == 1 and max(board_counts.values()) >= 2:
            base -= 0.15  # our "pair" is on the board
    return max(0.02, min(1.0, base + _draw_bonus(hole, board)))

def strength(hole, board):
    return preflop_strength(hole) if not board else postflop_strength(hole, board)

def approx_win_prob(strength_val, n_opponents):
    """Very rough: treat strength as a percentile vs one opponent."""
    return max(0.01, strength_val ** max(1, n_opponents))

# ---------------------------------------------------------------------------
# Strategy framework
# ---------------------------------------------------------------------------

FOLD, CHECK, CALL, RAISE = "fold", "check", "call", "raise"

class Strategy:
    """Sees only its own cards + public info. Returns (action, raise_to)."""
    name = "base"
    def new_hand(self):
        pass
    def observe(self, event):
        """Public table events: (hand_no, seat, action, amount, street)."""
        pass
    def act(self, view):
        raise NotImplementedError

def _clamped_raise(view, target_to):
    """Helper: build a legal raise-to amount (engine clamps too)."""
    max_to = view["my_stack"] + view["my_street_commit"]
    return (RAISE, min(max(target_to, view["min_raise_to"]), max_to))


class AllInAndy(Strategy):
    """if my_turn: bet = ALL IN; fi"""
    name = "All-In Andy"
    def act(self, view):
        return _clamped_raise(view, 10 ** 9)


class TheProfessor(Strategy):
    """Tight-aggressive. Chen-formula preflop with positional awareness,
    value-bets made hands, respects big aggression without the goods."""
    name = "The Professor"
    def act(self, view):
        s = strength(view["hole"], view["board"])
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        rel_pos = view["rel_position"]          # 0 = early ... 1 = button
        rng = view["rng"]
        n_opp = view["n_active"] - 1
        eff_stack = view["my_stack"]

        if not view["board"]:
            open_thresh = 0.52 - 0.14 * rel_pos     # looser on the button
            facing_shove = to_call > eff_stack * 0.6
            if facing_shove:
                return (CALL, 0) if s > 0.80 else (FOLD, 0)
            if s > 0.85:
                return _clamped_raise(view, view["current_bet"] * 3 + pot // 2)
            if s > open_thresh:
                if view["current_bet"] <= bb:
                    return _clamped_raise(view, bb * 3)
                if to_call <= eff_stack * 0.12:
                    return (CALL, 0)
            if to_call == 0:
                return (CHECK, 0)
            return (FOLD, 0)

        win = approx_win_prob(s, n_opp)
        if win > 0.75:
            return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.75), bb * 2))
        if win > 0.55:
            if to_call == 0:
                return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.6), bb * 2))
            if to_call <= pot:
                return (CALL, 0)
            return (FOLD, 0)
        if to_call == 0:
            return (CHECK, 0)
        pot_odds = to_call / (pot + to_call)
        if win > pot_odds + 0.06:
            return (CALL, 0)
        if s > 0.5 and to_call <= bb * 2 and rng.random() < 0.3:
            return (CALL, 0)  # occasional float in position
        return (FOLD, 0)


class LaPistolera(Strategy):
    """Loose-aggressive gunslinger. Opens wide, continuation-bets relentlessly,
    semi-bluffs draws, and randomizes bluffs so she can't be read."""
    name = "La Pistolera"
    def new_hand(self):
        self.was_preflop_aggressor = False
    def act(self, view):
        s = strength(view["hole"], view["board"])
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        rng = view["rng"]
        n_opp = view["n_active"] - 1

        if not view["board"]:
            facing_shove = to_call > view["my_stack"] * 0.5
            if facing_shove:
                return (CALL, 0) if s > 0.72 else (FOLD, 0)
            if s > 0.42 or rng.random() < 0.16:
                self.was_preflop_aggressor = True
                return _clamped_raise(view, max(view["current_bet"] * 3, bb * 3))
            if to_call <= bb and s > 0.30:
                return (CALL, 0)
            return (CHECK, 0) if to_call == 0 else (FOLD, 0)

        win = approx_win_prob(s, n_opp)
        has_draw = _draw_bonus(view["hole"], view["board"]) > 0.05
        # continuation bet / barrel
        if to_call == 0:
            if win > 0.5 or has_draw or (self.was_preflop_aggressor and rng.random() < 0.6):
                return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.66), bb * 2))
            return (CHECK, 0)
        pot_odds = to_call / (pot + to_call)
        if win > 0.7:
            return _clamped_raise(view, view["current_bet"] + to_call + int(pot * 0.8))
        if has_draw and to_call < pot * 0.8:
            if rng.random() < 0.35:
                return _clamped_raise(view, view["current_bet"] + to_call + int(pot * 0.7))
            return (CALL, 0)
        if win > pot_odds:
            return (CALL, 0)
        if rng.random() < 0.08 and to_call < pot * 0.5:
            return (CALL, 0)  # spite call, keeps her unpredictable
        return (FOLD, 0)


class TheRock(Strategy):
    """Ultra-tight nit. Folds almost everything, only commits with monsters,
    and min-plays medium hands to keep pots small."""
    name = "The Rock"
    def act(self, view):
        s = strength(view["hole"], view["board"])
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        n_opp = view["n_active"] - 1

        if not view["board"]:
            if s > 0.88:  # QQ+/AK territory
                return _clamped_raise(view, max(view["current_bet"] * 3, bb * 4))
            if s > 0.70 and to_call <= bb * 3:
                return (CALL, 0)
            # short-stack survival: shove premium-ish when blinds eat him
            if view["my_stack"] < bb * 6 and s > 0.62:
                return _clamped_raise(view, 10 ** 9)
            return (CHECK, 0) if to_call == 0 else (FOLD, 0)

        win = approx_win_prob(s, n_opp)
        if win > 0.85:
            # trap: small raise to keep prey in the web
            return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.4), bb))
        if win > 0.6:
            if to_call == 0:
                return (CHECK, 0)  # pot control
            if to_call <= pot * 0.6:
                return (CALL, 0)
            return (FOLD, 0)
        if to_call == 0:
            return (CHECK, 0)
        return (FOLD, 0)


class TheActuary(Strategy):
    """Pure pot-odds machine. Estimates equity, compares to price, and only
    puts chips in when the expected value is positive. Bets for value using
    a target of getting worse hands to pay."""
    name = "The Actuary"
    def act(self, view):
        s = strength(view["hole"], view["board"])
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        n_opp = view["n_active"] - 1
        win = approx_win_prob(s, n_opp) if view["board"] else s

        if to_call > 0:
            pot_odds = to_call / (pot + to_call)
            edge = win - pot_odds
            if edge > 0.25 and view["board"]:
                return _clamped_raise(view, view["current_bet"] + to_call + int(pot * 0.75))
            if edge > 0.28 and not view["board"]:
                return _clamped_raise(view, max(view["current_bet"] * 3, bb * 3))
            if edge > 0.0:
                return (CALL, 0)
            return (FOLD, 0)

        # nobody has bet: bet when EV of a value bet is positive
        if view["board"]:
            if win > 0.62:
                return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.6), bb * 2))
            return (CHECK, 0)
        if s > 0.60:
            return _clamped_raise(view, bb * 3)
        return (CHECK, 0)


class TheChameleon(Strategy):
    """Adaptive exploiter. Builds a live profile of every seat from public
    actions only (VPIP, aggression, shove frequency) and counter-adjusts:
    tightens up against maniacs, steals from nits, snap-calls habitual
    shovers with a strong-enough range."""
    name = "The Chameleon"
    def __init__(self):
        self.stats = defaultdict(lambda: {"hands": 0, "vpip": 0, "raises": 0,
                                          "shoves": 0, "acts": 0})
        self._seen_this_hand = set()
    def new_hand(self):
        self._seen_this_hand = set()
        for st in self.stats.values():
            st["hands"] += 1
    def observe(self, event):
        seat, action, amount, street, is_allin = (event["seat"], event["action"],
                                                  event["amount"], event["street"],
                                                  event["all_in"])
        st = self.stats[seat]
        st["acts"] += 1
        if action in (CALL, RAISE) and street == "preflop" and seat not in self._seen_this_hand:
            st["vpip"] += 1
            self._seen_this_hand.add(seat)
        if action == RAISE:
            st["raises"] += 1
            if is_allin:
                st["shoves"] += 1
    def _table_profile(self, view):
        maniacs, nits, shover_present = 0, 0, False
        for seat in view["active_seats"]:
            if seat == view["my_seat"]:
                continue
            st = self.stats[seat]
            if st["hands"] < 8:
                continue
            vpip = st["vpip"] / max(1, st["hands"])
            aggr = st["raises"] / max(1, st["acts"])
            shove_rate = st["shoves"] / max(1, st["hands"])
            if shove_rate > 0.5:
                shover_present = True
            if vpip > 0.5 and aggr > 0.4:
                maniacs += 1
            elif vpip < 0.18:
                nits += 1
        return maniacs, nits, shover_present
    def act(self, view):
        s = strength(view["hole"], view["board"])
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        rng = view["rng"]
        n_opp = view["n_active"] - 1
        maniacs, nits, shover_present = self._table_profile(view)

        call_thresh = 0.55
        steal_thresh = 0.45
        if maniacs or shover_present:
            # vs maniacs: stop bluffing, widen call-down range for value
            steal_thresh = 0.70
            call_thresh = 0.62
        if nits and not maniacs:
            steal_thresh = 0.35  # rob the rocks blind

        if not view["board"]:
            facing_shove = to_call > view["my_stack"] * 0.5
            if facing_shove:
                # a habitual shover's range is any-two: call much wider
                need = 0.58 if shover_present else 0.80
                return (CALL, 0) if s > need else (FOLD, 0)
            if s > 0.86:
                return _clamped_raise(view, max(view["current_bet"] * 3, bb * 4))
            if to_call == 0 or view["current_bet"] <= bb:
                if s > steal_thresh or (nits and rng.random() < 0.18):
                    return _clamped_raise(view, bb * 3)
            if to_call <= bb * 2 and s > 0.5:
                return (CALL, 0)
            return (CHECK, 0) if to_call == 0 else (FOLD, 0)

        win = approx_win_prob(s, n_opp)
        if to_call == 0:
            if win > call_thresh:
                return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.6), bb * 2))
            if nits and not maniacs and rng.random() < 0.30:
                return _clamped_raise(view, view["current_bet"] + max(int(pot * 0.5), bb * 2))
            return (CHECK, 0)
        pot_odds = to_call / (pot + to_call)
        need = pot_odds + (0.02 if shover_present else 0.08)
        if win > 0.78:
            return _clamped_raise(view, view["current_bet"] + to_call + int(pot * 0.8))
        if win > need:
            return (CALL, 0)
        return (FOLD, 0)

# ---------------------------------------------------------------------------
# Table engine
# ---------------------------------------------------------------------------

class Seat:
    def __init__(self, seat_no, name, strategy, stack):
        self.no = seat_no
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.reset_hand()
    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.street_commit = 0
        self.total_commit = 0
    @property
    def busted(self):
        return self.stack <= 0 and self.total_commit == 0

class Table:
    def __init__(self, seats, rng, start_bb=10, level_len=15, verbose=False):
        self.seats = seats
        self.rng = rng
        self.start_bb = start_bb
        self.level_len = level_len
        self.button = 0
        self.hand_no = 0
        self.verbose = verbose

    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def blinds(self):
        level = self.hand_no // self.level_len
        bb = self.start_bb * (2 ** min(level, 12))
        return bb // 2, bb

    def _broadcast(self, seat, action, amount, street, all_in):
        event = {"hand": self.hand_no, "seat": seat.no, "action": action,
                 "amount": amount, "street": street, "all_in": all_in}
        for s in self.alive():
            s.strategy.observe(event)

    def _post(self, seat, amount):
        amount = min(amount, seat.stack)
        seat.stack -= amount
        seat.street_commit += amount
        seat.total_commit += amount
        if seat.stack == 0:
            seat.all_in = True
        return amount

    def play_hand(self):
        self.hand_no += 1
        players = self.alive()
        for s in players:
            s.reset_hand()
            s.strategy.new_hand()

        sb_amt, bb_amt = self.blinds()
        deck = new_deck()
        self.rng.shuffle(deck)

        n = len(players)
        # rotate button among alive players
        order = players[self.button % n:] + players[:self.button % n]
        self.button += 1
        if n == 2:
            sb_seat, bb_seat = order[0], order[1]      # heads-up: button is SB
        else:
            sb_seat, bb_seat = order[1], order[2]
        self._post(sb_seat, sb_amt)
        self._post(bb_seat, bb_amt)

        for s in order:
            s.hole = [deck.pop(), deck.pop()]

        board = []
        current_bet = bb_amt
        min_raise = bb_amt

        def bet_round(street, first_idx, current_bet, min_raise):
            live = [s for s in order if not s.folded]
            if sum(1 for s in live if not s.all_in) <= 1:
                # nobody (or one player) can act; but they may still need to call?
                pass
            idx = first_idx
            acted = set()
            while True:
                live_now = [s for s in order if not s.folded]
                if len(live_now) == 1:
                    return current_bet, min_raise
                can_act = [s for s in live_now if not s.all_in]
                if all(s in acted and s.street_commit == current_bet for s in can_act):
                    return current_bet, min_raise
                if not can_act:
                    return current_bet, min_raise
                seat = order[idx % len(order)]
                idx += 1
                if seat.folded or seat.all_in:
                    continue
                if seat in acted and seat.street_commit == current_bet:
                    continue
                to_call = current_bet - seat.street_commit
                pot = sum(s.total_commit for s in order)
                view = {
                    "hole": seat.hole, "board": list(board), "street": street,
                    "pot": pot, "to_call": to_call, "current_bet": current_bet,
                    "min_raise_to": current_bet + min_raise,
                    "my_stack": seat.stack, "my_street_commit": seat.street_commit,
                    "my_seat": seat.no, "big_blind": bb_amt,
                    "n_active": len(live_now),
                    "active_seats": [s.no for s in live_now],
                    # 0 = small blind (worst) ... 1 = button (best)
                    "rel_position": ((order.index(seat) - 1) % len(order)) / max(1, len(order) - 1),
                    "stacks": {s.no: s.stack for s in live_now},
                    "hand_no": self.hand_no, "rng": self.rng,
                }
                action, raise_to = seat.strategy.act(view)

                # validate / clamp
                if action == RAISE:
                    max_to = seat.stack + seat.street_commit
                    raise_to = min(raise_to, max_to)
                    if raise_to <= current_bet:            # can't actually raise
                        action = CALL if to_call > 0 else CHECK
                    elif raise_to < current_bet + min_raise and raise_to < max_to:
                        raise_to = min(current_bet + min_raise, max_to)
                if action == CHECK and to_call > 0:
                    action = FOLD
                if action == CALL and to_call == 0:
                    action = CHECK

                if action == FOLD:
                    seat.folded = True
                    self._broadcast(seat, FOLD, 0, street, False)
                elif action == CHECK:
                    acted.add(seat)
                    self._broadcast(seat, CHECK, 0, street, False)
                elif action == CALL:
                    self._post(seat, to_call)
                    acted.add(seat)
                    self._broadcast(seat, CALL, to_call, street, seat.all_in)
                else:  # RAISE
                    self._post(seat, raise_to - seat.street_commit)
                    actual_to = seat.street_commit
                    if actual_to > current_bet:
                        min_raise = max(min_raise, actual_to - current_bet)
                        current_bet = actual_to
                        acted = {seat}
                    else:
                        acted.add(seat)
                    self._broadcast(seat, RAISE, actual_to, street, seat.all_in)

        # preflop: first to act is after the BB
        bb_index = order.index(bb_seat)
        current_bet, min_raise = bet_round("preflop", bb_index + 1, current_bet, min_raise)

        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if sum(1 for s in order if not s.folded) <= 1:
                break
            deck.pop()  # burn, for the culture
            board.extend(deck.pop() for _ in range(n_cards))
            for s in order:
                s.street_commit = 0
            # postflop: SB acts first (heads-up: the BB, i.e. non-button) — index 1 either way
            current_bet, min_raise = bet_round(street, 1, 0, bb_amt)

        # run out the board if betting is over but showdown remains
        live = [s for s in order if not s.folded]
        while len(live) > 1 and len(board) < 5:
            deck.pop()
            board.append(deck.pop())

        self._settle(order, board)

    def _settle(self, order, board):
        live = [s for s in order if not s.folded]
        contribs = {s: s.total_commit for s in order}
        if len(live) == 1:
            live[0].stack += sum(contribs.values())
            return
        scores = {s: evaluate_best(s.hole + board) for s in live}
        # side pots by contribution level
        while any(v > 0 for v in contribs.values()):
            positive = [s for s, v in contribs.items() if v > 0]
            level = min(contribs[s] for s in positive)
            pot = 0
            for s in positive:
                pot += level
                contribs[s] -= level
            eligible = [s for s in positive if not s.folded]
            if not eligible:
                # folded chips only: goes to overall best hand still live
                eligible = live
            best = max(scores[s] for s in eligible if s in scores)
            winners = [s for s in eligible if scores.get(s) == best]
            share, odd = divmod(pot, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < odd else 0)

    def run_tournament(self, max_hands=3000):
        while len(self.alive()) > 1 and self.hand_no < max_hands:
            self.play_hand()
        alive = self.alive()
        champion = max(alive, key=lambda s: s.stack)
        return champion, self.hand_no

# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

LINEUP = [
    ("Player 1 — All-In Andy", AllInAndy),
    ("Player 2 — The Professor", TheProfessor),
    ("Player 3 — La Pistolera", LaPistolera),
    ("Player 4 — The Rock", TheRock),
    ("Player 5 — The Actuary", TheActuary),
    ("Player 6 — The Chameleon", TheChameleon),
]

def run_sims(n_sims=100, seed=42, start_stack=1000, verbose=False):
    master_rng = random.Random(seed)
    wins = Counter()
    hand_counts = []
    for sim in range(n_sims):
        rng = random.Random(master_rng.getrandbits(64))
        seats = [Seat(i + 1, name, cls(), start_stack)
                 for i, (name, cls) in enumerate(LINEUP)]
        table = Table(seats, rng)
        champ, hands = table.run_tournament()
        wins[champ.name] += 1
        hand_counts.append(hands)
        if verbose:
            print(f"  sim {sim + 1:3d}: {champ.name} wins after {hands} hands")
    return wins, hand_counts

def histogram(wins, n_sims, width=50):
    lines = []
    lines.append("")
    lines.append("=" * 74)
    lines.append("  WINNER WINNER CHICKEN DINNER — championships per player "
                 f"({n_sims} tournaments)")
    lines.append("=" * 74)
    top = max(wins.values()) if wins else 1
    for name, _ in LINEUP:
        count = wins.get(name, 0)
        bar = "█" * max(1 if count else 0, round(count / top * width))
        lines.append(f"  {name:<28} {count:3d}  {bar}")
    lines.append("=" * 74)
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="Spoderpoker Hold'em simulator")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stack", type=int, default=1000)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json-out", default=None, help="write results JSON here")
    args = ap.parse_args()

    print(f"Dealing {args.sims} freezeout tournaments "
          f"(6 players, {args.stack} chips each, seed={args.seed})...")
    wins, hand_counts = run_sims(args.sims, args.seed, args.stack, args.verbose)
    print(histogram(wins, args.sims))
    avg_hands = sum(hand_counts) / len(hand_counts)
    print(f"  avg tournament length: {avg_hands:.0f} hands")

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"sims": args.sims, "seed": args.seed,
                       "wins": dict(wins),
                       "avg_hands": avg_hands}, f, indent=2)
        print(f"  results written to {args.json_out}")

if __name__ == "__main__":
    main()
