"""Six strategies. Player 1 gets AllInAndy; seats 2-6 get the five elaborate
bots. No strategy is told anything about the others — they see only public
table state and observable behavior (as at a real table).

Action protocol: return ('fold',), ('call',) (a check when to_call == 0), or
('raise', target_total_bet_for_this_street). The engine clamps illegal sizes.
"""

from .equity import chen_score, estimate_equity

PRE_SAMPLES = 120   # Monte Carlo rollouts for all-in / preflop equity checks
POST_SAMPLES = 70   # rollouts for postflop equity


class Strategy:
    name = "base"

    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        raise NotImplementedError

    # ------------------------------------------------------ shared helpers

    def equity(self, view, samples):
        n_opps = view.n_live - 1
        return estimate_equity(view.hole, view.board, n_opps, samples, self.rng)

    def pot_odds(self, view):
        if view.to_call <= 0:
            return 0.0
        return view.to_call / (view.pot + view.to_call)

    def bet_to(self, view, frac):
        """Raise target sized to `frac` of the pot after calling."""
        pot_after = view.pot + view.to_call
        return view.current_bet + max(view.bb, int(frac * pot_after))

    def facing_shove(self, view):
        """A call that risks a big chunk of our stack."""
        return view.to_call >= max(0.4 * view.my_stack, 8 * view.bb)

    def stack_bb(self, view):
        return view.my_stack / view.bb


class AllInAndy(Strategy):
    """Player 1's entire strategy document:

        if my_turn
        then bet = All in
        fi
    """
    name = "AllInAndy"

    def act(self, view):
        return ('raise', view.all_in_target)


class TagTycoon(Strategy):
    """Tight-aggressive textbook grinder.

    Preflop: Chen-formula ranges that widen with position; 3-bets premiums;
    calls big shoves only with a strong equity edge. Postflop: value-bets
    2/3 pot with strong equity, calls on pot odds plus a safety margin,
    semi-bluffs the occasional strong draw, and open-shoves short stacks.
    """
    name = "TAG Tycoon"

    def act(self, view):
        if view.street == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        chen = chen_score(view.hole)
        if self.stack_bb(view) < 10:  # short-stack push/fold
            if chen >= 8 or (view.to_call <= view.bb and chen >= 6.5):
                return ('raise', view.all_in_target)
            return ('fold',) if view.to_call > 0 else ('call',)
        if self.facing_shove(view):
            eq = estimate_equity(view.hole, view.board, 1, PRE_SAMPLES, self.rng)
            need = self.pot_odds(view) + 0.10
            return ('call',) if eq >= max(need, 0.56) else ('fold',)
        unopened = view.current_bet <= view.bb
        threshold = 9.0 - 2.5 * view.pos_frac  # ~9 early, ~6.5 on the button
        if unopened:
            if chen >= threshold:
                return ('raise', max(3 * view.bb, view.min_raise_to))
            return ('fold',) if view.to_call > 0 else ('call',)
        # facing a normal raise
        if chen >= 11:
            return ('raise', max(view.min_raise_to, view.current_bet * 3))
        if chen >= threshold + 1 and self.pot_odds(view) < 0.25:
            return ('call',)
        return ('fold',) if view.to_call > 0 else ('call',)

    def _postflop(self, view):
        eq = self.equity(view, POST_SAMPLES)
        odds = self.pot_odds(view)
        if view.to_call == 0:
            if eq > 0.62:
                return ('raise', self.bet_to(view, 0.66))
            if eq > 0.45 and view.pos_frac > 0.6 and self.rng.random() < 0.35:
                return ('raise', self.bet_to(view, 0.5))  # probe/semi-bluff
            return ('call',)
        if eq > 0.72:
            return ('raise', self.bet_to(view, 0.8))
        if eq >= odds + 0.06:
            return ('call',)
        return ('fold',)


