#!/usr/bin/env python3
"""
No-Limit Texas Hold'em tournament simulator.

Six players sit down with equal stacks. Five of them run elaborate,
hand-crafted strategies. Player #1 ("SuflairGPT") runs the entire strategy:

    if my_turn:
        bet = ALL IN
    fi

No player knows any other player's algorithm — they only observe public
actions at the table (which is exactly what the adaptive strategy exploits).

Run: python3 holdem_sim.py [--sims 100] [--seed 42]
Outputs a histogram of tournament winners (last player standing).
"""

import argparse
import random
from collections import Counter

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------

RANK_NAMES = {11: "J", 12: "Q", 13: "K", 14: "A"}
FULL_DECK = [(r, s) for r in range(2, 15) for s in range(4)]


def straight_high(rank_set):
    """Highest straight top-card in a set of ranks, 0 if none (wheel = 5)."""
    for high in range(14, 5, -1):
        if all(r in rank_set for r in range(high - 4, high + 1)):
            return high
    if {14, 2, 3, 4, 5} <= rank_set:
        return 5
    return 0


def evaluate7(cards):
    """Best 5-card hand from 5-7 cards -> comparable tuple (bigger wins)."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    rcount = Counter(ranks)
    scount = Counter(c[1] for c in cards)

    flush_suit = None
    for s, n in scount.items():
        if n >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        franks = sorted((c[0] for c in cards if c[1] == flush_suit), reverse=True)
        sf = straight_high(set(franks))
        if sf:
            return (8, sf)

    # groups sorted by (count, rank) descending
    groups = sorted(rcount.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    if groups[0][1] == 4:
        quad = groups[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0])

    if flush_suit is not None:
        return (5, *franks[:5])

    st = straight_high(set(ranks))
    if st:
        return (4, st)

    if groups[0][1] == 3:
        trip = groups[0][0]
        kick = [r for r in ranks if r != trip][:2]
        return (3, trip, *kick)

    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hi, lo = groups[0][0], groups[1][0]
        kicker = max(r for r in ranks if r != hi and r != lo)
        return (2, hi, lo, kicker)

    if groups[0][1] == 2:
        pair = groups[0][0]
        kick = [r for r in ranks if r != pair][:3]
        return (1, pair, *kick)

    return (0, *ranks[:5])


def chen_score(hole):
    """Chen formula: quick preflop hand quality (AA=20, 72o≈-1)."""
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    base = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if s1 == s2:
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        score += 1
    return score


def estimate_equity(rng, hole, community, n_opponents, trials):
    """Monte-Carlo win probability vs. n random opponent hands."""
    known = set(hole) | set(community)
    deck = [c for c in FULL_DECK if c not in known]
    need_board = 5 - len(community)
    wins = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need_board + 2 * n_opponents)
        board = list(community) + draw[:need_board]
        mine = evaluate7(list(hole) + board)
        best_opp = None
        for i in range(n_opponents):
            oh = draw[need_board + 2 * i: need_board + 2 * i + 2]
            v = evaluate7(oh + board)
            if best_opp is None or v > best_opp:
                best_opp = v
        if mine > best_opp:
            wins += 1
        elif mine == best_opp:
            wins += 0.5
    return wins / trials


# ---------------------------------------------------------------------------
# Strategies. Each sees only a public View + its own hole cards.
# ---------------------------------------------------------------------------

class View:
    """What a strategy is allowed to see when acting."""
    __slots__ = ("hole", "community", "street", "pot", "to_call", "current_bet",
                 "min_raise", "stack", "street_committed", "big_blind",
                 "players_in_hand", "position", "facing_allin", "was_aggressor",
                 "stats", "my_id", "rng")


class Strategy:
    name = "?"

    def act(self, v):
        """Return ('fold', 0) | ('call', 0) | ('raise', total_street_bet)."""
        raise NotImplementedError


class AllInGPT(Strategy):
    """Player #1. The whole algorithm:  if my_turn then bet = all in fi"""
    name = "SuflairGPT"

    def act(self, v):
        return ("raise", v.street_committed + v.stack)


