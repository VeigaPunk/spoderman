"""Texas Hold'em tournament simulator.

6 players, identical starting stacks, winner-take-all tournaments.
Players 2-6 run elaborate strategies; Player 1 runs:

    if my_turn:
        bet = ALL_IN
    fi

No player knows any other player's strategy.
"""

import itertools
import random
import sys
import time
from collections import Counter, defaultdict

RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}
SUITS = "shdc"
FULL_DECK = [r + s for r in RANKS for s in SUITS]

HAND_NAMES = [
    "High Card", "Pair", "Two Pair", "Trips", "Straight",
    "Flush", "Full House", "Quads", "Straight Flush",
]


# ---------------------------------------------------------------- evaluator

def _straight_high(vals):
    uv = sorted(set(vals), reverse=True)
    if 14 in uv:
        uv.append(1)
    run = 1
    for i in range(1, len(uv)):
        if uv[i] == uv[i - 1] - 1:
            run += 1
            if run >= 5:
                return uv[i] + 4
        else:
            run = 1
    return 0


def eval7(cards):
    """Best 5-card rank from 5-7 cards, as a comparable tuple."""
    vals = sorted((RANK_VAL[c[0]] for c in cards), reverse=True)
    suits = defaultdict(list)
    for c in cards:
        suits[c[1]].append(RANK_VAL[c[0]])
    flush = None
    for vs in suits.values():
        if len(vs) >= 5:
            flush = sorted(vs, reverse=True)
    if flush:
        sf = _straight_high(flush)
        if sf:
            return (8, sf)
    cnt = Counter(vals)
    groups = sorted(cnt.items(), key=lambda kv: (-kv[1], -kv[0]))
    if groups[0][1] == 4:
        q = groups[0][0]
        return (7, q, max(v for v in vals if v != q))
    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *flush[:5])
    st = _straight_high(vals)
    if st:
        return (4, st)
    if groups[0][1] == 3:
        t = groups[0][0]
        kick = [v for v in vals if v != t]
        return (3, t, *kick[:2])
    if groups[0][1] == 2 and groups[1][1] == 2:
        p1, p2 = groups[0][0], groups[1][0]
        return (2, p1, p2, max(v for v in vals if v not in (p1, p2)))
    if groups[0][1] == 2:
        p = groups[0][0]
        kick = [v for v in vals if v != p]
        return (1, p, *kick[:3])
    return (0, *vals[:5])


def equity(hole, board, n_opp, samples, rng):
    """Monte Carlo win probability vs n_opp random hands."""
    n_opp = max(1, min(n_opp, 3))
    dead = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in dead]
    need = 5 - len(board)
    score = 0.0
    for _ in range(samples):
        draw = rng.sample(deck, need + 2 * n_opp)
        full = list(board) + draw[:need]
        mine = eval7(list(hole) + full)
        best_opp = max(
            eval7(draw[need + 2 * i: need + 2 * i + 2] + full)
            for i in range(n_opp)
        )
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 0.5
    return score / samples


def chen(hole):
    """Chen formula preflop hand score (AA=20 ... 72o=-1)."""
    a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
    va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
    high = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(va, va / 2.0)
    if va == vb:
        return max(high * 2, 5.0)
    score = high
    if a[1] == b[1]:
        score += 2
    gap = va - vb - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and va < 12:
        score += 1
    return score


# ---------------------------------------------------------------- strategies

class Strategy:
    name = "base"

    def observe(self, actor, street, action):
        pass

    def act(self, v, rng):
        raise NotImplementedError


class AllInBot(Strategy):
    """Player #1. The entire strategy, verbatim:

        if my_turn:
            bet = ALL_IN
        fi
    """
    name = "LEEROY (ALL-IN)"

    def act(self, v, rng):
        return ("raise", v["my_bet"] + v["stack"])


class TAGBot(Strategy):
    """Tight-aggressive: Chen-formula positional ranges preflop, Monte Carlo
    equity vs pot odds postflop, value bets ~2/3 pot, semi-bluffs draws,
    equity-based shove calling."""
    name = "The Professor (TAG)"

    def act(self, v, rng):
        pot, to_call, stack = v["pot"], v["to_call"], v["stack"]
        if v["street"] == "preflop":
            s = chen(v["hole"])
            pos = v["position"]
            if to_call > stack * 0.25:                       # facing a shove
                eq = equity(v["hole"], [], 1, 40, rng)
                odds = to_call / (pot + to_call)
                return "call" if eq > odds + 0.04 else "fold"
            if to_call <= v["bb"]:                            # unopened pot
                if s >= 9 - 3 * pos:
                    return ("raise", v["current_bet"] + 3 * v["bb"])
                return "call" if to_call == 0 else "fold"
            if s >= 12:                                       # facing a raise
                return ("raise", v["current_bet"] * 3)
            if s >= 9 and to_call <= stack * 0.1:
                return "call"
            return "fold"
        eq = equity(v["hole"], v["board"], v["n_active"] - 1, 30, rng)
        if to_call == 0:
            strong = 0.5 + 0.04 * (v["n_active"] - 2)
            if eq > strong or (eq > 0.42 and v["street"] == "flop" and rng.random() < 0.35):
                return ("raise", v["current_bet"] + max(v["bb"], int(pot * 0.66)))
            return "call"
        odds = to_call / (pot + to_call)
        if eq > odds + 0.22 and eq > 0.62:
            return ("raise", v["current_bet"] + max(v["min_raise"], int(pot * 0.8)))
        if eq > odds + 0.03:
            return "call"
        return "fold"


