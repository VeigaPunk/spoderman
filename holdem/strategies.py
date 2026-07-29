"""Six poker brains. Five elaborate, one gloriously unhinged.

No strategy is told what any other strategy is — the only information
available is a player's own hole cards and the public action history.
"""
from collections import Counter, defaultdict

from .cards import best_hand, chen_score, mc_equity, rank_of, suit_of


def _postflop_features(hole, board):
    """Public-board-relative hand features used by the rule-based bots."""
    full = tuple(hole) + tuple(board)
    rank = best_hand(full)
    cat = rank[0]
    board_ranks = [rank_of(c) for c in board]
    hole_ranks = sorted((rank_of(c) for c in hole), reverse=True)
    top_board = max(board_ranks)
    pocket_pair = hole_ranks[0] == hole_ranks[1]
    overpair = pocket_pair and hole_ranks[0] > top_board
    top_pair = (not pocket_pair) and top_board in hole_ranks
    any_pair_with_hole = any(hr in board_ranks for hr in hole_ranks)
    suit_counts = Counter(suit_of(c) for c in full)
    flush_draw = cat < 5 and any(v == 4 for v in suit_counts.values())
    seen = set(hole_ranks) | set(board_ranks)
    if 14 in seen:
        seen.add(1)  # wheel ace
    straight_draw = cat < 4 and any(
        all(r in seen for r in range(lo, lo + 4)) for lo in range(1, 12)
    )
    kicker = hole_ranks[0] if hole_ranks[1] in board_ranks else hole_ranks[1]
    return {
        "cat": cat,
        "overpair": overpair,
        "top_pair": top_pair,
        "pair_with_hole": any_pair_with_hole,
        "flush_draw": flush_draw,
        "straight_draw": straight_draw,
        "kicker": kicker,
    }


def _last_aggressor(history, street=None):
    """(pid, was_allin) of the most recent raiser, or (None, False)."""
    for ev in reversed(history):
        if ev.get("type") != "action" or ev["action"] != "raise":
            continue
        if street is not None and ev["street"] != street:
            continue
        return ev["pid"], ev["allin"]
    return None, False


def _pot_odds(view):
    tc = view["to_call"]
    return tc / (view["pot"] + tc) if tc > 0 else 0.0


class Strategy:
    name = "base"

    def __init__(self, pid, rng):
        self.pid = pid
        self.rng = rng

    def act(self, view):
        return "check"

    def observe(self, event):
        pass


# ---------------------------------------------------------------------------
# Player 1 — the entire strategy, verbatim:
#   if my_turn
#   then bet = All in
#   fi
# ---------------------------------------------------------------------------
class AllInBot(Strategy):
    name = "Spoderman"

    def act(self, view):
        return ("raise", 10**9)


# ---------------------------------------------------------------------------
# Player 2 — TAG_Titan: tight-aggressive. Chen-formula preflop ranges that
# widen in late position, three-bets premiums, continuation-bets as the
# aggressor, value-bets strong made hands and calls draws only when the pot
# odds justify it.
# ---------------------------------------------------------------------------
class TightAggressive(Strategy):
    name = "TAG_Titan"

    def _i_raised_preflop(self, view):
        return any(
            ev.get("type") == "action"
            and ev["street"] == "preflop"
            and ev["action"] == "raise"
            and ev["pid"] == self.pid
            for ev in view["history"]
        )

    def act(self, view):
        c = chen_score(view["hole"])
        bb, tc, pot = view["bb"], view["to_call"], view["pot"]

        if view["street"] == "preflop":
            facing_jam = tc >= min(10 * bb, 0.6 * (view["stack"] + view["my_bet"]))
            if facing_jam:
                return "call" if c >= 11 else "fold"
            if tc > bb:  # facing a raise
                if c >= 10:
                    return ("raise", view["current_bet"] * 3)
                if c >= 8 and tc <= 0.12 * view["stack"]:
                    return "call"
                return "fold"
            open_threshold = 6.5 if view["late"] else 8
            if c >= open_threshold:
                return ("raise", max(3 * bb, view["min_raise_to"]))
            if c >= 6 and tc == 0:
                return "check"
            return "fold" if tc > 0 else "check"

        f = _postflop_features(view["hole"], view["board"])
        strong = f["cat"] >= 2 or f["overpair"] or (f["cat"] == 1 and f["top_pair"])
        monster = f["cat"] >= 3
        if strong:
            if tc == 0:
                return ("raise", max(int(pot * 0.66), view["min_raise_to"]))
            if monster or tc <= 0.5 * pot:
                if monster and self.rng.random() < 0.5:
                    return ("raise", view["current_bet"] + pot)
                return "call"
            return "call" if f["overpair"] else "fold"
        if f["flush_draw"] or f["straight_draw"]:
            if tc == 0:
                if self.rng.random() < 0.4:  # semi-bluff
                    return ("raise", max(int(pot * 0.5), view["min_raise_to"]))
                return "check"
            if _pot_odds(view) < 0.28 and tc < 0.3 * view["stack"]:
                return "call"
            return "fold"
        if tc == 0:
            if (
                view["street"] == "flop"
                and self._i_raised_preflop(view)
                and self.rng.random() < 0.55
            ):  # continuation bet
                return ("raise", max(int(pot * 0.5), view["min_raise_to"]))
            return "check"
        if f["pair_with_hole"] and _pot_odds(view) < 0.2:
            return "call"
        return "fold"


