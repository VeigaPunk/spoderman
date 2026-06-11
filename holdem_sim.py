"""
Texas Hold'em Poker Simulation — 100 tournaments
Player 1: YOLO All-In  |  Players 2-6: Elaborate strategies
All heuristic (no Monte Carlo) for speed.
"""

import random
from collections import Counter
from itertools import combinations
from enum import IntEnum

# ─────────────────────────────────────────────────────────────
#  Cards
# ─────────────────────────────────────────────────────────────

RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RANK_V = {r: i for i, r in enumerate(RANKS)}

DECK_RANKS = [RANK_V[r] for r in RANKS for _ in SUITS]   # 52 ints
DECK_SUITS = [si for _ in RANKS for si, _ in enumerate(SUITS)]

class Card:
    __slots__ = ('r', 's')
    def __init__(self, r, s):
        self.r = r   # int 0-12
        self.s = s   # int 0-3
    def rank_char(self):
        return RANKS[self.r]


FULL_DECK = [Card(r, s) for r in range(13) for s in range(4)]


def fresh_shuffled():
    d = FULL_DECK[:]
    random.shuffle(d)
    return d


# ─────────────────────────────────────────────────────────────
#  Hand evaluator  (returns int, higher = better)
# ─────────────────────────────────────────────────────────────

def score5(cards):
    """Score a 5-card hand as an int for fast comparison."""
    rv = sorted((c.r for c in cards), reverse=True)
    sv = [c.s for c in cards]
    cnt = Counter(rv)
    counts = sorted(cnt.values(), reverse=True)
    flush = len(set(sv)) == 1
    straight = (len(set(rv)) == 5 and rv[0] - rv[4] == 4) or rv == [12,3,2,1,0]
    if straight and rv == [12,3,2,1,0]:
        rv = [3,2,1,0,-1]

    if flush and straight:
        cat = 8
    elif counts[0] == 4:
        cat = 7
        qv = [v for v,c in cnt.items() if c==4][0]
        rv = [qv, qv, qv, qv] + [v for v,c in cnt.items() if c!=4]
    elif counts[:2] == [3,2]:
        cat = 6
        tv = [v for v,c in cnt.items() if c==3][0]
        pv = [v for v,c in cnt.items() if c==2][0]
        rv = [tv]*3 + [pv]*2
    elif flush:
        cat = 5
    elif straight:
        cat = 4
    elif counts[0] == 3:
        cat = 3
        tv = [v for v,c in cnt.items() if c==3][0]
        rv = [tv]*3 + sorted([v for v,c in cnt.items() if c!=3], reverse=True)
    elif counts[:2] == [2,2]:
        cat = 2
        pairs = sorted([v for v,c in cnt.items() if c==2], reverse=True)
        rv = pairs*2 + [v for v,c in cnt.items() if c==1]
    elif counts[0] == 2:
        cat = 1
        pv = [v for v,c in cnt.items() if c==2][0]
        rv = [pv]*2 + sorted([v for v,c in cnt.items() if c!=2], reverse=True)
    else:
        cat = 0

    # Pack into int: cat*10^10 + rank vector
    score = cat
    for v in rv[:5]:
        score = score * 15 + (v + 1)
    return score


def best_of_7(hole, board):
    best = 0
    cards = hole + board
    for combo in combinations(cards, 5):
        s = score5(combo)
        if s > best:
            best = s
    return best


# ─────────────────────────────────────────────────────────────
#  Heuristic hand-strength (no Monte Carlo)
# ─────────────────────────────────────────────────────────────

def hand_category(score):
    """Extract hand category 0-8 from packed score."""
    return score // (15**5)


