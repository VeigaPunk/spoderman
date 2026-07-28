"""No-limit Texas Hold'em tournament simulator.

6 players, equal starting stacks, play until one player holds all chips.
Player 1 uses a trivial "always all-in" strategy; players 2-6 use elaborate
strategies. No strategy can see another player's logic, only public actions.
"""

import random
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def make_deck():
    return [(r, s) for r in range(13) for s in range(4)]


def card_str(c):
    return RANKS[c[0]] + SUITS[c[1]]


# ---------------------------------------------------------------------------
# 7-card hand evaluator. Returns a tuple; higher tuple = better hand.
# ---------------------------------------------------------------------------

def _straight_high(rankset):
    bits = 0
    for r in rankset:
        bits |= 1 << r
    for high in range(12, 3, -1):
        if all(bits >> (high - i) & 1 for i in range(5)):
            return high
    if (bits & 0x100F) == 0x100F:  # A,2,3,4,5
        return 3
    return None


def eval7(cards):
    ranks = sorted((c[0] for c in cards), reverse=True)
    counts = {}
    suits = {}
    for r, s in cards:
        counts[r] = counts.get(r, 0) + 1
        suits.setdefault(s, []).append(r)

    flush_ranks = None
    for s, rs in suits.items():
        if len(rs) >= 5:
            flush_ranks = sorted(rs, reverse=True)
            break

    if flush_ranks:
        sf = _straight_high(set(flush_ranks))
        if sf is not None:
            return (8, sf)

    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    (r1, c1) = by_count[0]
    (r2, c2) = by_count[1] if len(by_count) > 1 else (None, 0)

    if c1 == 4:
        kicker = max(r for r in counts if r != r1)
        return (7, r1, kicker)
    if c1 == 3 and c2 >= 2:
        return (6, r1, r2)
    if flush_ranks:
        return (5,) + tuple(flush_ranks[:5])
    st = _straight_high(set(counts))
    if st is not None:
        return (4, st)
    if c1 == 3:
        kickers = [r for r in ranks if r != r1][:2]
        return (3, r1) + tuple(kickers)
    if c1 == 2 and c2 == 2:
        kicker = max(r for r in counts if r != r1 and r != r2)
        return (2, r1, r2, kicker)
    if c1 == 2:
        kickers = [r for r in ranks if r != r1][:3]
        return (1, r1) + tuple(kickers)
    return (0,) + tuple(ranks[:5])


# ---------------------------------------------------------------------------
# Preflop hand strength (Chen formula, scaled 0..1)
# ---------------------------------------------------------------------------

CHEN_BASE = {12: 10, 11: 8, 10: 7, 9: 6}


def chen_score(hole):
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    high = CHEN_BASE.get(r1, (r1 + 2) / 2.0)
    score = high
    if r1 == r2:
        score = max(5, high * 2)
    if s1 == s2:
        score += 2
    gap = r1 - r2
    if r1 != r2:
        score -= {1: 0, 2: 1, 3: 2, 4: 4}.get(gap, 5)
        if gap <= 2 and r1 < 10:
            score += 1
    return max(0.0, min(1.0, score / 20.0))


# ---------------------------------------------------------------------------
# Monte Carlo equity vs N random opponents
# ---------------------------------------------------------------------------

def mc_equity(hole, board, n_opps, rollouts, rng):
    deck = [c for c in make_deck() if c not in hole and c not in board]
    wins = 0.0
    need = 5 - len(board)
    for _ in range(rollouts):
        rng.shuffle(deck)
        idx = 0
        b = board + deck[idx:idx + need]
        idx += need
        my = eval7(list(hole) + b)
        best = True
        tie = 1
        for _o in range(n_opps):
            opp = deck[idx:idx + 2]
            idx += 2
            ov = eval7(opp + b)
            if ov > my:
                best = False
                break
            if ov == my:
                tie += 1
        if best:
            wins += 1.0 / tie
    return wins / rollouts


# ---------------------------------------------------------------------------
# Strategies. Interface: act(view) -> ("fold",) | ("call",) | ("raise", total_bet)
# view: dict with hole, board, pot, to_call, my_bet, stack, min_raise,
#       position, n_active, n_players, big_blind, street, history, seat, rng
# ---------------------------------------------------------------------------

class Strategy:
    name = "base"

    def act(self, v):
        raise NotImplementedError


class AllInMonkey(Strategy):
    """if my_turn then bet = all in fi"""
    name = "AllInMonkey"

    def act(self, v):
        if v["stack"] + v["my_bet"] <= v["to_call"]:
            return ("call",)
        return ("raise", v["stack"] + v["my_bet"])


