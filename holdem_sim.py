"""
Texas Hold'em Poker Simulation — 6 players, 100 tournaments
Player 1: Always All-In
Players 2-6: Elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ─── Cards ───────────────────────────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ─── Hand Evaluator ──────────────────────────────────────────────────────────

def hand_rank(cards):
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
    unique_vals = sorted(set(vals), reverse=True)
    straight = len(unique_vals) == 5 and (unique_vals[0] - unique_vals[4] == 4)
    if set(vals) == {14, 2, 3, 4, 5}:
        straight, vals = True, [5, 4, 3, 2, 1]
    counts = Counter(vals)
    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    gc = [g[1] for g in groups]
    gv = [g[0] for g in groups]
    if straight and flush: return (8, vals[0])
    if gc[0] == 4: return (7, gv[0], gv[1])
    if gc[:2] == [3, 2]: return (6, gv[0], gv[1])
    if flush: return (5,) + tuple(vals)
    if straight: return (4, vals[0])
    if gc[0] == 3: return (3, gv[0]) + tuple(gv[1:])
    if gc[:2] == [2, 2]: return (2, max(gv[0],gv[1]), min(gv[0],gv[1]), gv[2])
    if gc[0] == 2: return (1, gv[0]) + tuple(gv[1:])
    return (0,) + tuple(vals)

# ─── Fast Hand Strength (no MC) ──────────────────────────────────────────────
# Returns 0.0-1.0 relative strength estimate

def preflop_strength(hole):
    """Chen formula approximation, normalised to 0-1."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    high, low = max(r1, r2), min(r1, r2)
    pair = r1 == r2

    # Base score from high card
    score = {14:10, 13:8, 12:7, 11:6}.get(high, high / 2.0)
    if pair:
        score = max(score * 2, 5)
    if suited:
        score += 2
    gap = high - low
    if not pair:
        score -= [0, 0, 1, 2, 4, 5][min(gap, 5)]
        if gap <= 1 and high < 12:
            score += 1
    # Normalise: max possible ~20, min ~-1
    return max(0.0, min(1.0, (score + 1) / 21.0))

def postflop_strength(hole, community):
    """
    Fast post-flop strength: evaluate made hand + draw potential.
    Returns 0-1 estimate.
    """
    all_cards = hole + community
    if len(all_cards) < 5:
        return preflop_strength(hole)

    score_tuple = hand_rank(all_cards)
    hand_cat = score_tuple[0]  # 0-8

    # Raw hand strength from category
    made = hand_cat / 8.0

    # Draw bonus: flush draw, straight draw
    suits_in_hand = Counter(c[1] for c in all_cards)
    flush_draw = any(v >= 4 for v in suits_in_hand.values()) and hand_cat < 5
    vals = sorted(set(RANK_VAL[c[0]] for c in all_cards), reverse=True)
    oesd = False
    for i in range(len(vals) - 3):
        if vals[i] - vals[i+3] == 3:
            oesd = True
            break

    draw_bonus = (0.08 if flush_draw else 0) + (0.05 if oesd else 0)
    # Only give draw bonus on flop/turn, not river
    if len(community) == 5:
        draw_bonus = 0

    return min(1.0, made + draw_bonus)

# ─── Strategies ───────────────────────────────────────────────────────────────

def strategy_all_in(player, gs):
    """Player 1: always shove."""
    return ('raise', player.chips)


def strategy_tag(player, gs):
    """TAG — Tight Aggressive: premiums only, size up strong hands."""
    hole = player.hole
    community = gs['community']
    to_call = gs['to_call']
    pot = gs['pot']
    street = gs['street']

    if street == 'preflop':
        strength = preflop_strength(hole)
        if strength >= 0.70:
            return ('raise', min(player.chips, max(to_call * 3, pot)))
        if strength >= 0.52 and to_call <= player.chips * 0.12:
            return ('call', to_call)
        if strength >= 0.40 and to_call <= player.chips * 0.06:
            return ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)
    else:
        s = postflop_strength(hole, community)
        if s >= 0.70:
            return ('raise', min(player.chips, int(pot * 0.75)))
        if s >= 0.50:
            return ('call', to_call) if to_call <= player.chips * 0.30 else ('fold', 0)
        if s >= 0.35 and to_call == 0:
            return ('check', 0)
        return ('check', 0) if to_call == 0 else ('fold', 0)


