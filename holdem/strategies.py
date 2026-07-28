"""Six poker brains. Players 2-6 get elaborate strategies; Player 1 gets:

    if my_turn
    then bet = All in
    fi

No strategy knows any other's algorithm — the only shared information is
what happens at the table (public actions), exactly like a real game.
"""

from .cards import chen, estimate_equity, preflop_equity


def pot_odds(to_call, pot):
    return to_call / (pot + to_call) if to_call > 0 else 0.0


class Strategy:
    name = "?"

    def __init__(self, rng):
        self.rng = rng

    def observe(self, ev):
        pass

    def act(self, v):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, verbatim:
#     if my_turn then bet = All in fi
# ---------------------------------------------------------------------------
class AllInAndy(Strategy):
    name = "All-In Andy"

    def act(self, v):
        my_turn = True
        if my_turn:
            return ("raise", v.my_round_bet + v.stack)  # bet = All in
        # fi


# ---------------------------------------------------------------------------
# Player 2 — Tight-Aggressive: positional Chen-formula ranges preflop,
# Monte-Carlo equity vs pot odds postflop, semi-bluffs, push/fold when short.
# ---------------------------------------------------------------------------
class TagTanya(Strategy):
    name = "TAG Tanya"

    def act(self, v):
        return self._preflop(v) if v.stage == "preflop" else self._postflop(v)

    def _preflop(self, v):
        score = chen(v.hole)
        open_thr = 9.0 - 3.0 * v.pos_frac          # tight early, looser late

        if v.stack <= 8 * v.bb:                    # short stack: push/fold
            if score >= 7.5 or preflop_equity(v.hole, min(v.n_opp, 2)) > 0.50:
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if v.to_call == 0 else ("fold",)

        if v.to_call == 0:                         # BB option / checked to
            if score >= 8:
                return ("raise", v.current_bet + max(v.min_raise, 3 * v.bb))
            return ("call",)

        if v.to_call > 4 * v.bb or v.to_call >= 0.5 * v.stack:
            # big raise or shove in front: commitment decision on real equity
            eq = preflop_equity(v.hole, min(v.n_opp, 2))
            need = pot_odds(v.to_call, v.pot) + 0.06
            if eq >= 0.62:
                return ("raise", v.my_round_bet + v.stack)  # premium: get it in
            return ("call",) if eq >= need else ("fold",)

        if score >= 10:                            # 3-bet the good stuff
            return ("raise", 3 * v.current_bet)
        if score >= open_thr:
            return ("raise", v.current_bet + max(v.min_raise, 3 * v.bb)) \
                if v.current_bet <= v.bb else ("call",)
        if score >= open_thr - 2 and v.to_call <= 2 * v.bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        eq = estimate_equity(v.hole, v.board, v.n_opp, 50, self.rng)
        po = pot_odds(v.to_call, v.pot)
        if v.to_call == 0:
            if eq > 0.62:
                return ("raise", int(0.65 * v.pot) or v.bb)
            if 0.44 < eq <= 0.62 and self.rng.random() < 0.35:
                return ("raise", int(0.5 * v.pot) or v.bb)   # probe/semi-bluff
            return ("call",)
        if eq > 0.72:
            return ("raise", v.current_bet + max(v.min_raise, int(0.8 * v.pot)))
        if eq >= po + 0.03:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 3 — Loose-Aggressive: wide opens, light 3-bets, relentless barrels,
