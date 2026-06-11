"""
Texas Hold'em Poker Tournament Simulation
- Player 1: The Degenerate (always goes all-in)
- Players 2-6: Five elaborate strategy bots
- 100 tournaments, histogram of last-man-standing winners

Fast version: hand strength via lightweight rank-based heuristics
instead of per-decision Monte Carlo (100x speed-up).
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

RANKS = list(range(2, 15))  # 2..14, Ace=14
SUITS = ['s', 'h', 'd', 'c']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',
              9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ---------------------------------------------------------------------------
# 5-card hand evaluator — (category, tiebreakers), higher = better
# 8=SF  7=Quads  6=FullHouse  5=Flush  4=Straight
# 3=Trips  2=TwoPair  1=Pair  0=HighCard
# ---------------------------------------------------------------------------

def best_hand(cards):
    best = None
    for combo in combinations(cards, 5):
        v = eval5(combo)
        if best is None or v > best:
            best = v
    return best

def eval5(cards):
    ranks  = sorted([c[0] for c in cards], reverse=True)
    suits  = [c[1] for c in cards]
    flush  = len(set(suits)) == 1
    uniq   = len(set(ranks)) == 5
    straight, s_high = False, 0
    if uniq and ranks[0] - ranks[4] == 4:
        straight, s_high = True, ranks[0]
    if set(ranks) == {14, 2, 3, 4, 5}:
        straight, s_high = True, 5
    cnt     = sorted(Counter(ranks).items(), key=lambda x: (x[1], x[0]), reverse=True)
    grouped = [r for r, _ in cnt]
    freq    = [f for _, f in cnt]
    if flush and straight:   return (8, s_high)
    if freq[0] == 4:         return (7, grouped[0], grouped[1])
    if freq[0]==3 and freq[1]==2: return (6, grouped[0], grouped[1])
    if flush:                return (5, *ranks)
    if straight:             return (4, s_high)
    if freq[0] == 3:         return (3, grouped[0], *sorted(grouped[1:], reverse=True))
    if freq[0]==2 and freq[1]==2:
        p1, p2 = sorted([grouped[0], grouped[1]], reverse=True)
        return (2, p1, p2, grouped[2])
    if freq[0] == 2:         return (1, grouped[0], *grouped[1:])
    return (0, *ranks)

# ---------------------------------------------------------------------------
# Fast hand-strength heuristic (no Monte Carlo)
# Returns float 0..1 — higher = stronger hand
# ---------------------------------------------------------------------------

def hand_strength(hole, community):
    """
    Pre-flop: Chen formula approximation.
    Post-flop: ratio of current hand category to max (8).
    Adjusted for outs / draw potential.
    """
    if not community:
        return _preflop_strength(hole)
    cards  = hole + community
    val    = best_hand(cards)
    cat    = val[0]
    # Base score 0..1 from category
    base   = cat / 8.0
    # Bonus for draws on flop/turn
    bonus  = _draw_bonus(hole, community) if len(community) < 5 else 0.0
    return min(1.0, base * 0.80 + bonus + 0.05 * (cat >= 3))

def _preflop_strength(hole):
    r1, r2  = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited  = hole[0][1] == hole[1][1]
    paired  = r1 == r2
    # Pocket pair
    if paired:
        return 0.30 + (r1 - 2) / 12.0 * 0.55
    gap     = r1 - r2
    high    = r1 / 14.0
    s_bonus = 0.04 if suited else 0.0
    conn    = max(0, 0.08 - gap * 0.02)
    return min(0.95, 0.15 + high * 0.45 + conn + s_bonus)

def _draw_bonus(hole, community):
    """Rough flush/straight draw bonus."""
    cards   = hole + community
    suits_c = Counter(c[1] for c in cards)
    flush_draw = any(v >= 4 for v in suits_c.values())
    ranks   = sorted(set(c[0] for c in cards))
    # Check for 4-card straight draw
    str_draw = False
    for i in range(len(ranks) - 3):
        if ranks[i+3] - ranks[i] <= 4:
            str_draw = True; break
    return (0.12 if flush_draw else 0) + (0.08 if str_draw else 0)

# Relative strength vs n opponents: P(win) ≈ strength^n  (rough but fast)
def win_probability(hole, community, n_opponents):
    s = hand_strength(hole, community)
    if n_opponents <= 0:
        return 1.0
    return s ** (1.0 / max(1, n_opponents))  # gentler curve

# ---------------------------------------------------------------------------
# Street constants
# ---------------------------------------------------------------------------
PRE_FLOP, FLOP, TURN, RIVER = 0, 1, 2, 3

# ---------------------------------------------------------------------------
# Strategy 1 — The Degenerate  (always all-in — the chaos agent)
# ---------------------------------------------------------------------------

def strategy_degenerate(hole, community, pot, my_chips, to_call,
                         min_raise, street, position, n_active, history):
    """If my_turn then bet = ALL IN fi"""
    return ('allin', my_chips)

# ---------------------------------------------------------------------------
# Strategy 2 — The Mathematician  (pot-odds vs hand equity)
# ---------------------------------------------------------------------------

def strategy_mathematician(hole, community, pot, my_chips, to_call,
                            min_raise, street, position, n_active, history):
    equity   = win_probability(hole, community, n_active - 1)
    pot_odds = to_call / (pot + to_call + 1e-9)
    if equity < pot_odds * 0.80:
        return ('fold', 0) if to_call > 0 else ('check', 0)
    if equity > 0.78:
        bet = min(my_chips, max(min_raise, int(pot * 0.75)))
        return ('raise', bet)
    if to_call == 0:
        return ('check', 0)
    return ('call', min(to_call, my_chips))

# ---------------------------------------------------------------------------
# Strategy 3 — The TAG  (tight-aggressive, premium hands only pre-flop)
# ---------------------------------------------------------------------------

def strategy_tag(hole, community, pot, my_chips, to_call,
                 min_raise, street, position, n_active, history):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    premium = (r1 == r2 and r1 >= 8) or \
              (r1 >= 11 and r2 >= 9)   or \
              (suited and r1 >= 10 and r2 >= 8)
    if street == PRE_FLOP:
        if not premium:
            return ('fold', 0) if to_call > 0 else ('check', 0)
        bet = min(my_chips, max(min_raise * 3, int(pot * 1.0)))
        return ('raise', bet) if bet >= min_raise else ('call', min(to_call, my_chips))
    equity = win_probability(hole, community, n_active - 1)
    if equity > 0.68:
        bet = min(my_chips, max(min_raise, int(pot * 0.85)))
        return ('raise', bet)
    if equity > 0.42:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    return ('fold', 0) if to_call > 0 else ('check', 0)

# ---------------------------------------------------------------------------
# Strategy 4 — The Bluffer  (semi-bluffs + random bluffs, GTO-lite)
# ---------------------------------------------------------------------------

def strategy_bluffer(hole, community, pot, my_chips, to_call,
                     min_raise, street, position, n_active, history):
    equity     = win_probability(hole, community, n_active - 1)
    bluff_freq = 0.28 if street >= TURN else 0.14
    bluffing   = random.random() < bluff_freq
    if bluffing:
        bet = min(my_chips, max(min_raise, int(pot * 0.55)))
        return ('raise', bet)
    if equity > 0.73:
        bet = min(my_chips, max(min_raise, int(pot * 0.90)))
        return ('raise', bet)
    if equity > 0.48:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    if to_call == 0:
        return ('check', 0)
    if to_call <= pot * 0.18:
        return ('call', min(to_call, my_chips))
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 5 — The Positional Shark  (tighter early, looser in position)
# ---------------------------------------------------------------------------

def strategy_positional(hole, community, pot, my_chips, to_call,
                        min_raise, street, position, n_active, history):
    late = position >= n_active * 0.55
    equity = win_probability(hole, community, n_active - 1)
    thr_call  = 0.32 if late else 0.50
    thr_raise = 0.60 if late else 0.72
    if equity > thr_raise:
        size = 1.05 if late else 0.65
        bet  = min(my_chips, max(min_raise, int(pot * size)))
        return ('raise', bet)
    if equity > thr_call:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    if to_call == 0:
        if late and random.random() < 0.20:
            return ('raise', min(my_chips, max(min_raise, int(pot * 0.38))))
        return ('check', 0)
    return ('fold', 0)

# ---------------------------------------------------------------------------
# Strategy 6 — The Stack Bully  (exploits big-stack advantage)
# ---------------------------------------------------------------------------

def strategy_stack_bully(hole, community, pot, my_chips, to_call,
                         min_raise, street, position, n_active, history):
    avg_stack  = history.get('avg_stack', my_chips)
    big_stack  = my_chips >= avg_stack * 1.35
    short_stack= my_chips <= avg_stack * 0.45
    equity     = win_probability(hole, community, n_active - 1)
    if big_stack and equity > 0.42:
        bet = min(my_chips, max(min_raise, int(pot * 1.15)))
        return ('raise', bet)
    if short_stack:
        if equity > 0.60:
            return ('allin', my_chips)
        return ('fold', 0) if to_call > 0 else ('check', 0)
    if equity > 0.68:
        bet = min(my_chips, max(min_raise, int(pot * 0.75)))
        return ('raise', bet)
    if equity > 0.42:
        return ('call', min(to_call, my_chips)) if to_call > 0 else ('check', 0)
    return ('fold', 0) if to_call > 0 else ('check', 0)

# ---------------------------------------------------------------------------
# Strategy registry  (order = player index 0..5)
# ---------------------------------------------------------------------------

STRATEGIES = [
    ("The Degenerate",    strategy_degenerate),    # Player 1
    ("The Mathematician", strategy_mathematician),  # Player 2
    ("The TAG",           strategy_tag),            # Player 3
    ("The Bluffer",       strategy_bluffer),        # Player 4
    ("The Positional",    strategy_positional),     # Player 5
    ("The Stack Bully",   strategy_stack_bully),    # Player 6
]

# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20
MAX_HANDS      = 300

class Player:
    def __init__(self, pid, name, strategy):
        self.pid      = pid
        self.name     = name
        self.strategy = strategy
        self.chips    = STARTING_CHIPS
        self.active   = True
        self.folded   = False
        self.bet      = 0
        self.hole     = []

    def reset_hand(self):
        self.folded = False
        self.bet    = 0
        self.hole   = []

def run_betting_round(players, community, pot, street, dealer_idx):
    active = [p for p in players if p.active and not p.folded]
    if len(active) <= 1:
        return pot

    for p in active:
        p.bet = 0

    current_bet = 0
    min_raise   = BIG_BLIND
    n           = len(players)
    avg_stack   = sum(p.chips for p in active) / max(1, len(active))

    # Action order: left of dealer
    order = []
    i = (dealer_idx + 1) % n
    seen = 0
    while seen < n:
        p = players[i % n]
        if p.active and not p.folded:
            order.append(p)
        i += 1; seen += 1

    acted   = set()
    queue   = list(order)
    safety  = len(order) * 5

    while queue and safety > 0:
        safety -= 1
        player = queue.pop(0)
        if not player.active or player.folded or player.chips == 0:
            acted.add(player.pid); continue
        to_call = max(0, current_bet - player.bet)
        if player.pid in acted and to_call == 0:
            continue

        n_opp    = sum(1 for p in active if p.pid != player.pid and not p.folded)
        pos_idx  = order.index(player) if player in order else 0
        history  = {'avg_stack': avg_stack}

        action, amount = player.strategy(
            player.hole, community, pot, player.chips,
            to_call, min_raise, street, pos_idx, n_opp + 1, history
        )

        if action == 'fold':
            player.folded = True
        elif action == 'check':
            pass
        elif action == 'call':
            amount = min(to_call, player.chips)
            player.chips -= amount; player.bet += amount; pot += amount
        elif action in ('raise', 'allin'):
            if action == 'allin':
                amount = player.chips
            amount      = max(to_call + min_raise, amount)
            amount      = min(amount, player.chips)
            min_raise   = max(min_raise, amount - to_call)
            player.chips -= amount; player.bet += amount; pot += amount
            current_bet  = player.bet
            # Re-open betting for others
            for other in order:
                if other.pid != player.pid and not other.folded \
                        and other.active and other.bet < current_bet:
                    if other.pid in acted:
                        queue.append(other)
                        acted.discard(other.pid)

        acted.add(player.pid)
        if sum(1 for p in active if not p.folded) <= 1:
            break

    return pot

def run_hand(players, dealer_idx):
    n     = len(players)
    alive = [p for p in players if p.active]
    if len(alive) < 2:
        return dealer_idx

    for p in players:
        p.reset_hand()

    deck = make_deck()
    random.shuffle(deck)
    idx  = 0
    for p in alive:
        p.hole = [deck[idx], deck[idx+1]]; idx += 2

    community = []
    pot       = 0

    # Post blinds
    a_list = alive
    sb_pos = (dealer_idx + 1) % n
    while not players[sb_pos % n].active: sb_pos += 1
    bb_pos = sb_pos + 1
    while not players[bb_pos % n].active: bb_pos += 1

    sb_p = players[sb_pos % n]; bb_p = players[bb_pos % n]
    sb_a = min(SMALL_BLIND, sb_p.chips)
    bb_a = min(BIG_BLIND,   bb_p.chips)
    sb_p.chips -= sb_a; sb_p.bet = sb_a; pot += sb_a
    bb_p.chips -= bb_a; bb_p.bet = bb_a; pot += bb_a

    # Streets
    pot = run_betting_round(players, community, pot, PRE_FLOP, bb_pos % n)
    in_hand = [p for p in players if p.active and not p.folded]

    if len(in_hand) > 1:
        community += [deck[idx], deck[idx+1], deck[idx+2]]; idx += 3
        pot = run_betting_round(players, community, pot, FLOP, dealer_idx)
        in_hand = [p for p in players if p.active and not p.folded]

    if len(in_hand) > 1:
        community.append(deck[idx]); idx += 1
        pot = run_betting_round(players, community, pot, TURN, dealer_idx)
        in_hand = [p for p in players if p.active and not p.folded]

    if len(in_hand) > 1:
        community.append(deck[idx]); idx += 1
        pot = run_betting_round(players, community, pot, RIVER, dealer_idx)
        in_hand = [p for p in players if p.active and not p.folded]

    # Showdown / award pot
    if len(in_hand) == 1:
        in_hand[0].chips += pot
    elif len(in_hand) > 1:
        best_val = max(best_hand(p.hole + community) for p in in_hand)
        winners  = [p for p in in_hand if best_hand(p.hole + community) == best_val]
        share    = pot // len(winners)
        for w in winners: w.chips += share
        winners[0].chips += pot - share * len(winners)

    # Bust out broke players
    for p in players:
        if p.active and p.chips <= 0:
            p.active = False; p.chips = 0

    # Advance dealer
    nxt = (dealer_idx + 1) % n
    while not players[nxt].active:
        nxt = (nxt + 1) % n
    return nxt

def run_tournament():
    players    = [Player(i, STRATEGIES[i][0], STRATEGIES[i][1]) for i in range(6)]
    dealer_idx = 0
    for _ in range(MAX_HANDS):
        alive = [p for p in players if p.active]
        if len(alive) == 1:
            return alive[0].pid, alive[0].name
        dealer_idx = run_hand(players, dealer_idx)
    winner = max((p for p in players if p.active), key=lambda p: p.chips)
    return winner.pid, winner.name

# ---------------------------------------------------------------------------
# Main — 100 tournaments + ASCII histogram
# ---------------------------------------------------------------------------

def main():
    N = 100
    print(f"Running {N} Texas Hold'em tournaments...\n")
    print("Strategies:")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  ← SIMPLE ALL-IN BOT" if i == 0 else ""
        print(f"  Player {i+1}: {name}{tag}")
    print()

    win_counts = Counter()
    for i in range(N):
        pid, _ = run_tournament()
        win_counts[pid] += 1
        if (i + 1) % 10 == 0:
            print(f"  Completed {i+1}/{N} tournaments...", flush=True)

    print()
    print("=" * 62)
    print("   WINNER WINNER CHICKEN DINNER  —  100-TOURNAMENT HISTOGRAM")
    print("=" * 62)

    max_wins  = max(win_counts.values(), default=1)
    bar_width = 36

    print(f"\n  {'Player':<26} {'W':>3}  {'%':>5}  Bar")
    print("  " + "-" * 58)
    for pid in range(6):
        name  = STRATEGIES[pid][0]
        wins  = win_counts.get(pid, 0)
        pct   = wins / N * 100
        label = f"P{pid+1} {name}"
        bar   = "█" * round(wins / max_wins * bar_width)
        tag   = " ← ALL-IN" if pid == 0 else ""
        print(f"  {label:<26} {wins:>3}  {pct:>4.1f}%  {bar}{tag}")

    print("  " + "-" * 58)
    champ_pid   = win_counts.most_common(1)[0][0]
    champ_name  = STRATEGIES[champ_pid][0]
    champ_wins  = win_counts[champ_pid]
    print(f"\n  CHAMPION: Player {champ_pid+1} — {champ_name}  ({champ_wins}/100 wins)\n")

    if champ_pid == 0:
        print("  The Degenerate's pure chaos HUMILIATES every elaborate strategy.")
        print("  Suflair GPT has left the building. Variance is a hell of a drug.")
    else:
        print(f"  {champ_name} out-grinds The Degenerate's all-in madness over 100 runs.")
        print("  Skill beats chaos in the long run. Suflair GPT gets NOTHING.")
    print("=" * 62)

if __name__ == "__main__":
    random.seed(42)
    main()
