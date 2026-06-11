import random
from collections import Counter
from itertools import combinations

# ─── Card utilities ───────────────────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ─── Hand evaluator (7-card best 5) ───────────────────────────────────────────

def hand_rank(cards):
    best = None
    for five in combinations(cards, 5):
        score = eval5(five)
        if best is None or score > best:
            best = score
    return best

def eval5(cards):
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    uniq = sorted(set(vals), reverse=True)
    straight = len(uniq) == 5 and (uniq[0] - uniq[4] == 4)
    wheel = uniq == [14, 5, 4, 3, 2]
    if wheel:
        straight = True
        vals = [5, 4, 3, 2, 1]
    cnt = Counter(vals)
    groups = sorted(cnt.keys(), key=lambda v: (cnt[v], v), reverse=True)
    counts = sorted(cnt.values(), reverse=True)
    if flush and straight:   return (8,) + tuple(vals)
    if counts[0] == 4:       return (7,) + tuple(groups)
    if counts[:2] == [3, 2]: return (6,) + tuple(groups)
    if flush:                return (5,) + tuple(vals)
    if straight:             return (4,) + tuple(vals)
    if counts[0] == 3:       return (3,) + tuple(groups)
    if counts[:2] == [2, 2]: return (2,) + tuple(groups)
    if counts[0] == 2:       return (1,) + tuple(groups)
    return (0,) + tuple(vals)

# ─── Fast heuristic strength (no simulation) ──────────────────────────────────
# Returns 0.0–1.0 estimate; fast enough for 10k decisions/sec.

def estimate_strength(hole, community):
    all_cards = hole + community
    if len(community) >= 3:
        # We have a real board — score our 5-7 card hand
        score = hand_rank(all_cards)
        cat = score[0]
        # Map hand category to rough win probability
        base = [0.15, 0.35, 0.50, 0.62, 0.72, 0.82, 0.88, 0.93, 0.99][cat]
        # tiebreak within category: top card relative to max (14)
        top = score[1] / 14.0 * 0.08
        return min(0.99, base + top)
    else:
        # Preflop: use Chen-style heuristic
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited = hole[0][1] == hole[1][1]
        hi, lo = max(r1, r2), min(r1, r2)
        score = hi / 14.0  # base: high card quality
        if r1 == r2:       score += 0.20  # pocket pair
        if suited:         score += 0.06
        gap = hi - lo
        if gap == 0:       score += 0.05
        elif gap == 1:     score += 0.03
        elif gap == 2:     score += 0.01
        return min(0.99, score * 0.75)

# ─── Player ───────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = strategy_fn
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

# ─── 6 Strategies ─────────────────────────────────────────────────────────────

def strategy_all_in(player, gs):
    """P1: always shove everything, every street, no mercy."""
    return ('raise', player.chips)


def strategy_tight_aggressive(player, gs):
    """Play only strong hands; fold weak ones; raise when ahead."""
    s = estimate_strength(player.hole, gs['community'])
    to_call, pot, chips = gs['to_call'], gs['pot'], player.chips
    if s >= 0.78:
        return ('raise', min(chips, max(pot, to_call * 3, 1)))
    if s >= 0.55:
        if to_call == 0: return ('check', 0)
        if to_call <= chips * 0.15: return ('call', to_call)
        return ('fold', 0)
    if to_call == 0: return ('check', 0)
    return ('fold', 0)


