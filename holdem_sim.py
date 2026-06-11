#!/usr/bin/env python3
"""
Texas Hold'em Battle Royale — 100 Tournament Simulations
─────────────────────────────────────────────────────────
Player 1 : All-In Maniac        (simple: always shove)
Player 2 : Tight-Aggressive     (TAG — premium hands only, big bets)
Player 3 : Loose-Aggressive     (LAG — wide range, relentless pressure)
Player 4 : GTO Math Wizard      (equity vs pot-odds, mixed frequencies)
Player 5 : Position Captain     (adjusts range by table position)
Player 6 : Adaptive Reader      (detects table aggression, exploits it)

Last player standing = tournament winner.
"""

import random
import itertools
from collections import Counter

# ══════════════════════════════════════════════════════════════════════
# CARDS & DECK
# ══════════════════════════════════════════════════════════════════════

RANKS  = list(range(2, 15))      # 2–14 (Ace high = 14)
SUITS  = 'cdhs'
DECK   = [(r, s) for r in RANKS for s in SUITS]

def fresh_deck():
    d = DECK[:]
    random.shuffle(d)
    return d

# ══════════════════════════════════════════════════════════════════════
# HAND EVALUATION (5-card scorer → comparable tuple)
# ══════════════════════════════════════════════════════════════════════

def eval5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    rc    = Counter(ranks)

    flush    = len(set(suits)) == 1
    straight = len(set(ranks)) == 5 and ranks[0] - ranks[4] == 4
    wheel    = set(ranks) == {14, 2, 3, 4, 5}
    if wheel:
        straight, ranks = True, [5, 4, 3, 2, 1]

    grps     = sorted(rc.items(), key=lambda x: (x[1], x[0]), reverse=True)
    g_cnt    = [g[1] for g in grps]
    g_rnk    = [g[0] for g in grps]

    if straight and flush:      return (8, ranks[0])
    if g_cnt[0] == 4:           return (7, g_rnk[0], g_rnk[1])
    if g_cnt[:2] == [3, 2]:     return (6, g_rnk[0], g_rnk[1])
    if flush:                   return (5, *ranks)
    if straight:                return (4, ranks[0])
    if g_cnt[0] == 3:           return (3, g_rnk[0], g_rnk[1], g_rnk[2])
    if g_cnt[:2] == [2, 2]:     return (2, g_rnk[0], g_rnk[1], g_rnk[2])
    if g_cnt[0] == 2:           return (1, g_rnk[0], g_rnk[1], g_rnk[2], g_rnk[3])
    return (0, *ranks)

def best_hand(hole, board):
    return max(eval5(c) for c in itertools.combinations(hole + board, 5))

# ══════════════════════════════════════════════════════════════════════
# MONTE-CARLO EQUITY ESTIMATOR
# ══════════════════════════════════════════════════════════════════════

def equity(hole, board, n_opp, sims=60):
    """Win probability for hole cards vs n_opp unknown hands."""
    known     = set(map(tuple, hole + board))
    remaining = [c for c in DECK if tuple(c) not in known]
    wins      = 0

    for _ in range(sims):
        random.shuffle(remaining)
        idx      = 0
        sim_board = list(board)
        need     = 5 - len(sim_board)
        sim_board += remaining[idx:idx + need]
        idx      += need

        my_best  = best_hand(hole, sim_board)
        beat     = False
        for _ in range(n_opp):
            if idx + 2 > len(remaining):
                beat = True
                break
            opp_best = best_hand(remaining[idx:idx + 2], sim_board)
            idx += 2
            if opp_best >= my_best:
                beat = True
                break
        if not beat:
            wins += 1

    return wins / sims

# ══════════════════════════════════════════════════════════════════════
# PLAYER
# ══════════════════════════════════════════════════════════════════════

class Player:
    __slots__ = ['pid', 'name', 'chips', 'strategy',
                 'hole', 'street_bet', 'folded', 'all_in']

    def __init__(self, pid, name, chips, strategy):
        self.pid        = pid
        self.name       = name
        self.chips      = chips
        self.strategy   = strategy
        self.hole       = []
        self.street_bet = 0
        self.folded     = False
        self.all_in     = False

    def reset(self):
        self.hole       = []
        self.street_bet = 0
        self.folded     = False
        self.all_in     = False

    def __repr__(self):
        return f"{self.name}(${self.chips})"


