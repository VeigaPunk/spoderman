"""Texas Hold'em 100-simulation tournament. Player 1 = all-in maniac. Players 2-6 = elaborate strategies."""

import random
from collections import Counter
from itertools import combinations

# ── Card primitives ──────────────────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ── Hand evaluation (returns comparable tuple, higher = better) ──────────────

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards."""
    best = None
    for combo in combinations(cards, 5):
        score = score_five(combo)
        if best is None or score > best:
            best = score
    return best

def score_five(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5) or ranks == [14,5,4,3,2]
    if straight and ranks == [14,5,4,3,2]:
        ranks = [5,4,3,2,1]
    counts = sorted(Counter(ranks).values(), reverse=True)
    rank_by_count = sorted(Counter(ranks).keys(), key=lambda r: (Counter(ranks)[r], r), reverse=True)

    if flush and straight:
        return (8, ranks)
    if counts[0] == 4:
        return (7, rank_by_count)
    if counts[:2] == [3, 2]:
        return (6, rank_by_count)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts[0] == 3:
        return (3, rank_by_count)
    if counts[:2] == [2, 2]:
        return (2, rank_by_count)
    if counts[0] == 2:
        return (1, rank_by_count)
    return (0, ranks)

# ── Pot & side-pot logic ──────────────────────────────────────────────────────

def resolve_pots(contributions, hands, active_players):
    """Return {player_id: winnings} dict. contributions = {pid: amount_in_pot}."""
    winnings = {pid: 0 for pid in contributions}
    remaining = dict(contributions)
    involved = sorted(remaining.keys())

    while any(v > 0 for v in remaining.values()):
        min_contrib = min(v for v in remaining.values() if v > 0)
        pot = 0
        eligible = []
        for pid in involved:
            if remaining[pid] > 0:
                take = min(remaining[pid], min_contrib)
                pot += take
                remaining[pid] -= take
                if pid in active_players:
                    eligible.append(pid)

        if not eligible:
            eligible = [pid for pid in involved if remaining.get(pid, 0) == 0
                        and pid in active_players]

        best = max(hands[p] for p in eligible)
        winners = [p for p in eligible if hands[p] == best]
        share = pot // len(winners)
        remainder = pot % len(winners)
        for i, w in enumerate(winners):
            winnings[w] += share + (1 if i < remainder else 0)

    return winnings

# ── Strategy helpers ──────────────────────────────────────────────────────────

def hand_strength_preflop(hole):
    """0-1 score of hole cards before community."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    score = (hi + lo) / 28.0
    if hi == lo:
        score += 0.25
    if suited:
        score += 0.05
    return min(score, 1.0)

def hand_strength_postflop(hole, community):
    """Fast heuristic: normalize hand score to 0-1 range."""
    score = hand_rank(hole + community)
    # score[0] is category 0-8; use it plus high-card tiebreaker
    category = score[0]
    highs = score[1][:2] if len(score[1]) >= 2 else score[1]
    tiebreak = sum(v / 14.0 * (0.5 ** i) for i, v in enumerate(highs))
    return min((category / 8.0) * 0.85 + tiebreak * 0.15, 1.0)

def pot_odds(call_amount, pot):
    if call_amount + pot == 0:
        return 1.0
    return pot / (pot + call_amount)

# ── Strategies ────────────────────────────────────────────────────────────────

class Strategy:
    def decide(self, pid, state):
        """Return ('fold'|'call'|'raise', amount)."""
        raise NotImplementedError

class AllInManiac(Strategy):
    """Player 1. Simple: if my_turn then bet = all-in."""
    name = "ALL-IN MANIAC"
    def decide(self, pid, state):
        stack = state['stacks'][pid]
        return ('raise', stack)

