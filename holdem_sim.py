"""
Texas Hold'em Poker Simulation
Player 1: The Degen — all-in every turn
Players 2-6: Elaborate strategic algorithms
100 tournament simulations → winner histogram

Fast version: uses heuristic equity (no Monte Carlo per decision)
"""

import random
from collections import Counter
from itertools import combinations

# ─── Card primitives ─────────────────────────────────────────────────────────

RANKS = list(range(2, 15))   # 2..14 (14=Ace)
SUITS = ['s', 'h', 'd', 'c']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


# ─── Hand evaluator ──────────────────────────────────────────────────────────

def best_hand(cards):
    best = None
    for combo in combinations(cards, 5):
        h = evaluate5(combo)
        if best is None or h > best:
            best = h
    return best

def evaluate5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    rc = Counter(ranks)
    rank_counts = sorted(rc.values(), reverse=True)
    is_flush = len(set(suits)) == 1
    is_straight, sh = check_straight(ranks)

    if is_flush and is_straight:
        return (8, sh)
    if rank_counts[0] == 4:
        quad = max(r for r, c in rc.items() if c == 4)
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)
    if rank_counts[0] == 3 and rank_counts[1] == 2:
        trip = max(r for r, c in rc.items() if c == 3)
        pair = max(r for r, c in rc.items() if c == 2)
        return (6, trip, pair)
    if is_flush:
        return (5,) + tuple(ranks)
    if is_straight:
        return (4, sh)
    if rank_counts[0] == 3:
        trip = max(r for r, c in rc.items() if c == 3)
        kickers = sorted([r for r in ranks if r != trip], reverse=True)
        return (3, trip) + tuple(kickers)
    if rank_counts[0] == 2 and rank_counts[1] == 2:
        pairs = sorted([r for r, c in rc.items() if c == 2], reverse=True)
        kicker = max(r for r in ranks if r not in pairs)
        return (2,) + tuple(pairs) + (kicker,)
    if rank_counts[0] == 2:
        pair = max(r for r, c in rc.items() if c == 2)
        kickers = sorted([r for r in ranks if r != pair], reverse=True)
        return (1, pair) + tuple(kickers)
    return (0,) + tuple(ranks)

def check_straight(sorted_ranks):
    r = sorted(set(sorted_ranks), reverse=True)
    for i in range(len(r) - 4):
        w = r[i:i+5]
        if w[0] - w[4] == 4:
            return True, w[0]
    if {14, 2, 3, 4, 5}.issubset(set(r)):
        return True, 5
    return False, 0


# ─── Fast equity heuristics ──────────────────────────────────────────────────

def hand_strength(hole, community):
    """
    Fast 0..1 hand strength estimate.
    Preflop: use known preflop hand ranking tables.
    Postflop: evaluate current made hand category.
    """
    if not community:
        return preflop_strength(hole)
    score = best_hand(hole + community)
    cat = score[0]
    # Normalize to 0..1: cat/8 plus small rank tiebreak
    base = cat / 8.0
    if len(score) > 1:
        primary = score[1] / 14.0 * 0.09
        return min(1.0, base + primary)
    return base

def preflop_strength(hole):
    """Preflop hand strength 0..1 based on Chen formula approximation."""
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2
    g = r1 - r2  # gap

    if pair:
        # Pocket pairs
        score = r1 / 14.0
        return 0.4 + score * 0.45
    # High card value
    score = r1 / 14.0 * 0.5 + r2 / 14.0 * 0.3
    if suited:
        score += 0.08
    # Connectedness bonus
    if g == 0:
        score += 0.1
    elif g == 1:
        score += 0.07
    elif g == 2:
        score += 0.04
    return min(1.0, score)

def pot_odds(call_amount, pot):
    if call_amount == 0:
        return 1.0
    total = pot + call_amount
    if total <= 0:
        return 1.0
    return pot / total

def is_pocket_pair(hole):
    return hole[0][0] == hole[1][0]

def is_suited(hole):
    return hole[0][1] == hole[1][1]

def high_card_value(hole):
    return max(hole[0][0], hole[1][0])

def gap(hole):
    return abs(hole[0][0] - hole[1][0])

def premium_hole(hole):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    if is_pocket_pair(hole) and r1 >= 10:
        return True
    if r1 == 14 and r2 >= 10:
        return True
    return False

