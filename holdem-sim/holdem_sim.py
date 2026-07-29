#!/usr/bin/env python3
"""
Texas Hold'em tournament simulator — 6 players, winner-take-all.

Player 1 runs the simplest possible strategy:

    if my_turn:
        bet = ALL IN
    fi

Players 2..6 run five elaborate strategies (tight-aggressive, nit,
loose-aggressive, pot-odds mathematician, tricky/balanced). No strategy can
see any other player's hole cards or knows which algorithm anyone else is
running — every decision is made only from public information (board, pot,
stacks, bets) plus the player's own hole cards.

Usage:
    python3 holdem_sim.py [--sims 100] [--seed 42]
"""

import argparse
import random
from collections import deque
from itertools import combinations

# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_rank(c):
    return c >> 2  # 0..12  (0 = deuce, 12 = ace)


def card_suit(c):
    return c & 3


def card_str(c):
    return RANKS[card_rank(c)] + SUITS[card_suit(c)]


def new_deck(rng):
    deck = list(range(52))
    rng.shuffle(deck)
    return deck


# ---------------------------------------------------------------------------
# Hand evaluation: best 5 out of up to 7 cards.
# Returns a comparable tuple; higher tuple = better hand.
# Categories: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
#             3 trips, 2 two pair, 1 pair, 0 high card.
# ---------------------------------------------------------------------------
def eval5(cards):
    ranks = sorted((card_rank(c) for c in cards), reverse=True)
    suits = [card_suit(c) for c in cards]
    flush = len(set(suits)) == 1

    # straight detection (wheel: A-2-3-4-5)
    straight_high = -1
    uniq = sorted(set(ranks), reverse=True)
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [12, 3, 2, 1, 0]:  # wheel
            straight_high = 3

    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    # sort by (count, rank) desc -> kicker ordering
    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = tuple(kv[1] for kv in by_count)
    order = tuple(kv[0] for kv in by_count)

    if flush and straight_high >= 0:
        return (8, straight_high)
    if shape[0] == 4:
        return (7,) + order
    if shape[0] == 3 and shape[1] == 2:
        return (6,) + order
    if flush:
        return (5,) + tuple(ranks)
    if straight_high >= 0:
        return (4, straight_high)
    if shape[0] == 3:
        return (3,) + order
    if shape[0] == 2 and shape[1] == 2:
        return (2,) + order
    if shape[0] == 2:
        return (1,) + order
    return (0,) + tuple(ranks)


def eval_best(cards):
    """Best 5-card hand from 5, 6 or 7 cards."""
    if len(cards) == 5:
        return eval5(cards)
    return max(eval5(c) for c in combinations(cards, 5))


# ---------------------------------------------------------------------------
# Shared poker math helpers (public info + own cards only)
# ---------------------------------------------------------------------------
def chen_score(hole):
    """Bill Chen's preflop hand-strength formula."""
    a, b = sorted(hole, key=card_rank, reverse=True)
    ra, rb = card_rank(a), card_rank(b)
    high_pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(ra, (ra + 2) / 2.0)
    if ra == rb:
        return max(5.0, high_pts * 2)
    pts = high_pts
    if card_suit(a) == card_suit(b):
        pts += 2
    gap = ra - rb - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and ra < 10:  # straight-making bonus for low connectors
        pts += 1
    return pts


def board_pair_rank_info(hole, board):
    """Classify made-hand strength on a flop/turn/river. Returns dict."""
    full = list(hole) + list(board)
    val = eval_best(full)
    cat = val[0]
    board_ranks = sorted((card_rank(c) for c in board), reverse=True)
    hr = [card_rank(c) for c in hole]
    info = {
        "value": val,
        "category": cat,
        "top_pair": False,
        "overpair": False,
        "pair_uses_hole": False,
    }
    if cat == 1:
        pair_rank = val[1]
        info["pair_uses_hole"] = pair_rank in hr
        info["top_pair"] = info["pair_uses_hole"] and pair_rank == board_ranks[0]
        info["overpair"] = hr[0] == hr[1] and hr[0] > board_ranks[0]
    return info


