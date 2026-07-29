"""Six poker bots for the spoderman Hold'em death-match.

Seat 1 (index 0) runs the entire strategy spec it was given:

    if my_turn
    then bet = All in
    fi

Seats 2-6 run five genuinely elaborate, mutually-unaware strategies. No bot
can see another bot's cards or code - only the public action stream that the
engine broadcasts (the same information a human at the table would have).
"""

import random
from .engine import chen_score, estimate_equity, evaluate


# --------------------------------------------------------------------------
# shared hand-reading helpers (heuristics, deliberately human-imperfect)
# --------------------------------------------------------------------------

def pair_strength(hole, board):
    """0 air, 1 board-pair only, 2 weak/mid pair, 3 top pair, 4 overpair,
    5 two pair, 6 trips/set, 7 straight or better."""
    hr = [c >> 2 for c in hole]
    br = [c >> 2 for c in board]
    top = max(br)
    cat = evaluate(list(hole) + board)[0]
    if cat >= 4:
        return 7
    if cat == 3:
        return 6
    if cat == 2:
        return 5
    if cat == 1:
        if hr[0] == hr[1]:
            return 4 if hr[0] > top else 2
        if top in hr:
            return 3
        return 2 if any(r in br for r in hr) else 1
    return 0


def top_pair_kicker(hole, board):
    br = [c >> 2 for c in board]
    hr = [c >> 2 for c in hole]
    top = max(br)
    if top in hr:
        return max(r for r in hr if r != top) if hr[0] != hr[1] else hr[0]
    return -1


def flush_draw(hole, board):
    if len(board) >= 5:
        return False
    suits = {}
    for c in list(hole) + board:
        suits[c & 3] = suits.get(c & 3, 0) + 1
    return any(n == 4 and any((c & 3) == s for c in hole)
               for s, n in suits.items())


def straight_draw(hole, board):
    if len(board) >= 5:
        return False
    rs = {c >> 2 for c in list(hole) + board}
    hole_rs = {c >> 2 for c in hole}
    if 12 in rs:
        rs.add(-1)
    for lo in range(-1, 9):
        window = {lo, lo + 1, lo + 2, lo + 3}
        if window <= rs and (window & hole_rs):
            return True
    return False


def is_pocket_pair(hole, min_rank=0):
    return (hole[0] >> 2) == (hole[1] >> 2) and (hole[0] >> 2) >= min_rank


def high_ranks(hole):
    return tuple(sorted((hole[0] >> 2, hole[1] >> 2), reverse=True))


def suited(hole):
    return (hole[0] & 3) == (hole[1] & 3)


class Strategy:
    name = "?"

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    def observe(self, event):
        pass

    def act(self, obs):
        raise NotImplementedError


# --------------------------------------------------------------------------
# Seat 1 - the simple one
# --------------------------------------------------------------------------

class LeeroyAllIn(Strategy):
    """The complete strategy, verbatim from the spec:

        if my_turn
        then bet = All in
        fi
    """
    name = "Leeroy (ALL-IN)"

    def act(self, obs):
        my_turn = True
        if my_turn:
            return ("allin",)
        # fi


# --------------------------------------------------------------------------
# Seat 2 - tight-aggressive fundamentals
# --------------------------------------------------------------------------

