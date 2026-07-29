"""
Six poker strategies. None of them knows what the others are running —
they only see their own cards, the board, and publicly observable actions,
exactly like a real table.

Player 1  AllInAndy      — "if my_turn then bet = All in fi". That's it. That's the strategy.
Player 2  GranitGarry    — tight-aggressive: Chen-formula ranges, position-tightened,
                           disciplined value betting, folds without a real hand.
Player 3  BlitzBetty     — loose-aggressive: wide opens, 3-bet bluffs, c-bets,
                           semi-bluffs draws, double barrels.
Player 4  ActuaryAda     — pure math: Monte-Carlo equity vs pot odds every decision,
                           raises only with a provable edge.
Player 5  ProfilerPete   — exploitative: tracks every opponent's public VPIP /
                           aggression / all-in frequency and adjusts calling ranges.
Player 6  SharkSally     — tournament shark: M-ratio push/fold when short,
                           positional steals, fit-or-fold out of position,
                           stack-pressure aware.

Actions returned to the engine: ("fold", 0) | ("call", 0) | ("raise", raise_to_total)
The engine clamps everything to legal/affordable amounts.
"""

from engine import evaluate, equity_montecarlo

# ---------------------------------------------------------------------------
# shared hand-reading helpers (each strategy uses them differently)
# ---------------------------------------------------------------------------

