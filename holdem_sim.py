"""
Texas Hold'em Poker Simulation
6 players: Player 1 = YOLO All-In, Players 2-6 = Elaborate strategies
100 tournaments, histogram of winners.
"""

import random
from collections import Counter
from itertools import combinations
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS = '23456789TJQKA'   # index 0..12
SUITS = 'cdhs'

def make_deck():
    return [(r, s) for r in range(13) for s in range(4)]

def evaluate_hand(cards):
    """Best 5-card score from up to 7 cards. Higher tuple = better hand."""
    if len(cards) < 5:
        return (0, [])
    best = None
    for combo in combinations(cards, 5):
        s = _score5(combo)
        if best is None or s > best:
            best = s
    return best

def _score5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    rc = Counter(ranks)
    counts = sorted(rc.values(), reverse=True)
    sorted_by_cnt = sorted(rc.keys(), key=lambda r: (rc[r], r), reverse=True)
    flush = len(set(suits)) == 1
    straight, sh = _check_straight(sorted(rc.keys()))
    if straight and flush: return (8, sh)
    if counts[0] == 4:     return (7, sorted_by_cnt)
    if counts[0] == 3 and counts[1] == 2: return (6, sorted_by_cnt)
    if flush:              return (5, ranks)
    if straight:           return (4, sh)
    if counts[0] == 3:     return (3, sorted_by_cnt)
    if counts[0] == 2 and counts[1] == 2: return (2, sorted_by_cnt)
    if counts[0] == 2:     return (1, sorted_by_cnt)
    return (0, ranks)

def _check_straight(unique_asc):
    u = sorted(set(unique_asc))
    if len(u) < 5:
        return False, 0
    for i in range(len(u) - 4):
        window = u[i:i+5]
        if window[-1] - window[0] == 4:
            return True, window[-1]
    # Wheel A-2-3-4-5
    if set([0,1,2,3,12]).issubset(set(u)):
        return True, 3
    return False, 0

# ---------------------------------------------------------------------------
# Simple pre-flop equity estimate (no MC on pre-flop for speed)
# ---------------------------------------------------------------------------
def preflop_score(hole):
    r1, r2 = hole[0][0], hole[1][0]
    s1, s2 = hole[0][1], hole[1][1]
    suited = s1 == s2
    pair   = r1 == r2
    high, low = max(r1,r2), min(r1,r2)
    sc = high * 2 + low
    if pair:   sc += 22
    if suited: sc += 6
    if abs(r1-r2) <= 3 and not pair: sc += 4
    return min(sc / 68.0, 1.0)

def postflop_equity(hole, community, trials=80):
    """Monte-Carlo equity estimate vs one random opponent."""
    known = set(map(tuple, hole + community))
    deck  = [c for c in make_deck() if tuple(c) not in known]
    needed = 5 - len(community)
    wins = 0
    for _ in range(trials):
        random.shuffle(deck)
        extra = deck[:needed]
        full  = community + extra
        opp   = deck[needed:needed+2]
        if evaluate_hand(hole + full) >= evaluate_hand(opp + full):
            wins += 1
    return wins / trials

# ---------------------------------------------------------------------------
# Game state passed to strategies
# ---------------------------------------------------------------------------
class GameState:
    __slots__ = ['community','pot','current_bet','round','active','bb']
    def __init__(self, community, pot, current_bet, rnd, active, bb):
        self.community    = community
        self.pot          = pot
        self.current_bet  = current_bet
        self.round        = rnd
        self.active       = active   # list of Player (not folded, inc all-in)
        self.bb           = bb

# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid, chips, strategy):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.folded   = False
        self.all_in   = False
        self.bet      = 0   # amount committed this street

    def reset(self):
        self.hole    = []
        self.folded  = False
        self.all_in  = False
        self.bet     = 0

# ---------------------------------------------------------------------------
# STRATEGY 1 — YOLO All-In every single time
# ---------------------------------------------------------------------------
class YOLOAllIn:
    name = "YOLO All-In"
    color = "#e74c3c"

    def decide(self, player, gs):
        return ('raise', player.chips)

