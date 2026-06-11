#!/usr/bin/env python3
"""
Texas Hold'em Tournament Simulation
Player 1: if my_turn then bet = All In fi
Players 2-6: 5 elaborate strategies
100 tournaments — who becomes the last player standing?
"""

import random
from collections import Counter
from itertools import combinations

# ── Constants ──────────────────────────────────────────────────────────────────
RANKS    = '23456789TJQKA'
SUITS    = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20
NUM_PLAYERS    = 6
NUM_SIMS       = 100

# ── Cards ──────────────────────────────────────────────────────────────────────

class Card:
    __slots__ = ('rank', 'suit', 'value')
    def __init__(self, rank, suit):
        self.rank  = rank
        self.suit  = suit
        self.value = RANK_VAL[rank]
    def __repr__(self):
        return f"{self.rank}{self.suit}"

def make_deck():
    return [Card(r, s) for r in RANKS for s in SUITS]

def evaluate_5(hand):
    """Comparable tuple for a 5-card hand."""
    vals  = sorted([c.value for c in hand], reverse=True)
    suits = [c.suit for c in hand]
    flush = len(set(suits)) == 1
    uniq  = sorted(set(vals), reverse=True)
    straight = len(uniq) == 5 and uniq[0] - uniq[4] == 4
    if vals == [14, 5, 4, 3, 2]:
        straight, vals = True, [5, 4, 3, 2, 1]
    cnt      = Counter(vals)
    by_cnt   = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    grp      = [c for _, c in by_cnt]
    rbc      = [r for r, _ in by_cnt]
    if straight and flush:   return (8, vals[0])
    if grp[0] == 4:          return (7, rbc[0], rbc[1])
    if grp[:2] == [3, 2]:    return (6, rbc[0], rbc[1])
    if flush:                return (5, *vals)
    if straight:             return (4, vals[0])
    if grp[0] == 3:          return (3, rbc[0], rbc[1], rbc[2])
    if grp[:2] == [2, 2]:    return (2, max(rbc[:2]), min(rbc[:2]), rbc[2])
    if grp[0] == 2:          return (1, rbc[0], *rbc[1:])
    return (0, *vals)

def best_hand(cards):
    if len(cards) < 5:
        return (0,)
    return max(evaluate_5(list(c)) for c in combinations(cards, 5))

def hand_strength(hole, community):
    """0..1 hand strength from category + sub-rank."""
    bh  = best_hand(hole + community)
    cat = bh[0]
    sub = bh[1] / 14.0 * 0.099 if len(bh) > 1 else 0
    return min(1.0, cat / 8.0 + sub)

def preflop_score(hole):
    """0..1 pre-flop hand quality."""
    a, b   = hole
    hi, lo = max(a.value, b.value), min(a.value, b.value)
    score  = (hi + lo - 4) / 24.0
    if hi == lo:             score += hi / 14.0 * 0.35  # pair
    if a.suit == b.suit:     score += 0.08               # suited
    if 0 < hi - lo <= 2:    score += 0.04               # connected
    return min(1.0, max(0.0, score))

# ── Game State ─────────────────────────────────────────────────────────────────

class GameState:
    def __init__(self, hole, community, pot, to_call, my_chips,
                 chips_map, position, num_active, street, raises):
        self.hole_cards        = hole
        self.community_cards   = community
        self.pot               = pot
        self.to_call           = to_call
        self.my_chips          = my_chips
        self.player_chips      = chips_map
        self.position          = position
        self.num_active        = num_active
        self.street            = street
        self.raises_this_street = raises

    @property
    def pot_odds(self):
        total = self.pot + self.to_call
        return self.to_call / total if total > 0 else 0.0

    @property
    def hand_strength(self):
        return hand_strength(self.hole_cards, self.community_cards)

    @property
    def preflop(self):
        return preflop_score(self.hole_cards)

# ── STRATEGIES ─────────────────────────────────────────────────────────────────

def strategy_all_in(s):
    """
    STRATEGY 1 — THE ABSOLUTE UNIT
    if my_turn
    then bet = All In
    fi
    No hand reading. No pot odds. Pure primal chaos.
    """
    return ('raise', s.my_chips)


