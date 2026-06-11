"""
Texas Hold'em 100-simulation tournament.
Player 1  : The Maniac — always shoves all-in, every turn, no questions asked.
Players 2-6: Five elaborate strategy bots.
Last player with chips wins the tournament.
Run 100 tournaments, print ASCII histogram of winners.

Speed note: equity is estimated with fast heuristics (hand-rank score + board
texture) rather than full Monte Carlo, keeping each tournament under a second.
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}  # 2=0 … A=12

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ---------------------------------------------------------------------------
# Hand evaluator — returns comparable tuple (higher = better)
# ---------------------------------------------------------------------------
def hand_rank(cards):
    best = None
    for combo in combinations(cards, 5):
        score = eval5(combo)
        if best is None or score > best:
            best = score
    return best

def eval5(cards):
    vals  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (vals == list(range(vals[0], vals[0]-5, -1)) or
                vals == [12, 3, 2, 1, 0])
    if straight and vals[0] == 12 and vals[1] == 3:
        vals = [3, 2, 1, 0, -1]
    cnt = Counter(vals)
    groups = sorted(cnt.keys(), key=lambda v: (cnt[v], v), reverse=True)
    counts = sorted(cnt.values(), reverse=True)
    if flush and straight:   return (8, vals)
    if counts[0] == 4:       return (7, groups)
    if counts[:2] == [3, 2]: return (6, groups)
    if flush:                return (5, vals)
    if straight:             return (4, vals)
    if counts[0] == 3:       return (3, groups)
    if counts[:2] == [2, 2]: return (2, groups)
    if counts[0] == 2:       return (1, groups)
    return (0, vals)

# ---------------------------------------------------------------------------
# Fast equity estimator — lightweight Monte Carlo (25 trials only)
# ---------------------------------------------------------------------------
def estimate_equity(hole, community, num_opponents, trials=25):
    deck = [c for c in make_deck() if c not in hole and c not in community]
    random.shuffle(deck)
    wins = 0
    needed = 5 - len(community)
    for t in range(trials):
        # rotate a chunk of the deck as "random draw"
        start = t * (needed + num_opponents * 2) % max(1, len(deck) - needed - num_opponents*2)
        chunk = deck[start:]
        board = list(community) + chunk[:needed]
        opp_hands = []
        for i in range(num_opponents):
            h = chunk[needed + i*2: needed + i*2 + 2]
            if len(h) < 2:
                break
            opp_hands.append(h)
        my_score = hand_rank(hole + board)
        best_opp = max((hand_rank(oh + board) for oh in opp_hands), default=(-1, []))
        if my_score > best_opp:
            wins += 1
    return wins / trials

# ---------------------------------------------------------------------------
# Preflop hand strength heuristic (Chen-inspired, no MC needed)
# ---------------------------------------------------------------------------
def preflop_strength(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited  = hole[0][1] == hole[1][1]
    hi, lo  = max(r1, r2), min(r1, r2)
    gap     = hi - lo

    # Pair
    if gap == 0:
        return 0.5 + hi / 24.0          # AA≈1.0, 22≈0.5

    score = (hi * 0.04) + (lo * 0.02)
    if suited:
        score += 0.04
    if gap == 1:
        score += 0.03
    elif gap > 3:
        score -= 0.05 * (gap - 3)

    return max(0.1, min(0.75, score))

# ---------------------------------------------------------------------------
# Player
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid          = pid
        self.chips        = chips
        self.strategy_fn  = strategy_fn
        self.hole         = []
        self.bet_in_round = 0
        self.folded       = False
        self.all_in       = False

    def reset_for_hand(self):
        self.hole         = []
        self.bet_in_round = 0
        self.folded       = False
        self.all_in       = False

# ---------------------------------------------------------------------------
# Strategy 1: The Maniac — always all-in
# ---------------------------------------------------------------------------
def strategy_maniac(player, gs):
    return ('raise', player.chips)

# ---------------------------------------------------------------------------
# Strategy 2: GTO-Ish — equity + pot-odds + position sizing
# ---------------------------------------------------------------------------
def strategy_gto(player, gs):
    hole      = player.hole
    community = gs['community']
    pot       = gs['pot']
    to_call   = gs['to_call']
    n_opp     = max(1, gs['num_active'] - 1)
    position  = gs['position']
    street    = gs['street']

    equity = (preflop_strength(hole) if street == 'preflop'
              else estimate_equity(hole, community, n_opp))

    pot_odds = to_call / (pot + to_call + 1e-9)

    if equity < pot_odds - 0.03:
        return ('check', 0) if to_call == 0 else ('fold', 0)

    edge = equity - pot_odds
    if edge > 0.20 and position == 2:
        return ('raise', min(player.chips, int(pot * 1.5) + 1))
    if equity > 0.60:
        return ('raise', min(player.chips, int(pot * 0.75) + 1))
    if equity > pot_odds:
        return ('check', 0) if to_call == 0 else ('call', to_call)
    return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 3: TAG — tight preflop, aggressive postflop with strong hands
# ---------------------------------------------------------------------------
PREMIUM = {('A','A'),('K','K'),('Q','Q'),('J','J'),('T','T'),
           ('A','K'),('A','Q'),('A','J'),('K','Q')}

def strategy_tag(player, gs):
    hole    = player.hole
    pot     = gs['pot']
    to_call = gs['to_call']
    street  = gs['street']
    n_opp   = max(1, gs['num_active'] - 1)

    r1, r2   = hole[0][0], hole[1][0]
    suited   = hole[0][1] == hole[1][1]
    pair_key = tuple(sorted([r1, r2], key=lambda r: RANK_VAL[r], reverse=True))
    premium  = (pair_key in PREMIUM or
                (suited and pair_key in {('A','K'),('A','Q'),('K','Q')}))

    if street == 'preflop':
        if premium:
            return ('raise', min(player.chips, max(to_call * 3, int(pot) + 20)))
        return ('check', 0) if to_call == 0 else ('fold', 0)

    equity = estimate_equity(hole, gs['community'], n_opp)
    if equity > 0.70:
        return ('raise', min(player.chips, int(pot * 1.2) + 1))
    if equity > 0.50:
        return ('check', 0) if to_call == 0 else ('call', to_call)
    return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 4: LAG — loose range, frequent bluffs, variable sizing
# ---------------------------------------------------------------------------
def strategy_lag(player, gs):
    hole      = player.hole
    pot       = gs['pot']
    to_call   = gs['to_call']
    street    = gs['street']
    n_opp     = max(1, gs['num_active'] - 1)

    equity = (preflop_strength(hole) if street == 'preflop'
              else estimate_equity(hole, gs['community'], n_opp))

    bluff = random.random() < 0.38

    if equity > 0.52 or bluff:
        size = min(player.chips, int(pot * random.uniform(0.5, 1.8)) + 1)
        return ('raise', max(1, size))
    if equity > 0.33:
        return ('check', 0) if to_call == 0 else ('call', to_call)
    return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 5: Exploitative — adapts to observed table aggression
# ---------------------------------------------------------------------------
def strategy_exploitative(player, gs):
    hole        = player.hole
    pot         = gs['pot']
    to_call     = gs['to_call']
    street      = gs['street']
    n_opp       = max(1, gs['num_active'] - 1)
    aggression  = gs.get('table_aggression', 0.5)

    equity = (preflop_strength(hole) if street == 'preflop'
              else estimate_equity(hole, gs['community'], n_opp))

    if aggression > 0.65:          # maniacs at table — trap / call-down
        if equity > 0.72:
            return ('call', to_call) if to_call > 0 else ('check', 0)
        if equity > 0.48:
            return ('call', min(to_call, int(player.chips * 0.3))) if to_call > 0 else ('check', 0)
        return ('check', 0) if to_call == 0 else ('fold', 0)
    else:                          # passive table — bet for value
        if equity > 0.55:
            return ('raise', min(player.chips, int(pot * 0.9) + 1))
        if equity > 0.38:
            return ('check', 0) if to_call == 0 else ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 6: ICM-Aware — stack-size discipline, shove/fold when short
# ---------------------------------------------------------------------------
def strategy_icm(player, gs):
    hole       = player.hole
    pot        = gs['pot']
    to_call    = gs['to_call']
    street     = gs['street']
    n_opp      = max(1, gs['num_active'] - 1)
    avg_stack  = gs.get('avg_stack', player.chips)

    equity     = (preflop_strength(hole) if street == 'preflop'
                  else estimate_equity(hole, gs['community'], n_opp))
    stack_ratio = player.chips / max(1, avg_stack)

    if stack_ratio < 0.4:          # short stack — jam or fold
        if equity > 0.42:
            return ('raise', player.chips)
        return ('check', 0) if to_call == 0 else ('fold', 0)

    if equity > 0.70:
        return ('raise', min(player.chips, int(pot * 0.85) + 1))
    if equity > 0.52:
        cap = int(player.chips * 0.22)
        return ('check', 0) if to_call == 0 else ('call', min(to_call, cap))
    pot_odds = to_call / (pot + to_call + 1e-9)
    if equity > pot_odds * 1.05:
        return ('call', to_call) if to_call > 0 else ('check', 0)
    return ('check', 0) if to_call == 0 else ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------
STRATEGIES = [
    ("The Maniac",   strategy_maniac),
    ("GTO-Ish",      strategy_gto),
    ("TAG",          strategy_tag),
    ("LAG",          strategy_lag),
    ("Exploitative", strategy_exploitative),
    ("ICM-Aware",    strategy_icm),
]

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

# ---------------------------------------------------------------------------
# Tournament runner
# ---------------------------------------------------------------------------
def run_tournament():
    players = [Player(i+1, STARTING_CHIPS, STRATEGIES[i][1]) for i in range(6)]
    hand_count = 0
    while sum(1 for p in players if p.chips > 0) > 1 and hand_count < 2000:
        hand_count += 1
        active = [p for p in players if p.chips > 0]
        if len(active) < 2:
            break
        play_hand(active)
    survivors = [p for p in players if p.chips > 0]
    return max(survivors, key=lambda p: p.chips).pid if survivors else None

# ---------------------------------------------------------------------------
# Hand engine
# ---------------------------------------------------------------------------
def play_hand(active):
    for p in active:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    idx = 0
    for p in active:
        p.hole = [deck[idx], deck[idx+1]]
        idx += 2

    community       = []
    pot             = 0
    table_aggression = random.uniform(0.3, 0.85)
    avg_stack        = sum(p.chips for p in active) / len(active)

    # Post blinds
    sb_player = active[0]
    bb_player = active[1] if len(active) > 1 else active[0]
    for pl, amount in [(sb_player, SMALL_BLIND), (bb_player, BIG_BLIND)]:
        amt = min(amount, pl.chips)
        pl.chips -= amt
        pl.bet_in_round = amt
        if pl.chips == 0:
            pl.all_in = True
        pot += amt

    card_cursor = idx
    for street, num_cards in [('preflop',0),('flop',3),('turn',1),('river',1)]:
        if num_cards:
            community.extend(deck[card_cursor:card_cursor + num_cards])
            card_cursor += num_cards

        pot = betting_round(street, active, community, pot, table_aggression, avg_stack)

        still_in = [p for p in active if not p.folded]
        if len(still_in) <= 1:
            break

    # Showdown
    still_in = [p for p in active if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
    else:
        scores  = sorted([(hand_rank(p.hole + community), p) for p in still_in],
                         key=lambda x: x[0], reverse=True)
        best    = scores[0][0]
        winners = [p for sc, p in scores if sc == best]
        share, rem = divmod(pot, len(winners))
        for w in winners:
            w.chips += share
        winners[0].chips += rem

# ---------------------------------------------------------------------------
# Betting round
# ---------------------------------------------------------------------------
def betting_round(street, active, community, pot, table_aggression, avg_stack):
    eligible = [p for p in active if not p.folded and not p.all_in]
    if not eligible:
        return pot

    if street != 'preflop':
        for p in active:
            p.bet_in_round = 0

    current_bet = max(p.bet_in_round for p in active)

    # Preflop: UTG acts first (after blinds)
    order = (active[2:] + active[:2]) if (street == 'preflop' and len(active) > 2) else list(active)

    MAX_RAISES = 4
    raises = 0
    acted  = set()

    for _ in range(len(active) * (MAX_RAISES + 3)):
        # Find next player who must act
        todo = [p for p in order
                if not p.folded and not p.all_in
                and (p.bet_in_round < current_bet or p.pid not in acted)]
        if not todo:
            break

        p = todo[0]
        to_call = min(max(0, current_bet - p.bet_in_round), p.chips)
        num_active = len([x for x in active if not x.folded])
        position   = 2 if order.index(p) >= len(order) - 2 else (1 if order.index(p) > 0 else 0)

        gs = {
            'street':           street,
            'community':        community,
            'pot':              pot,
            'to_call':          to_call,
            'num_active':       num_active,
            'position':         position,
            'table_aggression': table_aggression,
            'avg_stack':        avg_stack,
        }

        action, amount = p.strategy_fn(p, gs)

        if action == 'fold':
            p.folded = True
            if len([x for x in active if not x.folded]) == 1:
                break

        elif action == 'check':
            acted.add(p.pid)

        elif action == 'call':
            amount = min(to_call, p.chips)
            p.chips -= amount
            p.bet_in_round += amount
            pot += amount
            if p.chips == 0:
                p.all_in = True
            acted.add(p.pid)

        elif action == 'raise':
            if raises >= MAX_RAISES:
                # Cap: treat as call
                amount = min(to_call, p.chips)
                p.chips -= amount
                p.bet_in_round += amount
                pot += amount
                if p.chips == 0:
                    p.all_in = True
                acted.add(p.pid)
            else:
                total = min(max(1, amount), p.chips)
                p.chips -= total
                p.bet_in_round += total
                pot += total
                if p.chips == 0:
                    p.all_in = True
                if p.bet_in_round > current_bet:
                    current_bet = p.bet_in_round
                    raises += 1
                    acted = {p.pid}   # re-open action
                else:
                    acted.add(p.pid)

        # Early exit: everyone matched or folded/all-in
        live = [x for x in active if not x.folded and not x.all_in]
        if all(x.bet_in_round >= current_bet for x in live):
            if all(x.pid in acted for x in live):
                break

    return pot

# ---------------------------------------------------------------------------
# Run 100 tournaments & histogram
# ---------------------------------------------------------------------------
def run_simulations(n=100):
    results = Counter()
    for i in range(n):
        wid = run_tournament()
        if wid:
            results[wid] += 1
    return results

def print_histogram(results, n_sims):
    print("\n" + "="*65)
    print("   TEXAS HOLD'EM — 100-TOURNAMENT CHAMPIONSHIP RESULTS")
    print("   Last player standing wins each tournament.")
    print("="*65)
    max_wins = max(results.values()) if results else 1
    BAR = 38
    for pid, (name, _) in enumerate(STRATEGIES, start=1):
        wins = results.get(pid, 0)
        pct  = wins / n_sims * 100
        bar  = "█" * int(wins / max_wins * BAR)
        tag  = " ◄ ALWAYS ALL-IN" if pid == 1 else ""
        print(f"  P{pid} {name:<14} |{bar:<38}| {wins:3d} ({pct:5.1f}%){tag}")
    print("="*65)
    best  = max(results, key=results.get) if results else None
    worst = min(results, key=results.get) if results else None
    if best:
        print(f"\n  CHAMPION  : P{best} {STRATEGIES[best-1][0]} — {results[best]} wins")
    if worst and worst != best:
        print(f"  HUMILIATED: P{worst} {STRATEGIES[worst-1][0]} — only {results[worst]} wins\n")

if __name__ == "__main__":
    random.seed(42)
    print("Running 100 Texas Hold'em tournament simulations…")
    results = run_simulations(100)
    print_histogram(results, 100)