class DoyleTAG(Strategy):
    """'Doyle' - classic tight-aggressive tournament poker.

    Pre-flop: Chen-formula hand ranking with position-adjusted opening
    thresholds (tight up front, wider on the button), 3-bets premiums,
    flat-calls speculative hands when the price is right, and has a strict
    calling range versus shoves (roughly TT+/AQ+). Below 10 big blinds it
    switches to push/fold.

    Post-flop: value-bets two-thirds pot with strong made hands, continuation
    bets as the pre-flop aggressor, calls with draws only when pot odds
    justify it, and refuses to pay off big bets with one-pair hands.
    """
    name = "Doyle (TAG)"

    def act(self, obs):
        if obs.street == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        score = chen_score(obs.hole)
        stack_bb = obs.my_stack / obs.bb
        facing_shove = (obs.aggressor_is_allin or
                        obs.to_call >= 0.4 * (obs.my_stack + obs.my_street_contrib))

        if stack_bb < 10:  # push/fold mode
            if score >= (7 if obs.pos_frac >= 0.5 else 8.5):
                return ("allin",)
            if obs.to_call == 0:
                return ("check_call",)
            return ("fold",)

        if obs.preflop_raise_count == 0:
            thr = 8 if obs.pos_frac < 0.4 else (7 if obs.pos_frac < 0.75 else 5.5)
            if score >= thr:
                return ("raise_to", 3 * obs.bb)
            if obs.to_call == 0:
                return ("check_call",)
            if score >= thr - 2 and obs.to_call <= obs.bb:
                return ("check_call",)
            return ("fold",)

        if facing_shove and obs.to_call > 3 * obs.bb:
            # calling-range discipline: ~TT+, AK, AQs
            if score >= 10 or is_pocket_pair(obs.hole, 8):
                return ("check_call",)
            return ("fold",)
        if score >= 12:
            return ("raise_to", obs.current_bet * 3)
        if score >= 8:
            return ("check_call",)
        if score >= 6.5 and obs.to_call <= 2.5 * obs.bb:
            return ("check_call",)
        return ("fold",)

    def _postflop(self, obs):
        ps = pair_strength(obs.hole, obs.board)
        kick = top_pair_kicker(obs.hole, obs.board)
        strong = ps >= 5 or ps == 4 or (ps == 3 and kick >= 8)
        drawing = flush_draw(obs.hole, obs.board) or straight_draw(obs.hole, obs.board)

        if obs.to_call == 0:
            if strong:
                return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                          (2 * obs.pot) // 3))
            if (obs.preflop_aggressor_seat == obs.seat
                    and obs.street == "flop" and obs.n_active <= 3):
                return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                          obs.pot // 2))
            return ("check_call",)

        pot_odds = obs.to_call / (obs.pot + obs.to_call)
        if strong:
            if ps >= 5:
                return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                          obs.pot))
            return ("check_call",)
        if drawing and obs.street != "river":
            limit = 0.34 if obs.street == "flop" else 0.26
            return ("check_call",) if pot_odds <= limit else ("fold",)
        if ps >= 2 and pot_odds <= 0.30 and obs.to_call <= 0.2 * obs.my_stack:
            return ("check_call",)
        if obs.street == "river" and ps >= 3 and pot_odds <= 0.25:
            return ("check_call",)  # disciplined bluff-catch
        return ("fold",)


# --------------------------------------------------------------------------
# Seat 3 - loose-aggressive pressure
# --------------------------------------------------------------------------

class MaverickLAG(Strategy):
    """'Maverick' - loose-aggressive table bully.

    Pre-flop: opens a wide range (any Chen 5+, all suited connectors),
    attacks folded-around pots from late position with almost any two cards,
    and mixes in 3-bet bluffs at a randomized frequency when holding an ace
    blocker. Versus shoves it snap-calls only with a real hand.

    Post-flop: relentless barrels - stabs at checked pots, semi-bluff raises
    draws, floats in position, and fires randomized river bluffs. The whole
    plan is to win the pots nobody else wants; discipline only kicks in when
    facing large raises with pure air.
    """
    name = "Maverick (LAG)"

    def act(self, obs):
        if obs.street == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        score = chen_score(obs.hole)
        hr = high_ranks(obs.hole)
        connected = suited(obs.hole) and abs(hr[0] - hr[1]) <= 2
        facing_shove = (obs.aggressor_is_allin or
                        obs.to_call >= 0.4 * (obs.my_stack + obs.my_street_contrib))
        stack_bb = obs.my_stack / obs.bb

        if stack_bb < 8:
            if score >= 6 or connected:
                return ("allin",)
            return ("check_call",) if obs.to_call == 0 else ("fold",)

        if obs.preflop_raise_count == 0:
            steal = obs.pos_frac >= 0.7 and self.rng.random() < 0.55
            if score >= 5 or connected or steal:
                return ("raise_to", int(2.5 * obs.bb))
            if obs.to_call == 0:
                return ("check_call",)
            return ("fold",)

        if facing_shove and obs.to_call > 3 * obs.bb:
            if score >= 10 or is_pocket_pair(obs.hole, 6):  # 88+
                return ("check_call",)
            return ("fold",)
        has_ace = 12 in hr
        if score >= 10 or (has_ace and self.rng.random() < 0.12):
            return ("raise_to", obs.current_bet * 3)
        if score >= 6 or connected:
            return ("check_call",)
        return ("fold",)

    def _postflop(self, obs):
        ps = pair_strength(obs.hole, obs.board)
        drawing = flush_draw(obs.hole, obs.board) or straight_draw(obs.hole, obs.board)
        strong = ps >= 5
        pot_odds = obs.to_call / (obs.pot + obs.to_call) if obs.to_call else 0.0

        if obs.to_call == 0:
            if strong or drawing or ps >= 2 or self.rng.random() < 0.35:
                size = (3 * obs.pot) // 5
                return ("raise_to", obs.current_bet + max(obs.min_raise, size))
            return ("check_call",)

        if strong:
            return ("raise_to", obs.current_bet + max(obs.min_raise, obs.pot))
        if drawing and obs.street != "river":
            if self.rng.random() < 0.45 and obs.to_call < 0.3 * obs.my_stack:
                return ("raise_to",
                        obs.current_bet + max(obs.min_raise, obs.pot))
            return ("check_call",) if pot_odds <= 0.38 else ("fold",)
        if ps >= 3 and pot_odds <= 0.40:
            return ("check_call",)
        if ps >= 2 and pot_odds <= 0.28:
            return ("check_call",)
        if (obs.street == "flop" and obs.pos_frac >= 0.6
                and pot_odds <= 0.30 and self.rng.random() < 0.15):
            return ("check_call",)  # float, planning to take it away later
        return ("fold",)