# ---------------------------------------------------------------------------
# STRATEGY 2 — Tight Aggressive (TAG)
# ---------------------------------------------------------------------------
class TightAggressive:
    name = "Tight-Aggressive"
    color = "#3498db"

    def decide(self, player, gs):
        to_call = gs.current_bet - player.bet
        pot     = gs.pot

        if gs.round == 'preflop':
            pf = preflop_score(player.hole)
            if pf > 0.72:                            # premium: 3-bet big
                return ('raise', min(pot + to_call + gs.bb*3, player.chips))
            if pf > 0.52 and to_call <= gs.bb * 4:  # decent: flat
                return ('call', to_call)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq = postflop_equity(player.hole, gs.community)
        if eq > 0.72:
            bet = min(int(pot * 0.70), player.chips)
            return ('raise', max(bet, gs.bb))
        if eq > 0.52 and to_call <= pot * 0.30:
            return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 3 — Loose Aggressive Bluffer (LAG)
# ---------------------------------------------------------------------------
class LooseAggressive:
    name = "Loose-Aggressive"
    color = "#2ecc71"

    def decide(self, player, gs):
        to_call = gs.current_bet - player.bet
        pot     = gs.pot
        n_opp   = len([p for p in gs.active if not p.folded and p.pid != player.pid])

        if gs.round == 'preflop':
            pf = preflop_score(player.hole)
            if pf > 0.42:
                return ('raise', min(int(gs.bb * 2.5), player.chips))
            if to_call <= gs.bb:
                return ('call', to_call)
            return ('fold', 0)

        eq = postflop_equity(player.hole, gs.community)
        bluff_odds = 0.28 + 0.06 * n_opp

        if eq > 0.60:
            bet = min(int(pot * 0.80), player.chips)
            return ('raise', max(bet, gs.bb))
        if eq > bluff_odds and random.random() < 0.45:  # semi-bluff
            bet = min(int(pot * 0.55), player.chips)
            return ('raise', max(bet, gs.bb))
        if to_call == 0:
            if random.random() < 0.30:                  # probe bet
                return ('raise', max(int(pot * 0.30), gs.bb))
            return ('check', 0)
        if to_call <= pot * 0.35:
            return ('call', to_call)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 4 — Position-Aware
# ---------------------------------------------------------------------------
class PositionAware:
    name = "Position-Aware"
    color = "#f39c12"

    def decide(self, player, gs):
        to_call = gs.current_bet - player.bet
        pot     = gs.pot
        alive   = [p for p in gs.active if not p.folded]
        if not alive:
            return ('check', 0)
        pos_idx  = next((i for i,p in enumerate(alive) if p.pid==player.pid), 0)
        position = pos_idx / max(len(alive)-1, 1)   # 0=early  1=late(button)

        if gs.round == 'preflop':
            pf        = preflop_score(player.hole)
            threshold = 0.62 - position * 0.26      # late = looser threshold
            if pf > threshold:
                if position > 0.65:
                    return ('raise', min(gs.bb*3, player.chips))
                if to_call <= gs.bb * 3:
                    return ('call', to_call)
                return ('fold', 0)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq = postflop_equity(player.hole, gs.community)
        # In position = willing to bluff/bet wider
        bet_threshold = 0.65 - position * 0.20

        if eq > bet_threshold:
            size = 0.50 + position * 0.30
            bet  = min(int(pot * size), player.chips)
            return ('raise', max(bet, gs.bb))
        if eq > 0.40 and to_call <= pot * 0.35:
            return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 5 — Pot-Odds Calculator
