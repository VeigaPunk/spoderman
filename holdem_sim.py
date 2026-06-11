#!/usr/bin/env python3
"""Texas Hold'em 6-player simulation: 1 degen vs 5 strategists. 100 rounds."""

import random
from collections import Counter
from itertools import combinations

# ──────────────────────────────────────────────
# Card primitives
# ──────────────────────────────────────────────
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}


def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


def card_str(c):
    return c[0] + c[1]


# ──────────────────────────────────────────────
# Hand evaluation (returns comparable tuple)
# ──────────────────────────────────────────────
def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards. Higher tuple = better."""
    best = None
    for combo in combinations(cards, 5):
        s = score5(combo)
        if best is None or s > best:
            best = s
    return best


def score5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5) or \
               (ranks == [14, 5, 4, 3, 2])  # wheel
    if straight and ranks[0] == 5:
        ranks = [5, 4, 3, 2, 1]
    counts = sorted(Counter(ranks).values(), reverse=True)
    rank_groups = sorted(Counter(ranks).keys(),
                         key=lambda r: (Counter(ranks)[r], r), reverse=True)
    if flush and straight:
        return (8, ranks)
    if counts == [4, 1]:
        return (7, rank_groups)
    if counts == [3, 2]:
        return (6, rank_groups)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts[0] == 3:
        return (3, rank_groups)
    if counts[:2] == [2, 2]:
        return (2, rank_groups)
    if counts[0] == 2:
        return (1, rank_groups)
    return (0, ranks)


# ──────────────────────────────────────────────
# Monte-Carlo equity estimator (fast, sampled)
# ──────────────────────────────────────────────
def estimate_equity(hole, community, num_opponents, samples=200):
    """Fraction of sampled runouts where we win (vs random opponent hands)."""
    deck_remaining = [c for c in make_deck()
                      if c not in hole and c not in community]
    wins = 0
    for _ in range(samples):
        d = deck_remaining[:]
        random.shuffle(d)
        board = community[:]
        ptr = 0
        # deal missing community cards
        while len(board) < 5:
            board.append(d[ptr]); ptr += 1
        # deal opponent hole cards
        opp_cards = [d[ptr + i] for i in range(num_opponents * 2)]
        my_score = hand_rank(hole + board)
        best_opp = max(
            hand_rank([opp_cards[i*2], opp_cards[i*2+1]] + board)
            for i in range(num_opponents)
        )
        if my_score > best_opp:
            wins += 1
    return wins / samples


def hand_strength_fast(hole, community):
    """Cheap static strength: high-card / pair / two-pair etc. 0-1 scale."""
    ranks = [RANK_VAL[c[0]] for c in hole]
    suited = hole[0][1] == hole[1][1]
    paired = ranks[0] == ranks[1]
    hi = max(ranks)
    lo = min(ranks)
    score = hi / 14.0
    if paired: score += 0.2 + hi / 70.0
    if suited: score += 0.06
    if abs(ranks[0] - ranks[1]) == 1: score += 0.04  # connector
    if community:
        hand = hand_rank(hole + community)
        score = max(score, hand[0] / 8.0 + 0.05)
    return min(score, 1.0)


# ──────────────────────────────────────────────
# Strategy definitions
# Each returns an action: ('fold'|'call'|'raise', amount)
# Context dict keys: hole, community, pot, to_call, chips,
#                    min_raise, num_active, street, position
# ──────────────────────────────────────────────

# --- Strategy 0: The Maniac (always all-in) ---
def strategy_maniac(ctx):
    return ('raise', ctx['chips'])


# --- Strategy 1: Tight-Aggressive (TAG) ---
def strategy_tag(ctx):
    hole, community = ctx['hole'], ctx['community']
    pot, to_call = ctx['pot'], ctx['to_call']
    chips, min_raise = ctx['chips'], ctx['min_raise']
    street, num_active = ctx['street'], ctx['num_active']

    strength = hand_strength_fast(hole, community)

    if street == 'preflop':
        ranks = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
        paired = ranks[0] == ranks[1]
        hi = ranks[0]
        # Only play premium hands
        if paired and hi >= 10:
            return ('raise', min(min_raise * 3, chips))
        if hi >= 12 and ranks[1] >= 10:
            return ('raise', min(min_raise * 3, chips))
        if hi >= 11 and hole[0][1] == hole[1][1]:
            return ('raise', min(min_raise * 2, chips))
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)
    else:
        if strength > 0.75:
            bet = min(int(pot * 0.75), chips)
            return ('raise', max(bet, min_raise))
        if strength > 0.5:
            return ('call', to_call) if to_call < chips * 0.3 else ('fold', 0)
        return ('fold', 0) if to_call > 0 else ('call', 0)


# --- Strategy 2: Loose-Aggressive (LAG) ---
def strategy_lag(ctx):
    hole, community = ctx['hole'], ctx['community']
    pot, to_call = ctx['pot'], ctx['to_call']
    chips, min_raise = ctx['chips'], ctx['min_raise']
    street, position = ctx['street'], ctx['position']
    num_active = ctx['num_active']

    strength = hand_strength_fast(hole, community)
    # LAG plays wide and bluffs in position
    late_position = position >= num_active - 2

    if street == 'preflop':
        if strength > 0.55 or late_position:
            if strength > 0.7:
                return ('raise', min(min_raise * 4, chips))
            return ('call', to_call) if to_call < chips * 0.1 else ('raise', min(min_raise * 2, chips))
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)
    else:
        # Bluff ~25% of the time in position with weak hands
        bluff = late_position and random.random() < 0.25
        if strength > 0.65 or bluff:
            bet = min(int(pot * 0.6), chips)
            return ('raise', max(bet, min_raise))
        if strength > 0.45 and to_call < chips * 0.2:
            return ('call', to_call)
        return ('fold', 0) if to_call > 0 else ('call', 0)


# --- Strategy 3: Monte-Carlo Equity Player ---
def strategy_mc(ctx):
    hole, community = ctx['hole'], ctx['community']
    pot, to_call = ctx['pot'], ctx['to_call']
    chips, min_raise = ctx['chips'], ctx['min_raise']
    num_active = ctx['num_active']

    if len(community) < 3:
        # Preflop: use fast heuristic
        equity = hand_strength_fast(hole, community)
    else:
        equity = estimate_equity(hole, community, num_active - 1, samples=150)

    pot_odds = to_call / (pot + to_call + 1e-9)

    if equity > 0.70:
        bet = min(int(pot * equity), chips)
        return ('raise', max(bet, min_raise))
    if equity > pot_odds + 0.05:
        return ('call', to_call)
    return ('fold', 0) if to_call > 0 else ('call', 0)


# --- Strategy 4: GTO-Inspired Mixed Frequency ---
def strategy_gto(ctx):
    hole, community = ctx['hole'], ctx['community']
    pot, to_call = ctx['pot'], ctx['to_call']
    chips, min_raise = ctx['chips'], ctx['min_raise']
    street, position = ctx['street'], ctx['position']
    num_active = ctx['num_active']

    strength = hand_strength_fast(hole, community)
    # GTO mixes bet sizes and frequencies
    r = random.random()

    if strength > 0.80:
        # Value bet, sometimes overbet for balance
        size = 0.75 if r < 0.6 else 1.25
        bet = min(int(pot * size), chips)
        return ('raise', max(bet, min_raise))
    if strength > 0.60:
        if r < 0.7:
            bet = min(int(pot * 0.5), chips)
            return ('raise', max(bet, min_raise))
        return ('call', to_call)
    if strength > 0.40:
        # Balanced: sometimes bluff, sometimes check/call
        if r < 0.3 and to_call < chips * 0.15:
            return ('call', to_call)
        if r < 0.15:  # bluff raise
            bet = min(int(pot * 0.5), chips)
            return ('raise', max(bet, min_raise))
        return ('fold', 0) if to_call > 0 else ('call', 0)
    # Weak: fold to bets, occasionally bluff
    if to_call == 0 and r < 0.10:
        bet = min(int(pot * 0.4), chips)
        return ('raise', max(bet, min_raise))
    return ('fold', 0) if to_call > 0 else ('call', 0)


# --- Strategy 5: ICM / Stack-Size Aware ---
def strategy_icm(ctx):
    hole, community = ctx['hole'], ctx['community']
    pot, to_call = ctx['pot'], ctx['to_call']
    chips, min_raise = ctx['chips'], ctx['min_raise']
    num_active = ctx['num_active']
    total_chips = ctx.get('total_chips', chips * num_active)

    strength = hand_strength_fast(hole, community)
    stack_ratio = chips / total_chips  # how big is our stack?

    # Big stack: apply pressure
    if stack_ratio > 0.3:
        if strength > 0.55:
            bet = min(int(pot * 0.65), chips)
            return ('raise', max(bet, min_raise))
        if to_call < chips * 0.05:
            return ('call', to_call)
        return ('fold', 0)
    # Short stack: push or fold
    if chips < pot * 2:
        return ('raise', chips) if strength > 0.45 else ('fold', 0)
    # Medium stack: conservative
    if strength > 0.65:
        bet = min(int(pot * 0.5), chips)
        return ('raise', max(bet, min_raise))
    if strength > 0.5 and to_call < chips * 0.1:
        return ('call', to_call)
    return ('fold', 0) if to_call > 0 else ('call', 0)


STRATEGIES = [
    strategy_maniac,   # Player 1 (the degen)
    strategy_tag,      # Player 2
    strategy_lag,      # Player 3
    strategy_mc,       # Player 4
    strategy_gto,      # Player 5
    strategy_icm,      # Player 6
]

STRATEGY_NAMES = [
    "P1-Maniac(AllIn)",
    "P2-TAG",
    "P3-LAG",
    "P4-MonteCarlo",
    "P5-GTO",
    "P6-ICM",
]

# ──────────────────────────────────────────────
# Game engine
# ──────────────────────────────────────────────
SMALL_BLIND = 10
BIG_BLIND = 20
STARTING_CHIPS = 1000


class Player:
    def __init__(self, pid, chips, strategy):
        self.pid = pid
        self.chips = chips
        self.strategy = strategy
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0


def run_betting_round(players, community, pot, street, total_chips, dealer_idx):
    """Single betting street. Returns updated pot."""
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) <= 1:
        return pot

    # Reset round bets
    for p in players:
        p.bet_this_round = 0

    current_bet = 0
    # preflop blinds already handled; street ordering handled by caller

    num_to_act = len(active)
    acted = 0
    idx = 0
    last_raiser = None

    while True:
        p = active[idx % len(active)]
        if p.folded or p.all_in:
            idx += 1
            continue

        to_call = current_bet - p.bet_this_round
        min_raise = max(BIG_BLIND, current_bet * 2 - p.bet_this_round)
        num_active = sum(1 for x in players if not x.folded)

        ctx = {
            'hole': p.hole,
            'community': community,
            'pot': pot,
            'to_call': to_call,
            'chips': p.chips,
            'min_raise': min_raise,
            'street': street,
            'position': idx % len(active),
            'num_active': num_active,
            'total_chips': total_chips,
        }

        action, amount = p.strategy(ctx)

        if action == 'fold':
            p.folded = True
        elif action == 'call':
            actual = min(to_call, p.chips)
            p.chips -= actual
            p.bet_this_round += actual
            pot += actual
            if p.chips == 0:
                p.all_in = True
        elif action == 'raise':
            total_put_in = min(amount + to_call, p.chips) if to_call > 0 else min(amount, p.chips)
            # raise means: match current bet then add raise on top
            actual = min(to_call + amount, p.chips)
            p.chips -= actual
            p.bet_this_round += actual
            pot += actual
            if p.bet_this_round > current_bet:
                current_bet = p.bet_this_round
                last_raiser = p.pid
                # reset acted count so others can respond
                acted = 0
            if p.chips == 0:
                p.all_in = True

        acted += 1
        idx += 1

        # Check if round is over
        remaining = [x for x in active if not x.folded and not x.all_in]
        if not remaining:
            break
        all_matched = all(
            x.bet_this_round >= current_bet or x.folded or x.all_in
            for x in active
        )
        if all_matched and acted >= len(remaining):
            break
        if len([x for x in active if not x.folded]) <= 1:
            break

    return pot


def showdown(players, community, pot):
    """Award pot to best hand(s). Returns winner pid."""
    contenders = [p for p in players if not p.folded]
    if not contenders:
        return None
    if len(contenders) == 1:
        contenders[0].chips += pot
        return contenders[0].pid
    scores = [(hand_rank(p.hole + community), p) for p in contenders]
    best_score = max(s for s, _ in scores)
    winners = [p for s, p in scores if s == best_score]
    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += remainder  # odd chip to first winner
    return winners[0].pid


def play_hand(players, dealer_idx, total_chips):
    """Play one complete hand. Returns (winner_pid or None if no elimination)."""
    for p in players:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    active_players = [p for p in players if p.chips > 0]
    if len(active_players) < 2:
        return None

    n = len(active_players)
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    # Post blinds
    pot = 0
    sb = active_players[sb_idx]
    bb = active_players[bb_idx]

    sb_bet = min(SMALL_BLIND, sb.chips)
    sb.chips -= sb_bet
    sb.bet_this_round = sb_bet
    pot += sb_bet
    if sb.chips == 0:
        sb.all_in = True

    bb_bet = min(BIG_BLIND, bb.chips)
    bb.chips -= bb_bet
    bb.bet_this_round = bb_bet
    pot += bb_bet
    if bb.chips == 0:
        bb.all_in = True

    # Deal hole cards
    ptr = 0
    for p in active_players:
        p.hole = [deck[ptr], deck[ptr+1]]
        ptr += 2

    community = []
    current_bet = BIG_BLIND

    # Preflop betting (UTG acts first)
    # Reorder so UTG (dealer+3) acts first
    preflop_order = active_players[(bb_idx+1) % n:] + active_players[:(bb_idx+1) % n]

    # Run preflop with existing bets
    # We'll do a simplified version: reset round bets but keep existing
    pot = run_betting_round(active_players, community, pot, 'preflop', total_chips, dealer_idx)

    # Check if hand is over
    still_in = [p for p in active_players if not p.folded]
    if len(still_in) <= 1:
        return showdown(active_players, community, pot)

    # Flop
    community = [deck[ptr], deck[ptr+1], deck[ptr+2]]
    ptr += 3
    for p in active_players:
        p.bet_this_round = 0
    pot = run_betting_round(active_players, community, pot, 'flop', total_chips, dealer_idx)

    still_in = [p for p in active_players if not p.folded]
    if len(still_in) <= 1:
        return showdown(active_players, community, pot)

    # Turn
    community.append(deck[ptr]); ptr += 1
    for p in active_players:
        p.bet_this_round = 0
    pot = run_betting_round(active_players, community, pot, 'turn', total_chips, dealer_idx)

    still_in = [p for p in active_players if not p.folded]
    if len(still_in) <= 1:
        return showdown(active_players, community, pot)

    # River
    community.append(deck[ptr]); ptr += 1
    for p in active_players:
        p.bet_this_round = 0
    pot = run_betting_round(active_players, community, pot, 'river', total_chips, dealer_idx)

    return showdown(active_players, community, pot)


def play_tournament(starting_chips=STARTING_CHIPS, max_hands=500):
    """Play until one player has all chips. Returns winner index (0-based)."""
    players = [
        Player(i, starting_chips, STRATEGIES[i])
        for i in range(6)
    ]
    total_chips = starting_chips * 6
    dealer_idx = 0

    for hand_num in range(max_hands):
        active = [p for p in players if p.chips > 0]
        if len(active) <= 1:
            break
        play_hand(active, dealer_idx % len(active), total_chips)
        dealer_idx += 1

    # Winner = player with most chips
    winner = max(players, key=lambda p: p.chips)
    return winner.pid


# ──────────────────────────────────────────────
# Run 100 tournaments
# ──────────────────────────────────────────────
def run_simulations(n=100):
    win_counts = Counter()
    for i in range(n):
        if (i + 1) % 10 == 0:
            print(f"  Running sim {i+1}/{n}...", flush=True)
        winner = play_tournament()
        win_counts[winner] += 1
    return win_counts


def print_histogram(win_counts, n_sims):
    print("\n" + "="*60)
    print("  TEXAS HOLD'EM — 100-TOURNAMENT RESULTS")
    print("  'Winner Winner Chicken Dinner' Histogram")
    print("="*60)
    bar_max = 40
    max_wins = max(win_counts.values()) if win_counts else 1
    for pid in range(6):
        name = STRATEGY_NAMES[pid]
        wins = win_counts.get(pid, 0)
        pct = wins / n_sims * 100
        bar_len = int(wins / max_wins * bar_max)
        bar = "█" * bar_len
        marker = " ← THE DEGEN" if pid == 0 else ""
        print(f"  {name:<22} │ {bar:<40} {wins:3d} ({pct:5.1f}%){marker}")
    print("="*60)
    champion_pid = max(win_counts, key=win_counts.get)
    print(f"\n  Champion: {STRATEGY_NAMES[champion_pid]} with {win_counts[champion_pid]} wins")
    if champion_pid == 0:
        print("  The Maniac carried. ChatGPT would've folded AK preflop.")
    else:
        print(f"  Strategy depth won the day. GPT cries in transformer weights.")
    print()


if __name__ == '__main__':
    print("Shuffling decks, humiliating ChatGPT...")
    random.seed(42)
    N = 100
    results = run_simulations(N)
    print_histogram(results, N)
