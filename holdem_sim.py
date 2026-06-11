"""
Texas Hold'em Poker Tournament Simulator
6 players, 100 tournaments, histogram of winners.

Player 1: The Degenerate (always all-in)
Player 2: GTO Scholar
Player 3: Tight-Aggressive (TAG)
Player 4: Loose-Aggressive (LAG)
Player 5: Pot Odds Robot
Player 6: Adaptive Exploiter
"""

import random
import sys
from collections import Counter, defaultdict
from itertools import combinations
from enum import IntEnum

# ─────────────────────────────────────────────────────────────────────────────
# CARD PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────

RANKS = "23456789TJQKA"   # index 0-12
SUITS = "cdhs"             # index 0-3

def rank_of(c):  return c >> 2
def suit_of(c):  return c & 3
def make_deck(): return list(range(52))

# ─────────────────────────────────────────────────────────────────────────────
# HAND EVALUATOR  (best 5 from N cards)
# ─────────────────────────────────────────────────────────────────────────────

class HR(IntEnum):
    HIGH_CARD = 0; ONE_PAIR = 1; TWO_PAIR = 2; TRIPS = 3
    STRAIGHT = 4; FLUSH = 5; FULL_HOUSE = 6; QUADS = 7
    STR_FLUSH = 8; ROYAL = 9

def _score5(cards):
    ranks = sorted((rank_of(c) for c in cards), reverse=True)
    suits = [suit_of(c) for c in cards]
    flush  = len(set(suits)) == 1
    straight = (len(set(ranks)) == 5 and ranks[0] - ranks[4] == 4)
    if not straight and ranks == [12, 3, 2, 1, 0]:   # wheel
        straight, ranks = True, [3, 2, 1, 0, -1]
    rc = Counter(ranks)
    grps = sorted(rc.items(), key=lambda x: (x[1], x[0]), reverse=True)
    cnt  = [g[1] for g in grps]
    grnk = [g[0] for g in grps]
    if straight and flush:
        return (HR.ROYAL if ranks[0] == 12 else HR.STR_FLUSH, ranks)
    if cnt[0] == 4:    return (HR.QUADS,      grnk)
    if cnt[:2]==[3,2]: return (HR.FULL_HOUSE,  grnk)
    if flush:          return (HR.FLUSH,       ranks)
    if straight:       return (HR.STRAIGHT,    ranks)
    if cnt[0] == 3:    return (HR.TRIPS,       grnk)
    if cnt[:2]==[2,2]: return (HR.TWO_PAIR,    grnk)
    if cnt[0] == 2:    return (HR.ONE_PAIR,    grnk)
    return (HR.HIGH_CARD, ranks)

def best_hand(cards):
    return max(_score5(c) for c in combinations(cards, 5))

# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO EQUITY (fast, low-sim version for real-time decisions)
# ─────────────────────────────────────────────────────────────────────────────

def equity(hole, board, n_opponents, sims=120):
    dead = set(hole + board)
    deck = [c for c in range(52) if c not in dead]
    wins = ties = 0
    needed = 5 - len(board)
    for _ in range(sims):
        sample = random.sample(deck, needed + 2 * n_opponents)
        full_board = board + sample[:needed]
        my_score = best_hand(hole + full_board)
        opp_best = max(
            best_hand(sample[needed + i*2 : needed + i*2 + 2] + full_board)
            for i in range(n_opponents)
        )
        if my_score > opp_best:   wins += 1
        elif my_score == opp_best: ties += 1
    return (wins + ties * 0.5) / sims

# ─────────────────────────────────────────────────────────────────────────────
# PREFLOP HAND CATEGORY
# ─────────────────────────────────────────────────────────────────────────────