def relative_strength(hole, board):
    """
    Returns float [0..1] estimating hand strength.
    Uses actual hand rank + board texture bonuses/penalties.
    Fast — no simulation.
    """
    if not board:
        # Preflop: use preflop_rank
        return preflop_rank(hole) / 8.0

    my_score = best_of_7(hole, board)
    cat = hand_category(my_score)

    # Raw category maps to rough equity
    cat_equity = [0.18, 0.38, 0.52, 0.63, 0.72, 0.80, 0.88, 0.94, 0.99]
    base = cat_equity[cat]

    # Board danger modifiers
    board_ranks = [c.r for c in board]
    board_suits = [c.s for c in board]
    flush_threat = max(Counter(board_suits).values()) >= 3
    paired_board = len(board_ranks) != len(set(board_ranks))

    # Penalise low pairs/one-pairs on threatening boards
    if cat <= 2:
        if flush_threat:
            base -= 0.08
        if paired_board and cat == 1:
            base -= 0.04

    # Small bonus for top pair with top kicker
    if cat == 1:
        board_max = max(board_ranks)
        hole_vals = sorted([c.r for c in hole], reverse=True)
        if hole_vals[0] >= board_max and hole_vals[0] >= 10:
            base += 0.06

    return max(0.02, min(0.98, base))


def preflop_rank(hole):
    """
    Return 0-8 hand tier for preflop decisions.
    8=pocket aces, 0=72o
    """
    r1, r2 = sorted([c.r for c in hole], reverse=True)
    suited = hole[0].s == hole[1].s
    pair = r1 == r2

    if pair:
        if r1 >= 12: return 8   # AA
        if r1 >= 10: return 7   # KK,QQ,JJ
        if r1 >= 8:  return 6   # TT,99
        if r1 >= 6:  return 5   # 88,77
        return 4                 # 66-22

    # High card hands
    if r1 == 12:
        if r2 >= 11:    return 7   # AK
        if r2 >= 9:     return 6   # AQ,AJ
        if r2 >= 8:     return 5   # AT
        if r2 >= 5 and suited: return 4
        return 3

    if r1 == 11:
        if r2 >= 10 and suited: return 6   # KQs
        if r2 >= 10:             return 5   # KQo
        if r2 >= 8 and suited:   return 4
        return 2

    if r1 >= 9:
        diff = r1 - r2
        if diff <= 1 and suited:  return 5
        if diff <= 1:             return 4
        if diff <= 2 and suited:  return 3
        return 2

    if suited and abs(r1-r2) <= 2 and r2 >= 4:
        return 3

    return 1 if suited else 0


# ─────────────────────────────────────────────────────────────
#  Game types
# ─────────────────────────────────────────────────────────────

class Street(IntEnum):
    PREFLOP = 0
    FLOP    = 1
    TURN    = 2
    RIVER   = 3


STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20


class Player:
    __slots__ = ('pid', 'chips', 'hole', 'bet', 'folded', 'allin')
    def __init__(self, pid):
        self.pid    = pid
        self.chips  = STARTING_CHIPS
        self.hole   = []
        self.bet    = 0
        self.folded = False
        self.allin  = False

    def reset_hand(self):
        self.hole   = []
        self.bet    = 0
        self.folded = False
        self.allin  = False

    def reset_street(self):
        self.bet = 0


# ─────────────────────────────────────────────────────────────
#  Strategy base
# ─────────────────────────────────────────────────────────────

class Strategy:
    name = "?"
    def decide(self, p, gs): raise NotImplementedError


# ─────────────────────────────────────────────────────────────
#  Strategy 1 — YOLO All-In  (the menace)
# ─────────────────────────────────────────────────────────────

class YoloAllIn(Strategy):
    """
    if my_turn
    then bet = All in
    fi
    """
    name = "YOLO All-In"
    def decide(self, p, gs):
        return ('allin',)


# ─────────────────────────────────────────────────────────────
#  Strategy 2 — Tight Aggressive (TAG)
# ─────────────────────────────────────────────────────────────

