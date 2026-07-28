#!/usr/bin/env python3
"""Texas Hold'em tournament simulator.

6 players, identical starting stacks, winner-take-all tournaments.
Player 1 goes all-in every time it acts. Players 2-6 run five distinct
elaborate strategies. No strategy can see another player's strategy —
only public actions.
"""

import random
from collections import deque
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}


def new_deck():
    return [r + s for r in RANKS for s in SUITS]


# ---------------------------------------------------------------------------
# Hand evaluation: returns comparable tuple, higher = better
# ---------------------------------------------------------------------------

def eval5(cards):
    vals = sorted((RANK_VAL[c[0]] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    counts = {}
    for v in vals:
        counts[v] = counts.get(v, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    distinct = sorted(counts, reverse=True)
    straight_high = 0
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_high = distinct[0]
        elif distinct == [14, 5, 4, 3, 2]:  # wheel
            straight_high = 5
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *vals)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        return (3, groups[0][0], *(kv[0] for kv in groups[1:]))
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2, groups[0][0], groups[1][0], groups[2][0])
    if groups[0][1] == 2:
        return (1, groups[0][0], *(kv[0] for kv in groups[1:]))
    return (0, *vals)


def eval7(cards):
    return max(eval5(c) for c in combinations(cards, 5))


def monte_carlo_equity(hole, community, n_opponents, iters=40, rng=random):
    """Estimate probability of winning at showdown vs random hands."""
    deck = [c for c in new_deck() if c not in hole and c not in community]
    need = 5 - len(community)
    wins = 0.0
    for _ in range(iters):
        sample = rng.sample(deck, need + 2 * n_opponents)
        board = community + sample[:need]
        mine = eval7(hole + board)
        best_opp = max(
            eval7(sample[need + 2 * i: need + 2 * i + 2] + board)
            for i in range(n_opponents)
        )
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / iters


def chen_score(hole):
    """Chen formula preflop hand strength."""
    a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
    va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
    base = {14: 10, 13: 8, 12: 7, 11: 6}.get(va, va / 2)
    if va == vb:
        return max(5, base * 2)
    score = base
    if a[1] == b[1]:
        score += 2
    gap = va - vb - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and va < 12:
        score += 1
    return score


# ---------------------------------------------------------------------------
# Strategies. Interface: act(view) -> ('fold',) | ('call',) | ('raise', to_amount)
# view keys: hole, community, pot, to_call, stack, committed, current_bet,
#            min_raise, big_blind, n_in_hand, n_at_table, position, street, rng
# observe(event) receives public events: (seat, street, kind) kind in
#            {'fold','call','check','raise','allin'}
# ---------------------------------------------------------------------------

class Strategy:
    name = "base"

    def act(self, view):
        raise NotImplementedError

    def observe(self, event):
        pass


class YoloAllIn(Strategy):
    """if my_turn then bet = All in fi"""
    name = "YOLO (all-in)"

    def act(self, view):
        return ("raise", view["stack"] + view["committed"])


class TheRock(Strategy):
    """Ultra-tight aggressive. Premium hands only preflop; postflop bets
    strong made hands hard and releases everything else."""
    name = "The Rock (tight-aggressive)"

    def act(self, view):
        rng = view["rng"]
        bb = view["big_blind"]
        to_call = view["to_call"]
        pot = view["pot"]
        stack = view["stack"]
        if view["street"] == "preflop":
            s = chen_score(view["hole"])
            if s >= 10:
                return ("raise", max(view["current_bet"] + view["min_raise"], 4 * bb))
            if s >= 8:
                return ("call",) if to_call <= stack * 0.15 else ("fold",)
            if s >= 6 and to_call <= bb:
                return ("call",)
            return ("check_or_fold",)
        strength = eval7(view["hole"] + view["community"])[0] if len(view["community"]) >= 3 else 0
        if strength >= 3:  # trips or better
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.8)))
        if strength == 2 or (strength == 1 and eval7(view["hole"] + view["community"])[1] >= 11):
            if to_call <= pot * 0.5:
                return ("call",)
            return ("fold",)
        if to_call == 0 and strength >= 1 and rng.random() < 0.5:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.5)))
        return ("check_or_fold",)


