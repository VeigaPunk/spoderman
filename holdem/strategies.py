"""The six players.

Seat 1 gets :class:`AllInBot` -- the four-line strategy from the brief.
Seats 2..6 get five very different elaborate agents:

* :class:`SolverLite`      - range/percentile preflop charts, MDF + alpha
                             bluff frequencies, polarised sizing, mixed
                             strategies.  Tries to be unexploitable.
* :class:`BayesianExploiter` - Beta-posterior opponent models; converts each
                             opponent's observed action frequencies into a
                             range width and re-prices equity against it.
                             Tries to be maximally exploitative.
* :class:`ICMNash`         - push/fold by effective stack, Harrington M
                             zones, and Malmuth-Harville ICM risk premiums.
                             Plays the payout ladder, not the chips.
* :class:`PressureLAG`     - loose-aggressive; explicit fold-equity model,
                             double/triple barrels, overbet rivers, with a
                             discipline valve that refuses bad stack-offs.
* :class:`TrapRock`        - ultra-tight, slow-plays monsters, check-raise
                             traps, pot control, calls down light against
                             proven aggression.

No strategy is told which strategy sits in which seat.  Everything an agent
knows about the others it learned from public actions and showdowns.
"""

from __future__ import annotations

import math

from .cards import FULL_HOUSE, PAIR, STRAIGHT, TRIPS, TWO_PAIR
from .engine import CALL, CHECK, FOLD, PREFLOP, RAISE, RIVER, FLOP, TURN, Obs
from .equity import (hand_percentile, p_beat_one, preflop_equity, equity)
from .features import Profile, profile, strength_bucket, texture
from .icm import icm_equity, risk_premium

# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def size_to(obs: Obs, pot_fraction: float) -> int:
    """Total street bet corresponding to betting ``pot_fraction`` of the pot."""
    pot_after_call = obs.pot + obs.to_call
    target = (obs.street_bets[obs.seat] + obs.to_call
              + int(round(pot_after_call * pot_fraction)))
    return int(max(obs.min_raise_to, min(target, obs.max_raise_to)))


def bb_to(obs: Obs, bbs: float) -> int:
    return int(max(obs.min_raise_to, min(round(bbs * obs.bb), obs.max_raise_to)))


def preflop_context(obs: Obs) -> dict:
    """Who has done what before us, preflop."""
    acts = obs.street_actions(PREFLOP)
    raises = [a for a in acts if a.kind == RAISE]
    limps = [a for a in acts if a.kind == CALL and a.to_amount == obs.bb]
    order = [(s - obs.button - 1) % len(obs.stacks) for s in range(len(obs.stacks))]
    mine = order[obs.seat]
    to_act_after = sum(
        1 for s in range(len(obs.stacks))
        if obs.in_hand[s] and s != obs.seat and order[s] > mine
        and not any(a.seat == s for a in acts)
    )
    return {
        "n_raises": len(raises),
        "raisers": [a.seat for a in raises],
        "last_raise_to": raises[-1].to_amount if raises else obs.bb,
        "limpers": len(limps),
        "to_act_after": to_act_after,
        "open_shove": bool(raises) and raises[-1].allin,
        "is_bb": obs.seat != obs.button and obs.street_bets[obs.seat] == obs.bb
                 and not acts,
    }


def position_factor(obs: Obs) -> float:
    """0.0 = worst position preflop (UTG), 1.0 = button."""
    n = len(obs.stacks)
    live = [s for s in range(n) if obs.dealt[s] and obs.stacks[s] + obs.committed[s] > 0]
    if len(live) <= 1:
        return 1.0
    order = sorted(live, key=lambda s: (s - obs.button - 1) % n)
    return order.index(obs.seat) / (len(order) - 1)


def effective_bb(obs: Obs) -> float:
    return obs.effective_stack() / max(1, obs.bb)


