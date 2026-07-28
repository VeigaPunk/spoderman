#!/usr/bin/env python3
"""Texas Hold'em tournament simulator.

Six players, equal stacks. Seats 2-6 run elaborate strategies; seat 1 runs:

    if my_turn
    Then bet = All in
    Fi

No strategy knows another's algorithm — they only observe public actions.
"""
import random
import sys
import time
from collections import deque

RANK_STR = "23456789TJQKA"
SUIT_STR = "cdhs"

STARTING_CHIPS = 1000
SMALL_BLIND = 5
BIG_BLIND = 10
BLIND_DOUBLE_EVERY = 12
MAX_HANDS = 300
MC_TRIALS = 50


def card_str(c):
    return RANK_STR[c >> 2] + SUIT_STR[c & 3]


def straight_high(rank_set):
    rs = set(rank_set)
    if 12 in rs:
        rs.add(-1)
    for high in range(12, 2, -1):
        if all(high - i in rs for i in range(5)):
            return high
    return None


def eval7(cards):
    ranks = sorted((c >> 2 for c in cards), reverse=True)
    for s in range(4):
        suited = [c >> 2 for c in cards if (c & 3) == s]
        if len(suited) >= 5:
            sf = straight_high(suited)
            if sf is not None:
                return (8, sf)
            suited.sort(reverse=True)
            return (5, tuple(suited[:5]))
    counts = {}
    for r in ranks:
        counts[r] = counts.get(r, 0) + 1
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    if groups[0][1] == 4:
        quad = groups[0][0]
        return (7, quad, max(r for r in ranks if r != quad))
    if groups[0][1] == 3 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])
    st = straight_high(ranks)
    if st is not None:
        return (4, st)
    if groups[0][1] == 3:
        t = groups[0][0]
        kick = [r for r in ranks if r != t]
        return (3, t, kick[0], kick[1])
    if groups[0][1] == 2 and groups[1][1] == 2:
        p1, p2 = groups[0][0], groups[1][0]
        return (2, p1, p2, max(r for r in ranks if r != p1 and r != p2))
    if groups[0][1] == 2:
        p = groups[0][0]
        kick = [r for r in ranks if r != p]
        return (1, p, kick[0], kick[1], kick[2])
    return (0, tuple(ranks[:5]))


def mc_equity(hole, community, n_opps, trials, rng):
    used = set(hole) | set(community)
    deck = [c for c in range(52) if c not in used]
    need_board = 5 - len(community)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need_board + 2 * n_opps)
        board = list(community) + draw[:need_board]
        mine = eval7(list(hole) + board)
        best, ties = True, 1
        for i in range(n_opps):
            opp = draw[need_board + 2 * i : need_board + 2 * i + 2]
            oe = eval7(opp + board)
            if oe > mine:
                best = False
                break
            if oe == mine:
                ties += 1
        if best:
            score += 1.0 / ties
    return score / trials


def chen(hole):
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)
    high = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    score = high
    if r1 == r2:
        return max(5.0, high * 2)
    if (hole[0] & 3) == (hole[1] & 3):
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 <= 9:
        score += 1
    return score


# ---------------------------------------------------------------- strategies

class Strategy:
    name = "base"

    def act(self, v):
        raise NotImplementedError


class AllInBot(Strategy):
    """if my_turn Then bet = All in Fi"""
    name = "AllInBot"

    def act(self, v):
        return ("raise", 10 ** 9)


class TheRock(Strategy):
    """Tight-aggressive: premium ranges by position, value-bets equity edges,
    folds to aggression without the goods."""
    name = "TheRock"

    def act(self, v):
        if v["street"] == "preflop":
            score = chen(v["hole"])
            need = 9.0 - 3.0 * v["relpos"]
            if v["to_call"] > v["big_blind"]:
                need += 2 + min(3.0, 2.0 * v["to_call"] / max(v["pot"], 1))
            if score >= need + 2.5:
                return ("raise", v["current_bet"] + max(v["min_raise"], v["pot"]))
            if score >= need:
                return ("call", 0)
            return ("fold", 0)
        eq = v["equity"]()
        if v["to_call"] == 0:
            if eq > 0.62:
                return ("raise", v["current_bet"] + max(v["min_raise"], int(v["pot"] * 0.7)))
            return ("call", 0)
        pot_odds = v["to_call"] / (v["pot"] + v["to_call"])
        if eq > 0.75:
            return ("raise", v["current_bet"] + max(v["min_raise"], int(v["pot"] * 0.8)))
        if eq > pot_odds + 0.06:
            return ("call", 0)
        return ("fold", 0)


