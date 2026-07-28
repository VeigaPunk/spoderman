"""
Texas Hold'em Simulation: 6 players, 100 tournaments.
Player 1 = "Maniac" (always all-in).
Players 2-6 = five elaborate strategies.
Outputs a winner histogram.

Speed: strategies use fast heuristic hand-strength estimates (Chen formula
preflop, made-hand rank + draw bonuses postflop) instead of per-decision
Monte Carlo, so 100 tournaments complete in seconds.
"""

import random
from collections import Counter
from itertools import combinations
from enum import IntEnum

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

SUITS  = "shdc"
RANKS  = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for s in SUITS for r in RANKS]

# ---------------------------------------------------------------------------
# Hand evaluator — returns a comparable tuple (higher = better)
# ---------------------------------------------------------------------------

class HR(IntEnum):
    HIGH_CARD       = 1
    ONE_PAIR        = 2
    TWO_PAIR        = 3
    THREE_OF_A_KIND = 4
    STRAIGHT        = 5
    FLUSH           = 6
    FULL_HOUSE      = 7
    FOUR_OF_A_KIND  = 8
    STRAIGHT_FLUSH  = 9

def score_5(cards):
    vals  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    uniq  = sorted(set(vals))
    straight = False
    straight_high = 0
    if len(uniq) == 5:
        if uniq[-1] - uniq[0] == 4:
            straight = True; straight_high = uniq[-1]
        elif uniq == [2, 3, 4, 5, 14]:
            straight = True; straight_high = 5
    counts = Counter(vals)
    freq   = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda k: (counts[k], k), reverse=True)
    if straight and flush:
        return (HR.STRAIGHT_FLUSH, straight_high)
    if freq[0] == 4:
        return (HR.FOUR_OF_A_KIND, groups[0], groups[1])
    if freq[:2] == [3, 2]:
        return (HR.FULL_HOUSE, groups[0], groups[1])
    if flush:
        return (HR.FLUSH, *vals)
    if straight:
        return (HR.STRAIGHT, straight_high)
    if freq[0] == 3:
        ks = sorted([g for g in groups if g != groups[0]], reverse=True)
        return (HR.THREE_OF_A_KIND, groups[0], *ks)
    if freq[:2] == [2, 2]:
        return (HR.TWO_PAIR, groups[0], groups[1], groups[2])
    if freq[0] == 2:
        ks = sorted([g for g in groups if g != groups[0]], reverse=True)
        return (HR.ONE_PAIR, groups[0], *ks)
    return (HR.HIGH_CARD, *vals)

def best_hand(seven):
    return max(score_5(five) for five in combinations(seven, 5))

# ---------------------------------------------------------------------------
# Fast hand-strength heuristics (no Monte Carlo)
# ---------------------------------------------------------------------------

def preflop_strength(hole):
    """Chen-formula approximation mapped to [0,1]. 1.0 ~ AA, ~0.0 ~ 72o."""
    r1, r2 = sorted([RANK_VAL[h[0]] for h in hole], reverse=True)
    suited  = hole[0][1] == hole[1][1]
    gap     = r1 - r2

    score = {14: 10, 13: 8, 12: 7, 11: 6}.get(r1, r1 / 2.0)
    if r1 == r2:
        score = max(5, score * 2)
    if suited:
        score += 2
    if r1 != r2:
        score += {0: 0, 1: 0, 2: -1, 3: -2}.get(gap, -4)
    if gap <= 2 and r1 != r2:
        score += 1
    return max(0.0, min(1.0, score / 20.0))

def postflop_strength(hole, community):
    """Made-hand rank normalised + draw bonuses. No sampling."""
    known = hole + community
    if len(known) < 5:
        return preflop_strength(hole)

    score = best_hand(known) if len(known) > 5 else score_5(known)
    base = score[0] / HR.STRAIGHT_FLUSH

    if len(community) < 5:
        vals  = [RANK_VAL[c[0]] for c in known]
        suits = [c[1] for c in known]
        suit_counts = Counter(suits)
        flush_draw  = any(v >= 4 for v in suit_counts.values())
        uniq = sorted(set(vals))
        oesd = any(uniq[i+3] - uniq[i] == 3 for i in range(len(uniq)-3))
        if flush_draw:
            base += 0.12
        if oesd:
            base += 0.08

    return min(1.0, base)