class Strategy:
    """Base class: seat identity, RNG, and no-op observation hooks."""

    name = "strategy"
    blurb = ""

    def __init__(self, seat: int, n_players: int, rng):
        self.seat = seat
        self.n = n_players
        self.rng = rng

    def act(self, obs: Obs):  # pragma: no cover - abstract
        raise NotImplementedError

    def observe(self, event):
        pass

    # convenience -----------------------------------------------------
    def equity(self, obs: Obs) -> float:
        return equity(obs.hole, obs.board, max(1, obs.n_opponents))

    def check_or_fold(self, obs: Obs):
        return (CHECK, 0) if obs.to_call == 0 else (FOLD, 0)

    def call_or_check(self, obs: Obs):
        return (CALL, 0) if obs.to_call > 0 else (CHECK, 0)

    def shove(self, obs: Obs):
        if obs.can_raise:
            return (RAISE, obs.max_raise_to)
        return self.call_or_check(obs)


# ==========================================================================
# Seat 1 -- the whole brief, verbatim
# ==========================================================================

class AllInBot(Strategy):
    """if my_turn then bet = All in fi"""

    name = "JAM-O-TRON"
    blurb = "if my_turn: bet = ALL IN"

    def act(self, obs: Obs):
        if obs.can_raise:
            return (RAISE, obs.max_raise_to)   # shove
        return (CALL, 0)                       # already all-in for less: call


# ==========================================================================
# Seat 2 -- balanced / GTO-flavoured
# ==========================================================================

class SolverLite(Strategy):
    """Range-based, frequency-balanced, hard to exploit.

    Preflop it plays percentile ranges by position and by how many raises are
    already in.  Postflop it derives a value threshold from the number of
    opponents, defends at (close to) minimum-defence frequency, and bluffs at
    the pot-odds-neutral alpha = b / (1 + 2b) for its chosen bet size, so its
    bluff-to-value ratio stays indifferent-making.
    """

    name = "SOLVERLITE"
    blurb = "range charts + MDF + alpha-balanced bluffs, mixed frequencies"

    # top-x% opening ranges, by position factor bucket
    RFI = (0.16, 0.19, 0.23, 0.28, 0.36, 0.48)
    THREEBET = 0.075
    THREEBET_BLUFF = 0.055        # extra hands used as balanced 3bet bluffs
    FOURBET = 0.030
    CALL_OPEN = 0.24

    def act(self, obs: Obs):
        if obs.street == PREFLOP:
            return self._preflop(obs)
        return self._postflop(obs)

    # -- preflop ------------------------------------------------------
    def _preflop(self, obs: Obs):
        ctx = preflop_context(obs)
        pct = hand_percentile(obs.hole)
        pos = position_factor(obs)
        eff = effective_bb(obs)

        # short stacks collapse the tree to push/fold
        if eff <= 11:
            thresh = 0.10 + 0.30 * pos + 0.02 * max(0, 12 - eff)
            if ctx["n_raises"] == 0:
                return self.shove(obs) if pct <= thresh else self.check_or_fold(obs)
            return (CALL, 0) if pct <= thresh * 0.45 else self.check_or_fold(obs)

        if ctx["n_raises"] == 0:
            idx = min(len(self.RFI) - 1, int(pos * len(self.RFI)))
            open_pct = self.RFI[idx] + 0.05 * ctx["limpers"]
            if pct <= open_pct:
                return (RAISE, bb_to(obs, 2.5 + ctx["limpers"]))
            if obs.to_call == 0:
                return (CHECK, 0)
            # blind defence: price is good, defend wide from the big blind
            if ctx["is_bb"] and pct <= 0.55:
                return (CALL, 0)
            return (FOLD, 0)

        if ctx["n_raises"] == 1:
            # value 3bet / balanced 3bet bluff / flat / fold
            if pct <= self.THREEBET:
                return (RAISE, size_to(obs, 0.95 if pos > 0.5 else 1.25))
            if pct <= self.THREEBET + self.THREEBET_BLUFF and pos > 0.55 \
                    and self.rng.random() < 0.45:
                return (RAISE, size_to(obs, 0.95))
            if pct <= self.CALL_OPEN and obs.pot_odds() < 0.33:
                return (CALL, 0)
            return self.check_or_fold(obs)

        # facing a 3bet or worse
        if pct <= self.FOURBET:
            return (RAISE, size_to(obs, 0.85))
        if pct <= 0.09 and obs.pot_odds() < 0.30:
            return (CALL, 0)
        return self.check_or_fold(obs)

    # -- postflop -----------------------------------------------------
    def _postflop(self, obs: Obs):
        prof = profile(obs.hole, obs.board)
        tex = texture(obs.board)
        n = max(1, obs.n_opponents)
        eq = prof.p1 ** n
        # multiway pots need a stronger hand to bet for value
        value_line = 0.58 + 0.06 * (n - 1)
        aggressor = obs.is_aggressor()
        i_am_aggressor = aggressor == obs.seat or (
            aggressor is None and obs.street > FLOP)

        if obs.to_call == 0:
            size = 0.34 if tex.wetness < 0.35 else 0.70
            if eq >= value_line:
                if eq > 0.9 and self.rng.random() < 0.25:
                    return (CHECK, 0)              # occasional slowplay
                return (RAISE, size_to(obs, size)) if obs.can_raise else (CHECK, 0)
            # balanced bluffing: alpha = b/(1+2b) of our checking range
            alpha = size / (1 + 2 * size)
            bluffable = prof.has_draw or prof.overcards == 2 or prof.nut_flush_draw
            if bluffable and obs.can_raise and self.rng.random() < alpha * 1.6:
                return (RAISE, size_to(obs, size))
            return (CHECK, 0)

        # facing a bet: minimum defence frequency vs. the price offered
        price = obs.pot_odds()
        bet = obs.to_call
        pot_before = obs.pot - bet
        b = bet / max(1, pot_before)
        mdf = 1.0 / (1.0 + b)
        need = price + 0.02 * (n - 1)

        if eq >= max(0.72, need + 0.22) and obs.can_raise:
            return (RAISE, size_to(obs, 0.85))
        if eq >= need:
            return (CALL, 0)
        # bluff-raise a slice of our worst-but-with-outs hands, at frequency
        # alpha, so that our raising range stays balanced
        if prof.strong_draw and obs.can_raise and self.rng.random() < 0.28:
            return (RAISE, size_to(obs, 0.9))
        # defend the required frequency with our best folding candidates
        if eq >= need * 0.82 and self.rng.random() < mdf * 0.45:
            return (CALL, 0)
        return (FOLD, 0)