class LooseCannon(Strategy):
    """Loose-aggressive: plays wide in position, semi-bluffs draws,
    fires random barrels to punish passivity."""
    name = "Loose Cannon (LAG)"

    def _draws(self, hole, community):
        cards = hole + community
        suits = {}
        for c in cards:
            suits[c[1]] = suits.get(c[1], 0) + 1
        flush_draw = any(n == 4 for n in suits.values())
        vals = sorted({RANK_VAL[c[0]] for c in cards})
        oesd = any(
            len([v for v in vals if lo <= v <= lo + 4]) >= 4
            for lo in range(2, 11)
        )
        return flush_draw or oesd

    def act(self, view):
        rng = view["rng"]
        bb = view["big_blind"]
        to_call = view["to_call"]
        pot = view["pot"]
        late = view["position"] >= view["n_at_table"] - 2
        if view["street"] == "preflop":
            s = chen_score(view["hole"])
            thresh = 5 if late else 7
            if s >= thresh + 3 or (late and rng.random() < 0.15):
                return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
            if s >= thresh and to_call <= view["stack"] * 0.1:
                return ("call",)
            return ("check_or_fold",)
        strength = eval7(view["hole"] + view["community"])[0]
        drawing = view["street"] != "river" and self._draws(view["hole"], view["community"])
        if strength >= 2:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.7)))
        if drawing:
            if to_call == 0 and rng.random() < 0.6:
                return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.6)))
            if to_call <= pot * 0.35:
                return ("call",)
            return ("fold",)
        if strength == 1:
            return ("call",) if to_call <= pot * 0.3 else ("check_or_fold",)
        if to_call == 0 and late and rng.random() < 0.25:  # stab
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.5)))
        return ("check_or_fold",)


class TheProfessor(Strategy):
    """Pure math: Monte Carlo equity vs pot odds, raises when equity
    comfortably exceeds the price."""
    name = "The Professor (equity/pot-odds)"

    def act(self, view):
        rng = view["rng"]
        n_opp = view["n_in_hand"] - 1
        to_call = view["to_call"]
        pot = view["pot"]
        if view["street"] == "preflop":
            s = chen_score(view["hole"])
            equity = min(0.85, 0.30 + s * 0.045 - 0.03 * (n_opp - 1))
        else:
            equity = monte_carlo_equity(
                view["hole"], view["community"], n_opp, iters=40, rng=rng
            )
        if to_call == 0:
            if equity > 0.55 + 0.05 * (n_opp - 1):
                bet = view["current_bet"] + max(view["min_raise"], int(pot * 0.75))
                return ("raise", bet)
            return ("check_or_fold",)
        pot_odds = to_call / (pot + to_call)
        if equity > pot_odds + 0.22:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.8)))
        if equity > pot_odds + 0.03:
            return ("call",)
        return ("fold",)


