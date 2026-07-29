"""Six poker strategies.

Every strategy sees only the observation dict handed to it by the engine
(its own hole cards, the board, pot, stacks, position...). No strategy knows
anything about how the others play.

act(obs) -> (action, amount)
  action: "fold" | "call" | "raise"     ("call" with to_call == 0 is a check)
  amount: for "raise", the TOTAL street bet to raise to (engine clamps to
          all-in and treats too-small raises as calls).
"""

import random

from .cards import eval7


# --------------------------------------------------------------------- #
# shared math helpers (public poker knowledge, not shared state)
# --------------------------------------------------------------------- #

def chen_score(hole):
    """Bill Chen's preflop hand formula. AA=20, AKs=12, 72o=-1.5 ..."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    high = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, high * 2)
    score = high
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # connectors below queen can make more straights
        score += 1
    return score


def mc_equity(hole, board, n_opps, rng, iters=60):
    """Monte-Carlo equity of `hole` vs n_opps random hands."""
    if n_opps <= 0:
        return 1.0
    used = set(hole) | set(board)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, 2 * n_opps + need_board)
        full = list(board) + draw[:need_board]
        mine = eval7(list(hole) + full)
        best_opp = max(
            eval7([draw[need_board + 2 * k], draw[need_board + 2 * k + 1]] + full)
            for k in range(n_opps)
        )
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


def _pot_odds(obs):
    tc = obs["to_call"]
    return tc / (obs["pot"] + tc) if tc > 0 else 0.0


class Strategy:
    name = "base"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def act(self, obs):  # pragma: no cover - abstract
        raise NotImplementedError

    # convenience: raise TO a target, expressed off the current bet
    @staticmethod
    def _raise_to(obs, target):
        return ("raise", max(int(target), obs["min_raise_to"]))


# --------------------------------------------------------------------- #
# Player 1 — the entire strategy, verbatim from the spec:
#   if my_turn then bet = All in fi
# --------------------------------------------------------------------- #

class AllInGoblin(Strategy):
    name = "All-In Goblin"

    def act(self, obs):
        return ("raise", obs["my_street_bet"] + obs["stack"])


# --------------------------------------------------------------------- #
# Player 2 — "The Rock": ultra-tight passive-until-premium nit.
# Folds ~93% of hands, but when it plays, it plays for stacks.
# --------------------------------------------------------------------- #

class TheRock(Strategy):
    name = "The Rock"

    def act(self, obs):
        bb = obs["big_blind"]
        tc = obs["to_call"]
        if obs["street"] == "preflop":
            c = chen_score(obs["hole"])
            facing_big = tc > 4 * bb or tc >= obs["stack"] * 0.4
            if facing_big:
                if c >= 12:  # JJ+/AKs territory: get it in
                    return self._raise_to(obs, obs["my_street_bet"] + obs["stack"])
                return ("fold", 0) if tc > 0 else ("call", 0)
            if c >= 10:
                return self._raise_to(obs, obs["current_bet"] + 3 * bb)
            if c >= 8 and tc <= 3 * bb:
                return ("call", 0)
            return ("fold", 0) if tc > 0 else ("call", 0)

        eq = mc_equity(obs["hole"], obs["board"], obs["n_unfolded"] - 1,
                       self.rng, iters=50)
        if eq > 0.80:
            return self._raise_to(obs, obs["current_bet"] + obs["pot"])
        if eq > 0.60:
            return ("call", 0)
        if tc == 0:
            return ("call", 0)
        if eq > 0.45 and tc <= obs["pot"] * 0.25:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------- #
# Player 3 — "TAG Professor": position-aware tight-aggressive play with
# pot-odds discipline and continuation bets.
# --------------------------------------------------------------------- #

class TAGProfessor(Strategy):
    name = "TAG Professor"

    def act(self, obs):
        bb = obs["big_blind"]
        tc = obs["to_call"]
        if obs["street"] == "preflop":
            c = chen_score(obs["hole"])
            # later position (higher order index) can open wider
            pos = obs["order_index"] / max(1, obs["n_players"] - 1)
            open_thr = 9.0 - 3.5 * pos
            facing_big = tc > 4 * bb or tc >= obs["stack"] * 0.4
            if facing_big:
                if c >= 11:
                    return self._raise_to(obs, obs["my_street_bet"] + obs["stack"])
                return ("fold", 0) if tc > 0 else ("call", 0)
            if c >= 10 and obs["raises_this_street"] >= 1:
                return self._raise_to(obs, obs["current_bet"] * 3)
            if c >= open_thr:
                return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb))
            if c >= open_thr - 1.5 and tc <= 2 * bb:
                return ("call", 0)
            return ("fold", 0) if tc > 0 else ("call", 0)

        eq = mc_equity(obs["hole"], obs["board"], obs["n_unfolded"] - 1,
                       self.rng, iters=60)
        odds = _pot_odds(obs)
        if eq > 0.70:
            return self._raise_to(obs, obs["current_bet"] + int(obs["pot"] * 0.75))
        if obs["i_am_aggressor"] and tc == 0 and eq > 0.35:
            return self._raise_to(obs, int(obs["pot"] * 0.6))  # c-bet
        if tc == 0:
            return ("call", 0)
        if eq > odds + 0.05:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------- #
# Player 4 — "LAG Cowboy": loose-aggressive. Wide opens, semi-bluffs,
# outright bluffs on a randomized frequency, hates folding to small bets.
# --------------------------------------------------------------------- #

class LAGCowboy(Strategy):
    name = "LAG Cowboy"

    def act(self, obs):
        bb = obs["big_blind"]
        tc = obs["to_call"]
        r = self.rng.random()
        if obs["street"] == "preflop":
            c = chen_score(obs["hole"])
            facing_big = tc > 5 * bb or tc >= obs["stack"] * 0.4
            if facing_big:
                if c >= 10 or (c >= 8 and r < 0.25):
                    return self._raise_to(obs, obs["my_street_bet"] + obs["stack"])
                return ("fold", 0) if tc > 0 else ("call", 0)
            if c >= 9 or (c >= 5 and r < 0.45):
                return self._raise_to(obs, obs["current_bet"] + 3 * bb)
            if tc <= 2 * bb and (c >= 4 or r < 0.30):
                return ("call", 0)
            return ("fold", 0) if tc > 0 else ("call", 0)

        eq = mc_equity(obs["hole"], obs["board"], obs["n_unfolded"] - 1,
                       self.rng, iters=50)
        odds = _pot_odds(obs)
        if eq > 0.68:
            return self._raise_to(obs, obs["current_bet"] + obs["pot"])
        if 0.38 < eq <= 0.68 and r < 0.5:  # semi-bluff the draws/mid hands
            return self._raise_to(obs, obs["current_bet"] + int(obs["pot"] * 0.8))
        if tc == 0:
            if r < 0.18:  # pure bluff stab
                return self._raise_to(obs, int(obs["pot"] * 0.7))
            return ("call", 0)
        if eq > odds - 0.04 or tc <= obs["stack"] * 0.08:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------- #
# Player 5 — "The Mathematician": no reads, no bluffs, no fear. Every
# decision is Monte-Carlo equity vs pot odds, preflop included.
# --------------------------------------------------------------------- #

class Mathematician(Strategy):
    name = "The Mathematician"

    def act(self, obs):
        n_opps = obs["n_unfolded"] - 1
        iters = 40 if obs["street"] == "preflop" else 70
        eq = mc_equity(obs["hole"], obs["board"], n_opps, self.rng, iters=iters)
        tc = obs["to_call"]
        odds = _pot_odds(obs)
        fair_share = 1.0 / max(2, obs["n_unfolded"])

        if eq > 0.85:
            return self._raise_to(obs, obs["my_street_bet"] + obs["stack"])
        if eq > fair_share + 0.15:
            return self._raise_to(obs, obs["current_bet"] + int(obs["pot"] * 0.5) + obs["big_blind"])
        if tc == 0:
            return ("call", 0)
        if eq > odds + 0.02:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------- #
# Player 6 — "The Trapper": slow-plays monsters to induce bets, springs
# check-raises, and otherwise plays honest fit-or-fold poker.
# --------------------------------------------------------------------- #

class Trapper(Strategy):
    name = "The Trapper"

    def __init__(self, seed=0):
        super().__init__(seed)
        self._hand_no = -1
        self._i_checked = False

    def act(self, obs):
        if obs["hand_no"] != self._hand_no:
            self._hand_no = obs["hand_no"]
            self._i_checked = False

        bb = obs["big_blind"]
        tc = obs["to_call"]
        if obs["street"] == "preflop":
            c = chen_score(obs["hole"])
            facing_big = tc > 4 * bb or tc >= obs["stack"] * 0.4
            if facing_big:
                if c >= 11:
                    return self._raise_to(obs, obs["my_street_bet"] + obs["stack"])
                return ("fold", 0) if tc > 0 else ("call", 0)
            if c >= 12:  # trap: flat-call even monsters sometimes
                if self.rng.random() < 0.5:
                    return ("call", 0) if tc > 0 else self._raise_to(obs, 3 * bb)
                return self._raise_to(obs, obs["current_bet"] + 3 * bb)
            if c >= 7 and tc <= 3 * bb:
                return ("call", 0)
            if c >= 9:
                return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb))
            return ("fold", 0) if tc > 0 else ("call", 0)

        eq = mc_equity(obs["hole"], obs["board"], obs["n_unfolded"] - 1,
                       self.rng, iters=60)
        monster = eq > 0.85
        if monster:
            if obs["street"] in ("flop", "turn") and tc == 0 and self.rng.random() < 0.6:
                self._i_checked = True
                return ("call", 0)  # check to trap
            if tc > 0 and self._i_checked:
                return self._raise_to(obs, obs["current_bet"] * 3)  # spring it
            if tc > 0:
                return self._raise_to(obs, obs["current_bet"] + obs["pot"])
            return self._raise_to(obs, int(obs["pot"] * 0.9))
        if eq > 0.65:
            if tc == 0:
                return self._raise_to(obs, int(obs["pot"] * 0.6))
            return ("call", 0)
        if tc == 0:
            self._i_checked = True
            return ("call", 0)
        if eq > _pot_odds(obs) + 0.03:
            return ("call", 0)
        return ("fold", 0)


ROSTER = [AllInGoblin, TheRock, TAGProfessor, LAGCowboy, Mathematician, Trapper]
