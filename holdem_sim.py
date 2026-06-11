"""
Texas Hold'em 100-simulation tournament.
Player 1  : The Maniac — always shoves all-in, every turn, no questions asked.
Players 2-6: Five elaborate strategy bots.
Last player with chips wins the tournament.
Run 100 tournaments, print ASCII histogram of winners.
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ---------------------------------------------------------------------------
# Hand evaluator (returns comparable tuple, higher = better)
# ---------------------------------------------------------------------------
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
    straight = (vals == list(range(vals[0], vals[0]-5, -1)) or
                vals == [12, 3, 2, 1, 0])  # A-2-3-4-5
    if straight and vals[0] == 12 and vals[1] == 3:
        vals = [3, 2, 1, 0, -1]  # wheel: treat A as low

    counts = sorted(Counter(vals).values(), reverse=True)
    groups = sorted(Counter(vals).keys(), key=lambda v: (Counter(vals)[v], v), reverse=True)

    if flush and straight:
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

# ---------------------------------------------------------------------------
# Monte Carlo equity estimator (used by some strategies)
# ---------------------------------------------------------------------------
def estimate_equity(hole, community, num_opponents, trials=200):
    deck = [c for c in make_deck() if c not in hole and c not in community]
    wins = 0
    for _ in range(trials):
        random.shuffle(deck)
        needed = 5 - len(community)
        board = list(community) + deck[:needed]
        opp_hands = []
        for i in range(num_opponents):
            h = deck[needed + i*2: needed + i*2 + 2]
            if len(h) < 2:
                break
            opp_hands.append(h)
        my_score = hand_rank(hole + board)
        best_opp = max((hand_rank(oh + board) for oh in opp_hands), default=(-1, []))
        if my_score > best_opp:
            wins += 1
    return wins / trials

# ---------------------------------------------------------------------------
# Game state helpers
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = strategy_fn
        self.hole = []
        self.bet_in_round = 0
        self.folded = False
        self.all_in = False

    def reset_for_hand(self):
        self.hole = []
        self.bet_in_round = 0
        self.folded = False
        self.all_in = False

# ---------------------------------------------------------------------------
# Strategy 1 (Player 1): The Maniac — always all-in
# ---------------------------------------------------------------------------
def strategy_maniac(player, game_state):
    """If my_turn then bet = All in fi"""
    return ('raise', player.chips)

# ---------------------------------------------------------------------------
# Strategy 2: GTO-Ish — equity-based pot-odds with position awareness
# ---------------------------------------------------------------------------
def strategy_gto(player, game_state):
    hole = player.hole
    community = game_state['community']
    pot = game_state['pot']
    to_call = game_state['to_call']
    num_active = game_state['num_active']
    position = game_state['position']   # 0=early, 1=mid, 2=late/btn

    equity = estimate_equity(hole, community, max(1, num_active - 1), trials=150)

    # Pot odds
    pot_odds = to_call / (pot + to_call + 1e-9)

    if equity < pot_odds:
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

    ev = equity * pot - (1 - equity) * to_call
    # Size bet proportionally to equity edge
    edge = equity - pot_odds
    if edge > 0.25 and position == 2:
        bet_size = min(player.chips, int(pot * 1.5))
        return ('raise', bet_size)
    elif equity > 0.65:
        bet_size = min(player.chips, int(pot * 0.75))
        return ('raise', bet_size)
    elif ev > 0:
        if to_call == 0:
            return ('check', 0)
        return ('call', to_call)
    else:
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 3: Tag (Tight-Aggressive) — plays few hands, bets hard when in
# ---------------------------------------------------------------------------
PREMIUM_HANDS = {('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'),
                 ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('K', 'Q')}

def strategy_tag(player, game_state):
    hole = player.hole
    community = game_state['community']
    pot = game_state['pot']
    to_call = game_state['to_call']
    num_active = game_state['num_active']
    street = game_state['street']

    r1, r2 = hole[0][0], hole[1][0]
    suited = hole[0][1] == hole[1][1]
    pair_ranks = tuple(sorted([r1, r2], key=lambda r: RANK_VAL[r], reverse=True))
    premium = pair_ranks in PREMIUM_HANDS or (suited and pair_ranks in {('A','K'),('A','Q'),('K','Q')})

    if street == 'preflop':
        if premium:
            bet = min(player.chips, max(to_call * 3, int(pot * 1.0) + 1))
            return ('raise', bet)
        # Fold non-premium unless free
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)
    else:
        equity = estimate_equity(hole, community, max(1, num_active - 1), trials=120)
        if equity > 0.7:
            return ('raise', min(player.chips, int(pot * 1.2)))
        if equity > 0.5:
            if to_call == 0:
                return ('check', 0)
            return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 4: LAG (Loose-Aggressive) — plays wide, lots of bluffs
# ---------------------------------------------------------------------------
def strategy_lag(player, game_state):
    hole = player.hole
    community = game_state['community']
    pot = game_state['pot']
    to_call = game_state['to_call']
    num_active = game_state['num_active']
    street = game_state['street']

    equity = estimate_equity(hole, community, max(1, num_active - 1), trials=100)

    # Bluff frequency: if equity < 0.35 bluff 40% of the time
    bluff = random.random() < 0.4

    if equity > 0.55 or bluff:
        size = min(player.chips, int(pot * random.uniform(0.6, 2.0)))
        if size == 0:
            size = max(1, player.chips // 4)
        return ('raise', size)
    if equity > 0.35:
        if to_call == 0:
            return ('check', 0)
        return ('call', to_call)
    if to_call == 0:
        return ('check', 0)
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 5: Exploitative — reads table aggression, adjusts
# ---------------------------------------------------------------------------
def strategy_exploitative(player, game_state):
    hole = player.hole
    community = game_state['community']
    pot = game_state['pot']
    to_call = game_state['to_call']
    num_active = game_state['num_active']
    aggression = game_state.get('table_aggression', 0.5)  # 0=passive, 1=aggressive

    equity = estimate_equity(hole, community, max(1, num_active - 1), trials=120)

    # Against aggressive table: tighten up, trap with strong hands
    if aggression > 0.65:
        if equity > 0.75:
            # Slowplay / call to let them hang themselves, then raise river
            if to_call > 0:
                return ('call', to_call)
            return ('check', 0)
        if equity > 0.5 and to_call == 0:
            return ('check', 0)
        if equity > 0.5:
            return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)
    else:
        # Against passive table: bet big for value
        if equity > 0.55:
            return ('raise', min(player.chips, int(pot * 1.0 + 1)))
        if equity > 0.4:
            if to_call == 0:
                return ('check', 0)
            return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 6: Pot-Control / ICM-aware — protects stack, avoids bust
# ---------------------------------------------------------------------------
def strategy_icm(player, game_state):
    hole = player.hole
    community = game_state['community']
    pot = game_state['pot']
    to_call = game_state['to_call']
    num_active = game_state['num_active']
    avg_stack = game_state.get('avg_stack', player.chips)

    equity = estimate_equity(hole, community, max(1, num_active - 1), trials=120)

    stack_ratio = player.chips / max(1, avg_stack)

    # Short-stacked: shove or fold
    if stack_ratio < 0.4:
        if equity > 0.45:
            return ('raise', player.chips)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

    # Deep-stacked: play conservatively, avoid huge pots without near-nuts
    if equity > 0.72:
        return ('raise', min(player.chips, int(pot * 0.9 + 1)))
    if equity > 0.55:
        if to_call == 0:
            return ('check', 0)
        return ('call', min(to_call, int(player.chips * 0.25)))
    if to_call == 0:
        return ('check', 0)
    # Only call if pot odds justify it
    pot_odds = to_call / (pot + to_call + 1e-9)
    if equity > pot_odds * 1.1:
        return ('call', to_call)
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------
STRATEGIES = [
    ("The Maniac",       strategy_maniac),
    ("GTO-Ish",          strategy_gto),
    ("TAG",              strategy_tag),
    ("LAG",              strategy_lag),
    ("Exploitative",     strategy_exploitative),
    ("ICM-Aware",        strategy_icm),
]

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

def run_tournament():
    players = [
        Player(i+1, STARTING_CHIPS, STRATEGIES[i][1])
        for i in range(6)
    ]
    hand_count = 0
    max_hands  = 3000  # safety cap

    while sum(1 for p in players if p.chips > 0) > 1 and hand_count < max_hands:
        hand_count += 1
        active = [p for p in players if p.chips > 0]
        if len(active) < 2:
            break
        play_hand(active, players)

    survivors = [p for p in players if p.chips > 0]
    if survivors:
        winner = max(survivors, key=lambda p: p.chips)
        return winner.pid
    return None

# ---------------------------------------------------------------------------
# Hand engine
# ---------------------------------------------------------------------------
def play_hand(active, all_players):
    for p in active:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    # Deal hole cards
    idx = 0
    for p in active:
        p.hole = [deck[idx], deck[idx+1]]
        idx += 2

    community = []
    pot = 0

    # Blinds
    sb_player = active[0]
    bb_player = active[1] if len(active) > 1 else active[0]

    sb_amount = min(SMALL_BLIND, sb_player.chips)
    bb_amount = min(BIG_BLIND,   bb_player.chips)

    sb_player.chips -= sb_amount
    sb_player.bet_in_round = sb_amount
    if sb_player.chips == 0:
        sb_player.all_in = True

    bb_player.chips -= bb_amount
    bb_player.bet_in_round = bb_amount
    if bb_player.chips == 0:
        bb_player.all_in = True

    pot = sb_amount + bb_amount

    # Compute table aggression metric (raise fraction across last hands — proxy: random ±)
    # We just vary it mildly each hand so exploitative bot has something to react to
    table_aggression = random.uniform(0.3, 0.9)
    avg_stack = sum(p.chips for p in active) / len(active)

    card_cursor = idx  # after hole cards

    for street_name, num_cards in [
        ('preflop', 0),
        ('flop',    3),
        ('turn',    1),
        ('river',   1),
    ]:
        if num_cards:
            community.extend(deck[card_cursor:card_cursor + num_cards])
            card_cursor += num_cards

        pot = betting_round(
            street    = street_name,
            active    = active,
            community = community,
            pot       = pot,
            table_aggression = table_aggression,
            avg_stack = avg_stack,
        )

        still_in = [p for p in active if not p.folded]
        if len(still_in) <= 1:
            break

    # Showdown
    still_in = [p for p in active if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
    else:
        scores = [(hand_rank(p.hole + community), p) for p in still_in]
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score = scores[0][0]
        winners = [p for score, p in scores if score == best_score]
        share = pot // len(winners)
        remainder = pot - share * len(winners)
        for w in winners:
            w.chips += share
        winners[0].chips += remainder  # odd chip to first winner

def betting_round(street, active, community, pot, table_aggression, avg_stack):
    players = [p for p in active if not p.folded and not p.all_in]
    if not players:
        return pot

    current_bet = max(p.bet_in_round for p in active)

    # Reset per-street bet tracking on non-preflop streets
    if street != 'preflop':
        for p in active:
            p.bet_in_round = 0
        current_bet = 0

    # Preflop: BB already put in BIG_BLIND; action starts after BB
    if street == 'preflop':
        order = active[2:] + active[:2] if len(active) > 2 else active[:]
    else:
        order = active[:]

    num_active = len([p for p in active if not p.folded])

    max_raises = 4
    raises_this_round = 0

    acted = set()
    i = 0
    iterations = 0
    while iterations < len(active) * (max_raises + 2):
        iterations += 1
        p = order[i % len(order)]
        i += 1

        if p.folded or p.all_in:
            if len([x for x in order if not x.folded and not x.all_in and x.pid not in acted]) == 0:
                break
            continue

        to_call = max(0, current_bet - p.bet_in_round)
        if to_call > p.chips:
            to_call = p.chips  # can only call what they have

        game_state = {
            'street':           street,
            'community':        community,
            'pot':              pot,
            'to_call':          to_call,
            'num_active':       num_active,
            'position':         2 if i % len(order) >= len(order) - 2 else (1 if i % len(order) > 1 else 0),
            'table_aggression': table_aggression,
            'avg_stack':        avg_stack,
        }

        action, amount = p.strategy_fn(p, game_state)

        if action == 'fold':
            p.folded = True
            still_in = [x for x in active if not x.folded]
            if len(still_in) == 1:
                break
        elif action == 'check':
            pass
        elif action == 'call':
            amount = min(amount, p.chips)
            amount = min(amount, to_call)
            p.chips -= amount
            p.bet_in_round += amount
            pot += amount
            if p.chips == 0:
                p.all_in = True
        elif action == 'raise':
            amount = max(1, min(amount, p.chips))
            # Must at least call first
            call_part = min(to_call, p.chips)
            raise_part = max(0, amount - call_part)
            total = call_part + raise_part
            total = min(total, p.chips)
            p.chips -= total
            p.bet_in_round += total
            pot += total
            if p.chips == 0:
                p.all_in = True
            if raise_part > 0:
                current_bet = p.bet_in_round
                raises_this_round += 1
                acted = {p.pid}  # others must act again
            else:
                pass  # treated as call

        acted.add(p.pid)

        # Check if action is closed
        eligible = [x for x in order if not x.folded and not x.all_in]
        unsatisfied = [x for x in eligible if x.bet_in_round < current_bet and x.pid not in acted]
        # Everyone who can act has acted and matched
        all_matched = all(x.bet_in_round >= current_bet or x.all_in or x.folded for x in active)
        everyone_acted = all(x.pid in acted or x.folded or x.all_in for x in active)
        if all_matched and everyone_acted:
            break
        if raises_this_round >= max_raises:
            # No more raises — just calling round
            remaining = [x for x in order if not x.folded and not x.all_in and x.bet_in_round < current_bet]
            for rp in remaining:
                tc = min(current_bet - rp.bet_in_round, rp.chips)
                rp.chips -= tc
                rp.bet_in_round += tc
                pot += tc
                if rp.chips == 0:
                    rp.all_in = True
            break

    return pot

# ---------------------------------------------------------------------------
# Run 100 tournaments & histogram
# ---------------------------------------------------------------------------
def run_simulations(n=100):
    results = Counter()
    for i in range(n):
        winner_pid = run_tournament()
        if winner_pid:
            results[winner_pid] += 1
    return results

def print_histogram(results, n_sims):
    print("\n" + "="*60)
    print("  TEXAS HOLD'EM — 100-TOURNAMENT CHAMPIONSHIP RESULTS")
    print("  Last player standing wins. Player 1 = The Maniac.")
    print("="*60)

    max_wins = max(results.values()) if results else 1
    bar_width = 40

    for pid, (name, _) in enumerate(STRATEGIES, start=1):
        wins = results.get(pid, 0)
        pct  = wins / n_sims * 100
        bar  = "█" * int(wins / max_wins * bar_width)
        tag  = " ← MANIAC (always all-in)" if pid == 1 else ""
        print(f"  P{pid} {name:<16} | {bar:<40} {wins:3d} wins ({pct:5.1f}%){tag}")

    print("="*60)
    best_pid  = max(results, key=results.get) if results else None
    best_name = STRATEGIES[best_pid-1][0] if best_pid else "?"
    worst_pid = min(results, key=results.get) if results else None
    worst_name= STRATEGIES[worst_pid-1][0] if worst_pid else "?"
    print(f"\n  CHAMPION  : Player {best_pid} ({best_name}) with {results[best_pid]} tournament wins")
    if worst_pid != best_pid:
        print(f"  HUMILIATED: Player {worst_pid} ({worst_name}) limped home with {results[worst_pid]} wins")
    print()

if __name__ == "__main__":
    random.seed(42)
    print("Running 100 Texas Hold'em tournament simulations…")
    results = run_simulations(100)
    print_histogram(results, 100)
