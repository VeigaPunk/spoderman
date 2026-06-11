#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
Player 1: Simple All-In
Players 2-6: Elaborate algorithmic strategies
100 tournaments, histogram of winners
"""

import random
import sys
from collections import Counter
from itertools import combinations

# ── CARDS ──────────────────────────────────────────────────────────────────

RANKS  = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
SUITS  = ['s','h','d','c']
RANK_V = {r: i for i, r in enumerate(RANKS, 2)}

class Card:
    __slots__ = ('rank','suit','value')
    def __init__(self, rank, suit):
        self.rank  = rank
        self.suit  = suit
        self.value = RANK_V[rank]
    def __repr__(self):  return f"{self.rank}{self.suit}"
    def __eq__(self, o): return self.rank == o.rank and self.suit == o.suit
    def __hash__(self):  return hash((self.rank, self.suit))

class Deck:
    def __init__(self):
        self.cards = [Card(r,s) for r in RANKS for s in SUITS]
        random.shuffle(self.cards)
    def deal(self, n=1):
        out, self.cards = self.cards[:n], self.cards[n:]
        return out

# ── HAND EVALUATOR ─────────────────────────────────────────────────────────

def _score5(cards):
    vals  = sorted([c.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    flush = len(set(suits)) == 1
    # straight check
    straight, hi = False, 0
    if vals[0]-vals[4] == 4 and len(set(vals)) == 5:
        straight, hi = True, vals[0]
    elif vals == [14,5,4,3,2]:
        straight, hi = True, 5
    cnt = Counter(vals)
    freq   = sorted(cnt.values(), reverse=True)
    groups = sorted(cnt.keys(), key=lambda x:(cnt[x],x), reverse=True)
    if straight and flush:
        return (9 if vals[0]==14 and vals[1]==13 else 8, [hi])
    if freq[0]==4: return (7, groups)
    if freq[0]==3 and freq[1]==2: return (6, groups)
    if flush: return (5, vals)
    if straight: return (4, [hi])
    if freq[0]==3: return (3, groups)
    if freq[0]==2 and freq[1]==2: return (2, groups)
    if freq[0]==2: return (1, groups)
    return (0, vals)

def best_hand(cards):
    return max(_score5(list(c)) for c in combinations(cards, 5))

# ── PLAYER ─────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.invested = 0   # chips put in this round

    def reset_hand(self):
        self.hole = []; self.folded = False; self.allin = False; self.invested = 0

    def reset_street(self):
        self.invested = 0

    def act(self, state):
        if self.folded or self.allin or self.chips == 0:
            return 'check', 0
        return self.strategy(self, state)

# ── STRATEGIES ─────────────────────────────────────────────────────────────

def s_allin(player, state):
    """P1 – if my_turn then bet = ALL IN fi"""
    return 'raise', player.chips


def s_tag(player, state):
    """P2 – Tight-Aggressive: top 18% hands, strong value betting."""
    h     = player.hole
    comm  = state['community']
    pot   = state['pot']
    bet   = state['bet']
    to_go = max(0, bet - player.invested)
    street= state['street']

    if street == 'preflop':
        v1, v2  = sorted([c.value for c in h], reverse=True)
        suited  = h[0].suit == h[1].suit
        premium = (v1>=12 and v2>=12) or (v1==14 and v2>=11) or (v1==13 and v2==13)
        playable= (v1==v2 and v1>=7) or (v1==14 and v2>=8) or \
                  (v1>=11 and v2>=10 and suited)
        if premium:
            return 'raise', min(player.chips, max(to_go*3, pot*2, 30))
        if playable:
            if to_go == 0: return 'check', 0
            if to_go <= player.chips*0.12: return 'call', to_go
            return 'fold', 0
        return ('check',0) if to_go==0 else ('fold',0)

    score = best_hand(h + comm)[0]
    if score >= 3:
        return 'raise', min(player.chips, max(to_go, int(pot*0.8)))
    if score == 2:
        return ('call', min(to_go,player.chips)) if to_go <= pot*0.5 else \
               (('check',0) if to_go==0 else ('fold',0))
    if score == 1:
        return ('check',0) if to_go==0 else \
               (('call', min(to_go,player.chips)) if to_go<=pot*0.25 else ('fold',0))
    return ('check',0) if to_go==0 else ('fold',0)


def s_lag(player, state):
    """P3 – Loose-Aggressive: wide range, frequent bluffs, relentless pressure."""
    h     = player.hole
    comm  = state['community']
    pot   = state['pot']
    bet   = state['bet']
    to_go = max(0, bet - player.invested)
    street= state['street']
    pos   = state['position']

    bluff_p = 0.38 - pos * 0.04   # less bluffing from early position

    if street == 'preflop':
        v1, v2 = sorted([c.value for c in h], reverse=True)
        suited = h[0].suit == h[1].suit
        score  = v1 + v2*0.55 + (2.5 if suited else 0) + (4 if v1==v2 else 0)
        if score >= 21:
            return 'raise', min(player.chips, max(to_go, pot)*3+10)
        if score >= 14:
            if random.random() < 0.65:
                return 'raise', min(player.chips, max(to_go, pot)*2+5)
            return ('call', min(to_go,player.chips)) if to_go>0 else ('check',0)
        if to_go == 0 and random.random() < bluff_p:
            return 'raise', min(player.chips, int(pot*0.6)+5)
        if to_go <= player.chips*0.06:
            return ('call',to_go) if to_go>0 else ('check',0)
        return 'fold', 0

    score = best_hand(h + comm)[0]
    if score >= 4:
        return 'raise', min(player.chips, max(to_go, int(pot*random.uniform(0.7,1.3))))
    if score >= 2:
        if random.random() < 0.55:
            return 'raise', min(player.chips, max(to_go, int(pot*0.55)))
        return ('call',min(to_go,player.chips)) if to_go>0 else ('check',0)
    # weak – bluff or fold
    if to_go == 0:
        if random.random() < bluff_p:
            return 'raise', min(player.chips, int(pot*0.7))
        return 'check', 0
    if to_go <= pot*0.2 or random.random() < 0.22:
        return 'call', min(to_go, player.chips)
    return 'fold', 0


def s_rock(player, state):
    """P4 – Rock/Nit: only top 7% hands, near-zero bluffing."""
    h     = player.hole
    comm  = state['community']
    pot   = state['pot']
    bet   = state['bet']
    to_go = max(0, bet - player.invested)
    street= state['street']

    if street == 'preflop':
        v1, v2 = sorted([c.value for c in h], reverse=True)
        suited = h[0].suit == h[1].suit
        monster= (v1==14 and v2>=13) or \
                 (v1==v2 and v1>=11) or \
                 (v1==14 and v2==12 and suited)
        if monster:
            return 'raise', min(player.chips, max(to_go*4, 30))
        return ('check',0) if to_go==0 else ('fold',0)

    score = best_hand(h + comm)[0]
    if score >= 5:
        return 'raise', min(player.chips, max(to_go, pot))
    if score >= 3:
        return ('call',min(to_go,player.chips)) if to_go<=pot*0.45 else \
               (('check',0) if to_go==0 else ('fold',0))
    return ('check',0) if to_go==0 else ('fold',0)


def s_potodds(player, state):
    """P5 – Pot-Odds / GTO-lite: every decision justified by equity vs price."""
    h     = player.hole
    comm  = state['community']
    pot   = state['pot']
    bet   = state['bet']
    to_go = max(0, bet - player.invested)
    street= state['street']
    n_opp = max(state['n_active']-1, 1)

    if len(comm) == 0:
        # Chen formula approximation
        v1, v2 = sorted([c.value for c in h], reverse=True)
        suited = h[0].suit == h[1].suit
        if v1 == v2:
            chen = max(v1, 5) * 2
        else:
            chen = float(v1)
            gap  = v1 - v2
            chen += (1 if gap<=1 else 0.5 if gap<=2 else 0)
            if suited: chen += 2
        equity = min(chen / 22.0, 1.0)
    else:
        raw    = best_hand(h + comm)[0] / 9.0
        equity = raw ** (1.0/n_opp) * 0.85 + 0.05

    pot_odds = to_go / (pot + to_go + 1e-9)

    if equity > 0.78:
        return 'raise', min(player.chips, max(to_go, int(pot*0.85)))
    if equity > pot_odds + 0.12:
        if to_go == 0:
            return 'raise', min(player.chips, int(pot*0.55)+1)
        return 'call', min(to_go, player.chips)
    if equity > pot_odds - 0.04:
        return ('check',0) if to_go==0 else ('call',min(to_go,player.chips))
    return ('check',0) if to_go==0 else ('fold',0)


def s_adaptive(player, state):
    """P6 – Adaptive: stack-aware, position-sensitive, push-fold when short."""
    h      = player.hole
    comm   = state['community']
    pot    = state['pot']
    bet    = state['bet']
    to_go  = max(0, bet - player.invested)
    street = state['street']
    pos    = state['position']
    avg_st = max(state['avg_stack'], 1)

    ratio  = player.chips / avg_st

    # ── short stack push/fold ──────────────────────────────
    if ratio < 0.25:
        v1, v2 = sorted([c.value for c in h], reverse=True)
        suited = h[0].suit == h[1].suit
        if street == 'preflop':
            threshold = 15 - pos*1.5
            hand_val  = v1 + v2 + (3 if suited else 0) + (5 if v1==v2 else 0)
            if hand_val >= threshold:
                return 'raise', player.chips
        else:
            sc = best_hand(h+comm)[0]
            if sc >= 2: return 'raise', player.chips
        return ('check',0) if to_go==0 else ('fold',0)

    # ── normal play ───────────────────────────────────────
    v1, v2 = sorted([c.value for c in h], reverse=True)
    suited = h[0].suit == h[1].suit

    if street == 'preflop':
        pos_bonus = pos * 1.8
        val = v1 + v2*0.7 + (2.5 if suited else 0) + (5 if v1==v2 else 0) + pos_bonus
        if val >= 24:
            return 'raise', min(player.chips, max(to_go*3, int(pot*0.9), 20))
        if val >= 17:
            if to_go <= player.chips*0.09:
                return ('call',to_go) if to_go>0 else ('check',0)
            return 'fold', 0
        if val >= 13 and pos >= 3:  # late-position steal
            if to_go == 0:
                return 'raise', min(player.chips, int(pot*2.5)+10)
            if to_go <= player.chips*0.06:
                return 'call', to_go
        return ('check',0) if to_go==0 else ('fold',0)

    sc      = best_hand(h+comm)[0]
    c_size  = int(pot*(0.45 + pos*0.12))

    if sc >= 5:
        return 'raise', min(player.chips, max(to_go, c_size*2))
    if sc >= 3:
        if pos >= 2:
            return 'raise', min(player.chips, max(to_go, c_size))
        return ('call',min(to_go,player.chips)) if to_go>0 else ('check',0)
    if sc >= 1:
        if to_go == 0:
            if pos >= 3 and random.random() < 0.38:
                return 'raise', min(player.chips, int(pot*0.42))
            return 'check', 0
        return ('call',min(to_go,player.chips)) if to_go<=pot*0.38 else ('fold',0)
    if to_go == 0:
        if pos >= 4 and random.random() < 0.28:
            return 'raise', min(player.chips, int(pot*0.52))
        return 'check', 0
    return 'fold', 0

# ── GAME ENGINE ────────────────────────────────────────────────────────────

SMALL_BLIND = 10
BIG_BLIND   = 20

def betting_round(players, start, street, community, pot, cur_bet):
    n        = len(players)
    acted    = set()
    iters    = 0
    idx      = start

    while iters < n * 6:
        iters += 1
        p = players[idx % n]
        idx += 1

        if p.folded or p.allin:
            continue

        live = [x for x in players if not x.folded and not x.allin]
        if not live:
            break
        all_settled = all(x.invested >= cur_bet for x in live)
        all_acted   = all(x.pid in acted for x in live)
        if all_settled and all_acted:
            break

        if p.invested >= cur_bet and p.pid in acted:
            if all_settled:
                break
            continue

        avg_st = sum(x.chips for x in players) / max(len(players), 1)
        state = {
            'community': community,
            'pot':       pot,
            'bet':       cur_bet,
            'street':    street,
            'n_active':  sum(1 for x in players if not x.folded),
            'position':  iters % max(n, 1),
            'avg_stack': avg_st,
        }

        action, amount = p.act(state)

        if action == 'fold':
            p.folded = True
            acted.add(p.pid)

        elif action == 'check':
            acted.add(p.pid)

        elif action == 'call':
            needed = min(max(cur_bet - p.invested, 0), p.chips)
            p.chips    -= needed
            p.invested += needed
            pot        += needed
            if p.chips == 0: p.allin = True
            acted.add(p.pid)

        elif action == 'raise':
            gap     = max(cur_bet - p.invested, 0)
            total   = min(gap + max(amount, 0), p.chips)
            p.chips    -= total
            p.invested += total
            pot        += total
            if p.invested > cur_bet:
                cur_bet = p.invested
                acted   = {p.pid}
            if p.chips == 0: p.allin = True
            acted.add(p.pid)

        live = [x for x in players if not x.folded and not x.allin]
        if len([x for x in players if not x.folded]) <= 1:
            break

    return pot, cur_bet


def play_hand(players, dealer_idx):
    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return

    for p in alive:
        p.reset_hand()

    n   = len(alive)
    sb  = alive[(dealer_idx+1) % n]
    bb  = alive[(dealer_idx+2) % n]

    def post(p, amount):
        a = min(p.chips, amount)
        p.chips    -= a
        p.invested += a
        if p.chips == 0: p.allin = True
        return a

    pot = post(sb, SMALL_BLIND) + post(bb, BIG_BLIND)

    deck = Deck()
    for p in alive:
        p.hole = deck.deal(2)

    community = []
    streets   = ['preflop','flop','turn','river']
    cur_bet   = BIG_BLIND
    start     = (dealer_idx + 3) % n   # UTG pre-flop

    for st in streets:
        if st == 'flop':
            community += deck.deal(3)
        elif st in ('turn','river'):
            community += deck.deal(1)

        if st != 'preflop':
            for p in alive:
                p.invested = 0
            cur_bet = 0
            start   = (dealer_idx + 1) % n

        live = [p for p in alive if not p.folded]
        if len(live) <= 1:
            break
        if sum(1 for p in live if not p.allin) <= 1:
            # run out remaining streets but no betting
            if st == 'flop':
                community += deck.deal(3)
            elif st == 'turn':
                community += deck.deal(1)
            elif st == 'river':
                pass
            # deal remaining board cards if needed
            while len(community) < 5:
                community += deck.deal(1)
            break

        pot, cur_bet = betting_round(alive, start, st, community, pot, cur_bet)

        if sum(1 for p in alive if not p.folded) <= 1:
            break

    # showdown / award pot
    standing = [p for p in alive if not p.folded]
    if not standing:
        return

    if len(standing) == 1:
        standing[0].chips += pot
        return

    # need board complete
    while len(community) < 5:
        community += deck.deal(1)

    scored = [(best_hand(p.hole + community), p) for p in standing]
    scored.sort(key=lambda x: x[0], reverse=True)
    top_score = scored[0][0]
    winners   = [p for sc, p in scored if sc == top_score]

    share = pot // len(winners)
    rem   = pot % len(winners)
    for p in winners:
        p.chips += share
    if rem:
        winners[0].chips += rem


def run_tournament(starting_chips=2000, max_hands=800):
    STRATEGIES = [
        (1, s_allin),
        (2, s_tag),
        (3, s_lag),
        (4, s_rock),
        (5, s_potodds),
        (6, s_adaptive),
    ]
    players = [Player(pid, starting_chips, fn) for pid, fn in STRATEGIES]
    dealer  = 0

    for _ in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        play_hand(alive, dealer % len(alive))
        dealer += 1

    return max(players, key=lambda p: p.chips).pid


def run_sims(n=100):
    counts = Counter()
    for i in range(n):
        if (i+1) % 20 == 0:
            print(f"  ... {i+1}/{n} done", file=sys.stderr)
        counts[run_tournament()] += 1
    return counts


# ── HISTOGRAM ──────────────────────────────────────────────────────────────

NAMES = {
    1: "P1 │ Simple All-In        ",
    2: "P2 │ Tight-Aggressive(TAG)",
    3: "P3 │ Loose-Aggressive(LAG)",
    4: "P4 │ Rock / Nit           ",
    5: "P5 │ Pot-Odds / GTO-lite  ",
    6: "P6 │ Adaptive / Positional",
}

def histogram(counts, n=100):
    BAR   = 44
    mxwin = max(counts.values()) if counts else 1

    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║    TEXAS HOLD'EM — 100 TOURNAMENT SIMULATION — WINNER HISTOGRAM     ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print()

    for pid in range(1, 7):
        wins = counts.get(pid, 0)
        pct  = wins / n * 100
        bar  = "█" * int(wins / mxwin * BAR)
        print(f"  {NAMES[pid]}│ {bar:<{BAR}} {wins:>3} ({pct:4.1f}%)")

    print()
    print("╠══════════════════════════════════════════════════════════════════════╣")
    champ_pid, champ_wins = max(counts.items(), key=lambda x: x[1])
    print(f"║  🏆  CHAMPION : {NAMES[champ_pid].strip():<30}  {champ_wins} / {n} wins  ║")
    print("╠══════════════════════════════════════════════════════════════════════╣")
    print()
    print("  Strategy legend")
    print("  ──────────────────────────────────────────────────────────────────")
    print("  P1  if my_turn then bet = ALL IN fi   ← the chad strategy")
    print("  P2  Tight-Aggressive : top 18% hands, hammer value spots")
    print("  P3  Loose-Aggressive : wide range, constant pressure + bluffs")
    print("  P4  Rock/Nit         : top 7% only, fold everything else")
    print("  P5  Pot-Odds/GTO     : equity vs price, Chen formula pre-flop")
    print("  P6  Adaptive         : position aware, push-fold when short")
    print()
    print("  No player knows any other player's strategy.")
    print("  All players start with identical chip stacks (2 000).")
    print("  Blinds: SB=10 / BB=20. Winner = last player standing (≤800 hands).")
    print()

if __name__ == '__main__':
    random.seed(1337)
    print("Running 100 Texas Hold'em tournaments …")
    print("Players : P1=All-In  P2=TAG  P3=LAG  P4=Rock  P5=GTO  P6=Adaptive")
    print()
    w = run_sims(100)
    histogram(w)