# --------------------------------------------------------------------------
# Seat 4 - the nit
# --------------------------------------------------------------------------

class MonkNit(Strategy):
    """'The Monk' - monastic patience, zero gamble.

    Pre-flop: plays only premium holdings (TT+, AK, AQ, AJs, KQs), raises
    them for value and folds literally everything else, no matter the price.
    Calls all-ins only with QQ+/AK. When blinds shred the stack below 8 big
    blinds, grudgingly widens to any pair, big aces and KQ.

    Post-flop: continues only with an overpair, top pair with a good kicker,
    or better. Never bluffs, never pays off with less. The plan: let the
    maniacs incinerate each other, then scoop with the nuts.
    """
    name = "The Monk (NIT)"

    PREMIUM_PAIR = 8  # TT+

    def _premium_open(self, hole):
        hr = high_ranks(hole)
        if is_pocket_pair(hole, self.PREMIUM_PAIR):
            return True
        if hr == (12, 11):  # AK
            return True
        if hr == (12, 10):  # AQ
            return True
        if suited(hole) and hr in ((12, 9), (11, 10)):  # AJs, KQs
            return True
        return False

    def _shove_call(self, hole):
        hr = high_ranks(hole)
        return is_pocket_pair(hole, 10) or hr == (12, 11)  # QQ+ / AK

    def act(self, obs):
        if obs.street == "preflop":
            return self._preflop(obs)
        return self._postflop(obs)

    def _preflop(self, obs):
        stack_bb = obs.my_stack / obs.bb
        hr = high_ranks(obs.hole)
        if stack_bb < 8:
            desperate = (is_pocket_pair(obs.hole) or hr[0] == 12
                         or hr in ((11, 10), (11, 9)))
            if desperate:
                return ("allin",)
            return ("check_call",) if obs.to_call == 0 else ("fold",)
        big_bet = (obs.aggressor_is_allin or obs.to_call > 4 * obs.bb or
                   obs.to_call >= 0.3 * obs.my_stack)
        if big_bet:
            if self._shove_call(obs.hole):
                return ("allin",)
            return ("check_call",) if obs.to_call == 0 else ("fold",)
        if self._premium_open(obs.hole):
            if obs.preflop_raise_count == 0:
                return ("raise_to", 3 * obs.bb)
            return ("raise_to", obs.current_bet * 3)
        if obs.to_call == 0:
            return ("check_call",)
        return ("fold",)

    def _postflop(self, obs):
        ps = pair_strength(obs.hole, obs.board)
        kick = top_pair_kicker(obs.hole, obs.board)
        good = ps >= 5 or ps == 4 or (ps == 3 and kick >= 8)
        if not good:
            return ("check_call",) if obs.to_call == 0 else ("fold",)
        if obs.to_call == 0:
            return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                      obs.pot // 2))
        if ps >= 5:
            return ("raise_to", obs.current_bet + max(obs.min_raise, obs.pot))
        pot_odds = obs.to_call / (obs.pot + obs.to_call)
        return ("check_call",) if pot_odds <= 0.45 else ("fold",)


# --------------------------------------------------------------------------
# Seat 5 - pure math
# --------------------------------------------------------------------------