# ==========================================================================
# Seat 3 -- Bayesian opponent modelling
# ==========================================================================

class _OppModel:
    """Beta posteriors over one opponent's action frequencies."""

    def __init__(self):
        self.hands = 0
        self.vpip = [1.0, 3.0]        # alpha, beta
        self.pfr = [1.0, 4.0]
        self.agg = [1.0, 2.0]         # bet/raise vs check/call postflop
        self.fold_to_bet = [1.0, 2.0]
        self.allin = [0.5, 6.0]
        self.showdown_pct = []
        self.acted_pre = False
        self.raised_pre = False

    @staticmethod
    def _p(beta_pair):
        a, b = beta_pair
        return a / (a + b)

    @property
    def p_vpip(self):
        return self._p(self.vpip)

    @property
    def p_pfr(self):
        return self._p(self.pfr)

    @property
    def p_agg(self):
        return self._p(self.agg)

    @property
    def p_fold(self):
        return self._p(self.fold_to_bet)

    @property
    def p_allin(self):
        return self._p(self.allin)

    @property
    def confidence(self):
        return min(1.0, (self.vpip[0] + self.vpip[1] - 4.0) / 25.0)

    def label(self):
        v, a = self.p_vpip, self.p_agg
        if self.p_allin > 0.6:
            return "kamikaze"
        if v > 0.72 and a > 0.6:
            return "maniac"
        if v > 0.55 and a < 0.35:
            return "station"
        if v < 0.20:
            return "nit"
        if a > 0.5:
            return "lag"
        return "tag"

    def range_width(self, street, is_raise, size_frac):
        """Estimated fraction of hands this opponent takes this line with."""
        if street == PREFLOP:
            w = self.p_pfr if is_raise else self.p_vpip
        else:
            w = self.p_agg if is_raise else 0.55
        # shade toward a sane prior while the sample is small
        prior = 0.20 if is_raise else 0.45
        c = self.confidence
        w = c * w + (1 - c) * prior
        # bigger bets are (slightly) more polarised toward strength
        w *= max(0.55, 1.25 - 0.35 * min(2.0, size_frac))
        return min(1.0, max(0.03, w))