def chen_score(hole):
    """Bill Chen's preflop hand formula (roughly: AA=20 ... 72o=-1)."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    suited = (hole[0] & 3) == (hole[1] & 3)
    base = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if suited:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:  # connectors below Queen get a straight bonus
        score += 1
    return score


def made_tier(hole, board):
    """0..9 strength ladder of the *made* hand (no draws)."""
    if not board:
        return 0
    cat = evaluate(hole + board)[0]
    hr = [hole[0] >> 2, hole[1] >> 2]
    br = [c >> 2 for c in board]
    board_top = max(br)
    pocket_pair = hr[0] == hr[1]
    if cat >= 5:
        return 9                      # flush or better
    if cat == 4:
        return 8                      # straight
    if cat == 3:
        return 7                      # trips / set
    if cat == 2:
        return 6                      # two pair
    if cat == 1:
        if pocket_pair and hr[0] > board_top:
            return 5                  # overpair
        if board_top in hr:
            return 4                  # top pair
        if hr[0] in br or hr[1] in br or pocket_pair:
            return 3                  # middle/weak pair
        return 2                      # pair on the board only
    if 12 in hr:
        return 1                      # ace high
    return 0


def flush_draw(hole, board):
    if len(board) >= 5:
        return False
    suits = [c & 3 for c in hole + board]
    for s in range(4):
        if suits.count(s) == 4 and (hole[0] & 3 == s or hole[1] & 3 == s):
            return True
    return False


def straight_draw(hole, board):
    """Open-ended-ish: 4 distinct consecutive ranks using a hole card."""
    if len(board) >= 5:
        return False
    ranks = set(c >> 2 for c in hole + board)
    hr = {hole[0] >> 2, hole[1] >> 2}
    for low in range(0, 9):
        window = {low, low + 1, low + 2, low + 3}
        if window <= ranks and window & hr:
            return True
    return False


def pot_odds(view):
    if view.to_call <= 0:
        return 0.0
    return view.to_call / (view.pot + view.to_call)


def raise_to(view, fraction_of_pot):
    """Raise-to amount that puts roughly `fraction_of_pot` more in."""
    target = view.current_bet + max(view.big_blind,
                                    int((view.pot + view.to_call) * fraction_of_pot))
    return max(target, view.min_raise_to)


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, verbatim from the spec:
#   if my_turn then bet = All in fi
# ---------------------------------------------------------------------------

class AllInAndy:
    def decide(self, view):
        my_turn = True
        if my_turn:
            bet = view.my_round_bet + view.my_stack   # All in
            return ("raise", bet)
        # fi


# ---------------------------------------------------------------------------
# Player 2 — GranitGarry, the tight-aggressive rock
# ---------------------------------------------------------------------------

class GranitGarry:
    """Plays few hands, plays them hard. Chen ranges tightened by position,
    never pays off big bets without a big hand, value-bets relentlessly."""

    def decide(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view.hole)
        late = view.seats_to_button <= 1
        open_thr = 8 if not late else 6.5
        call_thr = 7 if not late else 6

        big_bet = view.to_call > 4 * view.big_blind
        shove_facing = view.facing_all_in or view.to_call >= view.my_stack * 0.6

        if shove_facing or big_bet:
            # only continue with a premium; ship it rather than flat-call
            if score >= 11:
                return ("raise", view.my_round_bet + view.my_stack)
            if score >= 9.5 and view.to_call <= view.my_stack * 0.35:
                return ("call", 0)
            return ("fold", 0)

        if view.current_bet > view.big_blind:          # someone raised
            if score >= 10:
                return ("raise", raise_to(view, 1.0))  # 3-bet for value
            if score >= call_thr + 1:
                return ("call", 0)
            return ("fold", 0)

        if score >= open_thr:
            return ("raise", view.current_bet + 3 * view.big_blind)
        if score >= call_thr or view.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        tier = made_tier(view.hole, view.board)
        big_pressure = view.to_call > view.pot * 0.6 or view.facing_all_in

        if tier >= 6:                                   # two pair or better
            if view.to_call >= view.my_stack:
                return ("call", 0)
            return ("raise", raise_to(view, 0.75))
        if tier >= 4:                                   # top pair / overpair
            if big_pressure and tier == 4 and view.to_call > view.my_stack * 0.5:
                return ("fold", 0)
            if view.to_call == 0:
                return ("raise", raise_to(view, 0.6))
            return ("call", 0)
        if tier == 3 and not big_pressure and pot_odds(view) < 0.25:
            return ("call", 0)
        if view.to_call == 0:
            return ("call", 0)                          # free check
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 3 — BlitzBetty, the loose-aggressive whirlwind
# ---------------------------------------------------------------------------

class BlitzBetty:
    """Raises wide, 3-bet bluffs, c-bets most flops, semi-bluffs every draw,
    fires second barrels — but can release when the story stops working."""

    def decide(self, view):
        rng = view.rng
        if view.street == "preflop":
            return self._preflop(view, rng)
        return self._postflop(view, rng)

    def _playable(self, hole):
        r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
        suited = (hole[0] & 3) == (hole[1] & 3)
        if r1 == r2:
            return True                       # any pair
        if r1 == 12:
            return True                       # any ace
        if r1 >= 8 and r2 >= 8:
            return True                       # broadways
        if suited and r1 - r2 <= 2:
            return True                       # suited (semi)connectors
        return False

    def _preflop(self, view, rng):
        score = chen_score(view.hole)
        shove_facing = view.facing_all_in or view.to_call >= view.my_stack * 0.5

        if shove_facing:
            if score >= 10:
                return ("raise", view.my_round_bet + view.my_stack)
            if score >= 8 and pot_odds(view) < 0.42:
                return ("call", 0)
            return ("fold", 0)

        if view.current_bet > view.big_blind:            # facing a raise
            if score >= 9 or rng.random() < 0.15:        # value or 3-bet bluff
                return ("raise", raise_to(view, 1.0))
            if self._playable(view.hole) and view.to_call <= 5 * view.big_blind:
                return ("call", 0)
            return ("fold", 0)

        if self._playable(view.hole) or rng.random() < 0.20:
            return ("raise", view.current_bet + 3 * view.big_blind)
        if view.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view, rng):
        tier = made_tier(view.hole, view.board)
        drawing = flush_draw(view.hole, view.board) or straight_draw(view.hole, view.board)

        if tier >= 6:
            return ("raise", raise_to(view, 0.9))
        if drawing and view.street != "river":
            if view.to_call == 0:
                return ("raise", raise_to(view, 0.65))     # semi-bluff
            if pot_odds(view) < 0.36 or view.to_call < view.my_stack * 0.25:
                return ("call", 0)
            return ("fold", 0)
        if tier >= 4:
            if view.to_call == 0:
                return ("raise", raise_to(view, 0.7))
            if view.facing_all_in and tier == 4 and view.to_call > view.my_stack * 0.6:
                return ("fold", 0)
            return ("call", 0)
        # air: continuation-bet and occasional barrel
        if view.to_call == 0:
            cbet = 0.7 if view.was_aggressor else 0.25
            if view.street == "river":
                cbet *= 0.4
            if rng.random() < cbet:
                return ("raise", raise_to(view, 0.6))
            return ("call", 0)
        if tier == 3 and pot_odds(view) < 0.28:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 4 — ActuaryAda, the equity machine
# ---------------------------------------------------------------------------

class ActuaryAda:
    """Runs a Monte-Carlo simulation for every single decision and compares
    raw equity against pot odds. No feelings, only expected value."""

    ITERS = {"preflop": 50, "flop": 60, "turn": 70, "river": 80}

    def decide(self, view):
        n_opps = max(1, min(view.n_unfolded - 1, 3))
        eq = equity_montecarlo(view.hole, view.board, n_opps,
                               self.ITERS[view.street], view.rng)
        odds = pot_odds(view)
        rand_share = 1.0 / (n_opps + 1)          # equity of a random hand

        if view.to_call >= view.my_stack:        # decision is for the tournament
            return ("call", 0) if eq > odds + 0.04 else ("fold", 0)

        edge = eq - rand_share
        if eq > 0.72 or (edge > 0.22 and view.street != "preflop"):
            return ("raise", raise_to(view, 0.85))       # big edge: build the pot
        if edge > 0.12 and view.to_call <= view.pot:
            return ("raise", raise_to(view, 0.5))        # modest edge: apply pressure
        if view.to_call == 0:
            return ("call", 0)                           # free card, always
        if eq > odds + 0.03:                             # +EV call with margin
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 5 — ProfilerPete, the exploiter
# ---------------------------------------------------------------------------

class ProfilerPete:
    """Builds a statistical profile of every opponent from their PUBLIC actions
    (folds, calls, raises, all-ins) and exploits it: calls maniacs wider,
    respects rocks, bluffs the folders."""

    @staticmethod
    def _profile(stats):
        acts = max(1, stats["actions"])
        return {
            "aggr": stats["raises"] / acts,
            "fold_freq": stats["folds"] / acts,
            "allin_freq": stats["allins"] / max(1, stats["hands"]),
        }

    def _aggressor_profile(self, view):
        if view.aggressor_name and view.aggressor_name in view.opp_stats:
            return self._profile(view.opp_stats[view.aggressor_name])
        return {"aggr": 0.3, "fold_freq": 0.4, "allin_freq": 0.05}

    def decide(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        score = chen_score(view.hole)
        prof = self._aggressor_profile(view)
        maniac = prof["allin_freq"] > 0.5 or prof["aggr"] > 0.6
        nit = prof["aggr"] < 0.15 and prof["fold_freq"] > 0.5

        shove_facing = view.facing_all_in or view.to_call >= view.my_stack * 0.5
        if shove_facing:
            # vs a proven maniac, any decent hand is way ahead of his range
            thr = 7.5 if maniac else 10.5
            if score >= thr:
                return ("raise", view.my_round_bet + view.my_stack)
            return ("fold", 0)

        if view.current_bet > view.big_blind:
            thr = (7 if maniac else 11 if nit else 9)
            if score >= thr + 1.5:
                return ("raise", raise_to(view, 1.0))
            if score >= thr:
                return ("call", 0)
            return ("fold", 0)

        if score >= 7:
            return ("raise", view.current_bet + 3 * view.big_blind)
        if score >= 5.5 or view.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        tier = made_tier(view.hole, view.board)
        prof = self._aggressor_profile(view)
        maniac = prof["allin_freq"] > 0.5 or prof["aggr"] > 0.6

        call_tier = 3 if maniac else 4       # maniacs get paid off lighter
        if tier >= 6:
            return ("raise", raise_to(view, 0.8))
        if tier >= call_tier:
            if view.to_call == 0:
                return ("raise", raise_to(view, 0.55))
            if view.to_call >= view.my_stack and tier < 5 and not maniac:
                return ("fold", 0)
            return ("call", 0)
        # bluff the players who fold too much when checked to
        if view.to_call == 0:
            avg_fold = 0.0
            if view.opp_stats:
                profs = [self._profile(s) for s in view.opp_stats.values()]
                avg_fold = sum(p["fold_freq"] for p in profs) / len(profs)
            if avg_fold > 0.45 and view.n_unfolded <= 3 and view.rng.random() < 0.5:
                return ("raise", raise_to(view, 0.6))
            return ("call", 0)
        if tier >= 2 and maniac and pot_odds(view) < 0.3:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 6 — SharkSally, the tournament specialist
# ---------------------------------------------------------------------------

class SharkSally:
    """Thinks in tournament terms: M-ratio push/fold when short, steals blinds
    from late position, plays fit-or-fold out of position, and leans on
    medium stacks when she covers them."""

    def decide(self, view):
        m_ratio = view.my_stack / max(1, view.small_blind + view.big_blind)
        if view.street == "preflop":
            return self._preflop(view, m_ratio)
        return self._postflop(view, m_ratio)

    def _preflop(self, view, m):
        score = chen_score(view.hole)
        late = view.seats_to_button <= 1
        covered = all(s <= view.my_stack for s in view.opp_stacks)

        if m < 5:                                   # desperation: push or fold
            thr = 6 if late else 7.5
            if score >= thr:
                return ("raise", view.my_round_bet + view.my_stack)
            return ("fold", 0) if view.to_call > 0 else ("call", 0)
        if m < 10:                                  # short: shove-or-fold, tighter
            if score >= 9 or (late and score >= 7.5):
                return ("raise", view.my_round_bet + view.my_stack)
            return ("fold", 0) if view.to_call > 0 else ("call", 0)

        shove_facing = view.facing_all_in or view.to_call >= view.my_stack * 0.5
        if shove_facing:
            if score >= 10.5:
                return ("raise", view.my_round_bet + view.my_stack)
            if score >= 9 and covered and pot_odds(view) < 0.4:
                return ("call", 0)                  # they're at risk, not me
            return ("fold", 0)

        if view.current_bet > view.big_blind:
            if score >= 10:
                return ("raise", raise_to(view, 1.0))
            if score >= 8:
                return ("call", 0)
            return ("fold", 0)

        if late and (score >= 5.5 or view.n_unfolded <= 3):
            return ("raise", view.current_bet + int(2.5 * view.big_blind))  # steal
        if score >= 8:
            return ("raise", view.current_bet + 3 * view.big_blind)
        if score >= 6.5 or view.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view, m):
        tier = made_tier(view.hole, view.board)
        in_position = view.seats_to_button == 0
        drawing = flush_draw(view.hole, view.board) or straight_draw(view.hole, view.board)

        if tier >= 6:
            if view.to_call >= view.my_stack:
                return ("call", 0)
            return ("raise", raise_to(view, 0.8))
        if tier >= 4:
            if view.to_call == 0:
                return ("raise", raise_to(view, 0.6))
            if view.to_call > view.my_stack * 0.55 and tier == 4:
                return ("fold", 0)
            return ("call", 0)
        if drawing and view.street != "river":
            if view.to_call == 0 and in_position:
                return ("raise", raise_to(view, 0.6))    # semi-bluff in position
            if pot_odds(view) < 0.32:
                return ("call", 0)
            return ("fold", 0)
        if view.to_call == 0:
            if in_position and view.was_aggressor and view.rng.random() < 0.55:
                return ("raise", raise_to(view, 0.5))    # positional pressure
            return ("call", 0)
        return ("fold", 0)                                # fit-or-fold OOP


LINEUP = [
    ("P1-AllInAndy", AllInAndy),
    ("P2-GranitGarry", GranitGarry),
    ("P3-BlitzBetty", BlitzBetty),
    ("P4-ActuaryAda", ActuaryAda),
    ("P5-ProfilerPete", ProfilerPete),
    ("P6-SharkSally", SharkSally),
]
