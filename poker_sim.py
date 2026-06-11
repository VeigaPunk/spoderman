#!/usr/bin/env python3
"""
Texas Hold'em 100-Tournament Simulation
========================================
6 players, equal starting stacks.

P1  — The Maniac   : if my_turn then bet = ALL IN fi
P2  — TAG          : Tight-Aggressive (premium hands only, big bets)
P3  — LAG          : Loose-Aggressive (wide range, constant pressure, bluffs)
P4  — Positional   : exploits late position, steals, adjusts range by seat
P5  — Pot-Odds     : mathematical equity vs pot-odds, outs counting
P6  — GTO          : game-theory inspired balanced ranges, mixed frequencies
"""

import random, itertools, sys
from collections import Counter, deque, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ═══════════════════════════════════════════════════════════════
#  CARD PRIMITIVES
# ═══════════════════════════════════════════════════════════════

RANKS = "23456789TJQKA"
SUITS = "cdhs"
VAL   = {r: i + 2 for i, r in enumerate(RANKS)}   # '2'→2 … 'A'→14

def new_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ═══════════════════════════════════════════════════════════════
#  HAND EVALUATOR  — returns comparable (rank_class, tiebreakers)
# ═══════════════════════════════════════════════════════════════

def eval5(cards):
    v = sorted([VAL[c[0]] for c in cards], reverse=True)
    s = [c[1] for c in cards]
    flush    = len(set(s)) == 1
    straight = len(set(v)) == 5 and v[0] - v[4] == 4
    if set(v) == {14, 2, 3, 4, 5}:       # wheel
        straight, v = True, [5, 4, 3, 2, 1]
    cnt  = Counter(v)
    grp  = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    ov   = [g[0] for g in grp]
    of   = [g[1] for g in grp]
    if straight and flush:        return (8, v)
    if of[0] == 4:                return (7, ov)
    if of[:2] == [3, 2]:          return (6, ov)
    if flush:                     return (5, v)
    if straight:                  return (4, v)
    if of[0] == 3:                return (3, ov)
    if of[:2] == [2, 2]:          return (2, ov)
    if of[0] == 2:                return (1, ov)
    return (0, v)

def best_of_7(cards):
    return max(eval5(c) for c in itertools.combinations(cards, 5))

# ═══════════════════════════════════════════════════════════════
#  HAND-STRENGTH HELPERS  (0 … 1)
# ═══════════════════════════════════════════════════════════════

def preflop_str(hole):
    r1, r2  = VAL[hole[0][0]], VAL[hole[1][0]]
    suited  = hole[0][1] == hole[1][1]
    paired  = r1 == r2
    hi, lo  = max(r1, r2), min(r1, r2)
    s = hi + lo * 0.4
    if paired: s += 12
    if suited: s +=  3
    if hi - lo <= 2: s += 2          # connectedness bonus
    return min(s / 42.0, 1.0)

def postflop_str(hole, comm):
    if not comm:
        return preflop_str(hole)
    return best_of_7(hole + comm)[0] / 8.0

# ═══════════════════════════════════════════════════════════════
#  STRATEGIES
#  signature: (hole, comm, chips, to_call, pot, stage, pos, n)
#             → ('fold'|'check'|'call'|'raise', amount)
#  amount for 'raise' = TOTAL chips this player commits this action
# ═══════════════════════════════════════════════════════════════

# ── Strategy 0 ────────────────────────────────────────────────
def s_maniac(hole, comm, chips, to_call, pot, stage, pos, n):
    """If my_turn then bet = ALL IN fi"""
    return ('raise', chips)