# ---------------------------------------------------------------------------
class PotOddsCalc:
    name = "Pot Odds Calc"
    color = "#9b59b6"

    def decide(self, player, gs):
        to_call = gs.current_bet - player.bet
        pot     = gs.pot

        if gs.round == 'preflop':
            pf      = preflop_score(player.hole)
            pot_frac = to_call / (pot + to_call + 1e-9)
            if pf > 0.65:
                return ('raise', min(int(pot*0.55)+to_call, player.chips))
            if pf > pot_frac + 0.10:
                return ('call', to_call)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq      = postflop_equity(player.hole, gs.community)
        pot_frac = to_call / (pot + to_call + 1e-9)

        if to_call > 0:
            if eq > pot_frac + 0.12:
                if eq > 0.68:
                    bet = min(int(pot*0.65), player.chips)
                    return ('raise', max(bet, gs.bb))
                return ('call', to_call)
            return ('fold', 0)
        else:
            if eq > 0.58:
                bet = min(int(pot*0.55), player.chips)
                return ('raise', max(bet, gs.bb))
            return ('check', 0)

# ---------------------------------------------------------------------------
# STRATEGY 6 — GTO-Inspired Mixed Frequencies
# ---------------------------------------------------------------------------
class GTOInspired:
    name = "GTO-Inspired"
    color = "#1abc9c"

    def __init__(self):
        self.af = random.uniform(0.42, 0.68)   # aggression factor per instance

    def decide(self, player, gs):
        to_call = gs.current_bet - player.bet
        pot     = gs.pot
        rng     = random.random()

        if gs.round == 'preflop':
            pf = preflop_score(player.hole)
            if pf > 0.80:
                sz = gs.bb * random.randint(2, 4)
                return ('raise', min(sz, player.chips))
            if pf > 0.58:
                if rng < self.af:
                    return ('raise', min(gs.bb*2, player.chips))
                if to_call <= gs.bb*3:
                    return ('call', to_call)
                return ('fold', 0)
            if pf > 0.35:
                if rng < 0.22 and to_call <= gs.bb*2:
                    return ('call', to_call)
                if to_call == 0:
                    return ('check', 0)
                return ('fold', 0)
            # trash — occasional bluff raise
            if rng < 0.10:
                return ('raise', min(gs.bb*3, player.chips))
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq = postflop_equity(player.hole, gs.community)

        if eq > 0.80:
            sz = random.choice([0.50, 0.65, 0.80])
            return ('raise', max(int(pot*sz), gs.bb))
        if eq > 0.60:
            if rng < 0.75:
                return ('raise', max(int(pot*0.55), gs.bb))
            if to_call == 0: return ('check', 0)
            return ('call', to_call) if to_call <= pot*0.40 else ('fold', 0)
        if eq > 0.40:
            if to_call == 0:
                if rng < self.af*0.40:
                    return ('raise', max(int(pot*0.40), gs.bb))
                return ('check', 0)
            pot_frac = to_call / (pot + to_call + 1e-9)
            return ('call', to_call) if eq > pot_frac else ('fold', 0)
        # weak hand — bluff or give up
        if to_call == 0 and rng < self.af*0.35:
            return ('raise', max(int(pot*0.45), gs.bb))
        return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Texas Hold'em Engine
# ---------------------------------------------------------------------------
STREETS = [('preflop', 0), ('flop', 3), ('turn', 1), ('river', 1)]

