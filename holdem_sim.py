"""
Texas Hold'em Poker Simulation
Player 1: The Maniac (all-in every turn)
Players 2-6: Elaborate strategy bots
100 tournament simulations, histogram of winners
"""

import random
from collections import Counter, defaultdict
from itertools import combinations
import sys

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ---------------------------------------------------------------------------
# Hand evaluator (7-card best-5)
# ---------------------------------------------------------------------------

HAND_NAMES = ['High Card','One Pair','Two Pair','Three of a Kind',
              'Straight','Flush','Full House','Four of a Kind',
              'Straight Flush','Royal Flush']

def _hand_rank(five):
    ranks = sorted([RANK_VAL[c[0]] for c in five], reverse=True)
    suits = [c[1] for c in five]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5)
    # Wheel straight: A-2-3-4-5
    if set(ranks) == {12, 0, 1, 2, 3}:
        straight = True
        ranks = [3, 2, 1, 0, -1]  # treat ace as low

    counts = sorted(Counter(ranks).values(), reverse=True)
    rank_groups = sorted(Counter(ranks).keys(),
                         key=lambda r: (Counter(ranks)[r], r), reverse=True)

    if straight and flush:
        cat = 9 if ranks[0] == 12 else 8
    elif counts[0] == 4:
        cat = 7
    elif counts[:2] == [3, 2]:
        cat = 6
    elif flush:
        cat = 5
    elif straight:
        cat = 4
    elif counts[0] == 3:
        cat = 3
    elif counts[:2] == [2, 2]:
        cat = 2
    elif counts[0] == 2:
        cat = 1
    else:
        cat = 0
    return (cat,) + tuple(rank_groups)

def best_hand_score(cards):
    """Return the best 5-card score from up to 7 cards."""
    return max(_hand_rank(h) for h in combinations(cards, 5))

# ---------------------------------------------------------------------------
# Monte Carlo hand strength estimator
# ---------------------------------------------------------------------------

def estimate_hand_strength(hole, community, num_opponents, samples=200):
    """Win probability via Monte Carlo rollout."""
    wins = 0
    deck = [c for c in make_deck() if c not in hole and c not in community]
    needed = 5 - len(community)
    for _ in range(samples):
        d = deck[:]
        random.shuffle(d)
        board = community + d[:needed]
        my_score = best_hand_score(hole + board)
        opp_scores = [best_hand_score(d[needed + i*2: needed + i*2 + 2] + board)
                      for i in range(num_opponents)]
        if all(my_score >= s for s in opp_scores):
            wins += 1
    return wins / samples

# ---------------------------------------------------------------------------
# Game state helpers
# ---------------------------------------------------------------------------

