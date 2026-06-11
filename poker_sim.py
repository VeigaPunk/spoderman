#!/usr/bin/env python3
"""
Texas Hold'em Tournament Simulation
Player 1: Always All-In (the humble chad)
Players 2-6: Elaborate strategic masterminds
"""

import random
import itertools
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ─── Card primitives ──────────────────────────────────────────────────────────

RANKS  = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
SUITS  = ['s','h','d','c']
RANK_V = {r: i for i, r in enumerate(RANKS)}   # 2=0 … A=12

class Card:
    __slots__ = ('rank','suit','v')
    def __init__(self, rank, suit):
        self.rank = rank; self.suit = suit; self.v = RANK_V[rank]
    def __repr__(self): return self.rank + self.suit

class Deck:
    def __init__(self):
        self._cards = [Card(r,s) for s in SUITS for r in RANKS]
        random.shuffle(self._cards)
    def deal(self, n=1):
        cards, self._cards = self._cards[:n], self._cards[n:]
        return cards

# ─── Hand evaluator (best 5 from N) ──────────────────────────────────────────

def _score5(cards):
    vals  = sorted((c.v for c in cards), reverse=True)
    suits = [c.suit for c in cards]
    flush = len(set(suits)) == 1
    # straight detection
    straight = (vals[0]-vals[4] == 4 and len(set(vals)) == 5)
    if vals == [12,3,2,1,0]:          # wheel A-2-3-4-5
        straight = True; vals = [3,2,1,0,-1]
    cnt = defaultdict(int)
    for v in vals: cnt[v] += 1
    grps = sorted(cnt.items(), key=lambda x:(x[1],x[0]), reverse=True)
    gv   = [v for v,_ in grps]
    gc   = [c for _,c in grps]
    if straight and flush: return (9 if vals[0]==12 else 8, vals)
    if gc[0]==4: return (7, gv)
    if gc[0]==3 and gc[1]==2: return (6, gv)
    if flush: return (5, vals)
    if straight: return (4, vals)
    if gc[0]==3: return (3, gv)
    if gc[0]==2 and gc[1]==2: return (2, gv)
    if gc[0]==2: return (1, gv)
    return (0, vals)

def best_hand(cards):
    best = None
    for combo in itertools.combinations(cards, 5):
        s = _score5(list(combo))
        if best is None or s > best: best = s
    return best

# ─── Strategy helpers ─────────────────────────────────────────────────────────

def preflop_rank(hole):
    """0-10 preflop hand strength."""
    if len(hole) < 2: return 0
    v1, v2 = sorted((c.v for c in hole), reverse=True)
    suited  = hole[0].suit == hole[1].suit
    paired  = v1 == v2
    if paired:
        if v1>=12: return 10
        if v1>=11: return 9
        if v1>=10: return 8
        if v1>= 9: return 7
        if v1>= 8: return 6
        if v1>= 6: return 5
        return 4
    if v1==12:
        if v2==11: return 9 if suited else 8
        if v2>=10: return 8 if suited else 7
        if v2>= 9: return 7 if suited else 5
        return 4 if suited else 2
    if v1==11:
        if v2==10: return 6 if suited else 5
        if v2>= 9: return 5 if suited else 4
        return 3 if suited else 1
    if v1==10 and v2==9: return 5 if suited else 4
    gap = v1-v2
    if gap==1 and v1>=7: return 3 if suited else 2
    if suited and v1>=8: return 2
    return 1

def hand_strength(hole, community):
    """Rough [0,1] strength estimate from current board."""
    if not hole: return 0.5
    if not community:
        return preflop_rank(hole) / 10.0
    rank = best_hand(hole + community)[0]
    bases = [0.05, 0.18, 0.36, 0.55, 0.65, 0.76, 0.86, 0.93, 0.97, 1.0]
    return bases[rank]

# ─── Game state passed to strategies ─────────────────────────────────────────