class LagLucia(Strategy):
    """Loose-aggressive pressure machine.

    Wide opens (especially in position), light 3-bets, relentless c-bets
    when she was the last preflop aggressor, randomized bluffs and
    semi-bluff barrels. Backs off only when the math is truly dire.
    """
    name = "LAG Lucia"

    def __init__(self, rng):
        super().__init__(rng)
        self._aggro_hand = -1  # hand_no where she was preflop aggressor

    def act(self, view):
        if view.street == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        chen = chen_score(view.hole)
        if self.stack_bb(view) < 12:
            if chen >= 7 or (view.pos_frac > 0.6 and chen >= 5.5):
                self._aggro_hand = view.hand_no
                return ('raise', view.all_in_target)
            return ('fold',) if view.to_call > 0 else ('call',)
        if self.facing_shove(view):
            eq = estimate_equity(view.hole, view.board, 1, PRE_SAMPLES, self.rng)
            return ('call',) if eq >= max(self.pot_odds(view) + 0.06, 0.52) else ('fold',)
        unopened = view.current_bet <= view.bb
        threshold = 7.0 - 2.5 * view.pos_frac  # opens ~40% on the button
        if unopened:
            if chen >= threshold or self.rng.random() < 0.12:
                self._aggro_hand = view.hand_no
                return ('raise', max(int(2.5 * view.bb), view.min_raise_to))
            return ('fold',) if view.to_call > 0 else ('call',)
        if chen >= 10 or (chen >= 8 and self.rng.random() < 0.35):
            self._aggro_hand = view.hand_no
            return ('raise', max(view.min_raise_to, int(view.current_bet * 2.7)))
        if chen >= 6 and self.pot_odds(view) < 0.3:
            return ('call',)
        return ('fold',) if view.to_call > 0 else ('call',)

    def _postflop(self, view):
        eq = self.equity(view, POST_SAMPLES)
        odds = self.pot_odds(view)
        was_aggressor = self._aggro_hand == view.hand_no
        if view.to_call == 0:
            if eq > 0.58:
                return ('raise', self.bet_to(view, 0.75))
            if was_aggressor and view.street == 'flop' and self.rng.random() < 0.7:
                return ('raise', self.bet_to(view, 0.55))  # c-bet almost always
            if self.rng.random() < 0.18:
                return ('raise', self.bet_to(view, 0.6))   # pure bluff stab
            return ('call',)
        if eq > 0.68:
            return ('raise', self.bet_to(view, 0.9))
        if eq >= odds + 0.02:
            return ('call',)
        if eq >= odds - 0.05 and self.rng.random() < 0.25:
            return ('call',)  # sticky float
        return ('fold',)


class RockReginald(Strategy):
    """Ultra-tight nit. Folds for a living, then makes you pay.

    Plays only premium hands (roughly TT+, AK, AQs/AJs), never bluffs,
    and calls all-ins only holding a premium with real equity. Postflop
    he continues only with a genuinely strong made hand. Designed to
    let maniacs hang themselves.
    """
    name = "Rock Reginald"

    def act(self, view):
        if view.street == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        chen = chen_score(view.hole)
        if self.facing_shove(view) or self.stack_bb(view) < 8:
            if chen >= 10:
                eq = estimate_equity(view.hole, view.board, 1, PRE_SAMPLES, self.rng)
                if eq >= 0.58:
                    return ('raise', view.all_in_target)  # premium: get it in
            return ('fold',) if view.to_call > 0 else ('call',)
        if chen >= 10:
            if view.current_bet > view.bb:
                return ('raise', max(view.min_raise_to, view.current_bet * 3))
            return ('raise', max(3 * view.bb, view.min_raise_to))
        if chen >= 9 and self.pot_odds(view) < 0.15:
            return ('call',)
        return ('fold',) if view.to_call > 0 else ('call',)

    def _postflop(self, view):
        eq = self.equity(view, POST_SAMPLES)
        if view.to_call == 0:
            if eq > 0.75:
                return ('raise', self.bet_to(view, 1.0))
            if eq > 0.6:
                return ('raise', self.bet_to(view, 0.5))
            return ('call',)
        odds = self.pot_odds(view)
        if eq > 0.78:
            return ('raise', self.bet_to(view, 1.0))
        if eq >= odds + 0.12:  # continues only with a clear edge
            return ('call',)
        return ('fold',)


class OddsOracle(Strategy):
    """Cold-blooded pot-odds mathematician.

    Every decision is Monte Carlo equity versus required pot odds, with
    value-raises when equity dwarfs the price, thin calls exactly at the
    price, and a small randomized bluff frequency so she is not perfectly
    exploitable. Position and stack depth nudge the margins.
    """
    name = "Odds Oracle"

    def act(self, view):
        samples = PRE_SAMPLES if view.street == 'preflop' else POST_SAMPLES
        eq = self.equity(view, samples)
        odds = self.pot_odds(view)
        n_opps = view.n_live - 1
        fair_share = 1.0 / (n_opps + 1)
        if self.stack_bb(view) < 10 and view.street == 'preflop':
            if eq >= fair_share + 0.12:
                return ('raise', view.all_in_target)
            return ('call',) if view.to_call == 0 else \
                (('call',) if eq >= odds + 0.03 else ('fold',))
        if view.to_call == 0:
            if eq >= fair_share + 0.18:
                return ('raise', self.bet_to(view, 0.7))
            if eq >= fair_share + 0.08:
                return ('raise', self.bet_to(view, 0.45))
            if self.rng.random() < 0.08:
                return ('raise', self.bet_to(view, 0.6))  # balancing bluff
            return ('call',)
        risk = view.to_call / max(view.my_stack + view.to_call, 1)
        margin = 0.02 + 0.10 * risk  # demand more edge when the call is huge
        if eq >= odds + margin + 0.18:
            return ('raise', self.bet_to(view, 0.85))
        if eq >= odds + margin:
            return ('call',)
        return ('fold',)