def preflop_category(hole):
    r1, r2 = rank_of(hole[0]), rank_of(hole[1])
    s1, s2 = suit_of(hole[0]), suit_of(hole[1])
    suited = (s1 == s2)
    hi, lo = max(r1, r2), min(r1, r2)
    paired = (hi == lo)
    gap    = hi - lo

    if paired and hi >= 10: return "premium"          # TT+
    if paired and hi >= 7:  return "strong"            # 77-99
    if paired:              return "playable"           # 22-66
    if hi == 12 and lo >= 11: return "premium"         # AK, AQ
    if hi == 12 and lo >= 9:  return "strong"          # AT-AJ
    if hi == 12 and suited:   return "strong"          # Ax suited
    if hi == 12:              return "marginal"        # Ax offsuit low
    if gap <= 1 and suited and hi >= 9: return "strong"   # KQ, QJ suited
    if gap <= 2 and hi >= 9: return "playable"
    if gap <= 2 and suited:  return "marginal"
    return "trash"

CAT_EQ = {"premium": 0.72, "strong": 0.60, "playable": 0.47,
           "marginal": 0.37, "trash": 0.27}

# ─────────────────────────────────────────────────────────────────────────────
# PLAYER & TABLE STATE
# ─────────────────────────────────────────────────────────────────────────────

class Player:
    __slots__ = ("pid", "chips", "strategy", "hole", "folded",
                 "allin", "bet", "invested", "history")
    def __init__(self, pid, chips, strategy):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.bet      = 0       # chips committed this street
        self.invested = 0       # chips committed this hand
        self.history  = defaultdict(int)  # for adaptive

    def reset_hand(self):
        self.hole = []; self.folded = False; self.allin = False
        self.bet  = 0;  self.invested = 0

    def reset_street(self):
        self.bet = 0


class Table:
    """Mutable snapshot passed to strategy functions."""
    __slots__ = ("players", "board", "pot", "street_bet",
                 "stage", "dealer", "bb")
    def __init__(self, players, dealer, bb):
        self.players    = players
        self.board      = []
        self.pot        = 0
        self.street_bet = 0
        self.stage      = "preflop"
        self.dealer     = dealer
        self.bb         = bb

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def s_allin(p, tbl, to_call, min_raise):
    """THE DEGENERATE: always rip it in."""
    return ("raise", p.chips)


def s_gto(p, tbl, to_call, min_raise):
    """GTO Scholar: equity + pot-odds, mixed strategies."""
    hole  = p.hole
    board = tbl.board
    n_opp = sum(1 for x in tbl.players if not x.folded and x.pid != p.pid)
    pot   = tbl.pot

    if tbl.stage == "preflop":
        cat  = preflop_category(hole)
        eq   = CAT_EQ[cat] ** max(n_opp, 1) ** 0.3
    else:
        eq = equity(hole, board, n_opp, sims=100)

    pot_odds = to_call / (pot + to_call + 1)

    if eq > 0.72:                               # monster — build pot
        bet = min(p.chips, max(min_raise, int(pot * 0.75)))
        return ("raise", bet)
    if eq > 0.55 and eq > pot_odds + 0.08:     # value bet
        bet = min(p.chips, max(min_raise, int(pot * 0.50)))
        return ("raise", bet) if bet >= min_raise else ("call", to_call)
    if eq > pot_odds + 0.03:                   # call / check
        return ("check", 0) if to_call == 0 else ("call", to_call)
    if to_call == 0:                            # free look
        return ("check", 0)
    if tbl.stage == "preflop" and random.random() < 0.12:  # 3bet bluff
        return ("raise", min(p.chips, max(min_raise, int(pot * 0.6))))
    return ("fold", 0)


