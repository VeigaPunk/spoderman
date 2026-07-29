"""The six agents.

Five elaborate strategies (seats 2-6) and one deliberately trivial one (seat 1).

Every agent sees only the public ``Observation`` plus its own hole cards. None
of them is told which strategy any opponent is running -- the one agent that
adapts (Caveira Peaky) has to infer tendencies from observed betting alone.
"""

from .engine import FOLD, CHECK, CALL, RAISE, PREFLOP, FLOP, TURN, RIVER
from .equity import (chen_score, monte_carlo_equity, board_texture,
                     made_hand_class, draw_strength)

ITERATIONS = {PREFLOP: 240, FLOP: 140, TURN: 120, RIVER: 100}


class Agent:
    """Shared plumbing. Subclasses implement ``decide``."""

    name = "agent"
    mascot = ""

    def reset(self):
        pass

    # -- hooks the engine calls; most agents ignore them ---------------------
    def new_hand(self, hand_number, stacks):
        pass

    def observe_action(self, player_id, street, action, amount, pot, current_bet):
        pass

    def observe_hand_end(self, payouts, showdown, revealed, board):
        pass

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def opponents(obs):
        return max(obs.num_in_hand - 1, 1)

    @staticmethod
    def pot_odds(obs):
        if obs.to_call <= 0:
            return 0.0
        return obs.to_call / float(obs.pot + obs.to_call)

    @staticmethod
    def position(obs):
        """0.0 = first to act, 1.0 = last to act."""
        live = max(obs.num_in_hand - 1, 1)
        return 1.0 - (obs.actors_after / float(live))

    def equity(self, obs, rng, iterations=None):
        n = self.opponents(obs)
        iters = iterations or ITERATIONS[obs.street]
        return monte_carlo_equity(obs.hole, obs.board, n, iters, rng)

    @staticmethod
    def bet_to(obs, fraction):
        """Total street bet for a raise of `fraction` x pot, clamped legal."""
        target = obs.street_bet + obs.to_call + int(obs.pot * fraction)
        target = max(target, obs.min_raise_to)
        return min(target, obs.max_raise_to)

    @staticmethod
    def shove(obs):
        return RAISE, obs.max_raise_to

    @staticmethod
    def passive(obs):
        return (CHECK, 0) if obs.to_call == 0 else (CALL, 0)

    def act(self, obs, rng):
        return self.decide(obs, rng)


# ---------------------------------------------------------------------------
# Seat 1 -- the simple one.
# ---------------------------------------------------------------------------

class MadRabbit(Agent):
    """if my_turn then bet = ALL IN fi

    That is the entire algorithm. No cards are read. No pot odds. No board.
    """

    name = "COELHO DOIDO (All-In Bot)"
    mascot = "rabbit"

    def decide(self, obs, rng):
        return RAISE, obs.max_raise_to


# ---------------------------------------------------------------------------
# Seat 2 -- tight-aggressive, equity + pot-odds disciplined.
# ---------------------------------------------------------------------------

