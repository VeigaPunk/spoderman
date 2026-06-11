"""
Texas Hold'em Poker Tournament Simulator
Player 1: Simple All-In strategy
Players 2-6: 5 elaborate strategies
100 tournament simulations, histogram of final winners
"""

import random
from collections import Counter
from itertools import combinations
import sys

# ─────────────────────────────────────────────
# CARD INFRASTRUCTURE
# ─────────────────────────────────────────────

RANKS = list(range(2, 15))  # 2-14, where 11=J 12=Q 13=K 14=A
SUITS = ['♠', '♥', '♦', '♣']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(card):
    return f"{RANK_NAMES[card[0]]}{card[1]}"

# ─────────────────────────────────────────────
# HAND EVALUATION
# ─────────────────────────────────────────────

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards. Returns comparable tuple."""
    best = None
    for combo in combinations(cards, 5):
        r = eval5(combo)
        if best is None or r > best:
            best = r
    return best

def eval5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = False
    if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
        straight = True
    # Wheel straight A-2-3-4-5
    if ranks == [14, 5, 4, 3, 2]:
        straight = True
        ranks = [5, 4, 3, 2, 1]

    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda x: (counts[x], x), reverse=True)

    if straight and flush:
        return (8, ranks)
    if freq[0] == 4:
        return (7, groups)
    if freq[:2] == [3, 2]:
        return (6, groups)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if freq[0] == 3:
        return (3, groups)
    if freq[:2] == [2, 2]:
        return (2, groups)
    if freq[0] == 2:
        return (1, groups)
    return (0, ranks)

# ─────────────────────────────────────────────
# MONTE CARLO EQUITY ESTIMATION
# ─────────────────────────────────────────────

def estimate_equity(hole, community, num_opponents, trials=200):
    """Estimate win probability via MC rollout."""
    wins = 0
    deck = [c for c in make_deck() if c not in hole and c not in community]
    needed = 5 - len(community)
    for _ in range(trials):
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        opp_cards = deck[needed:needed + 2 * num_opponents]
        my_rank = hand_rank(hole + board)
        best_opp = max(
            hand_rank(list(opp_cards[i*2:(i+1)*2]) + board)
            for i in range(num_opponents)
        )
        if my_rank > best_opp:
            wins += 1
    return wins / trials

# ─────────────────────────────────────────────
# HAND STRENGTH HELPERS
# ─────────────────────────────────────────────

def preflop_strength(hole):
    r1, r2 = hole[0][0], hole[1][0]
    suited = hole[0][1] == hole[1][1]
    high = max(r1, r2)
    low = min(r1, r2)
    score = high * 2 + low
    if r1 == r2:
        score += 20
    if suited:
        score += 5
    return score / 55.0  # normalised 0..1 roughly

def hand_category(hole, community):
    if not community:
        return preflop_strength(hole)
    return hand_rank(hole + community)[0] / 8.0

# ─────────────────────────────────────────────
# STRATEGY DEFINITIONS
# ─────────────────────────────────────────────

class Strategy:
    def decide(self, player, state):
        raise NotImplementedError


class AllInStrategy(Strategy):
    """Player 1 — the galaxy-brained lunatic. Always all-in."""
    name = "YOLO_ALL_IN"

    def decide(self, player, state):
        return ('raise', player['chips'])


class TightAggressiveStrategy(Strategy):
    """TAG — only plays strong hands, bets hard when in."""
    name = "TightAggressive"

    def decide(self, player, state):
        hole = player['hole']
        community = state['community']
        pot = state['pot']
        call_amt = state['call_amount']
        chips = player['chips']
        opponents = state['active_players'] - 1

        if not community:
            strength = preflop_strength(hole)
            if strength < 0.55:
                return ('fold', 0)
            elif strength < 0.75:
                if call_amt > chips * 0.15:
                    return ('fold', 0)
                return ('call', min(call_amt, chips))
            else:
                bet = min(int(pot * 0.75), chips)
                return ('raise', max(bet, call_amt + 1))
        else:
            equity = estimate_equity(hole, community, max(1, opponents), 150)
            if equity < 0.35:
                if call_amt == 0:
                    return ('check', 0)
                return ('fold', 0)
            elif equity < 0.55:
                if call_amt > pot * 0.4:
                    return ('fold', 0)
                return ('call', min(call_amt, chips))
            else:
                bet = min(int(pot * 0.8), chips)
                return ('raise', max(bet, call_amt + 1))


class LoosePassiveStrategy(Strategy):
    """Calling station — sees lots of flops, rarely raises."""
    name = "LoosePassive"

    def decide(self, player, state):
        hole = player['hole']
        community = state['community']
        pot = state['pot']
        call_amt = state['call_amount']
        chips = player['chips']

        if not community:
            strength = preflop_strength(hole)
            if strength < 0.25:
                return ('fold', 0)
            if call_amt > chips * 0.35:
                return ('fold', 0)
            return ('call', min(call_amt, chips))
        else:
            cat = hand_category(hole, community)
            if cat > 0.5:
                bet = min(int(pot * 0.3), chips)
                return ('raise', max(bet, call_amt + 1))
            if call_amt > chips * 0.3:
                return ('fold', 0)
            return ('call', min(call_amt, chips))


class GtoApproximatorStrategy(Strategy):
    """
    Approximates GTO by mixing bet sizes with equity-based frequencies.
    Uses pot-geometry sizing and polarised ranges.
    """
    name = "GTO_Approx"

    def decide(self, player, state):
        hole = player['hole']
        community = state['community']
        pot = state['pot']
        call_amt = state['call_amount']
        chips = player['chips']
        opponents = state['active_players'] - 1
        street = len(community)

        if not community:
            strength = preflop_strength(hole)
            # Mixed strategy: stronger hands raise more often
            threshold = random.random()
            if strength > 0.80:
                # Premium — always 3-bet sized open
                return ('raise', min(int(pot * 2.5 + call_amt * 3), chips))
            elif strength > 0.60 and threshold < 0.7:
                return ('raise', min(int(pot + call_amt * 2.5), chips))
            elif strength > 0.40 and threshold < 0.5:
                return ('call', min(call_amt, chips))
            else:
                if call_amt == 0:
                    return ('check', 0)
                return ('fold', 0)

        equity = estimate_equity(hole, community, max(1, opponents), 200)

        # Pot geometry sizing based on street
        sizing = {0: 0.5, 3: 0.6, 4: 0.75, 5: 1.0}.get(street, 0.6)

        if equity > 0.70:
            # Value bet
            bet = min(int(pot * sizing), chips)
            return ('raise', max(bet, call_amt + 1))
        elif equity > 0.55:
            # Thin value / protection
            if call_amt == 0:
                bet = min(int(pot * sizing * 0.6), chips)
                return ('raise', max(bet, 1))
            if call_amt < pot * 0.5:
                return ('call', min(call_amt, chips))
            return ('fold', 0)
        elif equity > 0.40:
            # Marginal — check/call small bets
            if call_amt == 0:
                return ('check', 0)
            if call_amt < pot * 0.3:
                return ('call', min(call_amt, chips))
            return ('fold', 0)
        elif equity > 0.25 and random.random() < 0.25:
            # Bluff with some frequency (balanced range)
            if call_amt == 0:
                bet = min(int(pot * sizing * 0.8), chips)
                return ('raise', max(bet, 1))
            return ('fold', 0)
        else:
            if call_amt == 0:
                return ('check', 0)
            return ('fold', 0)


class ShortStackPushFoldStrategy(Strategy):
    """
    Adapts to stack depth. Deep stacked plays methodically;
    short stacked (<20BB) switches to push-fold ICM-aware mode.
    """
    name = "ShortStackPushFold"
    BIG_BLIND = 20

    def decide(self, player, state):
        hole = player['hole']
        community = state['community']
        pot = state['pot']
        call_amt = state['call_amount']
        chips = player['chips']
        opponents = state['active_players'] - 1

        bb = self.BIG_BLIND
        effective_stack = chips / max(bb, 1)

        # Short stack: push or fold only
        if effective_stack <= 15:
            strength = preflop_strength(hole) if not community else hand_category(hole, community)
            push_threshold = max(0.3, 0.6 - effective_stack * 0.02)
            if strength >= push_threshold:
                return ('raise', chips)
            if call_amt == 0:
                return ('check', 0)
            return ('fold', 0)

        # Medium stack: standard play
        if not community:
            strength = preflop_strength(hole)
            if strength < 0.45:
                if call_amt == 0:
                    return ('check', 0)
                return ('fold', 0)
            elif strength < 0.65:
                return ('call', min(call_amt, chips))
            else:
                return ('raise', min(int(pot * 2 + call_amt * 2.5), chips))
        else:
            equity = estimate_equity(hole, community, max(1, opponents), 150)
            if equity > 0.60:
                bet = min(int(pot * 0.7), chips)
                return ('raise', max(bet, call_amt + 1))
            elif equity > 0.40:
                if call_amt <= pot * 0.35:
                    return ('call', min(call_amt, chips))
                return ('fold', 0)
            else:
                if call_amt == 0:
                    return ('check', 0)
                return ('fold', 0)


class PositionAwareStrategy(Strategy):
    """
    Exploits position aggressively. Steals from late position,
    tight from early, applies squeeze plays, barrel-heavy in position.
    """
    name = "PositionAware"

    def decide(self, player, state):
        hole = player['hole']
        community = state['community']
        pot = state['pot']
        call_amt = state['call_amount']
        chips = player['chips']
        position = state.get('position', 3)   # 0=BTN/best, higher=worse
        num_players = state.get('active_players', 4)
        opponents = num_players - 1

        # Relative position quality (0=best, 1=worst)
        pos_quality = 1.0 - (position / max(num_players - 1, 1))

        if not community:
            strength = preflop_strength(hole)
            # Steal range widens in late position
            play_threshold = 0.65 - pos_quality * 0.25
            raise_threshold = 0.75 - pos_quality * 0.20

            if strength < play_threshold:
                if call_amt == 0 and pos_quality > 0.6:
                    # Blind steal attempt
                    if random.random() < 0.4:
                        return ('raise', min(int(pot * 2.5), chips))
                if call_amt == 0:
                    return ('check', 0)
                return ('fold', 0)
            elif strength < raise_threshold:
                return ('call', min(call_amt, chips))
            else:
                raise_size = int(pot * (1.5 + pos_quality * 1.5) + call_amt * 2)
                return ('raise', min(raise_size, chips))

        equity = estimate_equity(hole, community, max(1, opponents), 180)
        street = len(community)

        # In position: bet more aggressively on all streets
        if pos_quality > 0.6:
            if equity > 0.45:
                sizing = 0.5 + pos_quality * 0.5
                bet = min(int(pot * sizing), chips)
                return ('raise', max(bet, call_amt + 1))
            elif equity > 0.30 and random.random() < (0.15 + pos_quality * 0.20):
                # Barrel bluff in position
                bet = min(int(pot * 0.55), chips)
                if call_amt == 0:
                    return ('raise', max(bet, 1))
            if call_amt == 0:
                return ('check', 0)
            if call_amt < pot * 0.4:
                return ('call', min(call_amt, chips))
            return ('fold', 0)
        else:
            # Out of position: tighter
            if equity > 0.60:
                bet = min(int(pot * 0.65), chips)
                return ('raise', max(bet, call_amt + 1))
            if equity > 0.42:
                if call_amt <= pot * 0.35:
                    return ('call', min(call_amt, chips))
                return ('fold', 0)
            if call_amt == 0:
                return ('check', 0)
            return ('fold', 0)


# ─────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND = 10
BIG_BLIND = 20


def deal_hands(deck, n):
    random.shuffle(deck)
    hands = []
    for i in range(n):
        hands.append([deck[i*2], deck[i*2+1]])
    return hands, deck[n*2:]


def run_betting_round(players, community, pot, current_bet, dealer_idx):
    """
    Single betting round. Returns updated pot.
    players: list of dicts with keys: chips, hole, active, strategy, name, position
    """
    n = len(players)
    # Determine acting order starting left of dealer
    order = [(dealer_idx + 1 + i) % n for i in range(n)]
    order = [i for i in order if players[i]['active'] and players[i]['chips'] > 0]

    contributions = {i: 0 for i in range(n)}
    # Account for blinds already in pot
    if current_bet > 0:
        contributions[order[0]] = SMALL_BLIND if len(order) >= 2 else 0
        if len(order) >= 2:
            contributions[order[1]] = BIG_BLIND

    last_raiser = None
    acted = set()
    i_ptr = 0

    while True:
        if not order:
            break
        # Check if action is closed
        active_with_chips = [i for i in order if players[i]['active'] and players[i]['chips'] > 0]
        if len(active_with_chips) == 0:
            break
        all_acted = all(
            (i in acted or players[i]['chips'] == 0)
            for i in active_with_chips
        )
        max_contrib = max(contributions[i] for i in range(n) if players[i]['active'])
        all_even = all(
            contributions[i] == max_contrib or players[i]['chips'] == 0
            for i in active_with_chips
        )
        if all_acted and all_even:
            break

        idx = order[i_ptr % len(order)]
        i_ptr += 1

        p = players[idx]
        if not p['active'] or p['chips'] == 0:
            continue
        if idx in acted and contributions[idx] == max_contrib:
            continue

        call_amount = max(0, max_contrib - contributions[idx])
        call_amount = min(call_amount, p['chips'])

        state = {
            'community': community,
            'pot': pot,
            'call_amount': call_amount,
            'active_players': sum(1 for pl in players if pl['active']),
            'position': p.get('position', 2),
        }

        action, amount = p['strategy'].decide(p, state)

        if action == 'fold':
            p['active'] = False
        elif action == 'check':
            acted.add(idx)
        elif action == 'call':
            actual = min(call_amount, p['chips'])
            p['chips'] -= actual
            contributions[idx] += actual
            pot += actual
            acted.add(idx)
        elif action == 'raise':
            total_commit = min(amount + call_amount, p['chips'])
            # Must at least call first
            actual_call = min(call_amount, p['chips'])
            raise_on_top = total_commit - actual_call
            if raise_on_top <= 0:
                # treat as call
                p['chips'] -= actual_call
                contributions[idx] += actual_call
                pot += actual_call
                acted.add(idx)
            else:
                p['chips'] -= total_commit
                contributions[idx] += total_commit
                pot += total_commit
                max_contrib = contributions[idx]
                last_raiser = idx
                acted = {idx}  # everyone else must act again

        # Safety: exit if only one active player
        if sum(1 for pl in players if pl['active']) <= 1:
            break

    return pot


def showdown(players, community, pot):
    """Determine winner(s) and distribute pot."""
    active = [p for p in players if p['active']]
    if len(active) == 0:
        return
    if len(active) == 1:
        active[0]['chips'] += pot
        return

    best_rank = None
    winners = []
    for p in active:
        r = hand_rank(p['hole'] + community)
        if best_rank is None or r > best_rank:
            best_rank = r
            winners = [p]
        elif r == best_rank:
            winners.append(p)

    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        w['chips'] += share
    winners[0]['chips'] += remainder


def play_hand(players, dealer_idx):
    """Play a single hand of Hold'em."""
    deck = make_deck()
    n = len(players)

    # Reset active flags (only for players with chips)
    for p in players:
        p['active'] = p['chips'] > 0

    alive = [p for p in players if p['active']]
    if len(alive) < 2:
        return dealer_idx

    # Post blinds
    order = [(dealer_idx + 1 + i) % n for i in range(n)]
    alive_order = [i for i in order if players[i]['active']]

    sb_idx = alive_order[0]
    bb_idx = alive_order[1] if len(alive_order) > 1 else alive_order[0]

    sb = min(SMALL_BLIND, players[sb_idx]['chips'])
    bb = min(BIG_BLIND, players[bb_idx]['chips'])
    players[sb_idx]['chips'] -= sb
    players[bb_idx]['chips'] -= bb
    pot = sb + bb

    # Deal hole cards
    random.shuffle(deck)
    community_deck = deck[n*2:]
    for i, p in enumerate(players):
        if p['active']:
            idx_in_deck = [j for j, pl in enumerate(players) if pl['active']].index(
                [j for j, pl in enumerate(players) if pl is p][0]
            )
        p['hole'] = []

    active_idxs = [i for i in range(n) if players[i]['active']]
    for slot, idx in enumerate(active_idxs):
        players[idx]['hole'] = [deck[slot*2], deck[slot*2+1]]

    remaining_deck = deck[len(active_idxs)*2:]

    # Assign positions (0=BTN best, ascending worse)
    for slot, idx in enumerate(active_idxs):
        players[idx]['position'] = slot

    community = []

    # Pre-flop betting
    pot = run_betting_round(players, community, pot, BIG_BLIND, dealer_idx)

    active_after = [p for p in players if p['active']]
    if len(active_after) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % n

    # Flop
    community = list(remaining_deck[:3])
    remaining_deck = remaining_deck[3:]
    pot = run_betting_round(players, community, pot, 0, dealer_idx)

    active_after = [p for p in players if p['active']]
    if len(active_after) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % n

    # Turn
    community.append(remaining_deck[0])
    remaining_deck = remaining_deck[1:]
    pot = run_betting_round(players, community, pot, 0, dealer_idx)

    active_after = [p for p in players if p['active']]
    if len(active_after) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % n

    # River
    community.append(remaining_deck[0])
    pot = run_betting_round(players, community, pot, 0, dealer_idx)

    showdown(players, community, pot)
    return (dealer_idx + 1) % n