def draw_outs(hole, board):
    """Detect flush draws / straight draws (only meaningful pre-river)."""
    cards = list(hole) + list(board)
    flush_draw = False
    suit_counts = {}
    for c in cards:
        suit_counts[card_suit(c)] = suit_counts.get(card_suit(c), 0) + 1
    for s, n in suit_counts.items():
        if n == 4 and any(card_suit(h) == s for h in hole):
            flush_draw = True
    ranks = set(card_rank(c) for c in cards)
    if 12 in ranks:
        ranks.add(-1)  # ace plays low for the wheel
    oesd = gutshot = False
    for low in range(-1, 9):
        window = [r for r in range(low, low + 5) if r in ranks]
        need = 5 - len(window)
        if need == 1:
            missing = [r for r in range(low, low + 5) if r not in ranks][0]
            if missing in (low, low + 4):
                oesd = True
            else:
                gutshot = True
    return flush_draw, oesd, gutshot


def made_strength(hole, board):
    """Heuristic 0..1 strength of the current made hand + draw equity."""
    info = board_pair_rank_info(hole, board)
    cat = info["category"]
    if cat >= 4:
        s = 0.95
    elif cat == 3:
        s = 0.85
    elif cat == 2:
        s = 0.72
    elif cat == 1:
        if info["overpair"]:
            s = 0.68
        elif info["top_pair"]:
            s = 0.60
        elif info["pair_uses_hole"]:
            s = 0.42
        else:
            s = 0.30  # board pair only
    else:
        s = 0.18 if max(card_rank(c) for c in hole) == 12 else 0.10
    if len(board) < 5:
        fd, oesd, gs = draw_outs(hole, board)
        if fd:
            s += 0.18
        if oesd:
            s += 0.14
        elif gs:
            s += 0.05
    return min(s, 0.99)


def monte_carlo_equity(hole, board, n_opps, rng, trials=60):
    """Estimate win equity vs n_opps random hands. Uses only public info."""
    known = set(hole) | set(board)
    remaining = [c for c in range(52) if c not in known]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(trials):
        sample = rng.sample(remaining, need_board + 2 * n_opps)
        sim_board = list(board) + sample[:need_board]
        mine = eval_best(list(hole) + sim_board)
        best_opp = None
        for i in range(n_opps):
            oh = sample[need_board + 2 * i : need_board + 2 * i + 2]
            v = eval_best(oh + sim_board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / trials


# ---------------------------------------------------------------------------
# Strategy interface.
#
# obs dict (PUBLIC info + own hole cards only — no opponent cards, no
# opponent strategy identities):
#   hole, board, street, pot, to_call, current_bet, min_raise_to,
#   my_bet_this_round, stack, big_blind, num_live, n_opps,
#   players_behind, i_was_last_aggressor, opp_stacks, rng
#
# Return one of: "fold" | "check" | "call" | "allin" | ("raise", amount_to)
# ---------------------------------------------------------------------------
class Strategy:
    name = "?"

    def act(self, obs):
        raise NotImplementedError


class AllInManiac(Strategy):
    """Player 1's entire algorithm:

        if my_turn
        then bet = All in
        fi
    """

    name = "All-In Bot"

    def act(self, obs):
        return "allin"


class TagShark(Strategy):
    """Tight-aggressive: Chen-formula preflop ranges with position awareness,
    continuation bets, value bets by hand class, pot-odds driven calls and
    semi-bluffs with strong draws."""

    name = "TAG Shark"

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]
        stack = obs["stack"]

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            late = obs["players_behind"] <= 1
            facing_raise = obs["current_bet"] > bb
            if score >= 10:
                target = max(obs["min_raise_to"], int(obs["current_bet"] * 2.5) or 3 * bb)
                return ("raise", target)
            if score >= 8:
                if facing_raise:
                    return "call" if to_call <= stack * 0.15 else "fold"
                return ("raise", 3 * bb)
            if score >= 6 and late and not facing_raise:
                return ("raise", int(2.5 * bb))
            if score >= 6 and to_call <= bb:
                return "call"
            return "check" if to_call == 0 else "fold"

        s = made_strength(obs["hole"], obs["board"])
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
        if to_call == 0:
            if s >= 0.60:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.66), bb))
            if obs["i_was_last_aggressor"] and rng.random() < 0.6:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.5), bb))
            return "check"
        if s >= 0.80:
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + pot))
        if s >= 0.55:
            return "call" if to_call <= pot else ("fold" if s < 0.6 else "call")
        fd, oesd, _ = draw_outs(obs["hole"], obs["board"])
        if (fd or oesd) and obs["street"] != "river":
            if rng.random() < 0.35 and to_call < pot * 0.6:
                return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + int(pot * 0.75)))
            return "call" if pot_odds < 0.32 else "fold"
        if s >= pot_odds + 0.12:
            return "call"
        return "fold"