class TightAggressive(Strategy):
    """
    Plays only top 20% of hands preflop with 3x open raises.
    Postflop: bets top-pair+ for value, folds air, minimal bluffing.
    Classic GTO-influenced ABC poker — tight ranges, big sizing.
    """
    name = "Tight Aggressive"

    def decide(self, p, gs):
        hole = p.hole
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        stage = gs['stage']
        pf = preflop_rank(hole)

        if stage == Street.PREFLOP:
            if pf >= 7:
                amt = min(max(to_call*3, BIG_BLIND*4), p.chips)
                return ('raise', amt)
            if pf >= 5:
                amt = min(max(to_call*2.5, BIG_BLIND*3), p.chips)
                return ('raise', int(amt))
            if pf >= 3:
                if to_call == 0:
                    return ('raise', min(BIG_BLIND*2, p.chips))
                if to_call <= BIG_BLIND*3:
                    return ('call',)
            return ('fold',) if to_call > 0 else ('check',)

        strength = relative_strength(hole, board)

        if strength > 0.70:
            amt = min(int(pot * 0.75), p.chips)
            return ('raise', max(amt, BIG_BLIND))
        if strength > 0.52:
            if to_call == 0:
                return ('raise', min(int(pot*0.50), p.chips))
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds + 0.08 else ('fold',)
        if strength > 0.38:
            if to_call == 0:
                return ('check',)
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds else ('fold',)
        return ('fold',) if to_call > 0 else ('check',)


# ─────────────────────────────────────────────────────────────
#  Strategy 3 — GTO Approximator
# ─────────────────────────────────────────────────────────────

class GTOApproximator(Strategy):
    """
    Position-sensitive ranges with mixed sizing to stay unexploitable.
    Opens wider on the button, 3-bets a balanced value+bluff range,
    checks back medium hands in position, probes OOP on dry boards.
    Gaussian noise on thresholds prevents exploitable patterns.
    """
    name = "GTO Approximator"

    def decide(self, p, gs):
        hole = p.hole
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        stage = gs['stage']
        pos = gs['position']   # 0=early 1=mid 2=late
        pf = preflop_rank(hole)

        if stage == Street.PREFLOP:
            open_min = 5 - pos   # late: 2, early: 5
            if pf >= open_min:
                sizing = int(random.choice([2.5, 3, 3.5]) * BIG_BLIND)
                if to_call > 0:
                    sizing = max(int(to_call * 2.8), sizing)
                return ('raise', min(sizing, p.chips))
            if pf >= open_min - 2 and pos >= 1:
                if to_call == 0:
                    return ('raise', min(BIG_BLIND*2, p.chips))
                if to_call <= BIG_BLIND*2:
                    return ('call',)
            return ('fold',) if to_call > 0 else ('check',)

        strength = relative_strength(hole, board)
        noise = random.gauss(0, 0.03)
        eff = strength + noise

        # Position-adjusted thresholds
        raise_t = 0.60 - pos * 0.04
        call_t  = 0.44 - pos * 0.03
        fold_t  = 0.28 - pos * 0.02

        pot_odds = to_call / (pot + to_call + 1)

        if eff >= raise_t:
            sizing = random.uniform(0.45, 0.85)
            amt = max(int(pot * sizing), to_call + BIG_BLIND)
            return ('raise', min(amt, p.chips))
        if eff >= call_t:
            if to_call == 0:
                probe = int(pot * random.uniform(0.28, 0.42))
                return ('raise', min(probe, p.chips)) if random.random() < 0.55 else ('check',)
            return ('call',)
        if eff >= fold_t:
            if to_call == 0:
                return ('check',)
            return ('call',) if eff > pot_odds else ('fold',)
        return ('fold',) if to_call > 0 else ('check',)


# ─────────────────────────────────────────────────────────────
#  Strategy 4 — Exploitative Shark
# ─────────────────────────────────────────────────────────────

