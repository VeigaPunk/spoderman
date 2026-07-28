"""Six poker strategies. None of them knows what the others are running —
they only see public actions (and showdowns) via observe().

  1. LeeroyJenkins   — "if my_turn then bet = All in fi"
  2. TheProfessor    — tight-aggressive: position-aware ranges, c-bets, discipline
  3. TheCowboy       — loose-aggressive: wide opens, 3-bet bluffs, relentless barrels
  4. TheRock         — ultra-tight nit: folds for hours, stacks off with monsters
  5. TheMathematician— Monte Carlo equity vs pot odds, pure expected value
  6. TheProfiler     — exploitative: tracks opponent stats and adjusts ranges
"""

import math
import random
from collections import Counter, defaultdict

from .cards import evaluate, rank_of, suit_of


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def chen_score(hole):
    r1, r2 = sorted((rank_of(c) for c in hole), reverse=True)
    suited = suit_of(hole[0]) == suit_of(hole[1])
    base = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:
        score += 1
    return math.ceil(score)


def made_tier(hole, board):
    """0 air, 1 board-pair/weak, 2 mid pair/underpair, 3 top pair,
    4 overpair/two pair, 5 trips/set, 6 straight or better."""
    my = evaluate(hole + board)
    cat = my[0]
    if cat >= 4:
        return 6
    if cat == 3:
        return 5
    if cat == 2:
        return 4
    board_ranks = [rank_of(c) for c in board]
    hole_ranks = [rank_of(c) for c in hole]
    top_board = max(board_ranks)
    if cat == 1:
        pr = my[1]
        if hole_ranks[0] == hole_ranks[1] and pr == hole_ranks[0]:
            return 4 if pr > top_board else 2
        if pr in hole_ranks and pr in board_ranks:
            return 3 if pr == top_board else 2
        return 1
    return 0


def draw_strength(hole, board):
    """0 none, 1 gutshot, 2 open-ended, 3 flush draw, 4 combo."""
    cards = hole + board
    suits = Counter(suit_of(c) for c in cards)
    hole_suits = {suit_of(c) for c in hole}
    fd = any(n == 4 and s in hole_suits for s, n in suits.items())

    ranks = {rank_of(c) for c in cards}
    if 12 in ranks:
        ranks = ranks | {-1}
    straight_draw = 0
    for lo in range(-1, 9):
        window = {lo, lo + 1, lo + 2, lo + 3, lo + 4}
        have = len(window & ranks)
        if have == 4:
            straight_draw = max(straight_draw, 1)
    for lo in range(-1, 9):
        if all(r in ranks for r in (lo, lo + 1, lo + 2, lo + 3)):
            if lo - 1 >= -1 and lo + 4 <= 12:
                straight_draw = 2

    if fd and straight_draw:
        return 4
    if fd:
        return 3
    return straight_draw


_EQUITY_CACHE = {}
_CACHE_RNG = random.Random(424242)


def preflop_equity(hole, n_opps, iters=200):
    """Equity of `hole` vs n random opponents, cached by canonical hand."""
    r1, r2 = sorted((rank_of(c) for c in hole), reverse=True)
    suited = suit_of(hole[0]) == suit_of(hole[1])
    key = (r1, r2, suited, n_opps)
    if key in _EQUITY_CACHE:
        return _EQUITY_CACHE[key]
    eq = monte_carlo_equity(hole, [], n_opps, _CACHE_RNG, iters)
    _EQUITY_CACHE[key] = eq
    return eq


def monte_carlo_equity(hole, community, n_opps, rng, iters=60):
    deck = [c for c in range(52) if c not in hole and c not in community]
    need_board = 5 - len(community)
    need = need_board + 2 * n_opps
    score = 0.0
    for _ in range(iters):
        drawn = rng.sample(deck, need)
        board = community + drawn[:need_board]
        mine = evaluate(hole + board)
        best_opp = None
        for i in range(n_opps):
            oh = drawn[need_board + 2 * i: need_board + 2 * i + 2]
            s = evaluate(oh + board)
            if best_opp is None or s > best_opp:
                best_opp = s
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters


def position_class(obs):
    """0 early, 1 middle, 2 late (button), 3 blinds."""
    if obs["seat"] == obs["button"]:
        return 2
    if obs["street"] == "preflop" and obs["my_street_bet"] > 0:
        return 3
    n = obs["num_live"]
    if n <= 3:
        return 2
    return 1 if n <= 5 else 0


