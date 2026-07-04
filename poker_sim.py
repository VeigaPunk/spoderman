#!/usr/bin/env python3
"""
Texas Hold'em Poker Tournament Simulator
-----------------------------------------
P1 : Always-All-In  (the monkey strategy)
P2 : Tight-Aggressive (TAG)
P3 : Pot-Odds Oracle
P4 : Semi-Bluff Machine
P5 : Position Shark
P6 : GTO Balancer

Runs 100 full tournaments (last-chip-standing).
Outputs an ASCII histogram of winners.
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────── Cards ────────────────────────────────────────────
RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RVAL  = {r: i for i, r in enumerate(RANKS, 2)}   # '2'→2 … 'A'→14

def new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(d)
    return d

# ─────────────────────── Hand evaluation ──────────────────────────────────────
def _eval5(hand):
    vals  = sorted([RVAL[c[0]] for c in hand], reverse=True)
    suits = [c[1] for c in hand]
    flush = len(set(suits)) == 1
    # Ace-low straight: A-2-3-4-5
    if vals == [14, 5, 4, 3, 2]:
        vals = [5, 4, 3, 2, 1]
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    cnt  = Counter(vals)
    freq = sorted(cnt.values(), reverse=True)
    grp  = sorted(cnt, key=lambda v: (cnt[v], v), reverse=True)
    if straight and flush: return (8, vals)
    if freq == [4, 1]:     return (7, grp)
    if freq == [3, 2]:     return (6, grp)
    if flush:              return (5, vals)
    if straight:           return (4, vals)
    if freq[0] == 3:       return (3, grp)
    if freq[:2] == [2, 2]: return (2, grp)
    if freq[0] == 2:       return (1, grp)
    return (0, vals)

def best_hand(cards):
    """Best 5-card hand from 5–7 cards. Returns comparable tuple."""
    return max(_eval5(h) for h in combinations(cards, 5))

# ──────────────────────── Strength helpers ─────────────────────────────────────
def hand_strength(hole, community):
    """Heuristic 0→1 hand-strength estimate."""
    known = hole + community
    if len(known) < 5:                  # pre-flop / partial board
        r1, r2  = RVAL[hole[0][0]], RVAL[hole[1][0]]
        paired  = hole[0][0] == hole[1][0]
        suited  = hole[0][1] == hole[1][1]
        hi      = max(r1, r2)
        s = (hi - 2) / 12 * 0.55
        if paired:  s += 0.26
        if suited:  s += 0.06
        s += min(r1, r2) / 14 * 0.07
        return min(s, 0.97)
    rank, _ = best_hand(known)
    return rank / 8.0

def preflop_tier(hole):
    """Premium tier 0–10 for pre-flop decisions."""
    v  = sorted([RVAL[hole[0][0]], RVAL[hole[1][0]]], reverse=True)
    su = hole[0][1] == hole[1][1]
    pa = v[0] == v[1]
    if pa:
        for thresh, score in [(14,10),(13,9),(12,8),(11,7),(10,6),(7,4)]:
            if v[0] >= thresh: return score
        return 2
    if v[0] == 14:
        for thresh, base in [(13,8),(12,7),(11,6)]:
            if v[1] >= thresh: return base + su
        return 4
    if v[0] == 13 and v[1] >= 12: return 5 + su
    if su and v[0] - v[1] == 1:   return 4
    return max(1, (v[0] - 2) // 3)

# ────────────────────────── Player ────────────────────────────────────────────
class Player:
    __slots__ = ('name','chips','strategy_fn','hole','folded','all_in','street_bet')

    def __init__(self, name, chips, fn):
        self.name        = name
        self.chips       = chips
        self.strategy_fn = fn
        self.hole        = []
        self.folded      = False
        self.all_in      = False
        self.street_bet  = 0

    def reset(self):
        self.hole       = []
        self.folded     = False
        self.all_in     = False
        self.street_bet = 0

# ───────────────────────── Strategies ─────────────────────────────────────────
# Strategy signature: fn(player, game_state) → (action, amount)
# action ∈ {'fold','check','call','raise','all_in'}
# gs keys: community, pot, to_call, street, position (0=early…1=button), n_active

def strat_all_in(p, gs):
    """THE MONKEY: if my_turn then bet = All-In fi."""
    return ('all_in', p.chips)

# ── Strategy 2: Tight-Aggressive (TAG) ─────────────────────────────────────
def strat_tag(p, gs):
    """
    Tight-Aggressive: premium hands pre-flop, relentless barrel post-flop.
    Folds garbage, raises hard when strong, never slow-plays.
    """
    hs      = hand_strength(p.hole, gs['community'])
    to_call = gs['to_call']
    pot     = gs['pot']

    if not gs['community']:                         # ── Pre-flop ──
        tier = preflop_tier(p.hole)
        if tier >= 8:                               # AA/KK/QQ/AKs → 3-bet
            return ('raise', min(int(pot * 3 + to_call), p.chips))
        if tier >= 5 and to_call <= p.chips * 0.12: # JJ/TT/AQ → call or limp
            return ('call', min(to_call, p.chips)) if to_call else ('check', 0)
        return ('check', 0) if to_call == 0 else ('fold', 0)

    if hs >= 0.82:                                  # Two-pair+ → fire big
        return ('raise', min(int(pot * 0.85), p.chips))
    if hs >= 0.55:                                  # Top pair → pot control
        if to_call == 0:           return ('check', 0)
        if to_call <= pot * 0.45:  return ('call',  min(to_call, p.chips))
    return ('check', 0) if to_call == 0 else ('fold', 0)

# ── Strategy 3: Pot-Odds Oracle ─────────────────────────────────────────────
def strat_pot_odds(p, gs):
    """
    Mathematical pot-odds engine. Computes required equity vs pot odds.
    Only commits chips when EV > 0. Raises aggressively when equity is way ahead.
    """
    hs      = hand_strength(p.hole, gs['community'])
    to_call = gs['to_call']
    pot     = gs['pot']

    if to_call == 0:
        return ('raise', min(int(pot * 0.6), p.chips)) if hs >= 0.65 else ('check', 0)

    pot_odds = to_call / (pot + to_call) if (pot + to_call) else 1.0
    margin   = hs - pot_odds

    if margin > 0.18:  return ('raise', min(int(to_call * 2.5), p.chips))
    if margin > 0.05:  return ('call',  min(to_call, p.chips))
    return ('fold', 0)

# ── Strategy 4: Semi-Bluff Machine ──────────────────────────────────────────
def strat_bluffer(p, gs):
    """
    Polarised range player. Value-bets top 30% of hands. Bluffs 22% of the time
    with air to remain unexploitable. Gives up quickly when called out.
    """
    hs      = hand_strength(p.hole, gs['community'])
    to_call = gs['to_call']
    pot     = gs['pot']
    bluff   = random.random() < 0.22

    if hs >= 0.70 or bluff:
        if to_call == 0:
            return ('raise', min(int(pot * 0.65), p.chips))
        return ('raise', min(int(to_call + pot * 0.5), p.chips))

    if hs >= 0.42:
        if to_call == 0:           return ('check', 0)
        if to_call <= pot * 0.40:  return ('call',  min(to_call, p.chips))

    return ('check', 0) if to_call == 0 else ('fold', 0)

# ── Strategy 5: Position Shark ──────────────────────────────────────────────
def strat_position(p, gs):
    """
    Exploits positional advantage. Late position = +10% equity bonus.
    Steals blinds in position. Folds marginal hands from early seats.
    Button play is hyper-aggressive; UTG is rock-solid.
    """
    hs      = hand_strength(p.hole, gs['community'])
    to_call = gs['to_call']
    pot     = gs['pot']
    late    = gs.get('position', 0.5)       # 0=early, 1=button
    adj     = hs + late * 0.10              # position equity bonus

    if adj >= 0.78:
        if to_call == 0:
            return ('raise', min(int(pot * 0.75), p.chips))
        return ('raise', min(int(to_call * 2 + pot * 0.35), p.chips))

    if adj >= 0.48:
        if to_call == 0:
            if late > 0.66:                 # late-position steal
                return ('raise', min(int(pot * 0.45), p.chips))
            return ('check', 0)
        if to_call <= pot * 0.44:
            return ('call', min(to_call, p.chips))
        return ('fold', 0)

    return ('check', 0) if to_call == 0 else ('fold', 0)

# ── Strategy 6: GTO Balancer ────────────────────────────────────────────────
def strat_gto(p, gs):
    """
    Solver-inspired balanced ranges. Mixes bet/check on medium-strength hands
    to remain unexploitable. Bluffs at ~18% frequency with the worst hands.
    Sizes bets to give opponents exactly indifferent pot odds.
    """
    hs      = hand_strength(p.hole, gs['community'])
    to_call = gs['to_call']
    pot     = gs['pot']
    r       = random.random()

    if hs >= 0.80:
        if to_call == 0:
            return ('raise', min(int(pot * 0.72), p.chips))
        return ('raise', min(int(to_call + pot * 0.58), p.chips))

    if hs >= 0.60:
        if to_call == 0:
            return ('raise', min(int(pot * 0.5), p.chips)) if r < 0.55 else ('check', 0)
        if to_call <= pot * 0.55:
            return ('call', min(to_call, p.chips))
        return ('fold', 0)

    if hs >= 0.35:
        if to_call == 0:            return ('check', 0)
        if to_call <= pot * 0.28:   return ('call', min(to_call, p.chips))
        return ('fold', 0)

    if to_call == 0:
        return ('raise', min(int(pot * 0.55), p.chips)) if r < 0.18 else ('check', 0)
    return ('fold', 0)

# ───────────────────────── Strategy registry ──────────────────────────────────
STRATEGIES = [
    ('P1_AllIn',    strat_all_in),
    ('P2_TAG',      strat_tag),
    ('P3_PotOdds',  strat_pot_odds),
    ('P4_Bluffer',  strat_bluffer),
    ('P5_Position', strat_position),
    ('P6_GTO',      strat_gto),
]

LABELS = {
    'P1_AllIn'   : 'P1 Always-All-In  [THE MONKEY]',
    'P2_TAG'     : 'P2 Tight-Aggressive (TAG)',
    'P3_PotOdds' : 'P3 Pot-Odds Oracle',
    'P4_Bluffer' : 'P4 Semi-Bluff Machine',
    'P5_Position': 'P5 Position Shark',
    'P6_GTO'     : 'P6 GTO Balancer',
}

# ─────────────────────────── Betting round ────────────────────────────────────
def betting_round(players, pot, street_max, start_seat, gs_extra):
    """
    Runs a single betting street to completion.
    start_seat : index into players[] of first actor
    street_max : current highest street_bet (0 for post-flop opens)
    Returns updated pot.
    """
    n     = len(players)
    order = [(start_seat + i) % n for i in range(n)]
    acted = set()
    last_aggressor = None

    for _ in range(n * 6):         # upper-bound on iterations
        progress = False
        for seat in order:
            p = players[seat]
            if p.folded or p.all_in or p.chips == 0:
                continue
            to_call = max(0, street_max - p.street_bet)
            if seat in acted and to_call == 0:
                continue            # already acted, no re-open pending
            if seat == last_aggressor and to_call == 0:
                continue            # aggressor has nothing left to respond to

            progress = True
            pos_norm = order.index(seat) / max(len(order) - 1, 1)
            gs = {
                **gs_extra,
                'to_call' : to_call,
                'pot'     : pot,
                'position': pos_norm,
                'n_active': sum(1 for q in players if not q.folded),
            }

            action, amount = p.strategy_fn(p, gs)

            if action == 'fold':
                p.folded = True
                acted.add(seat)

            elif action in ('check', 'call'):
                pay           = min(to_call, p.chips)
                p.chips      -= pay
                p.street_bet += pay
                pot          += pay
                if p.chips == 0: p.all_in = True
                acted.add(seat)

            else:                   # 'raise' or 'all_in'
                total = p.chips if action == 'all_in' else min(int(amount), p.chips)
                total = max(total, to_call)     # must at least call
                pay   = min(total, p.chips)
                p.chips      -= pay
                p.street_bet += pay
                pot          += pay
                if p.chips == 0: p.all_in = True
                if p.street_bet > street_max:
                    street_max     = p.street_bet
                    last_aggressor = seat
                    # re-open: everyone else must respond
                    for s in list(acted):
                        if s != seat: acted.discard(s)
                acted.add(seat)

            if sum(1 for q in players if not q.folded) <= 1:
                return pot

        if not progress:
            break

    return pot

# ──────────────────────────── Single hand ─────────────────────────────────────
def play_hand(players, dealer_seat, big_blind):
    deck = new_deck()

    # Reset all players; mark chipless players as folded (not in this hand)
    for p in players:
        p.reset()
        if p.chips == 0:
            p.folded = True

    alive = [i for i, p in enumerate(players) if p.chips > 0]
    if len(alive) < 2:
        return

    n  = len(alive)
    # Resolve dealer/blind positions within the alive list
    d  = min(range(n), key=lambda k: (alive[k] - dealer_seat) % len(players))
    sb = alive[(d + 1) % n]
    bb = alive[(d + 2) % n]
    # Pre-flop first actor: UTG (one past BB), post-flop first: SB
    utg        = alive[(d + 3) % n]
    first_post = alive[(d + 1) % n]

    pot   = 0
    small = max(1, big_blind // 2)

    def post_blind(seat, amt):
        nonlocal pot
        p   = players[seat]
        pay = min(amt, p.chips)
        p.chips      -= pay
        p.street_bet  = pay
        pot          += pay
        if p.chips == 0: p.all_in = True

    post_blind(sb, small)
    post_blind(bb, big_blind)

    # Deal hole cards to everyone still alive
    for i in alive:
        players[i].hole = [deck.pop(), deck.pop()]

    # ── Pre-flop betting ──
    pot = betting_round(players, pot, big_blind, utg,
                        {'community': [], 'street': 'preflop'})

    community = []
    for street, n_cards in [('flop', 3), ('turn', 1), ('river', 1)]:
        if sum(1 for q in players if not q.folded) <= 1:
            break
        deck.pop()                          # burn card
        community += [deck.pop() for _ in range(n_cards)]
        for p in players: p.street_bet = 0
        pot = betting_round(players, pot, 0, first_post,
                            {'community': community, 'street': street})

    # ── Showdown ──
    contenders = [p for p in players if not p.folded]
    if len(contenders) == 1:
        contenders[0].chips += pot
        return
    ranked  = sorted(contenders,
                     key=lambda p: best_hand(p.hole + community), reverse=True)
    top     = best_hand(ranked[0].hole + community)
    winners = [p for p in ranked if best_hand(p.hole + community) == top]
    share, rem = divmod(pot, len(winners))
    for w in winners: w.chips += share
    winners[0].chips += rem            # remainder to first winner (tiebreak)

# ──────────────────────────── Tournament ──────────────────────────────────────
def run_tournament(starting_chips: int = 1500, base_blind: int = 10) -> str:
    """
    Runs a single tournament to completion.
    Returns the name of the last player standing.
    """
    players = [Player(name, starting_chips, fn) for name, fn in STRATEGIES]
    hand    = 0
    while True:
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        if hand > 3000:                     # safety valve against infinite loops
            break
        hand  += 1
        blind  = base_blind * (1 + hand // 40)   # escalating blinds every 40 hands
        seats  = [i for i, p in enumerate(players) if p.chips > 0]
        dealer = seats[hand % len(seats)]
        play_hand(players, dealer, blind)

    return max(players, key=lambda p: p.chips).name

# ─────────────────────────────── Main ─────────────────────────────────────────
if __name__ == '__main__':
    SIMS           = 100
    STARTING_CHIPS = 1500

    wins = {name: 0 for name, _ in STRATEGIES}

    print("=" * 68)
    print("  Texas Hold'em Tournament Simulator  —  suflair GPT humiliation arc")
    print("=" * 68)
    print(f"\n  6 players  |  {STARTING_CHIPS} chips each  |  {SIMS} tournaments\n")
    print("  Strategies:")
    for name, _ in STRATEGIES:
        marker = "  <- THE MONKEY (always all-in)" if name == 'P1_AllIn' else ""
        print(f"    {LABELS[name]}{marker}")
    print()

    for i in range(SIMS):
        w = run_tournament(starting_chips=STARTING_CHIPS)
        wins[w] += 1
        if (i + 1) % 25 == 0:
            leader = max(wins, key=wins.get)
            print(f"  [{i+1:3d}/100]  current leader -> {LABELS[leader]}  ({wins[leader]} wins)")

    # ── Histogram ──
    BAR = 44
    mx  = max(wins.values()) or 1
    sorted_results = sorted(wins.items(), key=lambda x: x[1], reverse=True)

    print()
    print("=" * 72)
    print("   WINNER WINNER CHICKEN DINNER  —  THE ROUNDER HISTOGRAM")
    print("=" * 72)
    print()

    for rank_pos, (name, count) in enumerate(sorted_results):
        pct   = count / SIMS * 100
        bar   = chr(9608) * int(count / mx * BAR)   # full block █
        crown = "  <- CROWNED ROUNDER" if rank_pos == 0 else ""
        print(f"  {LABELS[name]:<38}  {bar:<{BAR}}  {count:3d}/100  ({pct:4.1f}%){crown}")

    print()
    print("=" * 72)

    champion    = sorted_results[0][0]
    monkey_wins = wins['P1_AllIn']
    best_wins   = sorted_results[0][1]
    gap         = best_wins - monkey_wins

    print(f"\n  CROWNED ROUNDER : {LABELS[champion]}  ({best_wins}/100 wins)")
    print(f"  The monkey      : {monkey_wins}/100 wins")
    print()

    if monkey_wins == best_wins:
        print("  !! CHAOS REIGNS. The monkey won. Probability theory is dead.")
    elif monkey_wins >= best_wins * 0.75:
        print("  The monkey nearly won. Elaborate strategies: please try harder.")
    elif monkey_wins >= best_wins * 0.5:
        print("  Monkey held its own. Random all-in aggression is genuinely scary.")
    else:
        print(f"  Elaborate strategies beat the monkey by {gap} wins.")
        print("  Suflair GPT: this is what *thinking* looks like. Take notes.")