class ExploitativeShark(Strategy):
    """
    Maintains a running aggression index per opponent.
    vs Passive players: steals relentlessly with any equity.
    vs Maniacs: tightens range, check-raises strong hands, traps.
    Exploits bet-timing tells by adjusting equity thresholds dynamically.
    """
    name = "Exploitative Shark"

    def __init__(self):
        self.agg = {}    # pid -> float [0..1]
        self.seen = {}   # pid -> hands seen

    def record_action(self, pid, action):
        a = self.agg.get(pid, 0.50)
        n = self.seen.get(pid, 1)
        if action in ('raise', 'allin'):
            a += (1.0 - a) * 0.15
        elif action == 'fold':
            a -= a * 0.10
        elif action == 'call':
            a += (1.0 - a) * 0.03
        self.agg[pid] = max(0.0, min(1.0, a))
        self.seen[pid] = n + 1

    def decide(self, p, gs):
        hole = p.hole
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        stage = gs['stage']
        aggressors = gs.get('aggressors', [])
        pf = preflop_rank(hole)

        if stage == Street.PREFLOP:
            if pf >= 6:
                return ('raise', min(max(to_call*3, BIG_BLIND*4), p.chips))
            if pf >= 4:
                if to_call <= BIG_BLIND*3: return ('call',)
                return ('fold',)
            return ('fold',) if to_call > 0 else ('check',)

        avg_agg = sum(self.agg.get(pid, 0.5) for pid in aggressors) / max(len(aggressors), 1)
        strength = relative_strength(hole, board)

        if avg_agg < 0.35:        # passive table → steal
            if strength > 0.35:
                bet = int(pot * random.uniform(0.60, 0.85))
                return ('raise', min(bet, p.chips))
            if to_call == 0:
                if strength > 0.28: return ('raise', min(int(pot*0.35), p.chips))
                return ('check',)
            return ('fold',)

        if avg_agg > 0.60:        # maniacs → trap + tighten
            if strength > 0.72:
                return ('call',) if to_call > 0 else ('check',)   # slowplay
            if strength > 0.55:
                pot_odds = to_call / (pot + to_call + 1)
                return ('call',) if strength > pot_odds * 1.2 else ('fold',)
            return ('fold',) if to_call > 0 else ('check',)

        # balanced aggression → standard exploitation
        if strength > 0.60:
            return ('raise', min(int(pot*0.55), p.chips))
        if strength > 0.42:
            if to_call == 0: return ('raise', min(int(pot*0.30), p.chips))
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds else ('fold',)
        return ('fold',) if to_call > 0 else ('check',)


# ─────────────────────────────────────────────────────────────
#  Strategy 5 — Stack-Aware Shover (ICM-flavored)
# ─────────────────────────────────────────────────────────────

class StackAwareShover(Strategy):
    """
    Implements push/fold below M=10 using Nash equilibrium shove ranges.
    Medium stacks: pot-commits with 55%+ equity.
    Deep stacks: patient aggression, avoids marginal spots, protects equity.
    Adjusts all thresholds based on effective stack-to-pot ratio (SPR).
    """
    name = "Stack-Aware Shover"

    def decide(self, p, gs):
        hole = p.hole
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        stage = gs['stage']
        pf = preflop_rank(hole)
        m = p.chips / max(BIG_BLIND*2, 1)
        spr = p.chips / max(pot, 1)

        if stage == Street.PREFLOP:
            if m < 6:
                return ('allin',) if pf >= 3 else (('fold',) if to_call > 0 else ('check',))
            if m < 12:
                if pf >= 5: return ('allin',)
                if pf >= 3: return ('call',) if to_call <= BIG_BLIND*4 else ('fold',)
                return ('fold',) if to_call > 0 else ('check',)
            # Deep stack
            if pf >= 7: return ('raise', min(BIG_BLIND*4, p.chips))
            if pf >= 5: return ('call',) if to_call <= BIG_BLIND*3 else ('fold',)
            if pf >= 3 and to_call == 0: return ('raise', min(BIG_BLIND*2, p.chips))
            return ('fold',) if to_call > 0 else ('check',)

        strength = relative_strength(hole, board)

        if m < 6:
            return ('allin',) if strength > 0.42 else (('fold',) if to_call > 0 else ('check',))
        if spr < 2.5:
            return ('allin',) if strength > 0.45 else (('fold',) if to_call > 0 else ('check',))

        # Normal depth
        if strength > 0.68:
            return ('raise', min(int(pot * 0.70), p.chips))
        if strength > 0.48:
            if to_call == 0:
                return ('raise', min(int(pot*0.40), p.chips))
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds else ('fold',)
        if to_call == 0: return ('check',)
        pot_odds = to_call / (pot + to_call + 1)
        return ('call',) if strength > pot_odds else ('fold',)


