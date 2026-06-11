#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
Player 1: The All-In Savage (simple strategy)
Players 2-6: Elaborate strategic thinkers
100 simulations, histogram of winners
"""

import random
from collections import Counter
from itertools import combinations
import sys

# ──────────────────────────────────────────────
# CARD ENGINE
# ──────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ──────────────────────────────────────────────
# HAND EVALUATOR  (returns (rank, tiebreakers))
# rank: 8=straight flush, 7=four of a kind, ...0=high card
# ──────────────────────────────────────────────

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards."""
    best = None
    for combo in combinations(cards, 5):
        score = eval5(combo)
        if best is None or score > best:
            best = score
    return best

def eval5(cards):
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    # wheel straight A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        straight = True
        vals = [5, 4, 3, 2, 1]

    counts = sorted(Counter(vals).values(), reverse=True)
    groups = sorted(Counter(vals).keys(), key=lambda v: (Counter(vals)[v], v), reverse=True)

    if straight and flush:
        return (8, vals)
    if counts[0] == 4:
        return (7, groups)
    if counts[:2] == [3, 2]:
        return (6, groups)
    if flush:
        return (5, vals)
    if straight:
        return (4, vals)
    if counts[0] == 3:
        return (3, groups)
    if counts[:2] == [2, 2]:
        return (2, groups)
    if counts[0] == 2:
        return (1, groups)
    return (0, vals)

# ──────────────────────────────────────────────
# EQUITY ESTIMATION (Monte Carlo, fast)
# ──────────────────────────────────────────────

def estimate_equity(hole, community, deck, opponents=1, trials=200):
    """Estimate win probability for hole cards given community cards."""
    wins = 0
    remaining = [c for c in deck if c not in hole and c not in community]
    needed = 5 - len(community)
    for _ in range(trials):
        sample = random.sample(remaining, needed + 2 * opponents)
        board = list(community) + sample[:needed]
        my_score = hand_rank(hole + board)
        win = True
        for i in range(opponents):
            opp_hole = sample[needed + i*2: needed + i*2 + 2]
            opp_score = hand_rank(opp_hole + board)
            if opp_score > my_score:
                win = False
                break
        if win:
            wins += 1
    return wins / trials