class TightAggressive(Strategy):
    """Premium-range TAG: narrow preflop range widened by position, value-bets
    made hands, uses pot odds for draws, punishes shoves with premiums only."""
    name = "TightTAG"

    def act(self, v):
        rng = v["rng"]
        bb = v["big_blind"]
        to_call = v["to_call"] - v["my_bet"]
        pot = v["pot"]
        if v["street"] == 0:
            s = chen_score(v["hole"])
            pos_bonus = 0.05 * v["position"]
            thr_call = 0.42 - pos_bonus
            thr_raise = 0.55 - pos_bonus
            facing_shove = to_call > 10 * bb
            if facing_shove:
                if s >= 0.60:
                    return ("call",)
                return ("fold",) if to_call > 0 else ("call",)
            if s >= thr_raise:
                target = v["to_call"] + max(v["min_raise"], 3 * bb)
                return ("raise", min(target, v["stack"] + v["my_bet"]))
            if s >= thr_call or to_call == 0:
                return ("call",)
            return ("fold",)
        eq = mc_equity(v["hole"], v["board"], max(1, v["n_active"] - 1), 40, rng)
        price = to_call / (pot + to_call) if to_call > 0 else 0.0
        if eq > 0.72:
            target = v["to_call"] + max(v["min_raise"], int(pot * 0.75))
            return ("raise", min(target, v["stack"] + v["my_bet"]))
        if eq > price + 0.06:
            return ("call",)
        if to_call == 0:
            return ("call",)
        return ("fold",)


class LooseAggressive(Strategy):
    """LAG: wide opening range, relentless continuation bets, semi-bluffs
    draws, randomized bluff frequency to stay unreadable."""
    name = "LAGBluffer"

    def __init__(self):
        self.was_aggressor = False

    def act(self, v):
        rng = v["rng"]
        bb = v["big_blind"]
        to_call = v["to_call"] - v["my_bet"]
        pot = v["pot"]
        if v["street"] == 0:
            s = chen_score(v["hole"])
            facing_shove = to_call > 10 * bb
            if facing_shove:
                self.was_aggressor = False
                return ("call",) if s >= 0.55 else ("fold",)
            if s >= 0.30 or rng.random() < 0.15:
                self.was_aggressor = True
                target = v["to_call"] + max(v["min_raise"], int(2.5 * bb))
                return ("raise", min(target, v["stack"] + v["my_bet"]))
            self.was_aggressor = False
            return ("call",) if to_call <= bb else ("fold",)
        eq = mc_equity(v["hole"], v["board"], max(1, v["n_active"] - 1), 30, rng)
        price = to_call / (pot + to_call) if to_call > 0 else 0.0
        cbet = self.was_aggressor and to_call == 0 and rng.random() < 0.7
        if eq > 0.60 or cbet or (eq > 0.35 and rng.random() < 0.25):
            self.was_aggressor = True
            target = v["to_call"] + max(v["min_raise"], int(pot * 0.66))
            return ("raise", min(target, v["stack"] + v["my_bet"]))
        if eq > price:
            return ("call",)
        if to_call == 0:
            return ("call",)
        return ("fold",)


class EquityMaximizer(Strategy):
    """Pure math bot: Monte Carlo equity every street, compares to pot odds,
    sizes bets proportionally to its edge (fractional-Kelly-ish)."""
    name = "EquityMax"

    def act(self, v):
        rng = v["rng"]
        to_call = v["to_call"] - v["my_bet"]
        pot = v["pot"]
        n_opp = max(1, v["n_active"] - 1)
        rollouts = 60 if v["street"] > 0 else 40
        eq = mc_equity(v["hole"], v["board"], n_opp, rollouts, rng)
        breakeven = 1.0 / (n_opp + 1)
        price = to_call / (pot + to_call) if to_call > 0 else 0.0
        edge = eq - breakeven
        if edge > 0.22:
            bet = int(pot * min(1.5, edge * 4))
            target = v["to_call"] + max(v["min_raise"], bet)
            return ("raise", min(target, v["stack"] + v["my_bet"]))
        if to_call == 0:
            return ("call",)
        if eq > price + 0.03:
            return ("call",)
        return ("fold",)


