"""Six poker brains. None of them knows what the others are running.

Actions returned to the engine:
    ("fold",)            give up (auto-converted to check if free)
    ("check",)/("call",) match the current bet (all-in call if short)
    ("raise", total)     raise so my total bet this street becomes `total`
                         (engine clamps to stack / min-raise rules)
"""

from .cards import chen_score, estimate_equity


class Strategy:
    name = "?"

    def __init__(self, seat, rng):
        self.seat = seat
        self.rng = rng

    def act(self, view):
        raise NotImplementedError

    def observe(self, event):
        pass


def _pot_odds(view):
    tc = view["to_call"]
    return tc / (view["pot"] + tc) if tc > 0 else 0.0


def _mc_opp(view):
    return max(1, min(2, view["n_unfolded"] - 1))


# ---------------------------------------------------------------------------
# Player 1
# ---------------------------------------------------------------------------
class AllInAndy(Strategy):
    """Player 1's entire strategy, verbatim from the spec:

        if my_turn
        then bet = All in
        fi
    """
    name = "AllInAndy"

    def act(self, view):
        return ("raise", view["my_bet"] + view["stack"])


# ---------------------------------------------------------------------------
# Player 2 — tight-aggressive: strong ranges, position, equity-driven bets
# ---------------------------------------------------------------------------
class TightAggressiveTina(Strategy):
    name = "TAG-Tina"

    def act(self, view):
        if view["stage"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view["hole"])
        bb = view["bb"]
        to_call = view["to_call"]
        late = view["position"] >= view["n_positions"] - 2

        if score >= 12:  # JJ+, AKs and friends: 3-bet / get it in
            return ("raise", max(3 * bb, 3 * view["current_bet"]))
        if score >= 9:
            if view["current_bet"] <= bb:
                return ("raise", int(2.5 * bb))
            if to_call <= 4 * bb:
                return ("call",)
            # facing real pressure: only continue if it's cheap vs stack
            if to_call <= 0.08 * view["stack"]:
                return ("call",)
            return ("fold",)
        if score >= 7:
            if view["current_bet"] <= bb:
                return ("raise", int(2.2 * bb)) if late else ("call",)
            if to_call <= bb:
                return ("call",)
            return ("fold",)
        if score >= 5.5 and late and to_call <= bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, view):
        eq = estimate_equity(view["hole"], view["community"],
                             _mc_opp(view), 50, self.rng)
        need = _pot_odds(view)
        pot = view["pot"]
        if view["to_call"] == 0:
            if eq > 0.62:
                return ("raise", view["my_bet"] + int(0.66 * pot))
            if eq > 0.45 and self.rng.random() < 0.30:
                return ("raise", view["my_bet"] + max(view["bb"],
                                                      int(0.40 * pot)))
            return ("check",)
        if eq > 0.78:
            return ("raise", view["current_bet"] + max(view["min_raise"],
                                                       pot))
        if eq >= need + 0.05:
            return ("call",)
        if eq >= need and view["to_call"] <= 0.10 * view["stack"]:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 3 — loose-aggressive: wide ranges, c-bets, bluffs, chaos
