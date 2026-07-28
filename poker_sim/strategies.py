"""Six strategies. Players never see each other's strategy — only public
actions via state.history."""
from holdem import chen_score, equity_montecarlo


class AllInMonkey:
    """Player 1: if my_turn then bet = All in. Fi."""
    name = "All-In Monkey"

    def act(self, s, rng):
        return ('raise', s.my_bet + s.my_chips)


class TightAggressive:
    """TAG: Chen-formula preflop ranges by position, equity-driven value
    betting postflop, folds to heavy aggression without the goods."""
    name = "Tight-Aggressive"

    def act(self, s, rng):
        if s.street == 'preflop':
            score = chen_score(s.hole)
            late = s.position <= max(1, s.n_players // 3)
            threshold = 7 if late else 9
            if score >= 11:
                return ('raise', s.pot + s.to_call + 3 * s.big_blind)
            if score >= threshold:
                if s.to_call <= 4 * s.big_blind:
                    return ('raise', s.to_call + s.my_bet + 3 * s.big_blind) \
                        if s.to_call <= s.big_blind else ('call', 0)
                return ('call', 0) if score >= 10 else ('fold', 0)
            return ('check', 0) if s.to_call == 0 else ('fold', 0)

        eq = equity_montecarlo(s.hole, s.board, s.n_active - 1, rng, samples=50)
        pot_odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if eq > 0.75:
            return ('raise', s.my_bet + s.to_call + int(0.8 * s.pot))
        if eq > 0.55 and s.to_call <= s.pot // 2:
            if s.to_call == 0:
                return ('raise', s.my_bet + int(0.6 * s.pot))
            return ('call', 0)
        if s.to_call == 0:
            return ('check', 0)
        return ('call', 0) if eq > pot_odds + 0.08 else ('fold', 0)


class LooseAggressive:
    """LAG: wide ranges, frequent pressure, positional steals and bluffs,
    but bails when the math turns hopeless."""
    name = "Loose-Aggressive"

    def act(self, s, rng):
        if s.street == 'preflop':
            score = chen_score(s.hole)
            steal = s.position <= 1 and s.to_call <= s.big_blind
            if score >= 9 or (steal and rng.random() < 0.5):
                return ('raise', s.my_bet + s.to_call + 3 * s.big_blind)
            if score >= 6 and s.to_call <= 3 * s.big_blind:
                return ('call', 0)
            return ('check', 0) if s.to_call == 0 else ('fold', 0)

        eq = equity_montecarlo(s.hole, s.board, s.n_active - 1, rng, samples=40)
        bluffing = rng.random() < 0.22 and s.n_active <= 3
        if eq > 0.6 or (bluffing and s.to_call == 0):
            return ('raise', s.my_bet + s.to_call + int(0.75 * s.pot))
        pot_odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if s.to_call == 0:
            return ('check', 0)
        return ('call', 0) if eq > pot_odds else ('fold', 0)


class Rock:
    """Nit: plays only premium hands, but plays them for stacks."""
    name = "Rock"

    def act(self, s, rng):
        if s.street == 'preflop':
            score = chen_score(s.hole)
            if score >= 12:
                return ('raise', s.my_bet + s.my_chips)  # premiums go in
            if score >= 10:
                return ('raise', s.my_bet + s.to_call + 4 * s.big_blind)
            if score >= 8 and s.to_call <= 2 * s.big_blind:
                return ('call', 0)
            return ('check', 0) if s.to_call == 0 else ('fold', 0)

        eq = equity_montecarlo(s.hole, s.board, s.n_active - 1, rng, samples=50)
        if eq > 0.8:
            return ('raise', s.my_bet + s.my_chips)
        if eq > 0.65:
            return ('raise', s.my_bet + s.to_call + s.pot)
        if s.to_call == 0:
            return ('check', 0)
        pot_odds = s.to_call / (s.pot + s.to_call)
        return ('call', 0) if eq > pot_odds + 0.15 else ('fold', 0)


class MathProfessor:
    """Pure EV: Monte Carlo equity vs pot odds every street, semi-bluffs
    when fold equity plus draw equity beats folding."""
    name = "Math Professor"

    def act(self, s, rng):
        n_opp = max(1, s.n_active - 1)
        eq = equity_montecarlo(s.hole, s.board, n_opp, rng,
                               samples=80 if s.street != 'preflop' else 50)
        pot_odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        fair = 1.0 / s.n_active

        if eq > fair * 1.9:
            return ('raise', s.my_bet + s.to_call + int(0.9 * s.pot))
        if eq > fair * 1.4:
            if s.to_call == 0:
                return ('raise', s.my_bet + int(0.5 * s.pot))
            return ('call', 0) if eq > pot_odds else ('fold', 0)
        if s.to_call == 0:
            # occasional semi-bluff with live equity
            if 0.30 < eq < 0.45 and rng.random() < 0.3:
                return ('raise', s.my_bet + int(0.5 * s.pot))
            return ('check', 0)
        return ('call', 0) if eq > pot_odds + 0.03 else ('fold', 0)


class Profiler:
    """Exploitative: tracks each opponent's aggression from the public
    action history and widens calling ranges against maniacs (looking at
    you, seat 1) while respecting raises from passive players."""
    name = "Profiler"

    def __init__(self):
        self.raises = {}
        self.actions = {}

    def _observe(self, history):
        for idx, act, _ in history[len(getattr(self, '_seen', [])):]:
            self.actions[idx] = self.actions.get(idx, 0) + 1
            if act == 'raise':
                self.raises[idx] = self.raises.get(idx, 0) + 1
        self._seen = list(history)

    def _aggression(self, idx):
        a = self.actions.get(idx, 0)
        if a < 5:
            return 0.5
        return self.raises.get(idx, 0) / a

    def act(self, s, rng):
        self._observe(s.history)
        # aggression of whoever bet into us: use table max as proxy
        aggressors = [self._aggression(i) for i in self.actions] or [0.5]
        table_aggro = max(aggressors)
        # vs maniacs, equity needed to call drops sharply
        discount = 0.18 * (table_aggro - 0.5)

        if s.street == 'preflop':
            score = chen_score(s.hole)
            need = 9 - 6 * discount
            if score >= 11:
                return ('raise', s.my_bet + s.to_call + 3 * s.big_blind)
            if score >= need:
                return ('call', 0) if s.to_call else \
                    ('raise', s.my_bet + 2 * s.big_blind)
            return ('check', 0) if s.to_call == 0 else ('fold', 0)

        eq = equity_montecarlo(s.hole, s.board, s.n_active - 1, rng, samples=60)
        pot_odds = s.to_call / (s.pot + s.to_call) if s.to_call else 0
        if eq > 0.7:
            return ('raise', s.my_bet + s.to_call + s.pot)
        if s.to_call == 0:
            return ('raise', s.my_bet + int(0.5 * s.pot)) if eq > 0.55 \
                else ('check', 0)
        return ('call', 0) if eq > pot_odds + 0.06 - discount else ('fold', 0)
