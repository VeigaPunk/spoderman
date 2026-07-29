"""Six poker minds. Five elaborate, one gloriously simple.

Every strategy sees only its own hole cards and public information
(board, pot, stacks, observable action history/stats) — never another
player's cards or code.
"""

from engine import eval5, eval7

# --------------------------------------------------------------------- utils

def chen_score(hole):
    """Chen formula preflop hand strength (~ -1 .. 20)."""
    r1, r2 = sorted((hole[0] % 13, hole[1] % 13), reverse=True)
    suited = hole[0] // 13 == hole[1] // 13
    pts = {12: 10, 11: 8, 10: 7, 9: 6}.get(r1, (r1 + 2) / 2)
    if r1 == r2:
        return max(5, pts * 2)
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:
        pts += 1  # straight-making connectors below queen
    if suited:
        pts += 2
    return pts


def monte_carlo_equity(hole, board, n_opps, rng, iters=60):
    """P(win or tie) vs n_opps random hands, by rollout simulation."""
    known = set(hole) | set(board)
    rest = [c for c in range(52) if c not in known]
    wins = 0.0
    board = list(board)
    need = 5 - len(board)
    for _ in range(iters):
        rng.shuffle(rest)
        idx = 0
        full_board = board + rest[idx:idx + need]
        idx += need
        my_score = eval7(list(hole) + full_board)
        best_opp = None
        for _ in range(n_opps):
            opp = rest[idx:idx + 2]
            idx += 2
            s = eval7(opp + full_board)
            if best_opp is None or s > best_opp:
                best_opp = s
        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            wins += 0.5
    return wins / iters


def made_hand_strength(hole, board):
    """Crude 0..1 strength of the current made hand on this board."""
    if not board:
        return 0.0
    score = eval7(list(hole) + list(board))
    cat = score[0]
    board_score = eval5(list(board)) if len(board) == 5 else None
    # top pair or better with our hole cards actually improving the board
    base = {0: 0.05, 1: 0.30, 2: 0.55, 3: 0.70, 4: 0.80,
            5: 0.85, 6: 0.92, 7: 0.97, 8: 1.0}[cat]
    if cat == 1:
        pair_rank = score[1]
        board_ranks = [c % 13 for c in board]
        if pair_rank in (hole[0] % 13, hole[1] % 13):
            if board_ranks and pair_rank >= max(board_ranks):
                base = 0.50  # top pair
        elif pair_rank in board_ranks and pair_rank not in (
                hole[0] % 13, hole[1] % 13):
            base = 0.15  # board pair, we have nothing
    if board_score is not None and eval7(list(board)) == score:
        base = min(base, 0.20)  # we're just playing the board
    return base


