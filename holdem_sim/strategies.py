"""Six poker brains. One of them is not like the others.

Every strategy sees only its own hole cards plus public information
(board, pot, bets, stacks, observed actions). None of them is told what
the others are running — SherlockShark has to *deduce* that Player 1 is
a lunatic from the evidence, like everyone else at the table.
"""

import math
import random

from .cards import evaluate_best

PREMIUM = {(14, 14), (13, 13), (12, 12)}          # AA KK QQ (as rank pairs)


# ----------------------------------------------------------------- helpers

def chen_score(hole):
    """Bill Chen's preflop formula (slightly liberal rounding)."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    pts = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if s1 == s2:
        pts += 2
    gap = hi - lo - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        pts += 1
    return math.ceil(pts)


def hole_key(hole):
    (r1, _), (r2, _) = hole
    return (max(r1, r2), min(r1, r2))


def is_pair(hole, at_least=2):
    (r1, _), (r2, _) = hole
    return r1 == r2 and r1 >= at_least


def made(hole, board):
    """Best made-hand score using the hole cards and the board so far."""
    return evaluate_best(hole + board)


def top_pair_or_better(hole, board):
    score = made(hole, board)
    if score[0] >= 2:
        return True
    if score[0] == 1:
        board_top = max((c[0] for c in board), default=0)
        pair_rank = score[1]
        holds = any(c[0] == pair_rank for c in hole)
        return holds and pair_rank >= board_top
    return False


def flush_draw(hole, board):
    suits = [c[1] for c in hole + board]
    return any(suits.count(s) == 4 for s in set(suits)) and len(board) < 5


def open_ended(hole, board):
    ranks = set(c[0] for c in hole + board)
    if 14 in ranks:
        ranks.add(1)
    for lo in range(1, 11):
        window = [lo + k in ranks for k in range(5)]
        if sum(window) == 4 and window[0] and window[3] and not window[4]:
            return len(board) < 5
    return False


def mc_equity(hole, board, n_opp, iters, rng):
    """Monte Carlo equity vs `n_opp` random hands. Public info only."""
    seen = set(hole + board)
    stub = [c for c in
            ((r, s) for r in range(2, 15) for s in range(4)) if c not in seen]
    need_board = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        draw = rng.sample(stub, n_opp * 2 + need_board)
        full_board = board + draw[:need_board]
        mine = evaluate_best(hole + full_board)
        k = need_board
        best_opp = None
        for _o in range(n_opp):
            sc = evaluate_best(draw[k:k + 2] + full_board)
            k += 2
            if best_opp is None or sc > best_opp:
                best_opp = sc
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


class Strategy:
    name = "?"

    def reset(self, rng):
        self.rng = rng

    def observe(self, event):
        pass

    def act(self, view):
        raise NotImplementedError


# ================================================================ Player 1

class AllInAndy(Strategy):
    """The entire strategy document, implemented with total fidelity:

        if my_turn
        then bet = All in
        fi
    """
    name = "AllInAndy"

    def act(self, view):
        # It is, in fact, my turn.
        return ("raise", 10 ** 12)   # the engine clamps this to exactly all-in


# ================================================================ Player 2

class GrandmasterFlush(Strategy):
    """Tight-aggressive classicist.

    Preflop: Chen-formula ranges widened by position, short-stack
    push/fold below 8 big-blind-rounds (Harrington's M). Postflop:
    value-bets top pair or better, continuation-bets as the aggressor,
    semi-bluffs strong draws when the price and fold equity justify it,
    and folds marginal hands to serious pressure.
    """
    name = "GrandmasterFlush"

    def reset(self, rng):
        super().reset(rng)
        self.aggressor_hand = -1

    def act(self, view):
        hole, board, street = view["hole"], view["board"], view["street"]
        pot, to_call, stack = view["pot"], view["to_call"], view["my_stack"]
        bb = view["big_blind"]

        if street == "preflop":
            score = chen_score(hole)
            m_ratio = stack / max(1, bb + bb // 2)
            hi, lo = hole_key(hole)

            if m_ratio < 8:  # desperation: push/fold
                if score >= 8 or hi == lo or hi == 14:
                    return ("raise", 10 ** 12)
                return ("fold",)

            raised_against_me = to_call > bb  # someone raised before me
            if (hi, lo) in PREMIUM or (hi, lo) == (14, 13):
                self.aggressor_hand = view["hand_no"]
                return ("raise", max(view["min_raise_to"],
                                     view["my_street_bet"] + to_call + pot))
            threshold = 9 if view["position"] < 0.6 else 7
            if raised_against_me:
                if score >= 10:
                    return ("call",)
                if score >= 8 and to_call <= 3 * bb:
                    return ("call",)
                return ("fold",)
            if score >= threshold:
                self.aggressor_hand = view["hand_no"]
                return ("raise", view["my_street_bet"] + to_call + 3 * bb)
            if to_call == 0:
                return ("call",)  # check the big blind
            if to_call <= bb and score >= 6:
                return ("call",)  # complete cheap from the small blind
            return ("fold",)

        # ---- postflop
        strong = top_pair_or_better(hole, board)
        monster = made(hole, board)[0] >= 3
        drawing = flush_draw(hole, board) or open_ended(hole, board)

        if monster:
            target = view["my_street_bet"] + to_call + max(pot, bb)
            return ("raise", target)
        if strong:
            if to_call > pot and made(hole, board)[0] < 2:
                return ("fold",)  # top pair is not a stack-off vs huge bets
            if to_call > 0:
                return ("call",)
            return ("raise", view["my_street_bet"] + (2 * pot) // 3)
        if drawing:
            pot_odds = to_call / max(1, pot + to_call)
            if to_call == 0:
                if self.rng.random() < 0.5:
                    return ("raise", view["my_street_bet"] + pot // 2)
                return ("call",)
            return ("call",) if pot_odds < 0.3 else ("fold",)
        if self.aggressor_hand == view["hand_no"] and street == "flop" and to_call == 0:
            return ("raise", view["my_street_bet"] + pot // 2)  # c-bet
        return ("call",) if to_call == 0 else ("fold",)


# ================================================================ Player 3

class BluffyTheVampireSlayer(Strategy):
    """Loose-aggressive chaos merchant.

    Opens wide, three-bets light on a randomized frequency, steals from
    late position when the pot is unopened, barrels with pairs, draws or
    pure air on a schedule — but keeps a survival instinct: facing
    pot-sized-or-bigger aggression with no equity, the cape comes off.
    """
    name = "BluffyTheVampireSlayer"

    def reset(self, rng):
        super().reset(rng)
        self.raises_this_hand = 0
        self.seen_hand = -1

    def observe(self, event):
        if event.get("type") != "action":
            return
        if event["hand"] != self.seen_hand:
            self.seen_hand = event["hand"]
            self.raises_this_hand = 0
        if event["action"] in ("raise", "allin_raise"):
            self.raises_this_hand += 1

    def act(self, view):
        hole, board, street = view["hole"], view["board"], view["street"]
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        roll = self.rng.random()

        if street == "preflop":
            score = chen_score(hole)
            unopened = self.raises_this_hand == 0 and to_call <= bb
            if score >= 9 or (score >= 6 and roll < 0.55):
                bump = 3 * bb if self.raises_this_hand == 0 else pot
                return ("raise", view["my_street_bet"] + to_call + bump)
            if unopened and view["position"] > 0.65 and roll < 0.4:
                return ("raise", view["my_street_bet"] + to_call + 2 * bb)  # steal
            if to_call == 0:
                return ("call",)
            pot_odds = to_call / max(1, pot + to_call)
            if score >= 6 and pot_odds < 0.35:
                return ("call",)
            if to_call >= view["my_stack"] and score < 10:
                return ("fold",)  # even vampires respect a stake to the heart
            return ("fold",) if pot_odds > 0.3 else ("call",)

        score = made(hole, board)
        drawing = flush_draw(hole, board) or open_ended(hole, board)
        has_pair = score[0] >= 1
        pot_odds = to_call / max(1, pot + to_call)

        if score[0] >= 2:
            return ("raise", view["my_street_bet"] + to_call + pot)
        if to_call == 0:
            if has_pair or drawing or roll < 0.3:
                return ("raise", view["my_street_bet"] + (3 * pot) // 4)
            return ("call",)
        if to_call >= pot and not (has_pair or drawing):
            return ("fold",) if roll > 0.08 else ("call",)  # rare hero call
        if has_pair or drawing:
            return ("call",) if pot_odds < 0.45 else ("fold",)
        return ("call",) if pot_odds < 0.2 and roll < 0.5 else ("fold",)


# ================================================================ Player 4

class TheGranite(Strategy):
    """A rock. Folds for a living.

    Plays only premium holdings preflop, stacks off only with jacks-plus
    or ace-king, and after the flop continues with top pair/overpair or
    better. Boring, patient, and — against a table containing a
    shove-monkey — possibly a genius.
    """
    name = "TheGranite"

    RANGE = {(14, 13), (14, 12)}  # AK, AQ — pairs handled separately

    def act(self, view):
        hole, board, street = view["hole"], view["board"], view["street"]
        to_call, bb = view["to_call"], view["big_blind"]
        hi, lo = hole_key(hole)
        suited = hole[0][1] == hole[1][1]

        if street == "preflop":
            playable = (is_pair(hole, at_least=9)
                        or (hi, lo) in self.RANGE
                        or ((hi, lo) == (14, 11) and suited))
            stack_off = is_pair(hole, at_least=11) or (hi, lo) == (14, 13)
            if not playable:
                return ("call",) if to_call == 0 else ("fold",)
            if stack_off:
                return ("raise", 10 ** 12) if to_call >= 4 * bb else \
                       ("raise", view["my_street_bet"] + to_call + 3 * bb)
            if to_call > 5 * bb:  # good-but-not-great vs heavy action: pass
                return ("fold",)
            if to_call <= bb:
                return ("raise", view["my_street_bet"] + to_call + 3 * bb)
            return ("call",)

        score = made(hole, board)
        board_top = max((c[0] for c in board), default=0)
        overpair = is_pair(hole) and hi > board_top
        good = score[0] >= 2 or overpair or top_pair_or_better(hole, board)
        if score[0] >= 3:
            return ("raise", view["my_street_bet"] + to_call + view["pot"])
        if good:
            if to_call > 2 * view["pot"] and score[0] < 2 and not overpair:
                return ("fold",)
            return ("call",) if to_call > 0 else \
                   ("raise", view["my_street_bet"] + (2 * view["pot"]) // 3)
        return ("call",) if to_call == 0 else ("fold",)


# ================================================================ Player 5

class CountVonCount(Strategy):
    """The pot-odds mathematician. Ah-ah-ah.

    Every decision is a Monte Carlo equity estimate against the live
    number of opponents, compared with the price being offered. Bets
    grow with the edge; with no edge it will fold a hand that looks
    pretty but prices out. Short-stacked it switches to equity push/fold.
    """
    name = "CountVonCount"

    def act(self, view):
        hole, board = view["hole"], view["board"]
        pot, to_call, stack = view["pot"], view["to_call"], view["my_stack"]
        bb = view["big_blind"]
        n_opp = max(1, min(view["num_in_hand"] - 1, 3))
        iters = 60 if board else 45
        eq = mc_equity(hole, board, n_opp, iters, self.rng)
        fair = 1.0 / (n_opp + 1)
        pot_odds = to_call / max(1, pot + to_call)

        if stack <= 6 * (bb + bb // 2):  # short: shove any real edge
            if eq > fair + 0.08:
                return ("raise", 10 ** 12)
            return ("call",) if to_call == 0 else ("fold",)

        if eq >= fair + 0.28 or eq >= 0.80:
            return ("raise", view["my_street_bet"] + to_call + max(pot, 3 * bb))
        if eq >= fair + 0.12:
            if to_call == 0:
                return ("raise", view["my_street_bet"] + (2 * pot) // 3)
            return ("call",) if pot_odds < eq else ("fold",)
        if to_call == 0:
            return ("call",)
        return ("call",) if pot_odds < eq - 0.03 else ("fold",)


# ================================================================ Player 6

class SherlockShark(Strategy):
    """The profiler. Watches every public action and keeps a dossier:
    how often each opponent enters pots, raises, and open-shoves.

    Against detected maniacs (looking at nobody in particular) it stops
    respecting the shove and calls with any hand whose equity vs a
    random holding beats the price. Against rocks it steals relentlessly.
    Bluffs only at opponents who have shown they can fold.
    """
    name = "SherlockShark"

    def reset(self, rng):
        super().reset(rng)
        self.dossier = {}   # name -> {hands, entered, raises, allins, folds}
        self.counted = set()

    def _file(self, who):
        return self.dossier.setdefault(
            who, {"hands": 0, "entered": 0, "raises": 0, "allins": 0, "folds": 0})

    def observe(self, event):
        if event.get("type") != "action":
            return
        who = event["player"]
        f = self._file(who)
        key = (event["hand"], who)
        if key not in self.counted:
            self.counted.add(key)
            f["hands"] += 1
        act = event["action"]
        if act in ("call", "raise", "allin_raise", "allin_call"):
            f["entered"] += 1
        if act in ("raise", "allin_raise"):
            f["raises"] += 1
        if act == "allin_raise":
            f["allins"] += 1
        if act == "fold":
            f["folds"] += 1

    def _maniac_alert(self, view):
        """Is the current bet likely to come from an any-two-cards shover?"""
        worst = 0.0
        for who, f in self.dossier.items():
            if who == view["my_name"] or f["hands"] < 4:
                continue
            rate = f["allins"] / f["hands"]
            if rate > worst:
                worst = rate
        return worst

    def act(self, view):
        hole, board, street = view["hole"], view["board"], view["street"]
        pot, to_call, bb = view["pot"], view["to_call"], view["big_blind"]
        shover_rate = self._maniac_alert(view)
        facing_jam = to_call >= view["my_stack"] or to_call > 8 * bb
        pot_odds = to_call / max(1, pot + to_call)

        # --- the exploit: a table with a chronic shover has no fold equity
        #     against us; we simply take the best price we can get.
        if facing_jam and shover_rate > 0.5:
            eq = mc_equity(hole, board, 1, 90, self.rng)
            return ("call",) if eq > pot_odds + 0.04 else ("fold",)

        if street == "preflop":
            score = chen_score(hole)
            hi, lo = hole_key(hole)
            if (hi, lo) in PREMIUM or (hi, lo) == (14, 13):
                return ("raise", view["my_street_bet"] + to_call + max(pot, 3 * bb))
            if facing_jam:  # unknown shover: stay honest
                return ("call",) if score >= 10 else ("fold",)
            # steal wide vs foldy tables
            foldiness = 0.0
            files = [f for w, f in self.dossier.items()
                     if w != view["my_name"] and f["hands"] >= 4]
            if files:
                foldiness = sum(f["folds"] / f["hands"] for f in files) / len(files)
            open_threshold = 6 if foldiness > 0.45 else 8
            if score >= open_threshold and to_call <= 3 * bb:
                return ("raise", view["my_street_bet"] + to_call + 3 * bb)
            if to_call == 0:
                return ("call",)
            if score >= 7 and pot_odds < 0.3:
                return ("call",)
            return ("fold",)

        score = made(hole, board)
        drawing = flush_draw(hole, board) or open_ended(hole, board)
        if score[0] >= 2:
            return ("raise", view["my_street_bet"] + to_call + pot)
        if top_pair_or_better(hole, board):
            if to_call > pot:
                eq = mc_equity(hole, board, 1, 70, self.rng)
                return ("call",) if eq > pot_odds + 0.05 else ("fold",)
            return ("call",) if to_call > 0 else \
                   ("raise", view["my_street_bet"] + (2 * pot) // 3)
        if drawing and (to_call == 0 or pot_odds < 0.32):
            return ("call",) if to_call > 0 else \
                   ("raise", view["my_street_bet"] + pot // 2)
        return ("call",) if to_call == 0 else ("fold",)


LINEUP = [
    ("P1 " + AllInAndy.name, AllInAndy),
    ("P2 " + GrandmasterFlush.name, GrandmasterFlush),
    ("P3 " + BluffyTheVampireSlayer.name, BluffyTheVampireSlayer),
    ("P4 " + TheGranite.name, TheGranite),
    ("P5 " + CountVonCount.name, CountVonCount),
    ("P6 " + SherlockShark.name, SherlockShark),
]
