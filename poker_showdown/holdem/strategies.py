"""Player strategies.

Every strategy sees only public information plus its own hole cards. None of
them knows what algorithm anyone else runs — the Profiler has to *learn* who
the maniac is from observed actions.

act(obs) returns one of:  ("fold",)  ("call",)  ("raise", chip_target)
where chip_target is the total street commitment to raise to.
"""

import random

from .evaluator import evaluate7

# --------------------------------------------------------------------- utils


def chen(hole):
    """Chen formula preflop hand score (roughly -1 .. 20)."""
    r1, r2 = sorted((hole[0] % 13, hole[1] % 13), reverse=True)
    suited = hole[0] // 13 == hole[1] // 13
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 <= 9:
        pts += 1  # straight potential bonus
    if suited:
        pts += 2
    return pts


_PRE_CACHE = {}


def _canon(hole):
    r1, r2 = sorted((hole[0] % 13, hole[1] % 13), reverse=True)
    return (r1, r2, 1 if hole[0] // 13 == hole[1] // 13 else 0)


def preflop_equity(hole, n_opps):
    """Monte-Carlo equity of `hole` vs n_opps random hands (cached)."""
    key = (_canon(hole), n_opps)
    if key in _PRE_CACHE:
        return _PRE_CACHE[key]
    rng = random.Random(hash(key) & 0x7FFFFFFF)
    # build a representative pair of cards for the canonical class
    r1, r2, suited = key[0]
    if suited:
        hole = (r1, r2)  # both clubs
    else:
        hole = (r1, 13 + r2)
    eq = mc_equity(hole, (), n_opps, rng, iters=500)
    _PRE_CACHE[key] = eq
    return eq


def mc_equity(hole, board, n_opps, rng, iters=80):
    """Monte-Carlo equity vs n_opps uniformly random hands."""
    n_opps = max(1, min(n_opps, 5))
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(board)
    need = n_opps * 2 + need_board
    score = 0.0
    my_cards = list(hole)
    for _ in range(iters):
        draw = rng.sample(deck, need)
        full_board = list(board) + draw[:need_board]
        mine = evaluate7(my_cards + full_board)
        best_opp = -1
        i = need_board
        for _o in range(n_opps):
            s = evaluate7(draw[i:i + 2] + full_board)
            if s > best_opp:
                best_opp = s
            i += 2
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters


def pot_odds(obs):
    tc = obs["to_call"]
    return tc / (obs["pot"] + tc) if tc > 0 else 0.0


def n_live_opps(obs):
    return max(1, obs["n_in_hand"] - 1)


class Strategy:
    def observe(self, event):
        pass

    def act(self, obs):
        raise NotImplementedError


# ---------------------------------------------------------------- Player 1


class SuflairGPT(Strategy):
    """The entire strategy, verbatim:

        if my_turn
        then bet = All in
        fi
    """

    def act(self, obs):
        return ("raise", obs["my_street_commit"] + obs["my_stack"])


# ---------------------------------------------------------------- Player 2


class Professor(Strategy):
    """Tight-aggressive. Position-aware Chen-formula opening ranges, Monte
    Carlo equity postflop, strict pot-odds discipline with a small margin of
    safety, value bets 2/3 pot, semi-bluffs good draws."""

    def act(self, obs):
        if obs["street"] == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        ch = chen(obs["hole"])
        bb = obs["bb"]
        late = obs["players_behind"] <= 2
        open_thresh = 5.5 if late else (6.5 if obs["players_behind"] <= 4 else 7.5)

        if obs["to_call"] <= 0 or obs["current_bet"] <= bb:
            if ch >= open_thresh:
                return ("raise", max(3 * bb, obs["min_raise_to"]))
            if obs["to_call"] <= 0:
                return ("call",)
            if ch >= 4.5 and obs["to_call"] <= bb:
                return ("call",)
            return ("fold",)

        # facing a real raise: count committed opponents, use true equity
        commits = [o for o in obs["opponents"]
                   if o["in_hand"] and (o["street_commit"] * 2 >= obs["current_bet"]
                                        or o["all_in"])]
        n = max(1, len(commits))
        eq = preflop_equity(obs["hole"], n)
        po = pot_odds(obs)
        if eq > 0.75 and obs["to_call"] < obs["my_stack"]:
            return ("raise", obs["my_street_commit"] + obs["my_stack"])  # QQ+/AK zone
        if eq > po + 0.04:
            return ("call",)
        return ("fold",)

    def _postflop(self, obs):
        rng = obs["rng"]
        eq = mc_equity(obs["hole"], obs["board"], n_live_opps(obs), rng, iters=70)
        pot = obs["pot"]
        if obs["to_call"] <= 0:
            if eq > 0.62:
                return ("raise", obs["my_street_commit"] + max(obs["bb"], (2 * pot) // 3))
            if eq > 0.48 and obs["n_in_hand"] <= 3 and rng.random() < 0.35:
                return ("raise", obs["my_street_commit"] + max(obs["bb"], pot // 2))
            return ("call",)
        po = pot_odds(obs)
        if eq > po + 0.28 and eq > 0.6:
            target = obs["current_bet"] + pot
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        if eq > po + 0.02:
            return ("call",)
        if eq > po - 0.04 and obs["to_call"] <= pot // 5:
            return ("call",)  # priced-in with implied odds
        return ("fold",)


# ---------------------------------------------------------------- Player 3


class LaCobra(Strategy):
    """Loose-aggressive. Opens wide in position, 3-bets light, c-bets
    relentlessly, double-barrels with equity or a random bluff, and applies
    max pressure on capped ranges — but bails against heavy resistance."""

    def __init__(self):
        self.i_raised_pre = False
        self.barrels = 0

    def observe(self, event):
        if event["type"] == "hand_start":
            self.i_raised_pre = False
            self.barrels = 0

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["bb"]
        if obs["street"] == "preflop":
            ch = chen(obs["hole"])
            late = obs["players_behind"] <= 2
            if obs["current_bet"] <= bb:
                if ch >= 4.5 or (late and rng.random() < 0.25):
                    self.i_raised_pre = True
                    return ("raise", max(3 * bb, obs["min_raise_to"]))
                return ("call",) if obs["to_call"] <= 0 else ("fold",)
            # facing a raise
            eq = preflop_equity(obs["hole"], 1)
            if eq > 0.66 or (ch >= 7.5 and rng.random() < 0.35):
                self.i_raised_pre = True
                target = obs["current_bet"] * 3
                return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
            po = pot_odds(obs)
            if eq > po + 0.03 and obs["to_call"] < obs["my_stack"] // 2:
                return ("call",)
            return ("fold",)

        eq = mc_equity(obs["hole"], obs["board"], n_live_opps(obs), rng, iters=60)
        pot = obs["pot"]
        if obs["to_call"] <= 0:
            cbet = self.i_raised_pre and self.barrels < 2 and obs["n_in_hand"] <= 3
            if eq > 0.55 or (cbet and rng.random() < 0.75) or rng.random() < 0.12:
                self.barrels += 1
                size = (2 * pot) // 3 if eq > 0.6 else pot // 2
                return ("raise", obs["my_street_commit"] + max(bb, size))
            return ("call",)
        po = pot_odds(obs)
        if eq > 0.68:
            target = obs["current_bet"] + pot
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        if eq > po + 0.01:
            return ("call",)
        if rng.random() < 0.10 and obs["to_call"] < pot // 2 and not obs["aggressor_all_in"]:
            target = obs["current_bet"] * 3  # spite bluff-raise
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        return ("fold",)


# ---------------------------------------------------------------- Player 4


class TheRock(Strategy):
    """Ultra-tight. Plays only premium hands, set-mines cheaply, never
    bluffs, and only stacks off with near-nut equity. Boring — on purpose."""

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["bb"]
        if obs["street"] == "preflop":
            r1, r2 = sorted((obs["hole"][0] % 13, obs["hole"][1] % 13), reverse=True)
            suited = obs["hole"][0] // 13 == obs["hole"][1] // 13
            pair = r1 == r2
            premium = (pair and r1 >= 8) or (r1 == 12 and r2 == 11) \
                or (r1 == 12 and r2 == 10 and suited)  # TT+, AK, AQs
            playable = (pair and r1 >= 4) or (r1 == 12 and r2 >= 9) \
                or (r1 == 11 and r2 == 10 and suited)
            if premium:
                if obs["current_bet"] <= bb:
                    return ("raise", max(3 * bb, obs["min_raise_to"]))
                eq = preflop_equity(obs["hole"], 1)
                if eq > 0.7:
                    return ("raise", obs["my_street_commit"] + obs["my_stack"])
                return ("call",)
            if playable and obs["to_call"] <= max(bb, obs["my_stack"] // 20):
                return ("call",)
            return ("fold",) if obs["to_call"] > 0 else ("call",)

        eq = mc_equity(obs["hole"], obs["board"], n_live_opps(obs), rng, iters=60)
        pot = obs["pot"]
        if obs["to_call"] <= 0:
            if eq > 0.70:
                return ("raise", obs["my_street_commit"] + max(bb, (2 * pot) // 3))
            return ("call",)
        po = pot_odds(obs)
        if eq > 0.80:
            target = obs["current_bet"] + pot
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        if eq > max(po + 0.10, 0.55):
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------- Player 5


class Profiler(Strategy):
    """Exploitative. Tracks every opponent's VPIP, aggression and open-shove
    frequency from the public action log, then attacks the leaks: it calls
    detected shove-monkeys wide with real equity, steals from nits, and plays
    solid TAG poker against unknowns."""

    def __init__(self):
        self.stats = {}

    def _s(self, seat):
        return self.stats.setdefault(seat, {"hands": 0, "vpip": 0,
                                            "shoves": 0, "pre_acts": 0})

    def observe(self, event):
        t = event["type"]
        if t == "hand_start":
            for seat in event["stacks"]:
                self._s(seat)["hands"] += 1
        elif t == "action" and event["street"] == "preflop":
            s = self._s(event["seat"])
            s["pre_acts"] += 1
            if event["action"] in ("call", "raise") and event.get("paid", 0) > 0:
                s["vpip"] += 1
            if event["action"] == "raise" and event.get("all_in"):
                s["shoves"] += 1

    def _shove_rate(self, seat):
        s = self._s(seat)
        if s["hands"] < 5:
            return 0.0
        return s["shoves"] / max(1, s["hands"])

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["bb"]
        if obs["street"] == "preflop":
            agg = obs["aggressor_seat"]
            if agg is not None and obs["aggressor_all_in"] \
                    and self._shove_rate(agg) > 0.35:
                # identified maniac: call with genuine equity vs ~random hand
                shovers = 1 + sum(1 for o in obs["opponents"]
                                  if o["all_in"] and o["in_hand"]
                                  and o["seat"] != agg)
                eq = preflop_equity(obs["hole"], shovers)
                needed = 0.52 if shovers == 1 else 0.42
                if obs["to_call"] >= obs["my_stack"]:
                    needed += 0.02  # my tournament life — small premium
                if eq >= needed:
                    return ("raise", obs["my_street_commit"] + obs["my_stack"])
                return ("fold",)

            ch = chen(obs["hole"])
            late = obs["players_behind"] <= 2
            if obs["current_bet"] <= bb:
                # steal wider from tight tables
                vpips = [self._s(o["seat"])["vpip"] / max(1, self._s(o["seat"])["hands"])
                         for o in obs["opponents"] if o["in_hand"]]
                tight = vpips and sum(vpips) / len(vpips) < 0.30
                thresh = 4.0 if (late and tight) else (5.5 if late else 7.0)
                if ch >= thresh:
                    return ("raise", max(3 * bb, obs["min_raise_to"]))
                return ("call",) if obs["to_call"] <= 0 else ("fold",)
            n = max(1, sum(1 for o in obs["opponents"]
                           if o["in_hand"] and o["street_commit"] * 2 >= obs["current_bet"]))
            eq = preflop_equity(obs["hole"], n)
            po = pot_odds(obs)
            if eq > 0.74:
                return ("raise", obs["my_street_commit"] + obs["my_stack"])
            if eq > po + 0.04:
                return ("call",)
            return ("fold",)

        eq = mc_equity(obs["hole"], obs["board"], n_live_opps(obs), rng, iters=70)
        pot = obs["pot"]
        if obs["to_call"] <= 0:
            if eq > 0.60:
                return ("raise", obs["my_street_commit"] + max(bb, (3 * pot) // 5))
            return ("call",)
        po = pot_odds(obs)
        if eq > po + 0.25 and eq > 0.62:
            target = obs["current_bet"] + pot
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        if eq > po + 0.02:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------- Player 6


class Actuary(Strategy):
    """Risk-managed small-ball with a Nash-ish push/fold gear. Charges a
    survival premium on stack-threatening calls, pot-controls medium hands,
    and shoves any decent hand once short-stacked."""

    def act(self, obs):
        rng = obs["rng"]
        bb = obs["bb"]
        my_bbs = obs["my_stack"] / bb if bb else 99

        if obs["street"] == "preflop":
            ch = chen(obs["hole"])
            if my_bbs < 10:  # push/fold mode
                jam_thresh = 5.0 + 0.5 * min(obs["players_behind"], 4) - (10 - my_bbs) * 0.25
                if obs["to_call"] >= obs["my_stack"]:
                    eq = preflop_equity(obs["hole"], 1)
                    return ("call",) if eq > 0.48 else ("fold",)
                if ch >= jam_thresh:
                    return ("raise", obs["my_street_commit"] + obs["my_stack"])
                return ("fold",) if obs["to_call"] > 0 else ("call",)

            late = obs["players_behind"] <= 2
            if obs["current_bet"] <= bb:
                if ch >= (5.5 if late else 7.0):
                    return ("raise", max(int(2.5 * bb), obs["min_raise_to"]))
                if obs["to_call"] <= 0:
                    return ("call",)
                return ("call",) if ch >= 5.0 and obs["to_call"] <= bb else ("fold",)
            n = max(1, sum(1 for o in obs["opponents"]
                           if o["in_hand"] and o["street_commit"] * 2 >= obs["current_bet"]))
            eq = preflop_equity(obs["hole"], n)
            po = pot_odds(obs)
            risk = obs["to_call"] / max(1, obs["my_stack"] + obs["to_call"])
            if eq > 0.76:
                return ("raise", obs["my_street_commit"] + obs["my_stack"])
            if eq > po + 0.03 + 0.08 * risk:
                return ("call",)
            return ("fold",)

        eq = mc_equity(obs["hole"], obs["board"], n_live_opps(obs), rng, iters=60)
        pot = obs["pot"]
        if obs["to_call"] <= 0:
            if eq > 0.66:
                return ("raise", obs["my_street_commit"] + max(bb, pot // 2))
            if eq > 0.52 and obs["players_behind"] == 0:
                return ("raise", obs["my_street_commit"] + max(bb, pot // 3))
            return ("call",)
        po = pot_odds(obs)
        risk = obs["to_call"] / max(1, obs["my_stack"] + obs["to_call"])
        if eq > 0.78:
            target = obs["current_bet"] + pot
            return ("raise", min(target, obs["my_street_commit"] + obs["my_stack"]))
        if eq > po + 0.03 + 0.10 * risk:
            return ("call",)
        return ("fold",)


LINEUP = [
    ("Suflair-GPT [ALL-IN]", SuflairGPT),
    ("The Professor [TAG]", Professor),
    ("La Cobra [LAG]", LaCobra),
    ("The Rock [NIT]", TheRock),
    ("The Profiler [EXPLOIT]", Profiler),
    ("The Actuary [RISK-MGMT]", Actuary),
]