def strategy_calling_station(player, gs):
    """Calling Station — loose passive, calls wide, rarely raises."""
    hole = player.hole
    community = gs['community']
    to_call = gs['to_call']
    pot = gs['pot']
    street = gs['street']

    if street == 'preflop':
        if to_call <= player.chips * 0.20:
            return ('call', to_call)
        strength = preflop_strength(hole)
        if strength >= 0.55 and to_call <= player.chips * 0.40:
            return ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)
    else:
        s = postflop_strength(hole, community)
        if s >= 0.80:
            return ('raise', min(player.chips, pot // 3))
        if s >= 0.25 and to_call <= player.chips * 0.50:
            return ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)


def strategy_lag_bluffer(player, gs):
    """LAG Bluffer — wide range, frequent semi-bluffs, position aware."""
    hole = player.hole
    community = gs['community']
    to_call = gs['to_call']
    pot = gs['pot']
    street = gs['street']
    position = gs.get('position', 'middle')

    pos_factor = 1.3 if position == 'late' else (0.8 if position == 'early' else 1.0)

    if street == 'preflop':
        strength = preflop_strength(hole) * pos_factor
        if strength >= 0.70:
            return ('raise', min(player.chips, max(to_call * 3, pot)))
        if strength >= 0.45 and to_call <= player.chips * 0.25:
            if random.random() < 0.55:
                return ('raise', min(player.chips, max(to_call * 2, pot // 2)))
            return ('call', to_call)
        if strength >= 0.30 and to_call <= player.chips * 0.15:
            return ('call', to_call)
        if to_call == 0:
            if random.random() < 0.30:
                return ('raise', min(player.chips, pot // 2))
            return ('check', 0)
        return ('fold', 0)
    else:
        s = postflop_strength(hole, community) * pos_factor
        if s >= 0.65:
            bet = min(player.chips, int(pot * random.uniform(0.5, 1.1)))
            return ('raise', bet)
        if s >= 0.40:
            if random.random() < 0.45:
                return ('raise', min(player.chips, pot // 2))
            return ('call', to_call) if to_call <= player.chips * 0.30 else ('fold', 0)
        if to_call == 0:
            if random.random() < 0.30:
                return ('raise', min(player.chips, pot // 3))
            return ('check', 0)
        if to_call <= pot * 0.20 and random.random() < 0.25:
            return ('call', to_call)
        return ('fold', 0)


def strategy_gto(player, gs):
    """GTO Approx — pot-odds based decisions, balanced bluff frequency."""
    hole = player.hole
    community = gs['community']
    to_call = gs['to_call']
    pot = gs['pot']
    street = gs['street']

    if street == 'preflop':
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited = hole[0][1] == hole[1][1]
        high, low = max(r1, r2), min(r1, r2)
        pair = r1 == r2
        score = high * 0.4 + low * 0.3 + (2 if suited else 0) + (3 if pair else 0)
        score += max(0, 4 - (high - low)) * 0.5

        if score >= 9:
            return ('raise', min(player.chips, max(to_call * 3, pot)))
        if score >= 7:
            if to_call == 0:
                return ('raise', min(player.chips, pot // 2))
            if to_call <= player.chips * 0.12:
                return ('call', to_call)
            return ('fold', 0)
        if score >= 5:
            if to_call == 0:
                return ('check', 0)
            if to_call <= player.chips * 0.06:
                return ('call', to_call)
            return ('fold', 0)
        if to_call == 0 and random.random() < 0.25:
            return ('raise', min(player.chips, pot // 3))
        return ('check', 0) if to_call == 0 else ('fold', 0)
    else:
        s = postflop_strength(hole, community)
        pot_odds = to_call / (pot + to_call + 1)
        if s >= 0.75:
            return ('raise', min(player.chips, int(pot * 1.0)))
        if s >= 0.55:
            return ('raise', min(player.chips, int(pot * 0.66)))
        if s > pot_odds + 0.05:
            return ('call', to_call)
        if to_call == 0:
            if s >= 0.35 and random.random() < 0.33:
                return ('raise', min(player.chips, pot // 3))
            return ('check', 0)
        return ('fold', 0)


def strategy_short_stack(player, gs):
    """Short-Stack Specialist — shoves wide when shallow, tight when deep."""
    hole = player.hole
    community = gs['community']
    to_call = gs['to_call']
    pot = gs['pot']
    street = gs['street']
    avg_stack = gs.get('avg_stack', player.chips)

    relative = player.chips / max(avg_stack, 1)
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    high, low = max(r1, r2), min(r1, r2)
    pair = r1 == r2

    if street == 'preflop':
        hand_score = high + low * 0.5 + (4 if pair else 0) + (1.5 if hole[0][1] == hole[1][1] else 0)
        if relative < 0.4:
            if pair or high >= 12 or hand_score >= 14:
                return ('raise', player.chips)
            return ('check', 0) if to_call == 0 else ('fold', 0)
        if relative < 0.8:
            if hand_score >= 18 or (pair and r1 >= 8):
                return ('raise', min(player.chips, pot * 2))
            if hand_score >= 14 and to_call <= player.chips * 0.15:
                return ('call', to_call)
            return ('check', 0) if to_call == 0 else ('fold', 0)
        # Deep: tight
        if (pair and r1 >= 9) or (high >= 13 and low >= 10) or (high == 14 and low >= 9):
            return ('raise', min(player.chips, max(to_call * 3, pot // 2)))
        if hand_score >= 16 and to_call <= player.chips * 0.08:
            return ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)
    else:
        s = postflop_strength(hole, community)
        spr = player.chips / max(pot, 1)
        if spr < 2:
            if s >= 0.45:
                return ('raise', player.chips)
            return ('check', 0) if to_call == 0 else ('fold', 0)
        if spr < 5:
            if s >= 0.60:
                return ('raise', min(player.chips, int(pot * 0.75)))
            if s >= 0.40 and to_call <= player.chips * 0.30:
                return ('call', to_call)
            return ('check', 0) if to_call == 0 else ('fold', 0)
        if s >= 0.65:
            return ('raise', min(player.chips, pot // 2))
        if s >= 0.45 and to_call <= player.chips * 0.20:
            return ('call', to_call)
        return ('check', 0) if to_call == 0 else ('fold', 0)


STRATEGIES = [
    strategy_all_in,
    strategy_tag,
    strategy_calling_station,
    strategy_lag_bluffer,
    strategy_gto,
    strategy_short_stack,
]

STRATEGY_NAMES = [
    "AllIn Maniac",
    "TAG (Tight-Aggressive)",
    "Calling Station",
    "LAG Bluffer",
    "GTO Approximator",
    "Short-Stack Shover",
]

# ─── Betting Engine ───────────────────────────────────────────────────────────

def betting_round(players, community, pot, street, big_blind, dealer_idx):
    active = [p for p in players if not p.folded and p.chips > 0]
    if len(active) <= 1:
        return pot

    n = len(players)
    current_bet = max(p.bet for p in players)
    avg_stack = sum(p.chips for p in players) / max(len(players), 1)
    order = [(dealer_idx + 1 + i) % n for i in range(n)]

    acted = set()
    last_raiser = None
    max_iter = n * 6
    it = 0

    while it < max_iter:
        it += 1
        progress = False
        for idx in order:
            p = players[idx]
            if p.folded or p.all_in or p.chips == 0:
                continue
            if p.pid in acted and p.pid != last_raiser and p.bet >= current_bet:
                continue
            progress = True

            to_call = max(0, min(current_bet - p.bet, p.chips))
            pos = 'late' if idx == dealer_idx % n else ('early' if idx == (dealer_idx+1) % n else 'middle')
            gs = {
                'community': community, 'to_call': to_call, 'pot': pot,
                'street': street, 'position': pos, 'avg_stack': avg_stack,
                'active_opponents': sum(1 for x in players if not x.folded and x.pid != p.pid),
            }

            action, amount = p.strategy_fn(p, gs)

            if action == 'fold':
                p.folded = True
                acted.add(p.pid)
            elif action == 'check':
                acted.add(p.pid)
            elif action == 'call':
                actual = min(to_call, p.chips)
                p.chips -= actual; p.bet += actual; pot += actual
                if p.chips == 0: p.all_in = True
                acted.add(p.pid)
            elif action == 'raise':
                total = min(p.chips, max(int(amount), to_call + big_blind))
                p.chips -= total; p.bet += total; pot += total
                if p.chips == 0: p.all_in = True
                if p.bet > current_bet:
                    current_bet = p.bet
                    last_raiser = p.pid
                    acted = {p.pid}
                else:
                    acted.add(p.pid)

        contesting = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
        if not progress or len(contesting) <= 1:
            break

    return pot


def play_hand(players, dealer_idx, big_blind):
    deck = make_deck()
    random.shuffle(deck)
    for p in players:
        p.hole = []; p.folded = False; p.bet = 0; p.all_in = False

    active = [p for p in players if p.chips > 0]
    if len(active) < 2:
        return players, dealer_idx

    n = len(players)
    community = []
    pot = 0

    def next_active(start):
        idx = (start + 1) % n
        for _ in range(n):
            if players[idx].chips > 0:
                return idx
            idx = (idx + 1) % n
        return start

    for p in players:
        if p.chips > 0:
            p.hole = [deck.pop(), deck.pop()]

    sb_idx = next_active(dealer_idx)
    bb_idx = next_active(sb_idx)

    sb = min(big_blind // 2, players[sb_idx].chips)
    players[sb_idx].chips -= sb; players[sb_idx].bet = sb; pot += sb

    bb = min(big_blind, players[bb_idx].chips)
    players[bb_idx].chips -= bb; players[bb_idx].bet = bb; pot += bb

    pot = betting_round(players, community, pot, 'preflop', big_blind, dealer_idx)

    for street, cards in [('flop', 3), ('turn', 1), ('river', 1)]:
        if len([p for p in players if not p.folded]) <= 1:
            break
        community += [deck.pop() for _ in range(cards)]
        for p in players: p.bet = 0
        pot = betting_round(players, community, pot, street, big_blind, dealer_idx)

    contenders = [p for p in players if not p.folded]
    if len(contenders) == 1:
        contenders[0].chips += pot
    else:
        scores = [(hand_rank(p.hole + community), p) for p in contenders]
        best = max(s[0] for s in scores)
        winners = [p for s, p in scores if s == best]
        share = pot // len(winners)
        for w in winners: w.chips += share
        winners[0].chips += pot % len(winners)

    return players, (dealer_idx + 1) % n


# ─── Tournament ───────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, fn):
        self.pid = pid; self.chips = chips; self.strategy_fn = fn
        self.hole = []; self.folded = False; self.bet = 0; self.all_in = False

def run_tournament(starting_chips=1500, big_blind=30, max_hands=3000):
    players = [Player(i+1, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer_idx = 0
    bb = big_blind
    for hand_num in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid
        players, dealer_idx = play_hand(players, dealer_idx, bb)
        if hand_num > 0 and hand_num % 150 == 0:
            bb = min(bb * 2, starting_chips // 3)
    return max(players, key=lambda p: p.chips).pid


# ─── Run & Report ─────────────────────────────────────────────────────────────

def run_simulations(n=100):
    print(f"Running {n} tournaments...\n")
    wins = Counter()
    for i in range(n):
        if (i+1) % 20 == 0:
            print(f"  {i+1}/{n} done...")
        wins[run_tournament()] += 1
    return wins

def print_histogram(wins, n):
    max_w = max(wins.values()) if wins else 1
    bar_w = 38
    print("\n" + "═"*68)
    print("  HOLDEM TOURNAMENT — 100 SIMS — WINNER WINNER CHICKEN DINNER")
    print("═"*68)
    for pid in range(1, 7):
        w = wins.get(pid, 0)
        bar = "█" * int(w * bar_w / max_w)
        tag = "  ← THE DEGENERATE" if pid == 1 else ""
        print(f"  P{pid} {STRATEGY_NAMES[pid-1]:<24} {bar:<38} {w:>3} ({w}%){tag}")
    print("═"*68)
    champ = max(range(1,7), key=lambda p: wins.get(p,0))
    print(f"\n  CHAMPION: Player {champ} — {STRATEGY_NAMES[champ-1]} with {wins.get(champ,0)} wins")
    p1 = wins.get(1, 0)
    p_champ = wins.get(champ, 0)
    if champ != 1:
        margin = p_champ - p1
        print(f"  Player 1 (AllIn Maniac) finished with {p1} wins")
        print(f"  Margin of defeat: {margin} tournaments")
        print(f"\n  suflair gpt got HUMILIATED. Skill beats brute force over 100 games.\n")
    else:
        print(f"\n  Chaos theory wins. The maniac ran hot over 100 games.\n")

if __name__ == '__main__':
    random.seed(1337)
    results = run_simulations(100)
    print_histogram(results, 100)
