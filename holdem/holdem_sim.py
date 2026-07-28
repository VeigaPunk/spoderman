#!/usr/bin/env python3
"""Texas Hold'em tournament simulator.

6 players, equal starting stacks, blinds escalate, last player standing wins.
Player 1 shoves every hand. Players 2-6 run five distinct elaborate strategies.
No strategy can see another strategy's logic — they only observe public actions.
"""

import random
import itertools
from collections import Counter, defaultdict

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}


def new_deck():
    return [(RANK_VAL[r], s) for r in RANKS for s in SUITS]


# ---------------------------------------------------------------- hand eval

def evaluate5(cards):
    """Return comparable tuple: higher is better."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    uniq = sorted(set(ranks), reverse=True)
    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_high = 5
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][1] == 4:
        return (7, groups[0][0], groups[1][0])
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6, groups[0][0], groups[1][0])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if groups[0][1] == 3:
        kick = [r for r in ranks if r != groups[0][0]]
        return (3, groups[0][0], *kick)
    if groups[0][1] == 2 and groups[1][1] == 2:
        kick = [r for r in ranks if counts[r] == 1]
        return (2, groups[0][0], groups[1][0], *kick)
    if groups[0][1] == 2:
        kick = [r for r in ranks if r != groups[0][0]]
        return (1, groups[0][0], *kick)
    return (0, *ranks)


def best_hand(cards):
    return max(evaluate5(c) for c in itertools.combinations(cards, 5))


def hand_category_strength(hole, community):
    """Rough [0,1] strength of current made hand."""
    if not community:
        return chen_score(hole) / 20.0
    rank = best_hand(list(hole) + list(community))
    base = rank[0] / 8.0
    kicker = rank[1] / 14.0 if len(rank) > 1 else 0
    return min(1.0, base * 0.85 + kicker * 0.15)


def detect_draws(hole, community):
    """Return (flush_draw, open_ended) for 4-card draws using at least 1 hole card."""
    if not community or len(community) >= 5:
        return False, False
    cards = list(hole) + list(community)
    suits = Counter(c[1] for c in cards)
    flush_draw = any(
        n == 4 and any(h[1] == s for h in hole)
        for s, n in suits.items()
    )
    ranks = set(c[0] for c in cards)
    if 14 in ranks:
        ranks.add(1)
    open_ended = False
    for lo in range(1, 11):
        window = [r for r in range(lo, lo + 4) if r in ranks]
        if len(window) == 4 and any(h[0] in window or (h[0] == 14 and 1 in window) for h in hole):
            if lo > 1 and lo + 4 <= 14:
                open_ended = True
    return flush_draw, open_ended


def chen_score(hole):
    """Chen formula for preflop hand strength (max 20)."""
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2)
    if r1 == r2:
        return max(5, pts * 2)
    if s1 == s2:
        pts += 2
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        pts += 1
    return max(0, pts)


def monte_carlo_equity(hole, community, n_opps, rng, samples=40):
    """Estimated win probability vs n_opps random hands."""
    dead = set(hole) | set(community)
    deck = [c for c in new_deck() if c not in dead]
    wins = 0.0
    for _ in range(samples):
        rng.shuffle(deck)
        i = 0
        board = list(community)
        while len(board) < 5:
            board.append(deck[i]); i += 1
        mine = best_hand(list(hole) + board)
        best_opp = None
        for _ in range(n_opps):
            opp = best_hand([deck[i], deck[i + 1]] + board)
            i += 2
            if best_opp is None or opp > best_opp:
                best_opp = opp
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / samples


# ---------------------------------------------------------------- strategies

class Strategy:
    name = "base"

    def act(self, view, rng):
        raise NotImplementedError

    def observe(self, event):
        pass


class AllInMaximalist(Strategy):
    """Player 1: if my_turn then bet = All in. Fi."""
    name = "ALL-IN (P1)"

    def act(self, view, rng):
        return ("raise", view["my_stack"] + view["my_committed"])


class TightAggressive(Strategy):
    """TAG: premium ranges preflop (Chen), value-bets made hands, folds to
    pressure without equity, sizes bets to pot."""
    name = "TAG"

    def act(self, view, rng):
        v = view
        if not v["community"]:
            score = chen_score(v["hole"])
            thresh = 9 if v["position"] == "early" else 7 if v["position"] == "middle" else 6
            if score >= thresh + 3:
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] * 3)))
            if score >= thresh:
                if v["to_call"] <= v["my_stack"] * 0.12:
                    return ("call",)
                return ("fold",)
            if v["to_call"] == 0:
                return ("call",)
            return ("fold",)
        s = hand_category_strength(v["hole"], v["community"])
        fd, oesd = detect_draws(v["hole"], v["community"])
        if s >= 0.45:
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.75) + v["to_call"] + v["my_committed"])))
        if s >= 0.25 or fd or oesd:
            pot_odds = v["to_call"] / max(1, v["pot"] + v["to_call"])
            if v["to_call"] == 0 or pot_odds < 0.3:
                return ("call",)
        if v["to_call"] == 0:
            return ("call",)
        return ("fold",)


class LooseAggressive(Strategy):
    """LAG: wide ranges, relentless raising, semi-bluffs draws, pure bluffs
    at a controlled frequency, steals from late position."""
    name = "LAG"

    def act(self, view, rng):
        v = view
        if not v["community"]:
            score = chen_score(v["hole"])
            steal = v["position"] == "late" and v["current_bet"] <= v["bb"]
            if score >= 8 or (steal and score >= 4):
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] * 2 + v["to_call"])))
            if score >= 5 and v["to_call"] <= v["my_stack"] * 0.15:
                return ("call",)
            if v["to_call"] == 0:
                return ("call",)
            return ("fold",)
        s = hand_category_strength(v["hole"], v["community"])
        fd, oesd = detect_draws(v["hole"], v["community"])
        if s >= 0.4 or ((fd or oesd) and rng.random() < 0.7):
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] + v["to_call"] + v["my_committed"])))
        if v["to_call"] == 0:
            if rng.random() < 0.25:  # stab
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.6))))
            return ("call",)
        pot_odds = v["to_call"] / max(1, v["pot"] + v["to_call"])
        if s >= 0.2 and pot_odds < 0.35:
            return ("call",)
        return ("fold",)


class RockNit(Strategy):
    """Nit: only premium hands, prefers calling to raising, instantly folds
    to aggression unless holding near-nuts. Survives by attrition."""
    name = "NIT"

    def act(self, view, rng):
        v = view
        if not v["community"]:
            score = chen_score(v["hole"])
            if score >= 12:
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] * 2 + v["to_call"])))
            if score >= 9 and v["to_call"] <= v["my_stack"] * 0.1:
                return ("call",)
            if v["to_call"] == 0:
                return ("call",)
            return ("fold",)
        s = hand_category_strength(v["hole"], v["community"])
        if s >= 0.6:
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.5) + v["to_call"] + v["my_committed"])))
        if s >= 0.4 and v["to_call"] <= v["my_stack"] * 0.15:
            return ("call",)
        if v["to_call"] == 0:
            return ("call",)
        return ("fold",)


class PotOddsMathematician(Strategy):
    """GTO-ish: Monte Carlo equity vs pot odds, position-adjusted, bets for
    value when equity exceeds required threshold with margin."""
    name = "MATH"

    def act(self, view, rng):
        v = view
        n_opps = max(1, v["num_active"] - 1)
        if not v["community"]:
            score = chen_score(v["hole"])
            eq = min(0.95, score / 20 + 0.15)
        else:
            eq = monte_carlo_equity(v["hole"], v["community"], min(n_opps, 3), rng)
        pos_bonus = {"early": -0.03, "middle": 0.0, "late": 0.04}[v["position"]]
        eq += pos_bonus
        pot_odds = v["to_call"] / max(1, v["pot"] + v["to_call"])
        if eq > 0.62:
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] + v["to_call"] + v["my_committed"])))
        if v["to_call"] == 0:
            if eq > 0.5:
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.66))))
            return ("call",)
        if eq > pot_odds + 0.05:
            return ("call",)
        return ("fold",)


class AdaptiveProfiler(Strategy):
    """Opponent modeler: tracks each seat's aggression frequency and showdown
    behavior, widens calling ranges vs maniacs, bluffs vs tight players,
    tightens vs unknown aggression."""
    name = "ADAPT"

    def __init__(self):
        self.aggr = defaultdict(lambda: [1, 2])  # seat -> [raises, actions]

    def observe(self, event):
        kind, seat = event[0], event[1]
        if kind in ("raise", "call", "fold"):
            self.aggr[seat][1] += 1
            if kind == "raise":
                self.aggr[seat][0] += 1

    def _maniac_at_table(self, view):
        rates = [self.aggr[s][0] / self.aggr[s][1] for s in view["active_seats"] if s != view["my_seat"]]
        return max(rates, default=0) > 0.7

    def act(self, view, rng):
        v = view
        maniac = self._maniac_at_table(v)
        if not v["community"]:
            score = chen_score(v["hole"])
            # vs a shover: flat premium threshold, call wide-ish with real hands
            call_thresh = 8 if maniac else 9
            if score >= 11:
                return ("raise", min(v["all_in_to"], max(v["min_raise_to"], v["pot"] * 2 + v["to_call"])))
            if score >= call_thresh:
                # willing to call big vs maniac since their range is any-two
                cap = 1.0 if maniac and score >= 10 else 0.15
                if v["to_call"] <= v["my_stack"] * cap:
                    return ("call",)
            if v["to_call"] == 0:
                return ("call",)
            return ("fold",)
        s = hand_category_strength(v["hole"], v["community"])
        fd, oesd = detect_draws(v["hole"], v["community"])
        thresh = 0.3 if maniac else 0.45
        if s >= thresh:
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.8) + v["to_call"] + v["my_committed"])))
        if not maniac and v["to_call"] == 0 and rng.random() < 0.2:
            return ("raise", min(v["all_in_to"], max(v["min_raise_to"], int(v["pot"] * 0.5))))
        pot_odds = v["to_call"] / max(1, v["pot"] + v["to_call"])
        if (s >= 0.22 or fd or oesd) and (v["to_call"] == 0 or pot_odds < 0.33):
            return ("call",)
        if v["to_call"] == 0:
            return ("call",)
        return ("fold",)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.reset_hand()

    def reset_hand(self):
        self.hole = None
        self.in_hand = False
        self.committed_round = 0
        self.committed_total = 0
        self.all_in = False


def position_of(idx_from_button, n):
    if n <= 3:
        return "late"
    frac = idx_from_button / n
    if frac < 0.34:
        return "late"
    if frac < 0.67:
        return "early"
    return "middle"


class Tournament:
    def __init__(self, players, rng, sb=10, bb=20, blind_growth_every=10):
        self.players = players
        self.rng = rng
        self.sb, self.bb = sb, bb
        self.growth_every = blind_growth_every
        self.button = 0
        self.hands_played = 0

    def alive(self):
        return [p for p in self.players if p.stack > 0]

    def run(self):
        while len(self.alive()) > 1 and self.hands_played < 3000:
            self.play_hand()
            self.hands_played += 1
            if self.hands_played % self.growth_every == 0:
                self.sb *= 2
                self.bb *= 2
        alive = self.alive()
        return max(alive, key=lambda p: p.stack)

    def _post(self, p, amount):
        amt = min(amount, p.stack)
        p.stack -= amt
        p.committed_round += amt
        p.committed_total += amt
        if p.stack == 0:
            p.all_in = True
        return amt

    def play_hand(self):
        alive = self.alive()
        n = len(alive)
        for p in self.players:
            p.reset_hand()
        for p in alive:
            p.in_hand = True
        order = sorted(alive, key=lambda p: p.seat)
        # rotate so order starts left of button
        self.button %= len(order)
        seats = order[self.button + 1:] + order[:self.button + 1]

        deck = new_deck()
        self.rng.shuffle(deck)
        for p in seats:
            p.hole = (deck.pop(), deck.pop())

        if n == 2:
            sb_p, bb_p = seats[-1], seats[0]  # button posts SB heads-up
            first_pre = sb_p
        else:
            sb_p, bb_p = seats[0], seats[1]
            first_pre = seats[2 % n]
        self._post(sb_p, self.sb)
        self._post(bb_p, self.bb)

        community = []
        current_bet = self.bb
        self._betting_round(seats, community, current_bet, first_pre)

        for n_cards in (3, 1, 1):
            if self._hand_over(seats):
                break
            deck.pop()  # burn
            community.extend(deck.pop() for _ in range(n_cards))
            for p in seats:
                p.committed_round = 0
            live = [p for p in seats if p.in_hand and not p.all_in]
            if len(live) >= 2:
                self._betting_round(seats, community, 0, seats[0] if seats[0].in_hand else None)

        # complete board if runout needed
        contenders = [p for p in seats if p.in_hand]
        if len(contenders) > 1:
            while len(community) < 5:
                deck.pop()
                community.append(deck.pop())
        self._award_pots(seats, community)
        self.button = (self.button + 1) % max(1, len(self.alive()))

    def _hand_over(self, seats):
        return sum(1 for p in seats if p.in_hand) <= 1

    def _betting_round(self, seats, community, current_bet, first):
        n = len(seats)
        min_raise = self.bb
        if first is None:
            first = next((p for p in seats if p.in_hand and not p.all_in), None)
            if first is None:
                return
        start = seats.index(first)
        pending = {p.seat for p in seats if p.in_hand and not p.all_in}
        i = start
        guard = 0
        while pending and guard < 500:
            guard += 1
            p = seats[i % n]
            i += 1
            if p.seat not in pending:
                continue
            if not p.in_hand or p.all_in:
                pending.discard(p.seat)
                continue
            action = self._get_action(p, seats, community, current_bet, min_raise)
            pending.discard(p.seat)
            kind = action[0]
            to_call = current_bet - p.committed_round
            if kind == "fold":
                if to_call > 0:
                    p.in_hand = False
                self._broadcast(("fold" if to_call > 0 else "call", p.seat))
            elif kind == "call":
                self._post(p, to_call)
                self._broadcast(("call", p.seat))
            elif kind == "raise":
                target = action[1]
                max_to = p.committed_round + p.stack
                target = min(target, max_to)
                legal_min = current_bet + min_raise
                if target < legal_min and target < max_to:
                    # insufficient raise -> treat as call
                    self._post(p, to_call)
                    self._broadcast(("call", p.seat))
                    continue
                if target <= current_bet:
                    self._post(p, to_call)
                    self._broadcast(("call", p.seat))
                    continue
                raise_by = target - current_bet
                self._post(p, target - p.committed_round)
                if raise_by >= min_raise:
                    min_raise = raise_by
                current_bet = target
                self._broadcast(("raise", p.seat))
                pending = {q.seat for q in seats
                           if q.in_hand and not q.all_in and q.seat != p.seat}
            if self._hand_over(seats):
                return

    def _get_action(self, p, seats, community, current_bet, min_raise):
        pot = sum(q.committed_total for q in seats)
        active = [q for q in seats if q.in_hand]
        idx_from_button = (seats.index(p)) % len(seats)
        view = {
            "hole": p.hole,
            "community": tuple(community),
            "pot": pot,
            "to_call": max(0, current_bet - p.committed_round),
            "current_bet": current_bet,
            "min_raise_to": current_bet + min_raise,
            "all_in_to": p.committed_round + p.stack,
            "my_stack": p.stack,
            "my_committed": p.committed_round,
            "my_seat": p.seat,
            "bb": self.bb,
            "num_active": len(active),
            "active_seats": [q.seat for q in active],
            "position": position_of(idx_from_button, len(seats)),
        }
        try:
            return p.strategy.act(view, self.rng)
        except Exception:
            return ("fold",)

    def _broadcast(self, event):
        for p in self.players:
            p.strategy.observe(event)

    def _award_pots(self, seats, community):
        contenders = [p for p in seats if p.in_hand]
        contribs = {p.seat: p.committed_total for p in seats}
        if len(contenders) == 1:
            contenders[0].stack += sum(contribs.values())
            return
        ranks = {p.seat: best_hand(list(p.hole) + list(community)) for p in contenders}
        levels = sorted(set(c for c in contribs.values() if c > 0))
        prev = 0
        for lvl in levels:
            pot = 0
            for seat, c in contribs.items():
                pot += max(0, min(c, lvl) - prev)
            eligible = [p for p in contenders if contribs[p.seat] >= lvl]
            if not eligible:
                continue
            best = max(ranks[p.seat] for p in eligible)
            winners = [p for p in eligible if ranks[p.seat] == best]
            share, rem = divmod(pot, len(winners))
            for j, w in enumerate(winners):
                w.stack += share + (1 if j < rem else 0)
            prev = lvl


# ---------------------------------------------------------------- runner

STRATEGY_FACTORY = [
    ("Player 1", AllInMaximalist),
    ("Player 2", TightAggressive),
    ("Player 3", LooseAggressive),
    ("Player 4", RockNit),
    ("Player 5", PotOddsMathematician),
    ("Player 6", AdaptiveProfiler),
]

START_STACK = 1000


def run_sims(n_sims=100, seed=42):
    winners = Counter()
    rng_master = random.Random(seed)
    for sim in range(n_sims):
        rng = random.Random(rng_master.getrandbits(64))
        players = [Player(i, name, cls(), START_STACK)
                   for i, (name, cls) in enumerate(STRATEGY_FACTORY)]
        champ = Tournament(players, rng).run()
        winners[champ.name] += 1
    return winners


def print_histogram(winners, n_sims):
    print(f"\n  WINNER HISTOGRAM — {n_sims} tournaments, 6 players, {START_STACK} chips each")
    print("  " + "=" * 66)
    width = 50
    top = max(winners.values())
    for name, cls in STRATEGY_FACTORY:
        w = winners.get(name, 0)
        bar = "#" * round(w / top * width) if top else ""
        label = f"{name} [{cls.name}]"
        print(f"  {label:<24} {bar:<{width}} {w:>3}  ({w / n_sims:.0%})")
    print("  " + "=" * 66)
    champ = winners.most_common(1)[0]
    print(f"  Winner winner chicken dinner: {champ[0]} with {champ[1]}/{n_sims} titles\n")


if __name__ == "__main__":
    N = 100
    winners = run_sims(N)
    print_histogram(winners, N)