class GS:   # lightweight struct
    __slots__ = ('community','pot','to_call','stage','n_players',
                 'n_active','position','bb','my_stack','my_bet')

# ─── The 6 strategies ─────────────────────────────────────────────────────────

# ACTION: ('fold',0) | ('check',0) | ('call', amount) | ('bet', amount) | ('raise', amount)
# 'amount' for bet/raise is the TOTAL chips the player wants to put in this street.

def s_allin(p, gs):
    """Player 1: Simple genius – ALL IN, always, forever."""
    return ('raise', p.chips + p._street_bet)

def s_tag(p, gs):
    """Tight-Aggressive: premiums only, punishes limpers."""
    hs = hand_strength(p.hole, gs.community)
    pr = preflop_rank(p.hole)
    if gs.stage == 'preflop':
        if pr >= 8:
            return ('raise', min(p.chips + p._street_bet, max(gs.to_call, gs.bb)*3 + gs.bb*2))
        if pr >= 5:
            if gs.to_call <= gs.bb*4: return ('call', gs.to_call)
            return ('fold', 0)
        if pr >= 3 and gs.to_call == 0: return ('check', 0)
        if gs.to_call == 0: return ('check', 0)
        if pr >= 3 and gs.to_call <= gs.bb*2: return ('call', gs.to_call)
        return ('fold', 0)
    # post-flop
    if hs > 0.78:
        target = min(p.chips + p._street_bet, p._street_bet + int(gs.pot * 0.80))
        return ('raise', target)
    if hs > 0.55:
        if gs.to_call == 0: return ('bet', min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.55)))
        if gs.to_call <= int(gs.pot * 0.45): return ('call', gs.to_call)
        return ('fold', 0)
    if gs.to_call == 0: return ('check', 0)
    pot_odds = gs.to_call / (gs.pot + gs.to_call + 1e-9)
    if hs > pot_odds: return ('call', gs.to_call)
    return ('fold', 0)

def s_lag(p, gs):
    """Loose-Aggressive: wide range, pressure-cooking the pot."""
    hs = hand_strength(p.hole, gs.community)
    pr = preflop_rank(p.hole)
    if gs.stage == 'preflop':
        if pr >= 6:
            return ('raise', min(p.chips + p._street_bet, max(gs.to_call,gs.bb)*4 + gs.bb*2))
        if pr >= 2:
            if gs.to_call <= gs.bb*6: return ('call', gs.to_call)
            return ('fold', 0)
        if gs.to_call == 0: return ('check', 0)
        if gs.to_call <= gs.bb*2: return ('call', gs.to_call)
        return ('fold', 0)
    if hs > 0.62:
        target = min(p.chips + p._street_bet, p._street_bet + int(gs.pot*1.0))
        return ('raise', target)
    if hs > 0.38:
        if gs.to_call == 0: return ('bet', min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.6)))
        return ('call', gs.to_call)
    if gs.to_call == 0:
        if random.random() < 0.28:
            return ('bet', min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.45)))
        return ('check', 0)
    if gs.to_call <= gs.bb*3: return ('call', gs.to_call)
    return ('fold', 0)