def has_flush_draw(hole, community):
    if len(community) < 2:
        return False
    suit_counts = Counter(c[1] for c in hole + community)
    return max(suit_counts.values()) >= 4

def has_straight_draw(hole, community):
    if len(community) < 2:
        return False
    all_ranks = sorted(set(c[0] for c in hole + community))
    for i in range(len(all_ranks) - 2):
        window = all_ranks[i:i+4]
        if len(window) == 4 and window[-1] - window[0] <= 4:
            return True
    return False

def scare_card(community):
    if not community:
        return False
    return max(c[0] for c in community) >= 12


# ─── Six Strategies ───────────────────────────────────────────────────────────

def strategy_degen(player_state, game_state):
    """The Degen: if my_turn: bet = all_in"""
    return ('raise', player_state['chips'])


def strategy_gto_approximator(player_state, game_state):
    """
    GTO Approximator — balanced ranges, pot-odds based decisions.
    Raises for value with strong hands, mixed calls with medium equity,
    folds when well below pot odds. Bet sizing scales with hand strength.
    """
    hole = player_state['hole']
    community = game_state['community']
    call_amount = game_state['call_amount']
    pot = game_state['pot']
    stack = player_state['chips']

    equity = hand_strength(hole, community)
    odds = pot_odds(call_amount, pot)
    street = len(community)

    # Equity far below pot odds → fold/check
    if equity < odds * 0.65:
        if call_amount == 0:
            return ('check', 0)
        return ('fold', 0)

    # Strong equity → value raise
    if equity > 0.68:
        bet = min(stack, max(int(pot * 0.75), call_amount + BIG_BLIND))
        return ('raise', bet)

    # Medium equity with draw consideration
    draw = has_flush_draw(hole, community) or has_straight_draw(hole, community)
    if equity > 0.40 or (draw and equity > 0.25):
        if call_amount == 0:
            if street == 0 and equity > 0.55:
                return ('raise', max(BIG_BLIND * 2, int(pot * 0.4)))
            return ('check', 0)
        if call_amount <= pot * 0.45:
            return ('call', call_amount)
        return ('fold', 0)

    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)


def strategy_tight_aggro(player_state, game_state):
    """
    Tight-Aggressive (TAG) — premium hands only, but played with force.
    3-bets premiums preflop. Continuation bets most flops with top-pair+.
    Shuts down on bad turns. Never calls without equity.
    """
    hole = player_state['hole']
    community = game_state['community']
    call_amount = game_state['call_amount']
    pot = game_state['pot']
    stack = player_state['chips']
    street = len(community)

    strength = hand_strength(hole, community)

    if street == 0:  # Preflop
        if premium_hole(hole):
            bet = min(stack, max(call_amount * 3, int(pot * 0.7) + BIG_BLIND))
            return ('raise', bet)
        r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
        playable = is_pocket_pair(hole) or (r1 >= 11 and gap(hole) <= 2) or (is_suited(hole) and r1 >= 12)
        if playable:
            if call_amount == 0:
                return ('check', 0)
            if call_amount <= pot * 0.25:
                return ('call', call_amount)
        if call_amount == 0:
            return ('check', 0)
        return ('fold', 0)

    # Postflop: bet big with strong hands
    if strength > 0.6:
        bet = min(stack, int(pot * 0.8))
        return ('raise', max(bet, call_amount + 1))
    if strength > 0.38:
        if call_amount == 0:
            return ('raise', max(1, int(pot * 0.5)))
        if call_amount <= pot * 0.3:
            return ('call', call_amount)
        return ('fold', 0)
    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)


def strategy_loose_passive(player_state, game_state):
    """
    Loose-Passive (Calling Station) — plays wide, rarely folds.
    Calls cheap bets with any two cards preflop.
    Postflop calls with any pair or draw, folds only massive bets with air.
    Almost never raises, so opponents can't read its hands.
    """
    hole = player_state['hole']
    community = game_state['community']
    call_amount = game_state['call_amount']
    pot = game_state['pot']
    stack = player_state['chips']
    street = len(community)

    strength = hand_strength(hole, community)

    if street == 0:
        if call_amount == 0:
            return ('check', 0)
        if call_amount <= max(BIG_BLIND * 3, pot * 0.5):
            return ('call', min(call_amount, stack))
        if strength > 0.55:
            return ('call', min(call_amount, stack))
        return ('fold', 0)

    # Postflop: call with anything reasonable
    draw = has_flush_draw(hole, community) or has_straight_draw(hole, community)
    if strength > 0.15 or draw:
        if call_amount == 0:
            return ('check', 0)
        if call_amount <= pot * 0.6:
            return ('call', min(call_amount, stack))
        if strength > 0.5 or (draw and call_amount <= pot * 0.4):
            return ('call', min(call_amount, stack))
        return ('fold', 0)

    if call_amount == 0:
        return ('check', 0)
    if call_amount <= pot * 0.2:
        return ('call', min(call_amount, stack))
    return ('fold', 0)


