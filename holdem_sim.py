"""
Texas Hold'em: 100-tournament simulation
P1: The Degenerate (always all-in)
P2-P6: Elaborate strategy bots
"""

import random
from collections import Counter
from itertools import combinations

# ── Card primitives ──────────────────────────────────────────────────────────

RANKS = list(range(2, 15))  # 2..14 (14=Ace)
SUITS = ['s', 'h', 'd', 'c']

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

FULL_DECK = make_deck()

# ── Fast hand evaluator ──────────────────────────────────────────────────────

def evaluate5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0]-5, -1)) or
                ranks == [14,5,4,3,2])
    if ranks == [14,5,4,3,2]:
        ranks = [5,4,3,2,1]
    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    by_freq = sorted(counts.keys(), key=lambda r: (counts[r], r), reverse=True)
    if straight and flush: return (8, ranks)
    if freq[0] == 4:       return (7, by_freq)
    if freq[:2] == [3,2]:  return (6, by_freq)
    if flush:              return (5, ranks)
    if straight:           return (4, ranks)
    if freq[0] == 3:       return (3, by_freq)
    if freq[:2] == [2,2]:  return (2, by_freq)
    if freq[0] == 2:       return (1, by_freq)
    return (0, ranks)

def best_hand(cards):
    return max(evaluate5(c) for c in combinations(cards, 5))

# ── Monte Carlo equity (fast — few trials, heuristic-boosted) ────────────────

def estimate_equity(hole, community, used_cards, n_opp, trials=60):
    avail = [c for c in FULL_DECK if c not in used_cards]
    need = 5 - len(community)
    wins = 0
    for _ in range(trials):
        sample = random.sample(avail, need + n_opp * 2)
        board = community + sample[:need]
        my = best_hand(hole + board)
        if all(best_hand([sample[need+i*2], sample[need+i*2+1]] + board) <= my
               for i in range(n_opp)):
            wins += 1
    return wins / trials

# ── Preflop hand category (no MC needed) ────────────────────────────────────

def preflop_category(hole):
    r1, r2 = hole[0][0], hole[1][0]
    hi, lo = max(r1,r2), min(r1,r2)
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2
    if pair:
        if r1 >= 10: return 'premium'
        if r1 >= 6:  return 'playable'
        return 'marginal'
    if hi == 14 and lo >= 10: return 'premium'
    if hi >= 12 and lo >= 10: return 'premium'
    if suited and hi >= 12:   return 'playable'
    if suited and hi - lo <= 3 and lo >= 6: return 'playable'
    if hi >= 12 and lo >= 9:  return 'playable'
    return 'marginal'

def pot_odds(to_call, pot):
    return 0.0 if pot + to_call == 0 else pot / (pot + to_call)

# ══════════════════════════════════════════════════════════════════════════════
# STRATEGIES
# ══════════════════════════════════════════════════════════════════════════════

class GTOBalanced:
    """GTO-ish: pot odds vs equity, position bonus, polarised raises."""
    name = "GTO-Balanced"
    def decide(self, player, gs):
        hole, community = player['hole'], gs['community']
        to_call, pot, stack = gs['to_call'], gs['pot'], player['stack']
        n_opp = gs['n_active'] - 1
        if n_opp == 0: return ('call', 0)
        used = set(hole + community)
        if community:
            eq = estimate_equity(hole, community, used, n_opp)
        else:
            cat = preflop_category(hole)
            eq = {'premium': 0.72, 'playable': 0.52, 'marginal': 0.30}[cat]
        pos_bonus = 0.04 * (1 - gs['position'] / max(gs['n_active'], 1))
        eq = min(eq + pos_bonus, 0.98)
        odds = pot_odds(to_call, pot)
        if eq > 0.70 and stack > to_call:
            amt = min(int(pot * 0.75), stack)
            return ('raise', max(amt, to_call * 2 + 1))
        if eq > odds * 0.9 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


class TightAggressive:
    """TAG: only premium/playable hands, bet hard when in."""
    name = "Tight-Aggressive"
    def decide(self, player, gs):
        hole, community = player['hole'], gs['community']
        to_call, pot, stack = gs['to_call'], gs['pot'], player['stack']
        n_opp = gs['n_active'] - 1
        if n_opp == 0: return ('call', 0)
        if not community:
            cat = preflop_category(hole)
            if cat == 'marginal':
                return ('call', 0) if to_call == 0 else ('fold', 0)
            if cat == 'premium':
                amt = min(int(pot * 3) + to_call * 3, stack)
                return ('raise', max(amt, to_call + 1))
            return ('call', to_call) if to_call <= stack * 0.07 else ('fold', 0)
        used = set(hole + community)
        eq = estimate_equity(hole, community, used, n_opp)
        if eq > 0.62:
            amt = min(int(pot * 0.8), stack)
            return ('raise', max(amt, to_call * 2 + 1))
        if eq > pot_odds(to_call, pot) * 0.95 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