class BayesianExploiter(Strategy):
    """Maximally exploitative: re-prices equity against a modelled range.

    For each opponent it keeps Beta posteriors over VPIP, PFR, postflop
    aggression, fold-to-bet and all-in frequency.  A player who raises with
    100% of hands is *measured* to have a 100%-wide range, so their all-in is
    priced against random cards -- which is exactly how you punish a shove-bot
    without ever being told that it is one.
    """

    name = "BAYES-EXPLOIT"
    blurb = "Beta posteriors per seat -> range width -> re-priced equity + EV lines"

    def __init__(self, seat, n_players, rng):
        super().__init__(seat, n_players, rng)
        self.models = {i: _OppModel() for i in range(n_players)}

    # -- observation --------------------------------------------------
    def observe(self, event):
        t = event.get("type")
        if t == "hand_start":
            for i, m in self.models.items():
                m.acted_pre = False
                m.raised_pre = False
                if event["dealt"][i]:
                    m.hands += 1
            return
        if t == "hand_end":
            for seat, hole in (event.get("shown") or {}).items():
                if seat != self.seat:
                    self.models[seat].showdown_pct.append(hand_percentile(hole))
            return
        if t != "action":
            return
        rec = event["record"]
        if rec.seat == self.seat:
            return
        m = self.models[rec.seat]
        street = rec.street
        if street == PREFLOP:
            if not m.acted_pre:
                m.acted_pre = True
                voluntary = rec.kind in (CALL, RAISE)
                m.vpip[0 if voluntary else 1] += 1
                m.pfr[0 if rec.kind == RAISE else 1] += 1
        else:
            if rec.kind == RAISE:
                m.agg[0] += 1
            elif rec.kind in (CALL, CHECK):
                m.agg[1] += 1
            if rec.to_call > 0:
                m.fold_to_bet[0 if rec.kind == FOLD else 1] += 1
        if rec.kind == RAISE:
            m.allin[0 if rec.allin else 1] += 1

    # -- modelled equity ----------------------------------------------
    def _modelled_equity(self, obs: Obs) -> float:
        if obs.board:
            p1 = p_beat_one(obs.hole, obs.board)
        else:
            p1 = preflop_equity(obs.hole, 1)
        pot_before = max(1, obs.pot - obs.to_call)
        eq = 1.0
        for s in obs.opponents:
            m = self.models[s]
            acts = [a for a in obs.history if a.seat == s and a.street == obs.street]
            is_raise = any(a.kind == RAISE for a in acts)
            size_frac = (max((a.amount for a in acts), default=0) / pot_before
                         if acts else 0.4)
            w = m.range_width(obs.street, is_raise, size_frac)
            # equity against the top-w slice of hands ~= p1 ** (1 + k(1-w))
            exponent = 1.0 + 1.7 * (1.0 - w)
            eq *= p1 ** exponent
        return eq

    def _fold_equity(self, obs: Obs, size_frac: float) -> float:
        p = 1.0
        for s in obs.opponents:
            if obs.all_in[s]:
                return 0.0
            m = self.models[s]
            base = m.p_fold if m.confidence > 0.25 else 0.42
            adj = base * (0.55 + 0.45 * min(1.8, size_frac))
            if obs.street == PREFLOP:
                adj *= 0.8
            p *= min(0.94, max(0.02, adj))
        return p

    # -- decisions ----------------------------------------------------
    def act(self, obs: Obs):
        eq = self._modelled_equity(obs)
        price = obs.pot_odds()
        eff = effective_bb(obs)

        # facing an all-in: pure EV call, priced against the modelled range
        facing_shove = obs.to_call > 0 and any(
            obs.all_in[s] and obs.committed[s] > obs.committed[obs.seat]
            for s in obs.opponents)
        if facing_shove and obs.to_call >= obs.stacks[obs.seat] * 0.55:
            edge = 0.015 if obs.n_players_left > 3 else 0.0
            return (CALL, 0) if eq > price + edge else (FOLD, 0)

        if obs.street == PREFLOP:
            return self._preflop(obs, eq, eff)
        return self._postflop(obs, eq, price)

    def _preflop(self, obs: Obs, eq, eff):
        ctx = preflop_context(obs)
        pct = hand_percentile(obs.hole)
        pos = position_factor(obs)

        if eff <= 12 and ctx["n_raises"] == 0:
            if pct <= 0.14 + 0.32 * pos:
                return self.shove(obs)
            return self.check_or_fold(obs)

        if ctx["n_raises"] == 0:
            # open wider against seats that fold a lot, tighter into callers
            fold_est = 1.0
            for s in obs.opponents:
                m = self.models[s]
                fold_est *= (1 - m.p_vpip) if m.confidence > 0.2 else 0.72
            width = 0.18 + 0.30 * pos + 0.35 * fold_est
            if pct <= min(0.62, width):
                return (RAISE, bb_to(obs, 2.4 + ctx["limpers"]))
            return self.check_or_fold(obs)

        raiser = ctx["raisers"][-1]
        m = self.models[raiser]
        w = m.range_width(PREFLOP, True, obs.to_call / max(1, obs.pot - obs.to_call))
        # their range is wide -> our equity is real -> get it in
        thresh = 0.06 + 0.42 * w
        if pct <= thresh * 0.45 and obs.can_raise:
            return (RAISE, size_to(obs, 1.0))
        if pct <= thresh and obs.pot_odds() < 0.40:
            return (CALL, 0)
        if eq > obs.pot_odds() + 0.06 and obs.pot_odds() < 0.33:
            return (CALL, 0)
        return self.check_or_fold(obs)

    def _postflop(self, obs: Obs, eq, price):
        prof = profile(obs.hole, obs.board)
        pot_before = max(1, obs.pot - obs.to_call)

        if obs.to_call == 0:
            best = (CHECK, 0)
            best_ev = 0.0
            for frac in (0.33, 0.66, 1.1):
                bet = int(frac * obs.pot)
                if bet <= 0 or bet > obs.stacks[obs.seat]:
                    continue
                fe = self._fold_equity(obs, frac)
                ev = fe * obs.pot + (1 - fe) * (eq * (obs.pot + 2 * bet) - bet)
                if ev > best_ev + 1e-9:
                    best_ev, best = ev, (RAISE, size_to(obs, frac))
            if best[0] == RAISE and obs.can_raise:
                return best
            return (CHECK, 0)

        ev_call = eq * (obs.pot + obs.to_call) - obs.to_call
        best = (FOLD, 0) if ev_call < 0 else (CALL, 0)
        best_ev = max(0.0, ev_call)
        if obs.can_raise:
            for frac in (0.7, 1.2):
                bet = int(frac * obs.pot)
                if bet + obs.to_call > obs.stacks[obs.seat]:
                    continue
                fe = self._fold_equity(obs, frac)
                total = obs.to_call + bet
                ev = fe * obs.pot + (1 - fe) * (
                    eq * (obs.pot + 2 * total) - total)
                if ev > best_ev + 1e-9:
                    best_ev, best = ev, (RAISE, size_to(obs, frac))
        if best[0] == FOLD and prof.strong_draw and price < 0.25:
            return (CALL, 0)
        return best


