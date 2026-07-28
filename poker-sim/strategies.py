"""Six poker brains. Nobody knows what the others are running."""
from engine import chen_score, estimate_equity, hand_features


class YoloMcAllIn:
    """if my_turn then bet = All in fi"""
    def act(self, view):
        return ('raise', view['stack'])


class TheRock:
    """Ultra-tight nit. Plays only premium hands, folds everything else.

    Preflop: opens only Chen >= 10 (roughly TT+, AK, AQs), 3-bets/calls
    shoves only with Chen >= 12. Postflop: continues only with two pair or
    better, or an overpair; folds to any big bet without the goods.
    """
    def act(self, view):
        hole, board, to_call = view['hole'], view['board'], view['to_call']
        stack, pot, bb = view['stack'], view['pot'], view['bb']
        if view['preflop']:
            score = chen_score(hole)
            facing_shove = to_call >= stack * 0.5 or to_call > 10 * bb
            if facing_shove:
                return ('raise', stack) if score >= 12 else ('fold',)
            if score >= 10:
                return ('raise', max(view['min_raise'], 3 * bb))
            if to_call == 0:
                return ('call',)
            return ('fold',) if to_call > bb else (
                ('call',) if score >= 8 else ('fold',))
        f = hand_features(hole, board)
        strong = f['category'] >= 2 or f['overpair']
        decent = f['category'] >= 1 and (f['top_pair'] or f['overpair'])
        if strong:
            if to_call >= stack:
                return ('call',)
            return ('raise', max(view['min_raise'], pot // 2))
        if decent and to_call <= pot // 3:
            return ('call',)
        if to_call == 0:
            return ('call',)
        return ('fold',)


class TagTitan:
    """Tight-aggressive with positional awareness and continuation bets.

    Opens a position-scaled Chen range (tight early, wider on the button),
    3-bets premiums, c-bets most flops as the aggressor, and uses pot odds
    for draws. Folds to heavy aggression without top pair or better.
    """
    def __init__(self, rng):
        self.rng = rng
        self.was_aggressor = False

    def act(self, view):
        hole, board, to_call = view['hole'], view['board'], view['to_call']
        stack, pot, bb = view['stack'], view['pot'], view['bb']
        if view['preflop']:
            score = chen_score(hole)
            late = view['num_in_hand'] <= 3
            open_thresh = 7 if late else 9
            facing_big = to_call > 8 * bb
            if facing_big:
                if score >= 11 or (score >= 10 and to_call < stack * 0.4):
                    self.was_aggressor = True
                    return ('raise', stack)
                return ('fold',)
            if score >= 11:
                self.was_aggressor = True
                return ('raise', max(view['min_raise'], pot + to_call))
            if score >= open_thresh:
                self.was_aggressor = True
                return ('raise', max(view['min_raise'], 3 * bb))
            if to_call == 0:
                return ('call',)
            if score >= 6 and to_call <= 2 * bb:
                return ('call',)
            return ('fold',)
        f = hand_features(hole, board)
        strong = f['category'] >= 2 or f['overpair']
        pair_ish = f['top_pair'] or f['overpair'] or f['category'] >= 1
        draw = f['flush_draw'] or f['oesd']
        if strong:
            if to_call >= stack:
                return ('call',)
            return ('raise', max(view['min_raise'], (pot * 2) // 3))
        if draw and to_call > 0:
            pot_odds = to_call / max(1, pot + to_call)
            return ('call',) if pot_odds < 0.30 else ('fold',)
        if pair_ish:
            if to_call == 0:
                return ('raise', max(view['min_raise'], pot // 2))
            return ('call',) if to_call <= pot // 3 else ('fold',)
        if to_call == 0:
            if self.was_aggressor and self.rng.random() < 0.6:
                return ('raise', max(view['min_raise'], pot // 2))
            return ('call',)
        return ('fold',)


class LagLunatic:
    """Loose-aggressive maniac-lite: wide opens, 3-bet bluffs, semi-bluffs.

    Opens ~40% of hands, raises draws hard as semi-bluffs, fires random
    barrel bluffs, but still bails against shoves without real equity.
    """
    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        hole, board, to_call = view['hole'], view['board'], view['to_call']
        stack, pot, bb = view['stack'], view['pot'], view['bb']
        if view['preflop']:
            score = chen_score(hole)
            facing_shove = to_call >= stack * 0.5
            if facing_shove:
                return ('raise', stack) if score >= 10 else ('fold',)
            if score >= 9 or (score >= 6 and self.rng.random() < 0.5):
                bump = 3 if self.rng.random() < 0.7 else 5
                return ('raise', max(view['min_raise'], bump * bb))
            if to_call <= 3 * bb and score >= 4:
                return ('call',)
            if to_call == 0:
                return ('call',)
            return ('fold',)
        f = hand_features(hole, board)
        strong = f['category'] >= 2 or f['overpair']
        draw = f['flush_draw'] or f['oesd']
        facing_big = to_call > pot
        if strong:
            if to_call >= stack:
                return ('call',)
            return ('raise', max(view['min_raise'], pot))
        if draw:
            if to_call >= stack * 0.6:
                return ('call',) if f['flush_draw'] else ('fold',)
            return ('raise', max(view['min_raise'], (pot * 2) // 3))
        if facing_big:
            return ('fold',)
        if to_call == 0 and self.rng.random() < 0.35:
            return ('raise', max(view['min_raise'], pot // 2))
        if f['category'] >= 1 and to_call <= pot // 4:
            return ('call',)
        return ('fold',) if to_call > 0 else ('call',)


class TheProfessor:
    """Pure math: Monte Carlo equity vs pot odds, every single decision.

    Estimates win probability by simulating rollouts against random
    opponent hands, then calls when equity beats pot odds, value-raises
    with a big edge, and folds the rest. Zero psychology, all EV.
    """
    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        hole, board, to_call = view['hole'], view['board'], view['to_call']
        stack, pot, bb = view['stack'], view['pot'], view['bb']
        n_opps = min(3, max(1, view['num_in_hand'] - 1))
        if view['preflop']:
            score = chen_score(hole)
            if to_call >= stack * 0.4:
                eq = estimate_equity(hole, [], n_opps, self.rng, samples=60)
                need = to_call / max(1, pot + to_call)
                return ('raise', stack) if eq > need + 0.08 else ('fold',)
            if score >= 10:
                return ('raise', max(view['min_raise'], 3 * bb))
            if to_call == 0:
                return ('call',)
            need = to_call / max(1, pot + to_call)
            if score / 20 > need:
                return ('call',)
            return ('fold',)
        eq = estimate_equity(hole, board, n_opps, self.rng, samples=50)
        need = to_call / max(1, pot + to_call) if to_call else 0
        if eq > 0.75:
            if to_call >= stack:
                return ('call',)
            return ('raise', max(view['min_raise'], pot))
        if eq > 0.55 and to_call < stack * 0.5:
            if to_call == 0:
                return ('raise', max(view['min_raise'], pot // 2))
            return ('call',)
        if to_call == 0:
            return ('call',)
        return ('call',) if eq > need + 0.05 else ('fold',)


class TheProfiler:
    """Exploitative adapter: models opponents from observed actions only.

    Tracks shove frequency and aggression per seat (public info). Against
    frequent shovers it widens its calling range dramatically -- a maniac
    shoving every hand can be called with any decent equity edge. Against
    tight players it gives shoves respect. Plays solid TAG otherwise.
    """
    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        hole, board, to_call = view['hole'], view['board'], view['to_call']
        stack, pot, bb = view['stack'], view['pot'], view['bb']
        stats = view['stats']
        opps = view['opponents']
        max_shove_rate = max((stats.shove_rate(i) for i in opps), default=0)
        vs_maniac = max_shove_rate > 0.5 and stats.hands[view['my_index']] > 5
        if view['preflop']:
            score = chen_score(hole)
            if to_call >= stack * 0.4:
                if vs_maniac:
                    eq = estimate_equity(hole, [], 1, self.rng, samples=60)
                    return ('raise', stack) if eq > 0.52 else ('fold',)
                return ('raise', stack) if score >= 11 else ('fold',)
            if score >= 10:
                return ('raise', max(view['min_raise'], 3 * bb))
            if score >= 7 and to_call <= 3 * bb:
                return ('call',) if to_call else ('raise', max(view['min_raise'], 2 * bb))
            if to_call == 0:
                return ('call',)
            return ('fold',)
        f = hand_features(hole, board)
        strong = f['category'] >= 2 or f['overpair']
        if strong:
            if to_call >= stack:
                return ('call',)
            return ('raise', max(view['min_raise'], (pot * 3) // 4))
        if to_call >= stack * 0.5:
            n_opps = 1 if vs_maniac else min(2, len(opps))
            eq = estimate_equity(hole, board, n_opps, self.rng, samples=50)
            threshold = 0.50 if vs_maniac else 0.62
            return ('call',) if eq > threshold else ('fold',)
        if f['top_pair'] or f['category'] >= 1:
            if to_call == 0:
                return ('raise', max(view['min_raise'], pot // 2))
            return ('call',) if to_call <= pot // 2 else ('fold',)
        if f['flush_draw'] or f['oesd']:
            pot_odds = to_call / max(1, pot + to_call) if to_call else 0
            return ('call',) if pot_odds < 0.28 else ('fold',)
        return ('call',) if to_call == 0 else ('fold',)


def roster():
    return [
        ('P1 YOLO McAllIn', lambda rng: YoloMcAllIn()),
        ('P2 The Rock', lambda rng: TheRock()),
        ('P3 TAG Titan', lambda rng: TagTitan(rng)),
        ('P4 LAG Lunatic', lambda rng: LagLunatic(rng)),
        ('P5 The Professor', lambda rng: TheProfessor(rng)),
        ('P6 The Profiler', lambda rng: TheProfiler(rng)),
    ]