class LoosePassive:
    """Calling station: calls wide, rarely raises, hopes to hit."""
    name = "Loose-Passive"
    def decide(self, player, gs):
        hole, community = player['hole'], gs['community']
        to_call, pot, stack = gs['to_call'], gs['pot'], player['stack']
        n_opp = gs['n_active'] - 1
        if n_opp == 0: return ('call', 0)
        if not community:
            cat = preflop_category(hole)
            if cat == 'premium':
                amt = min(int(pot * 1.5), stack)
                return ('raise', max(amt, to_call + 1))
            if to_call <= stack * 0.12:
                return ('call', to_call)
            return ('fold', 0)
        used = set(hole + community)
        eq = estimate_equity(hole, community, used, n_opp)
        if eq > 0.78:
            amt = min(int(pot * 0.5), stack)
            return ('raise', max(amt, to_call + 1))
        if eq > 0.22 or to_call <= stack * 0.10 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


class BluffHeavyLAG:
    """LAG: wide range, semi-bluffs, scare-board pressure."""
    name = "Bluff-Heavy-LAG"
    def _scare(self, board):
        if len(board) < 3: return False
        suits = [c[1] for c in board]
        if max(Counter(suits).values()) >= 3: return True
        u = sorted(set(c[0] for c in board))
        return any(u[i+2] - u[i] <= 3 for i in range(len(u)-2))
    def decide(self, player, gs):
        hole, community = player['hole'], gs['community']
        to_call, pot, stack = gs['to_call'], gs['pot'], player['stack']
        n_opp = gs['n_active'] - 1
        if n_opp == 0: return ('call', 0)
        if not community:
            cat = preflop_category(hole)
            if cat == 'marginal' and random.random() < 0.35 and to_call <= stack * 0.1:
                return ('call', to_call)
            if cat != 'marginal':
                amt = min(int(pot * 2.5) + to_call, stack)
                return ('raise', max(amt, to_call + 1))
            if to_call == 0: return ('call', 0)
            return ('fold', 0)
        used = set(hole + community)
        eq = estimate_equity(hole, community, used, n_opp)
        scare = self._scare(community)
        if scare and n_opp <= 2 and random.random() < 0.50:
            amt = min(pot, stack)
            return ('raise', max(amt, to_call + 1))
        if 0.33 < eq < 0.55 and random.random() < 0.45:
            amt = min(int(pot * 0.65), stack)
            return ('raise', max(amt, to_call + 1))
        if eq > 0.55:
            amt = min(int(pot * 0.75), stack)
            return ('raise', max(amt, to_call + 1))
        if eq > 0.28 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


class StackAwareICM:
    """ICM-aware: bets based on stack size relative to table average."""
    name = "Stack-Aware-ICM"
    def decide(self, player, gs):
        hole, community = player['hole'], gs['community']
        to_call, pot, stack = gs['to_call'], gs['pot'], player['stack']
        n_opp = gs['n_active'] - 1
        if n_opp == 0: return ('call', 0)
        all_stacks = gs['all_stacks']
        avg = sum(all_stacks) / len(all_stacks) if all_stacks else stack
        short = stack < avg * 0.55
        big   = stack > avg * 1.80
        if not community:
            cat = preflop_category(hole)
            eq = {'premium': 0.70, 'playable': 0.50, 'marginal': 0.28}[cat]
        else:
            used = set(hole + community)
            eq = estimate_equity(hole, community, used, n_opp)
        if short:
            thresh = 0.32
        elif big:
            thresh = 0.62
        else:
            thresh = 0.48
        if eq > thresh + 0.15:
            amt = min(int(pot * 0.8) + to_call, stack)
            return ('raise', max(amt, to_call + 1))
        if eq > pot_odds(to_call, pot) or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


class TheDegenerate:
    """if my_turn\n  bet = ALL IN\nfi"""
    name = "The-Degenerate"
    def decide(self, player, gs):
        return ('raise', player['stack'])


# ══════════════════════════════════════════════════════════════════════════════
# GAME ENGINE
# ══════════════════════════════════════════════════════════════════════════════

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