class TheChameleon(Strategy):
    """Opponent modeler: tracks each seat's aggression/fold tendencies from
    public actions and exploits — tightens vs maniacs, steals from nits."""
    name = "The Chameleon (opponent modeler)"

    def __init__(self):
        self.stats = {}  # seat -> {'aggr': n, 'passive': n, 'folds': n, 'hands': n}

    def observe(self, event):
        seat, street, kind = event
        st = self.stats.setdefault(seat, {"aggr": 0, "passive": 0, "folds": 0})
        if kind in ("raise", "allin"):
            st["aggr"] += 1
        elif kind in ("call", "check"):
            st["passive"] += 1
        elif kind == "fold":
            st["folds"] += 1

    def _table_aggression(self):
        a = sum(s["aggr"] for s in self.stats.values())
        p = sum(s["passive"] + s["folds"] for s in self.stats.values())
        return a / max(1, a + p)

    def act(self, view):
        rng = view["rng"]
        bb = view["big_blind"]
        to_call = view["to_call"]
        pot = view["pot"]
        aggr = self._table_aggression()
        wild_table = aggr > 0.35
        if view["street"] == "preflop":
            s = chen_score(view["hole"])
            # vs maniacs: tighten up and trap; vs nits: steal wide
            if wild_table:
                if s >= 10:
                    return ("call",) if to_call <= view["stack"] * 0.5 else ("raise", view["stack"] + view["committed"])
                if s >= 9 and to_call <= 3 * bb:
                    return ("call",)
                return ("check_or_fold",)
            if s >= 9:
                return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
            if s >= 6 and to_call <= 2 * bb:
                return ("call",)
            if to_call == 0 or (to_call <= bb and rng.random() < 0.4):
                return ("call",) if to_call else ("check_or_fold",)
            return ("check_or_fold",)
        strength = eval7(view["hole"] + view["community"])[0]
        if strength >= 3:
            if wild_table and to_call == 0 and rng.random() < 0.5:
                return ("check_or_fold",)  # trap
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.75)))
        if strength >= 1:
            if to_call <= pot * (0.25 if wild_table else 0.45):
                return ("call",)
            return ("fold",)
        if not wild_table and to_call == 0 and rng.random() < 0.35:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.5)))
        return ("check_or_fold",)


class TheSurvivor(Strategy):
    """Tournament stack strategist: push/fold when short, pressure medium
    stacks when big, avoids marginal spots — survival first."""
    name = "The Survivor (stack/ICM)"

    def act(self, view):
        rng = view["rng"]
        bb = view["big_blind"]
        to_call = view["to_call"]
        pot = view["pot"]
        m_ratio = view["stack"] / max(1, bb * 1.5)  # rough M
        s = chen_score(view["hole"]) if view["street"] == "preflop" else None
        if view["street"] == "preflop":
            if m_ratio < 5:  # short: push or fold
                push_thresh = 5 if view["n_in_hand"] <= 3 else 7
                if s >= push_thresh:
                    return ("raise", view["stack"] + view["committed"])
                return ("check_or_fold",)
            if m_ratio < 10:
                if s >= 9:
                    return ("raise", max(view["current_bet"] + view["min_raise"], 3 * bb))
                if s >= 7 and to_call <= 2 * bb:
                    return ("call",)
                return ("check_or_fold",)
            # healthy stack: solid values, pressure only cheaply
            if s >= 9:
                return ("raise", max(view["current_bet"] + view["min_raise"], int(2.5 * bb)))
            if s >= 6 and to_call <= 2 * bb:
                return ("call",)
            return ("check_or_fold",)
        strength = eval7(view["hole"] + view["community"])[0]
        committed_frac = to_call / max(1, view["stack"])
        if strength >= 3:
            return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.7)))
        if strength == 2:
            return ("call",) if committed_frac < 0.35 else ("fold",)
        if strength == 1:
            if to_call == 0:
                if rng.random() < 0.4:
                    return ("raise", view["current_bet"] + max(view["min_raise"], int(pot * 0.4)))
                return ("check_or_fold",)
            return ("call",) if committed_frac < 0.12 else ("fold",)
        return ("check_or_fold",)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = []
        self.committed_hand = 0
        self.committed_street = 0
        self.folded = False
        self.all_in = False

    @property
    def alive(self):
        return self.stack > 0 or self.all_in or self.committed_hand > 0


