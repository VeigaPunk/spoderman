#!/usr/bin/env python3
"""
Texas Hold'em 6-player tournament simulation.
  Player 1 : Always All-In  (the simple caveman strategy)
  Players 2-6 : Elaborate AI strategies
100 tournaments; last chip-holder wins.
Outputs ASCII histogram + PNG.
"""
import random, sys
from collections import Counter
from itertools import combinations
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ──────────────────────────────────────────────────────────────────────
# CARDS
# ──────────────────────────────────────────────────────────────────────
RANKS     = list('23456789TJQKA')
SUITS     = 'cdhs'
RANK_VAL  = {r: i for i, r in enumerate(RANKS)}

class Card:
    __slots__ = ('rank', 'suit', 'val')
    def __init__(self, rank, suit):
        self.rank, self.suit, self.val = rank, suit, RANK_VAL[rank]
    def __repr__(self):
        return self.rank + self.suit

def fresh_deck():
    d = [Card(r, s) for r in RANKS for s in SUITS]
    random.shuffle(d)
    return d

# ──────────────────────────────────────────────────────────────────────
# HAND EVALUATION
# ──────────────────────────────────────────────────────────────────────
def best_hand(cards):
    best = None
    for combo in combinations(cards, min(5, len(cards))):
        s = _score5(combo)
        if best is None or s > best:
            best = s
    return best

