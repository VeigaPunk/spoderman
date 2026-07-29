"""Six poker bots.

Every bot sees only legal public information through ``view`` (its own hole
cards, the board, pot, stacks, blinds and the action history of the current
hand) plus whatever it remembered from watching previous hands. No bot knows
what algorithm any other bot runs.

Actions returned to the engine: ``('fold', 0)``, ``('call', 0)`` (a call with
to_call == 0 is a check) or ``('raise', raise_to)`` where raise_to is the
total street contribution the bot wants to reach. The engine clamps illegal
amounts, so bots may bid the moon: bidding more than their stack simply means
all-in.
"""

from .handreading import (
    chen_score, made_strength, draw_equity_bonus, detect_draws, pot_odds,
)
from .cards import equity_vs_random

ALL_IN = 10 ** 9


class Strategy:
    """Base class. ``pid`` (own seat id) is stamped on by the engine."""

    def __init__(self, rng):
        self.rng = rng
        self.pid = None

    def act(self, view):
        raise NotImplementedError

    def on_action(self, event):
        """Public action broadcast: {pid, street, action, amount, all_in}."""

    def on_hand_end(self, info):
        """Public hand result: {winners, pot, showdown: [(pid, hole)]}."""


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, as specified:
#
#     if my_turn
#     then bet = All in
#     fi
# ---------------------------------------------------------------------------
class LeeroyJenkins(Strategy):
    def act(self, view):
        my_turn = True  # act() is only ever called on our turn
        if my_turn:
            bet = ALL_IN
            return ('raise', bet)
        # fi


# ---------------------------------------------------------------------------
# Player 2 — "The Professor": textbook tight-aggressive. Chen formula
# preflop, made-hand strength vs pot odds postflop, position aware,
# push/fold when short.
# ---------------------------------------------------------------------------
class TheProfessor(Strategy):
    def act(self, view):
        if view['street'] == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        bb = view['big_blind']
        chen = chen_score(view['hole'])
        to_call = view['to_call']
        late = view['position_ratio'] >= 0.6
        stack_bb = view['my_stack'] / bb

        if stack_bb <= 8:  # push/fold mode
            if chen >= 8 or (late and chen >= 6):
                return ('raise', ALL_IN)
            return ('fold', 0)

        facing_raise = view['current_bet'] > bb
        if facing_raise:
            if chen >= 12:
                return ('raise', view['min_raise_to'] + 2 * bb)
            if chen >= 9 and pot_odds(view) < 0.35:
                return ('call', 0)
            return ('fold', 0)
        if chen >= 9:
            return ('raise', 3 * bb)
        if chen >= 7 and (late or to_call <= bb):
            return ('call', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)

    def _postflop(self, view):
        strength = made_strength(view['hole'], view['board'])
        equity = min(0.98, strength + draw_equity_bonus(view['hole'], view['board']))
        to_call = view['to_call']
        pot = view['pot']

        if to_call == 0:
            if strength >= 0.62:
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.66)))
            if strength >= 0.5 and self.rng.random() < 0.5:
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.5)))
            fd, sd = detect_draws(view['hole'], view['board'])
            if (fd or sd == 'oesd') and self.rng.random() < 0.35:
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.5)))
            return ('call', 0)

        odds = pot_odds(view)
        if strength >= 0.8:
            return ('raise', view['current_bet'] + max(view['min_raise_to'] - view['current_bet'], pot // 2))
        if equity > odds + 0.03:
            return ('call', 0)
        return ('fold', 0)


# ---------------------------------------------------------------------------
# Player 3 — "La Cobra": loose-aggressive. Steals wide in position,
# c-bets relentlessly, semi-bluff raises draws, double barrels, but can
# release when the math turns hopeless.
# ---------------------------------------------------------------------------
class LaCobra(Strategy):
    def __init__(self, rng):
        super().__init__(rng)
        self._aggressor = False

    def act(self, view):
        if view['street'] == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        bb = view['big_blind']
        chen = chen_score(view['hole'])
        late = view['position_ratio'] >= 0.5
        stack_bb = view['my_stack'] / bb
        self._aggressor = False

        if stack_bb <= 10:
            if chen >= 7 or (late and chen >= 5):
                self._aggressor = True
                return ('raise', ALL_IN)
            return ('fold', 0)

        facing_raise = view['current_bet'] > bb
        has_blocker = any(c[0] >= 13 for c in view['hole'])
        if facing_raise:
            if chen >= 11 or (chen >= 8 and has_blocker and self.rng.random() < 0.35):
                self._aggressor = True
                return ('raise', view['current_bet'] * 3)
            if chen >= 8 and pot_odds(view) < 0.4:
                return ('call', 0)
            return ('fold', 0)
        if (late and chen >= 5) or chen >= 8:
            self._aggressor = True
            return ('raise', int(2.5 * bb) + view['to_call'])
        suited_connector = (view['hole'][0][1] == view['hole'][1][1]
                           and abs(view['hole'][0][0] - view['hole'][1][0]) <= 2)
        if suited_connector or chen >= 6 or view['to_call'] == 0:
            return ('call', 0)
        return ('fold', 0)

    def _postflop(self, view):
        strength = made_strength(view['hole'], view['board'])
        fd, sd = detect_draws(view['hole'], view['board'])
        equity = min(0.98, strength + draw_equity_bonus(view['hole'], view['board']))
        pot = view['pot']
        to_call = view['to_call']
        street = view['street']

        if to_call == 0:
            cbet = self._aggressor and street == 'flop' and self.rng.random() < 0.7
            barrel = self._aggressor and street == 'turn' and self.rng.random() < 0.4
            if strength >= 0.55 or fd or sd == 'oesd' or cbet or barrel:
                self._aggressor = True
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.75)))
            if street == 'river' and strength < 0.3 and self.rng.random() < 0.15:
                return ('raise', view['my_street_contrib'] + int(pot * 0.66))  # stab
            return ('call', 0)

        # facing aggression: semi-bluff raise draws, continue with equity
        if (fd or sd == 'oesd') and street != 'river' and self.rng.random() < 0.45:
            return ('raise', view['current_bet'] * 3)
        if strength >= 0.72:
            return ('raise', view['current_bet'] * 3)
        odds = pot_odds(view)
        if equity > odds:
            return ('call', 0)
        if strength >= 0.45 and odds < 0.3:
            return ('call', 0)
        return ('fold', 0)