# ══════════════════════════════════════════════════════════════════════
# GAME STATE (read-only view passed into strategy functions)
# ══════════════════════════════════════════════════════════════════════

class State:
    __slots__ = ['players', 'board', 'pot', 'current_bet',
                 'street', 'dealer_idx', 'me_idx']

    def __init__(self, players, board, pot, current_bet, street, dealer_idx, me_idx):
        self.players     = players
        self.board       = board
        self.pot         = pot
        self.current_bet = current_bet
        self.street      = street
        self.dealer_idx  = dealer_idx
        self.me_idx      = me_idx

    @property
    def me(self):           return self.players[self.me_idx]
    @property
    def to_call(self):      return max(0, self.current_bet - self.me.street_bet)
    @property
    def n_active(self):     return sum(1 for p in self.players if not p.folded)
    @property
    def n_opp(self):        return sum(1 for p in self.players
                                       if not p.folded and p.pid != self.me.pid)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 0 — THE MANIAC  (Player 1)
# "if my_turn: bet = All in fi"
# ══════════════════════════════════════════════════════════════════════

def strategy_maniac(s: State):
    """Pure chaos. Every single turn: shove all the chips in."""
    return ('raise', s.me.chips + s.me.street_bet)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 1 — TIGHT-AGGRESSIVE  (Player 2)
# Plays only premium hands pre-flop; bets/raises hard post-flop.
# ══════════════════════════════════════════════════════════════════════

def strategy_tag(s: State):
    """
    Preflop: top ~15% of starting hands (TT+, AK, AQs, strong pairs).
    Postflop: equity > 65% → size bet; 45–65% → call if cheap; else fold.
    """
    me   = s.me
    r1, r2 = sorted([c[0] for c in me.hole], reverse=True)
    suited = me.hole[0][1] == me.hole[1][1]
    pair   = r1 == r2
    tc     = s.to_call
    pot    = s.pot

    if s.street == 'preflop':
        premium = (pair and r1 >= 10) or (r1 == 14 and r2 >= 11) \
                  or (r1 == 14 and r2 == 12)
        strong  = (pair and r1 >= 7)  or (r1 == 14 and r2 >= 10 and suited) \
                  or (r1 == 13 and r2 >= 11 and suited)

        if premium:
            raise_to = min(me.chips + me.street_bet,
                           max(s.current_bet * 3 + 40, s.current_bet + 60))
            return ('raise', raise_to)
        if strong and tc <= pot * 0.20:
            return ('call', 0)
        if tc == 0:
            return ('check', 0)
        return ('fold', 0)

    # ── post-flop ──
    n = s.n_opp
    if n == 0:
        return ('check', 0)
    eq = equity(me.hole, s.board, n)

    if eq > 0.65:
        bet_to = min(me.chips + me.street_bet,
                     s.current_bet + max(1, int(pot * 0.75)))
        return ('raise', bet_to)
    if eq > 0.45 and tc <= pot * 0.35:
        return ('call', 0)
    if tc == 0:
        return ('check', 0)
    return ('fold', 0)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 2 — LOOSE-AGGRESSIVE  (Player 3)
# Wide opening range, relentless pressure, frequent semi-bluffs.
# ══════════════════════════════════════════════════════════════════════