# ---------------------------------------------------------------------------
# Player 3 — LAG_Lunatic: loose-aggressive. Opens wide, three-bet bluffs,
# barrels flops, semi-bluff-raises draws and hero-calls with marginal pairs.
# High variance by design.
# ---------------------------------------------------------------------------
class LooseAggressive(Strategy):
    name = "LAG_Lunatic"

    def act(self, view):
        c = chen_score(view["hole"])
        bb, tc, pot = view["bb"], view["to_call"], view["pot"]
        r = self.rng.random()

        if view["street"] == "preflop":
            facing_jam = tc >= min(10 * bb, 0.6 * (view["stack"] + view["my_bet"]))
            if facing_jam:
                if c >= 9 or (c >= 7 and _pot_odds(view) < 0.38):
                    return "call"
                return "fold"
            if tc > bb:
                if c >= 9 or r < 0.15:  # three-bet (sometimes as pure bluff)
                    return ("raise", view["current_bet"] * 3)
                if c >= 4 and tc <= 4 * bb:
                    return "call"
                return "fold"
            if c >= 4.5 or r < 0.25:
                return ("raise", max(int(2.5 * bb), view["min_raise_to"]))
            if tc == 0:
                return "check"
            return "call" if tc <= 2 * bb and c >= 2 else "fold"

        f = _postflop_features(view["hole"], view["board"])
        big_draw = f["flush_draw"] or f["straight_draw"]
        if tc == 0:
            if f["cat"] >= 1 or big_draw or r < 0.45:  # bet made hands, draws, air
                size = 0.75 if f["cat"] >= 2 else 0.55
                return ("raise", max(int(pot * size), view["min_raise_to"]))
            return "check"
        if f["cat"] >= 2:
            if r < 0.6:
                return ("raise", view["current_bet"] + pot)
            return "call"
        if big_draw:
            if r < 0.45 and tc < 0.4 * view["stack"]:  # semi-bluff raise
                return ("raise", view["current_bet"] + pot)
            return "call" if _pot_odds(view) < 0.36 else "fold"
        if f["pair_with_hole"] and _pot_odds(view) < 0.33:
            return "call"  # hero call
        if r < 0.08 and tc < 0.25 * view["stack"]:
            return ("raise", view["current_bet"] + pot)  # pure bluff-raise
        return "fold"


# ---------------------------------------------------------------------------
# Player 4 — EquityOracle: runs a Monte Carlo simulation at every decision,
# compares estimated equity against the pot odds, sizes bets with equity and
# mixes frequencies so it can't be trivially read.
# ---------------------------------------------------------------------------
class EquityOracle(Strategy):
    name = "EquityOracle"

    def act(self, view):
        n_opp = max(1, view["num_live"] - 1)
        samples = 24 if view["street"] == "preflop" else 36
        eq = mc_equity(view["hole"], view["board"], n_opp, self.rng, samples)
        _, agg_allin = _last_aggressor(view["history"])
        if view["to_call"] > 0 and agg_allin:
            eq *= 0.88  # an all-in range is stronger than a random hand
        tc, pot = view["to_call"], view["pot"]
        r = self.rng.random()

        if tc > 0:
            po = _pot_odds(view)
            if eq > 0.80:
                return ("raise", 10**9) if r < 0.5 else ("raise", view["current_bet"] + pot)
            if eq > 0.62 and r < 0.55:
                return ("raise", view["current_bet"] + int(pot * 0.8))
            if eq >= po + 0.04 or (eq >= po and r < 0.5):
                return "call"
            return "fold"
        if eq > 0.72:
            return ("raise", max(int(pot * 0.85), view["min_raise_to"]))
        if eq > 0.55:
            if r < 0.65:
                return ("raise", max(int(pot * 0.6), view["min_raise_to"]))
            return "check"
        if eq > 0.42 and r < 0.25:  # thin probe bet
            return ("raise", max(int(pot * 0.4), view["min_raise_to"]))
        return "check"