class Berserker(Strategy):
    """Loose-aggressive: wide opens, positional steals, relentless semi-bluffs,
    only surrenders when clearly beaten."""
    name = "Berserker"

    def act(self, v):
        rng = v["rng"]
        if v["street"] == "preflop":
            score = chen(v["hole"])
            steal = v["relpos"] > 0.7 and rng.random() < 0.35
            if v["to_call"] <= v["big_blind"]:
                if score >= 6 or steal:
                    return ("raise", v["current_bet"] + max(v["min_raise"], 3 * v["big_blind"]))
                if score >= 3.5:
                    return ("call", 0)
                return ("fold", 0)
            if score >= 9:
                return ("raise", v["current_bet"] + max(v["min_raise"], v["pot"]))
            if score >= 5.5 and v["to_call"] < v["my_chips"] * 0.25:
                return ("call", 0)
            return ("fold", 0)
        eq = v["equity"]()
        if v["to_call"] == 0:
            if eq > 0.42 or rng.random() < 0.28:
                return ("raise", v["current_bet"] + max(v["min_raise"], int(v["pot"] * 0.66)))
            return ("call", 0)
        pot_odds = v["to_call"] / (v["pot"] + v["to_call"])
        if eq > 0.68:
            return ("raise", v["current_bet"] + max(v["min_raise"], v["pot"]))
        if eq > pot_odds - 0.08:
            return ("call", 0)
        return ("fold", 0)


class EVMachine(Strategy):
    """Cold expected-value math: Monte-Carlo equity vs pot odds every street,
    raise sized to the equity edge, zero emotion."""
    name = "EVMachine"

    def act(self, v):
        eq = v["equity"]()
        n = v["n_live"]
        baseline = 1.0 / n
        if v["to_call"] == 0:
            if eq > baseline + 0.18:
                bet = int(v["pot"] * min(1.2, (eq - baseline) * 3))
                return ("raise", v["current_bet"] + max(v["min_raise"], bet))
            return ("call", 0)
        ev_call = eq * (v["pot"] + v["to_call"]) - v["to_call"]
        if eq > 0.78:
            return ("raise", v["current_bet"] + max(v["min_raise"], v["pot"]))
        if ev_call > 0:
            return ("call", 0)
        return ("fold", 0)


class SlowPlayer(Strategy):
    """The trapper: under-represents monsters until the river or a shove,
    springs the check-raise, plays fit-or-fold otherwise."""
    name = "SlowPlayer"

    def act(self, v):
        if v["street"] == "preflop":
            score = chen(v["hole"])
            if score >= 10:
                return ("raise", v["current_bet"] + max(v["min_raise"], 2 * v["big_blind"]))
            if score >= 6 and v["to_call"] < v["my_chips"] * 0.15:
                return ("call", 0)
            if score >= 8.5:
                return ("call", 0)
            return ("fold", 0)
        eq = v["equity"]()
        pot_odds = v["to_call"] / (v["pot"] + v["to_call"]) if v["to_call"] else 0.0
        facing_shove = v["to_call"] >= v["my_chips"]
        if eq > 0.85:
            if v["street"] == "river" or facing_shove or v["to_call"] > v["pot"]:
                return ("raise", 10 ** 9)
            return ("call", 0)
        if eq > 0.62:
            if v["to_call"] == 0:
                return ("raise", v["current_bet"] + max(v["min_raise"], int(v["pot"] * 0.5)))
            if eq > pot_odds + 0.05:
                return ("call", 0)
            return ("fold", 0)
        if v["to_call"] == 0:
            return ("call", 0)
        if eq > pot_odds + 0.1:
            return ("call", 0)
        return ("fold", 0)