def run_tournament(strategies):
    """Run a single tournament to completion. Returns index of winner."""
    players = []
    for i, strat in enumerate(strategies):
        players.append({
            'name': f"P{i+1}_{strat.name}",
            'chips': STARTING_CHIPS,
            'strategy': strat,
            'active': True,
            'hole': [],
            'position': i,
        })

    dealer_idx = 0
    max_hands = 2000  # safety cap

    for _ in range(max_hands):
        alive = [p for p in players if p['chips'] > 0]
        if len(alive) <= 1:
            break
        dealer_idx = play_hand(players, dealer_idx)

    # Find winner (most chips)
    winner = max(players, key=lambda p: p['chips'])
    return players.index(winner), winner['name']


# ─────────────────────────────────────────────
# MAIN SIMULATION
# ─────────────────────────────────────────────

def run_simulations(n=100):
    strategies = [
        AllInStrategy(),           # Player 1
        TightAggressiveStrategy(), # Player 2
        LoosePassiveStrategy(),    # Player 3
        GtoApproximatorStrategy(), # Player 4
        ShortStackPushFoldStrategy(), # Player 5
        PositionAwareStrategy(),   # Player 6
    ]

    win_counts = Counter()
    name_map = {i: strategies[i].name for i in range(len(strategies))}

    print(f"\n{'='*60}")
    print("  TEXAS HOLD'EM TOURNAMENT SIMULATOR")
    print(f"  {n} Tournaments | 6 Players | {STARTING_CHIPS} chips each")
    print(f"{'='*60}")
    print("\nStrategies:")
    for i, s in enumerate(strategies):
        marker = " <<< THE ABSOLUTE UNIT" if i == 0 else ""
        print(f"  P{i+1}: {s.name}{marker}")
    print()

    for sim in range(n):
        winner_idx, winner_name = run_tournament(list(strategies))
        win_counts[winner_idx] += 1
        if (sim + 1) % 10 == 0:
            print(f"  Simulations completed: {sim+1}/{n}", end='\r')

    print(f"\n  Done! {n} tournaments simulated.              \n")
    return win_counts, name_map, len(strategies)