class ProfilerPetra(Strategy):
    """Adaptive exploitation engine.

    Builds a live profile of every seat (VPIP, aggression, shove rate) and
    attacks the leaks: calls maniacs' shoves with any decent equity edge
    versus a random hand, tightens up against nits' aggression, steals
    blinds from tight tables in late position, and switches to push/fold
    when short. The counter-strategy for a table with a bot that always
    jams.
    """
    name = "Profiler Petra"

    MANIAC_SHOVE = 0.40
    NIT_VPIP = 0.20

    def act(self, view):
        if view.street == 'preflop':
            return self._preflop(view)
        return self._postflop(view)

    def _profile(self, view, seat):
        if seat < 0 or seat not in view.stats:
            return 'unknown'
        s = view.stats[seat]
        if s.hands < 5:
            return 'unknown'
        if s.shove_freq > self.MANIAC_SHOVE:
            return 'maniac'
        if s.vpip_freq < self.NIT_VPIP:
            return 'nit'
        return 'normal'

    def _preflop(self, view):
        chen = chen_score(view.hole)
        aggressor = self._profile(view, view.last_aggressor_seat)
        heads_up = view.n_live == 2

        if self.facing_shove(view):
            eq = estimate_equity(view.hole, view.board, 1, PRE_SAMPLES, self.rng)
            need = self.pot_odds(view)
            if aggressor == 'maniac':
                # His range is any two cards: any real edge is a snap call.
                bar = need + 0.02 if heads_up else max(need + 0.02, 0.52)
                return ('call',) if eq >= bar else ('fold',)
            if aggressor == 'nit':
                return ('call',) if eq >= 0.62 else ('fold',)
            return ('call',) if eq >= max(need + 0.08, 0.55) else ('fold',)

        if self.stack_bb(view) < 10:
            if chen >= 7 or (heads_up and chen >= 5):
                return ('raise', view.all_in_target)
            return ('fold',) if view.to_call > 0 else ('call',)

        unopened = view.current_bet <= view.bb
        table_tight = self._table_tightness(view)
        if unopened:
            threshold = 8.5 - 2.5 * view.pos_frac
            if table_tight and view.pos_frac > 0.6:
                threshold -= 1.5  # steal wide against folders
            if chen >= threshold:
                return ('raise', max(int(2.5 * view.bb), view.min_raise_to))
            return ('fold',) if view.to_call > 0 else ('call',)

        if aggressor == 'nit':
            if chen >= 11:
                return ('raise', max(view.min_raise_to, view.current_bet * 3))
            return ('fold',) if view.to_call > 0 else ('call',)
        if chen >= 10:
            return ('raise', max(view.min_raise_to, view.current_bet * 3))
        if chen >= 7 and self.pot_odds(view) < 0.28:
            return ('call',)
        return ('fold',) if view.to_call > 0 else ('call',)

    def _table_tightness(self, view):
        live = [o['seat'] for o in view.opponents if not o['folded']]
        profiles = [self._profile(view, s) for s in live]
        known = [p for p in profiles if p != 'unknown']
        return bool(known) and all(p == 'nit' for p in known)

    def _postflop(self, view):
        eq = self.equity(view, POST_SAMPLES)
        odds = self.pot_odds(view)
        aggressor = self._profile(view, view.last_aggressor_seat)
        if view.to_call == 0:
            if eq > 0.60:
                return ('raise', self.bet_to(view, 0.7))
            if eq > 0.45 and self._table_tightness(view) and self.rng.random() < 0.4:
                return ('raise', self.bet_to(view, 0.55))
            return ('call',)
        margin = 0.05
        if aggressor == 'maniac':
            margin = -0.02  # his bets mean nothing; pay off lighter
        elif aggressor == 'nit':
            margin = 0.14   # his bets mean the nuts; get out
        if eq >= odds + margin + 0.20:
            return ('raise', self.bet_to(view, 0.85))
        if eq >= odds + margin:
            return ('call',)
        return ('fold',)


def default_lineup(rng_factory):
    """Seat 1: AllInAndy. Seats 2-6: the five elaborate strategies."""
    return [
        AllInAndy(rng_factory()),
        TagTycoon(rng_factory()),
        LagLucia(rng_factory()),
        RockReginald(rng_factory()),
        OddsOracle(rng_factory()),
        ProfilerPetra(rng_factory()),
    ]