def strategy_position_exploiter(player_state, game_state):
    """
    Position Exploiter — plays more hands in late position, tight early.
    Steals blinds from the button. Iso-raises limpers.
    Respects 3-bets; exploits passive opponents with thin value bets.
    """
    hole = player_state['hole']
    community = game_state['community']
    call_amount = game_state['call_amount']
    pot = game_state['pot']
    stack = player_state['chips']
    position = player_state.get('position', 3)
    street = len(community)

    strength = hand_strength(hole, community)
    late = position <= 1  # Button or cutoff

    if street == 0:
        if premium_hole(hole):
            bet = min(stack, max(call_amount * 4, int(pot * 0.9) + BIG_BLIND))
            return ('raise', bet)
        if late:
            if call_amount == 0:
                return ('raise', max(BIG_BLIND * 2, int(pot * 0.45)))
            if call_amount <= BIG_BLIND * 4 and (is_pocket_pair(hole) or high_card_value(hole) >= 9 or is_suited(hole)):
                return ('call', call_amount)
            return ('fold', 0)
        else:
            if is_pocket_pair(hole) and hole[0][0] >= 8:
                if call_amount <= pot * 0.25:
                    return ('call', min(call_amount, stack))
                return ('raise', min(stack, call_amount * 3))
            if high_card_value(hole) >= 13 and gap(hole) <= 1:
                if call_amount == 0:
                    return ('check', 0)
                return ('call', min(call_amount, stack))
            if call_amount == 0:
                return ('check', 0)
            return ('fold', 0)

    # Postflop
    if strength > 0.65:
        bet = min(stack, int(pot * 0.85))
        return ('raise', max(bet, call_amount + 1))
    if late and strength > 0.25 and call_amount == 0:
        return ('raise', max(1, int(pot * 0.4)))
    if strength > 0.42 and call_amount <= pot * 0.45:
        return ('call', min(call_amount, stack))
    if call_amount == 0:
        return ('check', 0)
    if strength > 0.28 and call_amount <= pot * 0.18:
        return ('call', min(call_amount, stack))
    return ('fold', 0)


def strategy_adaptive_bluffer(player_state, game_state):
    """
    Adaptive Bluffer — polarized betting: strong hands and bluffs, not middle.
    Bluffs on scare cards (A/K/Q on board) when holding initiative.
    Semi-bluffs flush and straight draws aggressively.
    Gives up immediately when facing resistance; never bluff-calls.
    Overrepresents strong ranges on monotone/coordinated boards.
    """
    hole = player_state['hole']
    community = game_state['community']
    call_amount = game_state['call_amount']
    pot = game_state['pot']
    stack = player_state['chips']
    street = len(community)

    strength = hand_strength(hole, community)
    scare = scare_card(community)
    draw = has_flush_draw(hole, community) or has_straight_draw(hole, community)
    spr = stack / max(pot, 1)

    if street == 0:
        if premium_hole(hole):
            return ('raise', min(stack, max(call_amount * 3 + BIG_BLIND, int(pot * 0.65))))
        if is_suited(hole) and gap(hole) <= 2 and high_card_value(hole) >= 9:
            if call_amount <= BIG_BLIND * 3:
                return ('call', min(call_amount, stack))
        if is_pocket_pair(hole):
            if call_amount == 0:
                return ('raise', max(BIG_BLIND * 2, int(pot * 0.4)))
            if call_amount <= BIG_BLIND * 4:
                return ('call', min(call_amount, stack))
        if call_amount == 0:
            return ('check', 0)
        return ('fold', 0)

    # Strong value hand
    if strength > 0.65:
        overbet = 1.0 if scare else 0.75
        bet = min(stack, int(pot * overbet))
        return ('raise', max(bet, call_amount + 1))

    # Semi-bluff draws
    if draw and strength > 0.2:
        if call_amount == 0:
            return ('raise', max(1, int(pot * 0.55)))
        if call_amount <= pot * 0.5:
            return ('call', min(call_amount, stack))

    # Pure bluff on scare card when stack is healthy and we're betting into a check
    if scare and spr > 2 and call_amount == 0 and street >= 2:
        return ('raise', max(1, int(pot * 0.7)))

    # Give up / thin value
    if strength > 0.32 and call_amount == 0:
        return ('check', 0)
    if strength > 0.45 and call_amount <= pot * 0.25:
        return ('call', min(call_amount, stack))
    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)