# ==========================================================================
# Seat 4 -- ICM / push-fold
# ==========================================================================

class ICMNash(Strategy):
    """Plays the payout ladder: Nash-ish push/fold plus ICM risk premiums.

    Short: an effective-stack push/fold chart.  Medium: Harrington M zones.
    Deep: tight-aggressive with pot control.  Every all-in decision is priced
    with a Malmuth-Harville risk premium instead of raw pot odds, so it needs
    a real edge before putting its tournament life in.
    """

    name = "ICM-GRINDER"
    blurb = "push/fold charts + Harrington M zones + Malmuth-Harville risk premium"

    def act(self, obs: Obs):
        eff = effective_bb(obs)
        m_ratio = obs.stacks[obs.seat] / max(1, obs.sb + obs.bb + obs.ante * obs.n_players_left)

        if obs.to_call > 0 and obs.to_call >= obs.stacks[obs.seat] * 0.6:
            return self._call_off(obs)

        if obs.street == PREFLOP:
            return self._preflop(obs, eff, m_ratio)
        return self._postflop(obs, m_ratio)

    # -- all-in pricing ------------------------------------------------
    def _call_off(self, obs: Obs):
        stacks = [obs.stacks[s] + obs.committed[s] for s in range(len(obs.stacks))]
        need = risk_premium(stacks, obs.seat,
                            risk=min(obs.to_call, obs.stacks[obs.seat]),
                            reward=obs.pot)
        pot_need = obs.pot_odds()
        # blend: pot odds set the floor, ICM adds the survival tax
        required = max(pot_need, 0.45 * pot_need + 0.55 * need)
        eq = self.equity(obs)
        return (CALL, 0) if eq >= required else self.check_or_fold(obs)

    # -- preflop -------------------------------------------------------
    def _preflop(self, obs: Obs, eff, m_ratio):
        ctx = preflop_context(obs)
        pct = hand_percentile(obs.hole)
        pos = position_factor(obs)

        if eff <= 13:
            # push/fold zone: threshold widens as the stack shrinks
            base = 0.055 + 0.055 * max(0.0, 14 - eff)
            thresh = min(0.85, base * (0.55 + 0.9 * pos))
            thresh /= max(1.0, 1.0 + 0.25 * ctx["to_act_after"])
            if ctx["n_raises"] == 0:
                if pct <= thresh:
                    return self.shove(obs)
                return self.check_or_fold(obs)
            if pct <= thresh * 0.40:
                return self.shove(obs)
            return self.check_or_fold(obs)

        if m_ratio < 10:      # Harrington orange/yellow: raise or fold
            thresh = 0.13 + 0.22 * pos
            if ctx["n_raises"] == 0 and pct <= thresh:
                return (RAISE, bb_to(obs, 2.2))
            if ctx["n_raises"] >= 1 and pct <= 0.05:
                return self.shove(obs)
            return self.check_or_fold(obs)

        # green zone: tight-aggressive
        if ctx["n_raises"] == 0:
            if pct <= 0.12 + 0.20 * pos:
                return (RAISE, bb_to(obs, 2.5 + ctx["limpers"]))
            return self.check_or_fold(obs)
        if pct <= 0.045:
            return (RAISE, size_to(obs, 1.0))
        if pct <= 0.16 and obs.pot_odds() < 0.22:
            return (CALL, 0)
        return self.check_or_fold(obs)

    # -- postflop ------------------------------------------------------
    def _postflop(self, obs: Obs, m_ratio):
        prof = profile(obs.hole, obs.board)
        tex = texture(obs.board)
        n = max(1, obs.n_opponents)
        eq = prof.p1 ** n
        bucket = strength_bucket(prof)

        if obs.to_call == 0:
            if bucket in ("monster", "strong"):
                frac = 0.75 if tex.wetness > 0.4 else 0.55
                return (RAISE, size_to(obs, frac)) if obs.can_raise else (CHECK, 0)
            if bucket == "good" and n <= 2 and obs.can_raise:
                return (RAISE, size_to(obs, 0.5))
            if bucket == "draw" and obs.can_raise and self.rng.random() < 0.35:
                return (RAISE, size_to(obs, 0.5))
            return (CHECK, 0)

        price = obs.pot_odds()
        # survival tax: needs more than the raw price to continue for big bets
        tax = 0.03 + 0.09 * min(1.0, obs.to_call / max(1, obs.stacks[obs.seat]))
        if bucket == "monster" and obs.can_raise:
            return (RAISE, size_to(obs, 0.9))
        if bucket == "strong":
            if obs.can_raise and eq > 0.78 and self.rng.random() < 0.6:
                return (RAISE, size_to(obs, 0.8))
            return (CALL, 0)
        if eq >= price + tax:
            return (CALL, 0)
        if prof.strong_draw and price < 0.28:
            return (CALL, 0)
        return (FOLD, 0)


