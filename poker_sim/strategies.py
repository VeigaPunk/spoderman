"""
Six poker brains. Player 1 gets the haiku; players 2-6 get the novels.

Every strategy only sees a TableView (public state + own hole cards) and
public action events via observe(). None of them knows what the others run.
"""

import math
from collections import Counter

from .engine import FULL_DECK, best7

# --------------------------------------------------------------------------
# Shared hand-reading helpers (each strategy uses these differently)
# --------------------------------------------------------------------------

def chen_score(hole):
    """Bill Chen's preflop formula, slightly smoothed. AA=20, 72o=-1.5-ish."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2.0)
    if s1 == s2:
        pts += 2.0
    gap = hi - lo - 1
    pts -= {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0}.get(gap, 5.0)
    if gap <= 1 and hi < 12:
        pts += 1.0
    return pts


def made_tier(hole, board):
    """Postflop made-hand tier, 0 (air) .. 7 (quads+), hole-card aware.

    0 air | 1 weak pair / ace high | 2 middle or weak-top pair |
    3 top pair / overpair | 4 two pair or trips using hole cards |
    5 straight | 6 flush | 7 boat or better
    """
    all7 = tuple(hole) + tuple(board)
    cat = best7(all7)[0]
    h_ranks = [c[0] for c in hole]
    b_ranks = sorted((c[0] for c in board), reverse=True)
    pocket = h_ranks[0] == h_ranks[1]
    top_b = b_ranks[0]

    if cat >= 6:
        return 7
    if cat == 5:
        suit_count = Counter(s for _, s in all7)
        fsuit = max(suit_count, key=suit_count.get)
        return 6 if any(s == fsuit for _, s in hole) else 1
    if cat == 4:
        return 5
    if cat == 3:
        trip_rank = best7(all7)[1]
        return 4 if trip_rank in h_ranks else 1
    if cat == 2:
        pr1, pr2 = best7(all7)[1], best7(all7)[2]
        return 4 if (pr1 in h_ranks or pr2 in h_ranks) else 1
    if cat == 1:
        pr = best7(all7)[1]
        if pocket:
            if h_ranks[0] > top_b:
                return 3  # overpair
            return 2 if len(b_ranks) > 1 and h_ranks[0] >= b_ranks[1] else 1
        if pr in h_ranks:
            return 3 if pr == top_b else 2
        return 0  # pairing lives entirely on the board
    return 1 if 14 in h_ranks else 0


def draw_info(hole, board):
    """(flush_draw, straight_outs) — only meaningful with 3-4 board cards."""
    cards = tuple(hole) + tuple(board)
    suit_count = Counter(s for _, s in cards)
    flush_draw = any(
        n == 4 and any(hs == s for _, hs in hole)
        for s, n in suit_count.items()
    )
    ranks = {r for r, _ in cards}
    if 14 in ranks:
        ranks = ranks | {1}
    outs = set()
    for x in range(2, 15):
        if x in ranks:
            continue
        rx = ranks | {x}
        for low in range(1, 11):
            if all(v in rx for v in range(low, low + 5)):
                outs.add(x)
                break
    return flush_draw, len(outs)


def mc_equity(hole, board, n_opp, trials, rng):
    """Monte Carlo equity vs n_opp random hands. The honest, slow way."""
    n_opp = max(1, min(n_opp, 3))  # cap for speed; extra foes ~ scaled below
    used = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in used]
    need_board = 5 - len(board)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need_board + 2 * n_opp)
        full_board = tuple(board) + tuple(draw[:need_board])
        mine = best7(hole + full_board)
        best_opp = max(
            best7((draw[need_board + 2 * i], draw[need_board + 2 * i + 1])
                  + full_board)
            for i in range(n_opp)
        )
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / trials


# --------------------------------------------------------------------------
# Base class
# --------------------------------------------------------------------------

class Strategy:
    name = "?"

    def __init__(self, rng):
        self.rng = rng

    def observe(self, event):
        pass

    def act(self, view):
        raise NotImplementedError

    # sizing helpers -------------------------------------------------------
    @staticmethod
    def shove(view):
        return ("raise", view.my_street_commit + view.my_stack)

    @staticmethod
    def raise_to(view, total):
        return ("raise", max(int(total), view.min_raise_to))

    @staticmethod
    def bet_pot_frac(view, frac):
        total = view.my_street_commit + view.to_call + int(view.pot * frac)
        return ("raise", max(total, view.min_raise_to))

    @staticmethod
    def pot_odds(view):
        if view.to_call <= 0:
            return 0.0
        return view.to_call / (view.pot + view.to_call)


# --------------------------------------------------------------------------
# Player 1 — the entire strategy, verbatim from the spec:
#     if my_turn
#     then bet = All in
#     fi
# --------------------------------------------------------------------------

class AllInAnnie(Strategy):
    name = "AllInAnnie"

    def act(self, view):
        my_turn = True
        if my_turn:
            return self.shove(view)
        # fi


# --------------------------------------------------------------------------
# Player 2 — "The Rock": ultra-tight nit. Folds for a living, stacks you
# the one time per hour it has a hand.
# --------------------------------------------------------------------------

class TheRock(Strategy):
    name = "TheRock"

    PREMIUM = 12.0    # ~ QQ+, AKs
    STRONG = 9.0      # ~ 99+, AQ+, AJs, KQs
    PLAYABLE = 7.5

    def act(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        c = chen_score(view.hole)
        bb = view.big_blind
        facing_shove = view.to_call >= view.my_stack * 0.6
        facing_raise = view.current_bet > bb

        if facing_shove:
            # Calls off its stack only with the top of the deck.
            if c >= self.PREMIUM:
                return ("call", 0)
            # Desperation: short stack, still-decent hand.
            if view.my_stack <= 6 * bb and c >= self.STRONG:
                return ("call", 0)
            return ("fold", 0)

        if facing_raise:
            if c >= self.PREMIUM:
                return self.raise_to(view, view.current_bet * 3)
            if c >= self.STRONG and view.to_call <= 4 * bb:
                return ("call", 0)
            return ("fold", 0)

        if c >= self.STRONG:
            return self.raise_to(view, 3 * bb)
        if c >= self.PLAYABLE and view.pos_frac > 0.5:
            return ("call", 0) if view.to_call <= bb else ("fold", 0)
        return ("fold", 0)

    def _postflop(self, view):
        t = made_tier(view.hole, view.board)
        if t >= 5:
            # Monster: trap small, shove big pots.
            if view.to_call > 0:
                return self.shove(view) if view.pot > view.my_stack else ("call", 0)
            if self.rng.random() < 0.4 and view.street == "flop":
                return ("call", 0)  # slow-play check
            return self.bet_pot_frac(view, 0.75)
        if t == 4:
            if view.to_call > view.pot:
                return ("call", 0) if self.rng.random() < 0.5 else ("fold", 0)
            return self.bet_pot_frac(view, 0.6) if view.to_call == 0 else ("call", 0)
        if t == 3:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.5)
            if view.to_call <= view.pot * 0.5:
                return ("call", 0)
            return ("fold", 0)
        # Anything weaker: check-fold. Rocks don't bluff.
        if view.to_call == 0:
            return ("call", 0)
        if view.to_call <= view.pot * 0.15 and t >= 1:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------------
# Player 3 — "TAG Titan": textbook tight-aggressive. Position-scaled Chen
# opens, 3-bets, continuation bets, semi-bluffs its draws, respects odds.
# --------------------------------------------------------------------------

class TagTitan(Strategy):
    name = "TagTitan"

    def __init__(self, rng):
        super().__init__(rng)
        self.was_aggressor = False

    def observe(self, event):
        if event.get("type") == "hand_start":
            self.was_aggressor = False

    def act(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        c = chen_score(view.hole)
        bb = view.big_blind
        open_threshold = 9.0 - 3.0 * view.pos_frac  # 9 early -> 6 on button
        facing_shove = view.to_call >= min(view.my_stack, 15 * bb)
        stack_bb = view.my_stack / bb

        if facing_shove:
            need = 10.5 if stack_bb > 25 else (9.0 if stack_bb > 12 else 7.5)
            return ("call", 0) if c >= need else ("fold", 0)

        if view.current_bet > bb:  # facing a raise
            if c >= 11.0:
                self.was_aggressor = True
                return self.raise_to(view, view.current_bet * 3)
            price_ok = view.to_call <= max(4 * bb, view.my_stack * 0.08)
            if c >= 8.5 and price_ok:
                return ("call", 0)
            return ("fold", 0)

        if c >= open_threshold:
            self.was_aggressor = True
            limpers = sum(1 for (st, _, a, _) in view.history
                          if st == "preflop" and a == "call")
            return self.raise_to(view, (3 + limpers) * bb)
        if c >= open_threshold - 1.5 and view.to_call == 0:
            return ("call", 0)  # check the big blind option
        return ("fold", 0)

    def _postflop(self, view):
        t = made_tier(view.hole, view.board)
        fd, souts = draw_info(view.hole, view.board)
        strong_draw = fd or souts >= 2
        odds = self.pot_odds(view)
        # rough draw equity: ~9 flush outs or ~8 straight outs, 2 cards to come
        draw_eq = 0.0
        if view.street in ("flop", "turn"):
            outs = (9 if fd else 0) + min(souts * 2, 8) * 0.5
            streets_left = 2 if view.street == "flop" else 1
            draw_eq = min(0.45, outs * 0.022 * streets_left)

        if t >= 4:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.66)
            if view.to_call >= view.my_stack * 0.5:
                return self.shove(view) if t >= 5 else ("call", 0)
            return self.raise_to(view, view.current_bet * 2.5)
        if t == 3:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.6)
            if odds <= 0.35:
                return ("call", 0)
            return ("fold", 0)
        if strong_draw and view.street != "river":
            if view.to_call == 0 and self.rng.random() < 0.6:
                return self.bet_pot_frac(view, 0.5)  # semi-bluff
            if odds <= draw_eq + 0.05:
                return ("call", 0)
            return ("fold", 0)
        if t == 2:
            if view.to_call == 0:
                return ("call", 0)
            return ("call", 0) if odds <= 0.22 else ("fold", 0)
        # air: c-bet once as the preflop aggressor, otherwise give up
        if (view.to_call == 0 and self.was_aggressor and view.street == "flop"
                and view.num_live <= 3 and self.rng.random() < 0.65):
            return self.bet_pot_frac(view, 0.5)
        if view.to_call == 0:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------------
# Player 4 — "LAG Loki": loose-aggressive chaos merchant. Wide opens,
# 3-bet bluffs, double barrels, hero-folds only when the story is grim.
# --------------------------------------------------------------------------

class LagLoki(Strategy):
    name = "LagLoki"

    def __init__(self, rng):
        super().__init__(rng)
        self.barreling = False

    def observe(self, event):
        if event.get("type") == "hand_start":
            self.barreling = False

    def act(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        c = chen_score(view.hole)
        bb = view.big_blind
        facing_shove = view.to_call >= min(view.my_stack, 15 * bb)
        has_ace = 14 in (view.hole[0][0], view.hole[1][0])

        if facing_shove:
            need = 9.5 if view.my_stack > 20 * bb else 8.0
            return ("call", 0) if c >= need else ("fold", 0)

        if view.current_bet > bb:
            if c >= 10.0 or (has_ace and self.rng.random() < 0.18):
                # value 3-bet, or an ace-blocker bluff 3-bet
                return self.raise_to(view, int(view.current_bet * 2.8))
            if c >= 6.0 and view.to_call <= 5 * bb:
                return ("call", 0)
            return ("fold", 0)

        open_threshold = 6.5 - 2.5 * view.pos_frac  # steals wide in position
        if c >= open_threshold or self.rng.random() < 0.10:
            self.barreling = True
            return self.raise_to(view, int(2.5 * bb))
        if view.to_call <= bb and c >= 4.5:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        t = made_tier(view.hole, view.board)
        fd, souts = draw_info(view.hole, view.board)
        odds = self.pot_odds(view)
        big_bet_faced = view.to_call > view.pot * 0.6

        if t >= 4:
            if view.to_call > 0:
                return self.shove(view) if self.rng.random() < 0.5 \
                    else self.raise_to(view, view.current_bet * 3)
            return self.bet_pot_frac(view, 0.75)
        if fd or souts >= 2:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.66)  # relentless semi-bluffs
            if view.street != "river" and odds <= 0.38:
                return ("call", 0)
            return ("fold", 0)
        if t == 3:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.6)
            if big_bet_faced and view.raises_this_street >= 1:
                return ("call", 0) if self.rng.random() < 0.4 else ("fold", 0)
            return ("call", 0)
        if t == 2:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.4) if self.rng.random() < 0.5 \
                    else ("call", 0)
            return ("call", 0) if odds <= 0.3 else ("fold", 0)
        # pure air: barrel the story it started, sometimes out of nowhere
        if view.to_call == 0:
            p = 0.55 if self.barreling else 0.25
            if view.street != "river" and self.rng.random() < p:
                self.barreling = True
                return self.bet_pot_frac(view, 0.6)
            return ("call", 0)
        if big_bet_faced:
            return ("fold", 0)
        return ("call", 0) if odds <= 0.18 and self.rng.random() < 0.3 \
            else ("fold", 0)


# --------------------------------------------------------------------------
# Player 5 — "Casey Calculator": no soul, only math. Monte Carlo equity
# versus pot odds on every nontrivial decision.
# --------------------------------------------------------------------------

class CaseyCalculator(Strategy):
    name = "CaseyCalculator"

    TRIALS = 60

    def __init__(self, rng):
        super().__init__(rng)
        self._cache_key = None
        self._cache_eq = 0.0

    def _equity(self, view):
        n_opp = max(1, view.num_live - 1)
        key = (view.hole, view.board, min(n_opp, 3))
        if key != self._cache_key:
            self._cache_key = key
            eq = mc_equity(view.hole, view.board, n_opp, self.TRIALS, self.rng)
            if n_opp > 3:  # crude correction for extra opponents
                eq *= (0.92 ** (n_opp - 3))
            self._cache_eq = eq
        return self._cache_eq

    def act(self, view):
        bb = view.big_blind
        # Cheap preflop pre-filter so we don't simulate trash.
        if view.street == "preflop":
            c = chen_score(view.hole)
            if c < 5.0 and view.to_call > 0:
                return ("fold", 0)
            if c < 6.5 and view.to_call > 3 * bb:
                return ("fold", 0)

        eq = self._equity(view)
        n_live = view.num_live
        fair_share = 1.0 / n_live
        odds = self.pot_odds(view)

        if view.to_call == 0:
            if eq > fair_share + 0.22:
                return self.bet_pot_frac(view, 0.75)
            if eq > fair_share + 0.10:
                return self.bet_pot_frac(view, 0.5)
            return ("call", 0)

        committed = view.to_call >= view.my_stack
        if committed:
            # All-in decision: demand a real edge over the price.
            return ("call", 0) if eq > odds + 0.06 else ("fold", 0)
        if eq > odds + 0.28 and eq > 0.5:
            return self.shove(view) if view.pot > view.my_stack \
                else self.raise_to(view, view.current_bet * 2.6)
        if eq > odds + 0.02:
            return ("call", 0)
        return ("fold", 0)


# --------------------------------------------------------------------------
# Player 6 — "Sherlock": the profiler. Tracks every opponent's VPIP,
# aggression and shove rate from public actions alone, then exploits.
# A table with a shove-bot at it is Sherlock's favourite crime scene.
# --------------------------------------------------------------------------

class Sherlock(Strategy):
    name = "Sherlock"

    def __init__(self, rng):
        super().__init__(rng)
        self.hands_seen = 0
        self.stats = {}   # pid -> {hands, vpip, acts, aggr, shoves}
        self._in_hand = set()
        self._vpip_credited = set()

    def _s(self, pid):
        return self.stats.setdefault(
            pid, {"hands": 0, "vpip": 0, "acts": 0, "aggr": 0, "shoves": 0})

    def observe(self, event):
        et = event.get("type")
        if et == "hand_start":
            self.hands_seen += 1
            self._in_hand = set(event["pids"])
            self._vpip_credited = set()
            for pid in event["pids"]:
                self._s(pid)["hands"] += 1
        elif et == "action":
            pid = event["pid"]
            s = self._s(pid)
            a = event["action"]
            if a == "blind":
                return
            s["acts"] += 1
            if a == "raise":
                s["aggr"] += 1
                if event.get("all_in"):
                    s["shoves"] += 1
            if (event["street"] == "preflop" and a in ("call", "raise")
                    and pid not in self._vpip_credited):
                self._vpip_credited.add(pid)
                s["vpip"] += 1

    # profiling ------------------------------------------------------------
    def shove_rate(self, pid):
        s = self._s(pid)
        return s["shoves"] / max(1, s["hands"])

    def aggression(self, pid):
        s = self._s(pid)
        return s["aggr"] / max(3, s["acts"])

    def _last_aggressor(self, view):
        for st, pid, a, _amt in reversed(view.history):
            if st == view.street and a in ("raise", "allin_raise"):
                return pid
        return None

    def act(self, view):
        if view.street == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        c = chen_score(view.hole)
        bb = view.big_blind
        facing_shove = view.to_call >= min(view.my_stack, 15 * bb)
        aggressor = self._last_aggressor(view)

        if facing_shove and aggressor is not None:
            sr = self.shove_rate(aggressor)
            if sr > 0.4 and self.hands_seen >= 5:
                # Deduced: that player shoves any two cards. Any decent
                # hand is a massive favourite — snap it off.
                need = 6.5
            elif sr > 0.15:
                need = 8.5
            else:
                need = 10.5  # a normal human shoving is scary
            if view.my_stack <= 8 * bb:
                need -= 1.5
            return ("call", 0) if c >= need else ("fold", 0)

        if view.current_bet > bb:
            tight_raiser = aggressor is not None and \
                self.aggression(aggressor) < 0.25 and self.hands_seen >= 8
            if c >= (12.0 if tight_raiser else 10.5):
                return self.raise_to(view, view.current_bet * 3)
            if c >= (9.5 if tight_raiser else 8.0) and view.to_call <= 5 * bb:
                return ("call", 0)
            return ("fold", 0)

        open_threshold = 8.5 - 2.5 * view.pos_frac
        if c >= open_threshold:
            return self.raise_to(view, 3 * bb)
        if view.to_call == 0:
            return ("call", 0)
        if c >= 6.5 and view.to_call <= bb:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        t = made_tier(view.hole, view.board)
        fd, souts = draw_info(view.hole, view.board)
        odds = self.pot_odds(view)
        aggressor = self._last_aggressor(view)
        vs_maniac = aggressor is not None and (
            self.shove_rate(aggressor) > 0.3 or self.aggression(aggressor) > 0.6)
        vs_nit = aggressor is not None and \
            self.aggression(aggressor) < 0.2 and self.hands_seen >= 8

        if t >= 4:
            if view.to_call > 0:
                return self.shove(view) if vs_maniac else \
                    self.raise_to(view, view.current_bet * 2.5)
            return self.bet_pot_frac(view, 0.7)
        if t == 3:
            if view.to_call == 0:
                return self.bet_pot_frac(view, 0.6)
            if vs_maniac:
                return ("call", 0)  # top pair is the nuts against a shove-bot
            if vs_nit and view.to_call > view.pot * 0.5:
                return ("fold", 0)  # a nit betting big has it; get out
            return ("call", 0) if odds <= 0.34 else ("fold", 0)
        if t == 2:
            if view.to_call == 0:
                return ("call", 0)
            limit = 0.30 if vs_maniac else 0.18
            return ("call", 0) if odds <= limit else ("fold", 0)
        if (fd or souts >= 2) and view.street != "river":
            if view.to_call == 0 and self.rng.random() < 0.5:
                return self.bet_pot_frac(view, 0.5)
            return ("call", 0) if odds <= 0.32 else ("fold", 0)
        # air: steal from opponents who fold too much, else surrender
        if view.to_call == 0:
            fold_happy = all(
                self.aggression(pid) < 0.3 for pid in view.live_pids
                if pid != view.pid) and self.hands_seen >= 8
            if fold_happy and view.street != "river" and self.rng.random() < 0.35:
                return self.bet_pot_frac(view, 0.55)
            return ("call", 0)
        return ("fold", 0)


ROSTER = [
    (1, AllInAnnie),
    (2, TheRock),
    (3, TagTitan),
    (4, LagLoki),
    (5, CaseyCalculator),
    (6, Sherlock),
]