STRATEGIES = [
    strategy_degen,
    strategy_gto_approximator,
    strategy_tight_aggro,
    strategy_loose_passive,
    strategy_position_exploiter,
    strategy_adaptive_bluffer,
]

STRATEGY_NAMES = [
    "The Degen (ALL IN)",
    "GTO Approximator",
    "Tight-Aggressive",
    "Loose-Passive",
    "Position Exploiter",
    "Adaptive Bluffer",
]

STARTING_CHIPS = 1000
SMALL_BLIND = 10
BIG_BLIND = 20
NUM_PLAYERS = 6


# ─── Game Engine ──────────────────────────────────────────────────────────────

class PokerGame:
    def __init__(self):
        self.chips = [STARTING_CHIPS] * NUM_PLAYERS
        self.dealer = 0

    def play_tournament(self):
        for _ in range(3000):
            active = [i for i in range(NUM_PLAYERS) if self.chips[i] > 0]
            if len(active) == 1:
                return active[0]
            self.play_hand(active)
        return max(range(NUM_PLAYERS), key=lambda i: self.chips[i])

    def play_hand(self, active):
        if len(active) < 2:
            return

        # Rotate dealer
        self.dealer = (self.dealer + 1) % NUM_PLAYERS
        while self.chips[self.dealer] == 0:
            self.dealer = (self.dealer + 1) % NUM_PLAYERS

        order = self._seat_order(active, self.dealer)
        sb_idx = order[0]
        bb_idx = order[1] if len(order) > 1 else order[0]

        pot = 0
        current_bets = {i: 0 for i in active}

        sb = min(SMALL_BLIND, self.chips[sb_idx])
        self.chips[sb_idx] -= sb
        current_bets[sb_idx] = sb
        pot += sb

        bb_val = min(BIG_BLIND, self.chips[bb_idx])
        self.chips[bb_idx] -= bb_val
        current_bets[bb_idx] = bb_val
        pot += bb_val

        deck = make_deck()
        random.shuffle(deck)
        hole_cards = {}
        ptr = 0
        for i in active:
            hole_cards[i] = [deck[ptr], deck[ptr + 1]]
            ptr += 2
        community = []
        folded = set()

        streets = [('preflop', 0), ('flop', 3), ('turn', 1), ('river', 1)]

        for street_name, new_cards in streets:
            community.extend(deck[ptr:ptr + new_cards])
            ptr += new_cards

            remaining = [i for i in active if i not in folded]
            if len(remaining) <= 1:
                break

            if street_name == 'preflop':
                action_order = order[2:] + order[:2]
                max_bet = bb_val
            else:
                action_order = [i for i in order if i not in folded]
                max_bet = 0

            pot, current_bets, max_bet, folded = self._betting_round(
                remaining, action_order, hole_cards, community,
                pot, current_bets, max_bet, folded
            )

        # Showdown
        winners = [i for i in active if i not in folded]
        if len(winners) == 1:
            self.chips[winners[0]] += pot
        elif winners:
            scores = {i: best_hand(hole_cards[i] + community) for i in winners}
            top = max(scores.values())
            best_players = [i for i in winners if scores[i] == top]
            share = pot // len(best_players)
            remainder = pot % len(best_players)
            for i in best_players:
                self.chips[i] += share
            if remainder:
                self.chips[best_players[0]] += remainder

    def _seat_order(self, active, dealer):
        ap = list(active)
        if dealer in ap:
            d = ap.index(dealer)
            return ap[d+1:] + ap[:d+1]
        return ap

    def _betting_round(self, still_active, action_order, hole_cards, community,
                       pot, current_bets, max_bet, folded):
        queue = [i for i in action_order if i in still_active and i not in folded]
        iterations = 0

        while queue and iterations < 200:
            iterations += 1
            i = queue.pop(0)
            if i in folded:
                continue
            live = [x for x in still_active if x not in folded]
            if len(live) <= 1:
                break

            call_amount = min(max_bet - current_bets.get(i, 0), self.chips[i])

            position = action_order.index(i) if i in action_order else 0
            player_state = {
                'hole': hole_cards[i],
                'chips': self.chips[i],
                'position': position,
                'current_bet': current_bets.get(i, 0),
            }
            game_state = {
                'community': community,
                'pot': pot,
                'call_amount': max(0, call_amount),
                'max_bet': max_bet,
                'num_active': len(live),
            }

            try:
                action, amount = STRATEGIES[i](player_state, game_state)
            except Exception:
                action, amount = ('fold', 0)

            if action == 'fold':
                folded.add(i)
            elif action == 'check':
                pass
            elif action == 'call':
                actual = min(max(0, call_amount), self.chips[i])
                self.chips[i] -= actual
                current_bets[i] = current_bets.get(i, 0) + actual
                pot += actual
            elif action == 'raise':
                total_add = max(0, min(amount, self.chips[i]))
                total_add = max(total_add, max(0, call_amount))  # must at least call
                total_add = min(total_add, self.chips[i])
                self.chips[i] -= total_add
                current_bets[i] = current_bets.get(i, 0) + total_add
                new_max = current_bets[i]
                if new_max > max_bet:
                    max_bet = new_max
                    for j in live:
                        if j != i and j not in folded and current_bets.get(j, 0) < max_bet:
                            if j not in queue:
                                queue.append(j)
                pot += total_add

        return pot, current_bets, max_bet, folded


