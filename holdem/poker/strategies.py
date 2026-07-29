"""Player strategies.

Player 1 uses YoloAllIn (the whole strategy: "if my_turn then bet = all in").
Players 2..6 use the five elaborate strategies below. No strategy knows any
other strategy's algorithm — they only observe public actions at the table,
exactly like a live player would.
"""

from .cards import card_rank, card_suit, preflop_strength

# ---------------------------------------------------------------------------
# Player 1 — the entire algorithm, faithfully transcribed:
#   if my_turn
#   Then bet = All in
#   Fi
# ---------------------------------------------------------------------------


class YoloAllIn:
    def act(self, view):
        return ("raise", view["my_committed"] + view["stack"])


# ---------------------------------------------------------------------------
# Shared helpers for the thinking players
# ---------------------------------------------------------------------------


def _board_texture(board):
    """Rudimentary draw detection: returns (flush_suit_count, straightiness)."""
    suits = [card_suit(c) for c in board]
    flushy = max(suits.count(s) for s in range(4)) if board else 0
    ranks = sorted({card_rank(c) for c in board})
    straighty = 0
    for i in range(len(ranks) - 1):
        if ranks[i + 1] - ranks[i] <= 2:
            straighty += 1
    return flushy, straighty


def _my_draws(hole, board):
    """Return (has_flush_draw, has_open_ender) for hole+board."""
    cards = list(hole) + list(board)
    suits = [card_suit(c) for c in cards]
    flush_draw = any(suits.count(s) == 4 for s in range(4))
    ranks = sorted({card_rank(c) for c in cards})
    open_ender = False
    for i in range(len(ranks) - 3):
        if ranks[i + 3] - ranks[i] == 3:  # 4 in a row
            open_ender = True
    return flush_draw, open_ender


def _pot_odds(view):
    to_call, pot = view["to_call"], view["pot"]
    if to_call <= 0:
        return 0.0
    return to_call / (pot + to_call)


# ---------------------------------------------------------------------------
# Player 2 — "TAG Titan": tight-aggressive, position-aware value player.
# Opens strong ranges, sizes bets by pot, c-bets good boards, and releases
# marginal hands against real aggression.
# ---------------------------------------------------------------------------