class PotOddsGrinder(Strategy):
    """Passive nit: almost never raises, but never pays a bad price. Grinds
    strictly on pot odds and implied odds, tightens as stacks get shallow."""
    name = "PotOddsNit"

    def act(self, v):
        rng = v["rng"]
        bb = v["big_blind"]
        to_call = v["to_call"] - v["my_bet"]
        pot = v["pot"]
        spr = v["stack"] / max(1, bb)
        if v["street"] == 0:
            s = chen_score(v["hole"])
            thr = 0.40 if spr > 15 else 0.55
            if to_call > 8 * bb:
                return ("call",) if s >= 0.70 else ("fold",)
            if s >= thr or to_call == 0:
                return ("call",)
            if s >= thr - 0.10 and to_call <= 2 * bb:
                return ("call",)
            return ("fold",)
        eq = mc_equity(v["hole"], v["board"], max(1, v["n_active"] - 1), 50, rng)
        price = to_call / (pot + to_call) if to_call > 0 else 0.0
        if eq > 0.85 and v["street"] >= 2:
            target = v["to_call"] + max(v["min_raise"], int(pot * 0.5))
            return ("raise", min(target, v["stack"] + v["my_bet"]))
        if to_call == 0:
            return ("call",)
        implied = 0.03 if v["street"] < 3 else 0.0
        if eq + implied > price:
            return ("call",)
        return ("fold",)


class AdaptiveExploiter(Strategy):
    """Opponent modeler: tracks each seat's aggression frequency and adapts —
    calls down maniacs lighter, bluffs nits harder, tightens multiway."""
    name = "Adaptive"

    def __init__(self):
        self.aggro = {}   # seat -> [raises, actions]

    def observe(self, seat, action):
        r, n = self.aggro.get(seat, [0, 0])
        self.aggro[seat] = [r + (1 if action == "raise" else 0), n + 1]

    def _table_aggression(self):
        r = sum(a[0] for a in self.aggro.values())
        n = sum(a[1] for a in self.aggro.values())
        return (r / n) if n >= 10 else 0.3

    def act(self, v):
        rng = v["rng"]
        bb = v["big_blind"]
        to_call = v["to_call"] - v["my_bet"]
        pot = v["pot"]
        aggr = self._table_aggression()
        loosen = max(-0.10, min(0.12, (aggr - 0.3) * 0.5))
        if v["street"] == 0:
            s = chen_score(v["hole"])
            if to_call > 10 * bb:
                # vs a shove-happy table, call lighter with good hands
                return ("call",) if s >= 0.62 - loosen else ("fold",)
            if s >= 0.52 - loosen:
                target = v["to_call"] + max(v["min_raise"], 3 * bb)
                return ("raise", min(target, v["stack"] + v["my_bet"]))
            if s >= 0.38 - loosen or to_call == 0:
                return ("call",)
            return ("fold",)
        eq = mc_equity(v["hole"], v["board"], max(1, v["n_active"] - 1), 40, rng)
        price = to_call / (pot + to_call) if to_call > 0 else 0.0
        bluff = aggr < 0.2 and to_call == 0 and rng.random() < 0.3
        if eq > 0.68 or bluff:
            target = v["to_call"] + max(v["min_raise"], int(pot * 0.7))
            return ("raise", min(target, v["stack"] + v["my_bet"]))
        if eq > price + max(0.0, 0.08 - loosen):
            return ("call",)
        if to_call == 0:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, seat, strategy, stack):
        self.seat = seat
        self.strategy = strategy
        self.stack = stack
        self.hole = None
        self.bet = 0          # committed this street
        self.total_bet = 0    # committed this hand
        self.folded = False
        self.all_in = False


