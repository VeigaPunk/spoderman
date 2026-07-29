"""Player strategies.

Strategies see only public information plus their own hole cards: the board,
pot, bets, stacks, and the action history of the current hand. No strategy has
any knowledge of another player's algorithm — anything they learn about an
opponent must be inferred from observed actions.

A strategy returns one of:
    ('fold',)
    ('call',)              # also means "check" when nothing to call
    ('raise', target)      # target = desired TOTAL street commitment

The engine legalizes every action (min-raise, all-in clamping, etc.).
"""

from .evaluator import evaluate, fresh_deck


# ---------------------------------------------------------------------------
# Shared, public-information helpers
# ---------------------------------------------------------------------------

def chen_score(hole):
    """Bill Chen's preflop hand formula (slightly simplified)."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    base = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if s1 == s2:
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        score += 1
    return score


def detect_draws(hole, board):
    """(flush_draw, open_ended, gutshot) for hole+board (board length 3 or 4)."""
    cards = hole + board
    suit_count = [0, 0, 0, 0]
    for _, s in cards:
        suit_count[s] += 1
    flush_draw = any(c == 4 for c in suit_count)

    ranks = set(r for r, _ in cards)
    if 14 in ranks:
        ranks.add(1)
    open_ended = False
    gutshot = False
    for low in range(1, 12):
        window = [low + i in ranks for i in range(5)]
        hits = sum(window)
        if hits == 5:
            continue  # made straight, not a draw
        if hits == 4:
            if not window[0] or not window[4]:
                gutshot = True
            if window[0] and window[1] and window[2] and window[3]:
                open_ended = True
    return flush_draw, open_ended, gutshot


def postflop_strength(hole, board):
    """Crude 0..1 made-hand strength score from public info + own cards."""
    cards = hole + board
    cat = evaluate(cards)[0]
    board_cat = evaluate(board)[0] if len(board) >= 5 else -1
    hole_ranks = sorted((r for r, _ in hole), reverse=True)
    board_ranks = sorted((r for r, _ in board), reverse=True)
    top_board = board_ranks[0]

    if cat >= 5:
        score = 0.97
    elif cat == 4:
        score = 0.92
    elif cat == 3:
        score = 0.85
    elif cat == 2:
        score = 0.72
    elif cat == 1:
        pair_rank = evaluate(cards)[1]
        if hole_ranks[0] == hole_ranks[1] and hole_ranks[0] > top_board:
            score = 0.66                       # overpair
        elif pair_rank == top_board and pair_rank in hole_ranks:
            score = 0.58 + (hole_ranks[0] if hole_ranks[0] != pair_rank
                            else hole_ranks[1]) / 200.0   # top pair + kicker
        elif pair_rank in hole_ranks:
            score = 0.42                       # middle/bottom pair
        else:
            score = 0.28                       # board pair only
    else:
        score = 0.24 if hole_ranks[0] == 14 else 0.14

    if cat == board_cat and board_cat >= 1 and len(board) >= 5:
        score = min(score, 0.35)               # "my hand" is just the board

    if len(board) < 5:
        fd, oesd, gut = detect_draws(hole, board)
        bonus = (0.16 if fd else 0) + (0.13 if oesd else 0) + (0.05 if gut else 0)
        score = min(0.93, score + bonus)
    return score


def mc_equity(hole, board, n_opps, rng, iters=50):
    """Monte Carlo equity of hole+board versus n_opps uniformly random hands."""
    seen = set(hole) | set(board)
    stub = [c for c in fresh_deck() if c not in seen]
    need_board = 5 - len(board)
    score = 0.0
    for _ in range(iters):
        rng.shuffle(stub)
        idx = 0
        opp_holes = []
        for _ in range(n_opps):
            opp_holes.append(stub[idx:idx + 2])
            idx += 2
        full_board = board + stub[idx:idx + need_board]
        mine = evaluate(hole + full_board)
        best_opp = max(evaluate(oh + full_board) for oh in opp_holes)
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / iters


def pot_odds_needed(to_call, pot):
    return to_call / (pot + to_call) if to_call > 0 else 0.0


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class Strategy:
    name = 'base'

    def __init__(self, rng):
        self.rng = rng

    def new_hand(self, hand_no, alive_ids):
        pass

    def observe(self, event):
        """Public action broadcast: same info every player at the table sees."""
        pass

    def act(self, view):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, as specified:
#
#     if my_turn
#     then bet = All in
#     fi
# ---------------------------------------------------------------------------

class AllInAndy(Strategy):
    name = 'All-In Andy'

    def act(self, view):
        return ('raise', view['my_committed_street'] + view['my_stack'])


# ---------------------------------------------------------------------------
# Player 2 — "The Accountant": tight-aggressive, Chen formula preflop,
# disciplined pot-odds accounting postflop. Never pays without a receipt.
# ---------------------------------------------------------------------------

class TheAccountant(Strategy):
    name = 'The Accountant'

    def act(self, view):
        hole, board = view['hole'], view['board']
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']

        if not board:
            return self._preflop(view)

        strength = postflop_strength(hole, board)
        need = pot_odds_needed(to_call, pot)

        if strength >= 0.80:
            return ('raise', mine + max(to_call + view['min_raise'],
                                        min(stack, int(pot * 0.75))))
        if strength >= 0.58:
            if to_call == 0:
                return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.6))))
            if need <= strength - 0.10 or to_call <= bb * 2:
                return ('call',)
            return ('fold',)
        if strength >= 0.40:
            if to_call == 0:
                return ('call',)
            if need <= 0.25 and to_call <= stack * 0.15:
                return ('call',)
            return ('fold',)
        # draws are folded unless the price is basically free
        if to_call == 0:
            return ('call',)
        fd, oesd, _ = detect_draws(hole, board) if len(board) < 5 else (False, False, False)
        if (fd or oesd) and need <= 0.20:
            return ('call',)
        return ('fold',)

    def _preflop(self, view):
        score = chen_score(view['hole'])
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']
        behind = view['players_behind']
        facing_big_raise = to_call > bb * 3

        if stack <= bb * 10:                       # short stack: push/fold
            if score >= 8.5:
                return ('raise', mine + stack)
            return ('fold',) if to_call > 0 else ('call',)

        if facing_big_raise:
            need = pot_odds_needed(to_call, pot)
            if score >= 12:                        # QQ+/AK territory: play for stacks
                return ('raise', mine + stack)
            if score >= 10:
                eq = mc_equity(view['hole'], [], 1, self.rng, iters=40)
                if eq >= need + 0.04:
                    return ('call',)
            return ('fold',)

        open_threshold = 9 - min(2, behind // 2)    # looser in late position
        if score >= open_threshold:
            return ('raise', mine + min(stack, to_call + bb * 3))
        if score >= 6 and to_call <= bb:
            return ('call',)
        return ('fold',) if to_call > 0 else ('call',)


# ---------------------------------------------------------------------------
# Player 3 — "The Cowboy": loose-aggressive. Wide open ranges, relentless
# continuation bets, semi-bluffs every draw, punishes weakness.
# ---------------------------------------------------------------------------

class TheCowboy(Strategy):
    name = 'The Cowboy'

    def new_hand(self, hand_no, alive_ids):
        self.was_aggressor = False

    def observe(self, event):
        pass

    def act(self, view):
        hole, board = view['hole'], view['board']
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']

        if not board:
            return self._preflop(view)

        strength = postflop_strength(hole, board)
        fd, oesd, gut = detect_draws(hole, board) if len(board) < 5 else (False, False, False)
        need = pot_odds_needed(to_call, pot)

        if strength >= 0.70:
            self.was_aggressor = True
            return ('raise', mine + max(to_call + view['min_raise'],
                                        min(stack, int(pot * 0.8))))
        if fd or oesd:                                # semi-bluff the draws
            if to_call == 0 or self.rng.random() < 0.55:
                self.was_aggressor = True
                return ('raise', mine + min(stack, to_call + max(view['min_raise'],
                                                                 int(pot * 0.66))))
            return ('call',) if need <= 0.32 else ('fold',)
        if self.was_aggressor and to_call == 0 and self.rng.random() < 0.65:
            return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.6))))  # c-bet
        if strength >= 0.50:
            if to_call == 0:
                return ('call',)
            return ('call',) if need <= strength - 0.08 else ('fold',)
        if to_call == 0:
            return ('call',)
        return ('fold',)

    def _preflop(self, view):
        score = chen_score(view['hole'])
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']
        facing_big_raise = to_call > bb * 3

        if facing_big_raise:
            need = pot_odds_needed(to_call, pot)
            if score >= 11:
                return ('raise', mine + stack)
            if score >= 9 and need <= 0.45:
                return ('call',)
            if score >= 7 and to_call <= stack * 0.08:
                return ('call',)
            return ('fold',)

        if score >= 8 or (score >= 5 and self.rng.random() < 0.5) \
                or self.rng.random() < 0.15:
            self.was_aggressor = True
            return ('raise', mine + min(stack, to_call + int(bb * (2 + self.rng.random() * 1.5))))
        if score >= 4 and to_call <= bb * 2:
            return ('call',)
        return ('fold',) if to_call > 0 else ('call',)


# ---------------------------------------------------------------------------
# Player 4 — "The Professor": pure Monte Carlo equity vs. pot odds. Estimates
# win probability against random hands every decision and bets the math.
# Incapable of bluffing; considers it undignified.
# ---------------------------------------------------------------------------

class TheProfessor(Strategy):
    name = 'The Professor'

    def act(self, view):
        hole, board = view['hole'], view['board']
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']
        n_opps = max(1, min(3, view['num_in_hand'] - 1))
        iters = 40 if not board else 60

        eq = mc_equity(hole, board, n_opps, self.rng, iters=iters)
        need = pot_odds_needed(to_call, pot)
        # committing a big fraction of the stack demands a bigger edge
        risk_margin = 0.03 + 0.07 * min(1.0, to_call / max(1, stack))

        if eq >= 0.82:
            return ('raise', mine + stack)
        if eq >= 0.62:
            return ('raise', mine + max(to_call + view['min_raise'],
                                        min(stack, int(pot * 0.75))))
        if to_call == 0:
            if eq >= 0.5 + 0.05 * n_opps:
                return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.5))))
            return ('call',)
        if eq >= need + risk_margin:
            return ('call',)
        return ('fold',)


# ---------------------------------------------------------------------------
# Player 5 — "The Trickster": randomized mixed strategy. Slowplays monsters,
# bluffs scary boards, check-raises for fun. Deliberately unreadable.
# ---------------------------------------------------------------------------

class TheTrickster(Strategy):
    name = 'The Trickster'

    def act(self, view):
        hole, board = view['hole'], view['board']
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']
        roll = self.rng.random()

        if not board:
            score = chen_score(hole)
            if to_call > bb * 3:
                if score >= 11 or (score >= 9 and roll < 0.5):
                    return ('raise', mine + stack)
                need = pot_odds_needed(to_call, pot)
                if score >= 8 and need <= 0.42:
                    return ('call',)
                return ('fold',)
            if score >= 9:
                if roll < 0.35:
                    return ('call',)               # limp a monster, why not
                return ('raise', mine + min(stack, to_call + bb * 3))
            if score >= 5.5 or roll < 0.12:
                if roll < 0.25:
                    return ('raise', mine + min(stack, to_call + bb * 2))
                return ('call',) if to_call <= bb * 2 else ('fold',)
            return ('fold',) if to_call > 0 else ('call',)

        strength = postflop_strength(hole, board)
        suited_board = max(sum(1 for _, bs in board if bs == s) for s in range(4)) >= 3
        scary = max(r for r, _ in board) == 14 or suited_board
        need = pot_odds_needed(to_call, pot)

        if strength >= 0.80:
            if roll < 0.40 and to_call <= pot:
                return ('call',)                   # slowplay
            return ('raise', mine + max(to_call + view['min_raise'],
                                        min(stack, pot)))
        if strength >= 0.55:
            if to_call == 0 and roll < 0.5:
                return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.55))))
            return ('call',) if need <= strength - 0.05 else ('fold',)
        bluff_freq = 0.28 if scary else 0.15
        if to_call == 0:
            if roll < bluff_freq:
                return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.66))))
            return ('call',)
        if roll < bluff_freq * 0.4 and to_call < stack * 0.2:
            return ('raise', mine + min(stack, to_call + max(view['min_raise'], pot)))
        if strength >= 0.40 and need <= 0.22:
            return ('call',)
        return ('fold',)


# ---------------------------------------------------------------------------
# Player 6 — "The Shark": adaptive opponent modeler. Tracks every player's
# observed VPIP, raise frequency and jam frequency from public actions only,
# then adjusts: exploits hyper-aggressive shovers by calling wide with equity
# edges, gives tight raisers respect, and steals from the fearful.
# ---------------------------------------------------------------------------

class TheShark(Strategy):
    name = 'The Shark'

    def __init__(self, rng):
        super().__init__(rng)
        self.stats = {}          # opp_id -> counters
        self.hands_seen = 0
        self._entered_this_hand = set()

    def _s(self, pid):
        return self.stats.setdefault(pid, {'vpip': 0, 'raises': 0, 'jams': 0})

    def new_hand(self, hand_no, alive_ids):
        self.hands_seen += 1
        self._entered_this_hand = set()

    def observe(self, event):
        pid = event['player']
        if event['action'] in ('call', 'raise') and event.get('voluntary'):
            if pid not in self._entered_this_hand:
                self._entered_this_hand.add(pid)
                self._s(pid)['vpip'] += 1
        if event['action'] == 'raise':
            self._s(pid)['raises'] += 1
            if event.get('all_in'):
                self._s(pid)['jams'] += 1

    def _jam_rate(self, pid):
        if self.hands_seen < 4:
            return 0.0
        return self._s(pid)['jams'] / self.hands_seen

    def _raise_rate(self, pid):
        if self.hands_seen < 4:
            return 0.15
        return self._s(pid)['raises'] / self.hands_seen

    def _aggressor(self, view):
        for ev in reversed(view['history']):
            if ev['action'] == 'raise' and ev['player'] != view['my_id']:
                return ev['player']
        return None

    def act(self, view):
        hole, board = view['hole'], view['board']
        to_call, pot = view['to_call'], view['pot']
        stack, bb = view['my_stack'], view['big_blind']
        mine = view['my_committed_street']
        aggressor = self._aggressor(view)

        # --- Facing a large bet: profile the bettor -----------------------
        if to_call > bb * 4 and aggressor is not None:
            need = pot_odds_needed(to_call, pot)
            jam_rate = self._jam_rate(aggressor)
            raise_rate = self._raise_rate(aggressor)
            if jam_rate > 0.4:
                # This person shoves everything: their range is random cards.
                eq = mc_equity(hole, board, 1, self.rng, iters=70)
                if eq >= need + 0.03:
                    return ('call',)
                return ('fold',)
            if raise_rate > 0.35:                  # generic aggro: modest respect
                eq = mc_equity(hole, board, 1, self.rng, iters=60)
                if eq >= need + 0.10:
                    return ('call',)
                return ('fold',)
            # A tight player woke up: only continue with the top of our range.
            if not board:
                return ('raise', mine + stack) if chen_score(hole) >= 12 else ('fold',)
            strength = postflop_strength(hole, board)
            return ('call',) if strength >= 0.83 else ('fold',)

        # --- Normal pots --------------------------------------------------
        if not board:
            score = chen_score(hole)
            if stack <= bb * 10:
                if score >= 8:
                    return ('raise', mine + stack)
                return ('fold',) if to_call > 0 else ('call',)
            steal_spot = (view['players_behind'] <= 2 and to_call <= bb
                          and aggressor is None)
            if score >= 8.5 or (steal_spot and score >= 6):
                return ('raise', mine + min(stack, to_call + bb * 3))
            if score >= 6 and to_call <= bb * 2:
                return ('call',)
            return ('fold',) if to_call > 0 else ('call',)

        strength = postflop_strength(hole, board)
        need = pot_odds_needed(to_call, pot)
        if strength >= 0.78:
            return ('raise', mine + max(to_call + view['min_raise'],
                                        min(stack, int(pot * 0.8))))
        if strength >= 0.55:
            if to_call == 0:
                return ('raise', mine + min(stack, max(bb * 2, int(pot * 0.6))))
            return ('call',) if need <= strength - 0.08 else ('fold',)
        if len(board) < 5:
            fd, oesd, _ = detect_draws(hole, board)
            if (fd or oesd) and (to_call == 0 or need <= 0.28):
                return ('call',)
        if to_call == 0:
            return ('call',)
        return ('fold',)


ROSTER = [
    (1, AllInAndy),
    (2, TheAccountant),
    (3, TheCowboy),
    (4, TheProfessor),
    (5, TheTrickster),
    (6, TheShark),
]