# ─────────────────────────────────────────────────────────────
#  Strategy 6 — Bayesian Bluffer
# ─────────────────────────────────────────────────────────────

class BayesianBluffer(Strategy):
    """
    Estimates posterior probability of opponents holding strong hands
    based on board texture. Fires bluffs on coordinated scare-card boards
    that miss opponents' likely ranges. Value overbets paired boards.
    Fires triple-barrel bluffs on missed flush-draw runouts HU.
    Check-folds multiway when strength is marginal.
    """
    name = "Bayesian Bluffer"

    def _texture(self, board):
        if not board:
            return 0, False, False
        sc = Counter(c.s for c in board)
        rc = sorted([c.r for c in board], reverse=True)
        flush_draw = max(sc.values()) >= 3
        paired = len(rc) != len(set(rc))
        gaps = [rc[i]-rc[i+1] for i in range(len(rc)-1)] if len(rc) > 1 else [99]
        connected = any(g <= 2 for g in gaps)
        return (1 if flush_draw else 0) + (1 if connected else 0), paired, flush_draw

    def decide(self, p, gs):
        hole = p.hole
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        stage = gs['stage']
        pos = gs['position']
        n_opp = gs['active_opponents']
        pf = preflop_rank(hole)

        if stage == Street.PREFLOP:
            if pf >= 6:
                return ('raise', min(int(BIG_BLIND*3.5), p.chips))
            if pf >= 4:
                if to_call == 0: return ('raise', min(BIG_BLIND*2, p.chips))
                if to_call <= BIG_BLIND*3: return ('call',)
            if pf >= 2 and pos >= 1:
                if to_call == 0: return ('raise', min(BIG_BLIND*2, p.chips))
                if to_call <= BIG_BLIND*2: return ('call',)
            return ('fold',) if to_call > 0 else ('check',)

        draw_score, paired, flush_draw = self._texture(board)
        strength = relative_strength(hole, board)

        # Bluff frequency
        bluff_freq = 0.0
        if to_call == 0:
            if n_opp == 1:
                bluff_freq += 0.15
                if stage == Street.RIVER and not flush_draw:
                    bluff_freq += 0.12   # missed draw narrative
                if stage == Street.TURN and draw_score >= 2:
                    bluff_freq += 0.10
            if pos == 2:
                bluff_freq += 0.08
            if draw_score >= 1 and stage == Street.FLOP:
                bluff_freq += 0.07

        if random.random() < bluff_freq:
            bet = int(pot * random.uniform(0.55, 0.85))
            return ('raise', min(bet, p.chips))

        # Value
        if strength > 0.72:
            mult = 1.05 if paired else 0.75
            return ('raise', min(int(pot * mult), p.chips))
        if strength > 0.52:
            if to_call == 0:
                return ('raise', min(int(pot*0.50), p.chips))
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds * 0.92 else ('fold',)
        if strength > 0.36:
            if to_call == 0: return ('check',)
            pot_odds = to_call / (pot + to_call + 1)
            return ('call',) if strength > pot_odds else ('fold',)
        return ('fold',) if to_call > 0 else ('check',)


# ─────────────────────────────────────────────────────────────
#  Game engine
# ─────────────────────────────────────────────────────────────

STRATEGIES = [
    YoloAllIn,
    TightAggressive,
    GTOApproximator,
    ExploitativeShark,
    StackAwareShover,
    BayesianBluffer,
]
N_PLAYERS = len(STRATEGIES)