def draws(hole, board):
    """(flush_draw, open_ended_straight_draw) flags."""
    if not board or len(board) >= 5:
        return False, False
    cards = list(hole) + list(board)
    suits = [c // 13 for c in cards]
    fd = any(suits.count(s) == 4 for s in set(suits)) and \
        any(suits.count(hole[i] // 13) == 4 for i in (0, 1))
    ranks = sorted({c % 13 for c in cards})
    oesd = False
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] == 3:
            window = set(range(ranks[i], ranks[i] + 4))
            if (hole[0] % 13 in window or hole[1] % 13 in window) \
                    and ranks[i] > 0 and ranks[i + 3] < 12:
                oesd = True
    return fd, oesd


# ----------------------------------------------------------------- Player 1

class AllInAndy:
    """The entire strategy, verbatim from the spec:

        if my_turn
        then bet = All in
        fi
    """

    def __init__(self, rng):
        pass

    def act(self, view):
        return ("raise", view.my_bet + view.my_stack)


# ----------------------------------------------------------------- Player 2

class TightAggressiveTanya:
    """Classic TAG: positional preflop ranges via the Chen formula,
    continuation-bets flops she raised preflop, value-bets strong made
    hands, chases draws only at correct pot odds, folds to heavy
    aggression without the goods."""

    def __init__(self, rng):
        self.rng = rng
        self.raised_pre = False

    def act(self, view):
        v = view
        if v.street == "preflop":
            self.raised_pre = False
            score = chen_score(v.hole)
            late = v.position >= v.n_players - 2
            open_thr = 8 if not late else 6.5
            call_thr = 6 if not late else 5
            huge_bet = v.to_call > 8 * v.big_blind
            if huge_bet:  # someone shoved or 3-bet big: premiums only
                return ("call", 0) if score >= 10 else ("fold", 0)
            if score >= open_thr and v.to_call <= 3 * v.big_blind:
                self.raised_pre = True
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= call_thr and v.pot_odds < 0.25:
                return ("call", 0)
            return ("fold", 0) if v.to_call > 0 else ("call", 0)

        strength = made_hand_strength(v.hole, v.board)
        fd, oesd = draws(v.hole, v.board)
        pot = v.pot
        if strength >= 0.65:  # two pair or better: pile it in
            return ("raise", v.my_bet + min(v.my_stack, max(v.min_raise_to, pot)))
        if strength >= 0.45:  # top pair-ish
            if v.to_call == 0:
                return ("raise", v.my_bet + max(v.min_raise_to - v.my_bet,
                                                (2 * pot) // 3))
            return ("call", 0) if v.pot_odds < 0.35 else ("fold", 0)
        if fd or oesd:
            outs = 9 if fd else 8
            equity = outs * (4 if v.street == "flop" else 2) / 100
            return ("call", 0) if v.pot_odds < equity else ("fold", 0)
        if self.raised_pre and v.street == "flop" and v.to_call == 0 \
                and v.n_active <= 3:
            return ("raise", v.my_bet + max(v.min_raise_to - v.my_bet, pot // 2))
        return ("fold", 0) if v.to_call > 0 else ("call", 0)


# ----------------------------------------------------------------- Player 3

class LooseAggressiveLars:
    """LAG: wide opening range, frequent 3-bets, relentless barreling,
    semi-bluffs every draw, and just enough hand-reading to release
    trash when the pot gets serious."""

    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        v = view
        r = self.rng.random()
        if v.street == "preflop":
            score = chen_score(v.hole)
            if v.to_call > 10 * v.big_blind:  # facing a shove
                return ("call", 0) if score >= 9 else ("fold", 0)
            if score >= 9 and r < 0.6:
                return ("raise", max(v.min_raise_to, 4 * v.big_blind))
            if score >= 5:
                if r < 0.35:
                    return ("raise", max(v.min_raise_to, 3 * v.big_blind))
                return ("call", 0) if v.pot_odds < 0.30 else ("fold", 0)
            if score >= 3 and v.pot_odds < 0.15:
                return ("call", 0)
            return ("fold", 0) if v.to_call > 0 else ("call", 0)

        strength = made_hand_strength(v.hole, v.board)
        fd, oesd = draws(v.hole, v.board)
        pot = v.pot
        if strength >= 0.55:
            return ("raise", v.my_bet + min(v.my_stack, max(v.min_raise_to, pot)))
        if fd or oesd:  # semi-bluff raise
            if v.to_call <= pot // 2 or r < 0.5:
                return ("raise", v.my_bet + min(v.my_stack,
                                                max(v.min_raise_to, (3 * pot) // 4)))
            return ("call", 0)
        if strength >= 0.30:
            return ("call", 0) if v.pot_odds < 0.30 else ("fold", 0)
        if v.to_call == 0 and r < 0.40:  # naked stab
            return ("raise", v.my_bet + max(v.min_raise_to - v.my_bet, pot // 2))
        return ("fold", 0) if v.to_call > 0 else ("call", 0)


# ----------------------------------------------------------------- Player 4

class MonteCarloMatt:
    """Pure math: estimates equity by simulating random rollouts against
    the live number of opponents, then compares equity to the price the
    pot is laying. Raises when equity dominates, calls at a discount,
    folds bad prices. No reads, no fear, just variance-reduced EV."""

    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        v = view
        n_opps = max(1, v.n_active - 1)
        if v.street == "preflop":
            score = chen_score(v.hole)
            equity = min(0.85, 0.28 + score * 0.030) * (0.9 ** (n_opps - 1))
        else:
            iters = 70 if v.street == "flop" else 90
            equity = monte_carlo_equity(v.hole, v.board, n_opps, self.rng, iters)

        price = v.pot_odds
        if v.to_call == 0:
            if equity > 0.55 + 0.05 * n_opps:
                bet = v.my_bet + max(v.min_raise_to - v.my_bet, (2 * v.pot) // 3)
                return ("raise", bet)
            return ("call", 0)
        if equity > price + 0.22 and equity > 0.5:
            return ("raise", v.my_bet + min(v.my_stack,
                                            max(v.min_raise_to, v.pot)))
        if equity > price + 0.03:
            return ("call", 0)
        return ("fold", 0)


# ----------------------------------------------------------------- Player 5

class NitNadia:
    """The survivalist nit: folds almost everything, waits in ambush with
    premiums, and only then commits chips — the textbook counter-style
    to table maniacs. Patience is a weapon."""

    PREMIUM = 11    # ~AA/KK/QQ/AK-suited territory on the Chen scale
    STRONG = 9

    def __init__(self, rng):
        self.rng = rng

    def act(self, view):
        v = view
        if v.street == "preflop":
            score = chen_score(v.hole)
            shove_out_there = v.to_call >= v.my_stack // 2
            if score >= self.PREMIUM:
                return ("raise", v.my_bet + v.my_stack)  # premium: ambush shove
            if score >= self.STRONG and not shove_out_there:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if score >= self.STRONG and v.pot_odds < 0.4:
                return ("call", 0)
            if v.to_call == 0:
                return ("call", 0)
            if v.pot_odds < 0.09 and score >= 5:
                return ("call", 0)
            return ("fold", 0)

        strength = made_hand_strength(v.hole, v.board)
        if strength >= 0.60:
            return ("raise", v.my_bet + min(v.my_stack,
                                            max(v.min_raise_to, v.pot)))
        if strength >= 0.45 and v.pot_odds < 0.30:
            return ("call", 0)
        return ("fold", 0) if v.to_call > 0 else ("call", 0)


# ----------------------------------------------------------------- Player 6

class AdaptiveAda:
    """The exploiter: builds a live profile of every opponent from public
    behaviour (all-in frequency, raise frequency), then adjusts — calls
    wider against maniacs who shove any two cards, steals more against
    players who fold too much. Knows nobody's code; reads everybody's
    soul."""

    def __init__(self, rng):
        self.rng = rng
        self.name = None  # set by the simulator so Ada can skip herself

    def table_maniac_level(self, v):
        """Max observed all-in rate among opponents still in the hand."""
        worst = 0.0
        for name, s in v.public_stats.items():
            if name == self.name or s["hands"] < 3:
                continue
            rate = s["allins"] / max(1, s["hands"])
            worst = max(worst, rate)
        return worst

    def table_fold_level(self, v):
        rates = [s["folds"] / max(1, s["hands"])
                 for name, s in v.public_stats.items()
                 if name != self.name and s["hands"] >= 3]
        return sum(rates) / len(rates) if rates else 0.4

    def act(self, view):
        v = view
        maniac = self.table_maniac_level(v)      # ~1.0 at an all-in-every-hand table
        foldy = self.table_fold_level(v)
        if v.street == "preflop":
            score = chen_score(v.hole)
            facing_shove = v.to_call > 8 * v.big_blind
            if facing_shove:
                # vs a maniac, any decent hand is way ahead of a random shove
                need = 10 - 4.5 * maniac
                return ("call", 0) if score >= need else ("fold", 0)
            if score >= 9:
                return ("raise", max(v.min_raise_to, 3 * v.big_blind))
            if foldy > 0.55 and v.to_call <= v.big_blind \
                    and self.rng.random() < 0.35:
                return ("raise", max(v.min_raise_to, 2 * v.big_blind + v.big_blind // 2))
            if score >= 6 and v.pot_odds < 0.25:
                return ("call", 0)
            return ("fold", 0) if v.to_call > 0 else ("call", 0)

        n_opps = max(1, v.n_active - 1)
        equity = monte_carlo_equity(v.hole, v.board, n_opps, self.rng, 60)
        price = v.pot_odds
        edge = 0.03 - 0.02 * maniac  # thinner calls allowed vs maniacs
        if v.to_call == 0:
            if equity > 0.60:
                return ("raise", v.my_bet + max(v.min_raise_to - v.my_bet,
                                                (2 * v.pot) // 3))
            if foldy > 0.55 and self.rng.random() < 0.30:
                return ("raise", v.my_bet + max(v.min_raise_to - v.my_bet,
                                                v.pot // 2))
            return ("call", 0)
        if equity > price + 0.20:
            return ("raise", v.my_bet + min(v.my_stack,
                                            max(v.min_raise_to, v.pot)))
        if equity > price + edge:
            return ("call", 0)
        return ("fold", 0)


ROSTER = [
    ("P1 AllInAndy",  AllInAndy),
    ("P2 TAG-Tanya",  TightAggressiveTanya),
    ("P3 LAG-Lars",   LooseAggressiveLars),
    ("P4 MC-Matt",    MonteCarloMatt),
    ("P5 Nit-Nadia",  NitNadia),
    ("P6 Ada-Adapt",  AdaptiveAda),
]