class TheRock(Strategy):
    """Ultra-tight nit: plays only premium hands, value bets big made hands,
    refuses to pay off without the goods, waits for everyone else to die."""

    name = "The Rock"

    def act(self, obs):
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        stack = obs["stack"]

        if obs["street"] == "preflop":
            r = sorted((card_rank(c) for c in obs["hole"]), reverse=True)
            pair = r[0] == r[1]
            suited = card_suit(obs["hole"][0]) == card_suit(obs["hole"][1])
            premium = (pair and r[0] >= 10) or (r == [12, 11])          # QQ+/AK
            strong = (pair and r[0] >= 7) or (r == [12, 10] and suited)  # 99+/AQs
            if premium:
                return ("raise", max(obs["min_raise_to"], 3 * bb, obs["current_bet"] * 3))
            if strong:
                return "call" if to_call <= max(3 * bb, stack // 10) else "fold"
            # desperation shove when blinds have eaten the stack
            if stack <= 4 * bb and (pair or r[0] == 12):
                return "allin"
            return "check" if to_call == 0 else "fold"

        info = board_pair_rank_info(obs["hole"], obs["board"])
        cat = info["category"]
        pot = obs["pot"]
        if cat >= 3:
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + int(pot * 0.8)))
        if cat == 2 or info["overpair"] or info["top_pair"]:
            if to_call == 0:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.5), bb))
            return "call" if to_call <= pot * 0.5 else "fold"
        return "check" if to_call == 0 else "fold"


class LagBully(Strategy):
    """Loose-aggressive table bully: opens wide, steals blinds, barrels,
    semi-bluffs every draw, and shoves on short stacks to apply maximum
    pressure."""

    name = "LAG Bully"

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]
        stack = obs["stack"]

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            facing_raise = obs["current_bet"] > bb
            shortest_opp = min(obs["opp_stacks"]) if obs["opp_stacks"] else 0
            if score >= 9 and facing_raise:
                return ("raise", max(obs["min_raise_to"], obs["current_bet"] * 3))
            if score >= 7 and shortest_opp <= 10 * bb and not facing_raise:
                return "allin"  # punish the shorties
            if score >= 5 and not facing_raise:
                return ("raise", max(obs["min_raise_to"], 3 * bb))
            if obs["players_behind"] <= 1 and not facing_raise and rng.random() < 0.55:
                return ("raise", max(obs["min_raise_to"], int(2.5 * bb)))  # steal
            if score >= 6 and to_call <= stack * 0.1:
                return "call"
            return "check" if to_call == 0 else "fold"

        s = made_strength(obs["hole"], obs["board"])
        fd, oesd, gs = draw_outs(obs["hole"], obs["board"])
        drawing = (fd or oesd) and obs["street"] != "river"
        if to_call == 0:
            if s >= 0.55 or drawing or rng.random() < 0.40:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.75), bb))
            return "check"
        if s >= 0.75:
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + int(pot * 1.2)))
        if drawing:
            if rng.random() < 0.5:
                return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + pot))
            return "call" if to_call <= pot else "fold"
        if s >= 0.5 and to_call <= pot * 0.75:
            return "call"
        if gs and to_call <= pot * 0.25:
            return "call"
        return "fold"