class LAGBot(Strategy):
    """Loose-aggressive: wide positional opens, frequent c-bets and steals,
    randomized bluff raises, thin value bets, calls shoves lighter than it
    should because pressure works both ways."""
    name = "Maniac Picasso (LAG)"

    def act(self, v, rng):
        pot, to_call, stack = v["pot"], v["to_call"], v["stack"]
        if v["street"] == "preflop":
            s = chen(v["hole"]) + 2 * v["position"]
            if to_call > stack * 0.25:
                eq = equity(v["hole"], [], 1, 40, rng)
                odds = to_call / (pot + to_call)
                return "call" if eq > odds - 0.02 else "fold"
            if to_call <= v["bb"]:
                if s >= 6 or (v["position"] > 0.6 and rng.random() < 0.35):
                    return ("raise", v["current_bet"] + 3 * v["bb"])
                return "call" if to_call == 0 else "fold"
            if s >= 10 or rng.random() < 0.12:
                return ("raise", v["current_bet"] * 3)
            if s >= 7:
                return "call"
            return "fold"
        eq = equity(v["hole"], v["board"], v["n_active"] - 1, 30, rng)
        if to_call == 0:
            if eq > 0.45 or rng.random() < 0.30:              # bet or barrel
                return ("raise", v["current_bet"] + max(v["bb"], int(pot * 0.75)))
            return "call"
        odds = to_call / (pot + to_call)
        if eq > odds + 0.15 or (rng.random() < 0.10 and to_call < stack * 0.2):
            return ("raise", v["current_bet"] + max(v["min_raise"], int(pot * 0.9)))
        if eq > odds - 0.02:
            return "call"
        return "fold"


class NitBot(Strategy):
    """The Rock: folds everything except premiums, then bets them hard.
    Never bluffs. Waits for the maniacs to hand over their stacks."""
    name = "The Rock (Nit)"

    def act(self, v, rng):
        pot, to_call = v["pot"], v["to_call"]
        if v["street"] == "preflop":
            s = chen(v["hole"])
            if s >= 13:                                       # QQ+ territory
                return ("raise", v["my_bet"] + v["stack"] if to_call > 3 * v["bb"]
                        else v["current_bet"] + 4 * v["bb"])
            if s >= 10 and to_call <= 2 * v["bb"]:
                return "call"
            return "call" if to_call == 0 else "fold"
        eq = equity(v["hole"], v["board"], v["n_active"] - 1, 30, rng)
        if to_call == 0:
            if eq > 0.72:
                return ("raise", v["current_bet"] + max(v["bb"], int(pot * 0.6)))
            return "call"
        odds = to_call / (pot + to_call)
        if eq > 0.80:
            return ("raise", v["current_bet"] + max(v["min_raise"], pot))
        if eq > odds + 0.12:
            return "call"
        return "fold"


class MathBot(Strategy):
    """Pot-Odds Oracle: pure expected value. Monte Carlo equity on every
    decision, calls exactly when equity beats pot odds, raises for value
    when equity dominates. Zero bluffs, zero emotion."""
    name = "Pot-Odds Oracle (Math)"

    def act(self, v, rng):
        pot, to_call = v["pot"], v["to_call"]
        eq = equity(v["hole"], v["board"], v["n_active"] - 1,
                    35 if v["street"] == "preflop" else 30, rng)
        if to_call == 0:
            fair = 1.0 / v["n_active"]
            if eq > fair + 0.18:
                return ("raise", v["current_bet"] + max(v["bb"], int(pot * 0.7)))
            return "call"
        odds = to_call / (pot + to_call)
        if eq > 0.65 and eq > odds + 0.20:
            return ("raise", v["current_bet"] + max(v["min_raise"], int(pot * 0.8)))
        if eq > odds + 0.01:
            return "call"
        return "fold"