def strategy_lag(s: State):
    """
    Preflop: plays ~40% of hands.  Raises 65% of the time with playables.
    Postflop: bets/raises when equity > 50% OR random bluff trigger fires (30%).
    Gives up cheaply with pure air on the river.
    """
    me    = s.me
    r1, r2 = sorted([c[0] for c in me.hole], reverse=True)
    suited = me.hole[0][1] == me.hole[1][1]
    pair   = r1 == r2
    conn   = abs(r1 - r2) <= 2
    tc     = s.to_call
    pot    = s.pot

    if s.street == 'preflop':
        playable = (r1 >= 11) or pair or (suited and r1 >= 8) \
                   or (r1 >= 9 and r2 >= 7) or (conn and r1 >= 7) \
                   or (r1 >= 8 and r2 >= 8)

        if not playable:
            if tc == 0:    return ('check', 0)
            if tc <= 20:   return ('call',  0)
            return ('fold', 0)

        # 65% aggression raise
        if random.random() < 0.65:
            extra   = int(pot * (0.7 + random.random() * 0.6)) + tc
            raise_to = min(me.chips + me.street_bet,
                           s.current_bet + max(extra, 20))
            return ('raise', raise_to)
        return ('call', 0)

    # ── post-flop ──
    n = s.n_opp
    if n == 0:
        return ('check', 0)

    # Skip equity on river pure-bluff if street is river with weak draw
    eq      = equity(me.hole, s.board, n)
    bluffing = random.random() < 0.30

    if eq > 0.50 or bluffing:
        size     = int(pot * (0.55 + random.random() * 0.45)) + tc
        raise_to = min(me.chips + me.street_bet,
                       s.current_bet + max(size, 1))
        return ('raise', raise_to)
    if eq > 0.32:
        if tc == 0:              return ('check', 0)
        if tc <= pot * 0.40:     return ('call',  0)
    if tc == 0:
        return ('check', 0)
    return ('fold', 0)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 3 — GTO MATH WIZARD  (Player 4)
# Equity vs pot-odds with balanced mixed-strategy frequencies.
# ══════════════════════════════════════════════════════════════════════

def strategy_gto(s: State):
    """
    Computes pot-odds threshold.  Bets when equity > threshold with
    frequency proportional to edge.  Bluffs at GTO-approximate frequency
    (opponent's pot-odds) to keep range balanced and unexploitable.
    """
    me    = s.me
    tc    = s.to_call
    pot   = s.pot
    n     = s.n_opp

    pot_odds_needed = tc / (tc + pot) if (tc + pot) > 0 else 0.0

    # Preflop rule-based (avoid MC overhead)
    r1, r2 = sorted([c[0] for c in me.hole], reverse=True)
    suited = me.hole[0][1] == me.hole[1][1]
    pair   = r1 == r2

    if s.street == 'preflop':
        hand_score = (r1 + r2) / 2 + (3 if pair else 0) + (1 if suited else 0)
        if hand_score >= 13.5:
            raise_to = min(me.chips + me.street_bet,
                           s.current_bet + int(pot * 0.9) + 40)
            return ('raise', max(raise_to, s.current_bet + 20))
        if hand_score >= 11.0:
            mix = random.random()
            if mix < 0.5:
                raise_to = min(me.chips + me.street_bet,
                               s.current_bet + int(pot * 0.5) + 20)
                return ('raise', max(raise_to, s.current_bet + 20))
            if tc <= pot * 0.25:
                return ('call', 0)
        if hand_score >= 9.5 and tc == 0:
            return ('check', 0)
        if hand_score >= 9.0 and tc <= 20:
            return ('call', 0)
        if tc == 0:
            return ('check', 0)
        return ('fold', 0)

    # ── post-flop ──
    if n == 0:
        return ('check', 0)
    eq   = equity(me.hole, s.board, n)
    edge = eq - pot_odds_needed
    rng  = random.random()

    if eq > 0.70:
        if rng < 0.90:
            bet_to = min(me.chips + me.street_bet,
                         s.current_bet + int(pot * (0.55 + eq * 0.45)))
            return ('raise', max(bet_to, s.current_bet + 1))
        return ('call', 0)

    if eq > 0.55:
        if edge > 0.05 and rng < 0.65:
            bet_to = min(me.chips + me.street_bet,
                         s.current_bet + int(pot * 0.45))
            return ('raise', max(bet_to, s.current_bet + 1))
        if tc <= pot * 0.35:
            return ('call', 0)
        if tc == 0:
            return ('check', 0)
        return ('fold', 0)

    if eq > 0.40:
        if tc == 0:    return ('check', 0)
        if edge > 0:   return ('call',  0)
        return ('fold', 0)

    # Balanced bluff frequency ≈ villain's pot-odds × dampener
    bluff_freq = max(0.0, (1.0 - pot_odds_needed)) * 0.20
    if tc == 0 and rng < bluff_freq:
        bet_to = min(me.chips + me.street_bet,
                     s.current_bet + int(pot * 0.55))
        return ('raise', max(bet_to, s.current_bet + 1))
    if tc == 0:
        return ('check', 0)
    return ('fold', 0)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 4 — POSITION CAPTAIN  (Player 5)