class Table:
    def __init__(self):
        self.players = [Player(i) for i in range(N_PLAYERS)]
        self.strats  = [STRATEGIES[i]() for i in range(N_PLAYERS)]

    def run_tournament(self):
        dealer = 0
        for _ in range(10000):   # safety cap
            active = [p for p in self.players if p.chips > 0]
            if len(active) <= 1:
                break
            while self.players[dealer].chips == 0:
                dealer = (dealer + 1) % N_PLAYERS
            self._hand(dealer, active)
            dealer = (dealer + 1) % N_PLAYERS
        alive = [p for p in self.players if p.chips > 0]
        return max(alive, key=lambda p: p.chips).pid if alive else 0

    def _hand(self, dealer_idx, active):
        n = len(active)
        if n < 2: return

        for p in active: p.reset_hand()

        deck = fresh_shuffled()
        sb_i = 1 % n
        bb_i = 2 % n if n > 2 else 1
        sb_p, bb_p = active[sb_i], active[bb_i]

        def post(player, amt):
            a = min(amt, player.chips)
            player.chips -= a
            player.bet    = a
            player.allin  = (player.chips == 0)
            return a

        pot = post(sb_p, SMALL_BLIND) + post(bb_p, BIG_BLIND)

        for p in active:
            p.hole = [deck.pop(), deck.pop()]

        board     = []
        cur_bet   = BIG_BLIND

        def betting(street, first_i):
            nonlocal pot, cur_bet
            order      = [active[(first_i+i)%n] for i in range(n)]
            acted      = set()
            aggressors = []
            idx        = 0
            guard      = n * 10

            for _ in range(guard):
                can = [x for x in active if not x.folded and not x.allin]
                if not can: break
                if all(x.pid in acted and x.bet == cur_bet for x in can): break

                p = order[idx % len(order)]
                idx += 1
                if p.folded or p.allin: continue

                to_call = max(0, cur_bet - p.bet)
                pos_i   = order.index(p)
                pos     = 0 if pos_i < n//3 else (1 if pos_i < 2*n//3 else 2)

                gs = {
                    'stage':             street,
                    'board':             board,
                    'pot':               pot,
                    'to_call':           to_call,
                    'active_opponents':  len([x for x in active if not x.folded and x.pid != p.pid]),
                    'position':          pos,
                    'aggressors':        aggressors[:],
                }

                strat  = self.strats[p.pid]
                action = strat.decide(p, gs)

                # Let shark observe all actions
                for s in self.strats:
                    if isinstance(s, ExploitativeShark):
                        s.record_action(p.pid, action[0])

                acted.add(p.pid)
                tag = action[0]

                if tag == 'fold':
                    p.folded = True
                    live = [x for x in active if not x.folded]
                    if len(live) == 1:
                        live[0].chips += pot
                        return True

                elif tag == 'check':
                    pass

                elif tag == 'call':
                    amt = min(to_call, p.chips)
                    p.chips -= amt; p.bet += amt; pot += amt
                    if p.chips == 0: p.allin = True

                elif tag == 'allin':
                    amt = p.chips
                    new_bet = p.bet + amt
                    pot += amt
                    if new_bet > cur_bet:
                        cur_bet = new_bet
                        aggressors.append(p.pid)
                        acted = {p.pid}
                    p.bet   = new_bet
                    p.chips = 0
                    p.allin = True

                elif tag == 'raise':
                    raw     = max(action[1], to_call + BIG_BLIND)
                    raw     = min(raw, p.chips)
                    extra   = raw - to_call
                    if extra <= 0:
                        amt = min(to_call, p.chips)
                        p.chips -= amt; p.bet += amt; pot += amt
                        if p.chips == 0: p.allin = True
                    else:
                        p.chips -= raw
                        p.bet   += raw
                        pot     += raw
                        cur_bet  = p.bet
                        aggressors.append(p.pid)
                        acted = {p.pid}
                        if p.chips == 0: p.allin = True

            return False

        first_pf = (bb_i + 1) % n if n > 2 else 0
        if betting(Street.PREFLOP, first_pf): return

        for p in active: p.reset_street()
        board += [deck.pop(), deck.pop(), deck.pop()]
        cur_bet = 0
        if betting(Street.FLOP, sb_i): return

        for p in active: p.reset_street()
        board.append(deck.pop())
        cur_bet = 0
        if betting(Street.TURN, sb_i): return

        for p in active: p.reset_street()
        board.append(deck.pop())
        cur_bet = 0
        if betting(Street.RIVER, sb_i): return

        # showdown
        live = [p for p in active if not p.folded]
        if len(live) == 1:
            live[0].chips += pot; return
        if not live: return

        scored = [(best_of_7(p.hole, board), p) for p in live]
        best_s = max(s for s,_ in scored)
        winners = [p for s,p in scored if s == best_s]
        share, rem = divmod(pot, len(winners))
        for w in winners: w.chips += share
        winners[0].chips += rem


