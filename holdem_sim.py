"""
Texas Hold'em Poker Tournament Simulator
100 tournaments · 6 players · Player 1 = All-In Maniac
Players 2-6 = elaborate strategic bots
"""

import random
import itertools
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import sys

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS   = '23456789TJQKA'
SUITS   = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}   # '2'->2 … 'A'->14

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def rank(card):
    return RANK_VAL[card[0]]

# ---------------------------------------------------------------------------
# Hand evaluator — returns a tuple that compares correctly with >
# Category:  8=SF 7=Quads 6=FH 5=Flush 4=Straight 3=Trips 2=TwoPair 1=Pair 0=High
# ---------------------------------------------------------------------------
def score_five(cards):
    ranks = sorted([rank(c) for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    rc    = Counter(ranks)
    counts = sorted(rc.values(), reverse=True)

    flush    = len(set(suits)) == 1
    straight = len(set(ranks)) == 5 and (ranks[0] - ranks[4] == 4)
    # Wheel (A-2-3-4-5)
    if set(ranks) == {14, 2, 3, 4, 5}:
        straight = True
        ranks = [5, 4, 3, 2, 1]

    if straight and flush:
        return (8, ranks)
    if counts == [4, 1]:
        q = [r for r, c in rc.items() if c == 4]
        k = [r for r, c in rc.items() if c == 1]
        return (7, q + k)
    if counts == [3, 2]:
        tr = [r for r, c in rc.items() if c == 3]
        pa = [r for r, c in rc.items() if c == 2]
        return (6, tr + pa)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts == [3, 1, 1]:
        tr = [r for r, c in rc.items() if c == 3]
        ki = sorted([r for r, c in rc.items() if c == 1], reverse=True)
        return (3, tr + ki)
    if counts == [2, 2, 1]:
        pa = sorted([r for r, c in rc.items() if c == 2], reverse=True)
        ki = [r for r, c in rc.items() if c == 1]
        return (2, pa + ki)
    if counts == [2, 1, 1, 1]:
        pa = [r for r, c in rc.items() if c == 2]
        ki = sorted([r for r, c in rc.items() if c == 1], reverse=True)
        return (1, pa + ki)
    return (0, ranks)

def best_hand(cards):
    return max(score_five(c) for c in itertools.combinations(cards, 5))

# ---------------------------------------------------------------------------
# Pre-flop hand strength (0-1)
# ---------------------------------------------------------------------------
def preflop_strength(hole):
    r1, r2 = sorted([rank(c) for c in hole], reverse=True)
    suited  = hole[0][1] == hole[1][1]

    if r1 == r2:                             # Pocket pair
        return 0.50 + (r1 - 2) / 26.0
    gap = r1 - r2
    base = (r1 + r2 - 4) / 56.0             # Higher cards = stronger
    suited_bonus    = 0.08 if suited  else 0
    connector_bonus = 0.08 if gap <= 2 else (0.04 if gap <= 4 else 0)
    return max(0.05, min(0.95, base + suited_bonus + connector_bonus - gap * 0.02))

# ---------------------------------------------------------------------------
# Monte-Carlo equity estimator (post-flop)
# ---------------------------------------------------------------------------
def mc_equity(hole, community, n_opponents, n_sims=120):
    known = set(map(tuple, hole + community))
    deck  = [c for c in make_deck() if tuple(c) not in known]
    need  = 5 - len(community)
    wins  = 0

    for _ in range(n_sims):
        random.shuffle(deck)
        idx = 0
        board = community + deck[idx:idx + need]; idx += need
        my_score = best_hand(hole + board)
        beat = False
        for _ in range(n_opponents):
            if idx + 2 > len(deck):
                break
            opp_score = best_hand(deck[idx:idx+2] + board); idx += 2
            if opp_score >= my_score:
                beat = True
                break
        if not beat:
            wins += 1
    return wins / n_sims

# ---------------------------------------------------------------------------
# Player & base Strategy
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid, strategy, chips):
        self.pid      = pid
        self.strategy = strategy
        self.chips    = chips
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.bet_rnd  = 0          # chips committed this betting round
        self.pos      = 'middle'

    @property
    def active(self):
        return not self.folded

    @property
    def can_bet(self):
        return not self.folded and not self.allin and self.chips > 0

class Strategy:
    def __init__(self, name):
        self.name = name

    def act(self, pstate, gstate):
        """Return ('fold'|'call'|'raise'|'allin', amount)"""
        raise NotImplementedError

# ===========================================================================
# Strategy 0 — The All-In Maniac (Player 1)
# ===========================================================================
class AllinManiac(Strategy):
    def __init__(self):
        super().__init__("🤡 All-In Maniac")

    def act(self, ps, gs):
        # if my_turn then bet = ALL IN fi
        return ('allin', ps['chips'])

# ===========================================================================
# Strategy 1 — Tight-Aggressive (TAG)
# Only enters with premium holdings; punishes limpers hard
# ===========================================================================
class TightAggressive(Strategy):
    def __init__(self):
        super().__init__("🎯 Tight Aggressive")

    def act(self, ps, gs):
        hole, board = ps['hole'], gs['board']
        pot, tcall, chips = gs['pot'], gs['to_call'], ps['chips']
        street, nop = gs['street'], gs['n_opp']

        if street == 'preflop':
            strength = preflop_strength(hole)
            if strength >= 0.72:
                return ('raise', min(chips, max(tcall * 3, pot // 2 + tcall)))
            if strength >= 0.52 and tcall < chips * 0.10:
                return ('call', tcall)
            return ('fold', 0)

        strength = mc_equity(hole, board, nop, 100)
        if strength >= 0.68:
            amt = min(chips, max(tcall * 2, int(pot * 0.75)))
            return ('raise', amt) if amt > tcall else ('call', tcall)
        if strength >= 0.42 and tcall <= chips * 0.15:
            return ('call', tcall)
        if tcall == 0:
            return ('call', 0)
        return ('fold', 0)

# ===========================================================================
# Strategy 2 — Loose-Aggressive (LAG)
# Wide range, frequent bluffs, applies maximum pressure
# ===========================================================================
class LooseAggressive(Strategy):
    def __init__(self):
        super().__init__("🐍 Loose Aggressive")

    def act(self, ps, gs):
        hole, board = ps['hole'], gs['board']
        pot, tcall, chips = gs['pot'], gs['to_call'], ps['chips']
        street, nop, pos = gs['street'], gs['n_opp'], ps['pos']

        bluff_freq = 0.35 + (0.15 if pos == 'late' else 0)

        if street == 'preflop':
            strength = preflop_strength(hole)
            if strength >= 0.38 or random.random() < bluff_freq:
                size = min(chips, int(pot * 1.2) + tcall)
                return ('raise', size)
            return ('fold', 0)

        strength = mc_equity(hole, board, nop, 80)
        if strength >= 0.48:
            size = min(chips, int(pot * 0.85))
            return ('raise', size) if size > tcall else ('call', tcall)
        if random.random() < bluff_freq and tcall == 0:
            return ('raise', min(chips, pot // 2))
        if tcall == 0:
            return ('call', 0)
        return ('fold', 0) if random.random() > bluff_freq else ('call', min(tcall, chips))

# ===========================================================================
# Strategy 3 — Position Master
# Aggression scales with position; folds trash OOP, steals IP
# ===========================================================================
class PositionMaster(Strategy):
    def __init__(self):
        super().__init__("📍 Position Master")

    POS_MULT = {'blind': 0.80, 'early': 0.85, 'middle': 1.00, 'late': 1.30}

    def act(self, ps, gs):
        hole, board = ps['hole'], gs['board']
        pot, tcall, chips = gs['pot'], gs['to_call'], ps['chips']
        street, nop, pos = gs['street'], gs['n_opp'], ps['pos']

        pm = self.POS_MULT.get(pos, 1.0)

        if street == 'preflop':
            strength = preflop_strength(hole)
            threshold = 0.55 / pm
            if strength >= threshold:
                size = min(chips, int(max(tcall * 2.5, pot * pm * 0.5)))
                return ('raise', size)
            if strength >= threshold * 0.75 and tcall < chips * 0.08:
                return ('call', tcall)
            # Late position steal attempt
            if pos == 'late' and nop <= 2 and random.random() < 0.45:
                return ('raise', min(chips, pot + tcall))
            return ('fold', 0)

        strength = mc_equity(hole, board, nop, 100)
        adj = min(1.0, strength * pm)

        if adj >= 0.65:
            size = min(chips, int(pot * pm * 0.70))
            return ('raise', size) if size > tcall else ('call', tcall)
        if strength >= 0.40 and tcall < chips * 0.18:
            return ('call', tcall)
        if tcall == 0:
            return ('call', 0)
        return ('fold', 0)

# ===========================================================================
# Strategy 4 — Pot-Odds Rationalist
# Calls only when equity > price; raises for value with sizing discipline
# ===========================================================================
class PotOddsRationalist(Strategy):
    def __init__(self):
        super().__init__("📐 Pot Odds Rationalist")

    def act(self, ps, gs):
        hole, board = ps['hole'], gs['board']
        pot, tcall, chips = gs['pot'], gs['to_call'], ps['chips']
        street, nop = gs['street'], gs['n_opp']

        tcall = min(tcall, chips)

        if street == 'preflop':
            equity = preflop_strength(hole)
        else:
            equity = mc_equity(hole, board, nop, 120)

        if tcall == 0:
            if equity >= 0.62:
                size = min(chips, int(pot * 0.67))
                return ('raise', size)
            return ('call', 0)

        price = tcall / (pot + tcall)          # Pot odds break-even
        implied_price = price * 0.72           # Implied-odds discount

        if equity >= price:
            if equity >= 0.68:
                size = min(chips, int(pot * 0.80))
                return ('raise', size) if size > tcall * 1.4 else ('call', tcall)
            return ('call', tcall)
        if equity >= implied_price and tcall < chips * 0.12:
            return ('call', tcall)
        return ('fold', 0)

# ===========================================================================
# Strategy 5 — GTO Approximator
# Balanced betting ranges: value bets, bluffs at solver-like frequencies
# ===========================================================================
class GTOApproximator(Strategy):
    def __init__(self):
        super().__init__("🧠 GTO Approximator")

    def act(self, ps, gs):
        hole, board = ps['hole'], gs['board']
        pot, tcall, chips = gs['pot'], gs['to_call'], ps['chips']
        street, nop = gs['street'], gs['n_opp']

        if street == 'preflop':
            equity = preflop_strength(hole)
        else:
            equity = mc_equity(hole, board, nop, 120)

        # Value-bet tier  (80% raise, 20% slowplay)
        if equity >= 0.74:
            if random.random() < 0.80:
                size = min(chips, int(pot * (0.55 + equity * 0.45)))
                return ('raise', size) if size > tcall else ('call', tcall)
            return ('call', tcall)

        # Strong tier  (raise 60% / call 40%)
        if equity >= 0.58:
            if tcall == 0:
                return ('raise', min(chips, int(pot * 0.45))) if random.random() < 0.55 else ('call', 0)
            if tcall < chips * 0.22:
                return ('call', tcall)
            if random.random() < 0.50:
                return ('raise', min(chips, tcall + int(pot * 0.35)))
            return ('fold', 0)

        # Bluff-catching tier
        if equity >= 0.38:
            if tcall == 0:
                return ('raise', min(chips, int(pot * 0.33))) if random.random() < 0.28 else ('call', 0)
            if tcall < chips * 0.10:
                return ('call', tcall)
            return ('fold', 0)

        # Pure bluffs  (25% freq — balanced range)
        if random.random() < 0.22 and tcall == 0:
            return ('raise', min(chips, int(pot * 0.42)))
        if tcall == 0:
            return ('call', 0)
        return ('fold', 0)

# ===========================================================================
# Game Engine
# ===========================================================================
STARTING_CHIPS = 2000
BIG_BLIND      = 40
SMALL_BLIND    = 20

def assign_positions(players):
    n = len(players)
    for i, p in enumerate(players):
        frac = i / n
        if i < 2:
            p.pos = 'blind'
        elif frac < 0.33:
            p.pos = 'early'
        elif frac < 0.67:
            p.pos = 'middle'
        else:
            p.pos = 'late'

def betting_round(players, board, pot, street, bb):
    """Single betting round; returns updated pot."""
    active    = [p for p in players if p.active]
    if len(active) < 2:
        return pot

    current_bet = max(p.bet_rnd for p in players)
    queue       = [p for p in active if p.can_bet]
    acted       = set()
    ceiling     = len(players) * 6   # safety cap

    while queue and ceiling:
        ceiling -= 1
        p = queue.pop(0)
        if not p.can_bet:
            continue

        to_call  = max(0, current_bet - p.bet_rnd)
        to_call  = min(to_call, p.chips)
        n_active = sum(1 for x in players if x.active)
        n_opp    = max(1, n_active - 1)

        gs = {
            'board':    board,
            'pot':      pot,
            'to_call':  to_call,
            'street':   street,
            'n_opp':    n_opp,
            'bb':       bb,
        }
        ps = {
            'hole':  p.hole,
            'chips': p.chips,
            'pos':   p.pos,
            'bet':   p.bet_rnd,
        }

        action, amount = p.strategy.act(ps, gs)

        if action == 'fold':
            p.folded = True
            acted.add(p.pid)

        elif action == 'call':
            spend = min(to_call, p.chips)
            p.chips   -= spend
            p.bet_rnd += spend
            pot       += spend
            if p.chips == 0:
                p.allin = True
            acted.add(p.pid)

        else:   # raise or allin
            if action == 'allin':
                amount = p.chips
            # Minimum raise rule: total bet must be at least current_bet + last_raise
            min_total = max(current_bet * 2, bb) if current_bet > 0 else bb
            desired_total = max(p.bet_rnd + amount, min_total)
            desired_total = min(desired_total, p.bet_rnd + p.chips)

            spend = desired_total - p.bet_rnd
            spend = min(spend, p.chips)

            p.chips   -= spend
            p.bet_rnd += spend
            pot       += spend

            if p.chips == 0:
                p.allin = True

            if p.bet_rnd > current_bet:
                current_bet = p.bet_rnd
                # Re-open action for everyone else who already acted
                for other in players:
                    if other.can_bet and other.pid != p.pid and other.pid in acted:
                        queue.append(other)

            acted.add(p.pid)

        if sum(1 for x in players if x.active) <= 1:
            break

    return pot


def play_hand(players, dealer_idx):
    deck = make_deck()
    random.shuffle(deck)

    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return dealer_idx

    for p in alive:
        p.hole    = [deck.pop(), deck.pop()]
        p.folded  = False
        p.allin   = False
        p.bet_rnd = 0

    assign_positions(alive)
    n   = len(alive)
    pot = 0

    # --- Post blinds ---
    sb_p = alive[dealer_idx % n]
    bb_p = alive[(dealer_idx + 1) % n]

    sb_amt = min(sb_p.chips, SMALL_BLIND)
    sb_p.chips -= sb_amt; sb_p.bet_rnd = sb_amt; pot += sb_amt

    bb_amt = min(bb_p.chips, BIG_BLIND)
    bb_p.chips -= bb_amt; bb_p.bet_rnd = bb_amt; pot += bb_amt

    board = []

    for street, burn, n_cards in [
        ('preflop', 0, 0),
        ('flop',    1, 3),
        ('turn',    1, 1),
        ('river',   1, 1),
    ]:
        for _ in range(burn):
            deck.pop()          # burn card
        for _ in range(n_cards):
            board.append(deck.pop())

        if street != 'preflop':
            for p in alive:
                p.bet_rnd = 0

        remaining = [p for p in alive if p.active]
        if len(remaining) <= 1:
            break

        pot = betting_round(alive, board, pot, street, BIG_BLIND)

        remaining = [p for p in alive if p.active]
        if len(remaining) <= 1:
            break

    # --- Showdown ---
    survivors = [p for p in alive if p.active]
    if len(survivors) == 1:
        survivors[0].chips += pot
    else:
        scored = sorted(
            ((best_hand(p.hole + board), p) for p in survivors),
            key=lambda x: x[0],
            reverse=True
        )
        top_score = scored[0][0]
        winners   = [p for s, p in scored if s == top_score]
        share, rem = divmod(pot, len(winners))
        for w in winners:
            w.chips += share
        winners[0].chips += rem   # leftover chip to first winner

    return (dealer_idx + 1) % n


def run_tournament():
    strategies = [
        AllinManiac(),
        TightAggressive(),
        LooseAggressive(),
        PositionMaster(),
        PotOddsRationalist(),
        GTOApproximator(),
    ]
    players = [Player(i + 1, s, STARTING_CHIPS) for i, s in enumerate(strategies)]

    dealer = 0
    for _ in range(800):          # max hands per tournament
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        n_alive = len(alive)
        dealer = play_hand(alive, dealer % n_alive)

    winner = max(players, key=lambda p: p.chips)
    return winner.strategy.name


# ===========================================================================
# Run 100 simulations
# ===========================================================================
STRATEGY_NAMES = [
    "🤡 All-In Maniac",
    "🎯 Tight Aggressive",
    "🐍 Loose Aggressive",
    "📍 Position Master",
    "📐 Pot Odds Rationalist",
    "🧠 GTO Approximator",
]

def main():
    N_SIMS = 100
    tally  = {name: 0 for name in STRATEGY_NAMES}

    print("=" * 65)
    print("  Texas Hold'em — 100 Tournament Simulations")
    print("  Player 1: if my_turn then bet = ALL IN fi")
    print("  Players 2-6: elaborate strategic algorithms")
    print("=" * 65)

    for sim in range(1, N_SIMS + 1):
        winner = run_tournament()
        tally[winner] += 1
        if sim % 10 == 0:
            print(f"  [{sim:3d}/100]  running tallies: " +
                  " | ".join(f"{k.split()[-1]}={v}" for k, v in tally.items()))
        sys.stdout.flush()

    # --- Results ---
    print("\n" + "=" * 65)
    print("  FINAL SCOREBOARD — Winner Winner Chicken Dinner")
    print("=" * 65)
    sorted_results = sorted(tally.items(), key=lambda x: -x[1])
    for rank_pos, (name, wins) in enumerate(sorted_results, 1):
        bar = "█" * wins
        crown = " 👑" if rank_pos == 1 else ""
        print(f"  {rank_pos}. {name:<28} {wins:3d} wins  {bar}{crown}")
    print("=" * 65)

    # --- Histogram ---
    names  = list(tally.keys())
    wins   = [tally[n] for n in names]
    short  = [n.split(' ', 1)[1] for n in names]   # strip emoji

    colours = ['#E74C3C' if '🤡' in n else '#3498DB' for n in names]
    edge    = ['#922B21' if '🤡' in n else '#1A5276'  for n in names]

    fig, ax = plt.subplots(figsize=(13, 7))
    fig.patch.set_facecolor('#0D1117')
    ax.set_facecolor('#161B22')

    bars = ax.bar(range(len(names)), wins, color=colours, edgecolor=edge,
                  linewidth=1.8, width=0.6, zorder=3)

    for bar, val in zip(bars, wins):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.8,
                str(val),
                ha='center', va='bottom',
                fontsize=14, fontweight='bold', color='white', zorder=4)

    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(short, fontsize=10, color='#C9D1D9',
                        rotation=12, ha='right')
    ax.set_ylabel('Tournament Wins  (out of 100)',
                  fontsize=12, color='#C9D1D9', labelpad=10)
    ax.tick_params(colors='#C9D1D9')
    for spine in ax.spines.values():
        spine.set_color('#30363D')

    ax.set_ylim(0, max(wins) + 8)
    ax.yaxis.grid(True, color='#30363D', linestyle='--', linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)

    ax.set_title(
        '♠  Texas Hold\'em · 100 Tournaments · 6 Players · 2000 Chips Each  ♠\n'
        'Winner Winner Chicken Dinner  —  Rounder Leaderboard',
        fontsize=14, fontweight='bold', color='white', pad=18
    )

    leg = [
        mpatches.Patch(facecolor='#E74C3C', edgecolor='#922B21', label='Player 1 — All-In Every Hand'),
        mpatches.Patch(facecolor='#3498DB', edgecolor='#1A5276', label='Players 2-6 — Elaborate Strategies'),
    ]
    ax.legend(handles=leg, loc='upper right', fontsize=10,
              facecolor='#21262D', edgecolor='#30363D', labelcolor='white')

    plt.tight_layout()
    out = '/home/user/spoderman/poker_histogram.png'
    plt.savefig(out, dpi=160, bbox_inches='tight', facecolor=fig.get_facecolor())
    print(f"\n  Histogram saved → {out}")
    return tally

if __name__ == '__main__':
    main()