class TheRock(Strategy):
    """Tight-aggressive nit: premium hands only, never limps, respects
    aggression, pays off with two pair or better."""
    name = "TheRock"

    def act(self, v):
        pot_bet = max(v.big_blind, int(v.pot * 0.6))
        if v.street == "preflop":
            c = chen_score(v.hole)
            open_need = 7 + min(2, v.position // 2)  # looser near the button
            if v.to_call <= v.big_blind and v.current_bet <= v.big_blind:
                if c >= open_need:
                    return ("raise", 3 * v.big_blind)
                return ("fold", 0) if v.to_call > 0 else ("call", 0)
            # facing a raise / shove
            if c >= 11 or (c >= 9.5 and v.to_call <= 4 * v.big_blind):
                if c >= 12:
                    return ("raise", v.current_bet + max(v.min_raise, v.current_bet * 2))
                return ("call", 0)
            return ("fold", 0)

        made = evaluate7(list(v.hole) + list(v.community))
        cat = made[0]
        if cat >= 2:  # two pair or better: value all the way
            if v.to_call == 0:
                return ("raise", v.street_committed + pot_bet)
            return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
        top_board = max(c[0] for c in v.community)
        has_top_pair = cat == 1 and made[1] >= top_board
        if v.to_call == 0:
            if has_top_pair or (v.was_aggressor and v.rng.random() < 0.6):
                return ("raise", v.street_committed + pot_bet)
            return ("call", 0)  # check
        if has_top_pair and v.to_call <= v.pot // 3:
            return ("call", 0)
        return ("fold", 0)


class TheMaverick(Strategy):
    """Loose-aggressive: wide opens, relentless barrels and semi-bluffs,
    but bails when the pressure comes back without equity."""
    name = "TheMaverick"

    def _draws(self, v):
        cards = list(v.hole) + list(v.community)
        suits = Counter(c[1] for c in cards)
        flush_draw = any(n == 4 for n in suits.values())
        rset = set(c[0] for c in cards)
        oesd = any(all(r in rset for r in range(lo, lo + 4)) for lo in range(2, 12))
        return flush_draw, oesd

    def act(self, v):
        r = v.rng.random()
        if v.street == "preflop":
            c = chen_score(v.hole)
            if v.to_call <= v.big_blind and v.current_bet <= v.big_blind:
                if c >= 5 or r < 0.15:
                    return ("raise", int(2.5 * v.big_blind))
                return ("fold", 0) if v.to_call > 0 else ("call", 0)
            if c >= 10:
                return ("raise", v.current_bet + max(v.min_raise, v.current_bet))
            if c >= 7 and v.to_call <= 5 * v.big_blind:
                return ("call", 0)
            if v.to_call <= 2 * v.big_blind and r < 0.4:
                return ("call", 0)
            return ("fold", 0)

        made = evaluate7(list(v.hole) + list(v.community))
        cat = made[0]
        flush_draw, oesd = self._draws(v)
        strong_draw = flush_draw or oesd
        bet = max(v.big_blind, int(v.pot * 0.75))
        if v.to_call == 0:
            if cat >= 1 or strong_draw or r < 0.45:
                return ("raise", v.street_committed + bet)
            return ("call", 0)
        if cat >= 2:
            return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
        if strong_draw and v.to_call <= int(v.pot * 0.6):
            if r < 0.3:  # semi-bluff raise
                return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
            return ("call", 0)
        if cat == 1 and v.to_call <= v.pot // 2:
            return ("call", 0)
        return ("fold", 0)


class TheMathematician(Strategy):
    """Pure pot-odds machine: Monte-Carlo equity vs. required price, with a
    thin value-raise rule. Feels nothing, calculates everything."""
    name = "TheMathematician"

    def act(self, v):
        n_opp = max(1, v.players_in_hand - 1)
        if v.street == "preflop":
            trials = 40
        else:
            trials = 60
        eq = estimate_equity(v.rng, v.hole, v.community, n_opp, trials)
        pot_after = v.pot + v.to_call
        price = v.to_call / pot_after if pot_after > 0 else 0.0

        if v.to_call == 0:
            if eq > 0.55 + 0.05 * (n_opp - 1):
                return ("raise", v.street_committed + max(v.big_blind, int(v.pot * 0.66)))
            return ("call", 0)
        if eq > max(0.62, price + 0.18):
            return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
        if eq >= price + 0.03:
            return ("call", 0)
        return ("fold", 0)


class TheProfessor(Strategy):
    """Positional player: range charts by seat, pot control out of position,
    pounces when checked to in position."""
    name = "TheProfessor"

    def act(self, v):
        late = v.position <= 1  # button or cutoff-ish
        if v.street == "preflop":
            c = chen_score(v.hole)
            need = 6 if late else (7.5 if v.position <= 3 else 9)
            if v.to_call <= v.big_blind and v.current_bet <= v.big_blind:
                if c >= need:
                    return ("raise", 3 * v.big_blind)
                return ("fold", 0) if v.to_call > 0 else ("call", 0)
            if c >= 10.5:
                return ("raise", v.current_bet + max(v.min_raise, v.current_bet))
            if c >= need + 1.5 and v.to_call <= 4 * v.big_blind:
                return ("call", 0)
            return ("fold", 0)

        made = evaluate7(list(v.hole) + list(v.community))
        cat = made[0]
        if v.to_call == 0:
            if cat >= 2:
                return ("raise", v.street_committed + max(v.big_blind, int(v.pot * 0.7)))
            if late and (cat == 1 or v.rng.random() < 0.5):
                return ("raise", v.street_committed + max(v.big_blind, v.pot // 2))
            return ("call", 0)
        if cat >= 3:
            return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
        if cat == 2:
            return ("call", 0)
        if cat == 1 and v.to_call <= v.pot // 3 and late:
            return ("call", 0)
        return ("fold", 0)


class TheShark(Strategy):
    """Adaptive predator: profiles every opponent from public actions
    (VPIP, aggression, shove frequency) and adjusts. Calls chronic
    shovers wide, tightens vs. nits, value-bets stations."""
    name = "TheShark"

    def act(self, v):
        stats = v.stats
        # Is the current aggression coming from a maniac shover?
        maniac_shove = False
        if v.facing_allin is not None:
            s = stats.get(v.facing_allin)
            if s and s["hands"] >= 4 and s["allins"] / max(1, s["hands"]) > 0.5:
                maniac_shove = True

        if v.street == "preflop":
            c = chen_score(v.hole)
            (r1, _), (r2, _) = v.hole
            if maniac_shove:
                # vs an always-all-in bot any pair / big ace / broadway crushes
                if r1 == r2 or c >= 8 or (max(r1, r2) == 14 and min(r1, r2) >= 9):
                    return ("call", 0)
                return ("fold", 0)
            if v.to_call <= v.big_blind and v.current_bet <= v.big_blind:
                if c >= 8 - (1 if v.position <= 1 else 0):
                    return ("raise", 3 * v.big_blind)
                return ("fold", 0) if v.to_call > 0 else ("call", 0)
            if c >= 11:
                return ("raise", v.current_bet + max(v.min_raise, v.current_bet))
            if c >= 9 and v.to_call <= 4 * v.big_blind:
                return ("call", 0)
            return ("fold", 0)

        made = evaluate7(list(v.hole) + list(v.community))
        cat = made[0]
        if maniac_shove and cat >= 1:
            return ("call", 0)
        if cat >= 2:
            if v.to_call == 0:
                return ("raise", v.street_committed + max(v.big_blind, int(v.pot * 0.8)))
            return ("raise", v.current_bet + max(v.min_raise, v.pot // 2))
        top_board = max(c[0] for c in v.community)
        has_top_pair = cat == 1 and made[1] >= top_board
        if v.to_call == 0:
            if has_top_pair or (v.was_aggressor and v.rng.random() < 0.5):
                return ("raise", v.street_committed + max(v.big_blind, int(v.pot * 0.6)))
            return ("call", 0)
        if has_top_pair and v.to_call <= v.pot // 2:
            return ("call", 0)
        if cat == 1 and v.to_call <= v.pot // 4:
            return ("call", 0)
        return ("fold", 0)


# ---------------------------------------------------------------------------
# Tournament engine (no-limit, side pots, escalating blinds)
# ---------------------------------------------------------------------------

class Seat:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack
        # per-hand state
        self.hole = None
        self.folded = False
        self.allin = False
        self.street_committed = 0
        self.total_committed = 0


class Tournament:
    def __init__(self, strategies, rng, start_stack=1000):
        self.rng = rng
        self.seats = [Seat(i + 1, s, start_stack) for i, s in enumerate(strategies)]
        self.stats = {seat.pid: {"hands": 0, "vpip": 0, "raises": 0, "allins": 0}
                      for seat in self.seats}
        self.button = rng.randrange(len(self.seats))

    def alive(self):
        return [s for s in self.seats if s.stack > 0]

    def run(self, max_hands=2000):
        hand_no = 0
        while len(self.alive()) > 1 and hand_no < max_hands:
            level = hand_no // 15
            bb = min(20 * (2 ** level), 4000)
            self.play_hand(bb)
            hand_no += 1
        survivors = self.alive()
        return max(survivors, key=lambda s: s.stack).pid

    # -- one hand ----------------------------------------------------------
    def play_hand(self, big_blind):
        alive = self.alive()
        n = len(alive)
        # rotate button among live seats
        self.button = (self.button + 1) % len(self.seats)
        while self.seats[self.button].stack <= 0:
            self.button = (self.button + 1) % len(self.seats)

        order = self._ring(self.button)  # live seats, button first
        for s in alive:
            s.folded = False
            s.allin = False
            s.street_committed = 0
            s.total_committed = 0
            self.stats[s.pid]["hands"] += 1

        deck = FULL_DECK[:]
        self.rng.shuffle(deck)
        di = 0
        for s in order:
            s.hole = (deck[di], deck[di + 1])
            di += 2
        board_cards = deck[di:di + 5]
        di += 5

        sb_amt, bb_amt = big_blind // 2, big_blind
        if n == 2:
            sb_seat, bb_seat = order[0], order[1]   # heads-up: button = SB
        else:
            sb_seat, bb_seat = order[1], order[2]
        self._commit(sb_seat, min(sb_amt, sb_seat.stack))
        self._commit(bb_seat, min(bb_amt, bb_seat.stack))

        preflop_order = self._after(bb_seat, order)
        self.community = []
        aggressor = {s.pid: False for s in order}

        self._betting(order, preflop_order, big_blind, "preflop",
                      current=bb_amt, aggressor=aggressor, bb=big_blind)

        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len([s for s in order if not s.folded]) <= 1:
                break
            self.community.extend(board_cards[len(self.community):
                                              len(self.community) + ncards])
            for s in order:
                s.street_committed = 0
            live = [s for s in order if not s.folded and not s.allin]
            if len(live) > 1:
                street_order = self._after(order[0], order)  # left of button first
                self._betting(order, street_order, big_blind, street,
                              current=0, aggressor=aggressor, bb=big_blind)
        # deal remaining board if showdown with all-ins
        if len([s for s in order if not s.folded]) > 1:
            self.community = board_cards[:5]
        self._payout(order)

    def _ring(self, button_idx):
        n = len(self.seats)
        ring = []
        for k in range(n):
            s = self.seats[(button_idx + k) % n]
            if s.stack > 0 or s.total_committed > 0:
                ring.append(s)
        return [s for s in ring if s.stack > 0]

    @staticmethod
    def _after(seat, order):
        """Action order starting with the seat after `seat`."""
        i = order.index(seat)
        return order[i + 1:] + order[:i + 1]

    def _commit(self, seat, amount):
        amount = min(amount, seat.stack)
        seat.stack -= amount
        seat.street_committed += amount
        seat.total_committed += amount
        if seat.stack == 0:
            seat.allin = True

    def _betting(self, order, act_order, big_blind, street, current, aggressor, bb):
        min_raise = big_blind
        pot = lambda: sum(s.total_committed for s in order)
        need_action = {s.pid for s in act_order if not s.folded and not s.allin}
        queue = act_order[:]
        qi = 0
        guard = 0
        while need_action and guard < 200:
            guard += 1
            seat = queue[qi % len(queue)]
            qi += 1
            if seat.pid not in need_action or seat.folded or seat.allin:
                continue
            if len([s for s in order if not s.folded]) <= 1:
                break

            to_call = current - seat.street_committed
            v = View()
            v.hole = seat.hole
            v.community = tuple(self.community)
            v.street = street
            v.pot = pot()
            v.to_call = max(0, to_call)
            v.current_bet = current
            v.min_raise = min_raise
            v.stack = seat.stack
            v.street_committed = seat.street_committed
            v.big_blind = bb
            v.players_in_hand = len([s for s in order if not s.folded])
            # 0 = button (best position), 1 = cutoff, ... blinds are highest
            v.position = (len(order) - order.index(seat)) % len(order)
            allin_agg = [s for s in order
                         if s.allin and s.street_committed >= current and s is not seat
                         and current > bb]
            v.facing_allin = allin_agg[0].pid if (allin_agg and to_call > 0) else None
            v.was_aggressor = aggressor.get(seat.pid, False)
            v.stats = self.stats
            v.my_id = seat.pid
            v.rng = self.rng

            try:
                action, amount = seat.strategy.act(v)
            except Exception:
                action, amount = "fold", 0

            if action == "fold" and to_call <= 0:
                action = "call"  # never fold for free

            if action == "fold":
                seat.folded = True
                need_action.discard(seat.pid)
                continue

            if street == "preflop" and (to_call > 0 or action == "raise"):
                self.stats[seat.pid]["vpip"] += 1 if action != "fold" else 0

            if action == "call":
                self._commit(seat, max(0, to_call))
                need_action.discard(seat.pid)
                continue

            # raise: amount = target street total
            target = max(amount, current + min_raise)
            target = min(target, seat.street_committed + seat.stack)
            if target <= current:  # can't actually raise -> treat as call
                self._commit(seat, max(0, to_call))
                need_action.discard(seat.pid)
                continue
            put = target - seat.street_committed
            self._commit(seat, put)
            self.stats[seat.pid]["raises"] += 1
            if seat.allin:
                self.stats[seat.pid]["allins"] += 1
            raise_size = target - current
            if raise_size >= min_raise:
                min_raise = raise_size
            current = target
            for s in aggressor:
                aggressor[s] = False
            aggressor[seat.pid] = True
            need_action = {s.pid for s in order
                           if not s.folded and not s.allin and s is not seat}
            need_action.discard(seat.pid)

    def _payout(self, order):
        contenders = [s for s in order if not s.folded]
        if len(contenders) == 1:
            contenders[0].stack += sum(s.total_committed for s in order)
            for s in order:
                s.total_committed = 0
            return

        scores = {s.pid: evaluate7(list(s.hole) + list(self.community))
                  for s in contenders}
        levels = sorted(set(s.total_committed for s in contenders))
        prev = 0
        remainders = {s.pid: s.total_committed for s in order}
        for level in levels:
            slice_total = 0
            for s in order:
                take = max(0, min(remainders[s.pid], level - prev))
                slice_total += take
                remainders[s.pid] -= take
            eligible = [s for s in contenders if s.total_committed >= level]
            best = max(scores[s.pid] for s in eligible)
            winners = [s for s in eligible if scores[s.pid] == best]
            share = slice_total // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += slice_total - share * len(winners)  # odd chips
            prev = level
        # any leftover contributions (folded players above max level) — impossible,
        # but sweep to best hand to conserve chips
        leftover = sum(remainders.values())
        if leftover:
            best_seat = max(contenders, key=lambda s: scores[s.pid])
            best_seat.stack += leftover
        for s in order:
            s.total_committed = 0


# ---------------------------------------------------------------------------
# Simulation driver + histogram
# ---------------------------------------------------------------------------

STRATEGY_ROSTER = [AllInGPT, TheRock, TheMaverick, TheMathematician,
                   TheProfessor, TheShark]


def run_sims(n_sims, seed, start_stack=1000):
    master = random.Random(seed)
    wins = Counter()
    names = {i + 1: cls.name for i, cls in enumerate(STRATEGY_ROSTER)}
    for sim in range(n_sims):
        rng = random.Random(master.randrange(2 ** 63))
        t = Tournament([cls() for cls in STRATEGY_ROSTER], rng, start_stack)
        winner = t.run()
        wins[winner] += 1
    return wins, names


def print_histogram(wins, names, n_sims):
    print()
    print("=" * 66)
    print(f"  WINNER WINNER CHICKEN DINNER — {n_sims} tournament simulations")
    print("=" * 66)
    width = 40
    top = max(wins.values()) if wins else 1
    for pid in sorted(names):
        label = f"P{pid} {names[pid]:<16}"
        w = wins.get(pid, 0)
        bar = "█" * max(1 if w else 0, round(w / top * width))
        print(f"  {label} {bar:<{width}} {w:3d}  ({100.0 * w / n_sims:5.1f}%)")
    print("=" * 66)
    total_chickens = sum(wins.values())
    assert total_chickens == n_sims, "lost a chicken dinner somewhere"


def main():
    ap = argparse.ArgumentParser(description="Hold'em strategy showdown")
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--stack", type=int, default=1000)
    args = ap.parse_args()

    print(f"Dealing {args.sims} full tournaments (seed={args.seed}, "
          f"start stack={args.stack}, blinds 10/20 doubling every 15 hands)...")
    wins, names = run_sims(args.sims, args.seed, args.stack)
    print_histogram(wins, names, args.sims)

    gpt_wins = wins.get(1, 0)
    best_pid = max(wins, key=lambda p: wins[p])
    if best_pid != 1:
        print(f"\n  SuflairGPT ('if my_turn then bet = all in fi') won "
              f"{gpt_wins}/{args.sims}.")
        print(f"  {names[best_pid]} won {wins[best_pid]}/{args.sims}. "
              f"Thoughts and prayers, SuflairGPT.")
    else:
        print(f"\n  ...SuflairGPT actually won the most ({gpt_wins}). "
              f"Variance is a cruel god.")


if __name__ == "__main__":
    main()
