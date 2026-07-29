"""Six poker strategies.

Player 1 runs the requested masterpiece:

    if my_turn
    Then bet = All in
    Fi

Players 2..6 run five elaborate, mutually unaware strategies. Every bot
sees only public information (actions, stacks, board) plus its own hole
cards — nobody knows anybody else's algorithm.
"""

import random

from .cards import chen_score, equity_estimate


class Strategy:
    name = "base"

    def __init__(self, pid, rng):
        self.pid = pid
        self.rng = random.Random(rng.randrange(2 ** 63))

    def new_hand(self, pid, pids_in_hand):
        pass

    def observe(self, event):
        pass

    def act(self, view):
        raise NotImplementedError

    # ------------------------------------------------------------- helpers

    @staticmethod
    def pot_odds(view):
        if view.to_call <= 0:
            return 0.0
        return view.to_call / (view.pot + view.to_call)

    @staticmethod
    def raise_to_fraction(view, fraction):
        """Raise-to amount equal to `fraction` of the pot after calling."""
        target = view.current_bet + int((view.pot + view.to_call) * fraction)
        return max(target, view.min_raise_to)

    def last_aggressor(self, view):
        for pid, street, action, amount in reversed(view.history):
            if street == view.street and action in ("raise", "all_in_raise"):
                return pid
        return None


# ---------------------------------------------------------------------------
# Player 1 — the requested algorithm, verbatim in spirit.
# ---------------------------------------------------------------------------

class AllInMonkey(Strategy):
    """if my_turn Then bet = All in Fi"""

    name = "YOLO All-In"

    def act(self, view):
        return ("raise", view.my_street_commit + view.my_stack)


# ---------------------------------------------------------------------------
# Player 2 — tight-aggressive professional.
# ---------------------------------------------------------------------------

