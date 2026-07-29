"""Six sealed poker brains. Nobody sees anybody else's code or cards —
each strategy receives only a public `view` (its own hole cards, the board,
stacks, pot, price to call) plus the public action stream via `observe()`.

Actions returned to the engine:
    ("fold",) | ("check",) | ("call",) | ("raise", total_street_commitment)
The engine clamps illegal amounts (a raise beyond your stack becomes all-in,
an undersized raise becomes a min-raise or all-in, etc.).
"""

from __future__ import annotations

from poker import equity, chen_score

PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3


class Strategy:
    name = "base"

    def new_hand(self, hand_no):
        pass

    def observe(self, event):
        """Public event stream: every player receives the same broadcast."""

    def act(self, view):
        return ("fold",)

    # -- shared helpers -------------------------------------------------
    def _pot_odds(self, view):
        if view.to_call <= 0:
            return 0.0
        return view.to_call / (view.pot + view.to_call)

    def _equity(self, view, trials):
        """Monte Carlo equity vs the live opponents, cached once per street."""
        key = (view.hand_no, view.street, view.n_active)
        cached = getattr(self, "_eq_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        eq = equity(view.hole, view.board, view.n_active - 1, trials, view.rng)
        self._eq_cache = (key, eq)
        return eq

    def _shove(self, view):
        return ("raise", view.my_committed + view.my_stack)


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, verbatim:
#
#     if my_turn
#     then bet = All in
#     fi
# ---------------------------------------------------------------------------
class SuflairGPT(Strategy):
    name = "Suflair GPT (all-in)"

    def act(self, view):
        my_turn = True
        if my_turn:
            return self._shove(view)
        # fi


# ---------------------------------------------------------------------------
# Player 2 — "The Professor": classic tight-aggressive. Position-aware Chen
# ranges preflop; postflop lives by Monte Carlo equity — value-bets big
# equity, calls on price, and mixes in the occasional semi-bluff.
# ---------------------------------------------------------------------------
class TheProfessor(Strategy):
    name = "The Professor (TAG)"

    def act(self, view):
        if view.street == PREFLOP:
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view.hole)
        late = view.to_act_after <= 1
        bb = view.blinds[1]
        facing_raise = view.current_bet > bb

        if facing_raise:
            if score >= 11:
                return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
            big = view.to_call > 4 * bb or view.to_call >= view.my_stack
            if big:
                eq = self._equity(view, 90)
                need = self._pot_odds(view) + 0.04
                if eq > max(need, 0.5):
                    return ("call",)
                return ("fold",)
            if score >= 8 or (score >= 6 and late):
                return ("call",)
            return ("fold",)

        threshold = 7 if late else 9
        if score >= threshold:
            return ("raise", bb * 5 // 2 + view.to_call)
        if view.to_call == 0:
            return ("check",)
        if score >= 6 and view.to_call <= bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, view):
        eq = self._equity(view, 80)
        po = self._pot_odds(view)
        if view.to_call == 0:
            if eq > 0.52 + 0.05 * (view.n_active - 2):
                return ("raise", view.my_committed + max(view.pot * 3 // 5, view.blinds[1]))
            if 0.34 < eq < 0.50 and view.rng.random() < 0.15:
                return ("raise", view.my_committed + view.pot // 2)  # semi-bluff
            return ("check",)
        if eq > 0.78:
            return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
        if eq > po + 0.05:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 3 — "La Loba": loose-aggressive pressure machine. Steals, c-bets
# most flops, semi-bluff-raises with live equity, but can release a hand
# when the price says the bluff is dead.
# ---------------------------------------------------------------------------
class LaLoba(Strategy):
    name = "La Loba (LAG)"

    def new_hand(self, hand_no):
        self._aggressor = False

    def act(self, view):
        if view.street == PREFLOP:
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view.hole)
        bb = view.blinds[1]
        late = view.to_act_after <= 1
        facing_raise = view.current_bet > bb

        if facing_raise:
            if score >= 10 or (score >= 8 and view.rng.random() < 0.35):
                self._aggressor = True
                return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
            big = view.to_call > 5 * bb or view.to_call >= view.my_stack
            if big:
                eq = self._equity(view, 90)
                if eq > self._pot_odds(view) + 0.02:
                    return ("call",)
                return ("fold",)
            if score >= 5:
                return ("call",)
            return ("fold",)

        steal = late and view.rng.random() < 0.30
        if score >= 7 or steal:
            self._aggressor = True
            return ("raise", bb * 3 + view.to_call)
        if score >= 5:
            return ("call",) if view.to_call else ("check",)
        return ("check",) if view.to_call == 0 else ("fold",)

    def _postflop(self, view):
        eq = self._equity(view, 80)
        po = self._pot_odds(view)
        if view.to_call == 0:
            if self._aggressor and view.street == FLOP and view.rng.random() < 0.70:
                return ("raise", view.my_committed + view.pot * 2 // 3)  # c-bet
            if eq > 0.48 or (0.30 < eq < 0.48 and view.rng.random() < 0.30):
                self._aggressor = True
                return ("raise", view.my_committed + view.pot * 2 // 3)
            return ("check",)
        if eq > 0.72:
            return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
        if 0.38 < eq < 0.55 and view.to_call < view.pot // 2 and view.rng.random() < 0.25:
            return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))  # semi-bluff raise
        if eq > po - 0.02:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 4 — "The Rock": ultra-tight nit. Folds for a living, plays only
# premiums, and only stacks off holding the goods. Immune to tilt, allergic
# to coin flips.
# ---------------------------------------------------------------------------
class TheRock(Strategy):
    name = "The Rock (nit)"

    def act(self, view):
        if view.street == PREFLOP:
            return self._preflop(view)
        return self._postflop(view)

    def _premium(self, view):
        r1, r2 = sorted(((c >> 2) + 2 for c in view.hole), reverse=True)
        suited = (view.hole[0] & 3) == (view.hole[1] & 3)
        pair = r1 == r2
        if pair and r1 >= 9:
            return 2 if r1 >= 12 else 1          # 99+; QQ+ is tier 2
        if r1 == 14 and r2 == 13:
            return 2                              # AK
        if r1 == 14 and r2 == 12 and suited:
            return 1                              # AQs
        return 0

    def _preflop(self, view):
        tier = self._premium(view)
        bb = view.blinds[1]
        shove_price = view.to_call >= view.my_stack // 2 or view.to_call > 6 * bb
        if tier == 2:
            if shove_price:
                return self._shove(view)
            return ("raise", max(view.current_bet * 3, bb * 3, view.min_raise_to))
        if tier == 1:
            if shove_price:
                return ("fold",)                  # no coin flips for stacks
            if view.current_bet > bb:
                return ("call",)
            return ("raise", bb * 3 + view.to_call)
        return ("check",) if view.to_call == 0 else ("fold",)

    def _postflop(self, view):
        eq = self._equity(view, 80)
        po = self._pot_odds(view)
        if eq > 0.80:
            return ("raise", view.my_committed + view.my_stack) if view.to_call else \
                   ("raise", view.my_committed + view.pot)
        if view.to_call == 0:
            if eq > 0.60:
                return ("raise", view.my_committed + view.pot // 2)
            return ("check",)
        if eq > po + 0.15:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 5 — "The Actuary": pure expected value. No reads, no bluffs, no
# feelings — just Monte Carlo equity against the field versus the price
# being quoted, with a value-raise when the edge is fat.
# ---------------------------------------------------------------------------
class TheActuary(Strategy):
    name = "The Actuary (pot odds)"

    def act(self, view):
        eq = self._equity(view, 100 if view.street >= TURN else 80)
        po = self._pot_odds(view)
        fair_share = 1.0 / view.n_active
        edge = eq - fair_share

        if view.to_call == 0:
            if edge > 0.16:
                return ("raise", view.my_committed + view.pot * 3 // 4)
            return ("check",)
        if eq > 0.80 and view.to_call < view.my_stack // 3:
            return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
        if eq > po + 0.03:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 6 — "The Profiler": adaptive exploiter. Builds a dossier on every
# opponent from the public action stream alone (VPIP, raise rate, shove
# rate) and re-prices its calling range against whoever is in the pot —
# snap-calling maniacs wide, dodging nits' thunder.
# ---------------------------------------------------------------------------
class TheProfiler(Strategy):
    name = "The Profiler (adaptive)"

    def __init__(self):
        self.stats = {}          # pid -> {hands, vpip, raises, shoves}
        self._seen_this_hand = set()

    def _s(self, pid):
        return self.stats.setdefault(pid, {"hands": 0, "vpip": 0, "raises": 0, "shoves": 0})

    def new_hand(self, hand_no):
        self._seen_this_hand = set()
        self._current_raisers = set()

    def observe(self, event):
        kind = event[0]
        if kind == "hand_start":
            for pid in event[2]:
                self._s(pid)["hands"] += 1
        elif kind == "action":
            _, pid, street, act, paid, is_allin = event
            st = self._s(pid)
            if street == PREFLOP and act in ("call", "raise") and pid not in self._seen_this_hand:
                st["vpip"] += 1
                self._seen_this_hand.add(pid)
            if act == "raise":
                st["raises"] += 1
                self._current_raisers.add(pid)
            if is_allin and act in ("raise", "call"):
                st["shoves"] += 1

    def _shove_rate(self, pid):
        st = self._s(pid)
        if st["hands"] < 4:
            return 0.0
        return st["shoves"] / st["hands"]

    def _table_maniac_level(self):
        """How wild are the current raisers? 0 = unknown/tight, 1 = pure maniac."""
        if not self._current_raisers:
            return 0.0
        return max(self._shove_rate(p) for p in self._current_raisers)

    def act(self, view):
        maniac = self._table_maniac_level()
        if view.street == PREFLOP:
            return self._preflop(view, maniac)
        return self._postflop(view, maniac)

    def _preflop(self, view, maniac):
        score = chen_score(view.hole)
        bb = view.blinds[1]
        facing_big = view.to_call > 4 * bb or view.to_call >= view.my_stack

        if facing_big and maniac > 0.5:
            # Someone who shoves most hands is betting a random hand.
            # Price our holding against a random hand and call wide.
            eq = equity(view.hole, view.board, 1, 120, view.rng)
            need = self._pot_odds(view)
            if eq > need + 0.04:
                return ("call",)
            return ("fold",)

        if facing_big:
            eq = self._equity(view, 90)
            if eq > max(self._pot_odds(view) + 0.05, 0.52):
                return ("call",)
            return ("fold",)

        if view.current_bet > bb:            # normal raise from a normal human
            if score >= 11:
                return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
            if score >= 8:
                return ("call",)
            return ("fold",)

        late = view.to_act_after <= 1
        if score >= (7 if late else 9):
            return ("raise", bb * 5 // 2 + view.to_call)
        if view.to_call == 0:
            return ("check",)
        if score >= 6 and view.to_call <= bb:
            return ("call",)
        return ("fold",)

    def _postflop(self, view, maniac):
        po = self._pot_odds(view)
        if maniac > 0.5 and view.to_call > 0:
            eq = equity(view.hole, view.board, 1, 120, view.rng)
            if eq > po + 0.03:
                return ("call",)
            return ("fold",)
        eq = self._equity(view, 80)
        if view.to_call == 0:
            if eq > 0.55:
                return ("raise", view.my_committed + view.pot * 3 // 5)
            return ("check",)
        if eq > 0.78:
            return ("raise", max(view.current_bet * 5 // 2, view.min_raise_to))
        if eq > po + 0.05:
            return ("call",)
        return ("fold",)


def default_lineup():
    """Seat -> strategy. Player 1 is the philosopher-king of the shove."""
    return {
        1: SuflairGPT(),
        2: TheProfessor(),
        3: LaLoba(),
        4: TheRock(),
        5: TheActuary(),
        6: TheProfiler(),
    }