def s_position(p, gs):
    """Position Master: steals in late, plays tight in early."""
    hs = hand_strength(p.hole, gs.community)
    pr = preflop_rank(p.hole)
    pos_ratio = gs.position / max(gs.n_active - 1, 1)  # 0=UTG, 1=BTN
    min_pr = max(2, 7 - int(pos_ratio * 5))
    if gs.stage == 'preflop':
        if pr >= min_pr + 2:
            return ('raise', min(p.chips + p._street_bet, max(gs.to_call,gs.bb)*3 + gs.bb*2))
        if pr >= min_pr:
            if gs.to_call <= gs.bb*4: return ('call', gs.to_call)
            return ('fold', 0)
        if gs.to_call == 0:
            if pos_ratio > 0.65 and random.random() < 0.38:  # steal
                return ('raise', min(p.chips + p._street_bet, gs.bb*3))
            return ('check', 0)
        return ('fold', 0)
    if pos_ratio > 0.55:   # in position
        if hs > 0.58:
            target = min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.72))
            if gs.to_call == 0: return ('bet', target)
            if hs > 0.72: return ('raise', target)
            return ('call', gs.to_call)
        if gs.to_call == 0 and random.random() < 0.32:
            return ('bet', min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.40)))
        if gs.to_call == 0: return ('check', 0)
        if gs.to_call <= gs.pot*0.35: return ('call', gs.to_call)
        return ('fold', 0)
    else:   # out of position
        if hs > 0.70:
            target = min(p.chips + p._street_bet, p._street_bet + int(gs.pot*0.60))
            if gs.to_call == 0: return ('bet', target)
            return ('raise', target)
        if gs.to_call == 0: return ('check', 0)
        if gs.to_call <= gs.bb*2: return ('call', gs.to_call)
        return ('fold', 0)

def s_pot_odds(p, gs):
    """Pot-Odds Pro: pure math, no feelings."""
    hs = hand_strength(p.hole, gs.community)
    if gs.stage in ('flop','turn'): hs = min(1.0, hs * 1.18)  # implied odds bump
    pr = preflop_rank(p.hole)
    if gs.stage == 'preflop':
        equity = pr / 10.0
        if gs.to_call == 0:
            if equity > 0.52: return ('bet', min(p.chips+p._street_bet, p._street_bet+int(gs.pot+gs.bb*2.5)))
            return ('check', 0)
        po = gs.to_call / (gs.pot + gs.to_call + 1e-9)
        if equity > po + 0.15:
            return ('raise', min(p.chips+p._street_bet, max(gs.to_call,gs.bb)*3 + p._street_bet))
        if equity > po: return ('call', gs.to_call)
        return ('fold', 0)
    if gs.to_call == 0:
        if hs > 0.66: return ('bet', min(p.chips+p._street_bet, p._street_bet+int(gs.pot*0.66)))
        return ('check', 0)
    po = gs.to_call / (gs.pot + gs.to_call + 1e-9)
    if hs > po + 0.22:
        target = min(p.chips+p._street_bet, p._street_bet+int(gs.pot*0.80))
        if target > gs.to_call + p._street_bet: return ('raise', target)
        return ('call', gs.to_call)
    if hs > po: return ('call', gs.to_call)
    return ('fold', 0)

def s_bluff(p, gs):
    """Bluff King: value bets huge, semi-bluffs, fires blank barrels."""
    hs  = hand_strength(p.hole, gs.community)
    pr  = preflop_rank(p.hole)
    bfreq = {'preflop':0.22,'flop':0.38,'turn':0.26,'river':0.18}
    bf  = bfreq.get(gs.stage, 0.22)
    if gs.stage == 'preflop':
        if pr >= 7:
            return ('raise', min(p.chips+p._street_bet, max(gs.to_call,gs.bb)*4 + gs.bb*3))
        if pr >= 4 or random.random() < bf:
            if gs.to_call <= gs.bb*5:
                if random.random() < 0.55:
                    return ('raise', min(p.chips+p._street_bet, max(gs.to_call,gs.bb)*3 + p._street_bet))
                return ('call', gs.to_call)
            return ('fold', 0)
        if gs.to_call == 0: return ('check', 0)
        if gs.to_call <= gs.bb: return ('call', gs.to_call)
        return ('fold', 0)
    if hs > 0.65:
        target = min(p.chips+p._street_bet, p._street_bet + int(gs.pot*1.10))
        if gs.to_call == 0: return ('bet', target)
        return ('raise', target)
    if hs > 0.42:
        if gs.to_call == 0: return ('bet', min(p.chips+p._street_bet, p._street_bet+int(gs.pot*0.60)))
        return ('call', gs.to_call)
    if random.random() < bf:
        bluff_size = min(p.chips+p._street_bet, p._street_bet+int(gs.pot*0.80))
        if gs.to_call == 0 and bluff_size > p._street_bet: return ('bet', bluff_size)
        if gs.to_call > 0 and random.random() < 0.38:
            return ('raise', min(p.chips+p._street_bet, p._street_bet+int(gs.pot*0.90)))
    if gs.to_call == 0: return ('check', 0)
    if gs.to_call <= gs.bb*2: return ('call', gs.to_call)
    return ('fold', 0)