def classify_hole(hole):
    """Return (high_rank_val, low_rank_val, suited)."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    hi, lo = max(r1, r2), min(r1, r2)
    suited = hole[0][1] == hole[1][1]
    return hi, lo, suited

def preflop_strength(hole):
    """Quick preflop hand strength 0-1."""
    hi, lo, suited = classify_hole(hole)
    score = (hi + lo) / 24.0
    if hi == lo:
        score += 0.15 + hi * 0.01
    if suited:
        score += 0.05
    if hi == 12:
        score += 0.05
    return min(score, 1.0)

# ---------------------------------------------------------------------------
# STRATEGY 1: The GTO Scholar
# Approximates GTO by mixing frequencies based on hand strength ranges
# ---------------------------------------------------------------------------

class GTOScholar:
    name = "GTO Scholar"

    def __init__(self):
        self.bluff_threshold = 0.15   # bluff with weakest hands sometimes
        self.value_threshold = 0.72   # pure value above here

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active):
        n_opp = num_active - 1
        if n_opp == 0:
            return ('call', to_call)

        if street == 'preflop':
            strength = preflop_strength(hole)
        else:
            strength = estimate_hand_strength(hole, community, n_opp, samples=150)

        # Position bonus
        pos_bonus = position / max(num_active - 1, 1) * 0.06

        # GTO mixing: sometimes call/fold on borderline hands
        rand = random.random()
        effective_strength = strength + pos_bonus

        if to_call == 0:
            if effective_strength > 0.55:
                bet = int(pot * random.uniform(0.5, 0.9))
                return ('raise', min(bet, my_stack))
            elif effective_strength > 0.3:
                return ('check', 0)
            else:
                if rand < 0.25:  # bluff 25% of the time
                    return ('raise', int(pot * 0.6))
                return ('check', 0)
        else:
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
            if effective_strength > self.value_threshold:
                raise_size = int(to_call * random.uniform(2.2, 3.5))
                return ('raise', min(raise_size, my_stack))
            elif effective_strength > pot_odds + 0.05:
                return ('call', to_call)
            elif effective_strength < self.bluff_threshold and rand < 0.18:
                return ('raise', min(int(pot * 0.8), my_stack))
            else:
                return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 2: The Position Predator
# Hyper-aggressive in late position, tight in early position
# ---------------------------------------------------------------------------

class PositionPredator:
    name = "Position Predator"

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active):
        n_opp = num_active - 1
        if n_opp == 0:
            return ('call', to_call)

        late = position >= (num_active * 0.6)
        btn = position == num_active - 1

        if street == 'preflop':
            strength = preflop_strength(hole)
        else:
            strength = estimate_hand_strength(hole, community, n_opp, samples=150)

        # In position: steal pots aggressively
        if btn:
            strength += 0.18
        elif late:
            strength += 0.10

        if to_call == 0:
            if strength > 0.45:
                # Bigger bets in position
                multiplier = 0.8 if late else 0.4
                bet = int(pot * multiplier)
                return ('raise', max(1, min(bet, my_stack)))
            return ('check', 0)
        else:
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
            if strength > 0.65 and late:
                return ('raise', min(int(to_call * 2.8), my_stack))
            elif strength > pot_odds + 0.08:
                return ('call', to_call)
            else:
                return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 3: The Stack Bully
# Pressures short stacks, plays conservatively against big stacks
# ---------------------------------------------------------------------------

class StackBully:
    name = "Stack Bully"

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active):
        n_opp = num_active - 1
        if n_opp == 0:
            return ('call', to_call)

        avg_stack = sum(active_stacks) / len(active_stacks) if active_stacks else my_stack
        am_big = my_stack > avg_stack * 1.3
        short_stacks = sum(1 for s in active_stacks if s < my_stack * 0.4)

        if street == 'preflop':
            strength = preflop_strength(hole)
        else:
            strength = estimate_hand_strength(hole, community, n_opp, samples=150)

        # Boost aggression when we can bully
        if am_big and short_stacks > 0:
            strength += 0.12
        # Play tight when we are the short stack
        if my_stack < avg_stack * 0.5:
            strength -= 0.10

        if to_call == 0:
            if strength > 0.50:
                # Apply max pressure on short stacks
                if am_big and short_stacks > 0:
                    return ('raise', min(int(pot * 1.5), my_stack))
                return ('raise', min(int(pot * 0.6), my_stack))
            return ('check', 0)
        else:
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
            if strength > 0.70:
                return ('raise', min(int(to_call * 3), my_stack))
            elif strength > pot_odds:
                return ('call', to_call)
            else:
                return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 4: The Pot Control Surgeon
# Keeps pots small with medium hands, big with nutted hands
# ---------------------------------------------------------------------------

class PotControlSurgeon:
    name = "Pot Control Surgeon"

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active):
        n_opp = num_active - 1
        if n_opp == 0:
            return ('call', to_call)

        if street == 'preflop':
            strength = preflop_strength(hole)
        else:
            strength = estimate_hand_strength(hole, community, n_opp, samples=150)

        is_nuts = strength > 0.88
        is_medium = 0.50 < strength <= 0.88
        is_weak = strength <= 0.50

        if to_call == 0:
            if is_nuts:
                # Go for max value
                bet = int(pot * random.uniform(0.75, 1.1))
                return ('raise', min(bet, my_stack))
            elif is_medium:
                # Pot control: check or small bet
                if random.random() < 0.35:
                    return ('raise', min(int(pot * 0.25), my_stack))
                return ('check', 0)
            else:
                # Bluff selectively on late streets
                if street == 'river' and random.random() < 0.20:
                    return ('raise', min(int(pot * 0.65), my_stack))
                return ('check', 0)
        else:
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
            if is_nuts:
                return ('raise', min(int(to_call * 2.5), my_stack))
            elif is_medium and strength > pot_odds + 0.10:
                return ('call', to_call)
            elif is_weak:
                return ('fold', 0)
            else:
                return ('call', to_call) if strength > pot_odds else ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 5: The Reads Machine
# Models opponent tendencies using observed bet patterns
# ---------------------------------------------------------------------------

class ReadsMachine:
    name = "Reads Machine"

    def __init__(self):
        self.opp_aggression = defaultdict(lambda: 0.5)  # 0=passive, 1=aggressive
        self.opp_vpip = defaultdict(lambda: 0.5)        # voluntarily put in pot

    def update_read(self, player_id, action, amount, pot):
        if action == 'raise':
            self.opp_aggression[player_id] = min(1.0, self.opp_aggression[player_id] + 0.08)
        elif action == 'fold':
            self.opp_aggression[player_id] = max(0.0, self.opp_aggression[player_id] - 0.05)
        if action in ('call', 'raise'):
            self.opp_vpip[player_id] = min(1.0, self.opp_vpip[player_id] + 0.05)

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active, opp_ids=None):
        n_opp = num_active - 1
        if n_opp == 0:
            return ('call', to_call)

        if street == 'preflop':
            strength = preflop_strength(hole)
        else:
            strength = estimate_hand_strength(hole, community, n_opp, samples=150)

        # Adjust based on opponents' tendencies
        if opp_ids:
            avg_agg = sum(self.opp_aggression[i] for i in opp_ids) / len(opp_ids)
            avg_vpip = sum(self.opp_vpip[i] for i in opp_ids) / len(opp_ids)
            # Against aggressive players: tighten up, trap more
            if avg_agg > 0.65:
                strength -= 0.05  # require more equity to commit
            # Against loose players: thin value bet more
            if avg_vpip > 0.65:
                strength += 0.06

        if to_call == 0:
            if strength > 0.52:
                bet = int(pot * random.uniform(0.55, 0.85))
                return ('raise', min(bet, my_stack))
            return ('check', 0)
        else:
            pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
            if strength > 0.68:
                return ('raise', min(int(to_call * 2.5), my_stack))
            elif strength > pot_odds + 0.05:
                return ('call', to_call)
            else:
                return ('fold', 0)

# ---------------------------------------------------------------------------
# STRATEGY 0 (Player 1): The Maniac — simple all-in every time
# ---------------------------------------------------------------------------

class TheManiac:
    name = "The Maniac (ALL-IN)"

    def decide(self, hole, community, pot, to_call, my_stack, active_stacks,
                position, street, num_active, **kwargs):
        if my_turn := True:
            bet = my_stack
        return ('raise', bet)

# ---------------------------------------------------------------------------
# Texas Hold'em Engine
# ---------------------------------------------------------------------------

BLINDS_START = 10

class PokerGame:
    def __init__(self, players, starting_chips=1000):
        self.players = players  # list of (name, strategy_obj)
        self.chips = {i: starting_chips for i in range(len(players))}
        self.dealer = 0
        self.hand_count = 0

    def play_hand(self):
        active = [i for i in range(len(self.players)) if self.chips[i] > 0]
        if len(active) < 2:
            return

        self.hand_count += 1
        n = len(active)

        # Blinds
        sb_idx = active[(self.dealer + 1) % n]
        bb_idx = active[(self.dealer + 2) % n]
        blinds = min(BLINDS_START, self.chips[sb_idx])
        bigblind = min(BLINDS_START * 2, self.chips[bb_idx])

        self.chips[sb_idx] -= blinds
        self.chips[bb_idx] -= bigblind
        pot = blinds + bigblind
        bets = {i: 0 for i in active}
        bets[sb_idx] = blinds
        bets[bb_idx] = bigblind

        # Deal
        deck = make_deck()
        random.shuffle(deck)
        hole_cards = {}
        for idx, pid in enumerate(active):
            hole_cards[pid] = [deck[idx * 2], deck[idx * 2 + 1]]
        community = []
        deck_pos = n * 2

        folded = set()

        def betting_round(street, first_actor_offset=0):
            nonlocal pot
            current_bets = {i: 0 for i in active if i not in folded}
            max_bet = 0
            if street == 'preflop':
                current_bets[sb_idx] = blinds
                current_bets[bb_idx] = bigblind
                max_bet = bigblind

            order = [active[(self.dealer + first_actor_offset + j) % n]
                     for j in range(n)]
            order = [p for p in order if p not in folded]

            acted = set()
            iterations = 0
            while iterations < 4 * len(order):
                iterations += 1
                any_action = False
                for pid in order:
                    if pid in folded:
                        continue
                    remaining = [p for p in active if p not in folded]
                    if len(remaining) <= 1:
                        return
                    to_call = max_bet - current_bets.get(pid, 0)
                    to_call = min(to_call, self.chips[pid])
                    if to_call < 0:
                        to_call = 0

                    # Skip if already matched and acted
                    if current_bets.get(pid, 0) >= max_bet and pid in acted:
                        continue

                    strat = self.players[pid][1]
                    opp_ids = [p for p in remaining if p != pid]
                    pos = order.index(pid) if pid in order else 0

                    kwargs = {}
                    if isinstance(strat, ReadsMachine):
                        kwargs['opp_ids'] = opp_ids

                    action, amount = strat.decide(
                        hole=hole_cards[pid],
                        community=community,
                        pot=pot,
                        to_call=to_call,
                        my_stack=self.chips[pid],
                        active_stacks=[self.chips[p] for p in opp_ids],
                        position=pos,
                        street=street,
                        num_active=len(remaining),
                        **kwargs
                    )

                    if action == 'fold':
                        folded.add(pid)
                        acted.add(pid)
                        any_action = True
                    elif action == 'check':
                        acted.add(pid)
                    elif action == 'call':
                        actual = min(to_call, self.chips[pid])
                        self.chips[pid] -= actual
                        current_bets[pid] = current_bets.get(pid, 0) + actual
                        pot += actual
                        acted.add(pid)
                    elif action == 'raise':
                        total_bet = min(amount, self.chips[pid])
                        if total_bet <= to_call:
                            # Treat as call
                            actual = min(to_call, self.chips[pid])
                            self.chips[pid] -= actual
                            current_bets[pid] = current_bets.get(pid, 0) + actual
                            pot += actual
                        else:
                            self.chips[pid] -= total_bet
                            current_bets[pid] = current_bets.get(pid, 0) + total_bet
                            pot += total_bet
                            max_bet = current_bets[pid]
                            acted = {pid}  # reset so others can re-act
                        acted.add(pid)
                        any_action = True

                    # Update reads for ReadsMachine players
                    for other_pid in active:
                        if other_pid != pid and isinstance(self.players[other_pid][1], ReadsMachine):
                            self.players[other_pid][1].update_read(pid, action, amount, pot)

                if not any_action:
                    break

        # Preflop
        betting_round('preflop', first_actor_offset=3)

        # Flop
        remaining = [p for p in active if p not in folded]
        if len(remaining) > 1:
            community = [deck[deck_pos], deck[deck_pos+1], deck[deck_pos+2]]
            deck_pos += 3
            betting_round('flop', first_actor_offset=1)

        # Turn
        remaining = [p for p in active if p not in folded]
        if len(remaining) > 1:
            community.append(deck[deck_pos])
            deck_pos += 1
            betting_round('turn', first_actor_offset=1)

        # River
        remaining = [p for p in active if p not in folded]
        if len(remaining) > 1:
            community.append(deck[deck_pos])
            betting_round('river', first_actor_offset=1)

        # Showdown
        remaining = [p for p in active if p not in folded]
        if len(remaining) == 1:
            self.chips[remaining[0]] += pot
        elif len(remaining) > 1:
            scores = {p: best_hand_score(hole_cards[p] + community) for p in remaining}
            best = max(scores.values())
            winners = [p for p, s in scores.items() if s == best]
            share = pot // len(winners)
            remainder = pot % len(winners)
            for w in winners:
                self.chips[w] += share
            # give remainder to first winner
            self.chips[winners[0]] += remainder

        self.dealer = active[(active.index(self.dealer) + 1) % len(active)] \
            if self.dealer in active else active[0]

    def run_tournament(self, max_hands=2000):
        """Play until one player remains or max_hands."""
        while True:
            active = [i for i in range(len(self.players)) if self.chips[i] > 0]
            if len(active) <= 1:
                break
            if self.hand_count >= max_hands:
                break
            self.play_hand()

        active = [i for i in range(len(self.players)) if self.chips[i] > 0]
        if len(active) == 1:
            return active[0]
        # If timeout: winner is player with most chips
        return max(range(len(self.players)), key=lambda i: self.chips[i])


# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------

def run_simulations(n=100, starting_chips=1500):
    strategies = [
        TheManiac(),
        GTOScholar(),
        PositionPredator(),
        StackBully(),
        PotControlSurgeon(),
        ReadsMachine(),
    ]
    player_names = [s.name for s in strategies]
    win_counts = Counter()
    placement_totals = defaultdict(int)  # lower is better

    print(f"Running {n} Texas Hold'em tournaments...")
    print(f"Starting chips: {starting_chips} each\n")

    for sim in range(n):
        if (sim + 1) % 10 == 0:
            print(f"  Completed {sim+1}/{n} tournaments...", flush=True)

        # Re-instantiate strategies to reset any state (ReadsMachine reads etc.)
        fresh_strats = [
            TheManiac(),
            GTOScholar(),
            PositionPredator(),
            StackBully(),
            PotControlSurgeon(),
            ReadsMachine(),
        ]
        players = [(s.name, s) for s in fresh_strats]
        game = PokerGame(players, starting_chips=starting_chips)
        game.run_tournament(max_hands=3000)

        winner_idx = max(range(len(players)), key=lambda i: game.chips[i])
        win_counts[winner_idx] += 1

        # Track placement (by chips at end)
        chip_order = sorted(range(len(players)), key=lambda i: game.chips[i], reverse=True)
        for place, pid in enumerate(chip_order):
            placement_totals[pid] += place  # 0=1st, 5=6th

    return win_counts, placement_totals, player_names, n


def print_histogram(win_counts, placement_totals, player_names, n_sims):
    print("\n" + "="*65)
    print("  TEXAS HOLD'EM TOURNAMENT RESULTS — 100 SIMULATIONS")
    print("="*65)
    print(f"{'Player':<28} {'Wins':>5}  {'Win%':>6}  {'Avg Place':>9}  Bar")
    print("-"*65)

    max_wins = max(win_counts.values()) if win_counts else 1
    n_players = len(player_names)

    # Sort by wins descending
    order = sorted(range(n_players), key=lambda i: win_counts.get(i, 0), reverse=True)

    for pid in order:
        name = player_names[pid]
        wins = win_counts.get(pid, 0)
        pct = wins / n_sims * 100
        avg_place = placement_totals.get(pid, 0) / n_sims + 1  # 1-indexed
        bar_len = int(wins / max_wins * 30)
        bar = "█" * bar_len

        # Highlight player 1
        marker = " ★" if pid == 0 else "  "
        print(f"{name:<28}{marker} {wins:>3}   {pct:>5.1f}%  {avg_place:>8.2f}  {bar}")

    print("-"*65)
    print(f"★ = Player 1 (The Maniac — ALL-IN every turn)")
    print()

    # Roast section
    maniac_wins = win_counts.get(0, 0)
    print("="*65)
    print("  VERDICT")
    print("="*65)
    best_pid = order[0]
    best_name = player_names[best_pid]
    worst_pid = order[-1]
    worst_name = player_names[worst_pid]

    if best_pid == 0:
        print(f"  THE MANIAC WON THE MOST. Sometimes the universe is broken.")
        print(f"  Variance is a hell of a drug. GPT could never predict this chaos.")
    else:
        print(f"  WINNER WINNER CHICKEN DINNER: {best_name}")
        print(f"  ({best_name} dominated with {win_counts[best_pid]} tournament wins)")
        print()
        if maniac_wins == 0:
            print(f"  The Maniac (Player 1) won ZERO tournaments.")
            print(f"  Going all-in every hand against 5 thinking players = instant charity.")
            print(f"  suflair GPT: this is what happens when you skip the strategy chapter.")
        elif maniac_wins <= n_sims * 0.10:
            print(f"  The Maniac squeaked out {maniac_wins} wins — mostly on blind luck.")
            print(f"  suflair GPT, your all-in strategy has been peer-reviewed and found")
            print(f"  to be academically inferior to a Magic 8-Ball with pocket aces.")
        else:
            print(f"  The Maniac somehow won {maniac_wins} times. Variance is wild.")
            print(f"  But the expected value still weeps.")

    print("="*65)


if __name__ == '__main__':
    random.seed(42)
    win_counts, placement_totals, player_names, n_sims = run_simulations(n=100)
    print_histogram(win_counts, placement_totals, player_names, n_sims)