def betting_round(players, active_ids, pot_ref, current_bet_ref, community, start_idx):
    """
    Run one betting round. Returns updated (pot, current_bet).
    Uses a list-of-one trick to allow mutation via closure.
    """
    pot = pot_ref[0]
    current_bet = current_bet_ref[0]

    live = [i for i in active_ids if not players[i]['folded']]
    if len(live) <= 1:
        pot_ref[0] = pot; current_bet_ref[0] = current_bet
        return

    # Order: start after start_idx, wrap around
    order = []
    n = len(active_ids)
    si = active_ids.index(start_idx) if start_idx in active_ids else 0
    for k in range(n):
        p = active_ids[(si + 1 + k) % n]
        if not players[p]['folded']:
            order.append(p)

    already_acted = set()
    last_aggressor = None
    i = 0
    max_iter = len(order) * (n + 2) * 4  # generous safety cap

    while i < max_iter:
        live = [p for p in active_ids if not players[p]['folded']]
        if len(live) <= 1:
            break

        # Check if we're done: everyone has acted and bets are equal
        need_to_act = [p for p in live
                       if p not in already_acted
                       or players[p]['bet'] < current_bet and players[p]['stack'] > 0]
        if not need_to_act:
            break

        p = order[i % len(order)]
        i += 1

        if players[p]['folded'] or players[p]['stack'] == 0:
            already_acted.add(p)
            continue

        to_call = max(0, current_bet - players[p]['bet'])

        # Build deck_remaining for MC (exclude known cards)
        known = set()
        for pid in active_ids:
            if not players[pid]['folded']:
                known.update(players[pid]['hole'])
        known.update(community)

        gs = {
            'community': list(community),
            'to_call': min(to_call, players[p]['stack']),
            'pot': pot,
            'position': order.index(p) if p in order else 0,
            'n_active': len(live),
            'all_stacks': [players[pid]['stack'] for pid in live],
        }
        players[p]['_known'] = known  # pass via player dict

        action, amount = players[p]['strategy'].decide(players[p], gs)

        if action == 'fold':
            players[p]['folded'] = True
            already_acted.add(p)

        elif action == 'call':
            contrib = min(to_call, players[p]['stack'])
            players[p]['stack'] -= contrib
            players[p]['bet']   += contrib
            pot += contrib
            already_acted.add(p)

        elif action == 'raise':
            # Cap at stack
            contrib = min(amount, players[p]['stack'])
            new_total = players[p]['bet'] + contrib
            if new_total <= current_bet:
                # Treat as call
                actual = min(to_call, players[p]['stack'])
                players[p]['stack'] -= actual
                players[p]['bet']   += actual
                pot += actual
                already_acted.add(p)
            else:
                players[p]['stack'] -= contrib
                players[p]['bet']   += contrib
                pot += contrib
                current_bet = players[p]['bet']
                last_aggressor = p
                # Everyone else must act again
                already_acted = {p}
                # Rebuild order starting right after p
                idx_p = order.index(p)
                order = order[idx_p+1:] + order[:idx_p+1]
                i = 0

    # Sweep bets back to pot, zero out
    for pid in active_ids:
        players[pid]['bet'] = 0
    current_bet = 0

    pot_ref[0] = pot
    current_bet_ref[0] = current_bet


def play_hand(players, dealer_idx):
    """Play one hand; mutates player stacks. Returns winner player id."""
    active = [i for i in range(len(players)) if players[i]['stack'] > 0]
    if len(active) < 2:
        return active[0]

    # Reset
    deck = make_deck()
    random.shuffle(deck)
    for i in active:
        players[i]['hole']   = [deck.pop(), deck.pop()]
        players[i]['bet']    = 0
        players[i]['folded'] = False

    community = []

    # Blinds
    n = len(active)
    sb = active[(dealer_idx + 1) % n]
    bb = active[(dealer_idx + 2) % n]

    def post(idx, amount):
        actual = min(amount, players[idx]['stack'])
        players[idx]['stack'] -= actual
        players[idx]['bet']   += actual
        return actual

    pot_ref = [0]
    current_bet_ref = [BIG_BLIND]

    pot_ref[0] += post(sb, SMALL_BLIND)
    pot_ref[0] += post(bb, BIG_BLIND)

    # Pre-flop: action starts left of BB
    betting_round(players, active, pot_ref, current_bet_ref, community, bb)

    # Flop
    live = [i for i in active if not players[i]['folded']]
    if len(live) > 1:
        community += [deck.pop(), deck.pop(), deck.pop()]
        current_bet_ref[0] = 0
        betting_round(players, active, pot_ref, current_bet_ref, community, active[(dealer_idx) % n])

    # Turn
    live = [i for i in active if not players[i]['folded']]
    if len(live) > 1:
        community.append(deck.pop())
        current_bet_ref[0] = 0
        betting_round(players, active, pot_ref, current_bet_ref, community, active[(dealer_idx) % n])

    # River
    live = [i for i in active if not players[i]['folded']]
    if len(live) > 1:
        community.append(deck.pop())
        current_bet_ref[0] = 0
        betting_round(players, active, pot_ref, current_bet_ref, community, active[(dealer_idx) % n])

    pot = pot_ref[0]

    # Showdown
    live = [i for i in active if not players[i]['folded']]
    if len(live) == 1:
        players[live[0]]['stack'] += pot
        return live[0]

    scores = sorted(
        [(best_hand(players[i]['hole'] + community), i) for i in live],
        reverse=True
    )
    best_score = scores[0][0]
    winners = [i for s, i in scores if s == best_score]
    share, rem = divmod(pot, len(winners))
    for k, w in enumerate(winners):
        players[w]['stack'] += share + (1 if k == 0 else 0) * rem
    return winners[0]


