"""Six poker brains. One of them is not like the others.

Every strategy sees only public information (its own hole cards, the board,
pot, bets, stacks) plus whatever it manages to infer from observed actions.
No strategy knows what algorithm any other seat is running.

Interface:
    decide(view) -> ("fold",) | ("check",) | ("call",) | ("raise", raise_to) | ("allin",)
    observe(event)  # optional; engine broadcasts every public action
"""

from .poker import hand_strength, chen_score, rank_of


class Strategy:
    name = "base"

    def decide(self, view):
        raise NotImplementedError

    def observe(self, event):
        pass


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, as requested:
#
#   if my_turn
#   then bet = All in
#   fi
# ---------------------------------------------------------------------------
class AllInMonkey(Strategy):
    name = "YOLO all-in"

    def decide(self, view):
        return ("allin",)


# ---------------------------------------------------------------------------
# Player 2 — TAG: tight-aggressive. Plays a narrow, strong range and plays it
# fast. Position-aware preflop, value-bets made hands, semi-bluffs draws,
# refuses to pay off big bets with marginal holdings.
# ---------------------------------------------------------------------------
class TightAggressive(Strategy):
    name = "tight-aggressive"

    def decide(self, view):
        s = hand_strength(view.hole, view.board)
        pot_odds = view.to_call / max(1, view.pot + view.to_call)

        if view.street == "preflop":
            chen = chen_score(view.hole)
            late = view.seats_after <= 1  # button / cutoff-ish
            open_thr = 8.0 if late else 9.5
            facing_shove = view.to_call >= view.my_stack * 0.6
            if facing_shove:
                # Only stack off with the true premiums.
                return ("call",) if chen >= 11 else ("fold",)
            if chen >= open_thr:
                if view.to_call <= view.big_blind * 4:
                    return ("raise", view.suggest_raise(3.0))
                return ("call",) if chen >= 10 else ("fold",)
            if chen >= 6.5 and view.to_call <= view.big_blind:
                return ("call",)
            return ("check",) if view.to_call == 0 else ("fold",)

        # Postflop: bet the good stuff, protect against big aggression.
        big_bet_faced = view.to_call > 0.8 * view.pot
        if s >= 0.75:
            return ("raise", view.suggest_raise_pot(0.8))
        if s >= 0.55:
            if big_bet_faced:
                return ("call",) if s >= 0.65 else ("fold",)
            if view.to_call == 0:
                return ("raise", view.suggest_raise_pot(0.6))
            return ("call",)
        if s >= 0.35 and view.street in ("flop", "turn"):
            # mostly draws land here: semi-bluff cheap, chase only with odds
            if view.to_call == 0:
                return ("raise", view.suggest_raise_pot(0.5))
            return ("call",) if pot_odds < 0.28 else ("fold",)
        return ("check",) if view.to_call == 0 else ("fold",)


# ---------------------------------------------------------------------------
# Player 3 — LAG: loose-aggressive. Attacks wide, 3-bets light, c-bets
# relentlessly, and runs the occasional pure bluff. High variance by design.
# ---------------------------------------------------------------------------
class LooseAggressive(Strategy):
    name = "loose-aggressive"

    def __init__(self):
        self.was_preflop_aggressor = False

    def decide(self, view):
        rng = view.rng
        s = hand_strength(view.hole, view.board)

        if view.street == "preflop":
            self.was_preflop_aggressor = False
            chen = chen_score(view.hole)
            facing_shove = view.to_call >= view.my_stack * 0.6
            if facing_shove:
                return ("call",) if chen >= 9.5 else ("fold",)
            if chen >= 9 or (chen >= 6 and rng.random() < 0.5):
                self.was_preflop_aggressor = True
                mult = 3.0 if view.to_call <= view.big_blind else 2.5
                return ("raise", view.suggest_raise(mult))
            if chen >= 5 and view.to_call <= view.big_blind * 3:
                return ("call",)
            return ("check",) if view.to_call == 0 else ("fold",)

        big_bet_faced = view.to_call > 0.8 * view.pot
        if s >= 0.6:
            return ("raise", view.suggest_raise_pot(0.9))
        if view.to_call == 0:
            # c-bet as the raiser, or stab at orphaned pots sometimes
            if self.was_preflop_aggressor or rng.random() < 0.35:
                return ("raise", view.suggest_raise_pot(0.65))
            return ("check",)
        if s >= 0.4 and not big_bet_faced:
            return ("call",)
        if s >= 0.3 and rng.random() < 0.2 and not big_bet_faced:
            return ("raise", view.suggest_raise_pot(1.0))  # the occasional hero bluff
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 4 — the Nit: pathologically tight. Enters only with premiums, folds
# to pressure without the near-nuts, and tries to ride the blinds to the
# money while everyone else brawls.
# ---------------------------------------------------------------------------
class Nit(Strategy):
    name = "nit / rock"

    def decide(self, view):
        s = hand_strength(view.hole, view.board)
        desperate = view.my_stack < 4 * view.big_blind  # blinds will eat us anyway

        if view.street == "preflop":
            chen = chen_score(view.hole)
            if desperate and chen >= 8:
                return ("allin",)
            facing_shove = view.to_call >= view.my_stack * 0.6
            if facing_shove:
                return ("call",) if chen >= 12 else ("fold",)
            if chen >= 11:
                return ("raise", view.suggest_raise(3.0))
            if chen >= 9 and view.to_call <= view.big_blind * 2:
                return ("call",)
            return ("check",) if view.to_call == 0 else ("fold",)

        if s >= 0.8:
            return ("raise", view.suggest_raise_pot(0.75))
        if s >= 0.6:
            return ("call",) if view.to_call > 0 else ("raise", view.suggest_raise_pot(0.5))
        return ("check",) if view.to_call == 0 else ("fold",)