# Hand ranges scale with position; steals in late, traps in early.
# ══════════════════════════════════════════════════════════════════════

def _position(me_idx, dealer_idx, n):
    """0=early, 1=middle, 2=late/button, 3=blinds"""
    rel = (me_idx - dealer_idx) % n
    if rel in (1, 2):                          return 3  # SB / BB
    if rel in (n - 1, n - 2):                  return 2  # BTN / CO
    if rel <= n // 2:                           return 0  # UTG / early
    return 1                                              # middle

def strategy_position(s: State):
    """
    Early position: top 15% of hands.
    Middle position: top 25%.
    Late/button: top 40%, blind-steal when folded to.
    Post-flop: continuation-bet in position; check-fold without equity OOP.
    """
    me   = s.me
    tc   = s.to_call
    pot  = s.pot
    n    = len(s.players)
    pos  = _position(s.me_idx, s.dealer_idx, n)
    n_active = s.n_active
    n_opp    = s.n_opp

    r1, r2 = sorted([c[0] for c in me.hole], reverse=True)
    suited  = me.hole[0][1] == me.hole[1][1]
    pair    = r1 == r2
    conn    = abs(r1 - r2) <= 1

    if s.street == 'preflop':
        if pos == 2:    # late — wide
            playable = (r1 >= 9) or pair or suited or \
                       (r1 >= 8 and r2 >= 6) or conn
        elif pos == 1:  # middle
            playable = (r1 >= 11) or (pair and r1 >= 6) or \
                       (suited and r1 >= 9 and r2 >= 7)
        else:           # early / blinds
            playable = (pair and r1 >= 8) or (r1 == 14 and r2 >= 10) or \
                       (r1 >= 12 and r2 >= 11 and suited)

        if not playable:
            if tc == 0:  return ('check', 0)
            return ('fold', 0)

        # Steal when late and few players behind
        if pos == 2 and n_active <= 3:
            raise_to = min(me.chips + me.street_bet,
                           s.current_bet * 2 + 30)
            return ('raise', max(raise_to, s.current_bet + 20))

        if (pair and r1 >= 9) or (r1 == 14 and r2 >= 11):
            raise_to = min(me.chips + me.street_bet,
                           s.current_bet * 3 + 30)
            return ('raise', max(raise_to, s.current_bet + 20))

        call_threshold = 0.15 + 0.05 * pos
        if tc <= pot * call_threshold:
            return ('call', 0)
        if tc == 0:
            return ('check', 0)
        return ('fold', 0)

    # ── post-flop ──
    if n_opp == 0:
        return ('check', 0)
    eq       = equity(me.hole, s.board, n_opp)
    in_pos   = (pos == 2)
    eff_eq   = eq + (0.06 if in_pos else 0)

    if eff_eq > 0.58:
        bet_to = min(me.chips + me.street_bet,
                     s.current_bet + int(pot * (0.50 + (0.10 if in_pos else 0))))
        return ('raise', max(bet_to, s.current_bet + 1))

    if eff_eq > 0.40:
        if tc == 0:              return ('check', 0)
        if tc <= pot * 0.38:     return ('call',  0)
        return ('fold', 0)

    # Positional bluff / probe
    if in_pos and tc == 0 and random.random() < 0.32:
        bet_to = min(me.chips + me.street_bet,
                     s.current_bet + int(pot * 0.44))
        return ('raise', max(bet_to, s.current_bet + 1))

    if tc == 0:  return ('check', 0)
    return ('fold', 0)


# ══════════════════════════════════════════════════════════════════════
# STRATEGY 5 — ADAPTIVE READER  (Player 6)
# Detects table aggression; traps maniacs, thin-bets vs passives.
# ══════════════════════════════════════════════════════════════════════