class BaseStrategy:
    def __init__(self, player_id, rng):
        self.id = player_id
        self.rng = rng
        self.hole = None

    def new_hand(self, info):
        self.hole = info["hole"]

    def observe(self, event):
        pass

    def act(self, obs):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, as specified:
#   if my_turn then bet = All in fi
# ---------------------------------------------------------------------------

class LeeroyJenkins(BaseStrategy):
    NAME = "Leeroy Jenkins (ALL-IN)"

    def act(self, obs):
        return "raise", 10 ** 9


# ---------------------------------------------------------------------------
# Player 2 — The Professor: disciplined tight-aggressive play
# ---------------------------------------------------------------------------

class TheProfessor(BaseStrategy):
    NAME = "The Professor (TAG)"

    def new_hand(self, info):
        super().new_hand(info)
        self.was_aggressor = False

    def act(self, obs):
        if obs["street"] == "preflop":
            return self.preflop(obs)
        return self.postflop(obs)

    def preflop(self, obs):
        score = chen_score(self.hole)
        bb = obs["bb"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        pos = position_class(obs)
        open_threshold = {0: 9, 1: 8, 2: 6, 3: 7}[pos]

        unopened = obs["current_bet"] <= bb
        if unopened:
            if score >= open_threshold:
                self.was_aggressor = True
                return "raise", obs["my_street_bet"] + to_call + int(2.5 * bb)
            return "fold", 0

        pot_frac = to_call / max(1, stack)
        if score >= 11:
            self.was_aggressor = True
            return "raise", obs["current_bet"] * 3
        if score >= 10 and pot_frac <= 0.35:
            return "call", 0
        if score >= 8 and pot_frac <= 0.10:
            return "call", 0
        return "fold", 0

    def postflop(self, obs):
        board = obs["community"]
        tier = made_tier(self.hole, board)
        draw = draw_strength(self.hole, board)
        pot = obs["pot"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]

        if tier >= 4:
            target = obs["my_street_bet"] + to_call + max(obs["bb"], (2 * pot) // 3)
            self.was_aggressor = True
            return "raise", target
        if tier == 3:
            if to_call == 0:
                self.was_aggressor = True
                return "raise", obs["my_street_bet"] + pot // 2
            if to_call <= pot // 2 or to_call <= stack // 8:
                return "call", 0
            return "fold", 0
        if draw >= 2:
            if to_call == 0 and self.rng.random() < 0.6:
                self.was_aggressor = True
                return "raise", obs["my_street_bet"] + pot // 2
            need = 0.65 if draw >= 3 else 0.72
            if to_call <= max(obs["bb"], int(pot * (1 - need))):
                return "call", 0
            return "fold", 0
        if to_call == 0:
            if self.was_aggressor and obs["num_live"] <= 3 and obs["street"] == "flop":
                return "raise", obs["my_street_bet"] + pot // 2
            return "call", 0
        if tier >= 2 and to_call <= pot // 4:
            return "call", 0
        return "fold", 0


# ---------------------------------------------------------------------------
# Player 3 — The Cowboy: loose-aggressive pressure machine
# ---------------------------------------------------------------------------

class TheCowboy(BaseStrategy):
    NAME = "The Cowboy (LAG)"

    def new_hand(self, info):
        super().new_hand(info)
        self.barrels = 0

    def act(self, obs):
        if obs["street"] == "preflop":
            return self.preflop(obs)
        return self.postflop(obs)

    def preflop(self, obs):
        score = chen_score(self.hole)
        bb = obs["bb"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        ranks = sorted((rank_of(c) for c in self.hole), reverse=True)
        blocker = ranks[0] >= 11  # holds an A or K

        unopened = obs["current_bet"] <= bb
        if unopened:
            if score >= 5 or (blocker and self.rng.random() < 0.4):
                return "raise", obs["my_street_bet"] + to_call + 3 * bb
            return "fold", 0

        if score >= 10 or (blocker and self.rng.random() < 0.15):
            return "raise", obs["current_bet"] * 3
        if score >= 7 and to_call <= stack // 4:
            return "call", 0
        if score >= 9 and to_call <= stack:
            return "call", 0
        return "fold", 0

    def postflop(self, obs):
        board = obs["community"]
        tier = made_tier(self.hole, board)
        draw = draw_strength(self.hole, board)
        pot = obs["pot"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]

        if tier >= 5:
            if obs["street"] == "river" and self.rng.random() < 0.5:
                return "raise", obs["my_street_bet"] + to_call + int(1.4 * pot)
            return "raise", obs["my_street_bet"] + to_call + (3 * pot) // 4
        if tier == 4 or draw >= 3:
            return "raise", obs["my_street_bet"] + to_call + (2 * pot) // 3
        if tier == 3 or draw == 2:
            if to_call == 0:
                self.barrels += 1
                return "raise", obs["my_street_bet"] + (2 * pot) // 3
            if to_call <= pot:
                return "call", 0
            return "fold", 0
        if to_call == 0:
            if self.barrels < 2 and self.rng.random() < 0.45:
                self.barrels += 1
                return "raise", obs["my_street_bet"] + pot // 2
            if obs["street"] == "river" and self.rng.random() < 0.10:
                return "raise", obs["my_street_bet"] + pot
            return "call", 0
        if tier >= 1 and to_call <= pot // 3:
            return "call", 0
        return "fold", 0


# ---------------------------------------------------------------------------
# Player 4 — The Rock: fold, fold, fold, then break someone's stack
# ---------------------------------------------------------------------------

class TheRock(BaseStrategy):
    NAME = "The Rock (Nit)"

    def act(self, obs):
        if obs["street"] == "preflop":
            return self.preflop(obs)
        return self.postflop(obs)

    def preflop(self, obs):
        score = chen_score(self.hole)
        bb = obs["bb"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        short = stack <= 12 * bb

        unopened = obs["current_bet"] <= bb
        threshold = 8 if short else 10
        if unopened:
            if score >= threshold:
                return "raise", obs["my_street_bet"] + to_call + 3 * bb
            return "fold", 0
        if score >= 12:
            return "raise", 10 ** 9  # premium: get it all in
        if score >= 10:
            if to_call >= stack:
                return "call", 0
            return "raise", obs["current_bet"] * 3
        if short and score >= 8 and to_call <= stack:
            return "call", 0
        return "fold", 0

    def postflop(self, obs):
        board = obs["community"]
        tier = made_tier(self.hole, board)
        pot = obs["pot"]
        to_call = obs["to_call"]

        if tier >= 5:
            return "raise", 10 ** 9
        if tier == 4:
            return "raise", obs["my_street_bet"] + to_call + (2 * pot) // 3
        if tier == 3:
            if to_call == 0:
                return "raise", obs["my_street_bet"] + pot // 2
            if to_call <= pot // 2:
                return "call", 0
            return "fold", 0
        if to_call == 0:
            return "call", 0
        return "fold", 0


# ---------------------------------------------------------------------------
# Player 5 — The Mathematician: Monte Carlo equity vs pot odds, nothing else
# ---------------------------------------------------------------------------

class TheMathematician(BaseStrategy):
    NAME = "The Mathematician (EV)"

    def act(self, obs):
        n_opps = min(3, max(1, obs["num_live"] - 1))
        if obs["street"] == "preflop":
            eq = preflop_equity(self.hole, n_opps)
        else:
            eq = monte_carlo_equity(self.hole, obs["community"], n_opps,
                                    self.rng, iters=70)

        pot = obs["pot"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        fair_share = 1.0 / (n_opps + 1)

        if to_call == 0:
            if eq > fair_share + 0.18:
                return "raise", obs["my_street_bet"] + (2 * pot) // 3
            if eq > fair_share + 0.08 and obs["street"] != "preflop":
                return "raise", obs["my_street_bet"] + pot // 2
            return "call", 0

        pot_odds = to_call / (pot + to_call)
        risk = to_call / max(1, stack)
        margin = 0.02 + 0.06 * risk  # demand more edge for bigger bets
        if eq >= 0.5 + 0.15 * n_opps * 0.5 and eq > pot_odds + 0.10:
            return "raise", obs["my_street_bet"] + to_call + pot
        if eq > pot_odds + margin:
            return "call", 0
        return "fold", 0


# ---------------------------------------------------------------------------
# Player 6 — The Profiler: watches everyone and exploits what it sees
# ---------------------------------------------------------------------------

class TheProfiler(BaseStrategy):
    NAME = "The Profiler (Exploit)"

    def __init__(self, player_id, rng):
        super().__init__(player_id, rng)
        self.hands_seen = defaultdict(int)
        self.vpip = defaultdict(int)
        self.allins = defaultdict(int)
        self.raises = defaultdict(int)
        self.folds_to_bet = defaultdict(int)
        self.faced_bet = defaultdict(int)
        self._vpip_this_hand = set()

    def observe(self, event):
        et = event.get("type")
        if et == "hand_start":
            for p in event["players"]:
                self.hands_seen[p] += 1
            self._vpip_this_hand = set()
        elif et == "action":
            s = event["seat"]
            if s == self.id:
                return
            a = event["action"]
            if event["street"] == "preflop" and a in ("call", "raise") \
                    and event["paid"] > 0 and s not in self._vpip_this_hand:
                self.vpip[s] += 1
                self._vpip_this_hand.add(s)
            if a == "raise":
                self.raises[s] += 1
                if event["all_in"]:
                    self.allins[s] += 1
            if event["to_call"] > 0:
                self.faced_bet[s] += 1
                if a == "fold":
                    self.folds_to_bet[s] += 1

    def rate(self, num, den, seat, default):
        d = den[seat]
        return num[seat] / d if d >= 6 else default

    def maniac_alert(self, obs):
        """Largest all-in threat among opponents still in the hand."""
        best = 0.0
        for o in obs["opponents"]:
            if not o["in_hand"]:
                continue
            r = self.rate(self.allins, self.hands_seen, o["seat"], 0.0)
            best = max(best, r)
        return best

    def table_tightness(self, obs):
        vals = []
        for o in obs["opponents"]:
            vals.append(self.rate(self.vpip, self.hands_seen, o["seat"], 0.25))
        return sum(vals) / len(vals) if vals else 0.25

    def act(self, obs):
        if obs["street"] == "preflop":
            return self.preflop(obs)
        return self.postflop(obs)

    def preflop(self, obs):
        score = chen_score(self.hole)
        bb = obs["bb"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        maniac = self.maniac_alert(obs)
        tight_table = self.table_tightness(obs) < 0.18

        facing_jam = any(o["all_in"] and o["street_bet"] >= obs["current_bet"]
                         for o in obs["opponents"])

        if facing_jam and maniac > 0.35:
            # someone shoves near-every hand: their range is ~random,
            # so call off with any hand that beats a random hand + cushion
            eq = preflop_equity(self.hole, 1)
            risk = min(to_call, stack) / max(1, stack)
            if eq > 0.50 + 0.10 * risk:
                return "call", 0
            return "fold", 0

        unopened = obs["current_bet"] <= bb
        if unopened:
            threshold = 5 if tight_table else 7
            if score >= threshold:
                return "raise", obs["my_street_bet"] + to_call + int(2.5 * bb)
            return "fold", 0

        if score >= 11:
            return "raise", obs["current_bet"] * 3
        if score >= 9 and to_call <= stack // 6:
            return "call", 0
        if score >= 8 and to_call <= stack // 12:
            return "call", 0
        return "fold", 0

    def postflop(self, obs):
        board = obs["community"]
        tier = made_tier(self.hole, board)
        draw = draw_strength(self.hole, board)
        pot = obs["pot"]
        to_call = obs["to_call"]
        stack = obs["my_stack"]
        maniac = self.maniac_alert(obs)

        if maniac > 0.35 and to_call > 0:
            n_live = max(1, obs["num_live"] - 1)
            eq = monte_carlo_equity(self.hole, board, min(2, n_live),
                                    self.rng, iters=60)
            pot_odds = to_call / (pot + to_call)
            if eq > pot_odds + 0.02:
                return "call", 0
            return "fold", 0

        # find the biggest folder to bluff at
        foldiest = 0.0
        for o in obs["opponents"]:
            if o["in_hand"]:
                foldiest = max(foldiest, self.rate(self.folds_to_bet,
                                                   self.faced_bet, o["seat"], 0.5))

        if tier >= 4:
            return "raise", obs["my_street_bet"] + to_call + (2 * pot) // 3
        if tier == 3:
            if to_call == 0:
                return "raise", obs["my_street_bet"] + pot // 2
            if to_call <= pot // 2:
                return "call", 0
            return "fold", 0
        if draw >= 3 and to_call <= pot // 2:
            if to_call == 0:
                return "raise", obs["my_street_bet"] + (2 * pot) // 3
            return "call", 0
        if to_call == 0:
            if foldiest > 0.6 and self.rng.random() < 0.55:
                return "raise", obs["my_street_bet"] + pot // 2
            return "call", 0
        if draw == 2 and to_call <= pot // 4:
            return "call", 0
        return "fold", 0


ROSTER = {
    1: LeeroyJenkins,
    2: TheProfessor,
    3: TheCowboy,
    4: TheRock,
    5: TheMathematician,
    6: TheProfiler,
}
