"""
Texas Hold'em Poker Tournament Simulation
6 Players, 100 Tournaments, Last-Man-Standing wins.

Player 1  : The Degenerate  — always ALL-IN, no thought, pure chaos
Player 2  : TAG             — Tight-Aggressive, premium hands only, bets hard
Player 3  : LAG             — Loose-Aggressive, wide range, position + bluffs
Player 4  : Calling Station — passive, calls almost everything, rarely folds
Player 5  : GTO-Inspired    — balanced mixed-freq decisions, exact pot odds
Player 6  : Position Oracle — position dictates EVERYTHING, tight early/loose late
"""

import random
import sys
from collections import Counter
from itertools import combinations
from enum import Enum

# ─────────────────────────────────────────────────────────
#  CARD PRIMITIVES
# ─────────────────────────────────────────────────────────
RANKS  = '23456789TJQKA'
SUITS  = 'CDHS'
RVAL   = {r: i for i, r in enumerate(RANKS, 2)}  # '2'→2, 'A'→14

def new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(d)
    return d

def rv(card): return RVAL[card[0]]

# ─────────────────────────────────────────────────────────
#  HAND EVALUATOR  (returns comparable tuple, higher=better)
# ─────────────────────────────────────────────────────────
def eval5(cards):
    ranks  = sorted([rv(c) for c in cards], reverse=True)
    suits  = [c[1] for c in cards]
    flush  = len(set(suits)) == 1
    cnt    = Counter(ranks)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    freqs  = sorted(cnt.values(), reverse=True)

    straight = False
    if len(set(ranks)) == 5:
        if ranks[0] - ranks[4] == 4:
            straight = True
        elif ranks == [14, 5, 4, 3, 2]:      # wheel
            straight, ranks = True, [5, 4, 3, 2, 1]

    if straight and flush: return (8, ranks)
    if freqs[0] == 4:      return (7, groups)
    if freqs[:2] == [3,2]: return (6, groups)
    if flush:              return (5, ranks)
    if straight:           return (4, ranks)
    if freqs[0] == 3:      return (3, groups)
    if freqs[:2] == [2,2]: return (2, groups)
    if freqs[0] == 2:      return (1, groups)
    return                        (0, ranks)

def best_hand(hole, board):
    return max(eval5(list(c)) for c in combinations(hole + board, 5))

# ─────────────────────────────────────────────────────────
#  MONTE-CARLO EQUITY  (fast, ~150 samples)
# ─────────────────────────────────────────────────────────
def equity(hole, board, n_opps, sims=150):
    known  = {tuple(c) for c in hole + board}
    avail  = [c for c in new_deck() if tuple(c) not in known]
    wins   = 0
    needed = 5 - len(board)
    for _ in range(sims):
        random.shuffle(avail)
        idx    = 0
        runout = board + avail[idx:idx+needed]; idx += needed
        mine   = best_hand(hole, runout)
        beat   = False
        for _ in range(n_opps):
            if idx+2 > len(avail): beat = True; break
            opp = best_hand(list(avail[idx:idx+2]), runout); idx += 2
            if opp > mine: beat = True; break
        if not beat: wins += 1
    return wins / sims

# ─────────────────────────────────────────────────────────
#  PREFLOP STRENGTH  (heuristic, 0-1)
# ─────────────────────────────────────────────────────────
def preflop_str(hole):
    r1, r2 = rv(hole[0]), rv(hole[1])
    suited  = hole[0][1] == hole[1][1]
    hi, lo  = max(r1,r2), min(r1,r2)
    if r1 == r2:                          # pair
        return 0.50 + (hi-2)/12*0.48
    base = (hi-2)/12*0.58 + (lo-2)/12*0.33
    if suited:          base += 0.04
    gap = hi - lo
    if gap == 1:        base += 0.03
    elif gap == 2:      base += 0.015
    return min(base, 0.99)

# ─────────────────────────────────────────────────────────
#  PLAYER
# ─────────────────────────────────────────────────────────
class Action(Enum):
    FOLD=0; CHECK=1; CALL=2; RAISE=3; ALLIN=4

class Player:
    def __init__(self, pid, chips, strat):
        self.id, self.chips, self.strat = pid, chips, strat
        self.hole   = []
        self.active = True   # in current hand
        self.bet    = 0      # chips committed this street

    def act(self, gs):
        return self.strat(self, gs)

class GS:                     # GameState passed to strategies
    __slots__ = ('board','pot','street','current_bet','bb',
                 'actives','my_pos','n_players')

# ─────────────────────────────────────────────────────────
#  STRATEGY 1 — THE DEGENERATE  (always all-in)
# ─────────────────────────────────────────────────────────
def s_allin(me, gs):
    return Action.ALLIN, me.chips