def s_tag(p, tbl, to_call, min_raise):
    """Tight-Aggressive: top-20% hands only, punish limpers."""
    hole  = p.hole
    board = tbl.board
    n_opp = sum(1 for x in tbl.players if not x.folded and x.pid != p.pid)
    pot   = tbl.pot

    if tbl.stage == "preflop":
        cat = preflop_category(hole)
        if cat in ("premium",):
            return ("raise", min(p.chips, max(min_raise, tbl.bb * 4)))
        if cat == "strong":
            if to_call == 0:
                return ("raise", min(p.chips, max(min_raise, tbl.bb * 3)))
            if to_call <= tbl.bb * 4:
                return ("call", to_call)
            return ("fold", 0)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    eq = equity(hole, board, n_opp, sims=80)
    if eq > 0.60:
        bet = min(p.chips, max(min_raise, int(pot * 0.80)))
        return ("raise", bet)
    if eq > 0.40:
        return ("check", 0) if to_call == 0 else (
            ("call", to_call) if to_call <= pot * 0.30 else ("fold", 0))
    return ("check", 0) if to_call == 0 else ("fold", 0)


def s_lag(p, tbl, to_call, min_raise):
    """Loose-Aggressive: wide range, frequent bluffs, semi-bluffs."""
    hole  = p.hole
    board = tbl.board
    n_opp = sum(1 for x in tbl.players if not x.folded and x.pid != p.pid)
    pot   = tbl.pot
    rng   = random.random()

    if tbl.stage == "preflop":
        cat = preflop_category(hole)
        # Play 65% of hands; raise 40% of the time as opener
        if cat in ("premium", "strong"):
            return ("raise", min(p.chips, max(min_raise, tbl.bb * 3 + n_opp * tbl.bb)))
        if cat in ("playable", "marginal"):
            if to_call == 0:
                return ("raise", min(p.chips, min_raise)) if rng < 0.45 else ("check", 0)
            if to_call <= tbl.bb * 3:
                return ("raise", min(p.chips, to_call * 3)) if rng < 0.25 else ("call", to_call)
            return ("fold", 0)
        if cat == "trash":
            if to_call == 0:
                return ("raise", min(p.chips, min_raise)) if rng < 0.18 else ("check", 0)
            return ("fold", 0)

    eq = equity(hole, board, n_opp, sims=80)
    pot_odds = to_call / (pot + to_call + 1)

    # Semi-bluff any draw + bluff 20% spots
    if eq > 0.50 or rng < 0.22:
        bet = min(p.chips, max(min_raise, int(pot * random.uniform(0.55, 1.10))))
        if bet >= min_raise:
            return ("raise", bet)
    if eq > pot_odds:
        return ("check", 0) if to_call == 0 else ("call", to_call)
    if to_call == 0:
        return ("raise", min(p.chips, min_raise)) if rng < 0.15 else ("check", 0)
    return ("fold", 0)


def s_potodds(p, tbl, to_call, min_raise):
    """Pot Odds Robot: pure equity vs price, Kelly-ish sizing."""
    hole  = p.hole
    board = tbl.board
    n_opp = sum(1 for x in tbl.players if not x.folded and x.pid != p.pid)
    pot   = tbl.pot

    if tbl.stage == "preflop":
        cat = preflop_category(hole)
        eq  = CAT_EQ[cat]
        # adjust crude for multi-way
        eq  = eq / (n_opp ** 0.25) if n_opp > 1 else eq
    else:
        eq = equity(hole, board, n_opp, sims=110)

    pot_odds = to_call / (pot + to_call + 1)
    edge     = eq - pot_odds

    if edge > 0.25:                          # strong positive EV → overbet
        frac = min(edge * 1.8, 1.0)
        bet  = min(p.chips, max(min_raise, int(pot * frac)))
        return ("raise", bet)
    if edge > 0.08:                          # decent edge → value bet half-pot
        bet = min(p.chips, max(min_raise, int(pot * 0.50)))
        return ("raise", bet) if bet >= min_raise else (
            "check" if to_call == 0 else "call", to_call)
    if eq > pot_odds:                        # thin call
        return ("check", 0) if to_call == 0 else ("call", to_call)
    return ("check", 0) if to_call == 0 else ("fold", 0)


