"""Six poker strategies. Each only sees the engine's observation dict —
no strategy knows what any other strategy is.

Actions returned as (verb, amount): verb in {"fold", "call", "raise"},
amount = total chips in front of the player this street (raise-to).
The engine clamps illegal amounts, so strategies can shove with
my_bet + stack.
"""

from __future__ import annotations

import random

from engine import chen_score, equity_mc, preflop_equity


class Strategy:
    name = "base"

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def act(self, obs):  # pragma: no cover - interface
        raise NotImplementedError

    # helpers ---------------------------------------------------------------

    @staticmethod
    def _shove(obs):
        return ("raise", obs["my_bet"] + obs["stack"])

    @staticmethod
    def _raise_to(obs, target):
        target = max(target, obs["current_bet"] + obs["min_raise"])
        return ("raise", min(target, obs["my_bet"] + obs["stack"]))

    @staticmethod
    def _pot_odds(obs):
        to_call = min(obs["to_call"], obs["stack"])
        return to_call / (obs["pot"] + to_call) if to_call > 0 else 0.0

    def _equity(self, obs, rollouts):
        n_opp = max(1, obs["n_in_hand"] - 1)
        if not obs["board"]:
            return preflop_equity(obs["hole"], n_opp)
        return equity_mc(obs["hole"], obs["board"], n_opp, self.rng, rollouts)


# ---------------------------------------------------------------------------
# Player 1 — exactly the requested algorithm:
#
#   if my_turn
#   then bet = All in
#   fi
# ---------------------------------------------------------------------------

class AllInBot(Strategy):
    name = "All-In Andy"

    def act(self, obs):
        return self._shove(obs)  # my_turn is trivially true when act() runs


# ---------------------------------------------------------------------------
# Player 2 — "Athena", tight-aggressive. Chen-formula preflop ranges with
# positional widening, pot-controlled postflop lines driven by MC equity
# with a safety margin over pot odds.
# ---------------------------------------------------------------------------

class TagBot(Strategy):
    name = "Athena (TAG)"

    def act(self, obs):
        bb = obs["big_blind"]
        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            to_call = obs["to_call"]
            facing_big = to_call > 4 * bb
            if facing_big:
                # Big raise or shove ahead: continue only with a premium range,
                # priced by real equity when it is effectively an all-in call.
                eq = preflop_equity(obs["hole"], 1)
                if score >= 11 or (to_call >= obs["stack"] and eq > self._pot_odds(obs) + 0.10):
                    return self._shove(obs)
                if score >= 9.5 and to_call <= obs["stack"] * 0.25:
                    return ("call", 0)
                return ("fold", 0)
            if score >= 10:
                return self._raise_to(obs, obs["current_bet"] + 3 * bb)
            if score >= 8:
                return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb))
            if score >= 6 and to_call <= 2 * bb:
                return ("call", 0)
            return ("fold", 0) if to_call > 0 else ("call", 0)

        eq = self._equity(obs, rollouts=28)
        odds = self._pot_odds(obs)
        if obs["to_call"] == 0:
            if eq > 0.80:
                return self._raise_to(obs, obs["my_bet"] + obs["pot"])
            if eq > 0.52 + 0.04 * (obs["n_in_hand"] - 2):
                return self._raise_to(obs, obs["my_bet"] + max(bb, int(obs["pot"] * 0.6)))
            return ("call", 0)  # check
        if eq > 0.78:
            return self._raise_to(obs, obs["my_bet"] + obs["to_call"] + obs["pot"])
        if eq > odds + 0.07:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 3 — "Loki", loose-aggressive. Wider opening ranges, randomized
# sizing, blind steals, occasional bluffs and semi-bluff raises with
# live equity.
# ---------------------------------------------------------------------------

class LagBot(Strategy):
    name = "Loki (LAG)"

    def act(self, obs):
        bb = obs["big_blind"]
        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            to_call = obs["to_call"]
            if to_call > 4 * bb:
                eq = preflop_equity(obs["hole"], 1)
                if score >= 10 or eq > self._pot_odds(obs) + 0.13:
                    return self._shove(obs)
                return ("fold", 0)
            if score >= 9:
                return self._raise_to(obs, obs["current_bet"] + self.rng.choice((3, 4)) * bb)
            if score >= 5.5:
                if self.rng.random() < 0.7:
                    return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb))
                return ("call", 0)
            # pure steal attempt with trash, low frequency
            if to_call <= bb and self.rng.random() < 0.18:
                return self._raise_to(obs, obs["current_bet"] + 2 * bb)
            return ("fold", 0) if to_call > 0 else ("call", 0)

        eq = self._equity(obs, rollouts=26)
        odds = self._pot_odds(obs)
        if obs["to_call"] == 0:
            if eq > 0.45 or self.rng.random() < 0.22:  # value bets and bluffs blended
                size = int(obs["pot"] * self.rng.choice((0.5, 0.75, 1.0)))
                return self._raise_to(obs, obs["my_bet"] + max(bb, size))
            return ("call", 0)
        if eq > 0.72:
            return self._raise_to(obs, obs["my_bet"] + obs["to_call"] + obs["pot"])
        if 0.38 < eq <= 0.55 and self.rng.random() < 0.25:
            return self._raise_to(obs, obs["my_bet"] + obs["to_call"] * 3)  # semi-bluff
        if eq > odds + 0.03:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 4 — "Granite", the nit. Folds almost everything, but plays the