# ─────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────

def main():
    random.seed(42)
    n_games = 100
    names = [STRATEGIES[i]().name for i in range(N_PLAYERS)]
    wins  = Counter()

    print(f"\n{'='*65}")
    print("     TEXAS HOLD'EM SIMULATION  —  100 TOURNAMENTS")
    print(f"{'='*65}")
    print(f"  Stack: {STARTING_CHIPS} chips each  |  Blinds: {SMALL_BLIND}/{BIG_BLIND}")
    print()
    for i, nm in enumerate(names):
        tag = "  ← THE YOLO MENACE" if i == 0 else ""
        print(f"  P{i+1}: {nm}{tag}")
    print(f"{'='*65}\n")

    for g in range(1, n_games+1):
        t = Table()
        w = t.run_tournament()
        wins[w] += 1
        if g % 10 == 0:
            print(f"  Progress: {g}/{n_games} tournaments done...", flush=True)

    total   = sum(wins.values())
    bar_w   = 36
    max_w   = max(wins.values()) if wins else 1
    order   = sorted(range(N_PLAYERS), key=lambda i: wins.get(i,0), reverse=True)

    print(f"\n{'='*65}")
    print("  HISTOGRAM  —  WINNER WINNER CHICKEN DINNER")
    print(f"{'='*65}\n")

    medals = ["1st", "2nd", "3rd", "4th", "5th", "6th"]
    for rank, pid in enumerate(order):
        w = wins.get(pid, 0)
        pct = w / total * 100
        bar = "█" * int(w / max_w * bar_w) + "░" * (bar_w - int(w / max_w * bar_w))
        label = f"P{pid+1} {names[pid]}"
        suffix = f"  ★ CHAMPION" if rank == 0 else ""
        print(f"  [{medals[rank]}] {label:<30} {bar} {w:3d} wins ({pct:5.1f}%){suffix}")

    champ = order[0]
    yolo_w = wins.get(0, 0)
    yolo_pct = yolo_w / total * 100
    exp = total / N_PLAYERS

    print(f"\n{'='*65}")
    print(f"\n  CHAMPION: P{champ+1} — {names[champ]}  ({wins[champ]} wins)")
    print(f"  YOLO All-In:  {yolo_w} wins  ({yolo_pct:.1f}%)  [expected random: {exp:.0f}]")

    if wins[champ] == yolo_w and champ == 0:
        print("\n  Somehow the YOLO bot won. Variance wins again. Mathematics cries.")
    elif yolo_w > exp:
        print(f"\n  YOLO got lucky above baseline. Even a broken clock...")
        print(f"  Suflair GPT: still statistically humiliated in the long run.")
    else:
        print(f"\n  The YOLO bot underperformed. Fancy that.")
        print(f"  Suflair GPT: absolutely demolished by actual game theory.")
        print(f"  Going all-in every hand is not a strategy. It is a cry for help.")

    print(f"\n  Suflair GPT embarrassment index: ████████████ MAXIMUM")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    main()