def strategy_loose_passive(player, gs):
    """Call a lot, seldom raise, chase draws."""
    s = estimate_strength(player.hole, gs['community'])
    to_call, pot, chips = gs['to_call'], gs['pot'], player.chips
    if s >= 0.82:
        return ('raise', min(chips, pot // 2 + 1))
    if s >= 0.22:
        if to_call == 0: return ('check', 0)
        if to_call <= chips: return ('call', min(to_call, chips))
        return ('fold', 0)
    if to_call == 0: return ('check', 0)
    if to_call <= chips * 0.05: return ('call', to_call)
    return ('fold', 0)


def strategy_pot_odds(player, gs):
    """Only commit chips when equity exceeds pot-odds break-even."""
    s = estimate_strength(player.hole, gs['community'])
    to_call, pot, chips = gs['to_call'], gs['pot'], player.chips
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 and to_call > 0 else 0.0
    if s >= 0.78:
        return ('raise', min(chips, pot))
    if s > pot_odds + 0.06:
        if to_call == 0: return ('check', 0)
        return ('call', min(to_call, chips))
    if to_call == 0: return ('check', 0)
    return ('fold', 0)


def strategy_bluffer(player, gs):
    """Mix value-bets with random bluffs; keeps opponents guessing."""
    s = estimate_strength(player.hole, gs['community'])
    to_call, pot, chips = gs['to_call'], gs['pot'], player.chips
    bluff = random.random() < 0.28
    if s >= 0.73 or bluff:
        amt = min(chips, max(pot // 2, to_call * 2, 1))
        return ('raise', amt)
    if s >= 0.38:
        if to_call == 0: return ('check', 0)
        if to_call <= chips * 0.20: return ('call', to_call)
        return ('fold', 0)
    if to_call == 0:
        if random.random() < 0.12:
            return ('raise', min(chips, max(pot // 3, 1)))
        return ('check', 0)
    return ('fold', 0)


def strategy_adaptive(player, gs):
    """Tightens up under aggression; loosens when opponents are passive."""
    s = estimate_strength(player.hole, gs['community'])
    to_call, pot, chips = gs['to_call'], gs['pot'], player.chips
    agg = gs.get('aggression', 0)
    thresh_call  = 0.42 + agg * 0.05
    thresh_raise = 0.68 + agg * 0.03
    if s >= thresh_raise:
        return ('raise', min(chips, max(pot // 2, to_call * 2, 1)))
    if s >= thresh_call:
        if to_call == 0: return ('check', 0)
        if to_call <= chips * 0.25: return ('call', min(to_call, chips))
        return ('fold', 0)
    if to_call == 0: return ('check', 0)
    return ('fold', 0)

# ─── Betting round ────────────────────────────────────────────────────────────

def betting_round(alive, pot, community, sb_idx, street, bb_amount=0):
    active = [p for p in alive if not p.folded and not p.all_in]
    if len(active) <= 1:
        return pot

    for p in alive:
        p.bet = 0

    current_bet = bb_amount if street == 'preflop' else 0
    aggression = 0

    # Build action order
    order = [p for p in alive if not p.folded and not p.all_in]
    if street == 'preflop' and len(order) > 0:
        start = (sb_idx + 2) % len(order)
        order = order[start:] + order[:start]

    acted = set()
    i = 0
    max_iter = 4 * len(alive) + 8

    for _ in range(max_iter):
        if i >= len(order):
            i = 0
        p = order[i]
        i += 1
        if p.folded or p.all_in:
            continue

        to_call = max(0, current_bet - p.bet)
        gs = {
            'community': community,
            'to_call': min(to_call, p.chips),
            'pot': pot,
            'aggression': aggression,
        }

        action, amount = p.strategy_fn(p, gs)

        if action == 'fold':
            p.folded = True
            acted.add(p.pid)
        elif action == 'check':
            acted.add(p.pid)
        elif action == 'call':
            amt = min(amount, p.chips, max(to_call, 0))
            p.chips -= amt
            p.bet += amt
            pot += amt
            if p.chips == 0:
                p.all_in = True
            acted.add(p.pid)
        elif action == 'raise':
            call_amt = min(to_call, p.chips)
            extra = min(amount, p.chips - call_amt)
            total = call_amt + max(extra, 0)
            p.chips -= total
            p.bet += total
            pot += total
            if total > call_amt:  # actual raise happened
                current_bet = p.bet
                aggression += 1
                acted = {p.pid}
            else:
                acted.add(p.pid)
            if p.chips == 0:
                p.all_in = True

        # Done when all non-folded, non-allin players have acted + matched bet
        still = [x for x in order if not x.folded and not x.all_in]
        if all(x.pid in acted and x.bet >= current_bet for x in still):
            break

    return pot

# ─── Single hand ──────────────────────────────────────────────────────────────

def play_hand(players, dealer_idx, small_blind, big_blind):
    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return

    for p in alive:
        p.reset_hand()

    deck = make_deck()
    random.shuffle(deck)

    n = len(alive)
    sb_idx = dealer_idx % n
    bb_idx = (dealer_idx + 1) % n

    sb_p = alive[sb_idx]
    bb_p = alive[bb_idx]
    sb_amt = min(small_blind, sb_p.chips)
    bb_amt = min(big_blind, bb_p.chips)
    sb_p.chips -= sb_amt;  sb_p.bet = sb_amt
    bb_p.chips -= bb_amt;  bb_p.bet = bb_amt
    if sb_p.chips == 0: sb_p.all_in = True
    if bb_p.chips == 0: bb_p.all_in = True
    pot = sb_amt + bb_amt

    card_i = 0
    for p in alive:
        p.hole = [deck[card_i], deck[card_i + 1]]
        card_i += 2

    community = []
    for street, n_cards in [('preflop', 0), ('flop', 3), ('turn', 1), ('river', 1)]:
        if n_cards:
            community += deck[card_i:card_i + n_cards]
            card_i += n_cards
        pot = betting_round(alive, pot, list(community), sb_idx, street,
                            bb_amount=(big_blind if street == 'preflop' else 0))
        if len([p for p in alive if not p.folded]) <= 1:
            break

    # Showdown / award pot
    remaining = [p for p in alive if not p.folded]
    if not remaining:
        alive[0].chips += pot  # edge case: give to first
        return
    if len(remaining) == 1:
        remaining[0].chips += pot
        return

    scores = [(hand_rank(p.hole + community), p) for p in remaining]
    best = max(s for s, _ in scores)
    winners = [p for s, p in scores if s == best]
    share = pot // len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += pot - share * len(winners)

# ─── Full tournament ──────────────────────────────────────────────────────────

STRATEGIES = [
    ('AllIn♠',           strategy_all_in),
    ('TightAggro',       strategy_tight_aggressive),
    ('LoosePassive',     strategy_loose_passive),
    ('PotOdds',          strategy_pot_odds),
    ('Bluffer',          strategy_bluffer),
    ('Adaptive',         strategy_adaptive),
]

def run_tournament(starting_chips=1500, small_blind=10, big_blind=20, max_hands=3000):
    players = [Player(i + 1, starting_chips, STRATEGIES[i][1]) for i in range(6)]
    dealer_idx = 0
    sb = small_blind
    bb = big_blind

    for hand_num in range(max_hands):
        alive_count = sum(1 for p in players if p.chips > 0)
        if alive_count <= 1:
            break
        play_hand(players, dealer_idx % 6, sb, bb)
        dealer_idx += 1
        if hand_num > 0 and hand_num % 150 == 0:
            sb = min(sb * 2, starting_chips // 6)
            bb = sb * 2

    survivors = [p for p in players if p.chips > 0]
    if not survivors:
        return random.randint(1, 6)
    return max(survivors, key=lambda p: p.chips).pid

# ─── 100 simulations ──────────────────────────────────────────────────────────

def run_sims(n=100):
    wins = Counter()
    for i in range(n):
        wins[run_tournament()] += 1
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{n} tournaments complete...")
    return wins

# ─── Histogram ────────────────────────────────────────────────────────────────

def print_histogram(wins, n=100):
    bar_max = 40
    max_w = max(wins.values()) if wins else 1
    print()
    print("=" * 68)
    print("   TEXAS HOLD'EM  ·  100 TOURNAMENTS  ·  WINNER WINNER CHICKEN DINNER")
    print("=" * 68)
    print(f"  {'Player':<24}  {'Wins':>4}  {'Bar (scaled)'}")
    print("  " + "-" * 64)
    for pid, (name, _) in enumerate(STRATEGIES, 1):
        w = wins.get(pid, 0)
        bar = '█' * int(w / max_w * bar_max)
        tag = " ← ALL-IN MANIAC" if pid == 1 else ""
        print(f"  P{pid} {name:<22} {w:>3}  {bar}{tag}")
    print("=" * 68)
    champ_pid = wins.most_common(1)[0][0]
    champ_name = STRATEGIES[champ_pid - 1][0]
    allin_wins = wins.get(1, 0)
    print(f"\n  CHAMPION: P{champ_pid} {champ_name}  ({wins[champ_pid]} wins)")
    if champ_pid == 1:
        print("  The all-in degenerate YEETED the galaxy-brains into oblivion.")
        print("  GPT could never. Suflair stays pressed. 🐔💸")
    else:
        pct = allin_wins
        print(f"  The all-in maniac survived {pct} times — chaos monkey tax paid.")
        print(f"  Strategy beats randomness. Suflair stays humiliated regardless.")
    print()

# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    random.seed(42)
    print("┌─────────────────────────────────────────────────┐")
    print("│  Texas Hold'em  ·  6 Players  ·  100 Tournaments │")
    print("└─────────────────────────────────────────────────┘")
    print()
    print("  Strategies:")
    for i, (name, _) in enumerate(STRATEGIES, 1):
        tag = " ← THE DEGENERATE (all-in every single hand)" if i == 1 else ""
        print(f"    P{i}: {name}{tag}")
    print()
    wins = run_sims(100)
    print_histogram(wins)