class HoldemGame:
    def __init__(self, players, bb=20):
        self.players = players
        self.bb      = bb
        self.sb      = bb // 2
        self.dealer  = 0

    def _post_blinds(self, alive):
        n = len(alive)
        sb_p = alive[self.dealer % n]
        bb_p = alive[(self.dealer+1) % n]

        sb_amt = min(self.sb, sb_p.chips)
        bb_amt = min(self.bb, bb_p.chips)
        sb_p.chips -= sb_amt;  sb_p.bet = sb_amt
        bb_p.chips -= bb_amt;  bb_p.bet = bb_amt
        if sb_p.chips == 0: sb_p.all_in = True
        if bb_p.chips == 0: bb_p.all_in = True
        return sb_amt + bb_amt, bb_amt, self.dealer % n, (self.dealer+1) % n

    def _betting_round(self, active, current_bet, pot, community, rnd, first_to_act):
        """Run one betting round. Returns updated pot and current_bet."""
        bb = self.bb
        can_act = [p for p in active if not p.folded and not p.all_in]
        if not can_act:
            return pot, current_bet

        # Order: start from first_to_act
        n = len(active)
        ordered = []
        for i in range(n):
            p = active[(first_to_act + i) % n]
            if not p.folded and not p.all_in:
                ordered.append(p)

        gs = GameState(community, pot, current_bet, rnd, active, bb)
        acted = set()
        last_aggressor = None
        queue = list(ordered)

        while queue:
            player = queue.pop(0)
            if player.folded or player.all_in:
                continue
            # Already acted and no new aggression?
            if player.pid in acted and player.pid != (last_aggressor.pid if last_aggressor else -1):
                if player.bet >= current_bet:
                    continue   # nothing to do

            gs.pot         = pot
            gs.current_bet = current_bet
            action, amount = player.strategy.decide(player, gs)

            if action == 'fold':
                player.folded = True

            elif action in ('check', 'call'):
                call_amt = min(current_bet - player.bet, player.chips)
                player.chips -= call_amt
                player.bet   += call_amt
                pot          += call_amt
                if player.chips == 0:
                    player.all_in = True

            elif action == 'raise':
                # Amount is the TOTAL additional chips to put in (raise to)
                target_total = max(int(amount), current_bet + bb)
                additional   = min(target_total - player.bet, player.chips)
                player.chips -= additional
                player.bet   += additional
                pot          += additional
                if player.chips == 0:
                    player.all_in = True
                if player.bet > current_bet:
                    current_bet    = player.bet
                    last_aggressor = player
                    # Everyone else gets to act again
                    for p in active:
                        if not p.folded and not p.all_in and p.pid != player.pid:
                            if p not in queue:
                                queue.append(p)

            acted.add(player.pid)

        return pot, current_bet

    def play_hand(self):
        alive = [p for p in self.players if p.chips > 0]
        if len(alive) < 2:
            return

        for p in alive:
            p.reset()

        deck = make_deck()
        random.shuffle(deck)
        community = []
        pot, current_bet, sb_idx, bb_idx = self._post_blinds(alive)

        # Deal hole cards
        for p in alive:
            p.hole = [deck.pop(), deck.pop()]

        n = len(alive)
        first = (bb_idx + 1) % n   # UTG pre-flop

        for street, num_cards in STREETS:
            # Deal community cards
            if num_cards:
                deck.pop()   # burn
                for _ in range(num_cards):
                    community.append(deck.pop())

            still_up = [p for p in alive if not p.folded]
            if len(still_up) < 2:
                break

            # Reset bets for new street (post-flop)
            if street != 'preflop':
                for p in alive:
                    p.bet = 0
                current_bet = 0
                first = sb_idx % n   # SB acts first post-flop

            pot, current_bet = self._betting_round(
                alive, current_bet, pot, list(community), street, first
            )

            still_up = [p for p in alive if not p.folded]
            if len(still_up) < 2:
                break

        # Showdown / award pot
        remaining = [p for p in alive if not p.folded]
        if len(remaining) == 1:
            remaining[0].chips += pot
        else:
            scores = [(evaluate_hand(p.hole + community), p) for p in remaining]
            best   = max(scores, key=lambda x: x[0])[0]
            winners = [p for sc, p in scores if sc == best]
            share   = pot // len(winners)
            for w in winners:
                w.chips += share

        self.dealer = (self.dealer + 1) % len(alive)

    def run_tournament(self, max_hands=600):
        """Play until one player has all chips. Return winner pid."""
        for _ in range(max_hands):
            alive = [p for p in self.players if p.chips > 0]
            if len(alive) <= 1:
                break
            self.play_hand()
        alive = [p for p in self.players if p.chips > 0]
        return max(alive, key=lambda p: p.chips).pid if alive else None

# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------
STRATEGY_META = [
    (1, YOLOAllIn,       ),
    (2, TightAggressive, ),
    (3, LooseAggressive, ),
    (4, PositionAware,   ),
    (5, PotOddsCalc,     ),
    (6, GTOInspired,     ),
]

def make_players(starting_chips=1500):
    players = []
    for pid, StratClass in STRATEGY_META:
        s = StratClass()
        players.append(Player(pid, starting_chips, s))
    return players