# ==========================================================================
# Seat 5 -- loose-aggressive pressure
# ==========================================================================

class PressureLAG(Strategy):
    """Relentless pressure with an explicit fold-equity model.

    Opens wide, three-bets light in position, and barrels turns and rivers
    when the model says the pot is winnable without a showdown.  Overbets
    polarised rivers.  The discipline valve stops it from stacking off with
    air when the money actually goes in.
    """

    name = "PRESSURE-LAG"
    blurb = "wide opens, fold-equity model, multi-barrel bluffs, polarised overbets"

    def __init__(self, seat, n_players, rng):
        super().__init__(seat, n_players, rng)
        self.barrels = 0
        self.folds_seen = [1.0, 1.4]

    def observe(self, event):
        if event.get("type") == "hand_start":
            self.barrels = 0
        elif event.get("type") == "action":
            rec = event["record"]
            if rec.seat != self.seat and rec.to_call > 0:
                self.folds_seen[0 if rec.kind == FOLD else 1] += 1

    @property
    def table_fold_rate(self):
        a, b = self.folds_seen
        return a / (a + b)

    def _fold_equity(self, obs: Obs, frac: float) -> float:
        base = 0.35 + 0.55 * self.table_fold_rate
        sizing = 0.55 + 0.45 * min(1.6, frac)
        street = (0.72, 0.95, 1.05, 1.12)[obs.street]
        p = min(0.93, base * sizing * street * 0.75)
        live = [s for s in obs.opponents if not obs.all_in[s]]
        return p ** max(1, len(live))

    def act(self, obs: Obs):
        if obs.street == PREFLOP:
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs: Obs):
        ctx = preflop_context(obs)
        pct = hand_percentile(obs.hole)
        pos = position_factor(obs)
        eff = effective_bb(obs)

        if eff <= 10:
            if pct <= 0.24 + 0.36 * pos:
                return self.shove(obs)
            return self.check_or_fold(obs)

        if ctx["n_raises"] == 0:
            width = 0.30 + 0.30 * pos
            if pct <= width:
                return (RAISE, bb_to(obs, 2.3 + ctx["limpers"]))
            if obs.to_call == 0:
                return (CHECK, 0)
            if ctx["is_bb"] and pct <= 0.72:
                return (CALL, 0)
            return (FOLD, 0)

        if ctx["n_raises"] == 1:
            if pct <= 0.10:
                return (RAISE, size_to(obs, 1.1))
            # light 3bets in position, at a controlled frequency
            if pos > 0.5 and pct <= 0.34 and self.rng.random() < 0.42:
                return (RAISE, size_to(obs, 1.0))
            if pct <= 0.30 and obs.pot_odds() < 0.32:
                return (CALL, 0)
            return self.check_or_fold(obs)

        if pct <= 0.05:
            return (RAISE, size_to(obs, 0.9))
        if pct <= 0.13 and obs.pot_odds() < 0.30:
            return (CALL, 0)
        return self.check_or_fold(obs)

    def _postflop(self, obs: Obs):
        prof = profile(obs.hole, obs.board)
        tex = texture(obs.board)
        n = max(1, obs.n_opponents)
        eq = prof.p1 ** n
        bucket = strength_bucket(prof)

        # discipline valve: never stack off without real equity
        if obs.to_call >= obs.stacks[obs.seat] * 0.7:
            return (CALL, 0) if eq >= obs.pot_odds() + 0.04 else self.check_or_fold(obs)

        if obs.to_call == 0:
            if bucket in ("monster", "strong"):
                frac = 1.35 if (obs.street == RIVER and self.rng.random() < 0.4) else 0.8
                return (RAISE, size_to(obs, frac)) if obs.can_raise else (CHECK, 0)
            if bucket in ("good", "draw"):
                return (RAISE, size_to(obs, 0.65)) if obs.can_raise else (CHECK, 0)
            frac = 0.6 if tex.wetness > 0.45 else 0.45
            fe = self._fold_equity(obs, frac)
            bet = frac * obs.pot
            ev_bluff = fe * obs.pot - (1 - fe) * bet * (1 - eq * 2.2)
            if obs.can_raise and ev_bluff > 0 and self.barrels < 3 \
                    and self.rng.random() < 0.72:
                self.barrels += 1
                return (RAISE, size_to(obs, frac))
            return (CHECK, 0)

        price = obs.pot_odds()
        if bucket == "monster" and obs.can_raise:
            return (RAISE, size_to(obs, 1.0))
        if bucket == "strong" and obs.can_raise and self.rng.random() < 0.7:
            return (RAISE, size_to(obs, 0.85))
        if prof.strong_draw and obs.can_raise and price < 0.35 \
                and self.rng.random() < 0.45:
            return (RAISE, size_to(obs, 0.9))          # semi-bluff raise
        if eq >= price + 0.01:
            return (CALL, 0)
        if price < 0.18 and prof.has_draw:
            return (CALL, 0)
        return (FOLD, 0)