def hole_strength(hole):
    """Quick pre-flop hand strength heuristic 0-1."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2
    high = max(r1, r2)
    low = min(r1, r2)
    score = (high + low) / 28.0  # normalize
    if pair:
        score += 0.2
    if suited:
        score += 0.05
    if abs(r1 - r2) <= 2:
        score += 0.03  # connectors
    return min(score, 1.0)

# ──────────────────────────────────────────────
# PLAYER / GAME STATE
# ──────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = strategy_fn
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.all_in = False

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.all_in = False

    def is_active(self):
        return not self.folded and not self.all_in and self.chips > 0

    def place_bet(self, amount):
        actual = min(amount, self.chips)
        self.chips -= actual
        self.bet_this_round += actual
        if self.chips == 0:
            self.all_in = True
        return actual

# ──────────────────────────────────────────────
# STRATEGIES
# ──────────────────────────────────────────────

def strategy_all_in_savage(player, state):
    """Player 1: always shove. No thoughts, only pain."""
    return ('raise', player.chips)


def strategy_tight_aggressive(player, state):
    """
    Strategy 2 – TAG (Tight-Aggressive).
    Only plays premium hands, bets hard when in.
    Folds junk pre-flop, continuation-bets strong boards.
    """
    stage = state['stage']
    to_call = state['to_call']
    pot = state['pot']
    community = state['community']
    hole = player.hole
    active_opponents = state['active_opponents']

    if stage == 'preflop':
        strength = hole_strength(hole)
        if strength >= 0.72:
            raise_amt = min(player.chips, max(to_call * 3, pot // 2))
            return ('raise', raise_amt)
        elif strength >= 0.55 and to_call < player.chips * 0.08:
            return ('call', to_call)
        elif to_call == 0:
            return ('check', 0)
        else:
            return ('fold', 0)
    else:
        deck = make_deck()
        eq = estimate_equity(hole, community, deck, opponents=max(1, active_opponents), trials=150)
        if eq >= 0.70:
            return ('raise', min(player.chips, pot))
        elif eq >= 0.50:
            if to_call == 0:
                return ('check', 0)
            return ('call', to_call)
        elif to_call == 0:
            return ('check', 0)
        else:
            return ('fold', 0)


def strategy_loose_passive(player, state):
    """
    Strategy 3 – Calling Station / Loose-Passive.
    Calls almost anything hoping to hit draws.
    Rarely raises, never folds cheap.
    """
    to_call = state['to_call']
    pot = state['pot']
    stage = state['stage']
    hole = player.hole
    community = state['community']

    threshold = player.chips * 0.25  # calls up to 25% of stack cheaply
    if to_call == 0:
        return ('check', 0)
    if to_call <= threshold:
        return ('call', to_call)
    # only folds truly trash pre-flop with huge bet
    if stage == 'preflop' and hole_strength(hole) < 0.35 and to_call > player.chips * 0.4:
        return ('fold', 0)
    if to_call <= player.chips * 0.45:
        return ('call', to_call)
    # pot odds check post-flop
    if stage != 'preflop' and pot > 0:
        pot_odds = to_call / (pot + to_call)
        deck = make_deck()
        eq = estimate_equity(hole, community, deck, opponents=1, trials=100)
        if eq >= pot_odds * 0.8:
            return ('call', to_call)
    return ('fold', 0)


def strategy_gto_approximator(player, state):
    """
    Strategy 4 – GTO-ish mixed strategy.
    Uses equity vs pot-odds with randomised bluff frequency (~33%).
    Mixes raises, calls, and folds proportionally.
    """
    stage = state['stage']
    to_call = state['to_call']
    pot = state['pot']
    community = state['community']
    active_opponents = state['active_opponents']
    hole = player.hole

    if stage == 'preflop':
        strength = hole_strength(hole)
        r = random.random()
        if strength >= 0.78:
            return ('raise', min(player.chips, pot + to_call))
        elif strength >= 0.55:
            if r < 0.6:
                return ('raise', min(player.chips, max(to_call * 2, pot // 3)))
            return ('call', to_call) if to_call > 0 else ('check', 0)
        elif strength >= 0.40:
            if to_call == 0:
                return ('check', 0) if r > 0.25 else ('raise', min(player.chips, pot // 4))
            if to_call < player.chips * 0.10:
                return ('call', to_call)
            return ('fold', 0)
        else:
            if r < 0.15 and to_call == 0:  # bluff
                return ('raise', min(player.chips, pot // 3))
            return ('fold', 0) if to_call > 0 else ('check', 0)
    else:
        deck = make_deck()
        eq = estimate_equity(hole, community, deck, opponents=max(1, active_opponents), trials=150)
        pot_odds = to_call / (pot + to_call + 1)
        r = random.random()

        if eq >= 0.75:
            bet = min(player.chips, int(pot * random.uniform(0.6, 1.0)))
            return ('raise', bet)
        elif eq >= pot_odds + 0.05:
            if r < 0.4 and to_call < player.chips * 0.3:
                return ('raise', min(player.chips, pot // 2))
            return ('call', to_call) if to_call > 0 else ('check', 0)
        elif eq >= pot_odds - 0.05 and r < 0.35:
            return ('call', to_call) if to_call > 0 else ('check', 0)
        elif to_call == 0 and r < 0.30:  # bluff
            return ('raise', min(player.chips, pot // 3))
        elif to_call == 0:
            return ('check', 0)
        else:
            return ('fold', 0)


def strategy_position_shark(player, state):
    """
    Strategy 5 – Positional Awareness.
    Plays tighter out of position, looser in position.
    Steals blinds aggressively from late position.
    Uses pot geometry and stack-to-pot ratio (SPR).
    """
    stage = state['stage']
    to_call = state['to_call']
    pot = state['pot']
    community = state['community']
    position = state.get('position', 0.5)  # 0=early, 1=late
    active_opponents = state['active_opponents']
    hole = player.hole

    spr = player.chips / (pot + 1)

    if stage == 'preflop':
        strength = hole_strength(hole)
        # Widen range in late position
        threshold = 0.65 - position * 0.20
        if strength >= threshold:
            if position >= 0.6 and active_opponents <= 3:
                # steal / 3bet
                steal = min(player.chips, max(to_call * 3, pot))
                return ('raise', steal)
            if to_call < player.chips * 0.12:
                return ('call', to_call) if to_call > 0 else ('check', 0)
            return ('raise', min(player.chips, to_call * 2 + pot // 2))
        elif strength >= 0.45 and position >= 0.7 and to_call == 0:
            return ('raise', min(player.chips, pot // 3))
        elif to_call == 0:
            return ('check', 0)
        elif to_call < player.chips * 0.05 and strength >= 0.40:
            return ('call', to_call)
        else:
            return ('fold', 0)
    else:
        deck = make_deck()
        eq = estimate_equity(hole, community, deck, opponents=max(1, active_opponents), trials=150)
        pot_odds = to_call / (pot + to_call + 1)

        if eq >= 0.65:
            if spr < 3:
                return ('raise', player.chips)  # shove low SPR
            bet = min(player.chips, int(pot * 0.75))
            return ('raise', bet)
        elif eq >= pot_odds and position >= 0.5:
            if to_call == 0:
                bet = min(player.chips, pot // 2)
                return ('raise', bet) if random.random() < 0.5 else ('check', 0)
            return ('call', to_call)
        elif to_call == 0:
            if position >= 0.8 and random.random() < 0.4:
                return ('raise', min(player.chips, pot // 3))
            return ('check', 0)
        elif eq >= pot_odds * 0.85:
            return ('call', to_call)
        else:
            return ('fold', 0)


def strategy_adaptive_exploiter(player, state):
    """
    Strategy 6 – Adaptive Exploiter.
    Tracks recent aggression levels in the pot.
    When pot is inflated (heavy aggression detected), tightens up.
    When pot is small, plays wide and chips away.
    Uses stack preservation mode when short-stacked (<15BB).
    """
    stage = state['stage']
    to_call = state['to_call']
    pot = state['pot']
    community = state['community']
    active_opponents = state['active_opponents']
    aggression = state.get('aggression_factor', 1.0)  # >1 = aggressive table
    hole = player.hole

    big_blind = state.get('big_blind', 20)
    bb_stack = player.chips / big_blind

    # Short-stack shove-or-fold (< 15BB)
    if bb_stack < 15:
        strength = hole_strength(hole)
        if stage == 'preflop':
            if strength >= 0.60 or (strength >= 0.48 and active_opponents <= 2):
                return ('raise', player.chips)
            elif to_call == 0:
                return ('check', 0)
            else:
                return ('fold', 0)

    if stage == 'preflop':
        strength = hole_strength(hole)
        # Tighten against aggression
        threshold = 0.55 + min(0.20, (aggression - 1.0) * 0.10)
        if strength >= threshold:
            bet = min(player.chips, max(to_call * 3, pot // 2))
            return ('raise', bet)
        elif strength >= threshold - 0.15 and to_call < player.chips * 0.08:
            return ('call', to_call) if to_call > 0 else ('check', 0)
        elif to_call == 0:
            return ('check', 0)
        else:
            return ('fold', 0)
    else:
        deck = make_deck()
        eq = estimate_equity(hole, community, deck, opponents=max(1, active_opponents), trials=150)
        pot_odds = to_call / (pot + to_call + 1)

        # In passive pots, bet wider; in aggressive pots, value-bet only
        bluff_threshold = 0.28 if aggression < 1.2 else 0.10

        if eq >= 0.65:
            sizing = 0.6 if aggression >= 1.5 else 0.85
            return ('raise', min(player.chips, int(pot * sizing)))
        elif eq >= pot_odds + 0.08:
            return ('call', to_call) if to_call > 0 else ('check', 0)
        elif to_call == 0 and random.random() < bluff_threshold:
            return ('raise', min(player.chips, pot // 3))
        elif to_call == 0:
            return ('check', 0)
        elif eq >= pot_odds * 0.75:
            return ('call', to_call)
        else:
            return ('fold', 0)


STRATEGIES = [
    strategy_all_in_savage,       # Player 1
    strategy_tight_aggressive,    # Player 2
    strategy_loose_passive,       # Player 3
    strategy_gto_approximator,    # Player 4
    strategy_position_shark,      # Player 5
    strategy_adaptive_exploiter,  # Player 6
]

STRATEGY_NAMES = [
    "The All-In Savage",
    "Tight-Aggressive TAG",
    "Loose-Passive Calling Station",
    "GTO Approximator",
    "Position Shark",
    "Adaptive Exploiter",
]

# ──────────────────────────────────────────────
# GAME ENGINE
# ──────────────────────────────────────────────

SMALL_BLIND = 10
BIG_BLIND = 20
STARTING_CHIPS = 1000

def run_hand(players, dealer_idx):
    """Run one hand of Hold'em. Returns updated players."""
    active = [p for p in players if p.chips > 0]
    if len(active) < 2:
        return players

    # Reset
    for p in players:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    # Post blinds
    order = [p for p in players if p.chips > 0]
    n = len(order)
    if n < 2:
        return players

    sb_idx = dealer_idx % n
    bb_idx = (dealer_idx + 1) % n

    pot = 0
    pot += order[sb_idx].place_bet(SMALL_BLIND)
    pot += order[bb_idx].place_bet(BIG_BLIND)

    # Deal hole cards
    for p in order:
        p.hole = [deck.pop(), deck.pop()]

    community = []

    def betting_round(stage, first_to_act_idx):
        nonlocal pot
        aggression_count = 0
        total_actions = 0

        current_max_bet = max(p.bet_this_round for p in order)

        acted = set()
        acting_order = [(first_to_act_idx + i) % n for i in range(n)]
        queue = list(acting_order)

        while queue:
            idx = queue.pop(0)
            p = order[idx]
            if p.folded or p.all_in or p.chips == 0:
                continue
            if idx in acted and p.bet_this_round >= current_max_bet:
                continue

            to_call = max(0, current_max_bet - p.bet_this_round)
            active_opponents = sum(
                1 for op in order
                if not op.folded and not op.all_in and op.pid != p.pid
            )

            position_val = idx / max(1, n - 1)

            # aggression factor: ratio of raise actions to total
            agg_factor = 1.0 + (aggression_count / max(1, total_actions))

            state = {
                'stage': stage,
                'to_call': to_call,
                'pot': pot,
                'community': community,
                'active_opponents': active_opponents,
                'position': position_val,
                'aggression_factor': agg_factor,
                'big_blind': BIG_BLIND,
            }

            action, amount = p.strategy_fn(p, state)
            total_actions += 1

            if action == 'fold':
                p.folded = True
                acted.add(idx)
            elif action == 'check':
                acted.add(idx)
            elif action == 'call':
                amt = p.place_bet(to_call)
                pot += amt
                acted.add(idx)
            elif action == 'raise':
                amt = p.place_bet(to_call + amount)
                pot += amt
                if amt > to_call:
                    aggression_count += 1
                    new_max = p.bet_this_round
                    if new_max > current_max_bet:
                        current_max_bet = new_max
                        # re-open action for others
                        for j in acting_order:
                            if j != idx and not order[j].folded and not order[j].all_in:
                                if order[j].bet_this_round < current_max_bet:
                                    if j not in queue:
                                        queue.append(j)
                acted.add(idx)

            # Check if only one player remains
            still_in = [p for p in order if not p.folded]
            if len(still_in) == 1:
                return True  # hand over early

        return False

    # Reset bets for each street
    def reset_bets():
        for p in order:
            p.bet_this_round = 0

    # ── Pre-flop ──
    first_act = (dealer_idx + 2) % n  # UTG
    done = betting_round('preflop', first_act)
    if not done:
        reset_bets()
        # ── Flop ──
        community += [deck.pop(), deck.pop(), deck.pop()]
        done = betting_round('flop', dealer_idx % n)
    if not done:
        reset_bets()
        # ── Turn ──
        community.append(deck.pop())
        done = betting_round('turn', dealer_idx % n)
    if not done:
        reset_bets()
        # ── River ──
        community.append(deck.pop())
        betting_round('river', dealer_idx % n)

    # ── Showdown ──
    contenders = [p for p in order if not p.folded]
    if len(contenders) == 1:
        contenders[0].chips += pot
    else:
        scores = [(hand_rank(p.hole + community), p) for p in contenders]
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score = scores[0][0]
        winners = [p for s, p in scores if s == best_score]
        share = pot // len(winners)
        for w in winners:
            w.chips += share
        # remainder to first winner
        remainder = pot - share * len(winners)
        if remainder and winners:
            winners[0].chips += remainder

    return players


