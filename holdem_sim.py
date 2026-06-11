"""
Texas Hold'em Poker Simulation
6 players, 100 games, last-player-standing histogram.

Player 1 : SimpleAllIn  — always shoves all-in
Players 2-6 : five elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ──────────────────────────────────────────────
# Card / Deck primitives
# ──────────────────────────────────────────────

RANKS = list(range(2, 15))          # 2-14  (14=Ace)
SUITS = ['♠', '♥', '♦', '♣']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',
              9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return RANK_NAMES[c[0]] + c[1]

# ──────────────────────────────────────────────
# Hand evaluator  (returns a comparable tuple)
# Higher tuple = better hand
# ──────────────────────────────────────────────

def best_hand(seven_cards):
    """Return the best 5-card hand value from up to 7 cards."""
    best = None
    for five in combinations(seven_cards, 5):
        v = hand_value(five)
        if best is None or v > best:
            best = v
    return best

def hand_value(five):
    ranks = sorted([c[0] for c in five], reverse=True)
    suits = [c[1] for c in five]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0]-5, -1)) or
                ranks == [14, 5, 4, 3, 2])   # wheel
    if straight and ranks[0] == 5:            # wheel — ace plays low
        ranks = [5, 4, 3, 2, 1]

    counts = sorted(Counter(ranks).values(), reverse=True)
    rank_groups = sorted(Counter(ranks).keys(),
                         key=lambda r: (Counter(ranks)[r], r), reverse=True)

    if flush and straight:   return (8,) + tuple(ranks)
    if counts[0] == 4:       return (7,) + tuple(rank_groups)
    if counts[:2] == [3, 2]: return (6,) + tuple(rank_groups)
    if flush:                return (5,) + tuple(ranks)
    if straight:             return (4,) + tuple(ranks)
    if counts[0] == 3:       return (3,) + tuple(rank_groups)
    if counts[:2] == [2, 2]: return (2,) + tuple(rank_groups)
    if counts[0] == 2:       return (1,) + tuple(rank_groups)
    return (0,) + tuple(ranks)

# ──────────────────────────────────────────────
# Monte-Carlo equity estimator (used by strategies)
# ──────────────────────────────────────────────

def estimate_equity(hole, community, num_opponents, iterations=200):
    """Estimate win probability via Monte-Carlo."""
    deck = [c for c in make_deck() if c not in hole and c not in community]
    wins = 0
    needed = 5 - len(community)
    for _ in range(iterations):
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        opp_cards = deck[needed: needed + num_opponents * 2]
        my_val = best_hand(list(hole) + board)
        lost = False
        for i in range(num_opponents):
            opp = opp_cards[i*2:(i+1)*2]
            if best_hand(opp + board) > my_val:
                lost = True
                break
        if not lost:
            wins += 1
    return wins / iterations

# ──────────────────────────────────────────────
# Strategies
# Each strategy is a callable:
#   action(hole, community, pot, my_chips, call_amount,
#          min_raise, active_opponents, street) -> ('fold'|'call'|'raise', amount)
# ──────────────────────────────────────────────

# ── Strategy 0: SimpleAllIn (Player 1) ──────
def strategy_simple_allin(hole, community, pot, my_chips,
                           call_amount, min_raise, opponents, street):
    return ('raise', my_chips)   # always shove

# ── Strategy 1: EquityShark ─────────────────
# Raises large when equity is high, folds marginal hands, calls medium.
def strategy_equity_shark(hole, community, pot, my_chips,
                           call_amount, min_raise, opponents, street):
    eq = estimate_equity(hole, community, opponents, iterations=150)
    if eq > 0.65:
        bet = min(my_chips, max(min_raise, int(pot * 1.5)))
        return ('raise', bet)
    elif eq > 0.40:
        if call_amount == 0:
            return ('raise', max(min_raise, int(pot * 0.5)))
        return ('call', call_amount)
    elif eq > 0.25 and call_amount == 0:
        return ('call', 0)   # check
    else:
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)

# ── Strategy 2: PositionBully ───────────────
# Uses pot odds + street aggression. Bluffs the flop frequently.
def strategy_position_bully(hole, community, pot, my_chips,
                             call_amount, min_raise, opponents, street):
    eq = estimate_equity(hole, community, opponents, iterations=100)
    pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0

    # Pre-flop: play tight — only good hands
    if street == 'preflop':
        high = max(hole[0][0], hole[1][0])
        low  = min(hole[0][0], hole[1][0])
        pair = hole[0][0] == hole[1][0]
        suited = hole[0][1] == hole[1][1]
        premium = pair or high >= 11 or (high >= 10 and suited) or (high - low <= 3 and suited)
        if premium:
            return ('raise', min(my_chips, max(min_raise, int(pot * 2.5))))
        if call_amount == 0:
            return ('call', 0)   # limp with trash
        return ('fold', 0)

    # Flop: bluff 30% of the time when equity is low
    if street == 'flop' and eq < 0.35:
        if random.random() < 0.30:
            return ('raise', min(my_chips, max(min_raise, int(pot * 0.75))))
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)

    if eq > pot_odds + 0.15:
        return ('raise', min(my_chips, max(min_raise, int(pot * 1.0))))
    if eq > pot_odds:
        return ('call', call_amount)
    if call_amount == 0:
        return ('call', 0)
    return ('fold', 0)

# ── Strategy 3: GTO-Ish ─────────────────────
# Approximates GTO ranges with mixed strategies (randomised decisions).
def strategy_gto_ish(hole, community, pot, my_chips,
                     call_amount, min_raise, opponents, street):
    eq = estimate_equity(hole, community, opponents, iterations=120)

    # Build a mixed strategy based on equity buckets
    if eq >= 0.75:
        # value — always raise
        size = min(my_chips, max(min_raise, int(pot * (1.0 + random.uniform(0, 1)))))
        return ('raise', size)
    elif eq >= 0.55:
        # value but smaller
        if random.random() < 0.80:
            size = min(my_chips, max(min_raise, int(pot * random.uniform(0.5, 1.0))))
            return ('raise', size)
        return ('call', call_amount)
    elif eq >= 0.40:
        # medium — mixed call/check
        if call_amount == 0:
            if random.random() < 0.35:
                return ('raise', min(my_chips, max(min_raise, int(pot * 0.4))))
            return ('call', 0)
        r = random.random()
        if r < 0.50:
            return ('call', call_amount)
        elif r < 0.65:
            return ('raise', min(my_chips, max(min_raise, int(pot * 0.5))))
        return ('fold', 0)
    elif eq >= 0.20:
        # bluff candidate — bluff ~25% when first to act
        if call_amount == 0 and random.random() < 0.25:
            return ('raise', min(my_chips, max(min_raise, int(pot * 0.6))))
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)
    else:
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)

# ── Strategy 4: StackBully ──────────────────
# Shoves or raises large when chip stack is dominant; tightens up when short.
def strategy_stack_bully(hole, community, pot, my_chips,
                         call_amount, min_raise, opponents, street):
    eq = estimate_equity(hole, community, opponents, iterations=100)
    big_stack_threshold = 1500   # big stack plays very aggressively

    if my_chips >= big_stack_threshold:
        # Bully mode — raise frequently
        if eq > 0.30 or call_amount == 0:
            bet = min(my_chips, max(min_raise, int(pot * 2.0)))
            return ('raise', bet)
        return ('fold', 0)
    elif my_chips < 200:
        # Short-stack — shove or fold
        if eq > 0.45:
            return ('raise', my_chips)
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)
    else:
        # Normal stack — straightforward equity play
        if eq > 0.55:
            return ('raise', min(my_chips, max(min_raise, int(pot * 1.0))))
        if eq > 0.35:
            return ('call', call_amount)
        if call_amount == 0:
            return ('call', 0)
        return ('fold', 0)

# ── Strategy 5: TightAggressive ─────────────
# Classic TAG: only plays strong hands, raises/bets, almost never limps.
def strategy_tag(hole, community, pot, my_chips,
                 call_amount, min_raise, opponents, street):
    h0, h1 = hole[0][0], hole[1][0]
    high, low = max(h0, h1), min(h0, h1)
    suited = hole[0][1] == hole[1][1]
    pair = h0 == h1

    # Pre-flop hand strength filter
    if street == 'preflop':
        strong = (pair and high >= 7) or high >= 13 or (high == 14) or \
                 (high >= 11 and low >= 9) or (high >= 10 and suited and low >= 8)
        decent = pair or (high >= 10) or (suited and high - low <= 4)
        if strong:
            return ('raise', min(my_chips, max(min_raise, int(pot * 3.0))))
        if decent and call_amount <= 100:
            return ('call', call_amount)
        return ('fold', 0)

    eq = estimate_equity(hole, community, opponents, iterations=150)
    if eq > 0.60:
        return ('raise', min(my_chips, max(min_raise, int(pot * 1.2))))
    if eq > 0.45:
        return ('call', call_amount)
    if call_amount == 0:
        return ('call', 0)
    return ('fold', 0)

# ──────────────────────────────────────────────
# Strategy registry  (index = player number 1-6)
# ──────────────────────────────────────────────

STRATEGIES = [
    ("SimpleAllIn",      strategy_simple_allin),     # Player 1
    ("EquityShark",      strategy_equity_shark),      # Player 2
    ("PositionBully",    strategy_position_bully),    # Player 3
    ("GTO-Ish",          strategy_gto_ish),           # Player 4
    ("StackBully",       strategy_stack_bully),       # Player 5
    ("TightAggressive",  strategy_tag),               # Player 6
]

# ──────────────────────────────────────────────
# Game engine
# ──────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

def play_hand(players):
    """
    Play one hand of Texas Hold'em.
    players: list of dicts {name, chips, strategy_fn, active}
    Returns: (pot won, winner_index or list for split)
    Modifies players[i]['chips'] in place.
    """
    active = [p for p in players if p['chips'] > 0]
    if len(active) < 2:
        return

    n = len(active)
    deck = make_deck()
    random.shuffle(deck)

    # Deal hole cards
    for p in active:
        p['hole'] = [deck.pop(), deck.pop()]
        p['in_hand'] = True
        p['bet_this_street'] = 0

    community = []
    pot = 0
    side_pots = []   # not implemented; we approximate with simple pot

    # Post blinds
    sb_idx = 0
    bb_idx = 1 if n > 1 else 0
    sb_amount = min(SMALL_BLIND, active[sb_idx]['chips'])
    bb_amount = min(BIG_BLIND,   active[bb_idx]['chips'])
    active[sb_idx]['chips']          -= sb_amount
    active[sb_idx]['bet_this_street'] = sb_amount
    active[bb_idx]['chips']          -= bb_amount
    active[bb_idx]['bet_this_street'] = bb_amount
    pot += sb_amount + bb_amount

    def betting_round(street, first_to_act=0):
        nonlocal pot
        current_bet = max(p['bet_this_street'] for p in active)
        min_raise   = max(BIG_BLIND, current_bet * 2)
        acted       = set()
        order       = list(range(first_to_act, n)) + list(range(0, first_to_act))

        while True:
            progress = False
            for i in order:
                p = active[i]
                if not p['in_hand']:
                    continue
                if p['chips'] == 0:
                    acted.add(i)
                    continue

                alive_in_hand = [x for x in active if x['in_hand']]
                if len(alive_in_hand) <= 1:
                    return

                call_amount = max(0, current_bet - p['bet_this_street'])
                call_amount = min(call_amount, p['chips'])

                opponents = len([x for x in active if x['in_hand'] and x is not p])
                action, amount = p['strategy_fn'](
                    p['hole'], community, pot, p['chips'],
                    call_amount, min_raise, opponents, street
                )

                if action == 'fold':
                    p['in_hand'] = False
                    acted.add(i)
                    progress = True
                elif action == 'call':
                    contrib = min(call_amount, p['chips'])
                    p['chips']             -= contrib
                    p['bet_this_street']   += contrib
                    pot                    += contrib
                    acted.add(i)
                    progress = True
                elif action == 'raise':
                    total_bet = min(p['chips'], max(amount, call_amount))
                    contrib   = total_bet
                    p['chips']             -= contrib
                    p['bet_this_street']   += contrib
                    pot                    += contrib
                    if p['bet_this_street'] > current_bet:
                        current_bet = p['bet_this_street']
                        min_raise   = current_bet * 2
                        acted       = {i}   # re-open action
                    else:
                        acted.add(i)
                    progress = True

            # Stop when everyone who can act has acted and no re-opens pending
            pending = [i for i in order
                       if active[i]['in_hand'] and active[i]['chips'] > 0 and i not in acted]
            if not pending:
                break
            if not progress:
                break

        for p in active:
            p['bet_this_street'] = 0

    # Pre-flop betting (UTG acts first = index 2 wrapping)
    for p in active:
        p['bet_this_street'] = 0
    # restore blinds
    active[sb_idx]['bet_this_street'] = sb_amount
    active[bb_idx]['bet_this_street'] = bb_amount

    first_to_act_preflop = 2 % n
    betting_round('preflop', first_to_act_preflop)

    in_hand = [p for p in active if p['in_hand']]
    if len(in_hand) == 1:
        in_hand[0]['chips'] += pot
        return

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    betting_round('flop', 0)
    in_hand = [p for p in active if p['in_hand']]
    if len(in_hand) == 1:
        in_hand[0]['chips'] += pot
        return

    # Turn
    community.append(deck.pop())
    betting_round('turn', 0)
    in_hand = [p for p in active if p['in_hand']]
    if len(in_hand) == 1:
        in_hand[0]['chips'] += pot
        return

    # River
    community.append(deck.pop())
    betting_round('river', 0)
    in_hand = [p for p in active if p['in_hand']]
    if len(in_hand) == 1:
        in_hand[0]['chips'] += pot
        return

    # Showdown
    if in_hand:
        values = [(best_hand(p['hole'] + community), p) for p in in_hand]
        best_val = max(v for v, _ in values)
        winners  = [p for v, p in values if v == best_val]
        share    = pot // len(winners)
        remainder = pot - share * len(winners)
        for w in winners:
            w['chips'] += share
        winners[0]['chips'] += remainder   # give leftover to first winner


def play_tournament(starting_chips=STARTING_CHIPS):
    """
    Play a full tournament (last player standing).
    Returns the name of the winner.
    """
    players = [
        {'name': s[0], 'chips': starting_chips, 'strategy_fn': s[1],
         'hole': [], 'in_hand': True, 'bet_this_street': 0}
        for s in STRATEGIES
    ]

    hand_count = 0
    max_hands  = 5000   # safety cap

    while sum(1 for p in players if p['chips'] > 0) > 1 and hand_count < max_hands:
        # Rotate dealer position by shuffling active list order
        active = [p for p in players if p['chips'] > 0]
        random.shuffle(active)   # randomise seat order each hand
        play_hand(active)
        hand_count += 1

    survivors = [p for p in players if p['chips'] > 0]
    if survivors:
        return max(survivors, key=lambda p: p['chips'])['name']
    return "Draw"


# ──────────────────────────────────────────────
# Run 100 tournaments and print histogram
# ──────────────────────────────────────────────

def run_simulations(n=100):
    print(f"\n{'='*60}")
    print(f"  Texas Hold'em — {n} Tournament Simulations")
    print(f"  {len(STRATEGIES)} players, each starts with {STARTING_CHIPS} chips")
    print(f"{'='*60}\n")
    print("  Player strategies:")
    for i, (name, _) in enumerate(STRATEGIES, 1):
        tag = " ← THE SIMPLE ALL-IN MANIAC" if i == 1 else ""
        print(f"    Player {i}: {name}{tag}")
    print()

    results = Counter()
    for i in range(n):
        winner = play_tournament()
        results[winner] += 1
        if (i+1) % 10 == 0:
            print(f"  Simulations completed: {i+1}/{n}", flush=True)

    print(f"\n{'='*60}")
    print("  RESULTS — Last Player Standing (Winner Winner Chicken Dinner)")
    print(f"{'='*60}\n")

    # Sort by wins descending
    ordered = sorted(STRATEGIES, key=lambda s: results[s[0]], reverse=True)
    max_wins = max(results.values()) if results else 1
    bar_width = 40

    for rank, (name, _) in enumerate(ordered, 1):
        wins    = results[name]
        pct     = wins / n * 100
        bar_len = int(wins / max_wins * bar_width)
        bar     = '█' * bar_len + '░' * (bar_width - bar_len)
        marker  = " ◄ ALL-IN MANIAC" if name == "SimpleAllIn" else ""
        print(f"  #{rank:1d} {name:<20s} {bar} {wins:3d}/{n}  ({pct:5.1f}%){marker}")

    print()
    champion = ordered[0][0]
    print(f"  CHAMPION: {champion}")
    if champion == "SimpleAllIn":
        print("  ChatGPT would NOT have predicted this. Chaos reigns.")
    else:
        print(f"  The elaborate strategies prevailed. Skill beats reckless all-ins — eventually.")
    print(f"\n{'='*60}\n")

    return results


if __name__ == '__main__':
    random.seed(42)
    run_simulations(100)