# ==========================================================================
# Seat 6 -- the rock that traps
# ==========================================================================

class TrapRock(Strategy):
    """Ultra-tight, trap-heavy, and very hard to bluff.

    Plays roughly the top 12% preflop, then lets aggressive opponents bet
    into its monsters: it checks strong hands to induce, check-raises on
    later streets, pot-controls medium hands, and calls down when the price
    is right against opponents it has seen bet too often.
    """

    name = "TRAP-ROCK"
    blurb = "top-12% ranges, induced bluffs, check-raise traps, disciplined call-downs"

    def __init__(self, seat, n_players, rng):
        super().__init__(seat, n_players, rng)
        self.trap_street = -1
        self.aggression_seen = [1.0, 2.0]

    def observe(self, event):
        t = event.get("type")
        if t == "hand_start":
            self.trap_street = -1
        elif t == "action":
            rec = event["record"]
            if rec.seat != self.seat and rec.street > PREFLOP:
                self.aggression_seen[0 if rec.kind == RAISE else 1] += 1

    @property
    def table_aggression(self):
        a, b = self.aggression_seen
        return a / (a + b)

    def act(self, obs: Obs):
        if obs.street == PREFLOP:
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs: Obs):
        ctx = preflop_context(obs)
        pct = hand_percentile(obs.hole)
        pos = position_factor(obs)
        eff = effective_bb(obs)

        if eff <= 9:
            if pct <= 0.18 + 0.26 * pos:
                return self.shove(obs)
            return self.check_or_fold(obs)

        # against an all-in, only premiums
        if ctx["open_shove"] and obs.to_call > obs.stacks[obs.seat] * 0.4:
            eq = self.equity(obs)
            need = obs.pot_odds() + (0.06 if obs.n_players_left > 3 else 0.02)
            return (CALL, 0) if eq >= need else self.check_or_fold(obs)

        if ctx["n_raises"] == 0:
            if pct <= 0.09 + 0.09 * pos:
                # trap with the very best hands some of the time
                if pct <= 0.02 and ctx["to_act_after"] >= 2 \
                        and self.rng.random() < 0.30:
                    return self.call_or_check(obs)
                return (RAISE, bb_to(obs, 2.6 + ctx["limpers"]))
            if obs.to_call == 0:
                return (CHECK, 0)
            if pct <= 0.22 and obs.pot_odds() < 0.12:
                return (CALL, 0)
            return (FOLD, 0)

        if pct <= 0.025:
            return (RAISE, size_to(obs, 0.95)) if obs.can_raise else (CALL, 0)
        if pct <= 0.10 and obs.pot_odds() < 0.28:
            return (CALL, 0)
        return self.check_or_fold(obs)

    def _postflop(self, obs: Obs):
        prof = profile(obs.hole, obs.board)
        tex = texture(obs.board)
        n = max(1, obs.n_opponents)
        eq = prof.p1 ** n
        bucket = strength_bucket(prof)
        aggressive_table = self.table_aggression > 0.42

        if obs.to_call == 0:
            if bucket == "monster" or (bucket == "strong" and eq > 0.85):
                # induce: check the flop/turn, then check-raise
                if obs.street < RIVER and aggressive_table and self.trap_street < 0 \
                        and tex.wetness < 0.55 and self.rng.random() < 0.65:
                    self.trap_street = obs.street
                    return (CHECK, 0)
                return (RAISE, size_to(obs, 0.7)) if obs.can_raise else (CHECK, 0)
            if bucket == "good" and n == 1 and obs.can_raise:
                return (RAISE, size_to(obs, 0.45))
            return (CHECK, 0)

        price = obs.pot_odds()
        if bucket == "monster" and obs.can_raise:
            return (RAISE, size_to(obs, 1.0))
        if bucket == "strong":
            if obs.can_raise and (self.trap_street >= 0 or eq > 0.8):
                return (RAISE, size_to(obs, 0.9))       # the trap springs
            return (CALL, 0)
        if bucket == "good":
            # pot control: call one bet, fold to big pressure on scary boards
            if price <= 0.34 and (eq >= price + 0.06 or aggressive_table):
                return (CALL, 0)
            return (FOLD, 0)
        if prof.strong_draw and price <= 0.30:
            return (CALL, 0)
        if eq >= price + 0.10:
            return (CALL, 0)
        return (FOLD, 0)


ELABORATE = (SolverLite, BayesianExploiter, ICMNash, PressureLAG, TrapRock)
ROSTER = (AllInBot,) + ELABORATE


def default_lineup():
    """Seat 1 = the simple all-in bot, seats 2..6 = the elaborate five."""
    return list(ROSTER)