# ---------------------------------------------------------------------------
# Game constants
# ---------------------------------------------------------------------------

SMALL_BLIND = 50
BIG_BLIND   = 100

# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, pid, chips, strategy_fn, name):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy_fn
        self.name     = name
        self.hole     = []
        self.folded   = False
        self.all_in   = False
        self.street_bet = 0

    def reset(self):
        self.hole       = []
        self.folded     = False
        self.all_in     = False
        self.street_bet = 0

    def active(self):
        return not self.folded and not self.all_in and self.chips > 0

# ---------------------------------------------------------------------------
# Strategies
# Signature: fn(pid, hole, community, pot, to_call, chips, n_active, street)
# Returns (action, amount) where action in {fold, check, call, raise}.
# ---------------------------------------------------------------------------

# 0 — Maniac: "if my_turn then bet = All in fi"
def s_maniac(pid, hole, community, pot, to_call, chips, n_active, street):
    return ("raise", chips)

# 1 — Tight-Aggressive (TAG)
# Opens only premium hands, bets for value hard, folds marginal spots.
def s_tag(pid, hole, community, pot, to_call, chips, n_active, street):
    if street == "preflop":
        hs = preflop_strength(hole)
        r1, r2 = sorted([RANK_VAL[h[0]] for h in hole], reverse=True)
        is_pair = r1 == r2
        if hs < 0.48:
            if to_call == 0:
                return ("check", 0)
            return ("fold", 0)
        if hs >= 0.70 or (is_pair and r1 >= 10):
            size = min(chips, max(BIG_BLIND * 4, to_call * 3, pot))
            return ("raise", int(size))
        if to_call <= chips * 0.10:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    else:
        hs = postflop_strength(hole, community)
        po = to_call / (pot + to_call + 1)
        if hs >= 0.72:
            size = min(chips, int(pot * 0.75))
            return ("raise", max(size, to_call + BIG_BLIND))
        if hs >= 0.55 and hs > po + 0.08:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

# 2 — Calling Station
# Loose-passive: calls almost anything hoping for miracle cards.
def s_calling_station(pid, hole, community, pot, to_call, chips, n_active, street):
    hs = preflop_strength(hole) if street == "preflop" else postflop_strength(hole, community)
    if to_call == 0:
        if hs >= 0.80:
            return ("raise", min(chips, int(pot * 0.40)))
        return ("check", 0)
    if to_call <= chips * 0.40 or hs >= 0.45:
        return ("call", min(chips, to_call))
    return ("fold", 0)