# ─────────────────────────────────────────────────────────
#  STRATEGY 2 — TAG  (Tight-Aggressive)
#  Philosophy: only enter with premiums; when you enter, punish.
#  Exploits: folds vs mediocre hands; value-bets relentlessly.
#  Weakness: readable, good players 3-bet light against it.
# ─────────────────────────────────────────────────────────
def s_tag(me, gs):
    n    = len(gs.actives) - 1
    pf   = not gs.board
    eq   = preflop_str(me.hole) if pf else equity(me.hole, gs.board, n)
    call = gs.current_bet - me.bet
    pot  = gs.pot

    if pf:
        if eq >= 0.84:                    # AA/KK/QQ/AK — 3-bet/4-bet always
            return Action.RAISE, min(pot*3+call, me.chips)
        if eq >= 0.68:                    # JJ/TT/AQ/KQ — open or call 1 raise
            if call == 0:
                return Action.RAISE, min(gs.bb*3, me.chips)
            if call <= me.chips*0.12:
                return Action.CALL, min(call, me.chips)
        if eq >= 0.58 and gs.my_pos >= gs.n_players*0.65:
            if call == 0: return Action.RAISE, min(gs.bb*2.5, me.chips)
            if call <= gs.bb*2: return Action.CALL, min(call, me.chips)
        if call == 0: return Action.CHECK, 0
        return Action.FOLD, 0

    # postflop
    if eq >= 0.72:
        bet = min(int(pot*0.80), me.chips)
        return (Action.RAISE, bet) if bet > call else (Action.CALL, min(call,me.chips))
    if eq >= 0.52:
        if call == 0: return Action.CHECK, 0
        po = call/(pot+call) if pot+call else 1
        return (Action.CALL, min(call,me.chips)) if eq > po else (Action.FOLD, 0)
    if call == 0: return Action.CHECK, 0
    return Action.FOLD, 0

# ─────────────────────────────────────────────────────────
#  STRATEGY 3 — LAG  (Loose-Aggressive)
#  Philosophy: wide range, steal blinds, c-bet almost every flop,
#              use position to barrel opponents off marginal hands.
#  Exploits: tight players who fold too much; pot-control situations.
#  Weakness: bleeds chips when called by strong ranges.
# ─────────────────────────────────────────────────────────
def s_lag(me, gs):
    n    = len(gs.actives) - 1
    pf   = not gs.board
    eq   = preflop_str(me.hole) if pf else equity(me.hole, gs.board, n)
    call = gs.current_bet - me.bet
    pot  = gs.pot
    pos  = gs.my_pos / max(gs.n_players-1, 1)   # 0=early, 1=BTN

    if pf:
        thr = 0.44 - pos*0.12          # looser in position
        if eq >= thr+0.18:
            return Action.RAISE, min(int(gs.bb*2.5+pos*gs.bb), me.chips)
        if eq >= thr:
            if call == 0: return Action.RAISE, min(int(gs.bb*2.2), me.chips)
            if call <= gs.bb*3.5: return Action.CALL, min(call, me.chips)
        if call == 0: return Action.CHECK, 0
        return Action.FOLD, 0

    # postflop — c-bet heavy; semi-bluff draws
    bluff = 0.30 * pos
    if eq >= 0.58:
        bet = min(int(pot*0.65), me.chips)
        return (Action.RAISE, bet) if bet > call else (Action.CALL, min(call,me.chips))
    if eq >= 0.38 or random.random() < bluff:
        if call == 0:
            return Action.RAISE, min(int(pot*0.55), me.chips)
        po = call/(pot+call) if pot+call else 1
        if eq > po*0.75: return Action.CALL, min(call, me.chips)
    if call == 0: return Action.CHECK, 0
    return Action.FOLD, 0

# ─────────────────────────────────────────────────────────
#  STRATEGY 4 — CALLING STATION
#  Philosophy: "see the cards, keep hope alive."
#  Calls almost any bet. Never raises without a monster.
#  Exploits: nothing intentionally — just never gives up equity.
#  Weakness: bleeds against value; pot-odds are ignored.
# ─────────────────────────────────────────────────────────
def s_station(me, gs):
    n    = len(gs.actives) - 1
    pf   = not gs.board
    eq   = preflop_str(me.hole) if pf else equity(me.hole, gs.board, n, sims=80)
    call = gs.current_bet - me.bet
    pot  = gs.pot

    if call == 0:
        if eq >= 0.82:                   # monster — bet for value
            return Action.RAISE, min(int(pot*0.35), me.chips)
        return Action.CHECK, 0

    frac = call / me.chips if me.chips else 1
    if frac >= 0.60 and eq < 0.22:      # only fold against huge shove with air
        return Action.FOLD, 0
    return Action.CALL, min(call, me.chips)