class TagTitan:
    OPEN_THRESHOLD = 0.42      # preflop_strength needed to open-raise
    CALL_THRESHOLD = 0.34
    PREMIUM = 0.62

    def __init__(self):
        self.was_preflop_aggressor = False

    def reset(self, my_name, table_names):
        self.was_preflop_aggressor = False

    def act(self, view):
        if view["street"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        s = preflop_strength(view["hole"])
        bb = view["big_blind"]
        to_call = view["to_call"]
        facing_raise = view["current_bet"] > bb
        self.was_preflop_aggressor = False

        if s >= self.PREMIUM:
            self.was_preflop_aggressor = True
            return ("raise", max(3 * view["current_bet"], 3 * bb))
        if facing_raise:
            # continue only with real hands; commit fully with big pairs
            pot_odds = _pot_odds(view)
            if s >= 0.55 and to_call <= view["stack"] * 0.15:
                return ("call", 0)
            if s >= 0.5 and pot_odds < 0.25:
                return ("call", 0)
            return ("fold", 0)
        if s >= self.OPEN_THRESHOLD:
            self.was_preflop_aggressor = True
            return ("raise", 3 * bb)
        if s >= self.CALL_THRESHOLD and to_call <= bb:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        eq = view["equity"](30)
        pot = view["pot"]
        to_call = view["to_call"]
        rng = view["rng"]

        if to_call == 0:
            if eq > 0.68:
                return ("raise", max(view["min_raise"], int(pot * 0.66)))
            flushy, straighty = _board_texture(view["board"])
            if (self.was_preflop_aggressor and view["street"] == "flop"
                    and flushy < 3 and straighty < 2 and rng.random() < 0.55):
                return ("raise", max(view["min_raise"], int(pot * 0.5)))
            return ("call", 0)  # check
        need = _pot_odds(view)
        if eq > 0.75:
            return ("raise", view["my_committed"] + to_call + int(pot * 0.8))
        if eq > need + 0.08:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 3 — "LAG Loki": loose-aggressive trickster. Wide opens, frequent
# semi-bluffs with draws, randomized barrels, but folds garbage to big heat.
# ---------------------------------------------------------------------------


class LagLoki:
    def act(self, view):
        if view["street"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        s = preflop_strength(view["hole"])
        bb = view["big_blind"]
        rng = view["rng"]
        facing_raise = view["current_bet"] > bb
        if facing_raise:
            if s >= 0.6:
                return ("raise", 3 * view["current_bet"])  # 3-bet the goods
            r1 = card_rank(view["hole"][0])
            r2 = card_rank(view["hole"][1])
            has_ace_blocker = 14 in (r1, r2)
            if has_ace_blocker and rng.random() < 0.15 and \
                    view["to_call"] < view["stack"] * 0.2:
                return ("raise", 3 * view["current_bet"])  # light 3-bet
            if s >= 0.45 and _pot_odds(view) < 0.3:
                return ("call", 0)
            return ("fold", 0)
        if s >= 0.30 or rng.random() < 0.12:
            return ("raise", int(2.5 * bb))
        if view["to_call"] == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        rng = view["rng"]
        pot = view["pot"]
        to_call = view["to_call"]
        eq = view["equity"](25)
        flush_draw, open_ender = _my_draws(view["hole"], view["board"])
        has_draw = (flush_draw or open_ender) and view["street"] != "river"

        if to_call == 0:
            if eq > 0.62:
                return ("raise", max(view["min_raise"], int(pot * 0.75)))
            if has_draw and rng.random() < 0.7:
                return ("raise", max(view["min_raise"], int(pot * 0.6)))
            if rng.random() < 0.25:  # pure bluff stab
                return ("raise", max(view["min_raise"], int(pot * 0.5)))
            return ("call", 0)
        need = _pot_odds(view)
        if has_draw:
            # semi-bluff shove-ish raise sometimes, else use draw equity + implied odds
            if rng.random() < 0.3 and to_call < view["stack"] * 0.4:
                return ("raise", view["my_committed"] + to_call + int(pot * 0.9))
            if eq + 0.06 > need:
                return ("call", 0)
        if eq > 0.7:
            return ("raise", view["my_committed"] + to_call + int(pot * 0.9))
        if eq > need + 0.05:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 4 — "Nit Redwood": granite-tight rock. Plays only premiums deep,
# switches to a push/fold chart when short-stacked, never pays off big bets
# without the nuts-adjacent.
# ---------------------------------------------------------------------------


class NitRedwood:
    def act(self, view):
        if view["street"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        s = preflop_strength(view["hole"])
        bb = view["big_blind"]
        stack_bb = view["stack"] / bb if bb else 0
        if stack_bb < 10:  # short: push/fold
            if s >= 0.45:
                return ("raise", view["my_committed"] + view["stack"])
            return ("fold", 0)
        if s >= 0.7:  # QQ+/AK territory: raise big, happily get it in
            return ("raise", max(4 * view["big_blind"], 3 * view["current_bet"]))
        if s >= 0.6:
            if view["current_bet"] > 4 * bb:
                return ("fold", 0)
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        eq = view["equity"](30)
        to_call = view["to_call"]
        pot = view["pot"]
        if to_call == 0:
            if eq > 0.8:
                return ("raise", max(view["min_raise"], int(pot * 0.6)))
            return ("call", 0)
        need = _pot_odds(view)
        if eq > 0.85:
            return ("raise", view["my_committed"] + to_call + pot)
        if eq > need + 0.15:  # demands a big margin before paying anyone off
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 5 — "Professor Pot-Odds": pure math. Every decision is Monte-Carlo
# equity vs. price, with implied-odds credit for draws and value-raises
# sized to charge worse hands.
# ---------------------------------------------------------------------------


class ProfessorPotOdds:
    def act(self, view):
        pot = view["pot"]
        to_call = view["to_call"]
        bb = view["big_blind"]

        if view["street"] == "preflop":
            s = preflop_strength(view["hole"])
            eq_proxy = 0.25 + s * 0.55  # cheap preflop equity proxy
            if s >= 0.65:
                return ("raise", max(3 * bb, 3 * view["current_bet"]))
            if to_call == 0:
                if s >= 0.5:
                    return ("raise", 3 * bb)
                return ("call", 0)
            need = _pot_odds(view)
            big_bet = to_call > view["stack"] * 0.25
            margin = 0.12 if big_bet else 0.02
            if eq_proxy > need + margin:
                return ("call", 0)
            return ("fold", 0)

        eq = view["equity"](40)
        flush_draw, open_ender = _my_draws(view["hole"], view["board"])
        implied = 0.04 if (flush_draw or open_ender) and view["street"] != "river" else 0.0
        if to_call == 0:
            if eq > 0.6:
                # value bet sized so a caller pays a bad price
                return ("raise", max(view["min_raise"], int(pot * 0.7)))
            return ("call", 0)
        need = _pot_odds(view)
        if eq > 0.72 and view["num_opponents"] <= 2:
            return ("raise", view["my_committed"] + to_call + int(pot * 0.8))
        if eq + implied > need + 0.03:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Player 6 — "Chameleon": adaptive exploiter. Tracks every opponent's
# public behaviour (VPIP, aggression, shove frequency) and retunes its own
# thresholds: snap-calls maniacs wider, steals from nits, plays TAG baseline.
# ---------------------------------------------------------------------------


class Chameleon:
    def __init__(self):
        self.stats = {}
        self.me = None

    def reset(self, my_name, table_names):
        self.me = my_name
        self.stats = {n: {"acts": 0, "raises": 0, "shoves": 0, "folds": 0}
                      for n in table_names if n != my_name}

    def observe_action(self, actor, street, action, amount, to_call,
                       all_in, big_blind):
        if actor == self.me or actor not in self.stats:
            return
        st = self.stats[actor]
        if action in ("fold", "call", "check", "raise"):
            st["acts"] += 1
        if action == "raise":
            st["raises"] += 1
            if all_in:
                st["shoves"] += 1
        if action == "fold":
            st["folds"] += 1

    def _profile(self, name):
        st = self.stats.get(name)
        if not st or st["acts"] < 6:
            return "unknown"
        shove_rate = st["shoves"] / st["acts"]
        raise_rate = st["raises"] / st["acts"]
        fold_rate = st["folds"] / st["acts"]
        if shove_rate > 0.5:
            return "maniac"
        if raise_rate > 0.45:
            return "aggro"
        if fold_rate > 0.6:
            return "nit"
        return "normal"

    def _table_mood(self, view):
        """Profile of the biggest threat still in the hand (by recent raiser)."""
        for name, street, action, amount in reversed(view["history"]):
            if action == "raise" and name != self.me:
                return self._profile(name)
        return "normal"

    def act(self, view):
        if view["street"] == "preflop":
            return self._preflop(view)
        return self._postflop(view)

    def _preflop(self, view):
        s = preflop_strength(view["hole"])
        bb = view["big_blind"]
        to_call = view["to_call"]
        mood = self._table_mood(view)
        facing_raise = view["current_bet"] > bb

        if facing_raise and mood == "maniac":
            # a maniac's range is any-two: premium pairs/big aces print money
            r1, r2 = card_rank(view["hole"][0]), card_rank(view["hole"][1])
            pair_9plus = r1 == r2 and r1 >= 9
            big_ace = 14 in (r1, r2) and max(r1, r2) >= 14 and min(r1, r2) >= 10
            if pair_9plus or big_ace or s >= 0.6:
                return ("raise", view["my_committed"] + view["stack"])
            return ("fold", 0)
        if s >= 0.62:
            return ("raise", max(3 * bb, 3 * view["current_bet"]))
        if facing_raise:
            if s >= 0.52 and _pot_odds(view) < 0.28:
                return ("call", 0)
            return ("fold", 0)
        nits_behind = sum(1 for n in self.stats if self._profile(n) == "nit")
        steal_threshold = 0.40 - 0.04 * nits_behind  # steal wider vs nitty tables
        if s >= steal_threshold:
            return ("raise", int(2.5 * bb))
        if to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    def _postflop(self, view):
        eq = view["equity"](30)
        pot = view["pot"]
        to_call = view["to_call"]
        mood = self._table_mood(view)

        if to_call == 0:
            if eq > 0.65:
                return ("raise", max(view["min_raise"], int(pot * 0.66)))
            if mood == "nit" and view["rng"].random() < 0.4:
                return ("raise", max(view["min_raise"], int(pot * 0.5)))
            return ("call", 0)
        need = _pot_odds(view)
        # vs maniacs, big bets mean nothing: call down much lighter
        cushion = -0.05 if mood == "maniac" else 0.08
        if eq > 0.72:
            return ("raise", view["my_committed"] + to_call + int(pot * 0.8))
        if eq > need + cushion:
            return ("call", 0)
        return ("fold", 0)


ROSTER = [
    ("P1_YOLO_AllIn", YoloAllIn),
    ("P2_TAG_Titan", TagTitan),
    ("P3_LAG_Loki", LagLoki),
    ("P4_Nit_Redwood", NitRedwood),
    ("P5_Prof_PotOdds", ProfessorPotOdds),
    ("P6_Chameleon", Chameleon),
]
