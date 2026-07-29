"""Six poker minds, one table. Nobody knows what anybody else is running.

Seats 2-6 get five elaborate, genuinely different strategies.
Seat 1 gets... well. Seat 1 read half a tweet about poker once.
"""

from cards import equity_vs_random, chen_score


def _pot_odds(view):
    """Price being offered: call / (pot + call). Free action -> 0."""
    if view.to_call <= 0:
        return 0.0
    return view.to_call / (view.pot + view.to_call)


def _facing_shove(view):
    """Is the call a huge chunk of my stack?"""
    return view.to_call >= 0.6 * view.my_stack


def _n_opponents(view):
    return max(1, len(view.seats_active) - 1)


# --------------------------------------------------------------------------- 1
class AllInGoblin:
    """if my_turn then bet = All in fi"""

    name = "The Goblin (ALL-IN)"

    def act(self, view):
        return ("raise", view.my_bet + view.my_stack)


# --------------------------------------------------------------------------- 2
class TheRock:
    """Tight-aggressive grinder.

    Preflop: Bill Chen's formula with position-adjusted thresholds — plays only
    premium and strong speculative hands, always entering with a raise.
    Postflop: Monte Carlo equity vs. pot odds; value-bets big equity edges,
    calls only when the price is right, and refuses to pay off shoves without
    a near-nut holding. Survival first, chips second.
    """

    name = "The Rock (tight-aggressive)"

    def act(self, view):
        v = view
        if v.street == "preflop":
            score = chen_score(v.hole)
            # Later position -> looser threshold.
            dist = (v.my_seat - v.button_seat) % 6
            threshold = 9 - min(dist, 3)
            if _facing_shove(v):
                # Someone jammed: only continue with a monster.
                eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 90)
                return ("call",) if eq > 0.62 else ("fold",)
            if score >= threshold + 2:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= threshold:
                return ("call",)
            return ("call",) if v.to_call == 0 else ("fold",)

        eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 80)
        if _facing_shove(v):
            return ("call",) if eq > 0.68 else ("fold",)
        if eq > 0.75:
            return ("raise", max(v.min_raise_to, v.my_bet + v.pot))
        if eq > 0.55 and v.to_call <= 0.15 * v.my_stack:
            return ("raise", v.min_raise_to)
        if eq > _pot_odds(v) + 0.05:
            return ("call",)
        return ("call",) if v.to_call == 0 else ("fold",)


# --------------------------------------------------------------------------- 3
class TheManiac:
    """Loose-aggressive pressure merchant.

    Opens wide, three-bets light, c-bets relentlessly, semi-bluffs draws and
    randomizes bluffs so opponents can't put it on a range. Applies maximum
    pain to tight players — but bleeds chips when the table refuses to fold.
    """

    name = "The Maniac (loose-aggressive)"

    def act(self, view):
        v = view
        roll = v.rng.random()
        if v.street == "preflop":
            score = chen_score(v.hole)
            if _facing_shove(v):
                eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 90)
                return ("call",) if eq > 0.52 else ("fold",)
            if score >= 8 or roll < 0.25:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= 5:
                return ("call",)
            return ("call",) if v.to_call == 0 else ("fold",)

        eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 70)
        if _facing_shove(v):
            return ("call",) if eq > 0.60 else ("fold",)
        if eq > 0.62 or (eq > 0.40 and roll < 0.35):     # value or semi-bluff
            return ("raise", max(v.min_raise_to, v.my_bet + int(0.75 * v.pot)))
        if v.to_call == 0 and roll < 0.30:               # naked stab
            return ("raise", v.min_raise_to)
        if eq > _pot_odds(v):
            return ("call",)
        return ("call",) if v.to_call == 0 else ("fold",)


# --------------------------------------------------------------------------- 4
class TheProfessor:
    """Game-theory pot-odds purist.

    Every decision is an expected-value inequality: estimate equity by Monte
    Carlo, compare to the price of the call, and act accordingly. Raises only
    when clearly best, never bluffs, never tilts. The spreadsheet has no fear —
    but also no imagination.
    """

    name = "The Professor (pot-odds purist)"

    def act(self, view):
        v = view
        trials = 100 if _facing_shove(v) else 70
        eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, trials)
        price = _pot_odds(v)
        if _facing_shove(v):
            # Big calls need a margin over the raw price (risk of ruin).
            return ("call",) if eq > max(price + 0.10, 0.58) else ("fold",)
        if eq > 0.80:
            return ("raise", max(v.min_raise_to, v.my_bet + v.pot))
        if eq > 0.65 and v.street != "preflop":
            return ("raise", v.min_raise_to)
        if eq > price + 0.03:
            return ("call",)
        return ("call",) if v.to_call == 0 else ("fold",)