def strategy_tag(s):
    """
    STRATEGY 2 — TIGHT-AGGRESSIVE (TAG)
    Plays only the top ~25% of starting hands.
    When it plays, it plays hard: 3-bets premiums, bets for value post-flop.
    Folds anything marginal without hesitation.
    Exploits passive opponents by denying them cheap draws.
    """
    pf = s.preflop
    hs = s.hand_strength
    if s.street == 'preflop':
        if pf < 0.44:
            return ('check', 0) if s.to_call == 0 else ('fold', 0)
        if pf > 0.72:
            size = min(s.my_chips, max(3 * BIG_BLIND, s.pot))
            return ('raise', int(size))
        if s.to_call <= BIG_BLIND * 2:
            return ('call', s.to_call)
        return ('fold', 0)
    else:
        if hs > 0.68:
            size = min(s.my_chips, int(s.pot * 0.75))
            return ('raise', max(BIG_BLIND, size))
        if hs > 0.48:
            if s.to_call == 0:
                return ('check', 0)
            if s.to_call <= s.pot * 0.4:
                return ('call', s.to_call)
            return ('fold', 0)
        return ('check', 0) if s.to_call == 0 else ('fold', 0)


def strategy_lag(s):
    """
    STRATEGY 3 — LOOSE-AGGRESSIVE (LAG)
    Wide opening range (~50% of hands), relentless pressure.
    C-bets almost every flop. Attacks weakness with position.
    Identifies scared money and applies constant squeeze.
    Exploits tight players by stealing their blinds and pots.
    """
    pf = s.preflop
    hs = s.hand_strength
    if s.street == 'preflop':
        if pf < 0.22:
            if s.to_call > BIG_BLIND * 4:
                return ('fold', 0)
            return ('call', s.to_call) if s.to_call > 0 else ('check', 0)
        if s.raises_this_street < 2:
            size = min(s.my_chips, int(max(2.5 * BIG_BLIND, s.pot * 0.55)))
            return ('raise', max(BIG_BLIND, size))
        return ('call', s.to_call)
    else:
        if hs > 0.28 and s.raises_this_street < 2:
            size = min(s.my_chips, int(s.pot * 0.60))
            if size > 0:
                return ('raise', size)
        if hs > 0.38 and s.to_call > 0:
            return ('call', s.to_call)
        return ('check', 0) if s.to_call == 0 else ('fold', 0)


def strategy_pot_control(s):
    """
    STRATEGY 4 — POT CONTROLLER
    Rigorous pot-odds math on every street.
    Keeps pots small with marginal hands, massive with monsters.
    Slow-plays sets to trap aggressive players.
    Disciplines itself to never chase without proper equity.
    Spr-aware: adjusts bet sizing to stack-to-pot ratio.
    """
    pf = s.preflop
    hs = s.hand_strength
    po = s.pot_odds
    if s.street == 'preflop':
        if pf > 0.63:
            size = min(s.my_chips, 3 * BIG_BLIND)
            return ('raise', int(size))
        if pf > 0.38 and s.to_call <= BIG_BLIND * 3:
            return ('call', s.to_call)
        return ('check', 0) if s.to_call == 0 else ('fold', 0)
    else:
        if hs > po + 0.10:
            if hs > 0.72 and s.raises_this_street < 2:
                size = min(s.my_chips, int(s.pot * 0.65))
                if size > 0:
                    return ('raise', size)
            if s.to_call > 0:
                return ('call', s.to_call)
            return ('check', 0)
        return ('check', 0) if s.to_call == 0 else ('fold', 0)


