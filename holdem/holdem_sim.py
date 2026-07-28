"""Texas Hold'em tournament simulator.

6 players, identical starting stacks. Player 1 plays "if my_turn then all-in".
Players 2-6 each run a distinct, non-trivial strategy. No strategy can see
another's code -- they only observe public information (board, bets, stacks,
showdowns).

Runs N full tournaments (play until one player holds every chip) and prints a
histogram of tournament winners.
"""

import random
import sys
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------- cards

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}


def new_deck():
    return [r + s for r in RANKS for s in SUITS]


# ------------------------------------------------------- hand evaluation
# Returns a comparable tuple; higher tuple = better hand.
# Categories: 8 SF, 7 quads, 6 full house, 5 flush, 4 straight,
#             3 trips, 2 two pair, 1 pair, 0 high card.


def eval5(cards):
    vals = sorted((RANK_VAL[c[0]] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1

    distinct = sorted(set(vals), reverse=True)
    straight_high = 0
    if len(distinct) == 5:
        if distinct[0] - distinct[4] == 4:
            straight_high = distinct[0]
        elif distinct == [14, 5, 4, 3, 2]:  # wheel
            straight_high = 5

    counts = Counter(vals)
    # sort by (count, value) desc -> kicker ordering baked in
    by_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    shape = tuple(cnt for _, cnt in by_count)
    order = tuple(v for v, cnt in by_count for _ in range(cnt))

    if straight_high and flush:
        return (8, straight_high)
    if shape[0] == 4:
        return (7,) + order
    if shape == (3, 2):
        return (6,) + order
    if flush:
        return (5,) + tuple(vals)
    if straight_high:
        return (4, straight_high)
    if shape[0] == 3:
        return (3,) + order
    if shape[:2] == (2, 2):
        return (2,) + order
    if shape[0] == 2:
        return (1,) + order
    return (0,) + tuple(vals)


def eval7(cards):
    return max(eval5(c) for c in combinations(cards, 5))


def best_hand(hole, board):
    return eval7(list(hole) + list(board))


# -------------------------------------------------- shared strategy math


def chen_score(hole):
    """Chen formula: preflop hand strength, roughly -1..20."""
    a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
    va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(va, va / 2)
    if va == vb:
        return max(5, pts * 2)
    gap = va - vb - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and va < 12:
        pts += 1
    if a[1] == b[1]:
        pts += 2
    return pts


def estimate_equity(hole, board, n_opp, rng, trials=60):
    """Monte Carlo win probability vs n_opp random hands."""
    dead = set(hole) | set(board)
    deck = [c for c in new_deck() if c not in dead]
    need = 5 - len(board)
    wins = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need + 2 * n_opp)
        full = list(board) + draw[:need]
        mine = best_hand(hole, full)
        best_opp = max(
            best_hand(draw[need + 2 * i: need + 2 * i + 2], full)
            for i in range(n_opp)
        )
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / trials


# ------------------------------------------------------------ strategies
# Interface: act(view) -> ("fold"|"check_call"|"raise", raise_to_total)
# view is a dict of public info + own hole cards. Engine clamps everything
# to legal amounts (all-in if short).


class Strategy:
    name = "?"

    def act(self, v):
        raise NotImplementedError

    def observe_action(self, seat, action, amount):
        pass

    def observe_hand_end(self):
        pass


class AllInManiac(Strategy):
    """if my_turn then bet = all in fi"""
    name = "AllInManiac"

    def act(self, v):
        return ("raise", v["stack"] + v["my_bet"])


class TAGBot(Strategy):
    """Tight-aggressive: Chen-formula preflop with positional widening,
    equity-driven value betting postflop, folds to pressure without a hand."""
    name = "TAG"

    def __init__(self, rng):
        self.rng = rng

    def act(self, v):
        pot, to_call = v["pot"], v["to_call"]
        if not v["board"]:
            score = chen_score(v["hole"])
            score += v["position_frac"] * 2  # later position -> wider
            big_pressure = to_call > 4 * v["big_blind"]
            if score >= 12 and not (big_pressure and score < 14):
                target = v["my_bet"] + to_call + max(3 * v["big_blind"], pot)
                return ("raise", target)
            if score >= 9 and to_call <= 3 * v["big_blind"]:
                return ("check_call", 0)
            if score >= 7 and to_call == 0:
                return ("check_call", 0)
            return ("fold", 0) if to_call else ("check_call", 0)

        eq = estimate_equity(v["hole"], v["board"], max(1, v["n_opponents"]),
                             self.rng, trials=50)
        if eq > 0.72:
            return ("raise", v["my_bet"] + to_call + max(v["big_blind"], int(pot * 0.66)))
        if to_call == 0:
            if eq > 0.55:
                return ("raise", v["my_bet"] + max(v["big_blind"], int(pot * 0.5)))
            return ("check_call", 0)
        pot_odds = to_call / (pot + to_call)
        if eq > pot_odds + 0.05:
            return ("check_call", 0)
        return ("fold", 0)


class LAGBot(Strategy):
    """Loose-aggressive: wide opening range, positional steals, semi-bluffs
    draws, barrels when checked to."""
    name = "LAG"

    def __init__(self, rng):
        self.rng = rng

    def _draw_outs(self, hole, board):
        cards = list(hole) + list(board)
        suits = Counter(c[1] for c in cards)
        outs = 0
        if max(suits.values()) == 4:
            outs += 9
        vals = sorted(set(RANK_VAL[c[0]] for c in cards))
        for lo in range(2, 11):
            window = [x for x in vals if lo <= x <= lo + 4]
            if len(set(window)) == 4:
                outs += 4
                break
        return outs

    def act(self, v):
        pot, to_call = v["pot"], v["to_call"]
        if not v["board"]:
            score = chen_score(v["hole"]) + v["position_frac"] * 3
            if score >= 10 or (score >= 6 and self.rng.random() < 0.35):
                if to_call > v["stack"] * 0.35 and score < 13:
                    return ("fold", 0)
                return ("raise", v["my_bet"] + to_call + max(3 * v["big_blind"], int(pot * 0.8)))
            if score >= 6 and to_call <= 2 * v["big_blind"]:
                return ("check_call", 0)
            return ("fold", 0) if to_call else ("check_call", 0)

        eq = estimate_equity(v["hole"], v["board"], max(1, v["n_opponents"]),
                             self.rng, trials=40)
        outs = self._draw_outs(v["hole"], v["board"])
        street_cards_left = 5 - len(v["board"])
        draw_eq = min(0.45, outs * 0.02 * street_cards_left)
        eff = max(eq, draw_eq)

        if eq > 0.65 or (draw_eq > 0.3 and self.rng.random() < 0.6):
            return ("raise", v["my_bet"] + to_call + max(v["big_blind"], int(pot * 0.75)))
        if to_call == 0:
            if self.rng.random() < 0.4:  # stab at orphan pots
                return ("raise", v["my_bet"] + max(v["big_blind"], int(pot * 0.5)))
            return ("check_call", 0)
        pot_odds = to_call / (pot + to_call)
        if eff > pot_odds:
            return ("check_call", 0)
        return ("fold", 0)


class NitBot(Strategy):
    """Ultra-tight rock: folds everything except premiums, then never lets go.
    Feasts on maniacs by waiting for the top of its range."""
    name = "Nit"

    PREMIUM_PAIRS = {14, 13, 12, 11, 10, 9}

    def __init__(self, rng):
        self.rng = rng

    def _premium(self, hole):
        a, b = sorted(hole, key=lambda c: RANK_VAL[c[0]], reverse=True)
        va, vb = RANK_VAL[a[0]], RANK_VAL[b[0]]
        if va == vb:
            return va in self.PREMIUM_PAIRS
        suited = a[1] == b[1]
        if va == 14 and vb >= 12:
            return True
        if va == 14 and vb == 11 and suited:
            return True
        if va == 13 and vb == 12 and suited:
            return True
        return False

    def act(self, v):
        pot, to_call = v["pot"], v["to_call"]
        # desperation: blinds have eaten the stack, shove any decent hand
        if v["stack"] + v["my_bet"] < 6 * v["big_blind"]:
            if chen_score(v["hole"]) >= 8:
                return ("raise", v["stack"] + v["my_bet"])

        if not v["board"]:
            if self._premium(v["hole"]):
                return ("raise", v["my_bet"] + to_call + max(4 * v["big_blind"], pot))
            return ("fold", 0) if to_call else ("check_call", 0)

        eq = estimate_equity(v["hole"], v["board"], max(1, v["n_opponents"]),
                             self.rng, trials=50)
        if eq > 0.6:
            return ("raise", v["my_bet"] + to_call + max(v["big_blind"], int(pot * 0.8)))
        if eq > 0.45:
            return ("check_call", 0)
        return ("fold", 0) if to_call else ("check_call", 0)


class MathBot(Strategy):
    """Pure EV machine: Monte Carlo equity vs pot odds on every decision,
    raises proportional to edge, no emotions, no image."""
    name = "MathBot"

    def __init__(self, rng):
        self.rng = rng

    def act(self, v):
        pot, to_call = v["pot"], v["to_call"]
        n_opp = max(1, v["n_opponents"])
        eq = estimate_equity(v["hole"], v["board"], n_opp, self.rng, trials=70)
        breakeven = 1.0 / (n_opp + 1)

        if to_call == 0:
            if eq > breakeven + 0.18:
                bet = int(pot * min(1.0, (eq - breakeven) * 3))
                return ("raise", v["my_bet"] + max(v["big_blind"], bet))
            return ("check_call", 0)

        pot_odds = to_call / (pot + to_call)
        if eq > pot_odds + 0.22:
            return ("raise", v["my_bet"] + to_call + max(v["big_blind"], int(pot * 0.7)))
        if eq > pot_odds:
            return ("check_call", 0)
        return ("fold", 0)


class AdaptiveBot(Strategy):
    """Exploitative profiler: tracks every opponent's public aggression and
    fold frequency across hands, then tightens vs maniacs (call down lighter
    but only with real equity) and steals relentlessly vs tight tables."""
    name = "Adaptive"

    def __init__(self, rng):
        self.rng = rng
        self.raises = Counter()
        self.actions = Counter()
        self.folds = Counter()

    def observe_action(self, seat, action, amount):
        self.actions[seat] += 1
        if action == "raise":
            self.raises[seat] += 1
        elif action == "fold":
            self.folds[seat] += 1

    def _aggr(self, seat):
        n = self.actions[seat]
        return self.raises[seat] / n if n >= 5 else 0.3

    def act(self, v):
        pot, to_call = v["pot"], v["to_call"]
        opp_seats = v["active_opponents"]
        avg_aggr = (sum(self._aggr(s) for s in opp_seats) / len(opp_seats)) if opp_seats else 0.3
        vs_maniac = avg_aggr > 0.6

        eq_needed_shift = 0.08 if vs_maniac else -0.04

        if not v["board"]:
            score = chen_score(v["hole"]) + v["position_frac"] * 2
            if vs_maniac:
                # trap: flat premiums, fold speculative junk into shoves
                if score >= 13:
                    return ("check_call", 0) if to_call < v["stack"] * 0.5 \
                        else ("raise", v["stack"] + v["my_bet"])
                if score >= 10 and to_call <= 3 * v["big_blind"]:
                    return ("check_call", 0)
                return ("fold", 0) if to_call else ("check_call", 0)
            # vs passive table: raise wide, steal blinds
            if score >= 9:
                return ("raise", v["my_bet"] + to_call + max(3 * v["big_blind"], int(pot * 0.9)))
            if score >= 7 and to_call <= 2 * v["big_blind"]:
                return ("check_call", 0)
            return ("fold", 0) if to_call else ("check_call", 0)

        eq = estimate_equity(v["hole"], v["board"], max(1, v["n_opponents"]),
                             self.rng, trials=60)
        if to_call == 0:
            if eq > 0.6 + eq_needed_shift:
                return ("raise", v["my_bet"] + max(v["big_blind"], int(pot * 0.7)))
            if not vs_maniac and self.rng.random() < 0.3:
                return ("raise", v["my_bet"] + max(v["big_blind"], int(pot * 0.5)))
            return ("check_call", 0)
        pot_odds = to_call / (pot + to_call)
        if eq > max(pot_odds, 0.5) + eq_needed_shift and eq > 0.7:
            return ("raise", v["my_bet"] + to_call + max(v["big_blind"], int(pot * 0.8)))
        if eq > pot_odds + eq_needed_shift:
            return ("check_call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------- engine


class PlayerState:
    def __init__(self, seat, strategy, stack):
        self.seat = seat
        self.strategy = strategy
        self.stack = stack
        self.hole = None
        self.bet = 0            # committed this street
        self.total_in = 0       # committed this hand
        self.folded = False
        self.allin = False

    @property
    def alive(self):
        return self.stack > 0 or self.total_in > 0


class Tournament:
    def __init__(self, strategies, rng, start_stack=1000, sb=5, bb=10,
                 blind_double_every=15, max_hands=2000):
        self.players = [PlayerState(i + 1, s, start_stack)
                        for i, s in enumerate(strategies)]
        self.rng = rng
        self.sb, self.bb = sb, bb
        self.blind_double_every = blind_double_every
        self.max_hands = max_hands
        self.button = rng.randrange(len(self.players))

    def broadcast(self, seat, action, amount):
        for p in self.players:
            if p.stack > 0 or p.total_in > 0:
                p.strategy.observe_action(seat, action, amount)

    def run(self):
        hands = 0
        while True:
            standing = [p for p in self.players if p.stack > 0]
            if len(standing) == 1:
                return standing[0].seat
            hands += 1
            if hands > self.max_hands:  # pathological stall: chip leader wins
                return max(standing, key=lambda p: p.stack).seat
            if hands % self.blind_double_every == 0:
                self.sb *= 2
                self.bb *= 2
            self.play_hand(standing)
            for p in self.players:
                p.strategy.observe_hand_end()

    # ---- one hand ----

    def play_hand(self, standing):
        n = len(standing)
        self.button = self._next_standing_seat_idx(self.button)
        order = self._seat_order(standing)

        deck = new_deck()
        self.rng.shuffle(deck)
        for p in standing:
            p.hole = (deck.pop(), deck.pop())
            p.bet = p.total_in = 0
            p.folded = False
            p.allin = False

        board = []

        if n == 2:
            sb_p, bb_p = order[0], order[1]  # button posts SB heads-up
        else:
            sb_p, bb_p = order[1], order[2]
        self._post(sb_p, min(self.sb, sb_p.stack))
        self._post(bb_p, min(self.bb, bb_p.stack))

        if n == 2:
            preflop_start = 0  # button/SB acts first heads-up
        else:
            preflop_start = 3 % n  # UTG
        self._betting_round(order, board, first_idx=preflop_start)

        for n_new in (3, 1, 1):
            if self._hand_over():
                break
            board.extend(deck.pop() for _ in range(n_new))
            for p in standing:
                p.bet = 0
            postflop_start = 1 % n if n > 2 else 1  # left of button
            self._betting_round(order, board, first_idx=postflop_start)

        self._showdown(standing, board, deck)

    def _post(self, p, amt):
        p.stack -= amt
        p.bet += amt
        p.total_in += amt
        if p.stack == 0:
            p.allin = True

    def _hand_over(self):
        contesting = [p for p in self.players
                      if p.total_in >= 0 and not p.folded and (p.stack > 0 or p.allin) and p.hole]
        live = [p for p in contesting if not p.folded]
        can_act = [p for p in live if not p.allin]
        return len(live) <= 1 or len(can_act) <= 1 and self._bets_matched(live)

    def _bets_matched(self, live):
        top = max(p.bet for p in live)
        return all(p.bet == top or p.allin for p in live)

    def _betting_round(self, order, board, first_idx):
        n = len(order)
        current_bet = max(p.bet for p in order)
        min_raise = self.bb
        pending = [p for p in order if not p.folded and not p.allin]
        if len(pending) <= 1 and self._bets_matched([p for p in order if not p.folded]):
            return

        acted = set()
        i = first_idx
        safety = 0
        while True:
            safety += 1
            if safety > 500:
                break
            live = [p for p in order if not p.folded]
            if len(live) <= 1:
                break
            actionable = [p for p in live if not p.allin]
            if all(p in acted for p in actionable) and self._bets_matched(live):
                break
            p = order[i % n]
            i += 1
            if p.folded or p.allin:
                continue
            if p in acted and p.bet == current_bet:
                continue

            to_call = current_bet - p.bet
            pot = sum(q.total_in for q in order)
            view = {
                "hole": p.hole,
                "board": tuple(board),
                "pot": pot,
                "to_call": min(to_call, p.stack),
                "stack": p.stack,
                "my_bet": p.bet,
                "big_blind": self.bb,
                "min_raise": min_raise,
                "n_opponents": len(live) - 1,
                "active_opponents": [q.seat for q in live if q is not p],
                "position_frac": ((i - 1) % n) / max(1, n - 1),
                "stacks": {q.seat: q.stack for q in order},
            }
            action, raise_to = p.strategy.act(view)

            if action == "fold" and to_call == 0:
                action = "check_call"

            if action == "fold":
                p.folded = True
                self.broadcast(p.seat, "fold", 0)
            elif action == "check_call":
                pay = min(to_call, p.stack)
                self._post(p, pay)
                self.broadcast(p.seat, "call" if pay else "check", pay)
            else:  # raise
                raise_to = max(raise_to, current_bet + min_raise)
                add = raise_to - p.bet
                if add >= p.stack:  # all-in
                    add = p.stack
                    raise_to = p.bet + add
                self._post(p, add)
                if raise_to > current_bet:
                    min_raise = max(min_raise, raise_to - current_bet)
                    current_bet = raise_to
                    acted = set()
                self.broadcast(p.seat, "raise" if raise_to > current_bet - 1 else "call", add)
            acted.add(p)

    def _showdown(self, standing, board, deck):
        live = [p for p in standing if not p.folded]
        pot_total = sum(p.total_in for p in standing)

        if len(live) == 1:
            live[0].stack += pot_total
            return

        while len(board) < 5:
            board.append(deck.pop())

        scores = {p.seat: best_hand(p.hole, board) for p in live}

        # side pots by contribution layers
        contribs = {p: p.total_in for p in standing}
        levels = sorted(set(v for v in contribs.values() if v > 0))
        prev = 0
        for level in levels:
            layer = 0
            eligible = []
            for p, c in contribs.items():
                if c > prev:
                    layer += min(c, level) - prev
                    if not p.folded and c >= level:
                        eligible.append(p)
            if layer and eligible:
                best = max(scores[p.seat] for p in eligible)
                winners = [p for p in eligible if scores[p.seat] == best]
                share, rem = divmod(layer, len(winners))
                for j, w in enumerate(winners):
                    w.stack += share + (1 if j < rem else 0)
            prev = level

    # ---- seating helpers ----

    def _next_standing_seat_idx(self, from_idx):
        n = len(self.players)
        j = from_idx
        while True:
            j = (j + 1) % n
            if self.players[j].stack > 0:
                return j

    def _seat_order(self, standing):
        """Standing players ordered starting at the button."""
        idxs = [i for i, p in enumerate(self.players) if p.stack > 0]
        start = idxs.index(self.button)
        return [self.players[i] for i in idxs[start:] + idxs[:start]]


# ------------------------------------------------------------------ main


def make_strategies(rng):
    return [
        AllInManiac(),
        TAGBot(random.Random(rng.random())),
        LAGBot(random.Random(rng.random())),
        NitBot(random.Random(rng.random())),
        MathBot(random.Random(rng.random())),
        AdaptiveBot(random.Random(rng.random())),
    ]


def main(n_sims=100, seed=None):
    master = random.Random(seed)
    names = {i + 1: s.name for i, s in enumerate(make_strategies(random.Random(0)))}
    wins = Counter()

    for sim in range(1, n_sims + 1):
        rng = random.Random(master.random())
        strategies = make_strategies(rng)
        t = Tournament(strategies, rng)
        winner = t.run()
        wins[winner] += 1
        if sim % 10 == 0:
            print(f"  ... {sim}/{n_sims} tournaments done", file=sys.stderr)

    print()
    print(f"WINNER HISTOGRAM -- {n_sims} full tournaments (last player standing)")
    print("=" * 64)
    max_w = max(wins.values()) if wins else 1
    for seat in range(1, 7):
        w = wins[seat]
        bar = "#" * round(w / max_w * 40)
        tag = "  <-- ALL-IN BOT" if seat == 1 else ""
        print(f"P{seat} {names[seat]:<11} {w:3d} |{bar}{tag}")
    print("=" * 64)
    champ = wins.most_common(1)[0]
    print(f"Winner winner chicken dinner: P{champ[0]} ({names[champ[0]]}) "
          f"with {champ[1]}/{n_sims} tournament wins")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(n, seed)