# ---------------------------------------------------------------------------
# Player 5 — NitNorris: pathologically tight. Plays only premiums, set-mines
# cheap with pocket pairs, folds everything marginal, and switches to a
# Sklansky-style push/fold chart once short-stacked.
# ---------------------------------------------------------------------------
class NitPushFold(Strategy):
    name = "NitNorris"

    def act(self, view):
        c = chen_score(view["hole"])
        bb, tc, pot = view["bb"], view["to_call"], view["pot"]
        hr = [rank_of(x) for x in view["hole"]]
        pocket_pair = hr[0] == hr[1]

        if view["street"] == "preflop":
            eff_bb = (view["stack"] + view["my_bet"]) / bb
            if eff_bb <= 10:  # push/fold mode
                if c >= 7 or (view["late"] and c >= 6) or (pocket_pair and eff_bb <= 6):
                    return ("raise", 10**9)
                return "fold" if tc > 0 else "check"
            facing_jam = tc >= min(10 * bb, 0.6 * (view["stack"] + view["my_bet"]))
            if facing_jam:
                return "call" if c >= 11 else "fold"
            if c >= 10 or (view["late"] and c >= 8.5):
                return ("raise", max(3 * bb, view["min_raise_to"]))
            if pocket_pair and tc <= max(2 * bb, 0.05 * view["stack"]):
                return "call"  # set mining
            return "fold" if tc > 0 else "check"

        f = _postflop_features(view["hole"], view["board"])
        strong = (
            f["cat"] >= 2
            or f["overpair"]
            or (f["cat"] == 1 and f["top_pair"] and f["kicker"] >= 11)
        )
        if strong:
            if tc == 0:
                return ("raise", max(int(pot * 0.7), view["min_raise_to"]))
            return "call"
        if tc == 0:
            return "check"
        if f["pair_with_hole"] and _pot_odds(view) < 0.15:
            return "call"
        return "fold"


# ---------------------------------------------------------------------------
# Player 6 — AdaptiveAdversary: opponent modeling. Tracks every player's
# shove rate, raise rate and fold rate from the public action stream, then
# exploits: calls maniacs wide (with a Monte Carlo equity check), respects
# tight players' raises, and steals from players who fold too much.
# ---------------------------------------------------------------------------
class AdaptiveExploiter(Strategy):
    name = "AdaptiveAdversary"

    def __init__(self, pid, rng):
        super().__init__(pid, rng)
        self.stats = defaultdict(lambda: {"hands": 0, "shoves": 0, "raises": 0,
                                          "folds": 0, "acts": 0})

    def observe(self, event):
        if event.get("type") == "hand_start":
            for pid in event["pids"]:
                self.stats[pid]["hands"] += 1
        elif event.get("type") == "action" and event["pid"] != self.pid:
            s = self.stats[event["pid"]]
            s["acts"] += 1
            if event["action"] == "raise":
                s["raises"] += 1
                if event["allin"]:
                    s["shoves"] += 1
            elif event["action"] == "fold":
                s["folds"] += 1

    def _shove_rate(self, pid):
        s = self.stats[pid]
        return s["shoves"] / max(s["hands"], 1)

    def _fold_rate(self, pid):
        s = self.stats[pid]
        return s["folds"] / max(s["acts"], 1)

    def act(self, view):
        c = chen_score(view["hole"])
        bb, tc, pot = view["bb"], view["to_call"], view["pot"]
        agg_pid, agg_allin = _last_aggressor(view["history"])

        if view["street"] == "preflop":
            facing_jam = agg_allin or tc >= min(
                10 * bb, 0.6 * (view["stack"] + view["my_bet"])
            )
            if facing_jam and tc > 0:
                maniac = agg_pid is not None and self._shove_rate(agg_pid) > 0.30 \
                    and self.stats[agg_pid]["hands"] >= 3
                if maniac:
                    # vs a range of "literally any two cards": trust raw equity
                    eq = mc_equity(view["hole"], (), 1, self.rng, samples=40)
                    return "call" if eq > _pot_odds(view) + 0.03 else "fold"
                return "call" if c >= 10.5 else "fold"
            if tc > bb:
                tight_raiser = agg_pid is not None and self._shove_rate(agg_pid) < 0.05
                need = 9.5 if tight_raiser else 8
                if c >= need + 2:
                    return ("raise", view["current_bet"] * 3)
                if c >= need and tc <= 0.15 * view["stack"]:
                    return "call"
                return "fold"
            avg_fold = sum(self._fold_rate(p) for p in view["stacks"] if p != self.pid)
            avg_fold /= max(1, len(view["stacks"]) - 1)
            steal = view["late"] and avg_fold > 0.45 and self.rng.random() < 0.35
            if c >= (7 if not view["late"] else 5.5) or steal:
                return ("raise", max(int(2.5 * bb), view["min_raise_to"]))
            return "fold" if tc > 0 else "check"

        f = _postflop_features(view["hole"], view["board"])
        strong = f["cat"] >= 2 or f["overpair"] or (f["cat"] == 1 and f["top_pair"])
        if strong:
            if tc == 0:
                return ("raise", max(int(pot * 0.7), view["min_raise_to"]))
            if f["cat"] >= 3 and self.rng.random() < 0.6:
                return ("raise", view["current_bet"] + pot)
            return "call"
        if f["flush_draw"] or f["straight_draw"]:
            if tc == 0:
                return ("raise", max(int(pot * 0.5), view["min_raise_to"])) \
                    if self.rng.random() < 0.45 else "check"
            return "call" if _pot_odds(view) < 0.3 else "fold"
        if tc == 0:
            bluffable = agg_pid is None and any(
                self._fold_rate(p) > 0.5 for p in view["stacks"] if p != self.pid
            )
            if bluffable and self.rng.random() < 0.3:
                return ("raise", max(int(pot * 0.5), view["min_raise_to"]))
            return "check"
        if f["pair_with_hole"] and _pot_odds(view) < 0.22:
            return "call"
        return "fold"