# 3 — GTO-Lite: balanced ranges, polarised sizing, randomised bluffs.
def s_gto_lite(pid, hole, community, pot, to_call, chips, n_active, street):
    hs = preflop_strength(hole) if street == "preflop" else postflop_strength(hole, community)
    po = to_call / (pot + to_call + 1)
    bluff_freq = 0.33 / max(1, n_active - 1)
    bluffing   = random.random() < bluff_freq

    if street == "preflop":
        r1, r2  = sorted([RANK_VAL[h[0]] for h in hole], reverse=True)
        suited  = hole[0][1] == hole[1][1]
        if hs >= 0.68:
            size = min(chips, max(to_call * 3, BIG_BLIND * 3, pot // 2))
            return ("raise", int(size))
        if bluffing and suited and abs(r1 - r2) <= 2 and to_call < chips * 0.08:
            size = min(chips, max(to_call * 3, BIG_BLIND * 4))
            return ("raise", int(size))
        if hs >= po + 0.05 and to_call <= chips * 0.10:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    if hs >= 0.75:
        size = min(chips, int(pot * 0.67))
        return ("raise", max(size, to_call + BIG_BLIND))
    if bluffing and to_call == 0:
        return ("raise", min(chips, max(BIG_BLIND, int(pot * 0.33))))
    if hs > po + 0.07:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# 4 — Positional Exploiter
# Steals wide in late position, defends tight in early, adapts bet sizing.
def s_positional(pid, hole, community, pot, to_call, chips, n_active, street):
    hs  = preflop_strength(hole) if street == "preflop" else postflop_strength(hole, community)
    po  = to_call / (pot + to_call + 1)
    pos = (pid % 6) / 5.0   # 0 = early, 1 = late (approximation)

    open_thresh = 0.60 - pos * 0.18
    cont_thresh = 0.55 - pos * 0.12

    if street == "preflop":
        if hs >= open_thresh:
            mult = 3.5 - pos * 1.0
            size = min(chips, int(BIG_BLIND * mult + to_call))
            return ("raise", size)
        if hs >= po + 0.04 and to_call <= chips * 0.09:
            return ("call", to_call)
        if to_call == 0:
            if pos >= 0.7 and random.random() < 0.25:
                return ("raise", min(chips, BIG_BLIND * 3))
            return ("check", 0)
        return ("fold", 0)

    if hs >= cont_thresh:
        frac = 0.75 - pos * 0.20
        size = min(chips, int(pot * frac))
        return ("raise", max(size, to_call + BIG_BLIND))
    if hs > po:
        return ("call", to_call)
    if pos >= 0.6 and to_call == 0 and hs >= 0.38:
        return ("raise", min(chips, int(pot * 0.35)))
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# 5 — Short-Stack Shover
# Deep: conventional tight play. Short (<15BB): calibrated push/fold ranges.
def s_short_stack(pid, hole, community, pot, to_call, chips, n_active, street):
    hs    = preflop_strength(hole) if street == "preflop" else postflop_strength(hole, community)
    po    = to_call / (pot + to_call + 1)
    short = chips < BIG_BLIND * 15
    micro = chips < BIG_BLIND * 7

    if micro:
        if hs >= 0.30 or to_call == 0:
            return ("raise", chips)
        return ("fold", 0)

    if short:
        if hs >= 0.38:
            return ("raise", chips)
        if to_call == 0:
            return ("check", 0)
        if to_call <= chips * 0.20:
            return ("call", to_call)
        return ("fold", 0)

    if street == "preflop":
        r1, r2 = sorted([RANK_VAL[h[0]] for h in hole], reverse=True)
        if r1 >= 10 and (r2 >= 9 or r1 == r2):
            size = min(chips, BIG_BLIND * 4 + to_call)
            return ("raise", size)
        if hs >= 0.58 and to_call <= chips * 0.10:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    if hs >= 0.72:
        size = min(chips, int(pot * 0.65))
        return ("raise", max(size, to_call + BIG_BLIND))
    if hs >= po + 0.06:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

STRATEGIES = [
    ("Maniac (All-In)",      s_maniac),
    ("Tight-Aggressive",     s_tag),
    ("Calling Station",      s_calling_station),
    ("GTO-Lite",             s_gto_lite),
    ("Positional Exploiter", s_positional),
    ("Short-Stack Shover",   s_short_stack),
]

# ---------------------------------------------------------------------------
# Betting round
# ---------------------------------------------------------------------------

def betting_round(players, pot, community, street):
    current_bet = max(p.street_bet for p in players)
    acted = set()
    order = [p for p in players if p.active()]
    if not order:
        return pot

    idx = 0
    guard = len(players) * 6
    for _ in range(guard):
        if not any(p.active() for p in order):
            break
        p = order[idx % len(order)]
        idx += 1
        if not p.active():
            continue

        to_call = min(max(0, current_bet - p.street_bet), p.chips)
        n_act   = sum(1 for x in players if not x.folded)

        action, amount = p.strategy(
            p.pid, p.hole, community, pot,
            to_call, p.chips, n_act, street,
        )

        if action == "fold":
            p.folded = True
            acted.add(p.pid)
        elif action == "check":
            if to_call > 0:
                p.folded = True   # illegal check = auto-fold
            acted.add(p.pid)
        elif action == "call":
            chips_in = min(p.chips, to_call)
            p.chips      -= chips_in
            p.street_bet += chips_in
            pot          += chips_in
            if p.chips == 0:
                p.all_in = True
            acted.add(p.pid)
        elif action == "raise":
            target   = max(int(amount), to_call)
            chips_in = min(p.chips, target)
            p.chips      -= chips_in
            p.street_bet += chips_in
            pot          += chips_in
            if p.chips == 0:
                p.all_in = True
            if p.street_bet > current_bet:
                current_bet = p.street_bet
                acted = {p.pid}
            else:
                acted.add(p.pid)

        if not any(x.active() and x.pid not in acted for x in players):
            break

    return pot

# ---------------------------------------------------------------------------
# Hand engine
# ---------------------------------------------------------------------------

def play_hand(players):
    for p in players:
        p.reset()

    deck = make_deck()
    random.shuffle(deck)

    ptr = 0
    for p in players:
        p.hole = [deck[ptr], deck[ptr+1]]
        ptr += 2

    def deal(n):
        nonlocal ptr
        ptr += 1          # burn
        cards = deck[ptr:ptr+n]
        ptr  += n
        return cards

    pot = 0
    sb, bb = players[0], players[1]
    for p, blind in [(sb, SMALL_BLIND), (bb, BIG_BLIND)]:
        amt = min(p.chips, blind)
        p.chips -= amt; p.street_bet += amt; pot += amt
        if p.chips == 0: p.all_in = True

    community = []

    def street(name, new_cards, first=False):
        nonlocal pot
        community.extend(new_cards)
        if not first:
            for p in players:
                p.street_bet = 0
        pot = betting_round(players, pot, list(community), name)
        return sum(1 for p in players if not p.folded)

    if street("preflop", [], first=True) > 1:
        if street("flop", deal(3)) > 1:
            if street("turn", deal(1)) > 1:
                street("river", deal(1))

    contenders = [p for p in players if not p.folded]
    if not contenders:
        return None
    if len(contenders) == 1:
        contenders[0].chips += pot
        return contenders[0].pid

    # Showdown — deal out remaining community if all-in ended betting early
    while len(community) < 5:
        community.extend(deal(3 if len(community) == 0 else 1))

    scored = [(best_hand(p.hole + community), p) for p in contenders]
    scored.sort(key=lambda x: x[0], reverse=True)
    best    = scored[0][0]
    winners = [p for sc, p in scored if sc == best]
    share   = pot // len(winners)
    rem     = pot - share * len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += rem
    return winners[0].pid

# ---------------------------------------------------------------------------
# Tournament engine
# ---------------------------------------------------------------------------

def run_tournament(starting_chips=10_000):
    players = [
        Player(i+1, starting_chips, STRATEGIES[i][1], STRATEGIES[i][0])
        for i in range(len(STRATEGIES))
    ]
    dealer = 0
    for _ in range(3000):
        alive = [p for p in players if p.chips > 0]
        if len(alive) < 2:
            break
        dealer = (dealer + 1) % len(alive)
        seated = alive[dealer:] + alive[:dealer]
        play_hand(seated)
        for p in players:
            if p.chips < 0:
                p.chips = 0

    survivors = [p for p in players if p.chips > 0]
    if not survivors:
        return None
    return max(survivors, key=lambda p: p.chips).pid

# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------

def print_histogram(win_counts, n_sims):
    BAR  = 44
    LINE = 72
    print()
    print("=" * LINE)
    print("   TEXAS HOLD'EM — 100-TOURNAMENT WINNER HISTOGRAM")
    print("=" * LINE)
    mx = max(win_counts.values()) if win_counts else 1
    for i, (name, _) in enumerate(STRATEGIES):
        pid   = i + 1
        wins  = win_counts.get(pid, 0)
        bar   = "█" * max(int(wins / mx * BAR), 1 if wins else 0)
        pct   = wins / n_sims * 100
        tag   = " <- MANIAC" if pid == 1 else ""
        label = f"P{pid} {name[:22]}"
        print(f"  {label:<26} {bar:<44} {wins:>3} ({pct:4.1f}%){tag}")
    print("=" * LINE)
    top   = max(win_counts, key=win_counts.get)
    tname = STRATEGIES[top-1][0]
    print(f"\n  WINNER WINNER CHICKEN DINNER: P{top} — {tname}")
    print(f"  Took down {win_counts[top]}/{n_sims} tournaments.\n")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    N     = 100
    CHIPS = 10_000
    random.seed(42)

    print(f"\nRunning {N} Texas Hold'em tournaments  (blinds {SMALL_BLIND}/{BIG_BLIND})")
    print(f"Each player starts with {CHIPS:,} chips.\n")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  <-- shoves every single hand" if i == 0 else ""
        print(f"  P{i+1}: {name}{tag}")
    print()

    win_counts = Counter()
    for sim in range(1, N + 1):
        wpid = run_tournament(CHIPS)
        if wpid:
            win_counts[wpid] += 1
        if sim % 10 == 0:
            print(f"  {sim}/{N} tournaments complete ...")

    print_histogram(win_counts, N)