class Tournament:
    def __init__(self, strategies, rng, start_stack=1000, sb=10,
                 blind_double_every=12, max_hands=600):
        self.rng = rng
        self.players = [
            Player(i + 1, f"P{i + 1}", strat, start_stack)
            for i, strat in enumerate(strategies)
        ]
        self.sb0 = sb
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.button = rng.randrange(len(self.players))

    def run(self):
        hand_no = 0
        while True:
            live = [p for p in self.players if p.stack > 0]
            if len(live) == 1:
                return live[0].seat
            if hand_no >= self.max_hands:
                return max(live, key=lambda p: p.stack).seat
            level = hand_no // self.blind_double_every
            sb = self.sb0 * (2 ** min(level, 12))
            self.play_hand(live, sb, sb * 2)
            hand_no += 1

    def broadcast(self, seat, street, kind):
        for p in self.players:
            if p.seat != seat:
                p.strategy.observe((seat, street, kind))

    def play_hand(self, live, sb, bb):
        rng = self.rng
        deck = new_deck()
        rng.shuffle(deck)
        for p in live:
            p.hole = [deck.pop(), deck.pop()]
            p.committed_hand = 0
            p.committed_street = 0
            p.folded = False
            p.all_in = False
        community = []

        self.button = self._next_seat_idx(self.button, live)
        order = self._order_from(live, self.button)
        n = len(live)
        if n == 2:
            sb_p, bb_p = order[0], order[1]  # heads-up: button posts SB
        else:
            sb_p, bb_p = order[1], order[2]
        self._commit(sb_p, min(sb, sb_p.stack))
        self._commit(bb_p, min(bb, bb_p.stack))
        current_bet = bb

        streets = [("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)]
        for si, (street, ncards) in enumerate(streets):
            for _ in range(ncards):
                community.append(deck.pop())
            if street == "preflop":
                first = order.index(bb_p) + 1
                acting = order[first % n:] + order[:first % n]
            else:
                acting = order[1:] + order[:1]  # first to act left of button
                acting = [p for p in acting if not p.folded and not p.all_in]
                current_bet = 0
                for p in live:
                    p.committed_street = 0
            contenders = [p for p in live if not p.folded]
            if street == "preflop" or len([p for p in contenders if not p.all_in]) > 1:
                self._betting_round(live, acting, street, community, current_bet, bb)
            contenders = [p for p in live if not p.folded]
            if len(contenders) == 1:
                break

        # showdown / award
        while len(community) < 5 and len([p for p in live if not p.folded]) > 1:
            community.append(deck.pop())
        self._award(live, community)

    def _betting_round(self, live, acting, street, community, current_bet, bb):
        rng = self.rng
        min_raise = bb
        queue = deque(p for p in acting if not p.folded and not p.all_in and p.stack > 0)
        while queue:
            p = queue.popleft()
            if p.folded or p.all_in:
                continue
            contenders = [q for q in live if not q.folded]
            if len(contenders) == 1:
                break
            to_call = current_bet - p.committed_street
            pot = sum(q.committed_hand for q in live)
            view = {
                "hole": p.hole,
                "community": list(community),
                "pot": pot,
                "to_call": to_call,
                "stack": p.stack,
                "committed": p.committed_street,
                "current_bet": current_bet,
                "min_raise": min_raise,
                "big_blind": bb,
                "n_in_hand": len(contenders),
                "n_at_table": len(live),
                "position": self._position(p, live),
                "street": street,
                "rng": rng,
            }
            action = p.strategy.act(view)
            kind = action[0]
            if kind == "check_or_fold":
                kind = "call" if to_call == 0 else "fold"
                action = (kind,)
            if kind == "fold":
                if to_call == 0:
                    action = ("call",)
                    kind = "call"
                else:
                    p.folded = True
                    self.broadcast(p.seat, street, "fold")
                    continue
            if kind == "call":
                pay = min(to_call, p.stack)
                self._commit(p, pay)
                self.broadcast(
                    p.seat, street,
                    "allin" if p.all_in else ("check" if to_call == 0 else "call"),
                )
                continue
            # raise
            target = action[1]
            max_target = p.committed_street + p.stack
            target = min(target, max_target)
            legal_min = current_bet + min_raise
            if target < legal_min and target < max_target:
                # can't legally raise: treat as call
                pay = min(to_call, p.stack)
                self._commit(p, pay)
                self.broadcast(p.seat, street, "call")
                continue
            if target <= current_bet:
                pay = min(to_call, p.stack)
                self._commit(p, pay)
                self.broadcast(p.seat, street, "call")
                continue
            raise_size = target - current_bet
            self._commit(p, target - p.committed_street)
            if raise_size >= min_raise:
                min_raise = raise_size
            current_bet = target
            self.broadcast(p.seat, street, "allin" if p.all_in else "raise")
            for q in live:
                if (
                    q is not p and not q.folded and not q.all_in and q.stack > 0
                    and q.committed_street < current_bet and q not in queue
                ):
                    queue.append(q)
        return current_bet

    def _commit(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.committed_hand += amount
        p.committed_street += amount
        if p.stack == 0:
            p.all_in = True

    def _position(self, p, live):
        order = self._order_from(live, self.button)
        return order.index(p)

    def _order_from(self, live, button_idx):
        idxs = [i for i, q in enumerate(self.players) if q in live]
        # rotate so that first element is the button among live players
        if button_idx in idxs:
            start = idxs.index(button_idx)
        else:
            later = [i for i in idxs if i > button_idx]
            start = idxs.index(later[0]) if later else 0
        ordered = idxs[start:] + idxs[:start]
        return [self.players[i] for i in ordered]

    def _next_seat_idx(self, button_idx, live):
        idxs = [i for i, q in enumerate(self.players) if q in live]
        later = [i for i in idxs if i > button_idx]
        return later[0] if later else idxs[0]

    def _award(self, live, community):
        contenders = [p for p in live if not p.folded]
        if len(contenders) == 1:
            contenders[0].stack += sum(p.committed_hand for p in live)
            return
        scores = {p.seat: eval7(p.hole + community) for p in contenders}
        # side pots by committed levels
        levels = sorted({p.committed_hand for p in live if p.committed_hand > 0})
        prev = 0
        for lvl in levels:
            pot = 0
            eligible = []
            for p in live:
                chunk = min(p.committed_hand, lvl) - prev
                if chunk > 0:
                    pot += chunk
                if p.committed_hand >= lvl and not p.folded:
                    eligible.append(p)
            if pot == 0:
                prev = lvl
                continue
            best = max(scores[p.seat] for p in eligible)
            winners = [p for p in eligible if scores[p.seat] == best]
            share = pot // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += pot - share * len(winners)
            prev = lvl


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

STRATEGY_FACTORIES = [
    YoloAllIn,       # Player 1
    TheRock,         # Player 2
    LooseCannon,     # Player 3
    TheProfessor,    # Player 4
    TheChameleon,    # Player 5
    TheSurvivor,     # Player 6
]


def run_sims(n_sims=100, seed=42):
    master = random.Random(seed)
    wins = {i: 0 for i in range(1, 7)}
    for sim in range(n_sims):
        rng = random.Random(master.randrange(2 ** 63))
        strategies = [f() for f in STRATEGY_FACTORIES]
        t = Tournament(strategies, rng)
        winner = t.run()
        wins[winner] += 1
    return wins


def histogram(wins, n_sims):
    names = {i + 1: f() .name for i, f in enumerate(STRATEGY_FACTORIES)}
    width = 50
    lines = []
    lines.append(f"WINNER HISTOGRAM — {n_sims} tournaments (winner-take-all)")
    lines.append("=" * 78)
    top = max(wins.values()) or 1
    for seat in range(1, 7):
        n = wins[seat]
        bar = "█" * round(width * n / top)
        lines.append(f"P{seat} {names[seat]:<32} {bar} {n}")
    lines.append("=" * 78)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    wins = run_sims(n)
    print(histogram(wins, n))