def s_adaptive(p, tbl, to_call, min_raise):
    """
    Adaptive Exploiter:
    - Tracks aggression & VPIP of each opponent
    - Adjusts ranges vs fish (loose calling stations) vs nits
    - Short-stack push/fold with ICM-aware thresholds
    - Position-aware with late-position steals
    """
    hole  = p.hole
    board = tbl.board
    n_opp = sum(1 for x in tbl.players if not x.folded and x.pid != p.pid)
    pot   = tbl.pot
    rng   = random.random()

    alive  = [x for x in tbl.players if x.chips > 0]
    avg_stk = sum(x.chips for x in alive) / max(len(alive), 1)
    my_bb   = p.chips / tbl.bb if tbl.bb else 50

    # ── Short-stack push/fold (< 15 BB) ──────────────────────────────────────
    if my_bb < 15:
        cat = preflop_category(hole) if tbl.stage == "preflop" else None
        if tbl.stage == "preflop":
            if cat in ("premium", "strong", "playable"):
                return ("raise", p.chips)
            return ("check", 0) if to_call == 0 else ("fold", 0)
        eq = equity(hole, board, n_opp, sims=60)
        if eq > 0.45:
            return ("raise", p.chips) if p.chips >= min_raise else ("call", to_call)
        return ("check", 0) if to_call == 0 else ("fold", 0)

    # ── Exploit read: count how loose/aggressive each opponent is ─────────────
    # (history["vpip"] / history["hands"] → VPIP, history["raises"] / history["calls"])
    opp_vpips = []
    for x in tbl.players:
        if x.pid != p.pid and not x.folded:
            hands = max(x.history["hands"], 1)
            opp_vpips.append(x.history["vpip"] / hands)
    avg_vpip  = sum(opp_vpips) / max(len(opp_vpips), 1)
    table_loose = avg_vpip > 0.45   # majority calling station / fish
    table_tight = avg_vpip < 0.22   # nit-heavy table

    # ── Position (late = dealer-1, dealer, or BB with checks) ─────────────────
    n_pl = len(tbl.players)
    pos  = (p.pid - tbl.dealer) % n_pl
    late_pos = pos in (n_pl - 1, n_pl - 2, 0)

    # ── Preflop ───────────────────────────────────────────────────────────────
    if tbl.stage == "preflop":
        cat = preflop_category(hole)
        # vs fish: tighten up (they call too wide, bluffs don't work)
        if table_loose:
            if cat in ("premium", "strong"):
                return ("raise", min(p.chips, max(min_raise, tbl.bb * (5 + n_opp))))
            if cat == "playable" and to_call <= tbl.bb * 2:
                return ("call", to_call)
            return ("check", 0) if to_call == 0 else ("fold", 0)
        # vs nits: steal blind often from late pos
        if table_tight and late_pos and to_call == 0:
            return ("raise", min(p.chips, max(min_raise, tbl.bb * 2)))
        if cat in ("premium", "strong"):
            return ("raise", min(p.chips, max(min_raise, tbl.bb * 3)))
        if cat == "playable":
            if to_call == 0:
                return ("raise", min(p.chips, min_raise)) if late_pos and rng < 0.35 else ("check", 0)
            if to_call <= tbl.bb * 3:
                return ("call", to_call)
            return ("fold", 0)
        if to_call == 0:
            return ("raise", min(p.chips, min_raise)) if late_pos and rng < 0.20 else ("check", 0)
        return ("fold", 0)

    # ── Postflop ──────────────────────────────────────────────────────────────
    eq = equity(hole, board, n_opp, sims=90)
    pot_odds = to_call / (pot + to_call + 1)

    # Exploit fish: bet value mercilessly, cut bluffs
    if table_loose:
        if eq > 0.55:
            bet = min(p.chips, max(min_raise, int(pot * 0.85)))
            return ("raise", bet)
        if eq > pot_odds:
            return ("check", 0) if to_call == 0 else ("call", to_call)
        return ("check", 0) if to_call == 0 else ("fold", 0)

    # Exploit nits: bluff them off hands, cbet aggressively
    if table_tight:
        if to_call == 0:
            bet = min(p.chips, max(min_raise, int(pot * 0.65)))
            return ("raise", bet) if (eq > 0.35 or rng < 0.30) else ("check", 0)
        if eq > 0.50:
            bet = min(p.chips, max(min_raise, int(pot * 0.70)))
            return ("raise", bet) if bet >= min_raise else ("call", to_call)
        if eq > pot_odds:
            return ("call", to_call)
        return ("fold", 0)

    # Balanced default
    if eq > 0.65:
        bet = min(p.chips, max(min_raise, int(pot * 0.70)))
        return ("raise", bet)
    if eq > 0.45:
        return ("check", 0) if to_call == 0 else (
            ("call", to_call) if to_call <= pot * 0.35 else ("fold", 0))
    if to_call == 0:
        return ("raise", min(p.chips, min_raise)) if late_pos and rng < 0.25 else ("check", 0)
    return ("fold", 0)