# ---------------------------------------------------------------------------
# Player 4 — "The Rock": ultra-tight. Folds almost everything, plays
# premiums hard, occasionally slow-plays a monster so the tightness is
# not perfectly readable.
# ---------------------------------------------------------------------------
class TheRock(Strategy):
    def act(self, view):
        if view['street'] == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        bb = view['big_blind']
        chen = chen_score(view['hole'])
        stack_bb = view['my_stack'] / bb
        facing_allin = view['to_call'] >= view['my_stack']

        if stack_bb <= 6 and chen >= 9:
            return ('raise', ALL_IN)
        if facing_allin or view['to_call'] > 6 * bb:
            return ('call', 0) if chen >= 12 else ('fold', 0)
        if chen >= 14:
            return ('raise', ALL_IN if stack_bb <= 15 else 4 * bb + view['to_call'])
        if chen >= 10:
            return ('raise', 3 * bb + view['to_call'])
        if view['to_call'] == 0:
            return ('call', 0)
        if chen >= 8 and view['to_call'] <= bb:
            return ('call', 0)
        return ('fold', 0)

    def _postflop(self, view):
        strength = made_strength(view['hole'], view['board'])
        pot = view['pot']
        to_call = view['to_call']

        if strength >= 0.85 and to_call == 0 and self.rng.random() < 0.25:
            return ('call', 0)  # slow-play trap
        if strength >= 0.75:
            return ('raise', max(view['min_raise_to'], view['current_bet'] + pot))
        if to_call == 0:
            if strength >= 0.6:
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.6)))
            return ('call', 0)
        if strength >= 0.6 and pot_odds(view) < 0.45:
            return ('call', 0)
        if strength >= 0.45 and pot_odds(view) < 0.2:
            return ('call', 0)
        return ('fold', 0)


# ---------------------------------------------------------------------------
# Player 5 — "The Oracle": pure math. Monte Carlo equity against random
# hands, compared with pot odds; bets when equity clears a fair-share
# threshold. No reads, no fear, just variance-reduced arithmetic.
# ---------------------------------------------------------------------------
class TheOracle(Strategy):
    PRE_ROLLOUTS = 24
    POST_ROLLOUTS = 40

    def _equity(self, view):
        n_opp = min(3, max(1, view['players_in_hand'] - 1))
        rollouts = self.PRE_ROLLOUTS if view['street'] == 'preflop' else self.POST_ROLLOUTS
        eq = equity_vs_random(view['hole'], view['board'], n_opp, self.rng, rollouts)
        return eq, n_opp

    def act(self, view):
        eq, n_opp = self._equity(view)
        fair_share = 1.0 / (n_opp + 1)
        pot = view['pot']
        to_call = view['to_call']
        bb = view['big_blind']
        stack_bb = view['my_stack'] / bb

        if stack_bb <= 7 and view['street'] == 'preflop':
            return ('raise', ALL_IN) if eq > fair_share + 0.08 else ('fold', 0)

        if to_call == 0:
            if eq > fair_share + 0.22:
                return ('raise', view['my_street_contrib'] + max(bb, int(pot * 0.8)))
            if eq > fair_share + 0.12:
                return ('raise', view['my_street_contrib'] + max(bb, int(pot * 0.5)))
            return ('call', 0)

        odds = pot_odds(view)
        if eq > fair_share + 0.25 and view['street'] != 'preflop':
            return ('raise', view['current_bet'] + max(view['min_raise_to'] - view['current_bet'], int(pot * 0.75)))
        if eq > odds + 0.02:
            return ('call', 0)
        if eq > odds - 0.03 and self.rng.random() < 0.3:
            return ('call', 0)  # thin mixed call
        return ('fold', 0)


