"""
Texas Hold'em 100-simulation tournament.
Player 1: YOLO (always all-in)
Players 2-6: 5 elaborate strategies
Outputs a winner histogram.
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

RANKS = list(range(2, 15))  # 2-14, where 14=Ace
SUITS = ['s', 'h', 'd', 'c']

def card(rank, suit):
    return (rank, suit)

def deck():
    return [card(r, s) for r in RANKS for s in SUITS]

def rank_name(r):
    names = {14: 'A', 13: 'K', 12: 'Q', 11: 'J', 10: 'T'}
    return names.get(r, str(r))

# ---------------------------------------------------------------------------
# Hand evaluator (returns a tuple; higher = better hand)
# ---------------------------------------------------------------------------

def best_hand(cards):
    """Return the best 5-card hand value from up to 7 cards."""
    best = None
    for combo in combinations(cards, 5):
        val = hand_value(combo)
        if best is None or val > best:
            best = val
    return best

def hand_value(five):
    ranks = sorted([c[0] for c in five], reverse=True)
    suits = [c[1] for c in five]
    is_flush = len(set(suits)) == 1
    is_straight = (ranks == list(range(ranks[0], ranks[0] - 5, -1)) or
                   ranks == [14, 5, 4, 3, 2])  # wheel
    if ranks == [14, 5, 4, 3, 2]:
        ranks = [5, 4, 3, 2, 1]

    counts = sorted(Counter(ranks).values(), reverse=True)
    rank_by_freq = sorted(Counter(ranks).keys(),
                          key=lambda r: (Counter(ranks)[r], r), reverse=True)

    if is_flush and is_straight:
        return (8, ranks[0])
    if counts[0] == 4:
        return (7,) + tuple(rank_by_freq)
    if counts[:2] == [3, 2]:
        return (6,) + tuple(rank_by_freq)
    if is_flush:
        return (5,) + tuple(ranks)
    if is_straight:
        return (4, ranks[0])
    if counts[0] == 3:
        return (3,) + tuple(rank_by_freq)
    if counts[:2] == [2, 2]:
        return (2,) + tuple(rank_by_freq)
    if counts[0] == 2:
        return (1,) + tuple(rank_by_freq)
    return (0,) + tuple(ranks)

# ---------------------------------------------------------------------------
# Hand-strength estimator (Monte Carlo, light)
# ---------------------------------------------------------------------------

def estimate_strength(hole, community, n_players, n_samples=120):
    """Probability this hand wins at showdown (rough MC estimate)."""
    known = set(map(tuple, hole + community))
    remaining = [c for c in deck() if tuple(c) not in known]
    needed = 5 - len(community)
    wins = 0
    for _ in range(n_samples):
        sample = random.sample(remaining, needed + 2 * (n_players - 1))
        board = community + sample[:needed]
        my_val = best_hand(hole + board)
        opp_cards = sample[needed:]
        best_opp = max(
            best_hand([opp_cards[i], opp_cards[i+1]] + board)
            for i in range(0, len(opp_cards), 2)
        )
        if my_val >= best_opp:
            wins += 1
    return wins / n_samples

# ---------------------------------------------------------------------------
# Pre-flop hand category helpers
# ---------------------------------------------------------------------------

def hand_tier(hole):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2
    if pair and r1 >= 10:
        return 'premium'
    if pair and r1 >= 7:
        return 'mid_pair'
    if pair:
        return 'low_pair'
    gap = r1 - r2
    if r1 == 14 and r2 >= 10:
        return 'premium'
    if r1 >= 11 and r2 >= 10:
        return 'premium' if suited else 'strong'
    if r1 >= 10 and gap <= 3 and suited:
        return 'speculative'
    if r1 >= 10 and gap <= 2:
        return 'strong' if r2 >= 9 else 'marginal'
    if suited and gap <= 2:
        return 'speculative'
    return 'trash'

def pot_odds(call_amt, pot):
    if call_amt <= 0:
        return 1.0
    return pot / (pot + call_amt)

# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------
# Each strategy is a function:
#   decide(hole, community, pot, to_call, my_stack, min_raise,
#          n_active, position, street, aggression_history) -> action
# action: ('fold',), ('call',), ('raise', amount), ('check',), ('allin',)

# --- Strategy 0: YOLO (Player 1 always shoves) ---
def strategy_yolo(hole, community, pot, to_call, my_stack,
                  min_raise, n_active, position, street, history):
    return ('allin',)

# --- Strategy 1: GTO-Lite (position + hand-strength aware) ---
def strategy_gto_lite(hole, community, pot, to_call, my_stack,
                      min_raise, n_active, position, street, history):
    tier = hand_tier(hole)
    is_late = position >= n_active * 0.6
    is_bb = position == 0

    if street == 'preflop':
        if tier == 'premium':
            raise_amt = min(my_stack, max(min_raise, int(pot * 3)))
            return ('raise', raise_amt)
        if tier in ('strong', 'mid_pair'):
            if is_late or is_bb:
                raise_amt = min(my_stack, max(min_raise, int(pot * 2.5)))
                return ('raise', raise_amt)
            if to_call <= my_stack * 0.05:
                return ('call',)
            return ('fold',)
        if tier == 'speculative' and is_late:
            if to_call <= my_stack * 0.04:
                return ('call',)
        if to_call == 0:
            return ('check',)
        if tier != 'trash' and to_call <= my_stack * 0.03:
            return ('call',)
        return ('fold',)
    else:
        strength = estimate_strength(hole, community, n_active, 100)
        pot_o = pot_odds(to_call, pot)
        if strength > 0.75:
            raise_amt = min(my_stack, max(min_raise, int(pot * 0.75)))
            return ('raise', raise_amt)
        if strength > pot_o + 0.1:
            if to_call == 0:
                bet = min(my_stack, max(min_raise, int(pot * 0.5)))
                return ('raise', bet)
            return ('call',)
        if to_call == 0:
            return ('check',)
        return ('fold',)

# --- Strategy 2: Tight-Aggressive (TAG) ---
def strategy_tag(hole, community, pot, to_call, my_stack,
                 min_raise, n_active, position, street, history):
    tier = hand_tier(hole)
    if street == 'preflop':
        if tier == 'premium':
            return ('raise', min(my_stack, max(min_raise, int(pot * 3.5))))
        if tier == 'strong':
            if to_call <= my_stack * 0.06:
                return ('call',)
            return ('fold',)
        if to_call == 0:
            return ('check',)
        return ('fold',)
    else:
        strength = estimate_strength(hole, community, n_active, 80)
        if strength > 0.70:
            return ('raise', min(my_stack, max(min_raise, int(pot * 0.8))))
        if strength > 0.50:
            if to_call == 0:
                return ('check',)
            if to_call <= my_stack * 0.15:
                return ('call',)
        if to_call == 0:
            return ('check',)
        return ('fold',)

# --- Strategy 3: Loose-Aggressive (LAG) with bluffing ---
def strategy_lag(hole, community, pot, to_call, my_stack,
                 min_raise, n_active, position, street, history):
    tier = hand_tier(hole)
    bluff_roll = random.random()

    if street == 'preflop':
        if tier in ('premium', 'strong', 'mid_pair', 'speculative'):
            return ('raise', min(my_stack, max(min_raise, int(pot * 2.5))))
        if tier == 'low_pair' or (tier == 'marginal' and bluff_roll < 0.4):
            return ('call',) if to_call <= my_stack * 0.08 else ('fold',)
        if bluff_roll < 0.25 and to_call == 0:
            return ('raise', min(my_stack, max(min_raise, int(pot * 2))))
        if to_call == 0:
            return ('check',)
        if to_call <= my_stack * 0.04:
            return ('call',)
        return ('fold',)
    else:
        strength = estimate_strength(hole, community, n_active, 80)
        if strength > 0.60:
            return ('raise', min(my_stack, max(min_raise, int(pot * 1.0))))
        if bluff_roll < 0.20 and street in ('flop', 'turn'):
            # semi-bluff / pure bluff
            return ('raise', min(my_stack, max(min_raise, int(pot * 0.6))))
        if strength > 0.40 and to_call == 0:
            return ('check',)
        if strength > 0.35 and to_call <= my_stack * 0.12:
            return ('call',)
        if to_call == 0:
            return ('check',)
        return ('fold',)

# --- Strategy 4: Probabilistic / Bayesian ---
def strategy_probabilistic(hole, community, pot, to_call, my_stack,
                            min_raise, n_active, position, street, history):
    if street == 'preflop':
        tier = hand_tier(hole)
        tier_ev = {'premium': 0.82, 'strong': 0.65, 'mid_pair': 0.58,
                   'speculative': 0.50, 'low_pair': 0.48, 'marginal': 0.42,
                   'trash': 0.30}
        ev = tier_ev.get(tier, 0.30)
        # adjust for position
        ev += (position / max(n_active, 1)) * 0.08
    else:
        ev = estimate_strength(hole, community, n_active, 100)

    pot_o = pot_odds(to_call, pot)
    edge = ev - pot_o

    if ev > 0.75:
        bet = int(pot * min(ev, 1.0))
        return ('raise', min(my_stack, max(min_raise, bet)))
    if edge > 0.15:
        if to_call == 0:
            bet = int(pot * ev * 0.7)
            return ('raise', min(my_stack, max(min_raise, bet)))
        return ('call',)
    if edge > 0.0:
        if to_call == 0:
            return ('check',)
        if to_call <= my_stack * 0.10:
            return ('call',)
    if to_call == 0:
        return ('check',)
    return ('fold',)

# --- Strategy 5: Adaptive / History-based ---
def strategy_adaptive(hole, community, pot, to_call, my_stack,
                      min_raise, n_active, position, street, history):
    """
    Reads aggression_history (list of raise counts per opponent seen so far)
    and adjusts: tight vs loose opponents changes calling range.
    """
    avg_aggression = sum(history) / len(history) if history else 0.5
    # High aggression opponents -> tighten up; passive -> loosen

    if street == 'preflop':
        tier = hand_tier(hole)
        threshold_call = 0.05 if avg_aggression > 0.6 else 0.10
        if tier == 'premium':
            return ('raise', min(my_stack, max(min_raise, int(pot * 3))))
        if tier in ('strong', 'mid_pair'):
            if avg_aggression < 0.4:
                return ('raise', min(my_stack, max(min_raise, int(pot * 2))))
            return ('call',) if to_call <= my_stack * threshold_call else ('fold',)
        if tier == 'speculative' and avg_aggression < 0.35:
            return ('call',) if to_call <= my_stack * 0.04 else ('fold',)
        if to_call == 0:
            return ('check',)
        return ('fold',)
    else:
        strength = estimate_strength(hole, community, n_active, 90)
        if avg_aggression > 0.6:
            # tighter
            if strength > 0.70:
                return ('raise', min(my_stack, max(min_raise, int(pot * 0.7))))
            if strength > 0.55 and to_call <= my_stack * 0.12:
                return ('call',)
            if to_call == 0:
                return ('check',)
            return ('fold',)
        else:
            # looser
            if strength > 0.55:
                return ('raise', min(my_stack, max(min_raise, int(pot * 0.6))))
            if strength > 0.40:
                if to_call == 0:
                    return ('check',)
                if to_call <= my_stack * 0.15:
                    return ('call',)
            if to_call == 0:
                return ('check',)
            return ('fold',)

STRATEGIES = [
    strategy_yolo,
    strategy_gto_lite,
    strategy_tag,
    strategy_lag,
    strategy_probabilistic,
    strategy_adaptive,
]

STRATEGY_NAMES = [
    "YOLO (P1)",
    "GTO-Lite (P2)",
    "TAG (P3)",
    "LAG (P4)",
    "Probabilistic (P5)",
    "Adaptive (P6)",
]

# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

SMALL_BLIND = 50
BIG_BLIND = 100
STARTING_STACK = 5000

class Player:
    def __init__(self, pid, strategy_fn, name):
        self.pid = pid
        self.strategy = strategy_fn
        self.name = name
        self.stack = STARTING_STACK
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0  # amount put in this street
        self.aggression_seen = []  # raise counts from opponents each hand

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

    def reset_for_street(self):
        self.bet = 0

    def is_active(self):
        return self.stack > 0 and not self.folded


def play_hand(players, dealer_idx):
    """
    Play a single hand. Returns updated players list.
    dealer_idx: index into players list of current dealer button.
    """
    n = len(players)
    if n < 2:
        return players

    # Reset
    for p in players:
        p.reset_for_hand()

    d = deck()
    random.shuffle(d)

    # Deal hole cards
    for i, p in enumerate(players):
        p.hole = [d.pop(), d.pop()]

    # Blinds
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    pot = 0
    community = []

    def post_blind(idx, amount):
        nonlocal pot
        p = players[idx]
        amt = min(amount, p.stack)
        p.stack -= amt
        p.bet += amt
        pot += amt
        if p.stack == 0:
            p.all_in = True

    post_blind(sb_idx, SMALL_BLIND)
    post_blind(bb_idx, BIG_BLIND)

    def betting_round(street, first_to_act):
        nonlocal pot
        active = [p for p in players if not p.folded and not p.all_in]
        if len(active) <= 1:
            return

        for p in players:
            p.reset_for_street()
        # restore existing bets for preflop blinds
        if street == 'preflop':
            players[sb_idx].bet = min(SMALL_BLIND, players[sb_idx].stack + SMALL_BLIND)
            players[bb_idx].bet = min(BIG_BLIND, players[bb_idx].stack + BIG_BLIND)
            # but we already deducted from stack so reconstruct
            # simpler: track current_bet per player fresh each street
            pass

        current_bet = max(p.bet for p in players)
        min_raise_size = BIG_BLIND

        order = [(first_to_act + i) % n for i in range(n)]
        acted = set()
        last_raiser = None

        while True:
            advanced = False
            for idx in order:
                p = players[idx]
                if p.folded or p.all_in:
                    continue
                if idx in acted and idx != last_raiser:
                    if p.bet >= current_bet:
                        continue

                to_call = current_bet - p.bet
                n_active = sum(1 for x in players if not x.folded)
                pos = order.index(idx)

                history = p.aggression_seen if p.aggression_seen else [0.5]
                action = p.strategy(
                    p.hole, community, pot, to_call, p.stack,
                    min_raise_size, n_active, pos, street, history
                )

                if action[0] == 'fold':
                    p.folded = True
                elif action[0] == 'check':
                    pass
                elif action[0] == 'call':
                    amt = min(to_call, p.stack)
                    p.stack -= amt
                    p.bet += amt
                    pot += amt
                    if p.stack == 0:
                        p.all_in = True
                elif action[0] == 'raise':
                    total_raise = action[1]
                    # total_raise is the EXTRA amount on top of call
                    amt = min(to_call + total_raise, p.stack)
                    p.stack -= amt
                    p.bet += amt
                    pot += amt
                    if p.stack == 0:
                        p.all_in = True
                    current_bet = p.bet
                    min_raise_size = max(min_raise_size, action[1])
                    last_raiser = idx
                    acted.clear()
                    # update aggression tracking for others
                    for other in players:
                        if other.pid != p.pid:
                            other.aggression_seen.append(1)
                elif action[0] == 'allin':
                    amt = p.stack
                    p.stack = 0
                    p.bet += amt
                    pot += amt
                    p.all_in = True
                    if p.bet > current_bet:
                        current_bet = p.bet
                        last_raiser = idx
                        acted.clear()
                    for other in players:
                        if other.pid != p.pid:
                            other.aggression_seen.append(1)

                acted.add(idx)
                advanced = True

                # check if only one non-folded player left
                remaining = [x for x in players if not x.folded]
                if len(remaining) == 1:
                    return

            # Check if all active players have matched the bet
            still_to_act = [p for p in players
                            if not p.folded and not p.all_in
                            and p.bet < current_bet]
            if not still_to_act:
                break
            if not advanced:
                break

    # Preflop
    first_preflop = (dealer_idx + 3) % n
    # reset bets tracker for preflop (blinds already deducted, reflect in .bet)
    players[sb_idx].bet = SMALL_BLIND if players[sb_idx].stack + SMALL_BLIND <= STARTING_STACK else SMALL_BLIND
    players[bb_idx].bet = BIG_BLIND if players[bb_idx].stack + BIG_BLIND <= STARTING_STACK else BIG_BLIND
    # simpler re-set: we track how much each player has put in the pot this round
    # Since we already deducted, just note what they put in
    # (the pot is already correct; .bet is for determining call amounts)
    players[sb_idx].bet = min(SMALL_BLIND, STARTING_STACK)
    players[bb_idx].bet = min(BIG_BLIND, STARTING_STACK)

    betting_round('preflop', first_preflop)

    # Check if hand is over early
    active_players = [p for p in players if not p.folded]
    if len(active_players) == 1:
        active_players[0].stack += pot
        return players

    # Flop
    for p in players:
        p.bet = 0
    community += [d.pop(), d.pop(), d.pop()]
    betting_round('flop', (dealer_idx + 1) % n)

    active_players = [p for p in players if not p.folded]
    if len(active_players) == 1:
        active_players[0].stack += pot
        return players

    # Turn
    for p in players:
        p.bet = 0
    community.append(d.pop())
    betting_round('turn', (dealer_idx + 1) % n)

    active_players = [p for p in players if not p.folded]
    if len(active_players) == 1:
        active_players[0].stack += pot
        return players

    # River
    for p in players:
        p.bet = 0
    community.append(d.pop())
    betting_round('river', (dealer_idx + 1) % n)

    # Showdown
    showdown_players = [p for p in players if not p.folded]
    if not showdown_players:
        return players

    # Handle side pots simply: winner(s) of main pot
    # (full side-pot logic omitted for simulation speed; winner takes all pot)
    best_val = None
    winners = []
    for p in showdown_players:
        val = best_hand(p.hole + community)
        if best_val is None or val > best_val:
            best_val = val
            winners = [p]
        elif val == best_val:
            winners.append(p)

    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        w.stack += share
    winners[0].stack += remainder  # give remainder to first winner

    return players


def run_tournament():
    """Run a single tournament until one player has all chips. Return winner name."""
    players = [Player(i+1, STRATEGIES[i], STRATEGY_NAMES[i]) for i in range(6)]
    dealer_idx = 0
    hand_num = 0
    max_hands = 5000

    while True:
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1:
            return alive[0].name
        if hand_num >= max_hands:
            # chip-count winner
            return max(alive, key=lambda p: p.stack).name

        play_hand(alive, dealer_idx % len(alive))
        dealer_idx += 1
        hand_num += 1

        # Blind escalation every 100 hands to prevent inf games
        if hand_num % 100 == 0:
            global SMALL_BLIND, BIG_BLIND
            SMALL_BLIND = int(SMALL_BLIND * 1.5)
            BIG_BLIND = int(BIG_BLIND * 1.5)


# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------

def run_simulations(n=100):
    global SMALL_BLIND, BIG_BLIND
    results = Counter()
    for sim in range(1, n + 1):
        SMALL_BLIND = 50
        BIG_BLIND = 100
        winner = run_tournament()
        results[winner] += 1
        print(f"  Sim {sim:3d}/100  → {winner}")
    return results


def histogram(results, n_sims):
    print("\n" + "=" * 60)
    print("  TOURNAMENT WINNER HISTOGRAM  (100 simulations)")
    print("=" * 60)
    max_wins = max(results.values()) if results else 1
    bar_width = 40

    order = sorted(STRATEGY_NAMES, key=lambda name: results.get(name, 0), reverse=True)
    for name in order:
        wins = results.get(name, 0)
        bar = "█" * int(wins / max_wins * bar_width)
        pct = wins / n_sims * 100
        tag = " ← YOLO KING 👑" if "YOLO" in name and wins == max(results.values()) else ""
        tag2 = " ← YOLO (simple all-in)" if "YOLO" in name else ""
        label = tag if tag else tag2
        print(f"  {name:<22} {bar:<40} {wins:3d} wins ({pct:5.1f}%){label}")

    print("=" * 60)
    overall_winner = max(results, key=results.get)
    print(f"\n  CHAMPION: {overall_winner}  ({results[overall_winner]} / {n_sims} tournaments won)")
    if "YOLO" in overall_winner:
        print("  The \"think less, shove more\" strategy reigns supreme. 🃏")
    else:
        print("  The elaborate strategies prevailed. GG, YOLO.")
    print()


if __name__ == "__main__":
    print("Running 100 Texas Hold'em tournaments...")
    print("Player 1 = YOLO (always all-in)")
    print("Players 2-6 = GTO-Lite / TAG / LAG / Probabilistic / Adaptive\n")

    results = run_simulations(100)
    histogram(results, 100)