# ─────────────────────────────────────────────────────────
#  STRATEGY 5 — GTO-INSPIRED
#  Philosophy: balanced mixed-frequency play. Value bets and bluffs
#              at calibrated ratios so opponents can't exploit.
#  Exploits: predictable players (TAG / station).
#  Weakness: true GTO requires solver data; this is an approximation.
# ─────────────────────────────────────────────────────────
def s_gto(me, gs):
    n    = len(gs.actives) - 1
    pf   = not gs.board
    eq   = preflop_str(me.hole) if pf else equity(me.hole, gs.board, n, sims=200)
    call = gs.current_bet - me.bet
    pot  = gs.pot
    po   = call/(pot+call) if pot+call else 0

    if pf:
        if eq >= 0.87: return Action.RAISE, min(int(gs.bb*2.5), me.chips)
        if eq >= 0.72:
            if random.random() < 0.75:
                return Action.RAISE, min(int(gs.bb*2.5), me.chips)
            if call <= gs.bb*3: return Action.CALL, min(call, me.chips)
            return Action.FOLD, 0
        if eq >= 0.55:
            if call == 0: return Action.CHECK, 0
            if eq > po*1.15: return Action.CALL, min(call, me.chips)
            return Action.FOLD, 0
        if eq >= 0.43:                  # bluff-raise range
            if call == 0:
                if random.random() < 0.22:
                    return Action.RAISE, min(int(gs.bb*2.5), me.chips)
                return Action.CHECK, 0
            if call <= gs.bb: return Action.CALL, min(call, me.chips)
        if call == 0: return Action.CHECK, 0
        return Action.FOLD, 0

    # postflop — value / bluff mixed
    if eq >= 0.78:
        size = min(int(pot*(0.55+random.random()*0.45)), me.chips)
        return (Action.RAISE, size) if size > call else (Action.CALL, min(call,me.chips))
    if eq >= 0.62:
        size = min(int(pot*0.52), me.chips)
        return (Action.RAISE, size) if size > call else (Action.CALL, min(call,me.chips))
    if eq > po*1.08:
        if call == 0:
            if random.random() < 0.28:
                return Action.RAISE, min(int(pot*0.40), me.chips)
            return Action.CHECK, 0
        return Action.CALL, min(call, me.chips)
    if call == 0 and random.random() < 0.18:   # pure bluff
        return Action.RAISE, min(int(pot*0.42), me.chips)
    if call == 0: return Action.CHECK, 0
    return Action.FOLD, 0

# ─────────────────────────────────────────────────────────
#  STRATEGY 6 — POSITION ORACLE
#  Philosophy: position is the most exploitable edge in poker.
#              In position = aggression. Out of position = discipline.
#  Exploits: players who don't adjust for position.
#  Weakness: predictable range in early position; misses value OOP.
# ─────────────────────────────────────────────────────────
def s_position(me, gs):
    n    = len(gs.actives) - 1
    pf   = not gs.board
    eq   = preflop_str(me.hole) if pf else equity(me.hole, gs.board, n, sims=150)
    call = gs.current_bet - me.bet
    pot  = gs.pot
    pos  = gs.my_pos / max(gs.n_players-1, 1)   # 0=early, 1=BTN
    ip   = pos >= 0.55                            # "in position"

    if pf:
        thr = 0.40 if ip else (0.56 if pos >= 0.3 else 0.70)
        if eq >= thr+0.15:
            return Action.RAISE, min(int(gs.bb*(3.0 + pos*1.5)), me.chips)
        if eq >= thr:
            if call == 0: return Action.CHECK, 0
            if call <= gs.bb*(2+ip): return Action.CALL, min(call, me.chips)
        if call == 0: return Action.CHECK, 0
        return Action.FOLD, 0

    # postflop
    if ip:
        if eq >= 0.52:
            bet = min(int(pot*0.62), me.chips)
            return (Action.RAISE, bet) if bet > call else (Action.CALL, min(call,me.chips))
        if eq >= 0.38:
            if call == 0: return Action.RAISE, min(int(pot*0.42), me.chips)
            po = call/(pot+call) if pot+call else 1
            if eq > po: return Action.CALL, min(call,me.chips)
        if call == 0:
            if random.random() < 0.38:         # positional float/bluff
                return Action.RAISE, min(int(pot*0.50), me.chips)
            return Action.CHECK, 0
        return Action.FOLD, 0
    else:   # out of position — straightforward
        if eq >= 0.68:
            bet = min(int(pot*0.62), me.chips)
            return (Action.RAISE, bet) if bet > call else (Action.CALL, min(call,me.chips))
        if eq >= 0.52:
            if call == 0: return Action.CHECK, 0
            po = call/(pot+call) if pot+call else 1
            if eq > po: return Action.CALL, min(call,me.chips)
            return Action.FOLD, 0
        if call == 0: return Action.CHECK, 0
        return Action.FOLD, 0