def strategy_bluffer(s):
    """
    STRATEGY 5 — THE ARTIST OF DECEPTION
    Reads board texture for bluff opportunities.
    Bluffs more from late position, less multi-way.
    Represents coordinated boards aggressively.
    Fires continuation bets and turn barrels to fold equity.
    Calibrates bluff frequency dynamically to opponent count.
    """
    pf = s.preflop
    hs = s.hand_strength
    bluff_freq  = max(0.05, 0.40 - s.num_active * 0.06)
    pos_factor  = s.position / max(1, s.num_active - 1)
    do_bluff    = random.random() < bluff_freq * (0.5 + pos_factor)
    if s.street == 'preflop':
        if pf > 0.52:
            return ('raise', min(s.my_chips, int(3 * BIG_BLIND)))
        if do_bluff and s.raises_this_street == 0:
            return ('raise', min(s.my_chips, int(2.5 * BIG_BLIND)))
        if s.to_call <= BIG_BLIND * 2:
            return ('call', s.to_call)
        return ('fold', 0)
    else:
        if hs > 0.62:
            size = min(s.my_chips, int(s.pot * 0.75))
            if size > 0:
                return ('raise', size)
        if do_bluff and s.raises_this_street < 1:
            size = min(s.my_chips, int(s.pot * 0.55))
            if size > 0:
                return ('raise', size)
        if s.to_call == 0:
            return ('check', 0)
        if s.to_call <= s.pot * 0.35:
            return ('call', s.to_call)
        return ('fold', 0)


def strategy_gto(s):
    """
    STRATEGY 6 — GTO-INSPIRED
    Balanced mixed strategies to stay unexploitable.
    Position-aware open ranges; wider in late position.
    SPR-sensitive bet sizing; pot-geometry aware.
    Randomizes value/bluff ratios to prevent reads.
    Uses implied odds for semi-bluff calls on draws.
    Occasionally traps by slowplaying nut hands.
    """
    pf        = s.preflop
    hs        = s.hand_strength
    po        = s.pot_odds
    spr       = s.my_chips / max(1, s.pot)
    threshold = 0.62 - s.position * 0.04
    r         = random.random()
    if s.street == 'preflop':
        if pf > threshold:
            size = int(s.to_call * 2.5) if s.raises_this_street > 0 else int(2.5 * BIG_BLIND)
            return ('raise', min(s.my_chips, max(BIG_BLIND, size)))
        if pf > po * 0.85 and s.to_call <= BIG_BLIND * 3:
            return ('call', s.to_call)
        return ('check', 0) if s.to_call == 0 else ('fold', 0)
    else:
        if hs > 0.78:
            if r > 0.15:
                size = int(s.pot * (0.5 + r * 0.5))
                return ('raise', min(s.my_chips, max(1, size)))
            return ('call', s.to_call) if s.to_call > 0 else ('check', 0)
        if hs > 0.52:
            if spr > 3 and s.to_call == 0 and r > 0.40:
                size = int(s.pot * 0.40)
                if size > 0:
                    return ('raise', min(s.my_chips, size))
            if s.to_call > 0 and hs > po:
                return ('call', s.to_call)
            return ('check', 0) if s.to_call == 0 else ('fold', 0)
        if hs > 0.28:
            if s.to_call == 0:
                return ('check', 0)
            if hs > po and s.to_call < s.my_chips * 0.25:
                return ('call', s.to_call)
            if r > 0.80 and s.raises_this_street == 0:
                return ('raise', min(s.my_chips, max(BIG_BLIND, int(s.pot * 0.45))))
            return ('fold', 0)
        if s.to_call == 0:
            return ('check', 0)
        if r > 0.88 and s.raises_this_street == 0:
            return ('raise', min(s.my_chips, max(BIG_BLIND, int(s.pot * 0.6))))
        return ('fold', 0)


STRATEGIES = [
    strategy_all_in,
    strategy_tag,
    strategy_lag,
    strategy_pot_control,
    strategy_bluffer,
    strategy_gto,
]
NAMES = ["ALL_IN", "TAG", "LAG", "POT_CTL", "BLUFFER", "GTO"]

# ── Player ─────────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, strategy):
        self.pid      = pid
        self.strategy = strategy
        self.chips    = STARTING_CHIPS
        self.hole_cards = []
        self.folded   = False
        self.all_in   = False

    def reset(self):
        self.hole_cards = []
        self.folded  = self.chips == 0
        self.all_in  = False

# ── Hand Engine ────────────────────────────────────────────────────────────────

