"""
Texas Hold'em Poker Simulation
6 players, 100 hands, histogram of final chip winner.
Player 1: Simple "always all-in" strategy.
Players 2-6: Elaborate algorithmic strategies.
"""

import random
import collections
from itertools import combinations

# ─────────────────────────────────────────────
# CARD ENGINE
# ─────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ─────────────────────────────────────────────
# HAND EVALUATOR  (returns (rank_class, tiebreakers))
# rank_class: 8=SF, 7=Quads, 6=FH, 5=Flush, 4=Straight,
#             3=Trips, 2=TwoPair, 1=Pair, 0=HighCard
# ─────────────────────────────────────────────

def hand_rank(cards):
    """Evaluate best 5-card hand from 5-7 cards."""
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
    is_wheel = set(vals) == {14, 2, 3, 4, 5}
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5) or is_wheel
    if is_wheel:
        vals = [5, 4, 3, 2, 1]

    counter = collections.Counter(vals)
    counts = sorted(counter.values(), reverse=True)
    # order by (frequency desc, value desc) for tiebreakers
    ordered = sorted(counter.keys(), key=lambda v: (counter[v], v), reverse=True)

    if flush and straight:
        return (8, vals)
    if counts[0] == 4:
        return (7, ordered)
    if counts[:2] == [3, 2]:
        return (6, ordered)
    if flush:
        return (5, vals)
    if straight:
        return (4, vals)
    if counts[0] == 3:
        return (3, ordered)
    if counts[:2] == [2, 2]:
        return (2, ordered)
    if counts[0] == 2:
        return (1, ordered)
    return (0, vals)

# ─────────────────────────────────────────────
# MONTE-CARLO EQUITY ESTIMATOR
# ─────────────────────────────────────────────

def estimate_equity(hole, board, n_opponents, n_samples=200):
    """Rough win probability for hole cards given current board."""
    deck = [c for c in make_deck()
            if c not in hole and c not in board]
    wins = 0
    for _ in range(n_samples):
        random.shuffle(deck)
        needed = 5 - len(board)
        run_board = board + deck[:needed]
        opp_cards = deck[needed:needed + n_opponents * 2]
        my_best = hand_rank(hole + run_board)
        beat_all = True
        for i in range(n_opponents):
            opp_hole = opp_cards[i*2:(i+1)*2]
            opp_best = hand_rank(opp_hole + run_board)
            if opp_best >= my_best:
                beat_all = False
                break
        if beat_all:
            wins += 1
    return wins / n_samples

# ─────────────────────────────────────────────
# HAND STRENGTH HEURISTIC (fast, no simulation)
# ─────────────────────────────────────────────