# top of the deck like a sledgehammer and gladly stacks off with it.
# ---------------------------------------------------------------------------

class NitBot(Strategy):
    name = "Granite (Nit)"

    def act(self, obs):
        bb = obs["big_blind"]
        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            if score >= 12:  # QQ+/AKs territory: never folds preflop
                return self._shove(obs) if obs["to_call"] > 3 * bb else \
                    self._raise_to(obs, obs["current_bet"] + 3 * bb)
            if score >= 9:
                if obs["to_call"] > 6 * bb:
                    return ("fold", 0)
                if obs["to_call"] > 0:
                    return ("call", 0)
                return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb))
            # Short stack exception: shove real hands rather than blind out.
            if obs["stack"] <= 5 * bb and score >= 7.5:
                return self._shove(obs)
            return ("fold", 0) if obs["to_call"] > 0 else ("call", 0)

        eq = self._equity(obs, rollouts=26)
        odds = self._pot_odds(obs)
        if obs["to_call"] == 0:
            if eq > 0.68:
                return self._raise_to(obs, obs["my_bet"] + int(obs["pot"] * 0.75))
            return ("call", 0)
        if eq > 0.82:
            return self._shove(obs)
        if eq > odds + 0.12:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 5 — "Bayes", the pot-odds mathematician. Every decision is an
# expected-value calculation from Monte Carlo equity: call iff equity beats
# pot odds, bet when equity beats the fair share of the pot, shove huge
# equity. No feel, no fear, just arithmetic.
# ---------------------------------------------------------------------------

class OddsBot(Strategy):
    name = "Bayes (Odds)"

    def act(self, obs):
        eq = self._equity(obs, rollouts=36)
        odds = self._pot_odds(obs)
        bb = obs["big_blind"]
        fair_share = 1.0 / obs["n_in_hand"]
        if obs["to_call"] == 0:
            if eq > 0.85:
                return self._shove(obs)
            if eq > fair_share + 0.10:
                size = int(obs["pot"] * min(1.0, (eq - fair_share) * 2.5))
                return self._raise_to(obs, obs["my_bet"] + max(bb, size))
            return ("call", 0)
        if eq > 0.74:
            return self._shove(obs)
        if eq > odds + 0.02:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 6 — "Mirror", the profiler. Builds a statistical model of each
# opponent from observed actions only (all-in frequency, preflop raise %,
# showdown rate) and switches gears: snap-calls maniacs with any hand whose
# equity beats the price, steals from rocks, reverts to solid TAG otherwise.
# ---------------------------------------------------------------------------

class AdaptiveBot(Strategy):
    name = "Mirror (Adaptive)"

    @staticmethod
    def _maniac_in_pot(obs):
        for st in obs["opp_stats"].values():
            hands = max(1, st["hands"])
            if st["hands"] >= 5 and st["allin"] / hands > 0.4:
                return True
        return False

    @staticmethod
    def _table_tightness(obs):
        vp, hs = 0, 0
        for st in obs["opp_stats"].values():
            vp += st["vpip"]
            hs += max(1, st["hands"])
        return 1.0 - vp / max(1, hs)

    def act(self, obs):
        bb = obs["big_blind"]
        maniac = self._maniac_in_pot(obs)

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            to_call = obs["to_call"]
            if to_call >= min(obs["stack"], 8 * bb):
                # Facing a shove-sized bet. If the bettor shoves everything,
                # their range is random — call on raw equity vs price.
                n_opp = max(1, obs["n_in_hand"] - 1)
                eq = preflop_equity(obs["hole"], n_opp)
                edge = 0.03 if maniac else 0.12
                if eq > self._pot_odds(obs) + edge:
                    return self._shove(obs)
                return ("fold", 0)
            if maniac and score >= 7.5:
                return self._shove(obs)  # isolate the maniac, deny odds to others
            if score >= 9.5:
                return self._raise_to(obs, obs["current_bet"] + 3 * bb)
            tight = self._table_tightness(obs)
            if score >= 7 or (tight > 0.75 and to_call <= bb and score >= 5):
                if to_call <= 3 * bb:
                    return self._raise_to(obs, obs["current_bet"] + int(2.5 * bb)) \
                        if to_call <= bb else ("call", 0)
            return ("fold", 0) if to_call > 0 else ("call", 0)

        eq = self._equity(obs, rollouts=30)
        odds = self._pot_odds(obs)
        margin = 0.02 if maniac else 0.06
        if obs["to_call"] == 0:
            if eq > 0.75:
                return self._raise_to(obs, obs["my_bet"] + obs["pot"])
            if eq > 0.55:
                return self._raise_to(obs, obs["my_bet"] + max(bb, int(obs["pot"] * 0.6)))
            return ("call", 0)
        if eq > 0.76:
            return self._shove(obs)
        if eq > odds + margin:
            return ("call", 0)
        return ("fold", 0)


LINEUP = (AllInBot, TagBot, LagBot, NitBot, OddsBot, AdaptiveBot)