# ─────────────────────────────────────────────────────────
#  BETTING ROUND ENGINE
# ─────────────────────────────────────────────────────────
def betting_round(players, pot, street_bet, bb, board, dealer_pos):
    """
    Runs one street of betting. Mutates player.chips / player.bet.
    Returns updated pot.
    """
    n      = len(players)
    active = [p for p in players if p.active and p.chips > 0 or
              (p.active and p.bet < street_bet)]

    if len([p for p in players if p.active]) <= 1:
        return pot

    # Build action order
    if not board:                        # preflop: UTG first (after BB)
        start = (dealer_pos + 3) % n
    else:                                # postflop: first after dealer
        start = (dealer_pos + 1) % n

    order = []
    for i in range(n):
        p = players[(start + i) % n]
        if p.active:
            order.append(p)

    acted     = set()
    queue     = list(order)
    iters     = 0
    max_iters = n * 8

    while queue and iters < max_iters:
        iters += 1
        me = queue.pop(0)
        if not me.active: continue
        call = street_bet - me.bet
        if call < 0: call = 0
        if me.chips == 0:
            acted.add(me.id); continue

        gs           = GS()
        gs.board     = board
        gs.pot       = pot
        gs.street    = 'preflop' if not board else ('flop' if len(board)==3
                        else ('turn' if len(board)==4 else 'river'))
        gs.current_bet = street_bet
        gs.bb        = bb
        gs.actives   = [p for p in players if p.active]
        gs.n_players = n
        gs.my_pos    = order.index(me) if me in order else 0

        action, amount = me.act(gs)

        if action == Action.FOLD:
            me.active = False
            if len([p for p in players if p.active]) <= 1: break

        elif action in (Action.CHECK, Action.CALL):
            actual = min(call, me.chips)
            me.chips -= actual; me.bet += actual; pot += actual
            acted.add(me.id)

        elif action in (Action.RAISE, Action.ALLIN):
            if action == Action.ALLIN:
                to_add = me.chips
            else:
                target  = max(int(amount), street_bet + bb)
                to_add  = min(target - me.bet, me.chips)
                to_add  = max(to_add, min(call, me.chips))  # at least call

            me.chips -= to_add; me.bet += to_add; pot += to_add

            if me.bet > street_bet:
                street_bet = me.bet
                # everyone else re-acts
                acted_now = {me.id}
                queue = [p for p in order
                         if p.active and p.id not in acted_now
                         and (p.bet < street_bet) and p.chips > 0]
                acted = acted_now
            else:
                acted.add(me.id)

        all_ok = all(
            p.bet >= street_bet or p.chips == 0
            for p in players if p.active
        )
        if all_ok and not queue: break

    return pot