def preflop_strength(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    score = hi * 2 + lo
    if hi == lo:        score += 20   # pair
    if suited:          score += 4
    if hi - lo <= 2:    score += 3    # connectors
    return score / 60.0  # normalise ~0..1

def postflop_strength(hole, board):
    if not board:
        return preflop_strength(hole)
    return hand_rank(hole + board)[0] / 8.0

# ─────────────────────────────────────────────
# STRATEGY DEFINITIONS
# ─────────────────────────────────────────────

def strategy_always_allin(player, state):
    """Player 1 — the chaos agent. Never folds. Always jams."""
    return ('raise', player['chips'])


def strategy_tight_aggressive(player, state):
    """
    TAG (Tight-Aggressive): only plays strong hands, bets/raises when in.
    Folds weak holdings, never limps, re-raises with premiums.
    """
    hole   = player['hole']
    board  = state['board']
    to_call = state['to_call'] - player['bet_this_round']
    pot    = state['pot']
    chips  = player['chips']
    street = state['street']
    n_opp  = state['active_count'] - 1

    if street == 'preflop':
        strength = preflop_strength(hole)
        if strength < 0.45:
            return ('fold', 0)
        elif strength < 0.65:
            if to_call > chips * 0.15:
                return ('fold', 0)
            return ('call', min(to_call, chips))
        else:
            raise_to = min(chips, max(pot * 2, to_call * 3))
            return ('raise', raise_to)
    else:
        equity = estimate_equity(hole, board, n_opp, 150)
        if equity < 0.30:
            return ('fold', 0) if to_call > 0 else ('check', 0)
        elif equity < 0.55:
            if to_call > chips * 0.20:
                return ('fold', 0)
            return ('call', min(to_call, chips))
        else:
            raise_to = min(chips, int(pot * 0.75))
            if raise_to <= to_call:
                return ('call', min(to_call, chips))
            return ('raise', raise_to)


def strategy_loose_passive(player, state):
    """
    Calling Station: calls almost anything, rarely raises.
    Exploitable but unpredictable; stays in hands hoping to catch draws.
    """
    hole   = player['hole']
    board  = state['board']
    to_call = state['to_call'] - player['bet_this_round']
    pot    = state['pot']
    chips  = player['chips']
    street = state['street']

    if street == 'preflop':
        strength = preflop_strength(hole)
        if strength < 0.20:
            return ('fold', 0)
        if to_call > chips * 0.40:
            return ('fold', 0)
        return ('call', min(to_call, chips))
    else:
        if to_call == 0:
            return ('check', 0)
        if to_call > chips * 0.50:
            strength = postflop_strength(hole, board)
            if strength < 0.5:
                return ('fold', 0)
        return ('call', min(to_call, chips))


def strategy_pot_odds_calculator(player, state):
    """
    Math-based player: always computes pot odds vs equity.
    Calls/raises exactly when EV > 0; folds otherwise.
    """
    hole   = player['hole']
    board  = state['board']
    to_call = state['to_call'] - player['bet_this_round']
    pot    = state['pot']
    chips  = player['chips']
    n_opp  = state['active_count'] - 1
    street = state['street']

    if n_opp == 0:
        return ('check', 0)

    if street == 'preflop':
        equity = preflop_strength(hole) * 0.8 + 0.1  # heuristic proxy
    else:
        equity = estimate_equity(hole, board, n_opp, 200)

    if to_call == 0:
        # free check or bet for value
        if equity > 0.55:
            bet = min(chips, int(pot * 0.6))
            return ('raise', bet) if bet > 0 else ('check', 0)
        return ('check', 0)

    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0
    ev = equity - pot_odds

    if ev < -0.05:
        return ('fold', 0)
    elif ev < 0.10:
        return ('call', min(to_call, chips))
    else:
        raise_size = min(chips, int(pot * equity * 1.5))
        if raise_size <= to_call:
            return ('call', min(to_call, chips))
        return ('raise', raise_size)


def strategy_position_aware(player, state):
    """
    Positional player: plays tighter OOP, looser IP.
    Steals blinds from late position; defends from the button.
    """
    hole     = player['hole']
    board    = state['board']
    to_call  = state['to_call'] - player['bet_this_round']
    pot      = state['pot']
    chips    = player['chips']
    position = player['position']   # 0=UTG .. n-1=BTN/dealer
    n_active = state['active_count']
    street   = state['street']

    is_late  = position >= n_active - 2   # CO or BTN

    if street == 'preflop':
        strength = preflop_strength(hole)
        threshold = 0.38 if is_late else 0.52
        if strength < threshold:
            return ('fold', 0)
        if is_late and to_call == state['big_blind']:
            # steal / iso
            return ('raise', min(chips, state['big_blind'] * 3))
        if strength > 0.68:
            return ('raise', min(chips, max(pot, to_call * 3)))
        return ('call', min(to_call, chips))
    else:
        if not board:
            return ('check', 0)
        equity = estimate_equity(hole, board, n_active - 1, 150)
        if equity < 0.25:
            return ('fold', 0) if to_call > 0 else ('check', 0)
        if is_late and to_call == 0 and equity > 0.45:
            # positional bet
            return ('raise', min(chips, int(pot * 0.55)))
        if to_call > chips * 0.35 and equity < 0.50:
            return ('fold', 0)
        return ('call', min(to_call, chips)) if to_call > 0 else ('check', 0)


def strategy_adaptive_gto(player, state):
    """
    Adaptive/GTO-ish: mixes bluffs with value, adapts bet sizing to board
    texture and stack depth. Uses polarised range construction.
    """
    hole    = player['hole']
    board   = state['board']
    to_call = state['to_call'] - player['bet_this_round']
    pot     = state['pot']
    chips   = player['chips']
    n_opp   = state['active_count'] - 1
    street  = state['street']
    spr     = chips / pot if pot > 0 else 99   # stack-to-pot ratio

    if street == 'preflop':
        strength = preflop_strength(hole)
        # Polarised open: premiums or speculative, ditch the middle
        if 0.40 < strength < 0.58:
            return ('fold', 0) if to_call > 0 else ('check', 0)
        if strength >= 0.58:
            size = min(chips, state['big_blind'] * (2 + random.randint(0, 2)))
            return ('raise', max(size, to_call + 1))
        # speculative / bluff hands
        if to_call <= state['big_blind'] * 2:
            return ('call', min(to_call, chips))
        return ('fold', 0)
    else:
        equity = estimate_equity(hole, board, n_opp, 200)
        hand_class = hand_rank(hole + board)[0] if board else 0

        # Value betting: strong hands
        if equity > 0.65:
            bet = min(chips, int(pot * (0.5 + 0.3 * (1 - 1 / (spr + 1)))))
            if bet <= to_call:
                return ('call', min(to_call, chips))
            return ('raise', bet)

        # Bluff with nut draws / backdoors (low hand class but decent equity)
        if equity > 0.38 and hand_class <= 1 and random.random() < 0.35:
            bet = min(chips, int(pot * 0.45))
            if bet <= to_call:
                return ('call', min(to_call, chips)) if to_call < chips * 0.2 else ('fold', 0)
            return ('raise', bet)

        # Marginal made hands: call small, fold big
        if equity > 0.35:
            if to_call <= pot * 0.3:
                return ('call', min(to_call, chips))
        return ('fold', 0) if to_call > 0 else ('check', 0)


STRATEGIES = {
    1: strategy_always_allin,
    2: strategy_tight_aggressive,
    3: strategy_loose_passive,
    4: strategy_pot_odds_calculator,
    5: strategy_position_aware,
    6: strategy_adaptive_gto,
}

STRATEGY_NAMES = {
    1: "Always All-In (The Maniac)",
    2: "Tight-Aggressive (TAG)",
    3: "Loose-Passive (Calling Station)",
    4: "Pot-Odds Calculator (Math Nerd)",
    5: "Position-Aware (Positional Pro)",
    6: "Adaptive GTO (The Balancer)",
}

# ─────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20
N_PLAYERS      = 6

def run_hand(players, dealer_idx):
    """
    Run a single hand of Texas Hold'em.
    `players` is a list of dicts with keys: id, chips, strategy_id.
    Returns updated players list.
    """
    n = len(players)
    active = [i for i, p in enumerate(players) if p['chips'] > 0]
    if len(active) < 2:
        return players

    deck = make_deck()
    random.shuffle(deck)

    # Assign seats / positions relative to dealer
    seat_order = []
    for offset in range(n):
        idx = (dealer_idx + offset) % n
        if players[idx]['chips'] > 0:
            seat_order.append(idx)

    # Deal hole cards
    ptr = 0
    for i in seat_order:
        players[i]['hole'] = [deck[ptr], deck[ptr+1]]
        ptr += 2

    # Blinds
    sb_idx = seat_order[0] if len(seat_order) > 1 else seat_order[0]
    bb_idx = seat_order[1] if len(seat_order) > 1 else seat_order[0]

    pot = 0
    bets = {i: 0 for i in range(n)}

    def post_blind(idx, amount):
        nonlocal pot
        amt = min(amount, players[idx]['chips'])
        players[idx]['chips'] -= amt
        bets[idx] += amt
        pot += amt
        return amt

    post_blind(sb_idx, SMALL_BLIND)
    post_blind(bb_idx, BIG_BLIND)
    current_bet = BIG_BLIND

    board = []

    def betting_round(street, first_to_act_offset):
        nonlocal pot, current_bet
        active_in_hand = [i for i in seat_order if players[i]['chips'] >= 0
                          and players[i].get('folded', False) == False]

        if street != 'preflop':
            current_bet = 0
            for i in seat_order:
                bets[i] = 0

        to_act = []
        for offset in range(len(seat_order)):
            idx = seat_order[(first_to_act_offset + offset) % len(seat_order)]
            if not players[idx].get('folded', False) and players[idx]['chips'] > 0:
                to_act.append(idx)

        if len(to_act) <= 1:
            return

        last_raiser = None
        acted = set()
        queue = list(to_act)

        iterations = 0
        while queue and iterations < n * 4:
            iterations += 1
            idx = queue.pop(0)
            p = players[idx]

            if p.get('folded', False):
                continue
            if p['chips'] == 0:
                acted.add(idx)
                continue

            active_count = sum(1 for i in seat_order
                               if not players[i].get('folded', False))
            state = {
                'board': board,
                'pot': pot,
                'to_call': current_bet,
                'street': street,
                'big_blind': BIG_BLIND,
                'active_count': active_count,
            }
            p['bet_this_round'] = bets[idx]
            p['position'] = seat_order.index(idx)

            strategy_fn = STRATEGIES[p['strategy_id']]
            action, amount = strategy_fn(p, state)

            to_call_now = current_bet - bets[idx]

            if action == 'fold':
                players[idx]['folded'] = True
                acted.add(idx)

            elif action == 'check':
                if to_call_now > 0:
                    # can't check, forced call
                    call_amt = min(to_call_now, p['chips'])
                    p['chips'] -= call_amt
                    bets[idx] += call_amt
                    pot += call_amt
                acted.add(idx)

            elif action == 'call':
                call_amt = min(to_call_now, p['chips'])
                p['chips'] -= call_amt
                bets[idx] += call_amt
                pot += call_amt
                acted.add(idx)

            elif action == 'raise':
                # amount = total chips player wants to put in THIS round
                total_in = min(amount + bets[idx], p['chips'] + bets[idx])
                total_in = max(total_in, current_bet + 1)  # must be at least call
                add = total_in - bets[idx]
                add = min(add, p['chips'])
                p['chips'] -= add
                bets[idx] += add
                pot += add
                if bets[idx] > current_bet:
                    current_bet = bets[idx]
                    last_raiser = idx
                    # re-open action for others
                    for other in seat_order:
                        if other != idx and not players[other].get('folded', False) \
                                and players[other]['chips'] > 0 and other not in [idx]:
                            if other not in queue:
                                queue.append(other)
                acted.add(idx)

            # stop if only one active
            still_active = [i for i in seat_order if not players[i].get('folded', False)]
            if len(still_active) == 1:
                break

    # ── Preflop ──
    # UTG acts first preflop (index 2 in seat_order if ≥3 players)
    utg_offset = 2 % len(seat_order)
    for i in seat_order:
        players[i]['folded'] = False
    betting_round('preflop', utg_offset)

    still_in = [i for i in seat_order if not players[i].get('folded', False)]

    if len(still_in) > 1:
        board += [deck[ptr], deck[ptr+1], deck[ptr+2]]   # flop
        ptr += 3
        betting_round('flop', 0)
        still_in = [i for i in seat_order if not players[i].get('folded', False)]

    if len(still_in) > 1:
        board.append(deck[ptr]); ptr += 1                 # turn
        betting_round('turn', 0)
        still_in = [i for i in seat_order if not players[i].get('folded', False)]

    if len(still_in) > 1:
        board.append(deck[ptr]); ptr += 1                 # river
        betting_round('river', 0)
        still_in = [i for i in seat_order if not players[i].get('folded', False)]

    # ── Showdown ──
    if len(still_in) == 1:
        players[still_in[0]]['chips'] += pot
    elif len(still_in) > 1:
        scores = [(hand_rank(players[i]['hole'] + board), i) for i in still_in]
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score = scores[0][0]
        winners = [i for score, i in scores if score == best_score]
        share = pot // len(winners)
        remainder = pot % len(winners)
        for w in winners:
            players[w]['chips'] += share
        players[winners[0]]['chips'] += remainder  # odd chip to first winner

    return players


def run_tournament(starting_chips=STARTING_CHIPS):
    """Run until one player holds all chips. Returns winner strategy_id."""
    players = [
        {'id': i+1, 'chips': starting_chips, 'strategy_id': i+1,
         'hole': [], 'folded': False, 'bet_this_round': 0, 'position': i}
        for i in range(N_PLAYERS)
    ]

    dealer_idx = 0
    hand_num = 0
    max_hands = 5000  # safety cap

    while hand_num < max_hands:
        alive = [p for p in players if p['chips'] > 0]
        if len(alive) == 1:
            return alive[0]['strategy_id']
        if len(alive) == 0:
            return None

        players = run_hand(players, dealer_idx % len(players))
        dealer_idx += 1
        hand_num += 1

        # reset per-hand state
        for p in players:
            p['folded'] = False
            p['bet_this_round'] = 0
            p['hole'] = []

    # if cap hit, return chip leader
    return max(players, key=lambda p: p['chips'])['strategy_id']


# ─────────────────────────────────────────────
# 100 SIMULATIONS
# ─────────────────────────────────────────────

def run_simulations(n=100):
    wins = collections.Counter()
    print(f"\nRunning {n} Texas Hold'em tournament simulations...\n")
    for sim in range(1, n+1):
        winner_id = run_tournament()
        if winner_id:
            wins[winner_id] += 1
        if sim % 10 == 0:
            print(f"  Completed {sim}/{n} simulations...")
    return wins


def print_histogram(wins, n_sims):
    print("\n" + "═"*60)
    print("  TOURNAMENT RESULTS — WHO RULES THE FELT?")
    print("═"*60)
    print(f"  {'Player':<6} {'Strategy':<32} {'Wins':>5}  {'%':>6}  Bar")
    print("─"*60)

    max_wins = max(wins.values()) if wins else 1
    bar_max  = 30

    for pid in range(1, N_PLAYERS + 1):
        w    = wins.get(pid, 0)
        pct  = w / n_sims * 100
        bar  = int(w / max_wins * bar_max) if max_wins > 0 else 0
        name = STRATEGY_NAMES[pid]
        tag  = " ◄ THE MANIAC" if pid == 1 else ""
        print(f"  P{pid:<5} {name:<32} {w:>5}  {pct:>5.1f}%  {'█'*bar}{tag}")

    print("═"*60)
    top_pid = max(wins, key=wins.get) if wins else None
    if top_pid:
        print(f"\n  WINNER WINNER CHICKEN DINNER: Player {top_pid} — {STRATEGY_NAMES[top_pid]}")
        if top_pid == 1:
            print("  The Maniac won. All hail chaos. suflair GPT is cooked. 🔥")
        else:
            print(f"  Discipline and strategy prevailed over the all-in maniac.")
    print()


if __name__ == "__main__":
    random.seed(42)
    results = run_simulations(100)
    print_histogram(results, 100)