class AdaptiveBot(Strategy):
    """The Profiler: tracks every opponent's raise frequency across the
    tournament. Snap-calls maniacs with real equity, gives tight players'
    raises full respect, plays TAG baseline otherwise."""
    name = "The Profiler (Adaptive)"

    def __init__(self):
        self.actions = Counter()
        self.raises = Counter()

    def observe(self, actor, street, action):
        if actor == self.name:
            return
        self.actions[actor] += 1
        if action == "raise":
            self.raises[actor] += 1

    def _aggression(self, actor):
        n = self.actions[actor]
        return self.raises[actor] / n if n >= 5 else 0.35

    def act(self, v, rng):
        pot, to_call, stack = v["pot"], v["to_call"], v["stack"]
        aggr = self._aggression(v["aggressor"]) if v["aggressor"] else 0.35
        # vs a maniac their raises mean little; vs a rock they mean a lot
        margin = 0.16 - 0.30 * aggr
        if v["street"] == "preflop":
            s = chen(v["hole"])
            if to_call > stack * 0.25:
                eq = equity(v["hole"], [], 1, 40, rng)
                odds = to_call / (pot + to_call)
                return "call" if eq > odds + margin else "fold"
            if to_call <= v["bb"]:
                if s >= 8.5 - 3 * v["position"]:
                    return ("raise", v["current_bet"] + 3 * v["bb"])
                return "call" if to_call == 0 else "fold"
            if s >= 12:
                return ("raise", v["current_bet"] * 3)
            if s >= 9 + 4 * margin and to_call <= stack * 0.12:
                return "call"
            return "fold"
        eq = equity(v["hole"], v["board"], v["n_active"] - 1, 30, rng)
        if to_call == 0:
            if eq > 0.5 + 0.04 * (v["n_active"] - 2):
                return ("raise", v["current_bet"] + max(v["bb"], int(pot * 0.66)))
            return "call"
        odds = to_call / (pot + to_call)
        if eq > odds + 0.22 and eq > 0.62:
            return ("raise", v["current_bet"] + max(v["min_raise"], int(pot * 0.8)))
        if eq > odds + max(0.0, margin):
            return "call"
        return "fold"


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, seat, strategy, stack):
        self.seat = seat
        self.strategy = strategy
        self.name = strategy.name
        self.stack = stack

    def reset(self):
        self.hole = []
        self.folded = False
        self.allin = False
        self.bet_street = 0
        self.committed = 0


