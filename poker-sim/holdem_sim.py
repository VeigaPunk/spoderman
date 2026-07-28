"""No-limit Texas Hold'em tournament simulator.

6 players, identical starting stacks. Players 2-6 run elaborate strategies
(TAG, LAG, pot-odds mathematician, positional thief, adaptive profiler).
Player 1 runs the galaxy-brain strategy: if my_turn then bet = ALL IN fi.
No strategy can see another's code — they only observe table actions.
"""

import random
import sys
from collections import Counter, deque

RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
SUIT_NAMES = "shdc"


def make_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


def card_str(c):
    r = RANK_NAMES.get(c[0], str(c[0]))
    return f"{r}{SUIT_NAMES[c[1]]}"


# ---------------------------------------------------------------- evaluator

def _straight_high(rank_set):
    rs = set(rank_set)
    if 14 in rs:
        rs.add(1)
    for high in range(14, 4, -1):
        if all(high - i in rs for i in range(5)):
            return high
    return 0


def eval7(cards):
    """Best 5-card hand from 7 cards -> comparable tuple (higher wins)."""
    ranks = [c[0] for c in cards]
    rc = Counter(ranks)
    sc = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in sc.items() if n >= 5), None)

    if flush_suit is not None:
        franks = [c[0] for c in cards if c[1] == flush_suit]
        sf = _straight_high(franks)
        if sf:
            return (8, sf)

    groups = sorted(rc.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in rc if r != quad)
        return (7, quad, kicker)

    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_suit is not None:
        top5 = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)[:5]
        return (5, *top5)

    st = _straight_high(rc.keys())
    if st:
        return (4, st)

    if groups[0][1] == 3:
        t = groups[0][0]
        kick = sorted((r for r in rc if r != t), reverse=True)[:2]
        return (3, t, *kick)

    if groups[0][1] == 2 and groups[1][1] == 2:
        pairs = sorted((r for r, n in rc.items() if n == 2), reverse=True)
        kicker = max(r for r in rc if r not in pairs[:2])
        return (2, pairs[0], pairs[1], kicker)

    if groups[0][1] == 2:
        p = groups[0][0]
        kick = sorted((r for r in rc if r != p), reverse=True)[:3]
        return (1, p, *kick)

    return (0, *sorted(set(ranks), reverse=True)[:5])


# ---------------------------------------------------------------- hand math