# bluff frequency scaled to number of opponents left in the hand.
# ---------------------------------------------------------------------------
class LagLars(Strategy):
    name = "LAG Lars"

    def act(self, v):
        return self._preflop(v) if v.stage == "preflop" else self._postflop(v)

    def _preflop(self, v):
        score = chen(v.hole)
        open_thr = 7.0 - 3.0 * v.pos_frac

        if v.stack <= 8 * v.bb:
            if score >= 6.5:
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if v.to_call == 0 else ("fold",)

        if v.to_call == 0:
            if score >= 6 or self.rng.random() < 0.15:
                return ("raise", v.current_bet + max(v.min_raise, 3 * v.bb))
            return ("call",)

        if v.to_call > 4 * v.bb or v.to_call >= 0.5 * v.stack:
            eq = preflop_equity(v.hole, min(v.n_opp, 2))
            if eq >= 0.60:
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if eq >= pot_odds(v.to_call, v.pot) + 0.04 else ("fold",)

        if score >= 9 or (score >= 5 and self.rng.random() < 0.12):
            return ("raise", 3 * v.current_bet)     # value 3-bet or light 3-bet
        if score >= open_thr:
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        eq = estimate_equity(v.hole, v.board, v.n_opp, 50, self.rng)
        po = pot_odds(v.to_call, v.pot)
        bluff_freq = 0.45 / max(1, v.n_opp)         # bully small fields
        if v.to_call == 0:
            if eq > 0.55:
                return ("raise", int(0.75 * v.pot) or v.bb)
            if self.rng.random() < bluff_freq:
                return ("raise", int(0.65 * v.pot) or v.bb)
            return ("call",)
        if eq > 0.65:
            return ("raise", v.current_bet + max(v.min_raise, v.pot))
        if self.rng.random() < 0.08 and v.to_call < 0.3 * v.stack:
            return ("raise", v.current_bet + max(v.min_raise, v.pot))  # bluff-raise
        if eq >= po - 0.02:                          # sticky caller
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 4 — The Rock: folds almost everything, only fights with premiums,
# never bluffs. The classic nit who waits for aces while blinds eat them.
# ---------------------------------------------------------------------------
class RockRita(Strategy):
    name = "Rock Rita"

    def act(self, v):
        return self._preflop(v) if v.stage == "preflop" else self._postflop(v)

    def _preflop(self, v):
        score = chen(v.hole)
        if v.stack <= 6 * v.bb and score >= 8:
            return ("raise", v.my_round_bet + v.stack)
        if v.to_call == 0:
            if score >= 10:
                return ("raise", v.current_bet + max(v.min_raise, 4 * v.bb))
            return ("call",)
        if v.to_call > 4 * v.bb or v.to_call >= 0.5 * v.stack:
            eq = preflop_equity(v.hole, min(v.n_opp, 2))
            need = max(0.55, pot_odds(v.to_call, v.pot) + 0.08)
            if eq >= 0.66:
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if eq >= need else ("fold",)
        if score >= 11:
            return ("raise", 3 * v.current_bet)
        if score >= 10:
            return ("raise", v.current_bet + max(v.min_raise, 4 * v.bb)) \
                if v.current_bet <= v.bb else ("call",)
        return ("fold",)

    def _postflop(self, v):
        eq = estimate_equity(v.hole, v.board, v.n_opp, 50, self.rng)
        po = pot_odds(v.to_call, v.pot)
        if v.to_call == 0:
            if eq > 0.75:
                return ("raise", v.pot or v.bb)
            return ("call",)
        if eq > 0.80:
            return ("raise", v.current_bet + max(v.min_raise, v.pot))
        if eq >= po + 0.10:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 5 — Adaptive/exploitative: profiles every opponent from public
# actions (VPIP, preflop shove rate) and re-prices calls against each
# profile. Learns purely from observed behavior — no inside knowledge.
# ---------------------------------------------------------------------------
class MatrixMax(Strategy):
    name = "Matrix Max"

    def __init__(self, rng):
        super().__init__(rng)
        self.stats = {}   # pid -> {hands, vpip, shoves}
        self._voluntary = set()

    def _s(self, pid):
        return self.stats.setdefault(pid, {"hands": 0, "vpip": 0, "shoves": 0})

    def observe(self, ev):
        t = ev["type"]
        if t == "hand_start":
            self._voluntary = set()
            for pid in ev["pids"]:
                self._s(pid)["hands"] += 1
        elif t == "action" and ev["stage"] == "preflop":
            pid = ev["pid"]
            if ev["kind"] in ("call", "raise") and pid not in self._voluntary:
                self._voluntary.add(pid)
                self._s(pid)["vpip"] += 1
            if ev["kind"] == "raise" and ev["allin"]:
                self._s(pid)["shoves"] += 1

    def _profile(self, pid):
        s = self.stats.get(pid)
        if not s or s["hands"] < 6:
            return None
        return s["vpip"] / s["hands"], s["shoves"] / s["hands"]

    def _call_adjust(self, pid):
        """Extra equity demanded above raw pot odds, given who's betting."""
        prof = self._profile(pid) if pid is not None else None
        if prof is None:
            return 0.10                       # unknown: stay cautious
        vpip, shove = prof
        if shove > 0.40:
            return -0.02                      # maniac shoves ~any two: raw odds
        if vpip > 0.35:
            return 0.04                       # loose: modest respect
        if vpip < 0.18:
            return 0.14                       # tight ranges: big respect
        return 0.08

    def _maniac_in_hand(self, v):
        for pid, _stack, folded, _ai, _rb in v.opponents:
            if not folded:
                prof = self._profile(pid)
                if prof and prof[1] > 0.40:
                    return True
        return False

    def act(self, v):
        return self._preflop(v) if v.stage == "preflop" else self._postflop(v)

    def _preflop(self, v):
        score = chen(v.hole)
        if v.stack <= 8 * v.bb:
            if score >= 7.5:
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if v.to_call == 0 else ("fold",)

        # Trap line: with a maniac still behind, limp the big hands and let
        # them shove into us instead of raising them out.
        if self._maniac_in_hand(v) and v.to_call <= v.bb and score >= 9:
            return ("call",)

        if v.to_call == 0:
            if score >= 8:
                return ("raise", v.current_bet + max(v.min_raise, 3 * v.bb))
            return ("call",)

        if v.to_call > 4 * v.bb or v.to_call >= 0.5 * v.stack:
            eq = preflop_equity(v.hole, min(v.n_opp, 2))
            need = pot_odds(v.to_call, v.pot) + self._call_adjust(v.aggressor_pid)
            if eq >= 0.60 and self._call_adjust(v.aggressor_pid) <= 0:
                return ("raise", v.my_round_bet + v.stack)  # iso-shove the maniac
            return ("call",) if eq >= need else ("fold",)

        if score >= 9.5 - 2.5 * v.pos_frac:
            return ("raise", v.current_bet + max(v.min_raise, 3 * v.bb)) \
                if v.current_bet <= v.bb else ("call",)
        if score >= 6 and v.to_call <= 2 * v.bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        eq = estimate_equity(v.hole, v.board, v.n_opp, 50, self.rng)
        po = pot_odds(v.to_call, v.pot)
        if v.to_call == 0:
            if eq > 0.60:
                return ("raise", int(0.65 * v.pot) or v.bb)
            return ("call",)
        need = po + self._call_adjust(v.aggressor_pid) * 0.7
        if eq > 0.75:
            return ("raise", v.current_bet + max(v.min_raise, int(0.8 * v.pot)))
        if eq >= need:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 6 — GTO-flavored: randomized mixed strategies, balanced value/bluff