def _score5(cards):
    vals  = sorted((c.val for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    flush    = len(set(suits)) == 1
    straight = len(set(vals)) == 5 and (vals[0] - vals[4] == 4)
    if set(vals) == {12, 0, 1, 2, 3}:     # A-2-3-4-5 wheel
        straight, vals = True, [3, 2, 1, 0, -1]
    cnt   = Counter(vals)
    freq  = sorted(cnt.values(), reverse=True)
    grp   = sorted(cnt, key=lambda v: (cnt[v], v), reverse=True)
    if straight and flush: return (8, vals)
    if freq[0] == 4:       return (7, grp)
    if freq[:2] == [3, 2]: return (6, grp)
    if flush:              return (5, vals)
    if straight:           return (4, vals)
    if freq[0] == 3:       return (3, grp)
    if freq[:2] == [2, 2]: return (2, grp)
    if freq[0] == 2:       return (1, grp)
    return (0, vals)

# ──────────────────────────────────────────────────────────────────────
# HAND STRENGTH HEURISTIC  (0 .. 1)
# ──────────────────────────────────────────────────────────────────────
def strength(hole, board):
    cards = hole + board
    if len(cards) < 5:
        # Pre-flop heuristic
        v0, v1   = hole[0].val, hole[1].val
        hi, lo   = max(v0, v1), min(v0, v1)
        suited   = hole[0].suit == hole[1].suit
        paired   = v0 == v1
        s        = (hi * 1.5 + lo * 0.5) / 20.0
        if suited:       s += 0.08
        if paired:       s += 0.18
        if hi - lo <= 2: s += 0.05
        return min(s, 1.0)
    tier = best_hand(cards)[0]     # 0 (high card) .. 8 (straight flush)
    return tier / 8.0 * 0.88 + 0.06

# ──────────────────────────────────────────────────────────────────────
# PLAYER
# ──────────────────────────────────────────────────────────────────────
class Player:
    def __init__(self, pid, chips, strat, name):
        self.pid   = pid
        self.chips = chips
        self.strat = strat
        self.name  = name
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.invested = 0   # chips committed this street

    def reset(self):
        self.hole, self.folded, self.allin, self.invested = [], False, False, 0

# ──────────────────────────────────────────────────────────────────────
# STRATEGIES
# ──────────────────────────────────────────────────────────────────────
# state keys: board, pot, to_call, bb, my_chips, position (0=early..1=BTN), street

def s_allin(p, st):
    """
    ┌──────────────────────────────────────────┐
    │  IF my_turn THEN bet = ALL_IN  FI        │
    └──────────────────────────────────────────┘
    """
    return 'raise', p.chips


def s_tag(p, st):
    """
    Tight-Aggressive (TAG)
    ─────────────────────
    Only enters pots with the top ~25 % of hands.
    When it does play, it bets 1-2× pot to extract maximum value
    and deny equity to drawing hands.
    Folds anything marginal facing a bet — never pays off cheaply.
    """
    sv  = strength(p.hole, st['board'])
    tc  = st['to_call']
    pot = st['pot']
    bb  = st['bb']

    if sv >= 0.68:
        bet = min(p.chips, max(pot, tc + bb * 2))
        return 'raise', bet
    if sv >= 0.52:
        if tc == 0: return 'check', 0
        if tc <= p.chips * 0.08: return 'call', tc
    return ('check', 0) if tc == 0 else ('fold', 0)


def s_lag(p, st):
    """
    Loose-Aggressive (LAG)
    ──────────────────────
    Plays a wide range of hands pre-flop; exploits position & momentum.
    Bluffs ~28 % of the time with weak holdings to keep opponents guessing.
    Uses variable bet sizing (0.5–1.6× pot) to disguise hand strength.
    Forces mistakes from tight/passive opponents who can't call wide.
    """
    sv      = strength(p.hole, st['board'])
    tc      = st['to_call']
    pot     = st['pot']
    bb      = st['bb']
    bluffing = sv < 0.38 and random.random() < 0.28

    if sv >= 0.42 or bluffing:
        mult = random.uniform(0.5, 1.6)
        bet  = min(p.chips, max(int(pot * mult), tc + bb))
        return 'raise', bet
    if sv >= 0.28:
        if tc == 0: return 'check', 0
        if tc <= p.chips * 0.16: return 'call', tc
    return ('check', 0) if tc == 0 else ('fold', 0)


def s_rock(p, st):
    """
    Rock / Nit
    ──────────
    Extreme selectivity: only plays the top ~5 % of hands.
    Slow-plays monsters to trap aggressive opponents.
    Never bluffs; never defends weak draws.
    Relies on opponents paying off its rare but powerful holdings.
    """
    sv  = strength(p.hole, st['board'])
    tc  = st['to_call']
    bb  = st['bb']

    if sv >= 0.90:
        if random.random() < 0.35:
            return 'raise', min(p.chips, tc + bb * 3)
        return ('call', min(tc, p.chips)) if tc > 0 else ('check', 0)
    if sv >= 0.80:
        if tc == 0: return 'check', 0
        if tc <= p.chips * 0.03: return 'call', tc
    return ('check', 0) if tc == 0 else ('fold', 0)


def s_position(p, st):
    """
    Position Master
    ───────────────
    Understands that the later you act, the more information you have.
    Plays very tight from UTG (first to act), progressively looser
    toward the Button (last to act).
    Steals blinds and pots aggressively from late position.
    Folds speculative hands out-of-position to avoid tough decisions.
    """
    sv   = strength(p.hole, st['board'])
    tc   = st['to_call']
    pot  = st['pot']
    bb   = st['bb']
    pos  = st['position']               # 0 = early, 1 = button

    thresh = 0.68 - pos * 0.32          # looser as position improves
    if sv >= thresh + 0.18:
        size = int(pot * (0.45 + pos * 0.75))
        return 'raise', min(p.chips, max(size, tc + bb))
    if sv >= thresh:
        if tc == 0: return 'check', 0
        if tc <= p.chips * 0.12: return 'call', tc
    return ('check', 0) if tc == 0 else ('fold', 0)


def s_pot_odds(p, st):
    """
    Pot-Odds Technician
    ────────────────────
    Every call is a math problem: required equity = to_call ÷ (pot + to_call).
    Only continues when estimated hand equity exceeds the price.
    With sufficient edge (>15 %), re-raises to extract value.
    Bets ~65 % of pot when checking is free and holding decent equity.
    Completely immune to scare cards — decisions are always EV-based.
    """
    sv  = strength(p.hole, st['board'])
    tc  = st['to_call']
    pot = st['pot']
    bb  = st['bb']

    if tc <= 0:
        if sv > 0.55:
            bet = min(p.chips, max(bb, int(pot * 0.65)))
            return 'raise', bet
        return 'check', 0

    required = tc / (pot + tc) if (pot + tc) > 0 else 1.0
    margin   = sv - required

    if margin >= 0.15:
        return 'raise', min(p.chips, max(int(pot * 0.80), tc * 2))
    if margin >= 0:
        return 'call', min(tc, p.chips)
    return 'fold', 0


STRATEGIES = [s_allin, s_tag, s_lag, s_rock, s_position, s_pot_odds]
NAMES      = [
    'All-In Maniac',
    'Tight-Aggressive',
    'Loose-Aggressive',
    'Rock / Nit',
    'Position Master',
    'Pot-Odds Tech',
]

# ──────────────────────────────────────────────────────────────────────
# BETTING ENGINE
# ──────────────────────────────────────────────────────────────────────
def bet_round(seat_order, pot, init_bet, board, bb_size, street):
    """
    seat_order : players in action order (some may already have invested blinds).
    init_bet   : minimum bet that players must match (BB pre-flop, 0 post-flop).
    Modifies player state in-place; returns updated pot.
    """
    cur_bet = init_bet
    pending = list(seat_order)      # action queue
    guard   = len(seat_order) * 12

    while pending and guard > 0:
        guard -= 1
        p = pending.pop(0)

        if p.folded or p.allin:
            continue

        alive = [x for x in seat_order if not x.folded]
        if len(alive) <= 1:
            break

        tc      = max(0, cur_bet - p.invested)
        active  = [x for x in seat_order if not x.folded]
        pos_flt = active.index(p) / max(1, len(active) - 1) if p in active else 0.5

        state = dict(
            board    = board,
            pot      = pot,
            to_call  = tc,
            bb       = bb_size,
            my_chips = p.chips,
            position = pos_flt,
            street   = street,
        )

        action, amount = p.strat(p, state)

        if action == 'fold':
            p.folded = True

        elif action == 'check':
            if tc > 0:
                p.folded = True     # illegal check → fold

        elif action == 'call':
            put = min(tc, p.chips)
            p.chips -= put;  p.invested += put;  pot += put
            if p.chips == 0: p.allin = True

        elif action == 'raise':
            put = min(int(amount), p.chips)
            if put < tc:
                # All-in for less than call amount
                p.chips -= put;  p.invested += put;  pot += put
                p.allin = True
            else:
                p.chips -= put;  p.invested += put;  pot += put
                if p.chips == 0: p.allin = True
                if p.invested > cur_bet:
                    cur_bet = p.invested
                    # Raise → everyone else must act again
                    pending = [x for x in seat_order
                               if x.pid != p.pid and not x.folded and not x.allin]

    for p in seat_order:
        p.invested = 0
    return pot

# ──────────────────────────────────────────────────────────────────────
# PLAY ONE HAND
# ──────────────────────────────────────────────────────────────────────
def play_hand(players, dealer_pos, sb_size, bb_size):
    """players is the list of currently alive players (chips > 0)."""
    n = len(players)
    for p in players:
        p.reset()

    deck = fresh_deck()
    for p in players:
        p.hole = [deck.pop(), deck.pop()]

    # Post blinds
    sb_i = (dealer_pos + 1) % n
    bb_i = (dealer_pos + 2) % n
    pot  = 0

    for idx, blind in [(sb_i, sb_size), (bb_i, bb_size)]:
        pl  = players[idx]
        amt = min(blind, pl.chips)
        pl.chips -= amt;  pl.invested = amt;  pot += amt
        if pl.chips == 0: pl.allin = True

    cur_bet = players[bb_i].invested

    # Pre-flop: UTG acts first
    utg = (bb_i + 1) % n
    pre_order = [players[(utg + i) % n] for i in range(n)]
    board = []
    pot   = bet_round(pre_order, pot, cur_bet, board, bb_size, 'preflop')

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return

    # Post-flop: action starts left of dealer (skip folded)
    post_order = [players[(dealer_pos + 1 + i) % n] for i in range(n)
                  if not players[(dealer_pos + 1 + i) % n].folded]

    for street, ncards in [('flop', 3), ('turn', 1), ('river', 1)]:
        board += [deck.pop() for _ in range(ncards)]
        pot    = bet_round(post_order, pot, 0, board, bb_size, street)
        alive  = [p for p in players if not p.folded]
        if len(alive) == 1:
            alive[0].chips += pot
            return

    # Showdown
    alive  = [p for p in players if not p.folded]
    scored = [(best_hand(p.hole + board), p) for p in alive]
    best_s = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == best_s]
    share, rem = divmod(pot, len(winners))
    for w in winners:
        w.chips += share
    winners[0].chips += rem

# ──────────────────────────────────────────────────────────────────────
# TOURNAMENT
# ──────────────────────────────────────────────────────────────────────
def run_tournament(start_chips=10_000, sb=50, bb=100, max_hands=2_000):
    players = [Player(i + 1, start_chips, STRATEGIES[i], NAMES[i]) for i in range(6)]
    dealer  = 0

    for _ in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        d = dealer % len(alive)
        play_hand(alive, d, sb, bb)
        dealer += 1

    alive = [p for p in players if p.chips > 0]
    if not alive:
        return max(players, key=lambda p: p.chips).pid
    return max(alive, key=lambda p: p.chips).pid

# ──────────────────────────────────────────────────────────────────────
# 100 SIMULATIONS
# ──────────────────────────────────────────────────────────────────────
def run_sims(n=100):
    wins = Counter()
    for i in range(n):
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/100 sims done", flush=True)
        wins[run_tournament()] += 1
    return wins

# ──────────────────────────────────────────────────────────────────────
# OUTPUT
# ──────────────────────────────────────────────────────────────────────
def ascii_histogram(wins):
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║       TEXAS HOLD'EM — 100 TOURNAMENTS — LAST ONE STANDING   ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    mx = max(wins.values(), default=1)
    for pid in range(1, 7):
        w     = wins.get(pid, 0)
        bar   = '█' * w + '░' * (mx - w)
        crown = '  ◄ CHAMPION' if w == mx else ''
        print(f"║ P{pid} {NAMES[pid-1]:20s} [{w:3d}] {bar}{crown}")
    print("╚══════════════════════════════════════════════════════════════╝")
    champ = max(wins, key=wins.get)
    print(f"\n  WINNER WINNER CHICKEN DINNER:")
    print(f"  Player {champ} — {NAMES[champ - 1]}  ({wins[champ]}/100 tournaments)\n")


def plot_histogram(wins, outfile='poker_results.png'):
    pids   = list(range(1, 7))
    counts = [wins.get(p, 0) for p in pids]
    labels = [f"P{p}\n{NAMES[p-1]}" for p in pids]
    colors = ['#e74c3c', '#3498db', '#e67e22', '#2ecc71', '#9b59b6', '#1abc9c']
    champ  = counts.index(max(counts))

    fig, ax = plt.subplots(figsize=(14, 7))
    bars = ax.bar(labels, counts, color=colors, edgecolor='#2c3e50',
                  linewidth=1.4, zorder=3)

    # Gold crown on winner
    bars[champ].set_edgecolor('gold')
    bars[champ].set_linewidth(3.5)

    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.4,
                str(cnt), ha='center', va='bottom',
                fontsize=13, fontweight='bold', color='#2c3e50')

    ax.set_facecolor('#f8f9fa')
    fig.patch.set_facecolor('#ecf0f1')
    ax.grid(axis='y', alpha=0.35, zorder=0)
    ax.set_xlabel('Player / Strategy', fontsize=13, labelpad=10)
    ax.set_ylabel('Tournament Wins (out of 100)', fontsize=13, labelpad=10)
    ax.set_title(
        "Texas Hold'em · 6 Players · 100 Tournaments · Last Chip-Holder Wins\n"
        "Player 1 strategy:  IF my_turn THEN bet = ALL_IN  FI",
        fontsize=14, fontweight='bold', pad=14
    )
    ax.set_ylim(0, max(counts) * 1.28 + 3)

    legend_patches = [
        mpatches.Patch(color=colors[i], label=f"P{i+1}: {NAMES[i]}")
        for i in range(6)
    ]
    ax.legend(handles=legend_patches, loc='upper right',
              fontsize=9, framealpha=0.8)

    plt.tight_layout()
    plt.savefig(outfile, dpi=150, bbox_inches='tight')
    print(f"  Histogram saved → {outfile}")
    return outfile


# ──────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print()
    print("  Texas Hold'em Simulation  —  6 Players  —  100 Tournaments")
    print()
    for i, name in enumerate(NAMES):
        tag = '  ← THE SIMPLE ONE (always shoves)' if i == 0 else ''
        print(f"    Player {i+1}: {name}{tag}")
    print()
    print("  Running 100 full tournaments ...")
    print()

    random.seed(42)          # reproducible
    wins = run_sims(100)

    ascii_histogram(wins)
    plot_histogram(wins, 'poker_results.png')