def strategy_adaptive(s: State):
    """
    Reads table aggression from pot/avg-stack ratio.
    High aggression (likely a maniac at the table):
      → tighten preflop, call down wider with top-pair+, induce bluffs.
    Low aggression (passive table):
      → thin-value bet, wider bluff range, exploit limpers.
    """
    me   = s.me
    tc   = s.to_call
    pot  = s.pot
    n    = s.n_opp

    alive_stacks = [p.chips for p in s.players if p.chips > 0]
    avg_stack    = sum(alive_stacks) / max(1, len(alive_stacks))
    aggro        = pot / max(1, avg_stack)      # > 0.35 = wild table
    high_aggro   = aggro > 0.35

    r1, r2 = sorted([c[0] for c in me.hole], reverse=True)
    suited  = me.hole[0][1] == me.hole[1][1]
    pair    = r1 == r2

    if s.street == 'preflop':
        if high_aggro:
            # Trap-mode: only monster hands; call-down top pairs vs shoves
            super_premium = (pair and r1 >= 9) or (r1 == 14 and r2 >= 11)
            solid         = (pair and r1 >= 6) or (r1 >= 12 and r2 >= 10)

            if super_premium:
                if tc >= me.chips * 0.40:       # vs all-in shove: snap-call
                    return ('call', 0)
                raise_to = min(me.chips + me.street_bet,
                               s.current_bet * 2 + int(pot * 0.5))
                return ('raise', max(raise_to, s.current_bet + 20))
            if solid and tc <= me.chips * 0.20:
                return ('call', 0)
        else:
            # Normal/passive table: standard wide open
            playable = (r1 >= 10) or (pair and r1 >= 5) or \
                       (suited and r1 >= 9) or (r1 >= 11 and r2 >= 8)
            if playable:
                if (pair and r1 >= 10) or (r1 == 14 and r2 >= 12):
                    raise_to = min(me.chips + me.street_bet,
                                   s.current_bet * 3 + 30)
                    return ('raise', max(raise_to, s.current_bet + 20))
                if tc <= pot * 0.20:
                    return ('call', 0)

        if tc == 0:  return ('check', 0)
        return ('fold', 0)

    # ── post-flop ──
    if n == 0:
        return ('check', 0)
    eq = equity(me.hole, s.board, n)

    if high_aggro:
        # Induce bets from aggressor; call down wide; raise big for value
        if eq > 0.60:
            bet_to = min(me.chips + me.street_bet,
                         s.current_bet + int(pot * 0.80))
            return ('raise', max(bet_to, s.current_bet + 1))
        if eq > 0.43:
            if tc == 0:              return ('check', 0)   # trap / induce
            if tc <= pot * 0.50:     return ('call',  0)   # call wider
            return ('fold', 0)
    else:
        # Thin-value bet vs passives; occasional bluff
        if eq > 0.52:
            bet_to = min(me.chips + me.street_bet,
                         s.current_bet + int(pot * 0.55))
            return ('raise', max(bet_to, s.current_bet + 1))
        if eq > 0.36:
            if tc <= pot * 0.33:     return ('call', 0)
            if tc == 0:              return ('check', 0)
            return ('fold', 0)
        # Light bluff on passive tables
        if tc == 0 and random.random() < 0.18:
            bet_to = min(me.chips + me.street_bet,
                         s.current_bet + int(pot * 0.50))
            return ('raise', max(bet_to, s.current_bet + 1))

    if tc == 0:  return ('check', 0)
    return ('fold', 0)


# ══════════════════════════════════════════════════════════════════════
# BETTING ROUND ENGINE
# ══════════════════════════════════════════════════════════════════════

BIG_BLIND   = 20
SMALL_BLIND = 10