def play_hand(players, button, bb, rng):
    """players: live players in seat order. Mutates stacks."""
    sb = bb // 2
    n = len(players)
    for p in players:
        p.hole = None
        p.bet = 0
        p.total_bet = 0
        p.folded = False
        p.all_in = False

    deck = make_deck()
    rng.shuffle(deck)
    for p in players:
        p.hole = [deck.pop(), deck.pop()]
    board = []

    def post(p, amount):
        amt = min(amount, p.stack)
        p.stack -= amt
        p.bet += amt
        p.total_bet += amt
        if p.stack == 0:
            p.all_in = True
        return amt

    if n == 2:
        sb_i, bb_i = button, (button + 1) % n
    else:
        sb_i, bb_i = (button + 1) % n, (button + 2) % n
    post(players[sb_i], sb)
    post(players[bb_i], bb)
    pot = players[sb_i].bet + players[bb_i].bet

    observers = [p.strategy for p in players if isinstance(p.strategy, AdaptiveExploiter)]

    def betting_round(street, first_idx):
        nonlocal pot
        current_bet = max(p.bet for p in players)
        min_raise = bb
        active = [p for p in players if not p.folded and not p.all_in]
        if len([p for p in players if not p.folded]) <= 1:
            return
        acted = set()
        i = first_idx
        guard = 0
        while True:
            guard += 1
            if guard > 200:
                break
            actionable = [p for p in players if not p.folded and not p.all_in]
            if not actionable:
                break
            if all(p.seat in acted and p.bet == current_bet for p in actionable):
                break
            p = players[i % n]
            i += 1
            if p.folded or p.all_in:
                continue
            if p.seat in acted and p.bet == current_bet:
                continue
            n_active = len([q for q in players if not q.folded])
            view = {
                "hole": p.hole, "board": board, "pot": pot,
                "to_call": current_bet, "my_bet": p.bet, "stack": p.stack,
                "min_raise": min_raise, "position": (p.seat - button) % n,
                "n_active": n_active, "n_players": n, "big_blind": bb,
                "street": street, "seat": p.seat, "rng": rng,
            }
            action = p.strategy.act(view)
            kind = action[0]
            if kind == "raise":
                target = action[1]
                max_total = p.bet + p.stack
                target = min(target, max_total)
                if target <= current_bet:
                    kind = "call"
                else:
                    raise_by = target - current_bet
                    if raise_by < min_raise and target < max_total:
                        target = min(current_bet + min_raise, max_total)
                        raise_by = target - current_bet
                    min_raise = max(min_raise, raise_by)
                    pot += post(p, target - p.bet)
                    current_bet = p.bet
                    acted = {p.seat}
            if kind == "call":
                need = current_bet - p.bet
                if need > 0:
                    pot += post(p, need)
                acted.add(p.seat)
            elif kind == "fold":
                if current_bet == p.bet:
                    acted.add(p.seat)  # free check, never fold for free
                else:
                    p.folded = True
            elif kind == "raise":
                pass
            for obs in observers:
                obs.observe(p.seat, "raise" if action[0] == "raise" and not p.folded else kind)

    # preflop
    first = (bb_i + 1) % n
    betting_round(0, first)
    street_first = (button + 1) % n

    for street, ncards in ((1, 3), (2, 1), (3, 1)):
        if len([p for p in players if not p.folded]) <= 1:
            break
        for _ in range(ncards):
            board.append(deck.pop())
        for p in players:
            p.bet = 0
        if len([p for p in players if not p.folded and not p.all_in]) > 1:
            betting_round(street, street_first)

    # showdown with side pots
    live = [p for p in players if not p.folded]
    if len(live) == 1:
        live[0].stack += pot
        return

    while len(board) < 5:
        board.append(deck.pop())
    scores = {p.seat: eval7(p.hole + board) for p in live}

    contributions = sorted(set(p.total_bet for p in players if p.total_bet > 0))
    prev = 0
    remaining = {p.seat: p.total_bet for p in players}
    for level in contributions:
        layer = 0
        for p in players:
            take = max(0, min(remaining[p.seat], level - prev))
            remaining[p.seat] -= take
            layer += take
        eligible = [p for p in live if p.total_bet >= level]
        if layer and eligible:
            best = max(scores[p.seat] for p in eligible)
            winners = [p for p in eligible if scores[p.seat] == best]
            share = layer // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += layer - share * len(winners)
        prev = level


def make_strategies():
    return {
        1: AllInMonkey(),
        2: TightAggressive(),
        3: LooseAggressive(),
        4: EquityMaximizer(),
        5: PotOddsGrinder(),
        6: AdaptiveExploiter(),
    }


def play_tournament(rng, starting_stack=1000, bb0=20):
    strategies = make_strategies()
    players = [Player(seat, strategies[seat], starting_stack) for seat in range(1, 7)]
    button = rng.randrange(len(players))
    hand_no = 0
    while len(players) > 1:
        hand_no += 1
        bb = bb0 * (2 ** (hand_no // 20))  # escalating blinds guarantee an end
        bb = min(bb, starting_stack * 6)
        play_hand(players, button % len(players), bb, rng)
        survivors = [p for p in players if p.stack > 0]
        if len(survivors) < len(players):
            players = survivors
        button += 1
        if hand_no > 2000:
            return max(players, key=lambda p: p.stack).seat
    return players[0].seat


def main():
    rng = random.Random(42)
    n_sims = 100
    names = {s: st.name for s, st in make_strategies().items()}
    wins = {s: 0 for s in range(1, 7)}
    for i in range(n_sims):
        winner = play_tournament(rng)
        wins[winner] += 1
        if (i + 1) % 10 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done")

    print()
    print("=" * 62)
    print(" WINNER WINNER CHICKEN DINNER — 100 TOURNAMENTS")
    print("=" * 62)
    maxw = max(wins.values()) or 1
    for seat in range(1, 7):
        bar = "#" * round(wins[seat] * 40 / maxw)
        label = f"P{seat} {names[seat]:<12}"
        print(f"{label} | {bar} {wins[seat]}")
    print("=" * 62)
    return wins, names


if __name__ == "__main__":
    main()