class Hand:
    def __init__(self, players, dealer_idx):
        self.all_players  = players
        self.seated       = [p for p in players if p.chips > 0]
        self.dealer_idx   = dealer_idx % max(1, len(self.seated))
        self.pot          = 0
        self.total_contrib = {p.pid: 0 for p in players}
        self.community    = []
        deck = make_deck()
        random.shuffle(deck)
        self.deck = deck

    def take(self, player, amount):
        actual = min(amount, player.chips)
        player.chips -= actual
        self.total_contrib[player.pid] += actual
        self.pot += actual
        return actual

    def bet_round(self, street, cur_bet, start_idx, preposted=None):
        if preposted is None:
            preposted = {}
        seated = self.seated
        n      = len(seated)
        round_c = {p.pid: preposted.get(p.pid, 0) for p in seated}
        raises  = 0

        def can(p):
            return not p.folded and not p.all_in and p.chips > 0

        needs = {p.pid: can(p) for p in seated}
        idx   = start_idx % n
        limit = n * 14
        iters = 0

        while any(needs.values()) and iters < limit:
            iters += 1
            p = seated[idx % n]
            if not needs.get(p.pid):
                idx += 1
                continue

            to_call = max(0, cur_bet - round_c[p.pid])
            to_call = min(to_call, p.chips)

            st = GameState(
                p.hole_cards,
                list(self.community),
                self.pot,
                to_call,
                p.chips,
                {pp.pid: pp.chips for pp in seated},
                idx % n,
                sum(1 for pp in seated if not pp.folded),
                street,
                raises,
            )

            action, amount = p.strategy(st)
            needs[p.pid] = False

            if action == 'fold':
                p.folded = True
            elif action == 'check':
                if to_call > 0:
                    p.folded = True
            elif action in ('call', 'raise'):
                if action == 'call':
                    put = to_call
                else:
                    put = max(to_call, min(amount, p.chips))
                put    = min(max(put, 0), p.chips)
                actual = self.take(p, put)
                round_c[p.pid] += actual
                if p.chips == 0:
                    p.all_in = True
                if round_c[p.pid] > cur_bet:
                    cur_bet  = round_c[p.pid]
                    raises  += 1
                    for pp in seated:
                        if pp.pid != p.pid and can(pp):
                            needs[pp.pid] = True
            idx += 1

    def run(self):
        seated = self.seated
        n      = len(seated)
        if n < 2:
            return
        for p in seated:
            p.reset()

        d     = self.dealer_idx
        sb_i  = (d + 1) % n
        bb_i  = (d + 2) % n
        utg_i = (d + 3) % n if n > 2 else d

        sb, bb = seated[sb_i], seated[bb_i]
        sb_amt = self.take(sb, SMALL_BLIND)
        if sb.chips == 0:
            sb.all_in = True
        bb_amt = self.take(bb, BIG_BLIND)
        if bb.chips == 0:
            bb.all_in = True

        for p in seated:
            p.hole_cards = [self.deck.pop(), self.deck.pop()]

        self.bet_round('preflop', BIG_BLIND, utg_i,
                       {sb.pid: sb_amt, bb.pid: bb_amt})

        active = [p for p in seated if not p.folded]
        if len(active) == 1:
            active[0].chips += self.pot
            return

        self.deck.pop()
        self.community = [self.deck.pop() for _ in range(3)]
        self.bet_round('flop', 0, (d + 1) % n)

        active = [p for p in seated if not p.folded]
        if len(active) == 1:
            active[0].chips += self.pot
            return

        self.deck.pop()
        self.community.append(self.deck.pop())
        self.bet_round('turn', 0, (d + 1) % n)

        active = [p for p in seated if not p.folded]
        if len(active) == 1:
            active[0].chips += self.pot
            return

        self.deck.pop()
        self.community.append(self.deck.pop())
        self.bet_round('river', 0, (d + 1) % n)

        active = [p for p in seated if not p.folded]
        if len(active) == 1:
            active[0].chips += self.pot
            return

        self._showdown(active)

    def _showdown(self, active):
        active_pids = {p.pid for p in active}
        remaining   = dict(self.total_contrib)
        pots        = []

        while any(v > 0 for v in remaining.values()):
            pos = {pid: v for pid, v in remaining.items() if v > 0}
            if not pos:
                break
            min_c       = min(pos.values())
            contributors = list(pos.keys())
            pot_amount  = min_c * len(contributors)
            eligible    = [pid for pid in contributors if pid in active_pids]
            if eligible:
                pots.append((pot_amount, eligible))
            for pid in contributors:
                remaining[pid] -= min_c

        pid_map = {p.pid: p for p in self.seated}
        for pot_amount, eligible_pids in pots:
            contenders = [pid_map[pid] for pid in eligible_pids if pid in pid_map]
            if not contenders:
                continue
            best, winners = None, []
            for p in contenders:
                h = best_hand(p.hole_cards + self.community)
                if best is None or h > best:
                    best, winners = h, [p]
                elif h == best:
                    winners.append(p)
            share = pot_amount // len(winners)
            rem   = pot_amount - share * len(winners)
            for p in winners:
                p.chips += share
            if rem and winners:
                winners[0].chips += rem