def print_histogram(win_counts, name_map, n_players, total):
    print(f"{'='*60}")
    print("  WINNER WINNER CHICKEN DINNER — HISTOGRAM")
    print(f"  Total tournaments: {total}")
    print(f"{'='*60}\n")

    bar_width = 40
    sorted_players = sorted(range(n_players), key=lambda i: win_counts.get(i, 0), reverse=True)

    for idx in sorted_players:
        count = win_counts.get(idx, 0)
        pct = count / total * 100
        bar_len = int(bar_len_f := (count / total * bar_width))
        bar = '█' * bar_len + ('▌' if bar_len_f - bar_len >= 0.5 else '')
        marker = " ← YOLO KING" if idx == 0 else ""
        label = f"P{idx+1} {name_map[idx]:<25}"
        print(f"  {label} {bar:<{bar_width}} {count:>3} wins ({pct:5.1f}%){marker}")

    print(f"\n{'='*60}")

    yolo_wins = win_counts.get(0, 0)
    yolo_pct = yolo_wins / total * 100
    others = {i: win_counts.get(i, 0) for i in range(1, n_players)}
    best_strat_idx = max(others, key=others.get)
    best_strat_pct = others[best_strat_idx] / total * 100

    print("\n  VERDICT:")
    if yolo_pct > best_strat_pct:
        margin = yolo_pct - best_strat_pct
        print(f"  YOLO ALL-IN obliterates the fancy algorithms by {margin:.1f}%!")
        print(f"  The quants are crying. The poker bots are uninstalled.")
        print(f"  suflair gpt has been HUMILIATED. 💀")
    else:
        margin = best_strat_pct - yolo_pct
        print(f"  The elaborate strategies edge out YOLO by {margin:.1f}%.")
        print(f"  P1 YOLO won {yolo_pct:.1f}% — still respectable chaos.")
        print(f"  (suflair gpt coping and seething regardless)")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    random.seed(42)
    win_counts, name_map, n_players = run_simulations(n_sims)
    print_histogram(win_counts, name_map, n_players, n_sims)