# ─── Run 100 Simulations ──────────────────────────────────────────────────────

def run_simulations(n=100):
    wins = Counter()
    for sim in range(n):
        game = PokerGame()
        winner = game.play_tournament()
        wins[winner] += 1
        if (sim + 1) % 10 == 0:
            print(f"  Completed {sim + 1}/{n} tournaments...", flush=True)
    return wins


# ─── Histogram ────────────────────────────────────────────────────────────────

def print_histogram(wins, n_sims):
    print("\n" + "=" * 68)
    print("    TEXAS HOLD'EM — 100 TOURNAMENT WINNER HISTOGRAM")
    print("=" * 68)
    max_wins = max(wins.values()) if wins else 1
    bar_width = 32

    rows = []
    for idx in range(NUM_PLAYERS):
        name = STRATEGY_NAMES[idx]
        count = wins.get(idx, 0)
        pct = count / n_sims * 100
        bar_len = int(count / max_wins * bar_width) if max_wins else 0
        rows.append((idx, name, count, pct, bar_len))

    # Sort by wins descending for display
    rows_sorted = sorted(rows, key=lambda x: -x[2])

    for idx, name, count, pct, bar_len in rows_sorted:
        marker = " <<< THE DEGEN" if idx == 0 else ""
        bar = chr(9608) * bar_len  # █
        label = f"P{idx+1} {name}"
        print(f"  {label:<30} {bar:<32} {count:3d} ({pct:5.1f}%){marker}")

    print("=" * 68)

    rounder_idx = max(wins, key=wins.get)
    rounder_name = STRATEGY_NAMES[rounder_idx]
    degen_wins = wins.get(0, 0)
    rounder_wins = wins[rounder_idx]

    print(f"\n  WINNER WINNER CHICKEN DINNER")
    print(f"  The Rounder: P{rounder_idx+1} — {rounder_name}")
    print(f"  Won {rounder_wins}/{n_sims} tournaments ({rounder_wins/n_sims*100:.1f}%)")

    if rounder_idx != 0:
        gap_pct = (rounder_wins - degen_wins) / n_sims * 100
        print(f"\n  The Degen (ALL IN every turn) managed: {degen_wins} wins ({degen_wins/n_sims*100:.1f}%)")
        print(f"  sufflair GPT humiliated by {gap_pct:.1f} percentage points. REKT.")
    else:
        print(f"\n  Wait... the ALL IN bot WON? Even a blind squirrel finds a nut.")
    print("=" * 68)


if __name__ == '__main__':
    print("=" * 68)
    print("  6-Player Texas Hold'em — 100 Tournament Simulation")
    print("  P1: ALL IN every hand (The Degen)")
    print("  P2-P6: Elaborate strategic algorithms")
    print("=" * 68)
    random.seed(42)
    wins = run_simulations(100)
    print_histogram(wins, 100)