# ── Strategy 1 · Tight-Aggressive (TAG) ───────────────────────
def s_tag(hole, comm, chips, to_call, pot, stage, pos, n):
    """
    Plays only a narrow premium range pre-flop (~top 20% of hands).
    When in, bets 3/4-pot or bigger for value; never bluffs.
    Folds everything marginal vs aggression.
    """
    if stage == 'preflop':
        pf = preflop_str(hole)
        if pf > 0.74:                        # AA,KK,QQ,AKs,AKo …
            bet = min(chips, max(int(pot * 3), to_call * 3, 1))
            return ('raise', bet)
        if pf > 0.54 and to_call <= chips * 0.06:
            return ('call', to_call)
        return ('fold', 0)

    hs = postflop_str(hole, comm)
    if hs >= 0.50:
        return ('raise', min(chips, max(int(pot * 0.75), to_call + 1, 1)))
    if hs >= 0.25 and to_call <= chips * 0.15:
        return ('call', to_call)
    if to_call == 0:
        return ('check', 0)
    return ('fold', 0)

# ── Strategy 2 · Loose-Aggressive (LAG) ───────────────────────
def s_lag(hole, comm, chips, to_call, pot, stage, pos, n):
    """
    Plays a wide range (~top 45%) very aggressively.
    Bluffs ~28% of weak spots post-flop; applies constant pressure.
    Bets 1.2× pot when continuing.
    """
    r = random.random()
    if stage == 'preflop':
        pf = preflop_str(hole)
        if pf > 0.38 or r < 0.20:
            bet = min(chips, max(int(pot * 2 + to_call), to_call + 1, 1))
            return ('raise', bet)
        return ('fold', 0)

    hs = postflop_str(hole, comm)
    if hs >= 0.37 or r < 0.28:
        return ('raise', min(chips, max(int(pot * 1.2), to_call + 1, 1)))
    if to_call <= chips * 0.10:
        return ('call', to_call)
    return ('fold', 0)

# ── Strategy 3 · Positional ───────────────────────────────────
def s_position(hole, comm, chips, to_call, pot, stage, pos, n):
    """
    Tight from early position (play ≥78th percentile hands only),
    medium from middle (≥60th), wide from late (≥45th).
    In late position with no aggression, steal blinds 42% of time.
    Post-flop aggression scales with position multiplier.
    """
    late = pos >= n * 0.60
    mid  = pos >= n * 0.35

    if stage == 'preflop':
        pf  = preflop_str(hole)
        thr = 0.44 if late else (0.59 if mid else 0.76)
        if pf > thr:
            mult = 2.5 if late else 2.0
            return ('raise', min(chips, max(int(pot * mult), to_call + 1, 1)))
        if late and pf > 0.28 and to_call == 0:        # blind steal
            return ('raise', min(chips, max(int(pot * 2.0), 1)))
        if to_call <= chips * 0.06:
            return ('call', to_call)
        return ('fold', 0)

    hs = postflop_str(hole, comm)
    if hs >= 0.37:
        mult = 1.0 if late else 0.60
        return ('raise', min(chips, max(int(pot * mult), to_call + 1, 1)))
    if late and to_call == 0 and random.random() < 0.42:  # c-bet steal
        return ('raise', min(chips, max(int(pot * 0.5), 1)))
    if to_call <= chips * 0.12:
        return ('call', to_call)
    return ('fold', 0)

# ── Strategy 4 · Pot-Odds / Mathematical ──────────────────────
def s_pot_odds(hole, comm, chips, to_call, pot, stage, pos, n):
    """
    Computes required equity = to_call / (pot + to_call).
    Calls / raises only when estimated equity ≥ 1.15× pot-odds.
    Estimates equity from hand-rank strength + draw outs:
      flush draw  → +0.35 equity floor
      open-ended straight draw → +0.28 equity floor
    Bets 80% pot as value when equity > 55%.
    """
    if comm:
        hs = postflop_str(hole, comm)
        all_c = hole + comm
        # flush draw boost
        if max(Counter(c[1] for c in all_c).values()) >= 4:
            hs = max(hs, 0.35)
        # straight draw boost
        rv = sorted(VAL[c[0]] for c in all_c)
        for i in range(len(rv) - 3):
            if rv[i + 3] - rv[i] <= 4:
                hs = max(hs, 0.28)
    else:
        hs = preflop_str(hole) * 0.85

    if to_call > 0:
        pot_odds = to_call / (pot + to_call + 1e-9)
        if hs > pot_odds * 1.15:                  # +EV call
            if hs > 0.55:
                return ('raise', min(chips, max(int(pot * 0.8), to_call + 1, 1)))
            return ('call', to_call)
        return ('fold', 0)

    if hs > 0.55:
        return ('raise', min(chips, max(int(pot * hs), 1)))
    return ('check', 0)

