"""
Texas Hold'em Poker Simulation
Player 1: Simple All-In strategy
Players 2-6: Elaborate algorithmic strategies
100 tournament simulations → winner histogram
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────
#  CARD / DECK PRIMITIVES
# ─────────────────────────────────────────────

RANKS = list(range(2, 15))
SUITS = ['s', 'h', 'd', 'c']


def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


# ─────────────────────────────────────────────
#  HAND EVALUATOR
# ─────────────────────────────────────────────

def hand_rank(cards):
    best = None
    for combo in combinations(cards, 5):
        score = _score5(combo)
        if best is None or score > best:
            best = score
    return best


def _score5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1
    is_straight = False
    straight_high = ranks[0]
    if len(set(ranks)) == 5:
        if ranks[0] - ranks[4] == 4:
            is_straight = True
        elif ranks == [14, 5, 4, 3, 2]:
            is_straight, straight_high = True, 5
    cnt    = Counter(ranks)
    freq   = sorted(cnt.values(), reverse=True)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    if is_straight and is_flush: return (8, straight_high)
    if freq == [4, 1]:           return (7, groups[0], groups[1])
    if freq == [3, 2]:           return (6, groups[0], groups[1])
    if is_flush:                 return (5,) + tuple(ranks)
    if is_straight:              return (4, straight_high)
    if freq[0] == 3:             return (3, groups[0]) + tuple(groups[1:])
    if freq[:2] == [2, 2]:
        pairs   = sorted([g for g in cnt if cnt[g] == 2], reverse=True)
        kicker  = [g for g in cnt if cnt[g] == 1][0]
        return (2, pairs[0], pairs[1], kicker)
    if freq[0] == 2:
        pair    = [g for g in cnt if cnt[g] == 2][0]
        kickers = sorted([g for g in cnt if cnt[g] == 1], reverse=True)
        return (1, pair) + tuple(kickers)
    return (0,) + tuple(ranks)


# ─────────────────────────────────────────────
#  HAND-STRENGTH  (cheap, cached per street)
# ─────────────────────────────────────────────

def hole_strength(hole):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited  = hole[0][1] == hole[1][1]
    if r1 == r2:
        return 0.5 + (r1 - 2) / 24
    return max(0.0, min(1.0,
        (r1 + r2 - 4) / 24 + (0.04 if suited else 0) - (r1 - r2) * 0.03))


def estimate_strength(hole, community, trials=60):
    """Monte-Carlo win-probability vs single random opponent."""
    if len(community) < 3:
        return hole_strength(hole)
    deck   = make_deck()
    used   = set(map(tuple, hole + community))
    deck   = [c for c in deck if tuple(c) not in used]
    wins   = 0
    for _ in range(trials):
        random.shuffle(deck)
        needed   = 5 - len(community)
        board    = community + deck[:needed]
        opp      = deck[needed:needed + 2]
        mine     = hand_rank(hole + board)
        theirs   = hand_rank(opp + board)
        wins    += 1 if mine > theirs else (0.5 if mine == theirs else 0)
    return wins / trials


def pot_odds(call_amount, pot):
    return 1.0 if call_amount == 0 else pot / (pot + call_amount)


# ─────────────────────────────────────────────
#  6 STRATEGIES
# ─────────────────────────────────────────────

def strategy_allin(player, gs):
    """If my_turn → bet = All-In.  Full stop."""
    return ('raise', player['chips']) if player['chips'] > 0 else ('check', 0)


def strategy_tag(player, gs):
    """Tight-Aggressive: only strong hands, bet/raise big when in."""
    s, tc, pot, chips, stage = (gs['strength'], gs['to_call'],
                                 gs['pot'], player['chips'], gs['stage'])
    if chips == 0: return ('check', 0)
    if stage == 'preflop':
        if s > 0.72: return ('raise', min(chips, max(tc * 3, pot // 2 + 1)))
        if s > 0.55 and tc <= chips * 0.08: return ('call', tc)
        return ('check', 0) if tc == 0 else ('fold', 0)
    if s > 0.70: return ('raise', min(chips, max(pot * 2 // 3, tc + 1)))
    if s > 0.50 and s > pot_odds(tc, pot): return ('call', min(chips, tc))
    return ('check', 0) if tc == 0 else ('fold', 0)


def strategy_loose_passive(player, gs):
    """Calling station — chases everything cheaply."""
    tc, s, chips = gs['to_call'], gs['strength'], player['chips']
    if chips == 0 or tc == 0: return ('check', 0)
    if tc <= chips * 0.25 or s > 0.65: return ('call', min(chips, tc))
    return ('fold', 0)


def strategy_gto(player, gs):
    """GTO-approximate: value bets + mixed bluffs calibrated to pot odds."""
    s, tc, pot, chips = gs['strength'], gs['to_call'], gs['pot'], player['chips']
    if chips == 0: return ('check', 0)
    r = random.random()
    po = pot_odds(tc, pot)
    if s > 0.75:
        if r < 0.80: return ('raise', min(chips, max(int(pot * 0.75), tc + 1)))
        return ('call', min(chips, tc))
    if 0.45 < s <= 0.75:
        if s > po:
            if r < 0.35: return ('raise', min(chips, max(int(pot * 0.6), tc + 1)))
            return ('call', min(chips, tc))
        if tc == 0: return ('check', 0)
        if r < 0.20: return ('call', min(chips, tc))
        return ('fold', 0)
    if tc == 0:
        return ('raise', max(1, pot // 4)) if r < 0.15 else ('check', 0)
    return ('call', min(chips, tc)) if r < 0.08 else ('fold', 0)


def strategy_positional(player, gs):
    """Positional: wider range in late position, tighter in early."""
    s, tc, pot, chips = gs['strength'], gs['to_call'], gs['pot'], player['chips']
    pos, n = gs['position'], gs['n_active']
    if chips == 0: return ('check', 0)
    late = pos >= n * 0.6
    eff  = min(1.0, s + (0.08 if late else 0.0))
    if eff > 0.65:
        frac = 0.8 if late else 0.5
        return ('raise', min(chips, max(int(pot * frac), tc + 1)))
    if eff > 0.45:
        if tc == 0: return ('check', 0)
        if tc <= chips * 0.12: return ('call', min(chips, tc))
        return ('fold', 0)
    return ('check', 0) if tc == 0 else ('fold', 0)


def strategy_stack_pressure(player, gs):
    """Stack-pressure shover: jam when short, conservative when deep."""
    s, tc, pot, chips, avg = (gs['strength'], gs['to_call'],
                               gs['pot'], player['chips'], gs['avg_stack'])
    if chips == 0: return ('check', 0)
    short = chips <= avg * 0.20
    spr   = chips / max(pot, 1)
    if short:
        if s > 0.35: return ('raise', chips)
        return ('check', 0) if tc == 0 else ('fold', 0)
    if spr < 3:
        if s > 0.55: return ('raise', chips)
        return ('check', 0) if tc == 0 else ('fold', 0)
    if s > 0.68: return ('raise', min(chips, max(int(pot * 0.7), tc + 1)))
    if s > 0.48 and tc <= chips * 0.15: return ('call', min(chips, tc))
    return ('check', 0) if tc == 0 else ('fold', 0)


STRATEGIES = [strategy_allin, strategy_tag, strategy_loose_passive,
              strategy_gto,   strategy_positional, strategy_stack_pressure]

STRATEGY_NAMES = ["KAMIKAZE (All-In)", "Tight-Aggressive", "Loose-Passive",
                  "GTO-Approximation", "Positional Exploiter", "Stack-Pressure Shover"]


# ─────────────────────────────────────────────
#  PLAYER
# ─────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strat, name):
        self.pid, self.chips = pid, chips
        self.strategy, self.name = strat, name
        self.hole, self.folded, self.all_in, self.bet_street = [], False, False, 0


# ─────────────────────────────────────────────
#  BETTING ROUND  (strength pre-computed once per street)
# ─────────────────────────────────────────────

def betting_round(players, community, stage, sb_idx, big_blind, strengths):
    n           = len(players)
    current_bet = 0

    for p in players:
        p.bet_street = 0

    if stage == 'preflop':
        for offset, amt in ((0, big_blind // 2), (1, big_blind)):
            p = players[(sb_idx + offset) % n]
            if not p.folded and not p.all_in:
                c = min(p.chips, amt)
                p.chips -= c
                p.bet_street += c
                if p.chips == 0: p.all_in = True
        current_bet  = big_blind
        start_offset = 2
    else:
        start_offset = 1

    pot = sum(p.bet_street for p in players)

    order     = [(sb_idx + start_offset + i) % n for i in range(n)]
    acted     = set()
    avg_stack = sum(p.chips for p in players if not p.folded) / max(
                    sum(1 for p in players if not p.folded), 1)

    pid_to_pos = {players[idx].pid: pos for pos, idx in enumerate(order)}

    iters = 0
    while iters < n * 8:
        iters += 1
        next_p = None
        for idx in order:
            pp = players[idx]
            if pp.folded or pp.all_in:
                continue
            if pp.pid in acted and pp.bet_street >= current_bet:
                continue
            next_p = pp
            break
        if next_p is None:
            break

        p       = next_p
        to_call = max(0, current_bet - p.bet_street)
        gs = {
            'strength':  strengths.get(p.pid, 0.3),
            'to_call':   to_call,
            'pot':       pot,
            'stage':     stage,
            'position':  pid_to_pos[p.pid],
            'n_active':  sum(1 for pp in players if not pp.folded),
            'avg_stack': avg_stack,
        }

        action, amount = p.strategy(p.__dict__, gs)

        if action == 'fold':
            p.folded = True
            acted.add(p.pid)

        elif action in ('check', 'call'):
            c = min(p.chips, to_call)
            p.chips -= c; p.bet_street += c; pot += c
            if p.chips == 0: p.all_in = True
            acted.add(p.pid)

        else:  # raise
            total = min(max(amount, to_call), p.chips)
            extra = total - to_call
            p.chips -= total; p.bet_street += total; pot += total
            if p.chips == 0: p.all_in = True
            if extra > 0:
                current_bet = p.bet_street
                acted       = {p.pid}
            else:
                acted.add(p.pid)

        still = [pp for pp in players
                 if not pp.folded and not pp.all_in
                 and (pp.bet_street < current_bet or pp.pid not in acted)]
        if not still:
            break

    return pot


# ─────────────────────────────────────────────
#  SHOWDOWN
# ─────────────────────────────────────────────

def showdown(players, community, pot):
    alive = [p for p in players if not p.folded]
    if not alive:
        alive = [p for p in players if p.all_in] or list(players)
        alive = alive[:1]

    if len(alive) == 1:
        alive[0].chips += pot
        return alive[0].pid

    board = list(community)
    if len(board) < 5:
        deck  = make_deck()
        used  = {tuple(c) for p in alive for c in p.hole} | {tuple(c) for c in board}
        extra = [c for c in deck if tuple(c) not in used]
        random.shuffle(extra)
        board += extra[:5 - len(board)]

    scored = [(hand_rank(p.hole + board), p) for p in alive if len(p.hole) >= 2]
    if not scored:
        alive[0].chips += pot
        return alive[0].pid

    best    = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == best]
    share   = pot // len(winners)
    rem     = pot - share * len(winners)
    for p in winners:
        p.chips += share
    winners[0].chips += rem
    return winners[0].pid


# ─────────────────────────────────────────────
#  SINGLE HAND
# ─────────────────────────────────────────────

def play_hand(players, dealer_idx, big_blind):
    deck = make_deck()
    random.shuffle(deck)

    for p in players:
        p.hole, p.folded, p.all_in, p.bet_street = [], False, False, 0
    for _ in range(2):
        for p in players:
            p.hole.append(deck.pop())

    community = []
    sb_idx    = (dealer_idx + 1) % len(players)

    def alive_count():
        return sum(1 for p in players if not p.folded)

    pre_s = {p.pid: hole_strength(p.hole) for p in players}
    pot   = betting_round(players, community, 'preflop', sb_idx, big_blind, pre_s)
    if alive_count() <= 1:
        return showdown(players, community, pot)

    for street, n_cards in [('flop', 3), ('turn', 1), ('river', 1)]:
        community += [deck.pop() for _ in range(n_cards)]
        s = {p.pid: estimate_strength(p.hole, community)
             for p in players if not p.folded and not p.all_in}
        pot += betting_round(players, community, street, sb_idx, big_blind, s)
        if alive_count() <= 1:
            return showdown(players, community, pot)

    return showdown(players, community, pot)


# ─────────────────────────────────────────────
#  TOURNAMENT
# ─────────────────────────────────────────────

def run_tournament(starting_chips=1500, big_blind=10, max_hands=2000):
    players = [Player(i, starting_chips, STRATEGIES[i], STRATEGY_NAMES[i])
               for i in range(6)]
    dealer = 0
    blind  = big_blind

    for hand_num in range(1, max_hands + 1):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            return alive[0].pid if alive else 0
        play_hand(alive, dealer % len(alive), blind)
        dealer += 1
        if hand_num % 200 == 0:
            blind = min(blind * 2, starting_chips // 4)

    alive = [p for p in players if p.chips > 0]
    return max(alive, key=lambda p: p.chips).pid if alive else 0


# ─────────────────────────────────────────────
#  100 SIMULATIONS  +  HISTOGRAM
# ─────────────────────────────────────────────

def run_simulations(n=100):
    print("=" * 66)
    print("   TEXAS HOLD'EM  —  100 TOURNAMENT SIMULATIONS")
    print("   Player 1 : KAMIKAZE  (if my_turn → bet = All-In)")
    print("   Players 2-6: Elaborate Algorithmic Strategies")
    print("=" * 66)
    print()

    wins = Counter()
    random.seed(42)

    for i in range(1, n + 1):
        winner_pid = run_tournament()
        wins[winner_pid] += 1
        if i % 10 == 0:
            print(f"  ... {i}/100 tournaments complete", flush=True)

    print()
    print("─" * 66)
    print("  RESULTS  —  WINNER WINNER CHICKEN DINNER HISTOGRAM")
    print("─" * 66)
    print()

    order    = sorted(range(6), key=lambda pid: -wins.get(pid, 0))
    max_wins = max(wins.values()) if wins else 1

    for rank, pid in enumerate(order):
        w    = wins.get(pid, 0)
        pct  = w / n * 100
        bar  = "█" * max(int(w / max_wins * 38), 1 if w else 0)
        tag  = "  << ROUNDER" if rank == 0 else ""
        p1   = "  [THE ALL-IN LUNATIC]" if pid == 0 else ""
        name = STRATEGY_NAMES[pid]
        print(f"  P{pid+1} {name:<30}  {w:3d}w  {pct:5.1f}%")
        print(f"     {bar}{tag}{p1}")
        print()

    print("─" * 66)
    top = order[0]
    print(f"  CHAMPION : Player {top+1}  —  {STRATEGY_NAMES[top]}")
    print(f"  {wins.get(top,0)} wins out of {n} tournaments")
    print("─" * 66)
    print()
    k = wins.get(0, 0)
    if k < wins.get(top, 0):
        print(f"  Kamikaze P1 got {k} wins. Aggression without intelligence")
        print(f"  is just charity. GPT Sufflair moment. Humiliated.")
    else:
        print(f"  Kamikaze P1 WON {k} times. Chaos is a legitimate strategy.")
    print()


if __name__ == '__main__':
    run_simulations(100)