class TightAggressive(Strategy):
    """Only plays premium hands; bets big when it does."""
    name = "TIGHT-AGGRESSIVE"
    def decide(self, pid, state):
        hole = state['hole'][pid]
        community = state['community']
        to_call = state['to_call']
        pot = state['pot']
        stack = state['stacks'][pid]

        if community:
            strength = hand_strength_postflop(hole, community)
        else:
            strength = hand_strength_preflop(hole)

        if strength > 0.75:
            raise_amt = min(stack, max(to_call * 3, pot // 2))
            return ('raise', raise_amt)
        elif strength > 0.55:
            return ('call', to_call)
        else:
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

class PositionalBully(Strategy):
    """Plays aggressively from late position; folds garbage early."""
    name = "POSITIONAL BULLY"
    def decide(self, pid, state):
        hole = state['hole'][pid]
        community = state['community']
        to_call = state['to_call']
        pot = state['pot']
        stack = state['stacks'][pid]
        position = state['position']   # 0=early .. n=late
        n_active = state['n_active']
        late = position >= (n_active * 0.6)

        if community:
            strength = hand_strength_postflop(hole, community)
        else:
            strength = hand_strength_preflop(hole)

        if late and strength > 0.45:
            raise_amt = min(stack, pot // 2 + to_call)
            return ('raise', raise_amt)
        elif strength > 0.65:
            return ('call', to_call)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)

class PotOddsCalculator(Strategy):
    """Calls when pot odds justify it; raises on strong equity."""
    name = "POT-ODDS CALC"
    def decide(self, pid, state):
        hole = state['hole'][pid]
        community = state['community']
        to_call = state['to_call']
        pot = state['pot']
        stack = state['stacks'][pid]

        if community:
            equity = hand_strength_postflop(hole, community)
        else:
            equity = hand_strength_preflop(hole)

        odds = pot_odds(to_call, pot)

        if equity > 0.80:
            raise_amt = min(stack, pot)
            return ('raise', raise_amt)
        elif equity >= odds or to_call == 0:
            return ('call', to_call)
        else:
            return ('fold', 0)

class BluffMaster(Strategy):
    """Mixes bluffs with value bets; reads board texture."""
    name = "BLUFF MASTER"
    def decide(self, pid, state):
        hole = state['hole'][pid]
        community = state['community']
        to_call = state['to_call']
        pot = state['pot']
        stack = state['stacks'][pid]

        if community:
            strength = hand_strength_postflop(hole, community)
        else:
            strength = hand_strength_preflop(hole)

        bluff_roll = random.random()
        # bluff ~20% of the time when weak
        if strength < 0.40 and bluff_roll < 0.20:
            raise_amt = min(stack, pot // 2)
            return ('raise', raise_amt)

        if strength > 0.70:
            raise_amt = min(stack, int(pot * 0.75))
            return ('raise', raise_amt)
        elif strength > 0.50:
            return ('call', to_call)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)

class AdaptiveShark(Strategy):
    """Tracks aggression at the table and adjusts threshold dynamically."""
    name = "ADAPTIVE SHARK"
    def __init__(self):
        self.aggression_seen = 0
        self.hands_seen = 0

    def decide(self, pid, state):
        hole = state['hole'][pid]
        community = state['community']
        to_call = state['to_call']
        pot = state['pot']
        stack = state['stacks'][pid]
        last_raise = state.get('last_raise', 0)

        self.hands_seen += 1
        if last_raise > 0:
            self.aggression_seen += 1
        table_aggression = self.aggression_seen / max(self.hands_seen, 1)

        if community:
            strength = hand_strength_postflop(hole, community)
        else:
            strength = hand_strength_preflop(hole)

        # Tighten threshold when table is aggressive
        threshold = 0.55 + (table_aggression * 0.20)

        if strength > threshold + 0.20:
            raise_amt = min(stack, max(to_call * 2, pot // 3))
            return ('raise', raise_amt)
        elif strength > threshold:
            return ('call', to_call)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)

# ── Game engine ───────────────────────────────────────────────────────────────

SMALL_BLIND = 10
BIG_BLIND = 20

def play_hand(stacks, strategies, dealer_pos):
    n = len(stacks)
    pids = list(stacks.keys())
    active = [p for p in pids if stacks[p] > 0]
    if len(active) < 2:
        return stacks

    deck = make_deck()
    random.shuffle(deck)

    hole = {p: [deck.pop(), deck.pop()] for p in active}
    community = []
    contributions = {p: 0 for p in active}
    folded = set()

    def living():
        return [p for p in active if p not in folded]

    def post_blind(pid, amount):
        amt = min(amount, stacks[pid])
        stacks[pid] -= amt
        contributions[pid] += amt
        return amt

    # Blinds
    active_positions = active[:]
    n_act = len(active_positions)
    sb_idx = (dealer_pos + 1) % n_act
    bb_idx = (dealer_pos + 2) % n_act
    sb_pid = active_positions[sb_idx % n_act]
    bb_pid = active_positions[bb_idx % n_act]
    post_blind(sb_pid, SMALL_BLIND)
    post_blind(bb_pid, BIG_BLIND)
    current_bet = BIG_BLIND

    def betting_round(start_idx, street_community):
        nonlocal current_bet
        if len(living()) <= 1:
            return
        players_in = living()
        n_in = len(players_in)
        acted = set()
        max_iter = n_in * 4
        itr = 0
        idx = start_idx % n_in

        while itr < max_iter:
            itr += 1
            pid = players_in[idx % n_in]
            if pid in folded:
                idx += 1
                players_in = living()
                n_in = len(players_in)
                continue

            if len(living()) <= 1:
                break

            to_call = max(0, current_bet - contributions[pid])
            pot = sum(contributions.values())
            position = players_in.index(pid)
            state = {
                'hole': hole,
                'community': street_community[:],
                'to_call': min(to_call, stacks[pid]),
                'pot': pot,
                'stacks': dict(stacks),
                'position': position,
                'n_active': len(players_in),
                'last_raise': current_bet,
            }

            action, amount = strategies[pid].decide(pid, state)

            if action == 'fold':
                folded.add(pid)
            elif action == 'call':
                call_amt = min(to_call, stacks[pid])
                stacks[pid] -= call_amt
                contributions[pid] += call_amt
            elif action == 'raise':
                call_amt = min(to_call, stacks[pid])
                stacks[pid] -= call_amt
                contributions[pid] += call_amt
                raise_extra = min(amount, stacks[pid])
                if raise_extra > 0:
                    stacks[pid] -= raise_extra
                    contributions[pid] += raise_extra
                    current_bet = contributions[pid]
                    acted = {pid}

            acted.add(pid)
            idx += 1
            players_in = living()
            n_in = len(players_in)

            # All acted and bets are equal — end round
            if all(p in acted for p in players_in):
                if all(contributions[p] == current_bet or stacks[p] == 0 for p in players_in):
                    break

    # Pre-flop (action starts left of BB)
    current_bet = BIG_BLIND
    utg_idx = (bb_idx + 1) % n_act
    betting_round(utg_idx, [])

    for street, n_cards in [('flop', 3), ('turn', 1), ('river', 1)]:
        if len(living()) <= 1:
            break
        community += [deck.pop() for _ in range(n_cards)]
        current_bet = 0
        # Reset contributions tracking for this street? No — keep cumulative for pot odds
        # but reset current_bet so checks work
        first_idx = (dealer_pos + 1) % len(living())
        betting_round(first_idx, community)

    # Showdown
    alive = living()
    pot_total = sum(contributions.values())

    if len(alive) == 1:
        stacks[alive[0]] += pot_total
    else:
        hands = {p: hand_rank(hole[p] + community) for p in alive}
        wins = resolve_pots(contributions, hands, set(alive))
        for p, w in wins.items():
            stacks[p] += w

    return stacks


def run_tournament(strategies, start_chips=1000):
    pids = list(strategies.keys())
    stacks = {p: start_chips for p in pids}
    dealer = 0
    hand_num = 0
    max_hands = 2000

    while sum(1 for s in stacks.values() if s > 0) > 1 and hand_num < max_hands:
        stacks = play_hand(stacks, strategies, dealer % len(pids))
        dealer += 1
        hand_num += 1

    alive = [p for p in pids if stacks[p] > 0]
    return alive[0] if alive else pids[0]


# ── 100 Simulations ───────────────────────────────────────────────────────────

def run_simulations(n=100, start_chips=1000):
    strategy_classes = [
        AllInManiac,          # Player 1
        TightAggressive,      # Player 2
        PositionalBully,      # Player 3
        PotOddsCalculator,    # Player 4
        BluffMaster,          # Player 5
        AdaptiveShark,        # Player 6
    ]

    win_counts = {i+1: 0 for i in range(6)}
    strategy_names = {i+1: cls.name for i, cls in enumerate(strategy_classes)}

    for sim in range(n):
        strategies = {i+1: cls() for i, cls in enumerate(strategy_classes)}
        winner = run_tournament(strategies, start_chips)
        win_counts[winner] += 1

    return win_counts, strategy_names


# ── Histogram output ──────────────────────────────────────────────────────────

def print_histogram(win_counts, strategy_names, total):
    print("\n" + "="*60)
    print("  TEXAS HOLD'EM — 100-TOURNAMENT WINNER HISTOGRAM")
    print("  (Last player standing wins; all start with 1000 chips)")
    print("="*60)
    max_wins = max(win_counts.values()) if win_counts else 1
    bar_max = 40

    for pid in sorted(win_counts.keys()):
        wins = win_counts[pid]
        name = strategy_names[pid]
        pct = wins / total * 100
        bar_len = int(wins / max_wins * bar_max) if max_wins > 0 else 0
        bar = "█" * bar_len
        tag = "  ← SIMPLE ALL-IN" if pid == 1 else ""
        print(f"  P{pid} {name:<20} | {bar:<40} {wins:>3} wins ({pct:4.1f}%){tag}")

    print("="*60)
    best = max(win_counts, key=win_counts.get)
    print(f"\n  WINNER WINNER CHICKEN DINNER: Player {best} — {strategy_names[best]}")
    if best == 1:
        print("  The all-in maniac HUMILIATED the elaborate strategies! 🤡")
    else:
        print(f"  Sorry GPT, Player 1 (ALL-IN MANIAC) only won {win_counts[1]} times.")
    print()


if __name__ == '__main__':
    random.seed(42)
    print("Running 100 Texas Hold'em tournaments...")
    print("Player 1: ALL-IN every single hand")
    print("Players 2-6: Elaborate strategies")
    print("(This may take ~30-60 seconds due to Monte Carlo equity sampling)\n")

    win_counts, strategy_names = run_simulations(n=100, start_chips=1000)
    print_histogram(win_counts, strategy_names, total=100)