STRATEGIES = [s_allin, s_gto, s_tag, s_lag, s_potodds, s_adaptive]

NAMES = [
    "P1 ALL-IN MANIAC",
    "P2 GTO Scholar",
    "P3 Tight-Aggressive",
    "P4 Loose-Aggressive",
    "P5 Pot Odds Robot",
    "P6 Adaptive Exploiter",
]

COLORS = ["#E74C3C", "#3498DB", "#2ECC71", "#F39C12", "#9B59B6", "#E91E63"]

# ─────────────────────────────────────────────────────────────────────────────
# BETTING ROUND ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def betting_round(tbl, start_idx, skip_first_check=False):
    """
    Process one betting street.
    skip_first_check: preflop the BB already posted so last to close is BB.
    Returns True if hand continues, False if everyone folded to one player.
    """
    players = tbl.players
    n       = len(players)

    for p in players:
        p.bet = 0 if not skip_first_check else p.bet  # keep blinds on preflop

    # Ordered list starting at start_idx, skipping folded/allin
    def live():
        return [p for p in players if not p.folded and not p.allin]

    if len(live()) <= 1:
        return True

    order    = [(start_idx + i) % n for i in range(n)]
    acted    = set()
    last_raiser_pid = None
    i        = 0
    laps     = 0
    max_laps = n * 6  # safety

    while laps < max_laps:
        idx = order[i % len(order)]
        p   = players[idx]
        i  += 1
        laps += 1

        if p.folded or p.allin:
            continue

        to_call  = max(0, tbl.street_bet - p.bet)
        to_call  = min(to_call, p.chips)
        min_raise = max(tbl.bb, tbl.street_bet * 2 - p.bet)
        min_raise = min(min_raise, p.chips)

        action, amount = p.strategy(p, tbl, to_call, min_raise)

        # ── normalise action ─────────────────────────────────────────────────
        if action == "fold":
            p.folded = True
        elif action in ("check",):
            pass
        elif action == "call":
            amt = min(to_call, p.chips)
            p.chips    -= amt
            p.bet      += amt
            p.invested += amt
            tbl.pot    += amt
            if p.chips == 0:
                p.allin = True
        elif action == "raise":
            amount = max(int(amount), min_raise)
            amount = min(amount, p.chips)
            p.chips    -= amount
            p.bet      += amount
            p.invested += amount
            tbl.pot    += amount
            if p.bet > tbl.street_bet:
                tbl.street_bet  = p.bet
                last_raiser_pid = p.pid
            if p.chips == 0:
                p.allin = True

        acted.add(p.pid)

        # ── check if street is over ──────────────────────────────────────────
        remaining = [x for x in players if not x.folded]
        if len(remaining) == 1:
            return True

        need_act = [x for x in remaining if not x.allin
                    and (x.pid not in acted or x.bet < tbl.street_bet)]
        if not need_act:
            break

    return True


# ─────────────────────────────────────────────────────────────────────────────
# HAND DRIVER
# ─────────────────────────────────────────────────────────────────────────────

SB_BB = (10, 20)   # fixed blinds; tournament raises would complicate sims