def run_tournament(num_players=6, starting_chips=STARTING_CHIPS):
    """Run a full tournament until one player remains. Returns winner pid."""
    players = [
        Player(i + 1, starting_chips, STRATEGIES[i])
        for i in range(num_players)
    ]

    dealer_idx = 0
    hand_count = 0
    max_hands = 2000  # safety cap

    while True:
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid
        if len(alive) == 0:
            return -1
        if hand_count >= max_hands:
            # declare chip leader winner
            return max(alive, key=lambda p: p.chips).pid

        run_hand(players, dealer_idx)
        dealer_idx = (dealer_idx + 1) % len([p for p in players if p.chips > 0])
        hand_count += 1


# ──────────────────────────────────────────────
# SIMULATION + HISTOGRAM
# ──────────────────────────────────────────────

def run_simulations(n=100):
    print("=" * 60)
    print("  TEXAS HOLD'EM POKER SIMULATION  –  100 TOURNAMENTS")
    print("=" * 60)
    print()
    print("Players:")
    for i, name in enumerate(STRATEGY_NAMES, 1):
        tag = " ← THE ALL-IN SAVAGE" if i == 1 else ""
        print(f"  Player {i}: {name}{tag}")
    print()
    print(f"Starting chips: {STARTING_CHIPS} each")
    print(f"Blinds: {SMALL_BLIND}/{BIG_BLIND}")
    print()
    print("Running 100 tournaments...", end='', flush=True)

    wins = Counter()
    for t in range(n):
        winner = run_tournament()
        wins[winner] += 1
        if (t + 1) % 10 == 0:
            print(f" {t+1}", end='', flush=True)

    print()
    print()
    print("=" * 60)
    print("  RESULTS – WINNER WINNER CHICKEN DINNER")
    print("=" * 60)
    print()

    # Sort by player id for clean display
    max_wins = max(wins.values()) if wins else 1
    bar_width = 40

    rows = []
    for pid in range(1, 7):
        w = wins.get(pid, 0)
        name = STRATEGY_NAMES[pid - 1]
        tag = " 🔥" if pid == 1 else ""
        rows.append((pid, name + tag, w))

    # Header
    print(f"  {'Player':<6} {'Strategy':<35} {'Wins':>4}  Histogram")
    print(f"  {'-'*6} {'-'*35} {'-'*4}  {'-'*bar_width}")

    for pid, name, w in rows:
        bar = '█' * int(w / max_wins * bar_width)
        pct = w / n * 100
        marker = " ← ALL-IN CHAD" if pid == 1 else ""
        print(f"  P{pid:<5} {name:<35} {w:>4}  {bar:<{bar_width}} {pct:5.1f}%{marker}")

    print()
    print("─" * 60)
    winner_pid = max(wins, key=wins.get)
    print(f"  MOST TOURNAMENTS WON: Player {winner_pid} – {STRATEGY_NAMES[winner_pid-1]}")
    print(f"  ({wins[winner_pid]} out of {n} tournaments = {wins[winner_pid]/n*100:.1f}%)")
    print("─" * 60)
    print()

    if winner_pid == 1:
        print("  GPT HUMILIATED: The All-In Savage DOMINATED the table.")
        print("  Brains? Overrated. Stack shoved? Undefeated.")
    else:
        diff = wins[winner_pid] - wins.get(1, 0)
        print(f"  The All-In Savage: {wins.get(1,0)} wins ({wins.get(1,0)/n*100:.1f}%)")
        print(f"  The elaborate strategists combined for {n - wins.get(1,0)} wins.")
        print(f"  BUT: variance is poker's great equalizer. Run it again.")
    print()

    return wins


if __name__ == '__main__':
    random.seed(42)
    run_simulations(100)