# ── Strategy 5 · GTO-Inspired ─────────────────────────────────
def s_gto(hole, comm, chips, to_call, pot, stage, pos, n):
    """
    Balanced mixed-strategy poker:
    • Randomises bet sizing from {33%, 50%, 67%, 100%} of pot.
    • Pre-flop: always 3-bet with top 30%; mix raise/call with 20-50%;
      bluff-raise 18% of air.
    • Post-flop: value-bet ≥62.5% strength 82% of time (check-trap 18%);
      semi-bluff on wet boards; bluff ~25% on wet / ~15% on dry.
    • Detects board texture (flush/straight draws present) to adjust freq.
    """
    r   = random.random()
    hs  = postflop_str(hole, comm) if comm else preflop_str(hole)
    wet = False
    if comm:
        sc  = Counter(c[1] for c in comm)
        rv  = sorted(VAL[c[0]] for c in comm)
        wet = max(sc.values()) >= 3 or (len(rv) >= 3 and rv[-1] - rv[0] <= 4)

    sz = random.choice([0.33, 0.50, 0.67, 1.0])   # GTO mixed sizing

    if stage == 'preflop':
        pf = preflop_str(hole)
        if pf > 0.70:
            return ('raise', min(chips, max(int(pot * 2.5), to_call + 1, 1)))
        if pf > 0.50:
            if r < 0.70:
                return ('raise', min(chips, max(int(pot * 2.0), to_call + 1, 1)))
            if to_call <= chips * 0.10:
                return ('call', to_call)
            return ('fold', 0)
        if pf > 0.35 and r < 0.18:                 # balanced bluff-3bet
            return ('raise', min(chips, max(int(pot * 2.0), to_call + 1, 1)))
        return ('fold', 0)

    if hs >= 0.625:
        if r < 0.82:
            return ('raise', min(chips, max(int(pot * sz), to_call + 1, 1)))
        return ('call', to_call) if to_call > 0 else ('check', 0)

    if hs >= 0.375:
        if wet:
            return ('raise', min(chips, max(int(pot * 0.67), to_call + 1, 1)))
        if r < 0.50:
            return ('call', min(to_call, chips)) if to_call > 0 else ('check', 0)
        return ('fold', 0) if to_call > 0 else ('check', 0)

    bluff_freq = 0.25 if wet else 0.15
    if r < bluff_freq:
        return ('raise', min(chips, max(int(pot * sz), to_call + 1, 1)))
    if to_call == 0:
        return ('check', 0)
    if to_call <= chips * 0.08:
        return ('call', to_call)
    return ('fold', 0)


STRATEGY_FNS = [s_maniac, s_tag, s_lag, s_position, s_pot_odds, s_gto]
NAMES        = [
    "P1 · Maniac (ALL-IN)",
    "P2 · TAG",
    "P3 · LAG",
    "P4 · Positional",
    "P5 · Pot-Odds",
    "P6 · GTO",
]

# ═══════════════════════════════════════════════════════════════
#  PLAYER
# ═══════════════════════════════════════════════════════════════

class Player:
    __slots__ = ('pid', 'chips', 'fn', 'hole', 'alive', 'rbet')
    def __init__(self, pid, chips, fn):
        self.pid   = pid
        self.chips = chips
        self.fn    = fn
        self.hole  = []
        self.alive = True
        self.rbet  = 0   # chips committed this betting round

# ═══════════════════════════════════════════════════════════════
#  BETTING ROUND
# ═══════════════════════════════════════════════════════════════

MAX_RAISES_PER_STREET = 4