class Profiler(Strategy):
    """The adaptive exploiter: profiles opponents' public aggression, widens
    calling ranges against maniacs, ducks tight players' raises."""
    name = "Profiler"

    def _read(self, stats):
        if not stats or stats["acts"] < 5:
            return None
        freq = (stats["raises"] + stats["allins"]) / stats["acts"]
        if freq > 0.5:
            return "loose"
        if stats["acts"] >= 8 and freq < 0.15:
            return "tight"
        return None

    def act(self, v):
        profile = self._read(v["aggressor_stats"])
        if v["street"] == "preflop":
            score = chen(v["hole"])
            if v["to_call"] <= v["big_blind"]:
                if score >= 8:
                    return ("raise", v["current_bet"] + max(v["min_raise"], 3 * v["big_blind"]))
                if score >= 5:
                    return ("call", 0)
                return ("fold", 0)
            thresh = 9.0
            if profile == "loose":
                thresh = 6.5
            elif profile == "tight":
                thresh = 10.5
            if v["to_call"] > v["my_chips"] * 0.4 and profile != "loose":
                thresh += 1.5
            if score >= thresh:
                if profile == "loose" and score >= 8:
                    return ("raise", 10 ** 9)
                return ("call", 0)
            return ("fold", 0)
        eq = v["equity"]()
        adj = eq + (0.08 if profile == "loose" else 0.0) - (0.12 if profile == "tight" else 0.0)
        pot_odds = v["to_call"] / (v["pot"] + v["to_call"]) if v["to_call"] else 0.0
        if v["to_call"] == 0:
            if adj > 0.55:
                return ("raise", v["current_bet"] + max(v["min_raise"], int(v["pot"] * 0.6)))
            return ("call", 0)
        if adj > 0.8:
            return ("raise", 10 ** 9)
        if adj > pot_odds + 0.03:
            return ("call", 0)
        return ("fold", 0)


# ------------------------------------------------------------------- engine

class Player:
    def __init__(self, idx, chips, strategy):
        self.idx = idx
        self.chips = chips
        self.strategy = strategy
        self.hole = None
        self.folded = False
        self.all_in = False
        self.street_bet = 0
        self.contributed = 0


def betting_round(players, order, ctx, rng, stats):
    acted = set()
    i = 0
    while True:
        live = [p for p in players if not p.folded]
        if len(live) <= 1:
            return
        actors = [p for p in live if not p.all_in]
        if not actors:
            return
        if all(p in acted and p.street_bet == ctx["current_bet"] for p in actors):
            return
        p = order[i % len(order)]
        i += 1
        if p.folded or p.all_in:
            continue
        to_call = ctx["current_bet"] - p.street_bet
        pot = sum(q.contributed for q in players)
        n_live = len(live)
        st = stats[p.idx]
        st["acts"] += 1
        eq_cache = {}

        def equity(trials=MC_TRIALS, _p=p, _c=eq_cache):
            if trials not in _c:
                _c[trials] = mc_equity(_p.hole, ctx["community"], n_live - 1, trials, rng)
            return _c[trials]

        view = {
            "hole": p.hole,
            "street": ctx["street"],
            "community": tuple(ctx["community"]),
            "pot": pot,
            "to_call": to_call,
            "current_bet": ctx["current_bet"],
            "min_raise": ctx["min_raise"],
            "my_chips": p.chips,
            "my_street_bet": p.street_bet,
            "n_live": n_live,
            "big_blind": ctx["big_blind"],
            "relpos": ctx["relpos"][p.idx],
            "aggressor_stats": stats[ctx["aggressor"]] if ctx["aggressor"] is not None else None,
            "equity": equity,
            "rng": rng,
        }
        kind, amt = p.strategy.act(view)

        if kind == "raise":
            target = min(amt, p.street_bet + p.chips)
            if target <= ctx["current_bet"]:
                kind = "call"
            else:
                min_target = ctx["current_bet"] + ctx["min_raise"]
                if target < min_target:
                    target = min(min_target, p.street_bet + p.chips)
                if target <= ctx["current_bet"]:
                    kind = "call"
                else:
                    pay = target - p.street_bet
                    p.chips -= pay
                    p.contributed += pay
                    p.street_bet = target
                    if target - ctx["current_bet"] >= ctx["min_raise"]:
                        ctx["min_raise"] = target - ctx["current_bet"]
                    ctx["current_bet"] = target
                    ctx["aggressor"] = p.idx
                    st["raises"] += 1
                    if p.chips == 0:
                        p.all_in = True
                        st["allins"] += 1
                    acted = {p}
                    continue

        if kind == "fold" and to_call > 0:
            p.folded = True
            st["folds"] += 1
        else:
            pay = min(to_call, p.chips)
            p.chips -= pay
            p.contributed += pay
            p.street_bet += pay
            if p.chips == 0 and pay > 0:
                p.all_in = True
            if to_call > 0:
                st["calls"] += 1
        acted.add(p)