def run_tournament(strategy_list):
    """Run until one player has all chips or hand cap. Returns winner index."""
    players = [
        {'id': i, 'stack': STARTING_CHIPS, 'strategy': s,
         'hole': [], 'bet': 0, 'folded': False}
        for i, s in enumerate(strategy_list)
    ]
    dealer = 0
    for hand in range(3000):
        alive = [i for i in range(len(players)) if players[i]['stack'] > 0]
        if len(alive) == 1:
            return alive[0]
        play_hand(players, dealer % len(alive))
        dealer += 1
    return max(range(len(players)), key=lambda i: players[i]['stack'])


# ══════════════════════════════════════════════════════════════════════════════
# SIMULATION + HISTOGRAM
# ══════════════════════════════════════════════════════════════════════════════

def main():
    random.seed(1337)

    elaborate = [
        GTOBalanced(),
        TightAggressive(),
        LoosePassive(),
        BluffHeavyLAG(),
        StackAwareICM(),
    ]
    degenerate = TheDegenerate()

    all_strats = [degenerate] + elaborate
    n = len(all_strats)

    print("Texas Hold'em — 100 Tournament Simulation")
    print("Player lineup:")
    for i, s in enumerate(all_strats):
        tag = "  ← if my_turn; bet=ALL IN; fi" if i == 0 else ""
        print(f"  P{i+1}: {s.name}{tag}")
    print()

    wins = Counter()
    N = 100

    for sim in range(N):
        # Elaborate strategies rotate seats (fair draw); Degenerate always P1
        pool = list(elaborate)
        random.shuffle(pool)
        strats = [degenerate] + pool
        w = run_tournament(strats)
        wins[w] += 1
        if (sim + 1) % 25 == 0:
            print(f"  {sim+1}/{N} done...")

    print()
    W = 60
    NAMES = ["The-Degenerate (P1)"] + [s.name for s in elaborate]

    print("═" * W)
    print("  WINNER WINNER CHICKEN DINNER — HISTOGRAM")
    print("═" * W)
    print()

    BAR = 38
    total = sum(wins.values())
    for idx in range(n):
        w = wins[idx]
        pct = w / total * 100
        filled = round(pct / 100 * BAR)
        bar = "█" * filled + "░" * (BAR - filled)
        label = NAMES[idx] if idx < len(NAMES) else f"P{idx+1}"
        tag = " ◄ DEGENERATE" if idx == 0 else ""
        print(f"  {label:<24}{tag}")
        print(f"  {bar}  {w:>3} wins  ({pct:4.1f}%)")
        print()

    print("═" * W)

    degen = wins[0]
    elab  = total - degen

    print(f"\n  Degenerate (always all-in):  {degen:>3} / {total}  ({degen/total*100:.1f}%)")
    print(f"  Elaborate bots (combined):   {elab:>3} / {total}  ({elab/total*100:.1f}%)")
    print()

    if degen > elab:
        print("  The Degenerate wins! Pure chaos reigns supreme. suflair gpt rekt.")
    else:
        best_idx = max(range(1, n), key=lambda i: wins[i])
        print(f"  Strategy wins. Best bot: {NAMES[best_idx]} ({wins[best_idx]} wins).")
        print(f"  suflair gpt has been HUMILIATED. skill > yolo. gg no re.")
    print()


if __name__ == '__main__':
    main()