# ─── Player ───────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy, name):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.name     = name
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self._street_bet = 0   # chips put in THIS street so far

    def reset(self):
        self.hole = []; self.folded = False; self.allin = False; self._street_bet = 0

    def act(self, gs):
        if self.folded or self.allin: return ('check', 0)
        action, amount = self.strategy(self, gs)
        return action, amount

# ─── Game engine ──────────────────────────────────────────────────────────────

class HoldemGame:
    def __init__(self, players):
        self.players  = players
        self.dealer   = 0
        self.bb_size  = 10

    def _blinds(self, seats):
        n   = len(seats)
        sb  = seats[self.dealer % n]
        bb  = seats[(self.dealer + 1) % n]
        sb_put = min(self.bb_size // 2, sb.chips)
        bb_put = min(self.bb_size,      bb.chips)
        self._put(sb, sb_put)
        self._put(bb, bb_put)
        return bb_put, (self.dealer + 2) % n   # current_bet, UTG index

    def _put(self, player, amount):
        amount = min(amount, player.chips)
        player.chips       -= amount
        player._street_bet += amount
        self.pot           += amount
        if player.chips == 0: player.allin = True
        return amount

    def _bet_round(self, seats, current_bet, first_idx, stage):
        n   = len(seats)
        if n < 2: return current_bet
        max_raises = 6
        raises     = 0
        need_act   = {p.pid for p in seats if not p.folded and not p.allin}
        acted      = set()
        idx        = first_idx % n
        iterations = 0
        while True:
            iterations += 1
            if iterations > n * (max_raises + 4) + 20: break
            p = seats[idx % n]
            if p.folded or p.allin:
                idx += 1
                if not (need_act - acted): break
                continue
            if p.pid not in need_act:
                idx += 1
                active_unacted = need_act - acted
                if not active_unacted: break
                continue

            to_call = current_bet - p._street_bet

            gs           = GS()
            gs.community = self.community
            gs.pot       = self.pot
            gs.to_call   = to_call
            gs.stage     = stage
            gs.n_players = len(self.players)
            gs.n_active  = sum(1 for x in seats if not x.folded)
            gs.position  = idx % n
            gs.bb        = self.bb_size
            gs.my_stack  = p.chips
            gs.my_bet    = p._street_bet

            action, amount = p.act(gs)

            if action == 'fold':
                p.folded = True
                acted.add(p.pid)
                need_act.discard(p.pid)

            elif action in ('check',):
                if to_call > 0:                    # can't check – fold
                    p.folded = True
                acted.add(p.pid)
                need_act.discard(p.pid)

            elif action == 'call':
                if to_call <= 0:
                    acted.add(p.pid)
                    need_act.discard(p.pid)
                else:
                    self._put(p, to_call)
                    acted.add(p.pid)
                    need_act.discard(p.pid)

            elif action in ('bet', 'raise'):
                # 'amount' = desired total street commitment
                desired_total = max(amount, current_bet + self.bb_size)
                desired_total = min(desired_total, p.chips + p._street_bet)
                add = desired_total - p._street_bet
                if add <= to_call:           # not actually a raise
                    self._put(p, to_call)
                    acted.add(p.pid)
                    need_act.discard(p.pid)
                elif raises < max_raises:
                    self._put(p, add)
                    current_bet = p._street_bet
                    raises     += 1
                    acted       = {p.pid}
                    need_act    = {x.pid for x in seats if not x.folded and not x.allin and x.pid != p.pid}
                else:                        # max raises hit – call only
                    self._put(p, to_call)
                    acted.add(p.pid)
                    need_act.discard(p.pid)
            else:
                acted.add(p.pid)
                need_act.discard(p.pid)

            active_and_need = need_act - acted
            if not active_and_need: break
            idx += 1

        return current_bet

    def _reset_street_bets(self, seats):
        for p in seats: p._street_bet = 0

    def play_hand(self):
        seats = [p for p in self.players if p.chips > 0]
        if len(seats) < 2:
            self.dealer = (self.dealer + 1) % len(self.players)
            return

        for p in seats: p.reset()
        self.pot       = 0
        self.community = []

        deck = Deck()
        for p in seats: p.hole = deck.deal(2)

        current_bet, utg = self._blinds(seats)

        # Pre-flop
        current_bet = self._bet_round(seats, current_bet, utg, 'preflop')
        live = [p for p in seats if not p.folded]
        if len(live) == 1:
            live[0].chips += self.pot; self.pot = 0
            self.dealer = (self.dealer + 1) % len(self.players); return

        # Flop
        self._reset_street_bets(live)
        self.community = deck.deal(3)
        current_bet = self._bet_round(live, 0, 0, 'flop')
        live = [p for p in live if not p.folded]
        if len(live) == 1:
            live[0].chips += self.pot; self.pot = 0
            self.dealer = (self.dealer + 1) % len(self.players); return

        # Turn
        self._reset_street_bets(live)
        self.community += deck.deal(1)
        current_bet = self._bet_round(live, 0, 0, 'turn')
        live = [p for p in live if not p.folded]
        if len(live) == 1:
            live[0].chips += self.pot; self.pot = 0
            self.dealer = (self.dealer + 1) % len(self.players); return

        # River
        self._reset_street_bets(live)
        self.community += deck.deal(1)
        self._bet_round(live, 0, 0, 'river')
        live = [p for p in live if not p.folded]

        # Showdown
        self._showdown(live)
        self.dealer = (self.dealer + 1) % len(self.players)

    def _showdown(self, live):
        if not live: return
        if len(live) == 1:
            live[0].chips += self.pot; self.pot = 0; return
        scores = {}
        for p in live:
            scores[p.pid] = best_hand(p.hole + self.community)
        best = max(scores.values())
        winners = [p for p in live if scores[p.pid] == best]
        share, rem = divmod(self.pot, len(winners))
        for i, w in enumerate(winners):
            w.chips += share + (rem if i == 0 else 0)
        self.pot = 0

    def run_tournament(self):
        """Play until one player has everything. Return that player."""
        max_hands = 8000
        for _ in range(max_hands):
            alive = [p for p in self.players if p.chips > 0]
            if len(alive) == 1: return alive[0]
            if len(alive) == 0: return max(self.players, key=lambda p: p.chips)
            self.play_hand()
        # Time-out: richest player wins
        return max(self.players, key=lambda p: p.chips)

# ─── Strategy registry ────────────────────────────────────────────────────────

STRATEGY_CONFIGS = [
    (s_allin,    "P1 AllIn-Maniac"),
    (s_tag,      "P2 Tight-Aggro"),
    (s_lag,      "P3 Loose-Aggro"),
    (s_position, "P4 Pos-Master"),
    (s_pot_odds, "P5 Pot-Odds-Pro"),
    (s_bluff,    "P6 Bluff-King"),
]

# ─── Simulation ───────────────────────────────────────────────────────────────

def run_sims(n=100, starting_chips=1000):
    wins = defaultdict(int)
    for i in range(n):
        players = [Player(pid+1, starting_chips, strat, name)
                   for pid, (strat, name) in enumerate(STRATEGY_CONFIGS)]
        game = HoldemGame(players)
        winner = game.run_tournament()
        wins[winner.name] += 1
        if (i+1) % 25 == 0:
            print(f"  {i+1}/{n} tournaments done…")
    return wins

# ─── Histogram ────────────────────────────────────────────────────────────────

def histogram(wins, n_sims):
    names  = [c[1] for c in STRATEGY_CONFIGS]
    counts = [wins.get(n, 0) for n in names]
    palette = ['#E53935','#1E88E5','#43A047','#FB8C00','#8E24AA','#00ACC1']

    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(names, counts, color=palette, edgecolor='#222', linewidth=1.3, zorder=3)

    for bar, cnt in zip(bars, counts):
        pct = cnt / n_sims * 100
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + 0.6,
                f"{cnt}  ({pct:.1f}%)",
                ha='center', va='bottom', fontsize=11, fontweight='bold')

    expected = n_sims / len(names)
    ax.axhline(expected, color='grey', ls='--', lw=1.4, label=f'Equal-chance baseline: {expected:.1f}')

    ax.set_xlabel('Strategy', fontsize=13, fontweight='bold')
    ax.set_ylabel('Tournament Wins  (last player standing)', fontsize=12, fontweight='bold')
    ax.set_title(
        f'Texas Hold\'em — Who\'s the Last One Standing?\n'
        f'{n_sims} Full Tournaments  ·  All players start with {1000} chips\n'
        f'(P1 = always ALL-IN  vs  five elaborate strategies)',
        fontsize=13, fontweight='bold', pad=14)
    ax.set_ylim(0, max(counts) * 1.18)
    ax.yaxis.grid(True, alpha=0.4, zorder=0)
    ax.set_axisbelow(True)
    ax.legend(fontsize=10)

    # star on winner bar
    best_idx = counts.index(max(counts))
    bars[best_idx].set_edgecolor('gold')
    bars[best_idx].set_linewidth(3.5)
    ax.text(bars[best_idx].get_x() + bars[best_idx].get_width()/2,
            bars[best_idx].get_height() + 3.2,
            '★ WINNER WINNER\nCHICKEN DINNER',
            ha='center', va='bottom', fontsize=9, color='#C8A000', fontweight='bold')

    plt.tight_layout()
    out = 'poker_results.png'
    plt.savefig(out, dpi=150, bbox_inches='tight')
    plt.close()
    return out

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print()
    print("═"*58)
    print("   TEXAS HOLD'EM TOURNAMENT SIMULATOR")
    print("═"*58)
    print()
    print("  Player 1  ➜  AllIn-Maniac   [if my_turn: bet=ALL_IN fi]")
    print("  Player 2  ➜  Tight-Aggro    [TAG: premiums only, punish]")
    print("  Player 3  ➜  Loose-Aggro    [LAG: wide range, pressure]")
    print("  Player 4  ➜  Pos-Master     [steals late, tight early]")
    print("  Player 5  ➜  Pot-Odds-Pro   [pure math, no feelings]")
    print("  Player 6  ➜  Bluff-King     [value + barrel bluffs]")
    print()
    print("  Starting chips : 1 000 each")
    print("  Blinds         : 5 / 10")
    print("  Tournaments    : 100")
    print()
    print("Running…")
    wins = run_sims(n=100, starting_chips=1000)
    print()
    print("═"*58)
    print("   RESULTS")
    print("═"*58)
    sorted_w = sorted(wins.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, cnt) in enumerate(sorted_w, 1):
        bar = '█' * cnt + '░' * (max(w for _,w in sorted_w) - cnt)
        pct = cnt / 100 * 100
        print(f"  {rank}. {name:22s} {cnt:3d}  ({pct:5.1f}%)  {bar}")
    print()
    champ = sorted_w[0][0]
    print(f"  ★  WINNER WINNER CHICKEN DINNER: {champ}  ★")
    print()
    out = histogram(wins, 100)
    print(f"  Histogram saved → {out}")
    print()