def settle(players, community):
    live = [p for p in players if not p.folded]
    total = sum(p.contributed for p in players)
    if len(live) == 1:
        live[0].chips += total
        return
    scores = {p.idx: eval7(list(p.hole) + community) for p in live}
    levels = sorted({p.contributed for p in players if p.contributed > 0})
    prev = 0
    for lv in levels:
        pot = sum(min(p.contributed, lv) - min(p.contributed, prev) for p in players)
        elig = [p for p in live if p.contributed >= lv]
        if not elig:
            elig = live
        best = max(scores[p.idx] for p in elig)
        winners = [p for p in elig if scores[p.idx] == best]
        share = pot // len(winners)
        rem = pot - share * len(winners)
        for j, w in enumerate(winners):
            w.chips += share + (1 if j < rem else 0)
        prev = lv


def play_hand(players, button_pos, sb, bb, rng, stats):
    n = len(players)
    deck = list(range(52))
    rng.shuffle(deck)
    for p in players:
        p.folded = False
        p.all_in = False
        p.street_bet = 0
        p.contributed = 0
        p.hole = (deck.pop(), deck.pop())

    if n == 2:
        sb_i, bb_i = button_pos, (button_pos + 1) % n
    else:
        sb_i, bb_i = (button_pos + 1) % n, (button_pos + 2) % n

    for seat, amount in ((sb_i, sb), (bb_i, bb)):
        p = players[seat]
        pay = min(amount, p.chips)
        p.chips -= pay
        p.contributed += pay
        p.street_bet = pay
        if p.chips == 0:
            p.all_in = True

    first_pre = (bb_i + 1) % n
    pre_order = [players[(first_pre + k) % n] for k in range(n)]
    relpos = {}
    for k, p in enumerate(pre_order):
        relpos[p.idx] = k / max(1, n - 1)

    ctx = {
        "street": "preflop",
        "community": [],
        "current_bet": bb,
        "min_raise": bb,
        "big_blind": bb,
        "aggressor": None,
        "relpos": relpos,
    }
    betting_round(players, pre_order, ctx, rng, stats)

    first_post = (button_pos + 1) % n
    post_order = [players[(first_post + k) % n] for k in range(n)]
    for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
        ctx["community"].extend(deck.pop() for _ in range(ncards))
        live = [p for p in players if not p.folded]
        if len(live) <= 1:
            break
        for p in players:
            p.street_bet = 0
        ctx.update(street=street, current_bet=0, min_raise=bb, aggressor=None)
        if len([p for p in live if not p.all_in]) >= 2:
            betting_round(players, post_order, ctx, rng, stats)

    settle(players, ctx["community"])


def play_tournament(rng):
    strategies = [AllInBot(), TheRock(), Berserker(), EVMachine(), SlowPlayer(), Profiler()]
    table = [Player(i, STARTING_CHIPS, strategies[i]) for i in range(6)]
    stats = [dict(acts=0, raises=0, allins=0, calls=0, folds=0) for _ in range(6)]
    button = rng.randrange(6)
    hand_no = 0
    while len(table) > 1:
        if hand_no >= MAX_HANDS:
            return max(table, key=lambda p: p.chips).idx
        hand_no += 1
        level = min(hand_no // BLIND_DOUBLE_EVERY, 12)
        sb = SMALL_BLIND << level
        bb = BIG_BLIND << level
        button %= len(table)
        play_hand(table, button, sb, bb, rng, stats)
        nxt = table[(button + 1) % len(table)]
        table = [p for p in table if p.chips > 0]
        button = table.index(nxt) if nxt in table else (button + 1) % len(table)
    return table[0].idx


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    rng = random.Random(seed)
    names = ["AllInBot", "TheRock", "Berserker", "EVMachine", "SlowPlayer", "Profiler"]
    wins = [0] * 6
    t0 = time.time()
    for s in range(n_sims):
        w = play_tournament(rng)
        wins[w] += 1
        if (s + 1) % 10 == 0:
            print(f"  ...{s + 1}/{n_sims} tournaments done", file=sys.stderr)
    dt = time.time() - t0

    print()
    print(f"WINNER WINNER CHICKEN DINNER — {n_sims} tournaments ({dt:.1f}s)")
    print(f"6 players, {STARTING_CHIPS} chips each, blinds {SMALL_BLIND}/{BIG_BLIND} doubling every {BLIND_DOUBLE_EVERY} hands")
    print("=" * 58)
    peak = max(wins) or 1
    for i in range(6):
        bar = "#" * round(40 * wins[i] / peak)
        tag = "  <-- the 'if my_turn then ALL IN fi' guy" if i == 0 else ""
        print(f"P{i + 1} {names[i]:<11}| {bar:<40} {wins[i]}{tag}")
    print("=" * 58)


if __name__ == "__main__":
    main()