class TheProfessor(Strategy):
    """Pot-odds mathematician: estimates raw equity with Monte Carlo rollouts
    against the number of live opponents (random hands — it cannot see
    anyone's cards) and compares equity to the price being offered."""

    name = "The Professor"

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]
        n_opps = max(1, obs["n_opps"])
        trials = 50 if obs["street"] != "preflop" else 40
        eq = monte_carlo_equity(obs["hole"], obs["board"], n_opps, rng, trials)
        fair_share = 1.0 / (n_opps + 1)
        edge = eq - fair_share

        if to_call == 0:
            if edge > 0.22:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.9), bb))
            if edge > 0.10:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.55), bb))
            return "check"
        pot_odds = to_call / (pot + to_call)
        if eq > pot_odds + 0.28 and edge > 0.15:
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + pot))
        if eq > pot_odds + 0.03:
            return "call"
        # short-stack push/fold: shove decent equity rather than blind off
        if obs["stack"] <= 6 * bb and eq > fair_share + 0.05:
            return "allin"
        return "fold"


class Trickster(Strategy):
    """Balanced-deceptive: slow-plays monsters, check-raises, floats in
    position, mixes in random bluffs so opponents can never put it on a
    hand."""

    name = "Trickster"

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            facing_raise = obs["current_bet"] > bb
            suited_conn = (
                card_suit(obs["hole"][0]) == card_suit(obs["hole"][1])
                and abs(card_rank(obs["hole"][0]) - card_rank(obs["hole"][1])) == 1
            )
            if score >= 9:
                if rng.random() < 0.3 and not facing_raise:
                    return "call"  # limp a monster for deception
                return ("raise", max(obs["min_raise_to"], 3 * bb, obs["current_bet"] * 2))
            if score >= 6 or suited_conn:
                return "call" if to_call <= max(2 * bb, obs["stack"] // 20) else "fold"
            if not facing_raise and rng.random() < 0.12:
                return ("raise", max(obs["min_raise_to"], int(2.5 * bb)))  # air raise
            return "check" if to_call == 0 else "fold"

        s = made_strength(obs["hole"], obs["board"])
        monster = board_pair_rank_info(obs["hole"], obs["board"])["category"] >= 3
        if monster:
            if obs["street"] == "flop" and to_call == 0 and rng.random() < 0.6:
                return "check"  # trap
            if to_call > 0 and obs["street"] == "flop" and rng.random() < 0.5:
                return "call"  # keep the trap shut
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + pot))
        if to_call == 0:
            if s >= 0.55:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.6), bb))
            if rng.random() < 0.15:
                return ("raise", obs["my_bet_this_round"] + max(int(pot * 0.7), bb))  # pure bluff
            return "check"
        pot_odds = to_call / (pot + to_call)
        if s >= 0.6 and rng.random() < 0.25:
            return ("raise", max(obs["min_raise_to"], obs["my_bet_this_round"] + to_call + int(pot * 0.8)))
        if s >= pot_odds + 0.08:
            return "call"
        fd, oesd, _ = draw_outs(obs["hole"], obs["board"])
        if (fd or oesd) and obs["street"] != "river" and pot_odds < 0.3:
            return "call"
        return "fold"


# ---------------------------------------------------------------------------
# Tournament engine
# ---------------------------------------------------------------------------
BLIND_LEVELS = [
    (10, 20), (15, 30), (25, 50), (50, 100), (75, 150), (100, 200),
    (150, 300), (200, 400), (300, 600), (500, 1000), (800, 1600),
    (1200, 2400), (2000, 4000), (3000, 6000), (5000, 10000),
]
HANDS_PER_LEVEL = 10
STARTING_STACK = 1500
MAX_HANDS = 2000


class Player:
    def __init__(self, seat, strategy):
        self.seat = seat
        self.strategy = strategy
        self.stack = STARTING_STACK
        self.reset_hand()

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.total_contrib = 0

    @property
    def name(self):
        return f"Player {self.seat}"