def run_simulations(n=100, starting_chips=1500):
    winner_counts = Counter()
    for i in range(n):
        if i % 10 == 0:
            print(f"  sim {i+1}/{n}...")
        players = make_players(starting_chips)
        game    = HoldemGame(players, bb=20)
        winner  = game.run_tournament()
        if winner:
            winner_counts[winner] += 1
    return winner_counts

# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------
def plot_histogram(winner_counts, n=100):
    COLORS = {
        1: "#e74c3c",
        2: "#3498db",
        3: "#2ecc71",
        4: "#f39c12",
        5: "#9b59b6",
        6: "#1abc9c",
    }
    LABELS = {
        1: "P1\nYOLO All-In",
        2: "P2\nTight-Agg",
        3: "P3\nLoose-Agg",
        4: "P4\nPosition-\nAware",
        5: "P5\nPot Odds",
        6: "P6\nGTO-Insp",
    }

    pids  = list(range(1, 7))
    wins  = [winner_counts.get(p, 0) for p in pids]
    cols  = [COLORS[p] for p in pids]
    lbls  = [LABELS[p] for p in pids]

    fig, ax = plt.subplots(figsize=(13, 7))
    fig.patch.set_facecolor('#0d0d1a')
    ax.set_facecolor('#111122')

    bars = ax.bar(lbls, wins, color=cols, edgecolor='white', linewidth=1.4, alpha=0.92, width=0.6)

    # Red border on P1 for emphasis
    bars[0].set_edgecolor('#ff0000')
    bars[0].set_linewidth(3)

    for bar, w in zip(bars, wins):
        ax.text(bar.get_x() + bar.get_width()/2,
                bar.get_height() + 0.4,
                str(w),
                ha='center', va='bottom',
                color='white', fontsize=15, fontweight='bold')

    ax.set_ylim(0, max(wins) + 12)
    ax.set_title(
        '\U0001f0cf  Texas Hold\'em  —  100 Tournament Simulations\n'
        'Winner Winner Chicken Dinner  \U0001f357',
        color='white', fontsize=17, fontweight='bold', pad=18
    )
    ax.set_xlabel('Player / Strategy', color='#cccccc', fontsize=12, labelpad=8)
    ax.set_ylabel('Tournaments Won', color='#cccccc', fontsize=12)
    ax.tick_params(colors='white', labelsize=10)
    for spine in ('bottom', 'left'):
        ax.spines[spine].set_color('#555577')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.yaxis.grid(True, alpha=0.25, color='white', linestyle='--')
    ax.set_axisbelow(True)

    note = (
        'P1 = if my_turn → bet = all_in   |   P2–P6 = Elaborate strategies\n'
        'All players start with 1500 chips, blind = 20. No player knows rivals\' strategy.'
    )
    ax.text(0.02, 0.97, note, transform=ax.transAxes,
            color='#aaaacc', fontsize=9, va='top',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#1a1a33', alpha=0.7))

    plt.tight_layout()
    out = 'poker_results.png'
    plt.savefig(out, dpi=150, bbox_inches='tight', facecolor='#0d0d1a')
    print(f"\nHistogram saved → {out}")
    return out

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=" * 60)
    print("  Texas Hold'em Simulation  — 6 players, 100 tournaments")
    print("=" * 60)
    print("\nStrategies:")
    for pid, StratClass in STRATEGY_META:
        s = StratClass()
        print(f"  P{pid}: {s.name}")

    print("\nRunning simulations...\n")
    wc = run_simulations(100)

    print("\n" + "=" * 60)
    print("  FINAL STANDINGS  (out of 100 tournaments)")
    print("=" * 60)
    for pid, StratClass in STRATEGY_META:
        s    = StratClass()
        wins = wc.get(pid, 0)
        bar  = '█' * wins + '░' * (50 - wins)
        print(f"  P{pid}  {s.name:20s}  {wins:3d}  {bar[:40]}")

    print()
    plot_histogram(wc)
    print("\nDone. suflair GPT has been humiliated.")