class TagShark(Strategy):
    """Tight-aggressive: Chen-formula ranges by position, continuation
    betting, Monte-Carlo hand strength postflop, disciplined stack-off
    thresholds and pot-odds calls."""

    name = "TAG Shark"

    def act(self, view):
        if view.street == "preflop":
            return self.preflop(view)
        return self.postflop(view)

    def preflop(self, view):
        score = chen_score(view.hole)
        bb = view.big_blind
        raised_pot = view.current_bet > bb
        shove_vs_me = view.to_call >= view.my_stack * 0.6

        # position: fewer players still to act -> wider range
        left_to_act = sum(1 for o in view.opponents
                          if o["in_hand"] and o["street_commit"] < view.current_bet)
        open_threshold = 8.5 - min(left_to_act, 4) * 0.4

        if shove_vs_me or view.to_call > 8 * bb:
            # big pressure: only continue with a premium holding
            if score >= 11:
                return ("raise", view.my_street_commit + view.my_stack)
            return ("fold", 0)
        if not raised_pot:
            if score >= open_threshold:
                return ("raise", 3 * bb + view.pot // 4)
            if view.to_call == 0:
                return ("check", 0)
            return ("fold", 0)
        # facing a normal raise
        if score >= 11.5:
            return ("raise", self.raise_to_fraction(view, 1.0))
        if score >= 9 and self.pot_odds(view) < 0.25:
            return ("call", 0)
        return ("fold", 0)

    def postflop(self, view):
        n_opps = view.n_in_hand - 1
        eq = equity_estimate(view.hole, view.board, n_opps, self.rng)
        odds = self.pot_odds(view)
        big_pot = view.to_call >= view.my_stack * 0.5

        if view.to_call == 0:
            if eq >= 0.72:
                return ("raise", self.raise_to_fraction(view, 0.75))
            if eq >= 0.55 and self.last_aggressor(view) is None:
                return ("raise", self.raise_to_fraction(view, 0.5))
            return ("check", 0)
        if big_pot:
            if eq >= 0.66:
                return ("raise", view.my_street_commit + view.my_stack)
            return ("fold", 0)
        if eq >= 0.78:
            return ("raise", self.raise_to_fraction(view, 0.9))
        if eq >= odds + 0.04:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 3 — loose-aggressive pressure machine.
# ---------------------------------------------------------------------------

class LagBlaze(Strategy):
    """Loose-aggressive: wide opens, positional steals, random-frequency
    bluffs and double barrels, semi-bluff shoves — but bails against real
    resistance without equity."""

    name = "LAG Blaze"

    def new_hand(self, pid, pids_in_hand):
        self.bluffing = self.rng.random() < 0.28

    def act(self, view):
        bb = view.big_blind
        if view.street == "preflop":
            score = chen_score(view.hole)
            shove_vs_me = view.to_call >= view.my_stack * 0.6
            if shove_vs_me:
                return (("raise", view.my_street_commit + view.my_stack)
                        if score >= 10 else ("fold", 0))
            if view.current_bet <= bb:
                if score >= 6 or self.rng.random() < 0.18:
                    return ("raise", 3 * bb)
                return ("check", 0) if view.to_call == 0 else ("fold", 0)
            if score >= 10 or (self.bluffing and self.rng.random() < 0.35):
                return ("raise", self.raise_to_fraction(view, 0.9))
            if score >= 7.5 and self.pot_odds(view) < 0.3:
                return ("call", 0)
            return ("fold", 0)

        n_opps = view.n_in_hand - 1
        eq = equity_estimate(view.hole, view.board, n_opps, self.rng)
        odds = self.pot_odds(view)

        if view.to_call == 0:
            if eq >= 0.62:
                return ("raise", self.raise_to_fraction(view, 0.8))
            if self.bluffing and n_opps <= 2:
                return ("raise", self.raise_to_fraction(view, 0.66))
            return ("check", 0)
        if view.to_call >= view.my_stack * 0.5:
            return (("raise", view.my_street_commit + view.my_stack)
                    if eq >= 0.6 else ("fold", 0))
        if eq >= 0.7:
            return ("raise", self.raise_to_fraction(view, 1.0))
        if eq >= odds:
            return ("call", 0)
        if self.bluffing and self.rng.random() < 0.2 and odds < 0.3:
            return ("raise", self.raise_to_fraction(view, 1.0))
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 4 — the rock.
# ---------------------------------------------------------------------------

class RockNit(Strategy):
    """Ultra-tight value player: folds almost everything preflop, never
    bluffs, only stacks off with near-nut equity, milks monsters."""

    name = "Rock Nit"

    def act(self, view):
        bb = view.big_blind
        if view.street == "preflop":
            score = chen_score(view.hole)
            shove_vs_me = view.to_call >= view.my_stack * 0.5
            if shove_vs_me or view.to_call > 6 * bb:
                if score >= 12:  # JJ+/AKs territory
                    return ("raise", view.my_street_commit + view.my_stack)
                return ("fold", 0)
            if score >= 10:
                return ("raise", 3 * bb + view.pot // 3)
            if score >= 8 and self.pot_odds(view) < 0.15:
                return ("call", 0)
            return ("check", 0) if view.to_call == 0 else ("fold", 0)

        n_opps = view.n_in_hand - 1
        eq = equity_estimate(view.hole, view.board, n_opps, self.rng)
        if view.to_call == 0:
            if eq >= 0.8:
                return ("raise", self.raise_to_fraction(view, 0.6))
            return ("check", 0)
        if eq >= 0.82:
            return ("raise", self.raise_to_fraction(view, 1.0))
        if eq >= 0.7 and view.to_call < view.my_stack * 0.35:
            return ("call", 0)
        if eq >= self.pot_odds(view) + 0.15:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 5 — the equity mathematician.
# ---------------------------------------------------------------------------

class MathProfessor(Strategy):
    """Pure expected-value machine: Monte-Carlo equity on every single
    decision, compared against exact pot odds; value-raises when equity
    dwarfs the price, calls any positive-EV price, folds the rest."""

    name = "Math Professor"

    ITERS = 64

    def act(self, view):
        n_opps = max(1, view.n_in_hand - 1)
        eq = equity_estimate(view.hole, view.board, n_opps, self.rng,
                             iters=self.ITERS)
        odds = self.pot_odds(view)

        if view.to_call == 0:
            need = 1.0 / view.n_in_hand + 0.06
            if eq >= need + 0.18:
                return ("raise", self.raise_to_fraction(view, 0.85))
            if eq >= need + 0.05:
                return ("raise", self.raise_to_fraction(view, 0.5))
            return ("check", 0)

        if view.to_call >= view.my_stack:  # all-in decision: pure price
            return ("call", 0) if eq > odds + 0.02 else ("fold", 0)
        if eq >= odds + 0.28:
            return ("raise", self.raise_to_fraction(view, 1.0))
        if eq > odds + 0.02:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 6 — the adaptive exploiter.
# ---------------------------------------------------------------------------

class Adaptron(Strategy):
    """Exploitative profiler: tracks every opponent's VPIP, aggression and
    shove frequency from public actions only, then targets the leaks —
    calls maniac shoves wide, steals from nits, tightens vs rocks' raises,
    and switches to push/fold when short-stacked."""

    name = "Adaptron"

    def __init__(self, pid, rng):
        super().__init__(pid, rng)
        self.stats = {}  # pid -> {hands, vpip, raises, shoves, acts}

    def new_hand(self, pid, pids_in_hand):
        self._counted_vpip = set()
        for p in pids_in_hand:
            if p != self.pid:
                self.stats.setdefault(
                    p, {"hands": 0, "vpip": 0, "raises": 0,
                        "shoves": 0, "acts": 0})
                self.stats[p]["hands"] += 1

    def observe(self, event):
        pid, street, action, amount = event
        if pid == self.pid or pid not in self.stats:
            return
        st = self.stats[pid]
        if action in ("call", "raise", "all_in_raise"):
            st["acts"] += 1
            if pid not in self._counted_vpip:
                st["vpip"] += 1
                self._counted_vpip.add(pid)
        if action in ("raise", "all_in_raise"):
            st["raises"] += 1
        if action == "all_in_raise":
            st["shoves"] += 1

    # profiling ------------------------------------------------------------

    def shove_rate(self, pid):
        st = self.stats.get(pid)
        if not st or st["hands"] < 4:
            return 0.0
        return st["shoves"] / st["hands"]

    def is_maniac(self, pid):
        return self.shove_rate(pid) > 0.45

    def is_nit(self, pid):
        st = self.stats.get(pid)
        if not st or st["hands"] < 8:
            return False
        return st["vpip"] / st["hands"] < 0.22

    # decisions ------------------------------------------------------------

    def act(self, view):
        bb = view.big_blind
        short = view.my_stack <= 12 * bb
        aggressor = self.last_aggressor(view)

        if view.street == "preflop":
            score = chen_score(view.hole)
            facing_shove = view.to_call >= view.my_stack * 0.5

            if facing_shove:
                # exploit: a maniac shoves any two cards, so call way wider
                threshold = 6.5 if (aggressor is not None
                                    and self.is_maniac(aggressor)) else 11
                if score >= threshold:
                    return ("raise", view.my_street_commit + view.my_stack)
                return ("fold", 0)

            if short:  # push/fold regime
                if score >= 7:
                    return ("raise", view.my_street_commit + view.my_stack)
                return ("check", 0) if view.to_call == 0 else ("fold", 0)

            if view.current_bet <= bb:
                # steal wider when the players behind are folding machines
                still_in = [o["pid"] for o in view.opponents if o["in_hand"]]
                nit_table = bool(still_in) and all(
                    self.is_nit(p) for p in still_in)
                threshold = 6 if nit_table else 7.5
                if score >= threshold:
                    return ("raise", int(2.5 * bb))
                return ("check", 0) if view.to_call == 0 else ("fold", 0)

            # facing a raise: respect the nits, attack the rest
            if aggressor is not None and self.is_nit(aggressor):
                if score >= 12:
                    return ("raise", self.raise_to_fraction(view, 1.0))
                return ("fold", 0)
            if score >= 10.5:
                return ("raise", self.raise_to_fraction(view, 0.9))
            if score >= 8 and self.pot_odds(view) < 0.28:
                return ("call", 0)
            return ("fold", 0)

        # postflop: equity core with exploitative seasoning
        n_opps = view.n_in_hand - 1
        eq = equity_estimate(view.hole, view.board, n_opps, self.rng)
        odds = self.pot_odds(view)
        vs_maniac = aggressor is not None and self.is_maniac(aggressor)
        vs_nit = aggressor is not None and self.is_nit(aggressor)

        if view.to_call == 0:
            if eq >= 0.7:
                return ("raise", self.raise_to_fraction(view, 0.75))
            if eq >= 0.5 and n_opps == 1:
                return ("raise", self.raise_to_fraction(view, 0.5))
            return ("check", 0)
        if vs_maniac:  # their bets carry almost no information
            if eq >= 0.5:
                return ("raise", view.my_street_commit + view.my_stack)
            if eq >= odds - 0.05:
                return ("call", 0)
            return ("fold", 0)
        if vs_nit and view.to_call > view.my_stack * 0.3:
            return ("call", 0) if eq >= 0.8 else ("fold", 0)
        if view.to_call >= view.my_stack * 0.5:
            return (("raise", view.my_street_commit + view.my_stack)
                    if eq >= 0.65 else ("fold", 0))
        if eq >= 0.74:
            return ("raise", self.raise_to_fraction(view, 0.9))
        if eq >= odds + 0.03:
            return ("call", 0)
        return ("fold", 0)


ROSTER = [
    (1, AllInMonkey),
    (2, TagShark),
    (3, LagBlaze),
    (4, RockNit),
    (5, MathProfessor),
    (6, Adaptron),
]