class Ironclad(Agent):
    """Textbook TAG.

    Preflop it plays a Chen-scored range that tightens out of position and
    against raises. Postflop it is a pure equity machine: it bets when it beats
    the field often enough to be raising for value, calls only when its equity
    clears the pot odds it is being laid plus a safety margin, and folds
    otherwise. It bluffs rarely, and only when it holds real fold equity.
    """

    name = "GORILA ALADO (Tight-Aggressive)"
    mascot = "gorilla"

    OPEN_THRESHOLD = {0: 12.0, 1: 10.5, 2: 9.0, 3: 8.0}
    CALL_MARGIN = 0.045

    def decide(self, obs, rng):
        if obs.street == PREFLOP:
            return self._preflop(obs, rng)
        return self._postflop(obs, rng)

    def _preflop(self, obs, rng):
        score = chen_score(obs.hole)
        late = obs.actors_after
        threshold = self.OPEN_THRESHOLD.get(min(late, 3), 12.0)
        facing_raise = obs.to_call > obs.big_blind
        stack_bb = obs.chips / float(obs.big_blind)

        if facing_raise:
            if obs.to_call >= obs.chips * 0.9:
                # Being put all-in is a pure price question, not a range
                # question: folding every hand below a premium just donates the
                # blinds one orbit at a time.
                eq = monte_carlo_equity(obs.hole, (), self.opponents(obs),
                                        260, rng)
                margin = 0.08 if stack_bb > 20 else 0.02
                return (CALL, 0) if eq >= self.pot_odds(obs) + margin \
                    else (FOLD, 0)
            if score >= 16:
                if stack_bb < 22:
                    return self.shove(obs)
                return RAISE, self.bet_to(obs, 1.1)
            if score >= 12.5:
                return CALL, 0
            # Cheap closing call from the big blind with a playable hand.
            if obs.to_call <= obs.big_blind * 2.5 and score >= 9:
                return CALL, 0
            return FOLD, 0

        if score >= threshold:
            if stack_bb < 15:
                return self.shove(obs)
            return RAISE, self.bet_to(obs, 1.0)
        if obs.to_call == 0:
            return CHECK, 0
        if obs.to_call <= obs.small_blind and score >= 6:
            return CALL, 0
        return FOLD, 0

    def _postflop(self, obs, rng):
        eq = self.equity(obs, rng)
        odds = self.pot_odds(obs)
        texture = board_texture(obs.board)
        draws = draw_strength(obs.hole, obs.board)
        effective = min(eq + draws * 0.5, 0.99)

        if obs.to_call == 0:
            if eq > 0.80:
                return RAISE, self.bet_to(obs, 0.75)
            if eq > 0.62:
                return RAISE, self.bet_to(obs, 0.55)
            # Occasional semi-bluff, only with a real draw on a wet board.
            if draws >= 0.25 and obs.actors_after <= 1 and rng.random() < 0.45:
                return RAISE, self.bet_to(obs, 0.5)
            return CHECK, 0

        if effective > 0.85:
            return RAISE, self.bet_to(obs, 0.8)
        if effective > odds + self.CALL_MARGIN + texture * 0.05:
            return CALL, 0
        if obs.to_call >= obs.chips * 0.9 and effective < 0.55:
            return FOLD, 0
        return FOLD, 0


# ---------------------------------------------------------------------------
# Seat 3 -- loose-aggressive pressure merchant.
# ---------------------------------------------------------------------------

class RageBaby(Agent):
    """Relentless LAG.

    Opens a very wide range, three-bets light, and fires continuation bets at a
    high frequency whether or not it connected. It leans on fold equity rather
    than showdown value, but it is not blind: it tracks how much of the pot it
    would have to risk and folds off its worst bluffs against genuine
    resistance. Its aggression is randomised so it cannot be read off a single
    pattern.
    """

    name = "BEBE RAIVA (Loose-Aggressive)"
    mascot = "baby"

    def decide(self, obs, rng):
        if obs.street == PREFLOP:
            return self._preflop(obs, rng)
        return self._postflop(obs, rng)

    def _preflop(self, obs, rng):
        score = chen_score(obs.hole)
        stack_bb = obs.chips / float(obs.big_blind)
        facing_raise = obs.to_call > obs.big_blind

        if facing_raise:
            if score >= 15:
                return self.shove(obs) if stack_bb < 25 else \
                    (RAISE, self.bet_to(obs, 1.2))
            if score >= 10:
                return CALL, 0
            # Light three-bet as a pure bluff, sized to fold out mid strength.
            if score >= 5 and obs.actors_after <= 1 and rng.random() < 0.22:
                return RAISE, self.bet_to(obs, 1.0)
            if obs.to_call <= obs.big_blind * 3 and score >= 6:
                return CALL, 0
            return FOLD, 0

        open_floor = 4.0 if obs.actors_after <= 2 else 6.0
        if score >= open_floor and rng.random() < 0.85:
            if stack_bb < 13:
                return self.shove(obs)
            return RAISE, self.bet_to(obs, 1.0)
        if obs.to_call == 0:
            return CHECK, 0
        if obs.to_call <= obs.big_blind and rng.random() < 0.5:
            return CALL, 0
        return FOLD, 0

    def _postflop(self, obs, rng):
        eq = self.equity(obs, rng)
        draws = draw_strength(obs.hole, obs.board)
        odds = self.pot_odds(obs)
        effective = min(eq + draws * 0.7, 0.99)
        heads_up = obs.num_in_hand == 2

        if obs.to_call == 0:
            if eq > 0.78:
                return RAISE, self.bet_to(obs, 0.9)
            cbet_freq = 0.78 if heads_up else 0.5
            if draws > 0:
                cbet_freq += 0.15
            if rng.random() < cbet_freq:
                return RAISE, self.bet_to(obs, 0.7)
            return CHECK, 0

        if effective > 0.82:
            return RAISE, self.bet_to(obs, 1.0)
        if effective > odds + 0.02:
            # Raise as a semi-bluff sometimes instead of just calling along.
            if draws >= 0.25 and rng.random() < 0.35:
                return RAISE, self.bet_to(obs, 0.85)
            return CALL, 0
        # Float cheap bets in position to take the pot away later.
        if obs.to_call <= obs.pot * 0.3 and obs.actors_after == 0 \
                and rng.random() < 0.4:
            return CALL, 0
        return FOLD, 0


