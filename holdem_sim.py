"""
Texas Hold'em Poker Simulation — 6 players, 100 tournaments.

Player 1 : SimpleAllin       — if my_turn: bet = ALL IN; fi
Players 2-6: five elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card / deck
# ---------------------------------------------------------------------------
RANKS   = "23456789TJQKA"
SUITS   = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ---------------------------------------------------------------------------
# 5-card evaluator — returns comparable tuple (higher = better)
# ---------------------------------------------------------------------------
def best_hand(cards):
    return max(_eval5(c) for c in combinations(cards, 5))

def _eval5(cards):
    vals  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1

    cnt    = Counter(vals)
    groups = sorted(cnt, key=lambda v: (cnt[v], v), reverse=True)

    sv = vals[0]
    straight = (vals == list(range(sv, sv-5, -1)))
    if vals == [14, 5, 4, 3, 2]:
        straight, sv = True, 5

    c0 = cnt[groups[0]]
    c1 = cnt[groups[1]] if len(groups) > 1 else 0

    if flush and straight:    return (8, sv)
    if c0 == 4:               return (7, groups[0], groups[1])
    if c0 == 3 and c1 == 2:  return (6, groups[0], groups[1])
    if flush:                 return (5,) + tuple(vals)
    if straight:              return (4, sv)
    if c0 == 3:               return (3,) + tuple(groups)
    if c0 == 2 and c1 == 2:  return (2,) + tuple(groups)
    if c0 == 2:               return (1,) + tuple(groups)
    return                         (0,) + tuple(vals)

# ---------------------------------------------------------------------------
# Monte-Carlo hand strength
# ---------------------------------------------------------------------------
def estimate_strength(hole, community, n_opponents, n_samples=25):
    """Heads-up MC win rate raised to n_opponents (fast approximation)."""
    if n_opponents <= 0:
        return 1.0
    dead = set(hole) | set(community)
    deck = [c for c in make_deck() if c not in dead]
    needed = 5 - len(community)
    wins = ties = 0
    for _ in range(n_samples):
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        my_sc  = best_hand(list(hole) + board)
        opp_sc = best_hand(deck[needed:needed+2] + board)
        if my_sc > opp_sc:    wins += 1
        elif my_sc == opp_sc: ties += 1
    p = (wins + ties * 0.5) / n_samples
    return p ** n_opponents

# ---------------------------------------------------------------------------
# Strategies
#   Receive: hole, community, pot, to_call, my_stack, min_raise, stage,
#            n_opponents, position, n_active
#   Return:  (action, amount) — amount = new chips committed this action
# ---------------------------------------------------------------------------

def simple_allin(hole, community, pot, to_call, my_stack, min_raise, stage, **_):
    """if my_turn: bet = ALL IN; fi"""
    return ('raise', my_stack)


def strategy_tag(hole, community, pot, to_call, my_stack, min_raise, stage,
                 n_opponents=1, **_):
    """Tight-Aggressive: premium hands only, big bets when strong."""
    strength = estimate_strength(hole, community, n_opponents, 25)

    if stage == 'preflop':
        rv = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
        suited = hole[0][1] == hole[1][1]
        pp     = rv[0] == rv[1]
        high   = rv[0] >= 12 and (rv[1] >= 10 or suited)
        if (pp and rv[0] >= 7) or high:
            return ('raise', min(my_stack, max(min_raise, (pot or 30) * 3 // 2)))
        if to_call == 0: return ('check', 0)
        if to_call <= max(my_stack * 0.04, min_raise): return ('call', to_call)
        return ('fold', 0)

    if strength > 0.72:
        return ('raise', min(my_stack, max(min_raise, pot * 3 // 4)))
    if strength > 0.50:
        if to_call == 0: return ('check', 0)
        if (pot + to_call) > 0 and pot / (pot + to_call) < strength:
            return ('call', min(to_call, my_stack))
    if to_call == 0: return ('check', 0)
    return ('fold', 0)


def strategy_lp(hole, community, pot, to_call, my_stack, min_raise, stage,
                n_opponents=1, **_):
    """Loose-Passive: calls almost anything, rarely raises."""
    strength = estimate_strength(hole, community, n_opponents, 20)

    if strength > 0.82:
        return ('raise', min(my_stack, max(min_raise, (pot or 10) // 2)))
    if to_call == 0: return ('check', 0)
    if to_call <= my_stack * 0.20 and strength > 0.28: return ('call', min(to_call, my_stack))
    if to_call <= my_stack * 0.08: return ('call', min(to_call, my_stack))
    return ('fold', 0)


def strategy_maniac(hole, community, pot, to_call, my_stack, min_raise, stage,
                    n_opponents=1, **_):
    """Bluff-Maniac: frequent bluffs, chaotic aggression."""
    strength = estimate_strength(hole, community, n_opponents, 20)

    if random.random() < 0.22:
        return ('raise', min(my_stack, max(min_raise, int((pot or 10) * 0.9))))
    if strength > 0.55:
        sz = int((pot or 10) * random.uniform(0.6, 1.3))
        return ('raise', min(my_stack, max(min_raise, sz)))
    if strength > 0.35:
        if to_call == 0: return ('check', 0)
        return ('call', min(to_call, my_stack))
    if to_call == 0: return ('check', 0)
    if to_call <= my_stack * 0.06: return ('call', min(to_call, my_stack))
    return ('fold', 0)


def strategy_gto(hole, community, pot, to_call, my_stack, min_raise, stage,
                 n_opponents=1, **_):
    """GTO-Approximator: mixed frequencies, balanced range."""
    strength = estimate_strength(hole, community, n_opponents, 25)
    po = pot / (pot + to_call) if to_call > 0 else 1.0

    if strength > 0.85:
        sz = int((pot or 10) * random.uniform(0.65, 1.0))
        return ('raise', min(my_stack, max(min_raise, sz)))
    if strength > 0.65:
        if to_call == 0:
            sz = int((pot or 10) * random.uniform(0.40, 0.70))
            return ('raise', min(my_stack, max(min_raise, sz)))
        if po < strength: return ('call', min(to_call, my_stack))
        return ('fold', 0)
    if strength > 0.45:
        if to_call == 0:
            if random.random() < 0.30:
                return ('raise', min(my_stack, max(min_raise, int((pot or 10) * 0.40))))
            return ('check', 0)
        if po < strength: return ('call', min(to_call, my_stack))
        return ('fold', 0)
    if to_call == 0: return ('check', 0)
    if random.random() < 0.12 and my_stack > (pot or 0) * 2:
        return ('raise', min(my_stack, max(min_raise, int((pot or 10) * 0.75))))
    if to_call <= my_stack * 0.07 and po < strength + 0.05: return ('call', min(to_call, my_stack))
    return ('fold', 0)


def strategy_positional(hole, community, pot, to_call, my_stack, min_raise, stage,
                        n_opponents=1, position=0, n_active=6, **_):
    """Positional-Exploiter: tighter OOP, aggressive IP, steals blinds late."""
    strength = estimate_strength(hole, community, n_opponents, 25)
    pos_frac = position / max(n_active - 1, 1)

    if stage == 'preflop':
        rv = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
        if pos_frac > 0.65 and to_call <= BIG_BLIND and rv[0] >= 9:
            return ('raise', min(my_stack, max(min_raise, BIG_BLIND * 3)))
        if strength < 0.50 - pos_frac * 0.12:
            if to_call == 0: return ('check', 0)
            return ('fold', 0)

    sm = 0.50 + pos_frac * 0.50
    if strength > 0.75:
        return ('raise', min(my_stack, max(min_raise, int((pot or 10) * sm * 1.2))))
    if strength > 0.55:
        if to_call == 0:
            sz = int((pot or 10) * sm * 0.65)
            if sz >= min_raise: return ('raise', min(my_stack, sz))
            return ('check', 0)
        if (pot + to_call) > 0 and pot / (pot + to_call) < strength:
            return ('call', min(to_call, my_stack))
        return ('fold', 0)
    if to_call == 0: return ('check', 0)
    if (pot + to_call) > 0 and pot / (pot + to_call) < strength * (1 + pos_frac * 0.25):
        return ('call', min(to_call, my_stack))
    return ('fold', 0)


STRATEGIES = [simple_allin, strategy_tag, strategy_lp,
              strategy_maniac, strategy_gto, strategy_positional]
NAMES      = ["SimpleAllin", "TightAggressive", "LoosePassive",
              "BluffManiac", "GTOApprox", "PositionalExploit"]

SMALL_BLIND = 5
BIG_BLIND   = 10

# ---------------------------------------------------------------------------
# Betting engine
# ---------------------------------------------------------------------------
def betting_round(seats, community, stage, pot, first_idx, street_bets, current_bet):
    n = len(seats)
    min_raise = max(BIG_BLIND, current_bet)
    acted     = set()

    if sum(1 for p in seats if p.alive) <= 1:
        return pot

    order = [seats[(first_idx + i) % n] for i in range(n) if seats[(first_idx + i) % n].alive]
    q = list(order)

    safety = 0
    while q and safety < n * (n + 4):
        safety += 1
        p = q.pop(0)
        if not p.alive or p.stack <= 0:
            continue

        committed = street_bets.get(p.pid, 0)
        to_call   = max(0, current_bet - committed)
        n_opp     = sum(1 for s in seats if s.alive and s.pid != p.pid)

        action, amount = p.strategy(
            hole=p.hole, community=community, pot=pot, to_call=to_call,
            my_stack=p.stack, min_raise=max(BIG_BLIND, min_raise),
            stage=stage, n_opponents=max(n_opp, 1),
            position=order.index(p), n_active=len(order),
        )
        acted.add(p.pid)

        if action == 'fold':
            if to_call > 0:
                p.alive = False
            # folding when checking is free = treated as check
        elif action == 'check' or (action == 'call' and to_call == 0):
            pass
        elif action == 'call':
            chips = min(to_call, p.stack)
            p.stack -= chips
            pot     += chips
            street_bets[p.pid] = committed + chips
        elif action == 'raise':
            total_new = max(0, min(int(amount), p.stack))
            total_new = max(total_new, min(to_call, p.stack))  # at least call
            p.stack  -= total_new
            pot      += total_new
            new_committed = committed + total_new
            street_bets[p.pid] = new_committed
            if new_committed > current_bet:
                min_raise   = max(min_raise, new_committed - current_bet)
                current_bet = new_committed
                acted = {p.pid}
                q = [s for s in order if s.alive and s.stack > 0 and s.pid != p.pid]

        q = [s for s in q if s.alive and s.stack > 0 and
             (s.pid not in acted or street_bets.get(s.pid, 0) < current_bet)]

    return pot


class Player:
    __slots__ = ('pid', 'stack', 'strategy', 'hole', 'alive')
    def __init__(self, pid, stack, strategy):
        self.pid, self.stack, self.strategy = pid, stack, strategy
        self.hole, self.alive = [], True


def play_hand(seats, dealer_idx):
    n = len(seats)
    if n < 2:
        return
    deck = make_deck()
    random.shuffle(deck)

    for p in seats:
        p.alive = True
        p.hole  = [deck.pop(), deck.pop()]

    pot = 0
    street_bets = {}

    def post(idx, amount):
        nonlocal pot
        chips = min(amount, seats[idx].stack)
        seats[idx].stack -= chips
        pot += chips
        street_bets[seats[idx].pid] = chips
        return chips

    post((dealer_idx + 1) % n, SMALL_BLIND)
    current_bet = post((dealer_idx + 2) % n, BIG_BLIND)

    community = []
    streets = [
        ('preflop', 0, (dealer_idx + 3) % n),
        ('flop',    3, (dealer_idx + 1) % n),
        ('turn',    1, (dealer_idx + 1) % n),
        ('river',   1, (dealer_idx + 1) % n),
    ]

    for stage, ncards, first_idx in streets:
        for _ in range(ncards):
            community.append(deck.pop())
        if sum(1 for p in seats if p.alive) <= 1:
            break
        pot = betting_round(seats, community, stage, pot, first_idx, street_bets, current_bet)
        street_bets, current_bet = {}, 0
        if sum(1 for p in seats if p.alive) <= 1:
            break

    contenders = [p for p in seats if p.alive]
    if len(contenders) == 1:
        contenders[0].stack += pot
        return
    scores  = {p.pid: best_hand(p.hole + community) for p in contenders}
    top_sc  = max(scores.values())
    winners = [p for p in contenders if scores[p.pid] == top_sc]
    share, r = divmod(pot, len(winners))
    for w in winners:
        w.stack += share
    winners[0].stack += r


def run_tournament(starting_chips=1000):
    global SMALL_BLIND, BIG_BLIND
    players = [Player(i, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer = 0
    for hand_no in range(3000):
        # escalate blinds every 25 hands: 5/10 -> 10/20 -> 20/40 ...
        level = min(hand_no // 25, 6)
        SMALL_BLIND, BIG_BLIND = 5 * 2**level, 10 * 2**level
        living = [p for p in players if p.stack > 0]
        if len(living) == 1:
            SMALL_BLIND, BIG_BLIND = 5, 10
            return living[0].pid
        if len(living) < 2:
            break
        play_hand(living, dealer % len(living))
        dealer += 1
    SMALL_BLIND, BIG_BLIND = 5, 10
    return max(players, key=lambda p: p.stack).pid


# ---------------------------------------------------------------------------
# Run & histogram
# ---------------------------------------------------------------------------
def run_sims(n=100):
    wins = Counter()
    for i in range(n):
        wins[run_tournament(1000)] += 1
        if (i + 1) % 10 == 0:
            print(f"  {i+1:3d}/{n} done...")
    return wins


def histogram(wins, n):
    top = max(wins.values()) if wins else 1
    W = 30
    print()
    print("=" * 78)
    print("   TEXAS HOLD'EM  ·  100 TOURNAMENTS  ·  WHO RUNS THE TABLE")
    print("=" * 78)
    print(f"  {'Player':<24} {'Wins':>4}  {'%':>6}  Histogram")
    print("-" * 78)
    for pid in range(6):
        name = f"P{pid+1} {NAMES[pid]}"
        w    = wins.get(pid, 0)
        pct  = w / n * 100
        bl   = int(w / top * W)
        bar  = "#" * bl + "." * (W - bl)
        tag  = "  <-- ALL-IN GUY" if pid == 0 else ""
        print(f"  {name:<24} {w:>4}  {pct:>5.1f}%  {bar}{tag}")
    print("=" * 78)

    champ = max(wins, key=wins.get)
    print(f"\n  WINNER WINNER CHICKEN DINNER:  P{champ+1} — {NAMES[champ]}")
    print(f"  {wins[champ]} wins out of {n}  ({wins[champ]/n*100:.1f}%)\n")
    if champ == 0:
        print("  THE IF-STATEMENT HAS SPOKEN.")
        print("  One condition. Zero strategy. Infinite disrespect.")
        print("  suflair GPT built a cathedral. SimpleAllin brought a wrecking ball.")
    else:
        print(f"  Elaborate strategy '{NAMES[champ]}' reigned supreme.")
        print("  SimpleAllin swung hard but fell short.")
    print()


if __name__ == "__main__":
    random.seed(42)
    print("=" * 65)
    print("  Texas Hold'em Simulation — 6 players · 1000 chips each")
    print("=" * 65)
    print("  P1  SimpleAllin        — if my_turn: bet = ALL IN; fi")
    for i, nm in enumerate(NAMES[1:], 2):
        print(f"  P{i}  {nm}")
    print()
    wins = run_sims(100)
    histogram(wins, 100)