def betting_round(players, pot, current_bet, street, board, dealer_idx, first_idx):
    """
    Process one street of betting.  Mutates player state in-place.
    Returns updated pot.
    """
    n = len(players)

    def can_act(p):
        return not p.folded and not p.all_in and p.chips > 0

    acted = [False] * n
    queue = [((first_idx + i) % n)
             for i in range(n) if can_act(players[(first_idx + i) % n])]

    iters = 0
    while queue and iters < n * 8:
        iters += 1
        idx = queue.pop(0)
        p   = players[idx]

        if not can_act(p):
            continue

        tc = max(0, current_bet - p.street_bet)

        # Already acted at this bet level and nothing left to call → skip
        if acted[idx] and tc == 0:
            continue

        state = State(players, board, pot, current_bet, street, dealer_idx, idx)
        action, amount = p.strategy(state)
        acted[idx] = True

        if action == 'fold':
            p.folded = True

        elif action in ('check', 'call'):
            chips_in      = min(tc, p.chips)
            p.chips      -= chips_in
            p.street_bet += chips_in
            pot          += chips_in
            if p.chips == 0:
                p.all_in = True

        elif action == 'raise':
            # `amount` = desired total street_bet level after this action
            target   = max(amount, current_bet + max(BIG_BLIND, current_bet // 3))
            target   = min(target, p.street_bet + p.chips)
            chips_in = max(0, target - p.street_bet)
            chips_in = min(chips_in, p.chips)

            p.chips      -= chips_in
            p.street_bet += chips_in
            pot          += chips_in

            if p.street_bet > current_bet:
                current_bet = p.street_bet
                acted       = [False] * n
                acted[idx]  = True
                queue       = [((idx + i) % n)
                               for i in range(1, n) if can_act(players[(idx + i) % n])]

            if p.chips == 0:
                p.all_in = True

    return pot, current_bet

# ══════════════════════════════════════════════════════════════════════
# SINGLE HAND ENGINE
# ══════════════════════════════════════════════════════════════════════

def play_hand(players, dealer_idx):
    """
    Play one complete Texas Hold'em hand.
    Modifies player.chips in-place.
    `players` = only players with chips > 0.
    """
    n = len(players)
    for p in players:
        p.reset()

    # ── deal hole cards ──
    d = fresh_deck()
    for i, p in enumerate(players):
        p.hole = [d[i * 2], d[i * 2 + 1]]
    card_ptr = n * 2
    board    = []

    # ── blinds ──
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    for idx, blind in [(sb_idx, SMALL_BLIND), (bb_idx, BIG_BLIND)]:
        p = players[idx]
        b = min(blind, p.chips)
        p.chips      -= b
        p.street_bet  = b
        if p.chips == 0:
            p.all_in = True

    pot         = players[sb_idx].street_bet + players[bb_idx].street_bet
    current_bet = BIG_BLIND

    # ── helper: first non-folded player starting from idx ──
    def first_from(start):
        for i in range(n):
            p = players[(start + i) % n]
            if not p.folded and p.chips > 0:
                return (start + i) % n
        return start % n

    # ── pre-flop ──
    utg = (dealer_idx + 3) % n
    pot, current_bet = betting_round(
        players, pot, current_bet, 'preflop', board, dealer_idx, utg)

    def alive():
        return [p for p in players if not p.folded]

    if len(alive()) <= 1:
        if alive():
            alive()[0].chips += pot
        return

    # ── flop ──
    card_ptr += 1                                      # burn
    board      = [d[card_ptr], d[card_ptr+1], d[card_ptr+2]]
    card_ptr  += 3
    for p in players: p.street_bet = 0
    current_bet = 0
    pot, current_bet = betting_round(
        players, pot, current_bet, 'flop', board,
        dealer_idx, first_from((dealer_idx + 1) % n))

    if len(alive()) <= 1:
        if alive(): alive()[0].chips += pot
        return

    # ── turn ──
    card_ptr += 1                                      # burn
    board.append(d[card_ptr])
    card_ptr += 1
    for p in players: p.street_bet = 0
    current_bet = 0
    pot, current_bet = betting_round(
        players, pot, current_bet, 'turn', board,
        dealer_idx, first_from((dealer_idx + 1) % n))

    if len(alive()) <= 1:
        if alive(): alive()[0].chips += pot
        return

    # ── river ──
    card_ptr += 1                                      # burn
    board.append(d[card_ptr])
    for p in players: p.street_bet = 0
    current_bet = 0
    pot, current_bet = betting_round(
        players, pot, current_bet, 'river', board,
        dealer_idx, first_from((dealer_idx + 1) % n))

    # ── showdown ──
    contestants = alive()
    if len(contestants) == 1:
        contestants[0].chips += pot
        return

    scored   = [(best_hand(p.hole, board), p) for p in contestants]
    top_score = max(sc[0] for sc in scored)
    winners  = [p for sc, p in scored if sc == top_score]
    split    = pot // len(winners)
    rem      = pot  % len(winners)
    for w in winners:
        w.chips += split
    winners[0].chips += rem   # odd chip to first winner in list


# ══════════════════════════════════════════════════════════════════════
# TOURNAMENT ENGINE
# ══════════════════════════════════════════════════════════════════════

STARTING_CHIPS = 1500

ROSTER = [
    ("P1: All-In Maniac    ",  strategy_maniac),
    ("P2: Tight-Aggressive ",  strategy_tag),
    ("P3: Loose-Aggressive ",  strategy_lag),
    ("P4: GTO Math Wizard  ",  strategy_gto),
    ("P5: Position Captain ",  strategy_position),
    ("P6: Adaptive Reader  ",  strategy_adaptive),
]

def run_tournament():
    players    = [Player(i+1, name, STARTING_CHIPS, fn)
                  for i, (name, fn) in enumerate(ROSTER)]
    dealer_idx = 0
    hands      = 0

    while sum(p.chips > 0 for p in players) > 1 and hands < 4000:
        active = [p for p in players if p.chips > 0]
        play_hand(active, dealer_idx % len(active))
        dealer_idx += 1
        hands += 1

    winner = next((p.name for p in players if p.chips > 0), "Nobody")
    return winner.strip(), hands


# ══════════════════════════════════════════════════════════════════════
# 100 SIMULATIONS  +  ASCII HISTOGRAM
# ══════════════════════════════════════════════════════════════════════

N_SIMS = 100

def run_all():
    wins   = Counter()
    totals = []

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║   TEXAS HOLD'EM BATTLE ROYALE  ·  100 TOURNAMENT SIMULATIONS    ║")
    print("║   suflair gpt pls stand by while you get demolished              ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print(f"  6 players · {STARTING_CHIPS} chips each · last player standing wins\n")

    for i in range(N_SIMS):
        if (i % 20 == 0) or i == N_SIMS - 1:
            print(f"  ↻  simulation {i+1:>3}/{N_SIMS}…", flush=True)
        winner, hands = run_tournament()
        wins[winner] += 1
        totals.append(hands)

    print()
    return wins, totals


def print_histogram(wins, totals):
    order    = [name.strip() for name, _ in ROSTER]
    max_wins = max(wins.values()) if wins else 1
    BAR_W    = 38
    W        = 70

    print("═" * W)
    print("  WINNER WINNER CHICKEN DINNER  ─  FINAL SCOREBOARD")
    print("═" * W)
    print(f"  {'Player':<28}  {'W':>3}  {'%':>5}  {'Histogram'}")
    print(f"  {'─'*28}  {'─'*3}  {'─'*5}  {'─'*BAR_W}")

    for raw_name, _ in ROSTER:
        name  = raw_name.strip()
        w     = wins.get(name, 0)
        pct   = w / N_SIMS * 100
        filled = int(w / max_wins * BAR_W)
        bar    = '█' * filled + '░' * (BAR_W - filled)
        tag    = "  ◄ THE MANIAC" if 'Maniac' in name else ""
        print(f"  {name:<28}  {w:>3}  {pct:>4.1f}%  {bar}{tag}")

    avg_hands = sum(totals) / len(totals) if totals else 0
    print()
    print(f"  Total simulations : {N_SIMS}")
    print(f"  Avg hands / tourn : {avg_hands:.0f}")
    print("═" * W)

    maniac_w = wins.get("P1: All-In Maniac", 0)
    top_name = max(wins, key=wins.get) if wins else "?"
    top_w    = wins.get(top_name, 0)

    print()
    print("  ┌─ VERDICT ──────────────────────────────────────────────────┐")
    if 'Maniac' in top_name:
        print("  │  🔥 THE MANIAC WINS MOST TOURNAMENTS. CHAOS > THEORY.     │")
        print("  │     All those elaborate algorithms: DUST.                  │")
        print("  │     suflair gpt has been thoroughly, catastrophically       │")
        print("  │     humiliated by a one-line if-statement.                 │")
    else:
        print(f"  │  Champion : {top_name:<22}  {top_w:>3} wins ({top_w/N_SIMS*100:.1f}%)   │")
        print(f"  │  Maniac   : {maniac_w:>3} wins ({maniac_w/N_SIMS*100:.1f}%)  ─  chaos contained.     │")
        if maniac_w >= 15:
            print("  │  (Still — that all-in gremlin claimed a shocking slice.)    │")
        print("  │  suflair gpt's 'strategy' still got wrecked by a reckless   │")
        print("  │  all-in bot. Humiliation confirmed. Mission accomplished.    │")
    print("  └────────────────────────────────────────────────────────────┘")
    print()


if __name__ == '__main__':
    random.seed()          # true randomness
    wins, totals = run_all()
    print_histogram(wins, totals)