def chen_score(hole):
    """Chen formula preflop hand strength (roughly -1 .. 20)."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    base = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    pts = base
    if s1 == s2:
        pts += 2
    gap = hi - lo - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        pts += 1
    return pts


def mc_equity(hole, community, n_opps, trials, rng):
    """Monte Carlo equity of `hole` vs n_opps random hands."""
    used = set(hole) | set(community)
    deck = [c for c in make_deck() if c not in used]
    need_board = 5 - len(community)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, 2 * n_opps + need_board)
        board = list(community) + draw[:need_board]
        mine = eval7(list(hole) + board)
        best_opp = None
        for i in range(n_opps):
            oh = draw[need_board + 2 * i: need_board + 2 * i + 2]
            v = eval7(oh + board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / trials


# ---------------------------------------------------------------- strategies

class Strategy:
    name = "base"

    def act(self, view):
        raise NotImplementedError


class AllInBot(Strategy):
    """if my_turn then bet = All in fi"""
    name = "ALL-IN GREMLIN"

    def act(self, view):
        return ("raise", view["my_street_bet"] + view["stack"])


class TAGStrategy(Strategy):
    """Tight-aggressive: premium hands only, played fast.

    Preflop via Chen formula with position-tightened thresholds; postflop
    bets/raises strong equity, folds marginal spots to aggression.
    """
    name = "TAG Terminator"

    def act(self, view):
        rng = view["rng"]
        pot, to_call, bb = view["pot"], view["to_call"], view["bb"]
        stack = view["stack"]

        if view["street"] == "preflop":
            score = chen_score(view["hole"])
            open_thr = 8.5 if view["pos_frac"] < 0.5 else 7.0
            facing_big = to_call > 3 * bb
            if facing_big:
                need = 10 if to_call < stack * 0.5 else 11
                if score >= need:
                    return ("raise", view["my_street_bet"] + stack)
                return ("fold",)
            if score >= open_thr + 2:
                return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
            if score >= open_thr:
                return ("call",)
            if to_call == 0:
                return ("call",)
            return ("fold",)

        eq = view["equity"]()
        if eq > 0.80:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.9)))
        if eq > 0.62:
            if to_call <= pot * 0.75 or to_call >= stack:
                if to_call == 0 and rng.random() < 0.7:
                    return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.6)))
                return ("call",)
            return ("fold",)
        if to_call == 0:
            return ("call",)
        if eq > 0.45 and to_call <= pot * 0.25:
            return ("call",)
        return ("fold",)


class LAGStrategy(Strategy):
    """Loose-aggressive: wide ranges, relentless pressure, timed bluffs.

    Semi-bluffs draws, fires random barrels, but can release when the math
    is hopeless against big bets.
    """
    name = "LAG Lunatic"

    def act(self, view):
        rng = view["rng"]
        pot, to_call, bb = view["pot"], view["to_call"], view["bb"]
        stack = view["stack"]

        if view["street"] == "preflop":
            score = chen_score(view["hole"])
            if to_call > 4 * bb:
                if score >= 9.5 or (score >= 8 and to_call < stack * 0.25):
                    return ("call",) if rng.random() < 0.6 else ("raise", view["my_street_bet"] + stack)
                return ("fold",)
            if score >= 7 or rng.random() < 0.25:
                if rng.random() < 0.55:
                    return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
                return ("call",)
            if score >= 5 or to_call == 0:
                return ("call",)
            return ("fold",)

        eq = view["equity"]()
        bluffing = rng.random() < 0.18
        if eq > 0.72 or (bluffing and to_call == 0):
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * (0.5 + rng.random() * 0.5))))
        if 0.34 <= eq <= 0.55 and rng.random() < 0.35 and to_call < pot:
            # semi-bluff the draw
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.7)))
        if eq > 0.5:
            if to_call <= pot or to_call >= stack * 0.9:
                return ("call",)
            return ("fold",)
        if to_call == 0:
            return ("call",)
        if eq > 0.30 and to_call <= pot * 0.4:
            return ("call",)
        return ("fold",)


class PotOddsStrategy(Strategy):
    """The mathematician: pure equity-vs-pot-odds machine.

    Calls exactly when equity beats price, value-raises big edges, never
    tilts, never bluffs, feels nothing.
    """
    name = "PotOdds Professor"

    def act(self, view):
        pot, to_call = view["pot"], view["to_call"]
        stack, bb = view["stack"], view["bb"]

        if view["street"] == "preflop":
            score = chen_score(view["hole"])
            eq_est = min(0.85, 0.30 + score * 0.035)
        else:
            eq_est = view["equity"]()

        if to_call == 0:
            if eq_est > 0.70:
                return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.75) or 2 * bb))
            return ("call",)

        pot_odds = to_call / (pot + to_call)
        edge = eq_est - pot_odds
        if edge > 0.22 and eq_est > 0.65:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.8)))
        if edge > 0.03:
            return ("call",)
        return ("fold",)


class PositionStrategy(Strategy):
    """Positional predator: tight up front, a thief on the button.

    Steals unopened pots from late position, c-bets as the aggressor,
    surrenders out of position without real equity.
    """
    name = "Position Vulture"

    def act(self, view):
        rng = view["rng"]
        pot, to_call, bb = view["pot"], view["to_call"], view["bb"]
        stack = view["stack"]
        late = view["pos_frac"] >= 0.6  # closer to the button

        if view["street"] == "preflop":
            score = chen_score(view["hole"])
            unopened = view["current_bet"] <= bb
            if to_call > 4 * bb:
                if score >= 10.5:
                    return ("raise", view["my_street_bet"] + stack)
                return ("fold",)
            if late and unopened and (score >= 5.5 or rng.random() < 0.3):
                return ("raise", max(view["current_bet"] + view["min_raise"], int(2.5 * bb)))
            thr = 6.5 if late else 9.0
            if score >= thr + 2:
                return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
            if score >= thr:
                return ("call",)
            if to_call == 0:
                return ("call",)
            return ("fold",)

        eq = view["equity"]()
        was_aggressor = view["i_was_last_aggressor"]
        if eq > 0.75:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.8)))
        if to_call == 0:
            if was_aggressor and (eq > 0.4 or rng.random() < 0.5):
                return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.55)))
            if late and rng.random() < 0.3:
                return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.5)))
            return ("call",)
        if eq > 0.58 and to_call <= pot:
            return ("call",)
        if late and eq > 0.48 and to_call <= pot * 0.5:
            return ("call",)
        return ("fold",)


class AdaptiveStrategy(Strategy):
    """Profiling shark: tracks every villain's aggression frequency.

    Tightens up against nits, calls down maniacs light (hello, player 1),
    and switches to push/fold when short-stacked.
    """
    name = "Adaptive Shark"

    def act(self, view):
        pot, to_call, bb = view["pot"], view["to_call"], view["bb"]
        stack = view["stack"]
        stats = view["stats"]
        aggressor = view["last_aggressor"]

        maniac = False
        if aggressor is not None and aggressor != view["my_id"]:
            s = stats.get(aggressor)
            if s and s["actions"] >= 8:
                maniac = s["raises"] / s["actions"] > 0.6

        # short stack: push/fold
        if stack <= 10 * bb and view["street"] == "preflop":
            score = chen_score(view["hole"])
            if score >= (5.5 if maniac else 7.5):
                return ("raise", view["my_street_bet"] + stack)
            if to_call == 0:
                return ("call",)
            return ("fold",)

        if view["street"] == "preflop":
            score = chen_score(view["hole"])
            if to_call > 3 * bb:
                need = 8.0 if maniac else 10.5
                if score >= need:
                    return ("raise", view["my_street_bet"] + stack)
                return ("fold",)
            if score >= 9:
                return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
            if score >= 6.5:
                return ("call",)
            if to_call == 0:
                return ("call",)
            return ("fold",)

        eq = view["equity"]()
        call_thr = 0.42 if maniac else 0.58
        if eq > 0.78:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.85)))
        if to_call == 0:
            if eq > 0.6:
                return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.6)))
            return ("call",)
        pot_odds = to_call / (pot + to_call)
        if eq > max(call_thr, pot_odds + 0.02):
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------- engine

class PlayerState:
    def __init__(self, pid, name, strategy, stack):
        self.id = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.reset_hand()

    def reset_hand(self):
        self.hole = None
        self.folded = False
        self.all_in = False
        self.street_bet = 0
        self.total_contrib = 0

    @property
    def in_hand(self):
        return not self.folded


class Tournament:
    START_STACK = 1000
    BASE_SB = 5
    BLIND_LEVEL_HANDS = 25
    MAX_HANDS = 1500

    def __init__(self, players, seed):
        self.rng = random.Random(seed)
        self.players = players
        self.stats = {p.id: {"actions": 0, "raises": 0} for p in players}
        self.hand_no = 0

    def blinds(self):
        level = self.hand_no // self.BLIND_LEVEL_HANDS
        sb = self.BASE_SB * (2 ** min(level, 12))
        return sb, sb * 2

    def run(self):
        alive = list(self.players)
        btn = 0
        while len(alive) > 1 and self.hand_no < self.MAX_HANDS:
            self.play_hand(alive, btn % len(alive))
            survivors = [p for p in alive if p.stack > 0]
            if len(survivors) < len(alive):
                btn_player = alive[btn % len(alive)]
                alive = survivors
                if btn_player in alive:
                    btn = alive.index(btn_player)
            btn = (btn + 1) % max(len(alive), 1)
            self.hand_no += 1
        return max(alive, key=lambda p: p.stack)

    # -- one hand ---------------------------------------------------------
    def play_hand(self, alive, btn):
        n = len(alive)
        sb_amt, bb_amt = self.blinds()
        for p in alive:
            p.reset_hand()

        deck = make_deck()
        self.rng.shuffle(deck)
        for p in alive:
            p.hole = (deck.pop(), deck.pop())

        if n == 2:
            sb_pos, bb_pos = btn, (btn + 1) % n
        else:
            sb_pos, bb_pos = (btn + 1) % n, (btn + 2) % n
        self._pay(alive[sb_pos], sb_amt)
        self._pay(alive[bb_pos], bb_amt)

        self.community = []
        self.last_aggressor = None
        self._equity_cache = {}
        self.btn = btn
        self.alive_order = alive

        first_preflop = sb_pos if n == 2 else (bb_pos + 1) % n
        first_postflop = bb_pos if n == 2 else (btn + 1) % n

        self._betting_round(alive, first_preflop, bb_amt, preflop=True)
        for burn_count, street in ((3, "flop"), (1, "turn"), (1, "river")):
            if self._hand_over(alive):
                break
            self.community.extend(deck.pop() for _ in range(burn_count))
            self._equity_cache = {}
            if self._live_count(alive) > 1:
                self._betting_round(alive, first_postflop, bb_amt, preflop=False)

        # run out the board if betting closed early via all-ins
        while len(self.community) < 5 and self._in_hand_count(alive) > 1:
            self.community.append(deck.pop())

        self._award_pots(alive)

    def _pay(self, p, amount):
        amt = min(amount, p.stack)
        p.stack -= amt
        p.street_bet += amt
        p.total_contrib += amt
        if p.stack == 0:
            p.all_in = True
        return amt

    def _in_hand_count(self, alive):
        return sum(1 for p in alive if p.in_hand)

    def _live_count(self, alive):
        return sum(1 for p in alive if p.in_hand and not p.all_in)

    def _hand_over(self, alive):
        return self._in_hand_count(alive) <= 1

    def _betting_round(self, alive, first, bb_amt, preflop):
        n = len(alive)
        if not preflop:
            for p in alive:
                p.street_bet = 0
        current_bet = max(p.street_bet for p in alive)
        min_raise = bb_amt
        raise_count = 0

        order = [alive[(first + i) % n] for i in range(n)]
        to_act = deque(p for p in order if p.in_hand and not p.all_in)

        while to_act:
            p = to_act.popleft()
            if p.folded or p.all_in or self._in_hand_count(alive) <= 1:
                continue
            to_call = current_bet - p.street_bet
            view = self._make_view(p, alive, current_bet, min_raise, bb_amt, preflop)
            try:
                action = p.strategy.act(view)
            except Exception:
                action = ("fold",) if to_call > 0 else ("call",)

            self.stats[p.id]["actions"] += 1
            kind = action[0]

            if kind == "raise" and raise_count >= 8:
                kind = "call"
            if kind == "raise":
                target = int(action[1])
                max_target = p.street_bet + p.stack
                target = min(target, max_target)
                if target <= current_bet:
                    kind = "call"
                else:
                    full_min = current_bet + min_raise
                    if target < full_min and target < max_target:
                        target = min(full_min, max_target)
                    self._pay(p, target - p.street_bet)
                    if p.street_bet > current_bet:
                        raise_size = p.street_bet - current_bet
                        min_raise = max(min_raise, raise_size)
                        current_bet = p.street_bet
                        self.last_aggressor = p.id
                        self.stats[p.id]["raises"] += 1
                        raise_count += 1
                        idx = alive.index(p)
                        to_act = deque(
                            q for i in range(1, n)
                            for q in [alive[(idx + i) % n]]
                            if q.in_hand and not q.all_in
                        )
                    continue

            if kind == "call":
                if to_call > 0:
                    self._pay(p, to_call)
                continue

            if to_call == 0:
                continue  # treat bad fold as check
            p.folded = True

    def _make_view(self, p, alive, current_bet, min_raise, bb_amt, preflop):
        pot = sum(q.total_contrib for q in alive)
        n = len(alive)
        seat = alive.index(p)
        dist_from_btn = (seat - self.btn) % n  # 0 = button
        pos_frac = 1.0 if n == 1 else (
            ((dist_from_btn - 1) % n) / (n - 1) if n > 1 else 1.0
        )

        def equity(trials=40):
            key = p.id
            if key not in self._equity_cache:
                n_opps = min(max(self._in_hand_count(alive) - 1, 1), 3)
                self._equity_cache[key] = mc_equity(
                    p.hole, self.community, n_opps, trials, self.rng)
            return self._equity_cache[key]

        return {
            "my_id": p.id,
            "hole": p.hole,
            "community": list(self.community),
            "street": "preflop" if preflop else ("flop", "turn", "river")[len(self.community) - 3],
            "pot": pot,
            "to_call": current_bet - p.street_bet,
            "current_bet": current_bet,
            "min_raise": min_raise,
            "my_street_bet": p.street_bet,
            "stack": p.stack,
            "bb": bb_amt,
            "pos_frac": pos_frac,
            "n_active": self._in_hand_count(alive),
            "stats": self.stats,
            "last_aggressor": self.last_aggressor,
            "i_was_last_aggressor": self.last_aggressor == p.id,
            "equity": equity,
            "rng": self.rng,
        }

    def _award_pots(self, alive):
        contribs = {p: p.total_contrib for p in alive if p.total_contrib > 0}
        if not contribs:
            return
        # refund uncalled portion of the biggest bet
        amounts = sorted(contribs.values(), reverse=True)
        if len(amounts) >= 2 and amounts[0] > amounts[1]:
            top = max(contribs, key=lambda q: contribs[q])
            refund = amounts[0] - amounts[1]
            contribs[top] -= refund
            top.stack += refund
            top.total_contrib -= refund

        in_hand = [p for p in alive if p.in_hand]
        if len(in_hand) == 1:
            in_hand[0].stack += sum(contribs.values())
            return

        showdown = {p: eval7(list(p.hole) + self.community)
                    for p in contribs if p.in_hand}

        while any(v > 0 for v in contribs.values()):
            m = min(v for v in contribs.values() if v > 0)
            pot_amount = 0
            eligible = []
            for q in contribs:
                if contribs[q] > 0:
                    contribs[q] -= m
                    pot_amount += m
                    if q.in_hand:
                        eligible.append(q)
            if not eligible:
                continue
            best = max(showdown[q] for q in eligible)
            winners = [q for q in eligible if showdown[q] == best]
            share = pot_amount // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += pot_amount - share * len(winners)


# ---------------------------------------------------------------- runner

STRATEGY_LINEUP = [
    (1, AllInBot),
    (2, TAGStrategy),
    (3, LAGStrategy),
    (4, PotOddsStrategy),
    (5, PositionStrategy),
    (6, AdaptiveStrategy),
]


def run_sims(n_sims=100, base_seed=42):
    wins = Counter()
    names = {}
    for sim in range(n_sims):
        players = []
        for pid, cls in STRATEGY_LINEUP:
            strat = cls()
            names[pid] = strat.name
            players.append(PlayerState(pid, f"P{pid} {strat.name}",
                                       strat, Tournament.START_STACK))
        t = Tournament(players, seed=base_seed + sim)
        winner = t.run()
        wins[winner.id] += 1
        done = sim + 1
        if done % 10 == 0:
            print(f"  ... {done}/{n_sims} tournaments done", flush=True)
    return wins, names


def print_histogram(wins, names, n_sims):
    print()
    print("=" * 66)
    print(f" WINNER WINNER CHICKEN DINNER — tournament victories / {n_sims} sims")
    print("=" * 66)
    max_w = max(wins.values()) if wins else 1
    for pid, _ in STRATEGY_LINEUP:
        w = wins.get(pid, 0)
        bar = "█" * round(w * 50 / max_w)
        print(f" P{pid} {names[pid]:<18} {w:>3} ({w * 100 // n_sims:>2}%) |{bar}")
    print("=" * 66)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    print(f"Running {n} six-player NLHE tournaments (1000 chips each, "
          f"blinds 5/10 doubling every 25 hands)...")
    wins, names = run_sims(n)
    print_histogram(wins, names, n)