def play_hand(players: list[Player], dealer_idx: int):
    """Play one hand, mutate player chips in place."""
    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return

    for p in alive:
        p.reset_hand()

    n   = len(alive)
    tbl = Table(alive, dealer_idx % n, SB_BB[1])

    # Deal
    deck = make_deck(); random.shuffle(deck)
    d = 0
    for p in alive:
        p.hole = [deck[d], deck[d+1]]; d += 2

    # Post blinds
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n
    sb_p   = alive[sb_idx]
    bb_p   = alive[bb_idx]

    def post(player, amount):
        amt = min(amount, player.chips)
        player.chips    -= amt
        player.bet       = amt
        player.invested  = amt
        tbl.pot         += amt
        if player.chips == 0: player.allin = True

    post(sb_p, SB_BB[0])
    post(bb_p, SB_BB[1])
    tbl.street_bet = SB_BB[1]

    # ── PREFLOP ──────────────────────────────────────────────────────────────
    tbl.stage = "preflop"
    utg = (dealer_idx + 3) % n
    betting_round(tbl, utg, skip_first_check=True)

    remaining = [p for p in alive if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += tbl.pot
        _record_vpip(alive)
        return

    # ── FLOP ─────────────────────────────────────────────────────────────────
    tbl.board   = [deck[d], deck[d+1], deck[d+2]]; d += 3
    tbl.stage   = "flop"
    tbl.street_bet = 0
    for p in alive: p.bet = 0
    betting_round(tbl, (dealer_idx + 1) % n)

    remaining = [p for p in alive if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += tbl.pot
        _record_vpip(alive)
        return

    # ── TURN ─────────────────────────────────────────────────────────────────
    tbl.board.append(deck[d]); d += 1
    tbl.stage = "turn"
    tbl.street_bet = 0
    for p in alive: p.bet = 0
    betting_round(tbl, (dealer_idx + 1) % n)

    remaining = [p for p in alive if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += tbl.pot
        _record_vpip(alive)
        return

    # ── RIVER ────────────────────────────────────────────────────────────────
    tbl.board.append(deck[d])
    tbl.stage = "river"
    tbl.street_bet = 0
    for p in alive: p.bet = 0
    betting_round(tbl, (dealer_idx + 1) % n)

    remaining = [p for p in alive if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += tbl.pot
        _record_vpip(alive)
        return

    # ── SHOWDOWN ─────────────────────────────────────────────────────────────
    _showdown(remaining, tbl)
    _record_vpip(alive)


def _record_vpip(players):
    for p in players:
        p.history["hands"] += 1
        if p.invested > SB_BB[1]:   # put in more than the BB → VPIP
            p.history["vpip"] += 1
        if p.invested > SB_BB[1] * 2:
            p.history["raises"] += 1


def _showdown(remaining, tbl):
    """
    Distribute pots.  We do a simplified side-pot calc:
    sort by invested, peel layers.
    """
    invested = sorted(set(p.invested for p in remaining))
    prev = 0
    for lvl in invested:
        share = lvl - prev
        eligible = [p for p in remaining if p.invested >= lvl]
        this_pot = share * len(eligible)  # chips contributed at this level
        # add from folded players pro-rata  (very rough)
        if eligible:
            scores = [(best_hand(p.hole + tbl.board), p) for p in eligible]
            top_score = max(s for s, _ in scores)
            winners = [p for s, p in scores if s == top_score]
            split = this_pot // len(winners)
            rem   = this_pot % len(winners)
            for w in winners:
                w.chips += split
            if rem: winners[0].chips += rem
        prev = lvl

    # folded players' residual (left in tbl.pot not accounted) → best hand
    residual = tbl.pot - sum(p.invested for p in remaining)
    if residual > 0:
        scores = [(best_hand(p.hole + tbl.board), p) for p in remaining]
        top = max(s for s, _ in scores)
        winners = [p for s, p in scores if s == top]
        split = residual // len(winners)
        for w in winners:
            w.chips += split


# ─────────────────────────────────────────────────────────────────────────────
# TOURNAMENT
# ─────────────────────────────────────────────────────────────────────────────

def run_tournament(starting_chips=10_000, max_hands=3000):
    players = [Player(i, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer  = 0

    for _ in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        play_hand(alive, dealer % len(alive))
        dealer += 1
        # clamp negatives (shouldn't happen but just in case)
        for p in players:
            if p.chips < 0: p.chips = 0

    alive = [p for p in players if p.chips > 0]
    if not alive:
        return random.randint(0, 5)
    return max(alive, key=lambda p: p.chips).pid


# ─────────────────────────────────────────────────────────────────────────────
# MAIN: 100 SIMS
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    N_SIMS = 100
    print(f"\n{'='*60}")
    print(f"  Texas Hold'em – {N_SIMS} Tournament Simulations")
    print(f"  6 players · 10,000 chips each · blinds {SB_BB[0]}/{SB_BB[1]}")
    print(f"{'='*60}\n")

    wins = Counter()
    for sim in range(N_SIMS):
        if (sim + 1) % 10 == 0:
            sys.stdout.write(f"\r  Simulating... {sim+1}/{N_SIMS}")
            sys.stdout.flush()
        winner = run_tournament()
        wins[winner] += 1

    print(f"\r  Done!{' '*30}\n")

    # ── Text results table ───────────────────────────────────────────────────
    print(f"{'─'*44}")
    print(f"  {'Strategy':<25}  {'Wins':>5}  {'%':>5}")
    print(f"{'─'*44}")
    for i in range(6):
        w = wins[i]
        bar = "█" * w + "░" * (N_SIMS - w)
        print(f"  {NAMES[i]:<25}  {w:>5}  {w:>4.0f}%")
    print(f"{'─'*44}")
    winner_idx = max(range(6), key=lambda i: wins[i])
    print(f"\n  🏆 CHAMPION: {NAMES[winner_idx]}  ({wins[winner_idx]} wins)\n")

    # ── Matplotlib histogram ─────────────────────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        fig, ax = plt.subplots(figsize=(13, 7))
        fig.patch.set_facecolor("#1A1A2E")
        ax.set_facecolor("#16213E")

        x    = np.arange(6)
        vals = [wins[i] for i in range(6)]
        bars = ax.bar(x, vals, color=COLORS, edgecolor="white",
                      linewidth=1.4, width=0.65, zorder=3)

        # Gold crown on winner
        bars[winner_idx].set_edgecolor("gold")
        bars[winner_idx].set_linewidth(3.5)

        # Value labels
        for bar, v in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 0.5,
                    f"{v}", ha="center", va="bottom",
                    fontsize=14, fontweight="bold", color="white")

        # Random baseline
        ax.axhline(N_SIMS / 6, color="#AAAAAA", linestyle="--",
                   linewidth=1.4, alpha=0.7, zorder=2,
                   label=f"Random baseline ({N_SIMS/6:.1f})")

        ax.set_xticks(x)
        ax.set_xticklabels(NAMES, rotation=20, ha="right",
                           fontsize=11, color="white")
        ax.tick_params(axis="y", colors="white")
        ax.set_ylabel("Tournament Wins  (out of 100)",
                      fontsize=13, color="white")
        ax.set_title(
            "Texas Hold'em — 100 Tournament Simulations\n"
            "Winner Winner Chicken Dinner 🐔",
            fontsize=17, fontweight="bold", color="white", pad=15)
        ax.set_ylim(0, max(vals) + 8)
        ax.grid(axis="y", alpha=0.25, linestyle=":", color="#AAAAAA", zorder=1)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color("#AAAAAA")

        legend = ax.legend(facecolor="#1A1A2E", edgecolor="#AAAAAA",
                           labelcolor="white", fontsize=11)

        plt.tight_layout()
        out = "poker_results.png"
        plt.savefig(out, dpi=160, bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        print(f"  Histogram saved → {out}\n")

    except ImportError:
        print("  (matplotlib not available — skipping chart)\n")
