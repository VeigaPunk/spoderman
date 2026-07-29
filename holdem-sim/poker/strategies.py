"""Six poker brains.

Seat 1 gets the entire strategic genius of:

    if my_turn:
        bet = ALL_IN
    fi

Seats 2-6 get five genuinely elaborate, mutually-unaware strategies.
Nobody is told anything about anyone else's algorithm — the only
"reads" available are publicly observable actions (the ``stats`` table
the engine keeps: hands played, VPIP, preflop raises, all-in count).

An action is one of:
    'fold'
    'check_call'
    ('raise', raise_to)   # total street contribution to raise to
"""

import math

from .cards import evaluate, estimate_equity, PAIR, TWO_PAIR, TRIPS


# --------------------------------------------------------------------------- #
# shared hand-reading helpers
# --------------------------------------------------------------------------- #

def chen_score(hole):
    """Bill Chen's preflop formula (roughly -1 .. 20)."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)

    def hv(r):
        return {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(r, r / 2.0)

    if r1 == r2:
        return math.ceil(max(5.0, hv(r1) * 2))
    score = hv(r1)
    if s1 == s2:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        score += 1
    return math.ceil(score)


def hand_features(hole, board):
    """Cheap postflop hand reading: made-hand strength + draw detection."""
    cards = list(hole) + list(board)
    val = evaluate(cards)
    board_ranks = sorted((c[0] for c in board), reverse=True)
    hole_ranks = [c[0] for c in hole]
    top_board = board_ranks[0]

    pocket_pair = hole_ranks[0] == hole_ranks[1]
    overpair = pocket_pair and hole_ranks[0] > top_board
    board_paired_rank = None
    seen = set()
    for r in board_ranks:
        if r in seen:
            board_paired_rank = r
        seen.add(r)
    pair_with_hole = any(r in board_ranks for r in hole_ranks) or \
        (pocket_pair and val[0] >= PAIR)
    top_pair = top_board in hole_ranks

    # flush draw: 4 of a suit using at least one hole card
    flush_draw = False
    for s in range(4):
        n = sum(1 for c in cards if c[1] == s)
        if n == 4 and any(c[1] == s for c in hole):
            flush_draw = True

    # straight draw: 4 ranks inside some 5-rank window, using a hole card
    uniq = set(r for r, _ in cards)
    if 14 in uniq:
        uniq.add(1)
    straight_draw = False
    if val[0] < 4:  # no made straight yet
        for high in range(5, 15):
            window = set(range(high - 4, high + 1))
            have = uniq & window
            if len(have) == 4 and any(r in have or (r == 14 and 1 in have)
                                      for r in hole_ranks):
                straight_draw = True
                break

    # a single 0..1 "made hand" score
    cat = val[0]
    if cat >= 4:                       # straight or better
        strength = 0.80 + 0.05 * (cat - 4)
    elif cat == TRIPS:
        strength = 0.72
    elif cat == TWO_PAIR:
        strength = 0.62
    elif cat == PAIR:
        strength = 0.30
        if overpair:
            strength = 0.55
        elif top_pair:
            strength = 0.48 + 0.005 * max(hole_ranks)   # kicker matters
        elif pair_with_hole:
            strength = 0.36
        elif board_paired_rank:
            strength = 0.15             # "pair" that is entirely on the board
    else:
        strength = 0.05 + 0.01 * max(hole_ranks)

    return {
        "value": val, "category": cat, "strength": strength,
        "overpair": overpair, "top_pair": top_pair,
        "pair_with_hole": pair_with_hole,
        "flush_draw": flush_draw, "straight_draw": straight_draw,
        "draw": flush_draw or straight_draw,
    }


def _raise_to(obs, mult_pot):
    """Helper: raise sizing as a fraction/multiple of the pot."""
    target = obs.current_bet + max(obs.min_raise, int(obs.pot * mult_pot))
    return ("raise", min(target, obs.street_contrib + obs.stack))


def _open_to(obs, bbs):
    return ("raise", min(int(obs.big_blind * bbs), obs.street_contrib + obs.stack))


# --------------------------------------------------------------------------- #
# Seat 1 — the entire algorithm, as specified
# --------------------------------------------------------------------------- #

class AllInBot:
    """if my_turn then bet = All in fi"""

    def act(self, obs):
        my_turn = True
        if my_turn:
            return ("raise", obs.street_contrib + obs.stack)  # ALL. IN.
        # fi

# --------------------------------------------------------------------------- #
# Seat 2 — "Doyle": classic tight-aggressive position player
# --------------------------------------------------------------------------- #

class TightAggressive:
    """Plays a disciplined, position-aware TAG game.

    Preflop: Chen-formula ranges that widen from early position to the
    button; 3-bets premiums, flats speculative hands in position.
    Postflop: continuation-bets as the aggressor, value-bets two pair+,
    semi-bluffs good draws, and folds marginal hands to real pressure
    using pot odds.
    """

    def __init__(self):
        self.was_aggressor = False

    OPEN = {"early": 9, "middle": 8, "late": 7, "button": 6, "sb": 7, "bb": 6}

    def act(self, obs):
        if obs.street == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        score = chen_score(obs.hole)
        unopened = obs.current_bet <= obs.big_blind
        commit = obs.to_call / max(obs.stack + obs.street_contrib, 1)
        self.was_aggressor = False

        if unopened:
            if score >= self.OPEN[obs.position]:
                self.was_aggressor = True
                return _open_to(obs, 3)
            if obs.position == "bb" and obs.to_call == 0:
                return "check_call"
            return "fold"

        # facing a raise
        if score >= 12:                       # QQ+/AK territory: re-raise
            self.was_aggressor = True
            return _raise_to(obs, 1.0)
        if score >= 10 and commit < 0.25:
            return "check_call"
        if score >= 8 and commit < 0.08:      # cheap speculative peel
            return "check_call"
        return "fold"

    def _postflop(self, obs):
        f = hand_features(obs.hole, obs.board)
        pot_odds = obs.pot_odds

        if f["strength"] >= 0.62:             # two pair or better: value
            if obs.to_call == 0:
                return _raise_to(obs, 0.66)
            return _raise_to(obs, 0.8)

        if f["strength"] >= 0.48:             # top pair / overpair
            if obs.to_call == 0:
                return _raise_to(obs, 0.5)
            if pot_odds < 0.30:
                return "check_call"
            return "fold"

        if f["draw"]:
            outs = 9 if f["flush_draw"] else 8
            equity = outs * (0.04 if obs.street == "flop" else 0.02)
            if obs.to_call == 0 and obs.rng.random() < 0.5:
                return _raise_to(obs, 0.6)    # semi-bluff
            if pot_odds < equity:
                return "check_call"
            return "fold"

        if self.was_aggressor and obs.street == "flop" and obs.to_call == 0 \
                and obs.n_in_hand <= 3 and obs.rng.random() < 0.6:
            return _raise_to(obs, 0.5)        # c-bet
        if obs.to_call == 0:
            return "check_call"
        if f["pair_with_hole"] and pot_odds < 0.15:
            return "check_call"
        return "fold"


# --------------------------------------------------------------------------- #
# Seat 3 — "Gus": loose-aggressive pressure machine
# --------------------------------------------------------------------------- #

class LooseAggressive:
    """Wide ranges, relentless aggression, real fold discipline vs raises.

    Opens ~40% of hands, 3-bet bluffs at a controlled frequency, double-
    barrels boards, and turns draws into semi-bluff shoves — but gives up
    when raised without equity, because maniacs who never fold go broke.
    """

    def act(self, obs):
        if obs.street == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        score = chen_score(obs.hole)
        unopened = obs.current_bet <= obs.big_blind
        commit = obs.to_call / max(obs.stack + obs.street_contrib, 1)

        if unopened:
            if score >= 6 or (obs.position in ("late", "button")
                              and obs.rng.random() < 0.35):
                return _open_to(obs, 2.5)
            if obs.position == "bb" and obs.to_call == 0:
                return "check_call"
            return "fold"
        if score >= 11:
            return _raise_to(obs, 1.0)
        if score >= 9 and obs.rng.random() < 0.25 and commit < 0.2:
            return _raise_to(obs, 1.0)        # 3-bet bluff
        if score >= 8 and commit < 0.15:
            return "check_call"
        if score >= 6 and commit < 0.05:
            return "check_call"
        return "fold"

    def _postflop(self, obs):
        f = hand_features(obs.hole, obs.board)
        pot_odds = obs.pot_odds

        if f["strength"] >= 0.55 or (f["flush_draw"] and f["straight_draw"]):
            if obs.to_call == 0:
                return _raise_to(obs, 0.75)
            if f["strength"] >= 0.62:
                return _raise_to(obs, 1.0)
            return "check_call"

        if f["draw"]:
            if obs.to_call == 0:
                return _raise_to(obs, 0.66)
            if obs.to_call <= obs.stack * 0.25 and pot_odds < 0.36:
                return "check_call"
            return "fold"

        if f["pair_with_hole"]:
            if obs.to_call == 0 and obs.rng.random() < 0.55:
                return _raise_to(obs, 0.5)
            if pot_odds < 0.22:
                return "check_call"
            return "fold"

        # pure air: keep the pressure on sometimes, otherwise let go
        if obs.to_call == 0:
            if obs.n_in_hand == 2 and obs.rng.random() < 0.45:
                return _raise_to(obs, 0.6)
            return "check_call"
        return "fold"


# --------------------------------------------------------------------------- #
# Seat 4 — "The Rock": ultra-tight trapper
# --------------------------------------------------------------------------- #

class Rock:
    """Folds, folds, folds — then stacks you.

    Plays only premium hands, never bluffs, and once it has top pair or
    better it does not let go. Its entire win condition is being paid off
    by players who cannot believe anyone is really this tight.
    """

    def act(self, obs):
        if obs.street == "preflop":
            score = chen_score(obs.hole)
            unopened = obs.current_bet <= obs.big_blind
            if score >= 12:
                return _raise_to(obs, 1.2) if not unopened else _open_to(obs, 3)
            if score >= 10:
                if unopened:
                    return _open_to(obs, 3)
                # calls a raise, only jams in with the top of the range
                if obs.to_call <= obs.stack * 0.15:
                    return "check_call"
                return "fold"
            if obs.position == "bb" and obs.to_call == 0:
                return "check_call"
            return "fold"

        f = hand_features(obs.hole, obs.board)
        if f["strength"] >= 0.62:
            return _raise_to(obs, 0.8)        # monsters: pile it in
        if f["overpair"] or f["top_pair"]:
            if obs.to_call == 0:
                return _raise_to(obs, 0.6)
            if obs.pot_odds < 0.34:
                return "check_call"
            return "fold"
        if obs.to_call == 0:
            return "check_call"
        return "fold"


# --------------------------------------------------------------------------- #
# Seat 5 — "Ada": cold-blooded Monte Carlo mathematician
# --------------------------------------------------------------------------- #

class Mathematician:
    """Every decision is an equity calculation.

    Runs a Monte Carlo simulation against N random hands at every
    decision point and compares equity to pot odds: raise with a clear
    edge over the field, call any time the price is right, fold when the
    math says no. No reads, no fear, no tilt — just arithmetic.
    """

    def act(self, obs):
        n_opp = max(obs.n_in_hand - 1, 1)
        iters = 80 if obs.street == "preflop" else 100
        eq = estimate_equity(obs.hole, obs.board, n_opp, obs.rng, iters)
        fair_share = 1.0 / obs.n_in_hand
        commit = obs.to_call / max(obs.stack + obs.street_contrib, 1)

        if eq > fair_share * 1.6 or eq > 0.72:
            return _raise_to(obs, 0.75 if obs.street != "preflop" else 1.0)
        if eq > fair_share * 1.25 and obs.to_call == 0:
            return _raise_to(obs, 0.5)
        if obs.to_call == 0:
            return "check_call"
        # price-based call with a safety margin that scales with commitment
        needed = obs.pot_odds + (0.10 if commit > 0.4 else 0.03)
        if eq > needed:
            return "check_call"
        return "fold"


# --------------------------------------------------------------------------- #
# Seat 6 — "Sun-Tzu": adaptive exploiter
# --------------------------------------------------------------------------- #

class AdaptiveExploiter:
    """Profiles the table from public actions and attacks the weak spot.

    Tracks every opponent's VPIP, raise frequency, and all-in frequency
    (all observable at the table). Against detected shove-monkeys it
    stops respecting raises and calls off with strong-but-not-nutted
    hands, verified by an on-the-spot Monte Carlo equity check against a
    random range. Against nits it steals relentlessly; in dicey spots it
    reverts to solid TAG poker. Know your enemy.
    """

    def _profile(self, obs, seat):
        st = obs.stats.get(seat)
        if not st or st["hands"] < 6:
            return "unknown"
        allin_rate = st["allins"] / st["hands"]
        vpip = st["vpip"] / st["hands"]
        if allin_rate > 0.4:
            return "maniac"
        if vpip < 0.2:
            return "nit"
        if vpip > 0.5:
            return "loose"
        return "solid"

    def act(self, obs):
        aggressor_profile = ("unknown" if obs.last_aggressor is None
                             else self._profile(obs, obs.last_aggressor))
        facing_jam = obs.to_call >= obs.stack * 0.6 and obs.to_call > 0

        # --- the maniac protocol: call down light, with math as backup ---
        if facing_jam and aggressor_profile == "maniac":
            eq = estimate_equity(obs.hole, obs.board, 1, obs.rng, 120)
            if eq > obs.pot_odds + 0.02:   # vs a random shove, price is truth
                return "check_call"
            return "fold"

        if obs.street == "preflop":
            return self._preflop(obs, aggressor_profile)
        return self._postflop(obs, aggressor_profile)

    def _preflop(self, obs, profile):
        score = chen_score(obs.hole)
        unopened = obs.current_bet <= obs.big_blind
        commit = obs.to_call / max(obs.stack + obs.street_contrib, 1)
        nit_count = sum(1 for s in obs.opp_stacks
                        if self._profile(obs, s) == "nit")

        if unopened:
            open_bar = {"early": 9, "middle": 8, "late": 7,
                        "button": 6, "sb": 7, "bb": 6}[obs.position]
            if nit_count >= max(obs.n_in_hand - 2, 1):
                open_bar -= 2               # table full of nits: steal wider
            if score >= open_bar:
                return _open_to(obs, 2.5)
            if obs.position == "bb" and obs.to_call == 0:
                return "check_call"
            return "fold"

        if profile == "maniac":             # don't respect maniac raises
            if score >= 8:
                return _raise_to(obs, 1.0)  # isolate and punish
            if score >= 6 and commit < 0.1:
                return "check_call"
            return "fold"
        if score >= 12:
            return _raise_to(obs, 1.0)
        if score >= 10 and commit < 0.2:
            return "check_call"
        if score >= 8 and commit < 0.06:
            return "check_call"
        return "fold"

    def _postflop(self, obs, profile):
        f = hand_features(obs.hole, obs.board)
        pot_odds = obs.pot_odds
        thin_value = profile in ("maniac", "loose")

        if f["strength"] >= 0.62:
            return _raise_to(obs, 0.9 if thin_value else 0.7)
        if f["strength"] >= 0.48:
            if obs.to_call == 0:
                return _raise_to(obs, 0.6 if thin_value else 0.45)
            bar = 0.42 if thin_value else 0.30
            if pot_odds < bar:
                return "check_call"
            return "fold"
        if f["draw"]:
            if obs.to_call == 0 and obs.rng.random() < 0.5:
                return _raise_to(obs, 0.6)
            if pot_odds < 0.32:
                return "check_call"
            return "fold"
        if obs.to_call == 0:
            if profile == "nit" and obs.rng.random() < 0.5:
                return _raise_to(obs, 0.55)  # nits fold: take the pot
            return "check_call"
        if thin_value and f["pair_with_hole"] and pot_odds < 0.30:
            return "check_call"
        return "fold"