def do_betting_round(table, community, pot, stage, bb):
    """
    One complete betting street.
    Modifies player.chips / player.alive / player.rbet in-place.
    Returns updated pot.
    """
    active = [p for p in table if p.alive]
    if len(active) <= 1:
        return pot

    # Post-flop streets reset round bets; pre-flop bets are already set (blinds).
    if stage != 'preflop':
        for p in active:
            p.rbet = 0

    cur_bet = max(p.rbet for p in active) if active else 0

    # Initial action order
    if stage == 'preflop':
        # UTG acts first: seats 2,3,4,… then SB(0),BB(1) close
        if len(active) >= 3:
            order = active[2:] + active[:2]
        else:
            order = list(active)   # heads-up: SB first
    else:
        order = list(active)

    q     = deque(p for p in order if p.chips > 0)
    in_q  = {p.pid for p in q}
    raises = 0

    safety = 0
    while q and safety < len(active) * 12:
        safety += 1
        p = q.popleft()
        in_q.discard(p.pid)

        if not p.alive or p.chips == 0:
            continue

        to_call = min(max(0, cur_bet - p.rbet), p.chips)

        alive_now = [x for x in active if x.alive]
        pids      = sorted(x.pid for x in alive_now)
        pos       = pids.index(p.pid) if p.pid in pids else 0

        action, amount = p.fn(
            p.hole, community, p.chips, to_call, pot, stage, pos, len(alive_now)
        )

        if action == 'fold':
            p.alive = False

        elif action in ('check', 'call'):
            c        = to_call          # already capped at p.chips
            p.chips -= c
            p.rbet  += c
            pot     += c

        else:   # 'raise'
            target   = max(int(amount), to_call)
            c        = min(p.chips, target)
            p.chips -= c
            p.rbet  += c
            pot     += c
            if p.rbet > cur_bet and raises < MAX_RAISES_PER_STREET:
                raises  += 1
                cur_bet  = p.rbet
                for other in active:
                    if (other.pid != p.pid and other.alive
                            and other.chips > 0 and other.pid not in in_q):
                        q.append(other)
                        in_q.add(other.pid)

        if sum(1 for x in active if x.alive) <= 1:
            break

    return pot

# ═══════════════════════════════════════════════════════════════
#  ONE HAND
# ═══════════════════════════════════════════════════════════════