# ratios tied to bet sizing, minimum-defense-frequency calls, trap lines.
# ---------------------------------------------------------------------------
class GtoGreta(Strategy):
    name = "GTO Greta"

    def act(self, v):
        return self._preflop(v) if v.stage == "preflop" else self._postflop(v)

    def _preflop(self, v):
        score = chen(v.hole)
        thr = 8.0 - 2.5 * v.pos_frac + self.rng.uniform(-1.0, 1.0)  # mixed edges

        if v.stack <= 8 * v.bb:
            if score >= 7 or (score >= 5.5 and self.rng.random() < 0.3):
                return ("raise", v.my_round_bet + v.stack)
            return ("call",) if v.to_call == 0 else ("fold",)

        if v.to_call == 0:
            if score >= 8 and self.rng.random() < 0.8:
                return ("raise", v.current_bet + max(v.min_raise, int(2.5 * v.bb)))
            return ("call",)

        if v.to_call > 4 * v.bb or v.to_call >= 0.5 * v.stack:
            eq = preflop_equity(v.hole, min(v.n_opp, 2))
            po = pot_odds(v.to_call, v.pot)
            if eq >= po + 0.10:
                return ("raise", v.my_round_bet + v.stack) \
                    if self.rng.random() < 0.5 else ("call",)
            if eq >= po - 0.02:                       # mixed-frequency defend
                return ("call",) if self.rng.random() < 0.5 else ("fold",)
            return ("fold",)

        if score >= 9.5:
            return ("raise", 3 * v.current_bet)
        if score >= thr:
            return ("call",)
        return ("fold",)

    def _postflop(self, v):
        eq = estimate_equity(v.hole, v.board, v.n_opp, 50, self.rng)
        po = pot_odds(v.to_call, v.pot)
        bet = int(0.66 * v.pot) or v.bb
        if v.to_call == 0:
            if eq > 0.65:
                # bet for value most of the time, trap-check the rest
                return ("raise", bet) if self.rng.random() < 0.75 else ("call",)
            if eq < 0.30 and self.rng.random() < 0.28:
                return ("raise", bet)                  # balanced bluff share
            return ("call",)
        if eq > 0.75:
            return ("raise", v.current_bet + max(v.min_raise, bet)) \
                if self.rng.random() < 0.6 else ("call",)
        if eq >= po - 0.02:                            # ~MDF defense
            return ("call",)
        if self.rng.random() < 0.05 and v.to_call < 0.25 * v.stack:
            return ("raise", v.current_bet + max(v.min_raise, v.pot))
        return ("fold",)


# Seat order: Player 1 gets the galaxy-brain one-liner.
LINEUP = [AllInAndy, TagTanya, LagLars, RockRita, MatrixMax, GtoGreta]