# ---------------------------------------------------------------------------
# Player 6 — "The Vulture": exploitative profiler. Watches every public
# action, builds per-opponent aggression stats, then calls maniacs down
# light, bullies the tight, and stays honest against the balanced.
# ---------------------------------------------------------------------------
class TheVulture(Strategy):
    def __init__(self, rng):
        super().__init__(rng)
        self.acts = {}      # pid -> observed voluntary actions
        self.raises = {}    # pid -> raises
        self.allins = {}    # pid -> all-in shoves
        self.folds = {}     # pid -> folds

    def on_action(self, event):
        pid = event['pid']
        if pid == self.pid:
            return
        self.acts[pid] = self.acts.get(pid, 0) + 1
        if event['action'] == 'raise':
            self.raises[pid] = self.raises.get(pid, 0) + 1
            if event['all_in']:
                self.allins[pid] = self.allins.get(pid, 0) + 1
        elif event['action'] == 'fold':
            self.folds[pid] = self.folds.get(pid, 0) + 1

    def _maniac_level(self, pid):
        """0..1: how often this opponent shoves/raises when acting."""
        n = self.acts.get(pid, 0)
        if n < 4:
            return 0.0
        return (self.raises.get(pid, 0) + self.allins.get(pid, 0)) / (2 * n)

    def _table_reads(self, view):
        """Max maniac level among opponents still in the hand, and whether
        the current bet appears to come from a maniac."""
        opp_ids = [o['pid'] for o in view['opponents'] if o['in_hand']]
        maniac = max((self._maniac_level(p) for p in opp_ids), default=0.0)
        bettor = None
        for ev in reversed(view['history']):
            if ev['action'] == 'raise' and ev['pid'] != self.pid:
                bettor = ev['pid']
                break
        bettor_maniac = self._maniac_level(bettor) if bettor is not None else 0.0
        return maniac, bettor_maniac

    def act(self, view):
        if view['street'] == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        bb = view['big_blind']
        chen = chen_score(view['hole'])
        _, bettor_maniac = self._table_reads(view)
        stack_bb = view['my_stack'] / bb
        facing_big = view['to_call'] > 4 * bb

        # Discount required strength in proportion to how wild the bettor is.
        call_req = 11 - 4 * bettor_maniac      # 11 vs unknown, 7 vs pure maniac
        shove_req = 13 - 4 * bettor_maniac

        if facing_big or view['to_call'] >= view['my_stack']:
            if chen >= shove_req:
                return ('raise', ALL_IN)
            if chen >= call_req:
                return ('call', 0)
            return ('fold', 0)

        if stack_bb <= 8:
            return ('raise', ALL_IN) if chen >= 7 else ('fold', 0)

        folds_seen = sum(1 for ev in view['history'] if ev['action'] == 'fold')
        unopened = view['current_bet'] <= bb
        late = view['position_ratio'] >= 0.6
        if unopened and late and folds_seen >= view['players_in_hand'] and self.rng.random() < 0.55:
            return ('raise', int(2.3 * bb) + view['to_call'])  # steal
        if chen >= 9:
            return ('raise', 3 * bb + view['to_call'])
        if chen >= 6 and view['to_call'] <= bb:
            return ('call', 0)
        if view['to_call'] == 0:
            return ('call', 0)
        return ('fold', 0)

    def _postflop(self, view):
        strength = made_strength(view['hole'], view['board'])
        equity = min(0.98, strength + draw_equity_bonus(view['hole'], view['board']))
        _, bettor_maniac = self._table_reads(view)
        pot = view['pot']
        to_call = view['to_call']

        if to_call == 0:
            if strength >= 0.6:
                return ('raise', view['my_street_contrib'] + max(view['big_blind'], int(pot * 0.66)))
            return ('call', 0)

        # A maniac's bet devalues: bluff-catch much lighter against them.
        odds = pot_odds(view)
        required = odds + 0.05 - 0.25 * bettor_maniac
        if strength >= 0.78:
            return ('raise', view['current_bet'] + max(view['min_raise_to'] - view['current_bet'], pot))
        if equity > required:
            return ('call', 0)
        return ('fold', 0)


def lineup(rng_factory):
    """The tournament lineup: (display name, strategy instance) per seat."""
    return [
        ("Leeroy ALL-IN", LeeroyJenkins(rng_factory())),
        ("The Professor", TheProfessor(rng_factory())),
        ("La Cobra", LaCobra(rng_factory())),
        ("The Rock", TheRock(rng_factory())),
        ("The Oracle", TheOracle(rng_factory())),
        ("The Vulture", TheVulture(rng_factory())),
    ]