class CalculatorEquity(Strategy):
    """'The Calculator' - Monte Carlo equity versus pot odds, nothing else.

    Every decision runs a fresh Monte Carlo simulation of the current spot
    (hole cards + visible board vs. N random opponent hands) and compares
    win equity against the price being offered:

      * equity clearly above the price  -> raise for value (pot-sized)
      * equity above the price          -> call
      * marginally below                -> occasional exploratory call
      * otherwise                       -> fold

    Bets when checked to only with an equity edge over the field average.
    Under 10 big blinds it becomes an all-in-or-fold equity machine. It has
    no psychology and no memory - just cold arithmetic recomputed every
    single turn.
    """
    name = "The Calculator (EQ)"

    def _equity(self, obs):
        n_opps = max(1, min(obs.n_active - 1, 3))
        iters = 60 if obs.street != "preflop" else 40
        return estimate_equity(list(obs.hole), obs.board, n_opps, iters,
                               self.rng), n_opps

    def act(self, obs):
        equity, n_opps = self._equity(obs)
        stack_bb = obs.my_stack / obs.bb

        if obs.street == "preflop" and stack_bb < 10:
            return ("allin",) if equity > 0.5 + 0.03 * n_opps else (
                ("check_call",) if obs.to_call == 0 else ("fold",))

        if obs.to_call == 0:
            baseline = 1.0 / (n_opps + 1)
            if equity > baseline + 0.15:
                return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                          (3 * obs.pot) // 5))
            if equity > baseline + 0.06 and self.rng.random() < 0.5:
                return ("raise_to", obs.current_bet + max(obs.min_raise,
                                                          (2 * obs.pot) // 5))
            return ("check_call",)

        pot_odds = obs.to_call / (obs.pot + obs.to_call)
        if equity >= pot_odds + 0.12 and equity > 0.5:
            return ("raise_to", obs.current_bet + max(obs.min_raise, obs.pot))
        if equity >= pot_odds + 0.02:
            return ("check_call",)
        if equity >= pot_odds - 0.02 and self.rng.random() < 0.25:
            return ("check_call",)
        return ("fold",)


# --------------------------------------------------------------------------
# Seat 6 - the adaptive profiler
# --------------------------------------------------------------------------

class ProfilerAdaptive(DoyleTAG):
    """'The Profiler' - opponent modelling on top of TAG fundamentals.

    Knows nothing about anyone's algorithm; it builds statistical profiles
    purely from the public action stream, exactly like a human regular:

      * per-seat frequencies of pre-flop shoves, raises and folds
      * a 'maniac detector': a seat shoving >40% of observed hands is
        modelled as holding two random cards, so shoves get called with any
        hand whose Monte Carlo equity vs. random beats the pot odds
      * a 'rock detector': seats folding to almost every raise get their
        blinds relentlessly stolen with a widened opening range

    Everything else falls back to the disciplined TAG core it inherits, plus
    a short-stack push/fold mode. If someone at this table really is
    shoving blind every hand, this bot is designed to find out fast and make
    them pay for it.
    """
    name = "The Profiler (ADAPT)"

    def __init__(self, seed=0):
        super().__init__(seed)
        self.hands_seen = {}
        self.preflop_shoves = {}
        self.preflop_raises = {}
        self.preflop_folds = {}
        self._counted_this_hand = set()
        self._hand = -1

    def observe(self, event):
        et = event.get("type")
        if et == "hand_start":
            self._hand = event["hand"]
            self._counted_this_hand = set()
            for s in event["seats"]:
                self.hands_seen[s] = self.hands_seen.get(s, 0) + 1
        elif et == "action" and event["street"] == "preflop":
            s = event["seat"]
            if event["action"] == "raise" and event["allin"]:
                if (s, "shove") not in self._counted_this_hand:
                    self.preflop_shoves[s] = self.preflop_shoves.get(s, 0) + 1
                    self._counted_this_hand.add((s, "shove"))
            elif event["action"] == "raise":
                self.preflop_raises[s] = self.preflop_raises.get(s, 0) + 1
            elif event["action"] == "fold":
                self.preflop_folds[s] = self.preflop_folds.get(s, 0) + 1

    def _shove_freq(self, seat):
        seen = self.hands_seen.get(seat, 0)
        if seen < 6:
            return 0.0
        return self.preflop_shoves.get(seat, 0) / seen

    def _fold_freq(self, seat):
        seen = self.hands_seen.get(seat, 0)
        if seen < 8:
            return 0.0
        return self.preflop_folds.get(seat, 0) / seen

    def act(self, obs):
        if obs.street == "preflop":
            maniac = (obs.aggressor_is_allin
                      and obs.last_aggressor_seat is not None
                      and self._shove_freq(obs.last_aggressor_seat) > 0.4
                      and obs.to_call > 0)
            if maniac:
                # a chronic shover holds two random cards: price it precisely
                pot_odds = obs.to_call / (obs.pot + obs.to_call)
                equity = estimate_equity(list(obs.hole), obs.board, 1, 100,
                                         self.rng)
                if equity >= pot_odds + 0.03:
                    return ("allin",)
                return ("fold",)
            if (obs.preflop_raise_count == 0 and obs.pos_frac >= 0.6
                    and obs.opp_stacks
                    and all(self._fold_freq(s) > 0.55
                            for s in obs.opp_stacks)):
                # table full of rocks: steal wide
                if chen_score(obs.hole) >= 4:
                    return ("raise_to", int(2.5 * obs.bb))
        return super().act(obs)


def build_lineup(seed):
    """Fresh bots for one tournament. Seat order == player number - 1."""
    return [
        LeeroyAllIn(seed * 13 + 1),
        DoyleTAG(seed * 13 + 2),
        MaverickLAG(seed * 13 + 3),
        MonkNit(seed * 13 + 4),
        CalculatorEquity(seed * 13 + 5),
        ProfilerAdaptive(seed * 13 + 6),
    ]