class Hand:
    def __init__(self, seats, sb, bb, rng, observers):
        self.seats = seats            # live players, seat order, [0]=SB
        self.sb, self.bb = sb, bb
        self.rng = rng
        self.observers = observers
        self.board = []
        self.current_bet = 0
        self.min_raise = bb
        self.last_aggressor = None

    def pot(self):
        return sum(p.committed for p in self.seats)

    def commit(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.bet_street += amount
        p.committed += amount
        if p.stack == 0:
            p.allin = True

    def notify(self, actor, street, action):
        for s in self.observers:
            s.observe(actor.name, street, action)

    def view(self, p, street):
        order = [q for q in self.seats if not q.folded]
        return {
            "hole": p.hole, "board": self.board, "pot": self.pot(),
            "to_call": self.current_bet - p.bet_street,
            "stack": p.stack, "my_bet": p.bet_street,
            "current_bet": self.current_bet, "min_raise": self.min_raise,
            "n_active": len(order), "bb": self.bb, "street": street,
            "position": self.seats.index(p) / max(1, len(self.seats) - 1),
            "aggressor": self.last_aggressor,
        }

    def betting(self, first, street):
        n = len(self.seats)
        acted = set()
        i = first
        guard = 0
        while True:
            guard += 1
            if guard > 500:
                break
            live = [p for p in self.seats if not p.folded]
            if len(live) <= 1:
                return
            actors = [p for p in live if not p.allin]
            if not actors or all(
                id(p) in acted and p.bet_street == self.current_bet for p in actors
            ):
                return
            p = self.seats[i % n]
            i += 1
            if p.folded or p.allin:
                continue
            if id(p) in acted and p.bet_street == self.current_bet:
                continue
            to_call = self.current_bet - p.bet_street
            action = p.strategy.act(self.view(p, street), self.rng)
            acted.add(id(p))
            if action == "fold":
                if to_call > 0:
                    p.folded = True
                    self.notify(p, street, "fold")
                else:
                    self.notify(p, street, "check")
            elif action == "call":
                self.commit(p, to_call)
                self.notify(p, street, "call" if to_call else "check")
            else:                                             # ("raise", to)
                target = min(action[1], p.bet_street + p.stack)
                if target <= self.current_bet:                # can't raise
                    self.commit(p, to_call)
                    self.notify(p, street, "call")
                else:
                    full = target - self.current_bet >= self.min_raise
                    self.commit(p, target - p.bet_street)
                    if full:
                        self.min_raise = target - self.current_bet
                        acted = {id(p)}
                    self.current_bet = target
                    self.last_aggressor = p.name
                    self.notify(p, street, "raise")

    def new_street(self):
        for p in self.seats:
            p.bet_street = 0
        self.current_bet = 0
        self.min_raise = self.bb
        self.last_aggressor = None

    def play(self):
        for p in self.seats:
            p.reset()
        deck = FULL_DECK[:]
        self.rng.shuffle(deck)
        for p in self.seats:
            p.hole = [deck.pop(), deck.pop()]
        self.commit(self.seats[0], self.sb)
        self.commit(self.seats[1 % len(self.seats)], self.bb)
        self.current_bet = self.bb
        self.betting(2 % len(self.seats), "preflop")
        for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len([p for p in self.seats if not p.folded]) <= 1:
                break
            deck.pop()                                        # burn
            self.board += [deck.pop() for _ in range(n_cards)]
            self.new_street()
            self.betting(0, street)
        self.showdown()

    def showdown(self):
        contenders = [p for p in self.seats if not p.folded]
        if len(contenders) == 1:
            contenders[0].stack += self.pot()
            return
        ranks = {id(p): eval7(p.hole + self.board) for p in contenders}
        levels = sorted({p.committed for p in self.seats if p.committed > 0})
        prev = 0
        for lv in levels:
            layer = sum(
                max(0, min(p.committed, lv) - prev) for p in self.seats
            )
            eligible = [p for p in contenders if p.committed >= lv]
            if not eligible:                                  # overbet refund
                eligible = [max(contenders, key=lambda p: ranks[id(p)])]
            best = max(ranks[id(p)] for p in eligible)
            winners = [p for p in eligible if ranks[id(p)] == best]
            share = layer // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += layer - share * len(winners)
            prev = lv


def run_tournament(rng, stack=1000, sb=10, bb=20, escalate_every=12, max_hands=800):
    strategies = [AllInBot(), TAGBot(), LAGBot(), NitBot(), MathBot(), AdaptiveBot()]
    players = [Player(i, s, stack) for i, s in enumerate(strategies)]
    busted = []
    button = rng.randrange(6)
    hand_no = 0
    while sum(1 for p in players if p.stack > 0) > 1 and hand_no < max_hands:
        hand_no += 1
        if hand_no % escalate_every == 0:
            sb, bb = int(sb * 1.5), int(bb * 1.5)
        for _ in range(6):
            button = (button + 1) % 6
            if players[button].stack > 0:
                break
        live = sorted(
            (p for p in players if p.stack > 0),
            key=lambda p: (p.seat - button - 1) % 6,
        )
        Hand(live, sb, bb, rng, [p.strategy for p in live]).play()
        newly = [p for p in live if p.stack == 0]
        busted.extend(sorted(newly, key=lambda p: p.committed))
    alive = sorted((p for p in players if p.stack > 0), key=lambda p: p.stack)
    busted.extend(alive)
    finish_order = [p.name for p in reversed(busted)]          # 1st ... 6th
    return finish_order[0], finish_order, hand_no


# ---------------------------------------------------------------- main

BAR = "█"


def histogram(counter, order, total, width=50):
    lines = []
    top = max(counter.values()) if counter else 1
    for name in order:
        n = counter.get(name, 0)
        bar = BAR * max(1 if n else 0, round(n / top * width))
        lines.append(f"  {name:<26} {bar} {n}")
    return "\n".join(lines)


def main(n_sims=100, seed=31337):
    names = [AllInBot.name, TAGBot.name, LAGBot.name,
             NitBot.name, MathBot.name, AdaptiveBot.name]
    wins = Counter()
    finishes = defaultdict(list)
    hands_played = []
    t0 = time.time()
    for i in range(n_sims):
        winner, order, hands = run_tournament(random.Random(seed + i))
        wins[winner] += 1
        hands_played.append(hands)
        for pos, nm in enumerate(order, 1):
            finishes[nm].append(pos)
        if (i + 1) % 10 == 0:
            print(f"  sim {i + 1:>3}/{n_sims}  "
                  f"({time.time() - t0:.0f}s elapsed)", file=sys.stderr)

    print()
    print("=" * 72)
    print("  WINNER WINNER CHICKEN DINNER — tournament wins over"
          f" {n_sims} simulations")
    print("=" * 72)
    print(histogram(wins, names, n_sims))
    print("-" * 72)
    print(f"  avg tournament length: {sum(hands_played) / len(hands_played):.0f} hands")
    print()
    print("  avg finishing position (1 = winner, 6 = first bust):")
    for nm in names:
        fs = finishes[nm]
        avg = sum(fs) / len(fs)
        first_out = sum(1 for f in fs if f == 6)
        print(f"  {nm:<26} avg {avg:.2f}   busted first {first_out}x")
    return wins, finishes


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    main(n)