# ---------------------------------------------------------------------------
# Player 5 — the Mathematician: pure pot-odds machine. Estimates equity,
# compares it to the price, and acts on expected value, with a push-fold
# gear once the stack gets shallow (M-ratio).
# ---------------------------------------------------------------------------
class PotOddsMath(Strategy):
    name = "pot-odds EV"

    def decide(self, view):
        s = hand_strength(view.hole, view.board)
        # crude equity proxy: strength sharpened toward the extremes,
        # discounted for each extra live opponent
        equity = s ** 1.15
        equity *= 0.93 ** max(0, view.opponents_in_hand - 1)

        m_ratio = view.my_stack / max(1, view.small_blind + view.big_blind)
        if view.street == "preflop" and m_ratio < 5:
            # push-fold territory
            return ("allin",) if chen_score(view.hole) >= 7 else (
                ("check",) if view.to_call == 0 else ("fold",))

        if view.to_call == 0:
            if equity > 0.62:
                return ("raise", view.suggest_raise_pot(0.75))
            if equity > 0.5 and view.street != "preflop":
                return ("raise", view.suggest_raise_pot(0.5))
            if view.street == "preflop" and chen_score(view.hole) >= 9:
                return ("raise", view.suggest_raise(3.0))
            return ("check",)

        pot_odds = view.to_call / (view.pot + view.to_call)
        edge = equity - pot_odds
        if edge > 0.25 and equity > 0.6:
            return ("raise", view.suggest_raise_pot(0.9))
        if edge > 0.03:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Player 6 — the Adapter: profiles every opponent from observed actions only.
# Tracks shove and aggression frequencies, widens its calling range against
# maniacs, steals from tables full of folders, tightens against rocks.
# ---------------------------------------------------------------------------
class Adaptive(Strategy):
    name = "adaptive profiler"

    def __init__(self):
        self.actions_seen = {}   # pid -> total voluntary actions
        self.shoves_seen = {}    # pid -> all-ins
        self.aggro_seen = {}     # pid -> bets/raises

    def observe(self, event):
        pid = event["player"]
        kind = event["action"]
        if kind in ("fold", "check", "call", "raise", "allin"):
            self.actions_seen[pid] = self.actions_seen.get(pid, 0) + 1
            if kind == "allin":
                self.shoves_seen[pid] = self.shoves_seen.get(pid, 0) + 1
            if kind in ("raise", "allin"):
                self.aggro_seen[pid] = self.aggro_seen.get(pid, 0) + 1

    def shove_rate(self, pid):
        n = self.actions_seen.get(pid, 0)
        if n < 3:
            return 0.0  # not enough data, assume normal
        return self.shoves_seen.get(pid, 0) / n

    def decide(self, view):
        s = hand_strength(view.hole, view.board)
        chen = chen_score(view.hole)

        # Who is putting us to the decision right now?
        aggressor = view.current_aggressor
        maniac = aggressor is not None and self.shove_rate(aggressor) > 0.5

        if view.street == "preflop":
            facing_shove = view.to_call >= view.my_stack * 0.6
            if facing_shove:
                # Against someone who shoves everything, any decent hand is
                # way ahead of their random range. Against a rock, fold almost
                # everything.
                thr = 6.5 if maniac else 11.0
                return ("call",) if chen >= thr else ("fold",)
            if chen >= 9:
                return ("raise", view.suggest_raise(3.0))
            if chen >= 7 and view.to_call <= view.big_blind * 2:
                return ("call",)
            # steal attempt when it folds to us in late position
            if view.to_call <= view.big_blind and view.seats_after <= 1 and chen >= 5:
                return ("raise", view.suggest_raise(2.5))
            return ("check",) if view.to_call == 0 else ("fold",)

        big_bet_faced = view.to_call > 0.8 * view.pot
        call_thr = 0.33 if maniac else 0.55  # loosen up vs the all-in machine
        if s >= 0.72:
            return ("raise", view.suggest_raise_pot(0.85))
        if view.to_call == 0:
            if s >= 0.5:
                return ("raise", view.suggest_raise_pot(0.6))
            return ("check",)
        if s >= call_thr and (not big_bet_faced or maniac or s >= 0.65):
            return ("call",)
        return ("fold",)


def build_lineup():
    """Seat order: Player 1 is the monkey, 2..6 are the elaborate ones."""
    return [
        AllInMonkey(),
        TightAggressive(),
        LooseAggressive(),
        Nit(),
        PotOddsMath(),
        Adaptive(),
    ]