# ── Tournament ──────────────────────────────────────────────────────────────────

def run_tournament():
    players = [Player(i + 1, STRATEGIES[i]) for i in range(NUM_PLAYERS)]
    dealer  = 0
    for _ in range(6000):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        Hand(players, dealer).run()
        dealer += 1
    survivors = [p for p in players if p.chips > 0]
    if not survivors:
        return 1
    return max(survivors, key=lambda p: p.chips).pid

# ── Main ────────────────────────────────────────────────────────────────────────

def main():
    SEP = "=" * 66

    print(SEP)
    print("  TEXAS HOLD'EM TOURNAMENT SIMULATION")
    print(f"  {NUM_PLAYERS} players  |  {STARTING_CHIPS} chips each  |"
          f"  Blinds {SMALL_BLIND}/{BIG_BLIND}  |  {NUM_SIMS} tournaments")
    print(SEP)
    print()
    print("STRATEGIES:")
    print("  P1 ALL_IN  : if my_turn then bet = All In fi  ← THE CHAOS AGENT")
    print("  P2 TAG     : Tight-Aggressive  — premium hands only, value-bet hard")
    print("  P3 LAG     : Loose-Aggressive  — wide range, relentless pressure")
    print("  P4 POT_CTL : Pot Controller    — strict pot-odds, SPR-aware sizing")
    print("  P5 BLUFFER : Artist of Deception — positional bluffs, barrel turns")
    print("  P6 GTO     : GTO-Inspired      — balanced ranges, mixed frequencies")
    print()
    print("Running 100 tournaments", end='', flush=True)

    wins = Counter()
    for sim in range(NUM_SIMS):
        wins[run_tournament()] += 1
        if (sim + 1) % 10 == 0:
            print('.', end='', flush=True)

    print(" done!")
    print()
    print(SEP)
    print("  WINNER HISTOGRAM  (Last Player Standing — The Rounder)")
    print(SEP)
    print()

    max_wins = max(wins.values()) if wins else 1
    BAR_W    = 38

    for pid in range(1, NUM_PLAYERS + 1):
        name  = f"P{pid} {NAMES[pid-1]}"
        count = wins.get(pid, 0)
        filled = int(count / max_wins * BAR_W)
        empty  = BAR_W - filled
        bar    = "█" * filled + "░" * empty
        pct    = count / NUM_SIMS * 100
        tag    = "  ← CHAOS ALL-IN" if pid == 1 else ""
        print(f"  {name:<12} │{bar}│ {count:3d}  ({pct:5.1f}%){tag}")

    print()
    champ_pid   = wins.most_common(1)[0][0]
    champ_name  = NAMES[champ_pid - 1]
    champ_wins  = wins[champ_pid]
    p1_wins     = wins.get(1, 0)

    print(f"  CHAMPION : Player {champ_pid} — {champ_name} with {champ_wins} wins!")
    print()

    if p1_wins == 0:
        print("  The ALL-IN lunatic scored ZERO wins.")
        print("  Strategy > Entropy. Suflair GPT would've done the same thing.")
    elif p1_wins < 10:
        print(f"  The ALL-IN maniac scraped together {p1_wins} win(s) on pure luck.")
        print("  Monkeys at typewriters. Stopped clock. Twice a day, etc.")
    elif p1_wins >= champ_wins:
        print(f"  Wait... the ALL-IN psycho WON THE MOST?! {p1_wins} times!")
        print("  Variance is a cruel teacher. The field is humiliated.")
    else:
        print(f"  The ALL-IN maniac got {p1_wins} lucky win(s) out of {NUM_SIMS}.")
        print("  Chaos had its moment. Strategy had more.")

    print()
    print(SEP)

if __name__ == '__main__':
    main()