# ─────────────────────────────────────────────────────────
#  HAND ENGINE
# ─────────────────────────────────────────────────────────
def play_hand(players, dealer_pos, bb):
    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2: return

    n = len(alive)
    for p in alive:
        p.active = True
        p.bet    = 0
        p.hole   = []

    deck = new_deck()
    for p in alive: p.hole = [deck.pop(), deck.pop()]

    pot = 0
    # Blinds
    sb_i = (dealer_pos + 1) % n
    bb_i = (dealer_pos + 2) % n if n > 2 else (dealer_pos + 1) % n
    sb   = alive[sb_i];  bb_p = alive[bb_i]

    sb_amt = min(bb//2, sb.chips)
    sb.chips -= sb_amt; sb.bet = sb_amt; pot += sb_amt

    bb_amt = min(bb, bb_p.chips)
    bb_p.chips -= bb_amt; bb_p.bet = bb_amt; pot += bb_amt

    board = []

    for street in ('preflop','flop','turn','river'):
        if street == 'flop':   deck.pop(); board += [deck.pop(),deck.pop(),deck.pop()]
        elif street == 'turn': deck.pop(); board.append(deck.pop())
        elif street == 'river':deck.pop(); board.append(deck.pop())

        if len([p for p in alive if p.active]) <= 1: break

        street_bet = bb if street == 'preflop' else 0
        if street != 'preflop':
            for p in alive: p.bet = 0

        pot = betting_round(alive, pot, street_bet, bb, board, dealer_pos)
        if len([p for p in alive if p.active]) <= 1: break

    # Showdown
    contenders = [p for p in alive if p.active]
    if len(contenders) == 1:
        contenders[0].chips += pot
    else:
        scored = sorted(contenders, key=lambda p: best_hand(p.hole, board), reverse=True)
        top    = best_hand(scored[0].hole, board)
        winners= [p for p in scored if best_hand(p.hole, board) == top]
        share  = pot // len(winners)
        for w in winners: w.chips += share
        winners[0].chips += pot - share*len(winners)   # remainder

# ─────────────────────────────────────────────────────────
#  TOURNAMENT ENGINE
# ─────────────────────────────────────────────────────────
STRATEGIES = [s_allin, s_tag, s_lag, s_station, s_gto, s_position]
NAMES = {
    1: "P1 Always All-In",
    2: "P2 TAG",
    3: "P3 LAG",
    4: "P4 Calling Station",
    5: "P5 GTO-Inspired",
    6: "P6 Position Oracle",
}

def run_tournament(starting_chips=1500, starting_bb=30):
    players = [Player(i+1, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer  = 0
    bb      = starting_bb
    hand    = 0

    while sum(1 for p in players if p.chips > 0) > 1 and hand < 800:
        hand += 1
        if hand % 60 == 0:
            bb = min(bb*2, starting_chips//3)
        alive = [p for p in players if p.chips > 0]
        play_hand(alive, dealer % len(alive), bb)
        dealer += 1

    winner = max(players, key=lambda p: p.chips)
    return winner.id

# ─────────────────────────────────────────────────────────
#  RUN 100 SIMULATIONS + HISTOGRAM
# ─────────────────────────────────────────────────────────
def main():
    N = 100
    wins = {i: 0 for i in range(1, 7)}

    print(f"Running {N} Texas Hold'em tournaments...\n")
    for k in range(N):
        w = run_tournament()
        wins[w] += 1
        if (k+1) % 20 == 0:
            print(f"  {k+1}/{N} done …")

    # ── terminal table ────────────────────────────────────
    print("\n" + "="*62)
    print("  WINNER WINNER CHICKEN DINNER  —  100 tournament results")
    print("="*62)
    for pid in range(1, 7):
        bar = "█" * wins[pid]
        pct = wins[pid]
        print(f"  {NAMES[pid]:<22}  {pct:>3} wins  {bar}")
    print("="*62)

    # ── matplotlib histogram ──────────────────────────────
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np

        labels = [NAMES[i] for i in range(1, 7)]
        values = [wins[i] for i in range(1, 7)]
        colors = ['#E74C3C','#3498DB','#2ECC71','#F39C12','#9B59B6','#1ABC9C']

        fig, ax = plt.subplots(figsize=(13, 7))
        bars = ax.bar(labels, values, color=colors, edgecolor='#1a1a2e',
                      linewidth=1.1, alpha=0.88, zorder=3)

        # gold border on P1
        bars[0].set_edgecolor('gold')
        bars[0].set_linewidth(3)

        for bar, v in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width()/2,
                    bar.get_height() + 0.4,
                    f'{v}\n({v}%)', ha='center', va='bottom',
                    fontsize=10.5, fontweight='bold', color='#1a1a2e')

        expected = N / 6
        ax.axhline(expected, color='grey', ls=':', lw=1.5, label=f'Expected ({expected:.1f})', zorder=2)
        ax.legend(fontsize=9)

        ax.set_ylim(0, max(values)*1.30)
        ax.set_ylabel('Tournament Wins (out of 100)', fontsize=12)
        ax.set_title(
            '🃏  Texas Hold\'em: 100 Tournament Results\n'
            'P1 (Always All-In) vs 5 Elaborate Strategies',
            fontsize=14, fontweight='bold', pad=14
        )
        ax.set_xticks(range(6))
        ax.set_xticklabels(
            [f'P{i}\n{NAMES[i].split(" ",1)[1]}' for i in range(1,7)],
            fontsize=9.5
        )
        ax.grid(axis='y', alpha=0.25, linestyle='--', zorder=1)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        fig.patch.set_facecolor('#f7f9fc')
        ax.set_facecolor('#f7f9fc')
        plt.tight_layout()

        out = '/home/user/spoderman/poker_results.png'
        plt.savefig(out, dpi=150, bbox_inches='tight')
        print(f"\nHistogram saved → {out}")
        plt.close()
    except Exception as e:
        print(f"[matplotlib skipped: {e}]")

if __name__ == '__main__':
    random.seed(42)
    main()