class Tournament:
    def __init__(self, strategies, seed):
        self.rng = random.Random(seed)
        self.players = [Player(i + 1, s) for i, s in enumerate(strategies)]
        self.button = self.rng.randrange(len(self.players))
        self.hand_no = 0

    # -- helpers ------------------------------------------------------------
    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def blinds(self):
        level = min(self.hand_no // HANDS_PER_LEVEL, len(BLIND_LEVELS) - 1)
        return BLIND_LEVELS[level]

    def commit(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.bet_this_round += amount
        p.total_contrib += amount
        return amount

    def make_obs(self, p, street, board, hand_players):
        live = [q for q in hand_players if not q.folded]
        pot = sum(q.total_contrib for q in hand_players)
        order_after = 0
        for q in live:
            if q is not p and not q.folded and q.stack > 0 and q.bet_this_round < self.current_bet:
                order_after += 1
        return {
            "hole": tuple(p.hole),
            "board": tuple(board),
            "street": street,
            "pot": pot,
            "to_call": min(self.current_bet - p.bet_this_round, p.stack),
            "current_bet": self.current_bet,
            "min_raise_to": self.current_bet + self.last_raise_size,
            "my_bet_this_round": p.bet_this_round,
            "stack": p.stack,
            "big_blind": self.blinds()[1],
            "num_live": len(live),
            "n_opps": len(live) - 1,
            "players_behind": order_after,
            "i_was_last_aggressor": self.last_aggressor is p,
            "opp_stacks": [q.stack for q in live if q is not p],
            "rng": self.rng,
        }

    # -- betting ------------------------------------------------------------
    def betting_round(self, order, street, board, hand_players):
        pending = deque(p for p in order if not p.folded and p.stack > 0)
        while pending:
            live = [q for q in hand_players if not q.folded]
            if len(live) <= 1:
                return
            p = pending.popleft()
            if p.folded or p.stack == 0:
                continue
            obs = self.make_obs(p, street, board, hand_players)
            try:
                action = p.strategy.act(obs)
            except Exception:
                action = "fold"
            self.apply_action(p, action, pending, hand_players)

    def apply_action(self, p, action, pending, hand_players):
        to_call = self.current_bet - p.bet_this_round
        if action == "allin":
            target = p.bet_this_round + p.stack
            action = ("raise", target) if target > self.current_bet else "call"
        if isinstance(action, tuple) and action[0] == "raise":
            target = min(int(action[1]), p.bet_this_round + p.stack)
            if target <= self.current_bet:  # can't actually raise -> call
                action = "call"
            else:
                full_raise = target >= self.current_bet + self.last_raise_size
                is_all_in = target == p.bet_this_round + p.stack
                if not full_raise and not is_all_in:
                    target = min(self.current_bet + self.last_raise_size,
                                 p.bet_this_round + p.stack)
                    full_raise = target >= self.current_bet + self.last_raise_size
                if full_raise:
                    self.last_raise_size = target - self.current_bet
                self.current_bet = target
                self.commit(p, target - p.bet_this_round)
                self.last_aggressor = p
                for q in hand_players:
                    if q is not p and not q.folded and q.stack > 0 and q not in pending:
                        pending.append(q)
                return
        if action == "call":
            if to_call > 0:
                self.commit(p, to_call)
            return
        if action == "check" and to_call == 0:
            return
        if action == "fold" and to_call == 0:
            return  # be kind: checking is free
        p.folded = True

    # -- one hand -----------------------------------------------------------
    def play_hand(self):
        players = self.alive()
        n = len(players)
        seats = sorted(players, key=lambda p: p.seat)
        # rotate button to next living seat
        self.button = (self.button + 1) % len(self.players)
        while self.players[self.button].stack == 0:
            self.button = (self.button + 1) % len(self.players)
        btn_player = self.players[self.button]
        idx = seats.index(btn_player)
        order = seats[idx:] + seats[:idx]  # button first

        for p in players:
            p.reset_hand()
        deck = new_deck(self.rng)
        for p in order:
            p.hole = [deck.pop(), deck.pop()]

        sb_amt, bb_amt = self.blinds()
        if n == 2:
            sb, bb = order[0], order[1]  # heads-up: button posts SB
            preflop_order = [sb, bb]
        else:
            sb, bb = order[1], order[2]
            preflop_order = order[3:] + order[:3]  # UTG first, BB last
        self.commit(sb, sb_amt)
        self.commit(bb, bb_amt)
        self.current_bet = bb_amt
        self.last_raise_size = bb_amt
        self.last_aggressor = None

        board = []
        self.betting_round(preflop_order, "preflop", board, order)
        postflop_order = order[1:] + order[:1] if n > 2 else [order[1], order[0]]
        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len([p for p in order if not p.folded]) <= 1:
                break
            deck.pop()  # burn
            board.extend(deck.pop() for _ in range(n_cards))
            for p in order:
                p.bet_this_round = 0
            self.current_bet = 0
            self.last_raise_size = bb_amt
            self.last_aggressor = None
            self.betting_round(postflop_order, street, board, order)

        self.award_pots(order, board)
        self.hand_no += 1

    def award_pots(self, hand_players, board):
        live = [p for p in hand_players if not p.folded]
        contribs = {p: p.total_contrib for p in hand_players}

        # refund any uncalled portion of the biggest bet
        sorted_c = sorted(contribs.values(), reverse=True)
        if len(sorted_c) >= 2 and sorted_c[0] > sorted_c[1]:
            top = max(contribs, key=lambda p: contribs[p])
            refund = sorted_c[0] - sorted_c[1]
            contribs[top] -= refund
            top.stack += refund

        if len(live) == 1:
            live[0].stack += sum(contribs.values())
            return

        # complete the board for all-in runouts
        deck_left = [c for c in range(52) if c not in board
                     and all(c not in p.hole for p in hand_players)]
        self.rng.shuffle(deck_left)
        while len(board) < 5:
            board.append(deck_left.pop())

        values = {p: eval_best(p.hole + board) for p in live}

        # layered side pots
        while True:
            levels = [contribs[p] for p in live if contribs[p] > 0]
            if not levels:
                break
            lvl = min(levels)
            eligible = [p for p in live if contribs[p] > 0]
            amount = 0
            for p in hand_players:
                take = min(contribs[p], lvl)
                contribs[p] -= take
                amount += take
            best = max(values[p] for p in eligible)
            winners = [p for p in eligible if values[p] == best]
            share, rem = divmod(amount, len(winners))
            for i, w in enumerate(winners):
                w.stack += share + (1 if i < rem else 0)
        leftover = sum(contribs.values())  # dead money from deep folds
        if leftover:
            best = max(values[p] for p in live)
            winners = [p for p in live if values[p] == best]
            winners[0].stack += leftover

    def run(self):
        while len(self.alive()) > 1 and self.hand_no < MAX_HANDS:
            self.play_hand()
        return max(self.players, key=lambda p: p.stack), self.hand_no


# ---------------------------------------------------------------------------
# Simulation harness + histogram
# ---------------------------------------------------------------------------
def make_lineup():
    return [
        AllInManiac(),   # Player 1 — "if my_turn then bet = All in fi"
        TagShark(),      # Player 2
        TheRock(),       # Player 3
        LagBully(),      # Player 4
        TheProfessor(),  # Player 5
        Trickster(),     # Player 6
    ]


def main():
    ap = argparse.ArgumentParser(description="6-max Hold'em tournament sims")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    lineup = make_lineup()
    wins = {i + 1: 0 for i in range(len(lineup))}
    total_hands = 0
    for i in range(args.sims):
        t = Tournament(make_lineup(), seed=args.seed * 1_000_003 + i)
        champ, hands = t.run()
        wins[champ.seat] += 1
        total_hands += hands

    labels = {i + 1: s.name for i, s in enumerate(lineup)}
    print()
    print("=" * 66)
    print(f"  TEXAS HOLD'EM — {args.sims} winner-take-all tournaments, 6 players")
    print(f"  Everyone starts with {STARTING_STACK} chips. Blinds escalate.")
    print(f"  Avg tournament length: {total_hands / args.sims:.1f} hands")
    print("=" * 66)
    print()
    print("  WINNER WINNER CHICKEN DINNER HISTOGRAM (championships won)")
    print()
    peak = max(wins.values()) or 1
    for seat in sorted(wins):
        bar = "█" * round(wins[seat] / peak * 40)
        tag = f"Player {seat} ({labels[seat]})"
        print(f"  {tag:<28}|{bar:<41}{wins[seat]:>3}")
    print()
    champ_seat = max(wins, key=lambda s: wins[s])
    print(f"  👑 Overall champion of the sim: Player {champ_seat} "
          f"({labels[champ_seat]}) with {wins[champ_seat]}/{args.sims} titles")
    print()


if __name__ == "__main__":
    main()