# ---------------------------------------------------------------------------
# Seat 4 -- balanced, frequency-based, minimum-defence-frequency aware.
# ---------------------------------------------------------------------------

class ThinkingTiger(Agent):
    """Approximately balanced play.

    Rather than picking the single highest-EV action it plays a *mixed*
    strategy: equity is bucketed, and each bucket maps to a distribution over
    fold/call/raise. Facing a bet it defends at roughly the minimum defence
    frequency implied by the price (alpha = bet / (pot + bet)), choosing which
    hands to continue with by equity rank. Its own bets are polarised -- big
    with the top bucket and with the weakest bluff candidates, small with the
    merged middle -- so its sizing leaks little information.
    """

    name = "TIGRE PENSADOR (Balanced / MDF)"
    mascot = "tiger"

    def decide(self, obs, rng):
        if obs.street == PREFLOP:
            return self._preflop(obs, rng)
        return self._postflop(obs, rng)

    def _preflop(self, obs, rng):
        score = chen_score(obs.hole)
        stack_bb = obs.chips / float(obs.big_blind)
        pos = self.position(obs)
        # Open requirement slides with position instead of using hard buckets.
        requirement = 12.0 - 4.5 * pos
        facing_raise = obs.to_call > obs.big_blind

        if facing_raise:
            alpha = self.pot_odds(obs)
            if obs.to_call >= obs.chips * 0.9:
                # Minimum defence frequency applies to shoves too: continue
                # with everything that beats the price on offer.
                eq = monte_carlo_equity(obs.hole, (), self.opponents(obs),
                                        260, rng)
                return (CALL, 0) if eq >= alpha + 0.03 else (FOLD, 0)
            if score >= 16:
                return (RAISE, self.bet_to(obs, 1.1)) if stack_bb >= 25 \
                    else self.shove(obs)
            # Defend enough of the range to stop opens being auto-profitable.
            defend_score = 8.5 + alpha * 12.0
            if score >= defend_score:
                if score >= 13 and rng.random() < 0.35:
                    return RAISE, self.bet_to(obs, 1.0)
                return CALL, 0
            return FOLD, 0

        if score >= requirement:
            if stack_bb < 14:
                return self.shove(obs)
            return RAISE, self.bet_to(obs, 0.9)
        # A thin slice of the folding range is opened anyway, for balance.
        if score >= requirement - 3.0 and obs.actors_after <= 1 \
                and rng.random() < 0.3:
            return RAISE, self.bet_to(obs, 0.9)
        if obs.to_call == 0:
            return CHECK, 0
        if obs.to_call <= obs.small_blind and score >= 5:
            return CALL, 0
        return FOLD, 0

    def _postflop(self, obs, rng):
        eq = self.equity(obs, rng)
        draws = draw_strength(obs.hole, obs.board)
        texture = board_texture(obs.board)
        effective = min(eq + draws * 0.6, 0.99)
        roll = rng.random()

        if obs.to_call == 0:
            if effective > 0.82:
                # Polarised: mostly large, occasionally small to trap.
                return RAISE, self.bet_to(obs, 1.1 if roll < 0.7 else 0.4)
            if effective > 0.60:
                return (RAISE, self.bet_to(obs, 0.55)) if roll < 0.6 \
                    else (CHECK, 0)
            if effective < 0.30 and draws >= 0.25:
                bluff_freq = 0.4 + texture * 0.2
                if roll < bluff_freq:
                    return RAISE, self.bet_to(obs, 0.9)
            if effective < 0.22 and roll < 0.15:
                return RAISE, self.bet_to(obs, 0.75)      # pure bluff slice
            return CHECK, 0

        alpha = self.pot_odds(obs)
        mdf = 1.0 - alpha                    # share of range that must continue
        if effective > 0.84:
            return (RAISE, self.bet_to(obs, 0.9)) if roll < 0.75 else (CALL, 0)
        if effective > alpha + 0.03:
            # Inside the defending band; mix in raises with the top of it.
            if effective > 0.68 and roll < 0.3:
                return RAISE, self.bet_to(obs, 0.8)
            return CALL, 0
        # Bluff-catch just often enough to satisfy MDF against small bets.
        if alpha < 0.34 and roll < mdf * 0.35 and effective > 0.25:
            return CALL, 0
        return FOLD, 0