# --------------------------------------------------------------------------- 5
class TheShark:
    """Position-aware exploiter.

    Widens ruthlessly on the button, steals blinds, continuation-bets heads-up,
    and tightens out of position. Stack-aware: shifts to push/fold poker when
    short and pressures medium stacks near the bubble.
    """

    name = "The Shark (position player)"

    def act(self, view):
        v = view
        dist = (v.my_seat - v.button_seat) % 6
        in_position = dist == 0 or dist >= 4
        eq_needed_bonus = 0.0 if in_position else 0.06
        stack_bb = v.my_stack / max(v.big_blind, 1)

        if v.street == "preflop":
            score = chen_score(v.hole)
            if stack_bb < 8:  # push/fold mode
                if score >= 8:
                    return ("raise", v.my_bet + v.my_stack)
                return ("call",) if v.to_call == 0 else ("fold",)
            if _facing_shove(v):
                eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 90)
                return ("call",) if eq > 0.60 else ("fold",)
            if in_position and score >= 6 and v.to_call <= v.big_blind:
                return ("raise", max(v.min_raise_to, int(2.5 * v.big_blind)))  # steal
            if score >= 9:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= 6 and v.to_call <= 2 * v.big_blind:
                return ("call",)
            return ("call",) if v.to_call == 0 else ("fold",)

        eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, 75)
        if _facing_shove(v):
            return ("call",) if eq > 0.66 else ("fold",)
        was_aggressor = any(a[0] == v.my_seat and a[1] == "raise"
                            for a in v.aggression_log)
        if v.to_call == 0 and was_aggressor and len(v.seats_active) <= 3:
            return ("raise", max(v.min_raise_to, v.my_bet + int(0.6 * v.pot)))  # c-bet
        if eq > 0.70 + eq_needed_bonus:
            return ("raise", max(v.min_raise_to, v.my_bet + int(0.8 * v.pot)))
        if eq > _pot_odds(v) + 0.04 + eq_needed_bonus:
            return ("call",)
        return ("call",) if v.to_call == 0 else ("fold",)


# --------------------------------------------------------------------------- 6
class TheProfiler:
    """Adaptive opponent modeler.

    Builds a live statistical profile of every seat — shove frequency,
    raise frequency, fold frequency — from the public action log alone.
    Against maniacs it becomes a trap: fold everything marginal, then snap off
    their shoves with premium equity. Against nits it steals. It plays the
    player, not the cards.
    """

    name = "The Profiler (adaptive)"

    def __init__(self):
        self.actions_seen = {}   # seat -> {'raise': n, 'total': n}

    def _observe(self, view):
        for seat, action, _street in view.aggression_log:
            key = (view.hand_no, seat, action, _street)
            if key in getattr(self, "_seen_keys", set()):
                continue
            self._seen_keys = getattr(self, "_seen_keys", set())
            self._seen_keys.add(key)
            rec = self.actions_seen.setdefault(seat, {"raise": 0, "total": 0})
            rec["total"] += 1
            if action == "raise":
                rec["raise"] += 1

    def _table_maniac_level(self, view):
        """Max raise-frequency among opponents with a real sample."""
        level = 0.0
        for seat, rec in self.actions_seen.items():
            if seat == view.my_seat or rec["total"] < 8:
                continue
            level = max(level, rec["raise"] / rec["total"])
        return level

    def act(self, view):
        v = view
        self._observe(v)
        maniac = self._table_maniac_level(v)   # ~1.0 means someone shoves always
        trials = 100 if _facing_shove(v) else 70
        eq = equity_vs_random(v.hole, v.board, _n_opponents(v), v.rng, trials)

        if _facing_shove(v):
            # The whole plan: vs. wild shovers, call tighter early (variance
            # kills), but the threshold is calibrated to strictly beat a
            # random-hand range over time.
            need = 0.57 if maniac > 0.6 else 0.62
            if v.my_stack > 3 * v.to_call:
                need += 0.05   # don't gamble when comfortable
            return ("call",) if eq > need else ("fold",)

        if v.street == "preflop":
            score = chen_score(v.hole)
            open_threshold = 7 if maniac < 0.5 else 9  # tighten vs. aggression
            if score >= open_threshold + 2:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= open_threshold:
                return ("call",)
            return ("call",) if v.to_call == 0 else ("fold",)

        if eq > 0.72:
            return ("raise", max(v.min_raise_to, v.my_bet + v.pot))
        if maniac < 0.5 and v.to_call == 0 and eq > 0.5 and v.rng.random() < 0.3:
            return ("raise", v.min_raise_to)  # steal vs. passive tables
        if eq > _pot_odds(v) + 0.04:
            return ("call",)
        return ("call",) if v.to_call == 0 else ("fold",)


def make_lineup():
    """Seat 1..6. Fresh strategy objects per tournament (no cross-game memory)."""
    return [AllInGoblin(), TheRock(), TheManiac(),
            TheProfessor(), TheShark(), TheProfiler()]


STRATEGY_NAMES = {i + 1: s.name for i, s in enumerate(make_lineup())}