# ---------------------------------------------------------------------------
class LooseLucas(Strategy):
    name = "LAG-Lucas"

    def __init__(self, seat, rng):
        super().__init__(seat, rng)
        self.was_preflop_aggressor = False

    def act(self, view):
        if view["stage"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view["hole"])
        bb = view["bb"]
        to_call = view["to_call"]
        self.was_preflop_aggressor = False

        big_shove = to_call > 0.35 * view["stack"]
        if big_shove:
            if score >= 9.5 or self.rng.random() < 0.05:  # tilt call
                return ("call",)
            return ("fold",)
        if score >= 8 and self.rng.random() < 0.5:
            self.was_preflop_aggressor = True
            return ("raise", max(3 * bb, 3 * view["current_bet"]))
        if score >= 5:
            if view["current_bet"] <= bb and self.rng.random() < 0.6:
                self.was_preflop_aggressor = True
                return ("raise", int(2.2 * bb))
            if to_call <= 3 * bb:
                return ("call",)
        h = view["hole"]
        r1, r2 = sorted((h[0] >> 2, h[1] >> 2), reverse=True)
        suited_connector = (h[0] & 3) == (h[1] & 3) and r1 - r2 <= 2
        if suited_connector and to_call <= 2 * bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, view):
        eq = estimate_equity(view["hole"], view["community"],
                             _mc_opp(view), 50, self.rng)
        need = _pot_odds(view)
        pot = view["pot"]
        if view["to_call"] == 0:
            if eq > 0.80 or (eq > 0.55 and self.rng.random() < 0.03):
                return ("raise", view["my_bet"] + view["stack"])  # boom
            if eq > 0.60:
                return ("raise", view["my_bet"] + int(0.75 * pot))
            if self.was_preflop_aggressor and self.rng.random() < 0.55:
                return ("raise", view["my_bet"] + int(0.66 * pot))  # c-bet
            if self.rng.random() < 0.20:
                return ("raise", view["my_bet"] + int(0.50 * pot))  # stab
            return ("check",)
        if eq > 0.72:
            return ("raise", view["current_bet"] + max(view["min_raise"],
                                                       int(0.9 * pot)))
        if eq > need - 0.05:  # optimistic caller
            return ("call",)
        if self.rng.random() < 0.07 and view["to_call"] < 0.25 * view["stack"]:
            return ("call",)  # float and pray
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 4 — the rock: folds everything except the goods, then pounces
# ---------------------------------------------------------------------------
class NittyNina(Strategy):
    name = "Nit-Nina"

    PREMIUM_PAIRS = {12, 11, 10, 9}  # AA KK QQ JJ

    def act(self, view):
        if view["stage"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _classify(self, hole):
        r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
        suited = (hole[0] & 3) == (hole[1] & 3)
        pair = r1 == r2
        if (pair and r1 in self.PREMIUM_PAIRS) or (r1 == 12 and r2 == 11):
            return "premium"          # AA-JJ, AK
        if (pair and r1 >= 7) or (r1 == 12 and r2 == 10 and suited):
            return "strong"           # 99/TT, AQs
        return "trash"

    def _preflop(self, view):
        tier = self._classify(view["hole"])
        bb = view["bb"]
        if tier == "premium":
            # raise big; happily gets it all-in preflop
            return ("raise", max(4 * bb, 3 * view["current_bet"]))
        if tier == "strong":
            if view["to_call"] <= 3 * bb:
                return ("call",)
            return ("fold",)
        return ("fold",)  # engine turns this into a check when it's free

    def _postflop(self, view):
        eq = estimate_equity(view["hole"], view["community"],
                             _mc_opp(view), 50, self.rng)
        pot = view["pot"]
        if view["to_call"] == 0:
            if eq > 0.72:
                return ("raise", view["my_bet"] + pot)
            return ("check",)
        if eq > 0.72:
            return ("raise", view["current_bet"] + max(view["min_raise"],
                                                       pot))
        if eq > 0.55 and view["to_call"] <= 0.12 * view["stack"]:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 5 — the mathematician: pure pot odds vs Monte-Carlo equity
# ---------------------------------------------------------------------------
class PotOddsPete(Strategy):
    name = "PotOdds-Pete"

    def act(self, view):
        trials = 40 if view["stage"] == "preflop" else 60
        eq = estimate_equity(view["hole"], view["community"],
                             _mc_opp(view), trials, self.rng)
        need = _pot_odds(view)
        pot = view["pot"]
        if view["to_call"] == 0:
            fair_share = 1.0 / max(2, view["n_unfolded"])
            if eq > fair_share * 1.4:
                return ("raise", view["my_bet"] + max(view["bb"],
                                                      int(0.6 * pot)))
            return ("check",)
        if eq > need + 0.18 and eq > 0.5:
            return ("raise", view["current_bet"] + max(view["min_raise"],
                                                       pot))
        if eq > need:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 6 — the profiler: tracks opponents and exploits what she sees
# ---------------------------------------------------------------------------
class ExploitEve(Strategy):
    name = "Exploit-Eve"

    def __init__(self, seat, rng):
        super().__init__(seat, rng)
        self.stats = {}  # seat -> {"acts": n, "allins": n, "raises": n}

    def observe(self, event):
        if event.get("type") != "action" or event["seat"] == self.seat:
            return
        s = self.stats.setdefault(event["seat"],
                                  {"acts": 0, "allins": 0, "raises": 0})
        s["acts"] += 1
        if event["action"] == "raise":
            s["raises"] += 1
            if event["all_in"]:
                s["allins"] += 1

    def _is_maniac(self, seat):
        s = self.stats.get(seat)
        return s and s["acts"] >= 4 and s["allins"] / s["acts"] > 0.5

    def act(self, view):
        if view["stage"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        bb = view["bb"]
        to_call = view["to_call"]
        score = chen_score(view["hole"])
        shovers = [o for o in view["opponents"]
                   if o["all_in"] and o["bet"] > 0 and not o["folded"]]
        maniac_shove = shovers and all(self._is_maniac(o["seat"])
                                       for o in shovers)

        if to_call > 0.30 * view["stack"] or shovers:
            if maniac_shove:
                # a maniac's shove is a random hand: call with live-card edge
                eq = estimate_equity(view["hole"], view["community"],
                                     max(1, len(shovers)), 70, self.rng)
                threshold = 0.56 if len(shovers) == 1 else 0.42
                if view["stack"] <= 4 * bb:
                    threshold -= 0.08  # desperate times
                if eq > threshold:
                    return ("raise", view["my_bet"] + view["stack"])
                return ("fold",)
            # an unknown or sane player shoving means business
            if score >= 11:
                return ("call",)
            return ("fold",)
        if view["current_bet"] <= bb:
            late = view["position"] >= view["n_positions"] - 2
            if score >= 8 or (late and score >= 6):
                return ("raise", int(2.5 * bb))  # open / steal
            if to_call == 0:
                return ("check",)
            if score >= 6 and to_call <= bb:
                return ("call",)
            return ("fold",)
        if score >= 11:
            return ("raise", 3 * view["current_bet"])
        if score >= 9 and to_call <= 4 * bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, view):
        eq = estimate_equity(view["hole"], view["community"],
                             _mc_opp(view), 50, self.rng)
        need = _pot_odds(view)
        pot = view["pot"]
        bettor_seats = [o["seat"] for o in view["opponents"]
                        if o["bet"] >= view["current_bet"]
                        and not o["folded"] and view["current_bet"] > 0]
        vs_maniac = any(self._is_maniac(s) for s in bettor_seats)

        if view["to_call"] == 0:
            if eq > 0.65:
                return ("raise", view["my_bet"] + int(0.7 * pot))
            return ("check",)
        # a maniac's bet carries no information; a stranger's does
        margin = 0.0 if vs_maniac else 0.08
        if eq > 0.80:
            return ("raise", view["current_bet"] + max(view["min_raise"],
                                                       pot))
        if eq >= need + margin:
            return ("call",)
        return ("fold",)


def lineup():
    """Seats 1..6: the simple one first, then the five elaborate brains."""
    return [AllInAndy, TightAggressiveTina, LooseLucas, NittyNina,
            PotOddsPete, ExploitEve]