def play_hand(table, bb):
    """Deal and play one hand on `table`. Awards pot to winner."""
    active = [p for p in table if p.chips > 0]
    if len(active) <= 1:
        return

    for p in active:
        p.alive = True
        p.rbet  = 0
        p.hole  = []

    deck = new_deck()
    random.shuffle(deck)
    for p in active:
        p.hole = [deck.pop(), deck.pop()]

    comm = []
    pot  = 0

    # ── Post blinds ──────────────────────────────────────────
    sb_p  = active[0]
    bb_p  = active[1 % len(active)]
    sb_a  = min(bb // 2, sb_p.chips)
    bb_a  = min(bb,      bb_p.chips)
    sb_p.chips -= sb_a;  sb_p.rbet = sb_a
    bb_p.chips -= bb_a;  bb_p.rbet = bb_a
    pot += sb_a + bb_a

    def live():
        return [p for p in active if p.alive]

    # ── Pre-flop ─────────────────────────────────────────────
    pot = do_betting_round(active, comm, pot, 'preflop', bb)
    lv  = live()
    if len(lv) == 1:
        lv[0].chips += pot; return

    # ── Flop ─────────────────────────────────────────────────
    comm += [deck.pop() for _ in range(3)]
    pot = do_betting_round(active, comm, pot, 'flop', bb)
    lv  = live()
    if len(lv) == 1:
        lv[0].chips += pot; return

    # ── Turn ─────────────────────────────────────────────────
    comm.append(deck.pop())
    pot = do_betting_round(active, comm, pot, 'turn', bb)
    lv  = live()
    if len(lv) == 1:
        lv[0].chips += pot; return

    # ── River ────────────────────────────────────────────────
    comm.append(deck.pop())
    pot = do_betting_round(active, comm, pot, 'river', bb)
    lv  = live()
    if len(lv) == 1:
        lv[0].chips += pot; return

    # ── Showdown ─────────────────────────────────────────────
    lv = live()
    if lv:
        winner = max(lv, key=lambda p: best_of_7(p.hole + comm))
        winner.chips += pot

# ═══════════════════════════════════════════════════════════════
#  TOURNAMENT
# ═══════════════════════════════════════════════════════════════

def run_tournament(start_chips=1500, start_bb=30, max_hands=1000):
    players = [Player(i + 1, start_chips, fn) for i, fn in enumerate(STRATEGY_FNS)]
    bb = start_bb
    for h in range(1, max_hands + 1):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        play_hand(alive, bb)
        if h % 25 == 0:                     # escalate blinds every 25 hands
            bb = min(int(bb * 1.35), start_chips // 3)
    alive = [p for p in players if p.chips > 0]
    return max(alive, key=lambda p: p.chips).pid if alive else None

# ═══════════════════════════════════════════════════════════════
#  RUN 100 SIMULATIONS
# ═══════════════════════════════════════════════════════════════

def run_sims(n=100, seed=1337):
    random.seed(seed)
    wins = defaultdict(int)
    print(f"Running {n} full-tournament simulations …")
    for i in range(n):
        if (i + 1) % 20 == 0:
            print(f"  [{i+1:3d}/{n}] complete", flush=True)
        wid = run_tournament()
        if wid:
            wins[wid] += 1
    return wins

# ═══════════════════════════════════════════════════════════════
#  HISTOGRAM
# ═══════════════════════════════════════════════════════════════

COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c']

def plot_histogram(wins, n, outpath):
    pids   = list(range(1, 7))
    counts = [wins.get(p, 0) for p in pids]

    fig, ax = plt.subplots(figsize=(14, 7))
    bars = ax.bar(NAMES, counts, color=COLORS, edgecolor='#1a1a2e',
                  linewidth=1.4, zorder=3)

    for bar, c in zip(bars, counts):
        pct = c / n * 100
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.35,
            f"{c} wins\n({pct:.1f}%)",
            ha='center', va='bottom', fontsize=10.5, fontweight='bold'
        )

    ax.set_ylabel("Tournament wins (out of 100)", fontsize=12)
    ax.set_title(
        "Texas Hold'em — 100 Tournament Simulation\n"
        "WINNER WINNER CHICKEN DINNER   —   who reigns supreme?",
        fontsize=14, fontweight='bold', pad=16
    )
    ax.set_ylim(0, max(counts) * 1.38 + 2)
    ax.grid(axis='y', alpha=0.28, zorder=0)
    ax.tick_params(axis='x', labelsize=9)
    plt.xticks(rotation=12)

    fig.text(
        0.5, 0.005,
        "P1 goes ALL-IN every single action.   P2–P6 actually think about poker.",
        ha='center', fontsize=10, fontstyle='italic', color='#555555'
    )
    plt.tight_layout(rect=[0, 0.04, 1, 1])
    plt.savefig(outpath, dpi=160, bbox_inches='tight')
    plt.close(fig)


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 62)
    print("  Texas Hold'em · 100-Tournament Simulation")
    print("  P1=Maniac(ALL-IN)  P2=TAG  P3=LAG")
    print("  P4=Positional  P5=Pot-Odds  P6=GTO")
    print("=" * 62)

    wins = run_sims(100)

    print()
    print("┌" + "─" * 54 + "┐")
    print("│     FINAL SCOREBOARD — 100 Tournaments              │")
    print("├" + "─" * 54 + "┤")
    for pid in range(1, 7):
        w   = wins.get(pid, 0)
        bar = "█" * w + "░" * (40 - w)
        print(f"│ {NAMES[pid-1]:24s}  {w:3d}  {bar} │")
    print("└" + "─" * 54 + "┘")

    champ = max(range(1, 7), key=lambda p: wins.get(p, 0))
    print(f"\n  CHAMPION: {NAMES[champ - 1]}  ({wins[champ]} wins)\n")

    outpath = "/home/user/spoderman/poker_histogram.png"
    plot_histogram(wins, 100, outpath)
    print(f"Histogram saved → {outpath}")