# ---------------------------------------------------------------------------
# Seat 5 -- exploitative opponent modeller.
# ---------------------------------------------------------------------------

class SkullPeaky(Agent):
    """Builds a book on every opponent and attacks the leaks.

    It records, per player and across the whole tournament, how often they
    voluntarily put money in, how often they raise rather than call, and how
    often that raise is for their entire stack. From those three numbers it
    derives an aggression index and a credibility discount: a player who shoves
    every hand carries no information in a shove, so the required equity to call
    them collapses toward a pure coinflip threshold. Against genuinely tight
    opponents it does the reverse -- it folds marginal hands and steals more.
    """

    name = "CAVEIRA PEAKY (Exploitative Modeller)"
    mascot = "skull"

    def __init__(self):
        self.stats = {}

    def reset(self):
        self.stats = {}

    def _book(self, pid):
        return self.stats.setdefault(pid, {
            "actions": 0, "voluntary": 0, "raises": 0, "shoves": 0,
            "folds": 0, "hands": 0,
        })

    def new_hand(self, hand_number, stacks):
        self._stacks_at_start = dict(stacks)
        for pid in stacks:
            self._book(pid)["hands"] += 1

    def observe_action(self, player_id, street, action, amount, pot, current_bet):
        book = self._book(player_id)
        book["actions"] += 1
        if action == FOLD:
            book["folds"] += 1
        elif action in (CALL, RAISE) and amount > 0:
            book["voluntary"] += 1
        if action == RAISE:
            book["raises"] += 1
            stack_before = getattr(self, "_stacks_at_start", {}).get(player_id)
            if stack_before and amount >= stack_before * 0.85:
                book["shoves"] += 1

    def _profile(self, pid):
        """(aggression 0-1, shove-happiness 0-1, sample size)."""
        book = self.stats.get(pid)
        if not book or book["actions"] < 6:
            return 0.5, 0.0, book["actions"] if book else 0
        aggression = book["raises"] / float(book["actions"])
        shoviness = book["shoves"] / float(max(book["raises"], 1))
        return aggression, shoviness, book["actions"]

    def _threat(self, obs):
        """How credible is the aggression currently facing us?"""
        raisers = [pid for pid, street, action, amount in obs.action_log
                   if action == RAISE]
        if not raisers:
            return 0.5, 0.0
        pid = raisers[-1]
        aggression, shoviness, sample = self._profile(pid)
        if sample < 8:
            return 0.5, 0.0
        # Credibility falls as raise frequency and shove frequency climb.
        credibility = max(0.0, 1.0 - aggression * 1.6 - shoviness * 0.5)
        return credibility, shoviness

    def decide(self, obs, rng):
        credibility, shoviness = self._threat(obs)
        if obs.street == PREFLOP:
            return self._preflop(obs, rng, credibility, shoviness)
        return self._postflop(obs, rng, credibility)

    def _preflop(self, obs, rng, credibility, shoviness):
        score = chen_score(obs.hole)
        stack_bb = obs.chips / float(obs.big_blind)
        facing_raise = obs.to_call > obs.big_blind
        all_in_call = obs.to_call >= obs.chips * 0.9

        if facing_raise:
            if all_in_call:
                # Calling off a stack: how good a hand we need depends entirely
                # on how much that shove actually means.
                eq = monte_carlo_equity(obs.hole, (), 1, 260, rng)
                required = 0.50 + credibility * 0.22
                # Getting a price on dead money in the pot lowers the bar.
                required -= max(0.0, (0.5 - self.pot_odds(obs))) * 0.25
                return (CALL, 0) if eq >= required else (FOLD, 0)
            if score >= 15:
                return (RAISE, self.bet_to(obs, 1.1)) if stack_bb >= 25 \
                    else self.shove(obs)
            need = 9.0 + credibility * 5.0
            if score >= need:
                return CALL, 0
            return FOLD, 0

        # Nobody has raised: steal wider when the table has shown it folds a lot.
        folders = [pid for pid in self.stats
                   if self.stats[pid]["actions"] >= 10 and
                   self.stats[pid]["folds"] / float(self.stats[pid]["actions"]) > 0.6]
        steal_bonus = 1.5 if len(folders) >= 2 else 0.0
        requirement = (11.5 - steal_bonus) - 3.5 * self.position(obs)
        if score >= requirement:
            if stack_bb < 14:
                return self.shove(obs)
            return RAISE, self.bet_to(obs, 1.0)
        if obs.to_call == 0:
            return CHECK, 0
        if obs.to_call <= obs.small_blind and score >= 6:
            return CALL, 0
        return FOLD, 0

    def _postflop(self, obs, rng, credibility):
        eq = self.equity(obs, rng)
        draws = draw_strength(obs.hole, obs.board)
        effective = min(eq + draws * 0.6, 0.99)
        odds = self.pot_odds(obs)

        if obs.to_call == 0:
            if effective > 0.78:
                return RAISE, self.bet_to(obs, 0.8)
            if effective > 0.58:
                return RAISE, self.bet_to(obs, 0.5)
            if draws >= 0.25 and rng.random() < 0.45:
                return RAISE, self.bet_to(obs, 0.6)
            return CHECK, 0

        # A bet from a player whose bets mean nothing gets called much lighter.
        required = odds + 0.02 + (credibility - 0.5) * 0.18
        if effective > 0.84:
            return RAISE, self.bet_to(obs, 0.85)
        if effective > required:
            return CALL, 0
        return FOLD, 0


