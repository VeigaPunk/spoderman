"""
Texas Hold'em Poker Tournament Simulation
- Player 1: The Degenerate (always goes all-in)
- Players 2-6: Five elaborate strategy bots
- 100 tournaments, histogram of last-man-standing winners
"""

import random
import sys
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

RANKS = list(range(2, 15))  # 2-14 (14=Ace)
SUITS = ['s', 'h', 'd', 'c']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(card):
    return f"{RANK_NAMES[card[0]]}{card[1]}"

# ---------------------------------------------------------------------------
# Hand evaluator — returns (category, tiebreaker_tuple)  higher = better
# categories: 8=SF, 7=Quads, 6=FullHouse, 5=Flush, 4=Straight,
#             3=Trips, 2=TwoPair, 1=Pair, 0=High
# ---------------------------------------------------------------------------

def best_hand(cards):
    """Evaluate best 5-card hand from 5-7 cards."""
    best = None
    for combo in combinations(cards, 5):
        val = eval5(combo)
        if best is None or val > best:
            best = val
    return best

def eval5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    # Check straight (including wheel A-2-3-4-5)
    straight = False
    straight_high = 0
    if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
        straight = True
        straight_high = ranks[0]
    if set(ranks) == {14, 2, 3, 4, 5}:
        straight = True
        straight_high = 5  # wheel
    counts = sorted(Counter(ranks).items(), key=lambda x: (x[1], x[0]), reverse=True)
    grouped = [r for r, _ in counts]
    freq    = [f for _, f in counts]
    if flush and straight:
        return (8, straight_high)
    if freq[0] == 4:
        return (7, grouped[0], grouped[1])
    if freq[0] == 3 and freq[1] == 2:
        return (6, grouped[0], grouped[1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight_high)
    if freq[0] == 3:
        return (3, grouped[0], *sorted(grouped[1:], reverse=True))
    if freq[0] == 2 and freq[1] == 2:
        pair1, pair2 = sorted([grouped[0], grouped[1]], reverse=True)
        return (2, pair1, pair2, grouped[2])
    if freq[0] == 2:
        return (1, grouped[0], *grouped[1:])
    return (0, *ranks)

# ---------------------------------------------------------------------------
# Hand strength estimator (Monte Carlo, cheap)
# ---------------------------------------------------------------------------

def estimate_strength(hole, community, n_opponents, iterations=200):
    """Win-rate estimate via Monte Carlo sampling."""
    deck = make_deck()
    known = set(map(tuple, hole + community))
    deck = [c for c in deck if tuple(c) not in known]
    wins = 0
    for _ in range(iterations):
        sample = deck[:]
        random.shuffle(sample)
        idx = 0
        board = list(community)
        while len(board) < 5:
            board.append(sample[idx]); idx += 1
        my_best = best_hand(hole + board)
        beat = True
        for _ in range(n_opponents):
            opp = [sample[idx], sample[idx+1]]; idx += 2
            if best_hand(opp + board) > my_best:
                beat = False; break
        if beat:
            wins += 1
    return wins / iterations

# ---------------------------------------------------------------------------
# Street constants
# ---------------------------------------------------------------------------
PRE_FLOP, FLOP, TURN, RIVER = 0, 1, 2, 3

# ---------------------------------------------------------------------------
# Strategy 1 — The Degenerate (always all-in)
# ---------------------------------------------------------------------------

def strategy_degenerate(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    """If my turn then bet = ALL IN."""
    return ('allin', my_chips)

# ---------------------------------------------------------------------------
# Strategy 2 — The Mathematician (pot-odds + hand strength)
# ---------------------------------------------------------------------------

def strategy_mathematician(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    strength = estimate_strength(hole, community, n_active - 1, iterations=150)
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
    if strength < pot_odds * 0.85:
        return ('fold', 0)
    if strength > 0.80:
        bet = min(my_chips, max(min_raise, int(pot * 0.75)))
        return ('raise', bet)
    if to_call == 0:
        return ('check', 0)
    return ('call', min(to_call, my_chips))

# ---------------------------------------------------------------------------
# Strategy 3 — The Tight-Aggressive (TAG)
# Only plays premium pre-flop; fires big on strength post-flop
# ---------------------------------------------------------------------------

PREMIUM_HANDS = {(14,14),(13,13),(12,12),(11,11),(10,10),(14,13),(14,12),(14,11)}

def strategy_tag(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    is_premium = (r1, r2) in PREMIUM_HANDS or (suited and r1 >= 10) or (r1 == r2 and r1 >= 8)
    if street == PRE_FLOP:
        if not is_premium:
            return ('fold', 0) if to_call > 0 else ('check', 0)
        bet = min(my_chips, max(min_raise * 3, int(pot * 1.0)))
        return ('raise', bet) if bet >= min_raise else ('call', min(to_call, my_chips))
    strength = estimate_strength(hole, community, n_active - 1, iterations=120)
    if strength > 0.70:
        bet = min(my_chips, max(min_raise, int(pot * 0.85)))
        return ('raise', bet)
    if strength > 0.45:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    return ('fold', 0) if to_call > 0 else ('check', 0)

# ---------------------------------------------------------------------------
# Strategy 4 — The Bluffer (GTO-lite with random bluffs)
# ---------------------------------------------------------------------------

def strategy_bluffer(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    strength = estimate_strength(hole, community, n_active - 1, iterations=120)
    bluff_freq = 0.25 if street >= TURN else 0.15
    bluffing = random.random() < bluff_freq
    if bluffing:
        bet = min(my_chips, max(min_raise, int(pot * 0.60)))
        return ('raise', bet)
    if strength > 0.75:
        bet = min(my_chips, max(min_raise, int(pot * 0.90)))
        return ('raise', bet)
    if strength > 0.50:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    if to_call == 0:
        return ('check', 0)
    if to_call <= pot * 0.20:
        return ('call', min(to_call, my_chips))
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 5 — The Positional Shark (positional awareness)
# ---------------------------------------------------------------------------

def strategy_positional(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    """Late position = looser; early = tighter."""
    late = position >= n_active * 0.6  # last ~40% of seats
    strength = estimate_strength(hole, community, n_active - 1, iterations=120)
    threshold_call = 0.35 if late else 0.50
    threshold_raise = 0.65 if late else 0.75
    if strength > threshold_raise:
        size = 1.0 if late else 0.6
        bet = min(my_chips, max(min_raise, int(pot * size)))
        return ('raise', bet)
    if strength > threshold_call:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    if to_call == 0:
        if late and random.random() < 0.18:
            return ('raise', min(my_chips, max(min_raise, int(pot * 0.40))))
        return ('check', 0)
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 6 — The Stack Bully (shoves when big stack, folds trash when short)
# ---------------------------------------------------------------------------

def strategy_stack_bully(hole, community, pot, my_chips, to_call, min_raise, street, position, n_active, history):
    avg_stack = history.get('avg_stack', my_chips)
    big_stack = my_chips >= avg_stack * 1.4
    short_stack = my_chips <= avg_stack * 0.5
    strength = estimate_strength(hole, community, n_active - 1, iterations=120)
    if big_stack and strength > 0.45:
        bet = min(my_chips, max(min_raise, int(pot * 1.10)))
        return ('raise', bet)
    if short_stack:
        if strength > 0.65:
            return ('allin', my_chips)
        return ('fold', 0) if to_call > 0 else ('check', 0)
    if strength > 0.70:
        bet = min(my_chips, max(min_raise, int(pot * 0.75)))
        return ('raise', bet)
    if strength > 0.45:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    return ('fold', 0) if to_call > 0 else ('check', 0)

# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

STRATEGIES = [
    ("The Degenerate",   strategy_degenerate),    # Player 1
    ("The Mathematician",strategy_mathematician),  # Player 2
    ("The TAG",          strategy_tag),            # Player 3
    ("The Bluffer",      strategy_bluffer),        # Player 4
    ("The Positional",   strategy_positional),     # Player 5
    ("The Stack Bully",  strategy_stack_bully),    # Player 6
]

# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20
MAX_ROUNDS     = 200   # safety limit per tournament

class Player:
    def __init__(self, pid, name, strategy):
        self.pid      = pid
        self.name     = name
        self.strategy = strategy
        self.chips    = STARTING_CHIPS
        self.active   = True   # still in tournament
        self.folded   = False  # folded this hand
        self.bet      = 0      # chips bet this street
        self.hole     = []

    def reset_hand(self):
        self.folded = False
        self.bet    = 0
        self.hole   = []

    def is_in(self):
        return self.active and not self.folded and self.chips > 0

def run_betting_round(players, community, pot, street, dealer_idx):
    """Run one street of betting. Returns updated pot."""
    active = [p for p in players if p.active and not p.folded]
    if len(active) <= 1:
        return pot

    # Reset street bets
    for p in active:
        p.bet = 0

    current_bet = 0
    min_raise   = BIG_BLIND

    # Determine action order (left of dealer for post-flop; after BB pre-flop handled outside)
    n = len(players)
    start = (dealer_idx + 1) % n
    order = []
    i = start
    for _ in range(n):
        if players[i].active and not players[i].folded:
            order.append(players[i])
        i = (i + 1) % n

    n_active_total = len(active)
    avg_stack = sum(p.chips for p in active) / max(1, n_active_total)

    acted = set()
    q = list(order)
    iterations = 0
    while q and iterations < n_active_total * 4:
        iterations += 1
        player = q.pop(0)
        if not player.active or player.folded or player.chips == 0:
            acted.add(player.pid)
            continue
        to_call = max(0, current_bet - player.bet)
        # If already covered and no one raised
        if player.pid in acted and to_call == 0:
            continue

        history = {'avg_stack': avg_stack}
        position = order.index(player) if player in order else 0
        n_opp = sum(1 for p in active if p.pid != player.pid)

        action, amount = player.strategy(
            player.hole, community, pot, player.chips,
            to_call, min_raise, street, position, n_opp + 1, history
        )

        if action == 'fold':
            player.folded = True
            acted.add(player.pid)
        elif action in ('call',):
            amount = min(to_call, player.chips)
            player.chips -= amount
            player.bet   += amount
            pot          += amount
            acted.add(player.pid)
        elif action == 'check':
            acted.add(player.pid)
        elif action in ('raise', 'allin'):
            if action == 'allin':
                amount = player.chips
            amount = max(min_raise, min(amount, player.chips))
            # at least a min-raise above current
            actual_raise = max(amount, to_call + min_raise)
            actual_raise = min(actual_raise, player.chips)
            min_raise = max(min_raise, actual_raise - to_call)
            player.chips -= actual_raise
            pot          += actual_raise
            player.bet   += actual_raise
            current_bet   = player.bet
            acted.add(player.pid)
            # Re-open action for others who haven't matched
            for other in order:
                if other.pid != player.pid and not other.folded and other.active:
                    if other.bet < current_bet and other.pid in acted:
                        q.append(other)
                        acted.discard(other.pid)
        else:
            acted.add(player.pid)

        still_in = [p for p in active if not p.folded and p.chips >= 0]
        if len(still_in) <= 1:
            break

    return pot

def run_hand(players, dealer_idx):
    """Play a single hand. Returns dealer_idx (rotated)."""
    n = len(players)
    alive = [p for p in players if p.active]
    if len(alive) < 2:
        return dealer_idx

    for p in players:
        p.reset_hand()

    # Deal
    deck = make_deck()
    random.shuffle(deck)
    idx = 0
    for p in alive:
        p.hole = [deck[idx], deck[idx+1]]
        idx += 2

    community = []
    pot = 0

    # Blinds
    alive_list = [p for p in players if p.active]
    n_alive = len(alive_list)

    sb_idx = (dealer_idx + 1) % n
    while not players[sb_idx % n].active:
        sb_idx += 1
    bb_idx = sb_idx + 1
    while not players[bb_idx % n].active:
        bb_idx += 1

    sb_player = players[sb_idx % n]
    bb_player = players[bb_idx % n]

    sb_amount = min(SMALL_BLIND, sb_player.chips)
    bb_amount = min(BIG_BLIND,   bb_player.chips)

    sb_player.chips -= sb_amount; sb_player.bet = sb_amount; pot += sb_amount
    bb_player.chips -= bb_amount; bb_player.bet = bb_amount; pot += bb_amount

    # Pre-flop
    pot = run_betting_round(players, community, pot, PRE_FLOP, bb_idx % n)

    still_in = [p for p in players if p.active and not p.folded]

    if len(still_in) > 1:
        community += [deck[idx], deck[idx+1], deck[idx+2]]; idx += 3
        pot = run_betting_round(players, community, pot, FLOP, dealer_idx)
        still_in = [p for p in players if p.active and not p.folded]

    if len(still_in) > 1:
        community.append(deck[idx]); idx += 1
        pot = run_betting_round(players, community, pot, TURN, dealer_idx)
        still_in = [p for p in players if p.active and not p.folded]

    if len(still_in) > 1:
        community.append(deck[idx]); idx += 1
        pot = run_betting_round(players, community, pot, RIVER, dealer_idx)
        still_in = [p for p in players if p.active and not p.folded]

    # Showdown
    if len(still_in) == 1:
        still_in[0].chips += pot
    elif len(still_in) > 1:
        best_val = max(best_hand(p.hole + community) for p in still_in)
        winners  = [p for p in still_in if best_hand(p.hole + community) == best_val]
        share    = pot // len(winners)
        for w in winners:
            w.chips += share
        # Remainder goes to first winner
        winners[0].chips += pot - share * len(winners)

    # Eliminate broke players
    for p in players:
        if p.active and p.chips <= 0:
            p.active = False
            p.chips  = 0

    # Advance dealer
    next_dealer = (dealer_idx + 1) % n
    while not players[next_dealer].active:
        next_dealer = (next_dealer + 1) % n

    return next_dealer

def run_tournament():
    """Run one full tournament. Returns (winner_pid, winner_name)."""
    players = [Player(i, STRATEGIES[i][0], STRATEGIES[i][1]) for i in range(6)]
    dealer_idx = 0
    for _ in range(MAX_ROUNDS):
        alive = [p for p in players if p.active]
        if len(alive) == 1:
            return alive[0].pid, alive[0].name
        dealer_idx = run_hand(players, dealer_idx)
    # Tiebreak: most chips
    alive = [p for p in players if p.active]
    winner = max(alive, key=lambda p: p.chips)
    return winner.pid, winner.name

# ---------------------------------------------------------------------------
# Run 100 tournaments + histogram
# ---------------------------------------------------------------------------

def main():
    N = 100
    print(f"Running {N} Texas Hold'em tournaments...")
    print(f"Player 1 = '{STRATEGIES[0][0]}' (The Simple All-In Strategy)")
    print(f"Players 2-6 use elaborate strategies\n")

    win_counts = Counter()
    for i in range(N):
        pid, name = run_tournament()
        win_counts[pid] += 1
        if (i + 1) % 10 == 0:
            print(f"  Completed {i+1}/{N} tournaments...", flush=True)

    print("\n" + "="*60)
    print("  TOURNAMENT RESULTS — WHO IS THE CHICKEN DINNER KING?")
    print("="*60)

    max_wins = max(win_counts.values()) if win_counts else 1
    bar_width = 40

    print(f"\n{'Player':<24} {'Wins':>5}  {'%':>6}  Histogram")
    print("-"*70)
    for pid in range(6):
        name  = STRATEGIES[pid][0]
        wins  = win_counts.get(pid, 0)
        pct   = wins / N * 100
        label = f"P{pid+1} {name}"
        bar   = "█" * int(wins / max_wins * bar_width)
        tag   = " ← THE DEGENERATE (all-in bot)" if pid == 0 else ""
        print(f"{label:<24} {wins:>5}  {pct:>5.1f}%  {bar}{tag}")

    print("-"*70)
    winner_pid = win_counts.most_common(1)[0][0]
    winner_name = STRATEGIES[winner_pid][0]
    print(f"\n  CHAMPION: Player {winner_pid+1} — {winner_name} ({win_counts[winner_pid]} wins / {win_counts[winner_pid]}%)")

    if winner_pid == 0:
        print("\n  The Degenerate's chaotic all-in energy HUMILIATES the field.")
        print("  Sometimes chaos beats order. Suflair GPT has left the chat.")
    else:
        print(f"\n  {winner_name} out-thinks The Degenerate across 100 tournaments.")
        print("  Strategy wins in the long run. Eat that, Suflair GPT.")

    print("="*60)

if __name__ == "__main__":
    random.seed(42)
    main()