# ---------------------------------------------------------------------------
# Seat 6 -- stack-depth and ICM driven.
# ---------------------------------------------------------------------------

class BlueDemon(Agent):
    """Plays the tournament, not the hand.

    Everything is indexed off the M-ratio (stack divided by the cost of one
    orbit) which splits play into regimes: a push-or-fold zone when short, a
    steal-heavy zone when medium, and ordinary postflop poker when deep. On top
    of that it carries a bubble factor -- when another player is about to be
    blinded out, busting is far more costly than chips won are valuable, so it
    declines marginal coinflips and lets the short stack die first.
    """

    name = "DEMONIO AZUL (M-Ratio / ICM)"
    mascot = "demon"

    def decide(self, obs, rng):
        orbit = obs.small_blind + obs.big_blind + obs.ante * obs.num_in_hand
        m = obs.chips / float(max(orbit, 1))
        bubble = self._bubble_factor(obs)
        if obs.street == PREFLOP:
            return self._preflop(obs, rng, m, bubble)
        return self._postflop(obs, rng, m, bubble)

    @staticmethod
    def _bubble_factor(obs):
        """>1 when survival is worth more than the chips on offer."""
        stacks = sorted(s.chips for s in obs.seats if s.chips > 0)
        if len(stacks) < 3:
            return 1.0
        me = obs.chips
        shortest = stacks[0]
        if me <= shortest:
            return 1.0                       # we are the short stack; gamble
        orbit = obs.small_blind + obs.big_blind
        if shortest < orbit * 4:
            return 1.35                      # somebody is one orbit from dead
        if shortest < orbit * 8:
            return 1.15
        return 1.0

    def _preflop(self, obs, rng, m, bubble):
        score = chen_score(obs.hole)
        facing_raise = obs.to_call > obs.big_blind
        all_in_call = obs.to_call >= obs.chips * 0.9

        if all_in_call:
            eq = monte_carlo_equity(obs.hole, (), self.opponents(obs), 260, rng)
            # The bubble factor raises the equity we demand to risk the stack.
            required = self.pot_odds(obs) * bubble + 0.06
            if m < 5:
                required -= 0.10             # desperate; must gamble
            return (CALL, 0) if eq >= required else (FOLD, 0)

        if m < 6:
            # Push-or-fold. Range widens as the stack shrinks and in position.
            push_floor = (7.5 - 3.0 * self.position(obs)) + (m - 3.0) * 0.9
            if facing_raise:
                return (self.shove(obs)) if score >= 13 * bubble else (FOLD, 0)
            return (self.shove(obs)) if score >= push_floor else (FOLD, 0)

        if m < 14:
            if facing_raise:
                if score >= 15:
                    return self.shove(obs)
                if score >= 11.5 * bubble and obs.to_call <= obs.chips * 0.25:
                    return CALL, 0
                return FOLD, 0
            steal_floor = (10.5 - 3.5 * self.position(obs)) * bubble
            if score >= steal_floor:
                return self.shove(obs) if m < 9 else \
                    (RAISE, self.bet_to(obs, 1.0))
            if obs.to_call == 0:
                return CHECK, 0
            return FOLD, 0

        # Deep. Play real poker, but stay allergic to stack-off coinflips.
        if facing_raise:
            if score >= 16:
                return RAISE, self.bet_to(obs, 1.1)
            if score >= 11.0 * bubble:
                return CALL, 0
            return FOLD, 0
        requirement = (11.5 - 3.5 * self.position(obs)) * (1.0 + (bubble - 1) * 0.5)
        if score >= requirement:
            return RAISE, self.bet_to(obs, 1.0)
        if obs.to_call == 0:
            return CHECK, 0
        if obs.to_call <= obs.small_blind and score >= 6:
            return CALL, 0
        return FOLD, 0

    def _postflop(self, obs, rng, m, bubble):
        eq = self.equity(obs, rng)
        draws = draw_strength(obs.hole, obs.board)
        effective = min(eq + draws * 0.55, 0.99)
        odds = self.pot_odds(obs)

        if obs.to_call == 0:
            if effective > 0.78:
                return RAISE, self.bet_to(obs, 0.75)
            if effective > 0.60 and m > 10:
                return RAISE, self.bet_to(obs, 0.5)
            if draws >= 0.3 and m < 12 and rng.random() < 0.5:
                return self.shove(obs)       # short stacks use all their fold equity
            return CHECK, 0

        stack_off = obs.to_call >= obs.chips * 0.7
        required = odds + 0.03
        if stack_off:
            required = odds * bubble + 0.05
        if effective > 0.85:
            return RAISE, self.bet_to(obs, 0.85)
        if effective > required:
            return CALL, 0
        return FOLD, 0


ROSTER = [MadRabbit, Ironclad, RageBaby, ThinkingTiger, SkullPeaky, BlueDemon]


def build_agents():
    """Fresh agent instances, seat 1 first."""
    return [cls() for cls in ROSTER]
