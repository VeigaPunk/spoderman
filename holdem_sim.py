#!/usr/bin/env python3
"""
Texas Hold'em Poker Tournament Simulator
Player 1: The Maniac (All-In Every Turn)
Players 2-6: Five elaborate algorithmic strategies
100 tournament simulations → ASCII histogram of winners
"""

import random
import itertools
from collections import Counter, defaultdict
from typing import List, Optional, Tuple
import sys

# ─────────────────────────────────────────────
# CARDS & DECK
# ─────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

class Card:
    __slots__ = ("rank", "suit", "val")
    def __init__(self, rank: str, suit: str):
        self.rank = rank
        self.suit = suit
        self.val = RANK_VAL[rank]
    def __repr__(self):
        return f"{self.rank}{self.suit}"
    def __eq__(self, other):
        return self.val == other.val and self.suit == other.suit
    def __hash__(self):
        return hash((self.rank, self.suit))

FULL_DECK = [Card(r, s) for r in RANKS for s in SUITS]

def fresh_deck() -> List[Card]:
    d = FULL_DECK[:]
    random.shuffle(d)
    return d

# ─────────────────────────────────────────────
# HAND EVALUATOR  (7-card → best 5-card score)
# Returns tuple: higher is better
# ─────────────────────────────────────────────

def _rank_five(cards: List[Card]) -> Tuple:
    """Score a exactly 5-card hand. Returns comparable tuple."""
    vals = sorted([c.val for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    flush = len(set(suits)) == 1
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    # Ace-low straight: A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        straight = True
        vals = [5, 4, 3, 2, 1]
    counts = Counter(vals)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda v: (counts[v], v), reverse=True)

    if flush and straight:
        return (8, vals[0])
    if freq == [4, 1]:
        return (7, groups[0], groups[1])
    if freq == [3, 2]:
        return (6, groups[0], groups[1])
    if flush:
        return (5, *vals)
    if straight:
        return (4, vals[0])
    if freq[0] == 3:
        return (3, groups[0], *groups[1:])
    if freq[:2] == [2, 2]:
        pair1, pair2 = sorted([groups[0], groups[1]], reverse=True)
        return (2, pair1, pair2, groups[2])
    if freq[0] == 2:
        return (1, groups[0], *groups[1:])
    return (0, *vals)

def best_hand(hole: List[Card], community: List[Card]) -> Tuple:
    cards = hole + community
    return max(_rank_five(list(combo)) for combo in itertools.combinations(cards, 5))

def hand_name(score: Tuple) -> str:
    names = ["High Card","One Pair","Two Pair","Three of a Kind",
             "Straight","Flush","Full House","Four of a Kind","Straight Flush"]
    return names[score[0]]

# ─────────────────────────────────────────────
# HAND STRENGTH ESTIMATOR  (Monte Carlo equity)
# ─────────────────────────────────────────────

def estimate_equity(hole: List[Card], community: List[Card],
                    n_opponents: int, samples: int = 150) -> float:
    """Rough win equity via Monte Carlo."""
    known = set(map(id, hole + community))
    remaining = [c for c in FULL_DECK if id(c) not in known]
    wins = 0
    for _ in range(samples):
        deck = remaining[:]
        random.shuffle(deck)
        idx = 0
        board = community[:]
        needed = 5 - len(board)
        board_extra = deck[idx:idx+needed]; idx += needed
        full_board = board + board_extra
        my_score = best_hand(hole, full_board)
        beat = True
        for _ in range(n_opponents):
            opp_hole = deck[idx:idx+2]; idx += 2
            if idx > len(deck):
                break
            opp_score = best_hand(opp_hole, full_board)
            if opp_score >= my_score:
                beat = False
                break
        if beat:
            wins += 1
    return wins / samples

# ─────────────────────────────────────────────
# STARTING HAND RANK  (simplified Chen formula)
# ─────────────────────────────────────────────

def starting_hand_score(hole: List[Card]) -> float:
    """0-1 score of preflop hand strength."""
    a, b = sorted(hole, key=lambda c: c.val, reverse=True)
    score = RANK_VAL[a.rank]
    if a.val == b.val:             # pair
        score = max(score * 2, 5)
    if a.suit == b.suit:           # suited
        score += 2
    gap = a.val - b.val
    if gap == 0:
        score += 0
    elif gap == 1:
        score -= 1
    elif gap == 2:
        score -= 2
    elif gap == 3:
        score -= 4
    else:
        score -= 5
    if gap <= 1 and a.val < 12:    # connector bonus
        score += 1
    return max(0, min(score, 20)) / 20.0

# ─────────────────────────────────────────────
# GAME STATE  passed to strategy functions
# ─────────────────────────────────────────────

class GameState:
    __slots__ = (
        "hole", "community", "pot", "to_call", "min_raise",
        "my_stack", "active_stacks", "street", "position",
        "n_active", "already_bet", "aggressor_raised_this_street",
        "player_id", "bet_history"
    )
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

# ─────────────────────────────────────────────
# ══════════════════════════════════════════════
#  S T R A T E G I E S
# ══════════════════════════════════════════════
# Each returns (action, amount) where action in
# {"fold", "call", "raise", "all_in", "check"}
# ─────────────────────────────────────────────

# ─── STRATEGY 0: THE MANIAC (Player 1) ────────
def strategy_all_in(gs: GameState):
    """If my_turn then bet = ALL_IN fi"""
    return ("all_in", gs.my_stack)

# ─── STRATEGY 1: TIGHT-AGGRESSIVE (TAG) ───────
def strategy_tag(gs: GameState):
    """
    Only enters pots with top ~18% starting hands.
    Once in, bets/raises aggressively on strong equity.
    Folds quickly when board texture turns bad.
    """
    hole, comm = gs.hole, gs.community

    if gs.street == "preflop":
        strength = starting_hand_score(hole)
        if gs.to_call == 0:
            if strength >= 0.55:
                raise_amt = min(gs.pot * 3 + gs.already_bet, gs.my_stack)
                return ("raise", max(raise_amt, gs.min_raise))
            return ("check", 0)
        else:
            if strength >= 0.72:
                raise_amt = min(gs.to_call * 3, gs.my_stack)
                return ("raise", max(raise_amt, gs.min_raise))
            elif strength >= 0.55 and gs.to_call <= gs.pot * 0.25:
                return ("call", gs.to_call)
            else:
                return ("fold", 0)

    # Postflop: use equity
    if len(comm) >= 3:
        eq = estimate_equity(hole, comm, max(gs.n_active - 1, 1), samples=120)
        pot_odds = gs.to_call / (gs.pot + gs.to_call) if gs.to_call > 0 else 0

        if gs.to_call == 0:
            if eq >= 0.65:
                bet = min(int(gs.pot * 0.75), gs.my_stack)
                return ("raise", max(bet, gs.min_raise))
            elif eq >= 0.40:
                bet = min(int(gs.pot * 0.40), gs.my_stack)
                return ("raise", max(bet, gs.min_raise))
            return ("check", 0)
        else:
            if eq >= 0.70:
                reraise = min(gs.to_call * 2 + gs.pot // 2, gs.my_stack)
                return ("raise", max(reraise, gs.min_raise))
            elif eq > pot_odds + 0.10:
                return ("call", gs.to_call)
            else:
                return ("fold", 0)

    return ("call", gs.to_call) if gs.to_call <= gs.pot * 0.15 else ("fold", 0)


# ─── STRATEGY 2: POT-ODDS MATHEMATICIAN ───────
def strategy_pot_odds(gs: GameState):
    """
    Every decision is driven by pot odds vs estimated equity.
    Will call any bet where equity > pot_odds + small edge.
    Bets/raises when equity implies positive expected value.
    Accounts for implied odds on drawing hands.
    """
    hole, comm = gs.hole, gs.community

    if gs.street == "preflop":
        strength = starting_hand_score(hole)
        n_opp = max(gs.n_active - 1, 1)
        implied_eq = strength * 0.85 + 0.10  # rough preflop equity proxy
        if gs.to_call == 0:
            if implied_eq > 0.50:
                bet = min(int(gs.pot * 2.5 + 1), gs.my_stack)
                return ("raise", max(bet, gs.min_raise))
            return ("check", 0)
        pot_odds = gs.to_call / (gs.pot + gs.to_call)
        if implied_eq > pot_odds + 0.05:
            if implied_eq > pot_odds + 0.25:
                reraise = min(gs.to_call * 3, gs.my_stack)
                return ("raise", max(reraise, gs.min_raise))
            return ("call", gs.to_call)
        return ("fold", 0)

    eq = estimate_equity(hole, comm, max(gs.n_active - 1, 1), samples=150)
    pot_odds = gs.to_call / (gs.pot + gs.to_call + 1e-9)

    # Implied odds: drawing hands get a 8% boost
    draw_boost = 0.0
    if gs.street in ("flop", "turn"):
        vals = sorted([c.val for c in hole + comm], reverse=True)
        vcounts = Counter(v for c in hole + comm for v in [c.val])
        if any(v == 2 for v in vcounts.values()):  # has a pair already on board/hole
            pass
        suited_count = max(Counter(c.suit for c in hole + comm).values())
        if suited_count >= 4:
            draw_boost = 0.08
        gaps = sorted(set(vals))
        if len(gaps) >= 4 and gaps[-1] - gaps[0] <= 5:
            draw_boost = max(draw_boost, 0.07)

    adjusted_eq = eq + draw_boost

    if gs.to_call == 0:
        if adjusted_eq >= 0.60:
            bet = min(int(gs.pot * 0.65), gs.my_stack)
            return ("raise", max(bet, gs.min_raise))
        elif adjusted_eq >= 0.45:
            bet = min(int(gs.pot * 0.35), gs.my_stack)
            return ("raise", max(bet, gs.min_raise))
        return ("check", 0)

    edge = adjusted_eq - pot_odds
    if edge >= 0.20:
        reraise = min(int(gs.to_call * 2.5), gs.my_stack)
        return ("raise", max(reraise, gs.min_raise))
    elif edge >= 0.05:
        return ("call", gs.to_call)
    elif edge >= -0.02 and gs.street == "river":  # bluff catch on river
        return ("call", gs.to_call)
    return ("fold", 0)


# ─── STRATEGY 3: POSITION-AWARE GRINDER ───────
def strategy_position(gs: GameState):
    """
    Positional awareness is king.
    Early position (0-1): play only premium hands.
    Middle position (2-3): play solid hands + speculative suited connectors.
    Late position / button (4-5): steal blinds, play wide, exploit fold equity.
    Checks/raises based on how many players left to act.
    """
    hole, comm = gs.hole, gs.community
    pos = gs.position          # 0 = UTG, n_active-1 = BTN/last
    n = gs.n_active
    pos_ratio = pos / max(n - 1, 1)   # 0.0 = early, 1.0 = late

    if gs.street == "preflop":
        strength = starting_hand_score(hole)
        # threshold decreases as position improves
        threshold = 0.75 - pos_ratio * 0.30
        steal_threshold = 0.35 if pos_ratio >= 0.80 else 0.99

        if gs.to_call == 0:
            if strength >= threshold:
                raise_size = min(int(gs.pot * (2.5 + pos_ratio)), gs.my_stack)
                return ("raise", max(raise_size, gs.min_raise))
            elif strength >= steal_threshold and n <= 3:
                raise_size = min(int(gs.pot * 2.0), gs.my_stack)
                return ("raise", max(raise_size, gs.min_raise))
            return ("check", 0)
        else:
            call_threshold = threshold - 0.08
            if strength >= call_threshold + 0.15:
                reraise = min(gs.to_call * 3, gs.my_stack)
                return ("raise", max(reraise, gs.min_raise))
            elif strength >= call_threshold and gs.to_call <= gs.pot * 0.35:
                return ("call", gs.to_call)
            elif pos_ratio >= 0.85 and gs.to_call <= gs.pot * 0.15:
                return ("call", gs.to_call)   # positional float
            return ("fold", 0)

    # Postflop: position still matters
    eq = estimate_equity(hole, comm, max(n - 1, 1), samples=120)
    pot_odds = gs.to_call / (gs.pot + gs.to_call + 1e-9)
    # In position: bluff/bet more; out of position: play tighter
    eq_bonus = 0.05 * pos_ratio
    effective_eq = eq + eq_bonus

    if gs.to_call == 0:
        if effective_eq >= 0.55:
            bet = min(int(gs.pot * (0.50 + pos_ratio * 0.30)), gs.my_stack)
            return ("raise", max(bet, gs.min_raise))
        elif pos_ratio >= 0.75 and gs.street != "river":  # positional bet
            bet = min(int(gs.pot * 0.30), gs.my_stack)
            return ("raise", max(bet, gs.min_raise))
        return ("check", 0)
    else:
        if effective_eq >= pot_odds + 0.18 and gs.my_stack > gs.to_call:
            reraise = min(int(gs.to_call * 2.2), gs.my_stack)
            return ("raise", max(reraise, gs.min_raise))
        elif effective_eq > pot_odds + 0.03:
            return ("call", gs.to_call)
        elif pos_ratio >= 0.80 and gs.to_call <= gs.pot * 0.20:
            return ("call", gs.to_call)   # positional float
        return ("fold", 0)


# ─── STRATEGY 4: BLUFF MASTER ─────────────────
def strategy_bluff_master(gs: GameState):
    """
    Uses a balanced bluffing strategy.
    Identifies "scary board" textures (paired boards, flush/straight completing cards)
    and fires multi-street bluffs when opponents show weakness (check-back patterns).
    Has a calculated aggression frequency with randomized semi-bluffs.
    Maintains a 1:1 value-to-bluff ratio on later streets.
    """
    hole, comm = gs.hole, gs.community
    rng = random.random()

    if gs.street == "preflop":
        strength = starting_hand_score(hole)
        # Widen range, balance with bluff-raises
        if gs.to_call == 0:
            if strength >= 0.60:
                raise_size = min(int(gs.pot * 3), gs.my_stack)
                return ("raise", max(raise_size, gs.min_raise))
            elif strength >= 0.30 and rng < 0.25:  # light 3-bet / steal
                raise_size = min(int(gs.pot * 2.5), gs.my_stack)
                return ("raise", max(raise_size, gs.min_raise))
            return ("check", 0)
        else:
            if strength >= 0.70:
                reraise = min(gs.to_call * 3, gs.my_stack)
                return ("raise", max(reraise, gs.min_raise))
            elif strength >= 0.45:
                return ("call", gs.to_call)
            elif rng < 0.15 and gs.to_call <= gs.pot * 0.20:  # bluff-call
                return ("call", gs.to_call)
            return ("fold", 0)

    eq = estimate_equity(hole, comm, max(gs.n_active - 1, 1), samples=100)
    pot_odds = gs.to_call / (gs.pot + gs.to_call + 1e-9)

    # Board texture analysis
    def board_is_scary():
        if len(comm) < 3: return False
        suit_counts = Counter(c.suit for c in comm)
        if max(suit_counts.values()) >= 3: return True   # flush draw on board
        cvals = sorted(set(c.val for c in comm))
        for i in range(len(cvals)-1):
            if cvals[i+1] - cvals[i] == 1: return True  # connected board
        val_counts = Counter(c.val for c in comm)
        if max(val_counts.values()) >= 2: return True    # paired board
        return False

    scary = board_is_scary()
    bluff_freq = 0.35 if scary else 0.18
    street_mult = {"flop": 1.0, "turn": 0.80, "river": 0.55}.get(gs.street, 1.0)
    bluff_freq *= street_mult

    # Check if aggressor has raised this street (show of strength)
    facing_raise = gs.aggressor_raised_this_street and gs.to_call > 0

    if gs.to_call == 0:
        if eq >= 0.58:
            bet_size = min(int(gs.pot * 0.70), gs.my_stack)
            return ("raise", max(bet_size, gs.min_raise))
        elif rng < bluff_freq and not facing_raise:
            # Semi-bluff or pure bluff
            bluff_size = min(int(gs.pot * 0.55), gs.my_stack)
            return ("raise", max(bluff_size, gs.min_raise))
        return ("check", 0)
    else:
        if eq >= 0.65:
            reraise = min(int(gs.to_call * 2.5), gs.my_stack)
            return ("raise", max(reraise, gs.min_raise))
        elif eq > pot_odds + 0.08:
            return ("call", gs.to_call)
        elif rng < bluff_freq * 0.5 and gs.to_call <= gs.pot * 0.30:
            return ("call", gs.to_call)   # bluff catch
        return ("fold", 0)


# ─── STRATEGY 5: GTO APPROXIMATOR ─────────────
def strategy_gto(gs: GameState):
    """
    Approximates Game Theory Optimal mixed strategies.
    Uses frequency-based decisions derived from hand equity buckets:
      - Bucket A (top 15%): always raise/bet
      - Bucket B (15-35%): mixed raise/call based on freq tables
      - Bucket C (35-55%): mixed call/fold, bet occasionally
      - Bucket D (<35%): mostly fold, rare bluff raises
    Randomization prevents exploitation by pattern-recognizing opponents.
    Stack-to-pot ratio (SPR) adjusts commitment thresholds.
    """
    hole, comm = gs.hole, gs.community
    rng = random.random()

    spr = gs.my_stack / (gs.pot + 1e-9)  # stack-to-pot ratio
    shallow = spr < 3.0
    deep = spr > 10.0

    if gs.street == "preflop":
        strength = starting_hand_score(hole)
        # GTO bucket frequencies
        if strength >= 0.78:       # Bucket A: AA,KK,QQ,AKs,AKo etc
            if gs.to_call == 0:
                raise_amt = min(int(gs.pot * 3.5), gs.my_stack)
                return ("raise", max(raise_amt, gs.min_raise))
            else:
                reraise = min(gs.to_call * 3, gs.my_stack)
                return ("raise", max(reraise, gs.min_raise))
        elif strength >= 0.58:     # Bucket B: JJ,TT,AQs,KQs etc
            if gs.to_call == 0:
                if rng < 0.75:     # raise 75%
                    raise_amt = min(int(gs.pot * 2.5), gs.my_stack)
                    return ("raise", max(raise_amt, gs.min_raise))
                return ("check", 0)
            else:
                if rng < 0.55:
                    reraise = min(gs.to_call * 2, gs.my_stack)
                    return ("raise", max(reraise, gs.min_raise))
                elif rng < 0.85:
                    return ("call", gs.to_call)
                return ("fold", 0)
        elif strength >= 0.38:     # Bucket C: 77-99, suited broadways
            if gs.to_call == 0:
                if rng < 0.40:
                    raise_amt = min(int(gs.pot * 2.0), gs.my_stack)
                    return ("raise", max(raise_amt, gs.min_raise))
                return ("check", 0)
            else:
                pot_odds = gs.to_call / (gs.pot + gs.to_call)
                if rng < 0.45 and pot_odds < 0.25:
                    return ("call", gs.to_call)
                return ("fold", 0)
        else:                      # Bucket D: trash — bluff at low freq
            if gs.to_call == 0:
                if rng < 0.12:     # steal/bluff raise
                    raise_amt = min(int(gs.pot * 2.2), gs.my_stack)
                    return ("raise", max(raise_amt, gs.min_raise))
                return ("check", 0)
            return ("fold", 0)

    # Postflop GTO:
    eq = estimate_equity(hole, comm, max(gs.n_active - 1, 1), samples=130)
    pot_odds = gs.to_call / (gs.pot + gs.to_call + 1e-9)

    # SPR adjustments: with shallow stack, commit more aggressively
    commit_threshold = 0.55 if shallow else (0.65 if not deep else 0.70)
    bluff_threshold  = 0.25 if not deep else 0.15

    if eq >= commit_threshold:         # Strong hand: always bet/raise
        if gs.to_call == 0:
            bet = min(int(gs.pot * (0.80 if shallow else 0.65)), gs.my_stack)
            return ("raise", max(bet, gs.min_raise))
        else:
            reraise = min(int(gs.to_call * 2.5), gs.my_stack)
            return ("raise", max(reraise, gs.min_raise))

    elif eq >= 0.45:                   # Medium hand: mixed
        if gs.to_call == 0:
            freq = 0.60 if eq >= 0.52 else 0.35
            if rng < freq:
                bet = min(int(gs.pot * 0.45), gs.my_stack)
                return ("raise", max(bet, gs.min_raise))
            return ("check", 0)
        else:
            if eq > pot_odds + 0.05:
                if rng < 0.70:
                    return ("call", gs.to_call)
            return ("fold", 0)

    elif eq >= bluff_threshold:        # Weak hand: mostly fold, rare bluff
        if gs.to_call == 0:
            if rng < 0.20:             # balanced bluff frequency
                bluff = min(int(gs.pot * 0.55), gs.my_stack)
                return ("raise", max(bluff, gs.min_raise))
            return ("check", 0)
        else:
            if rng < 0.08 and gs.to_call <= gs.pot * 0.25:
                return ("call", gs.to_call)   # bluff-catch
            return ("fold", 0)

    else:                              # Garbage: fold
        return ("fold", 0) if gs.to_call > 0 else ("check", 0)


# ─────────────────────────────────────────────
# STRATEGY REGISTRY
# ─────────────────────────────────────────────

STRATEGIES = [
    ("The Maniac",               strategy_all_in),
    ("TAG (Tight-Aggressive)",   strategy_tag),
    ("Pot-Odds Mathematician",   strategy_pot_odds),
    ("Position-Aware Grinder",   strategy_position),
    ("Bluff Master",             strategy_bluff_master),
    ("GTO Approximator",         strategy_gto),
]

STRATEGY_NAMES = [s[0] for s in STRATEGIES]

# ─────────────────────────────────────────────
# PLAYER
# ─────────────────────────────────────────────

class Player:
    def __init__(self, pid: int, chips: int):
        self.pid = pid
        self.chips = chips
        self.hole: List[Card] = []
        self.folded = False
        self.all_in = False
        self.bet_this_street = 0
        self.total_bet_this_hand = 0

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_street = 0
        self.total_bet_this_hand = 0

    @property
    def active(self):
        return not self.folded and not self.all_in and self.chips > 0

    @property
    def in_hand(self):
        return not self.folded

# ─────────────────────────────────────────────
# BETTING ENGINE
# ─────────────────────────────────────────────

def run_betting_street(players: List[Player], pot: int, street: str,
                       community: List[Card], dealer_idx: int,
                       strategies, small_blind: int) -> int:
    """
    Run one street of betting. Returns updated pot.
    players[i] corresponds to strategies[i].
    """
    n = len(players)
    current_bet = 0
    aggressor_raised = False
    min_raise = small_blind * 2

    # Determine acting order: preflop starts left of BB (dealer+3), else dealer+1
    if street == "preflop":
        start = (dealer_idx + 3) % n
        # Set blinds
        sb_idx = (dealer_idx + 1) % n
        bb_idx = (dealer_idx + 2) % n
        sb_player = players[sb_idx]
        bb_player = players[bb_idx]
        sb = min(small_blind, sb_player.chips)
        bb = min(small_blind * 2, bb_player.chips)
        sb_player.chips -= sb; sb_player.bet_this_street = sb
        bb_player.chips -= bb; bb_player.bet_this_street = bb
        if sb_player.chips == 0: sb_player.all_in = True
        if bb_player.chips == 0: bb_player.all_in = True
        pot += sb + bb
        current_bet = bb
    else:
        start = (dealer_idx + 1) % n

    # Track who can still act
    last_raiser = None
    acted = set()

    action_order = [(start + i) % n for i in range(n)]

    idx_ptr = 0
    laps = 0

    while laps < n * 4:
        i = action_order[idx_ptr % len(action_order)]
        idx_ptr += 1
        laps += 1
        p = players[i]

        if p.folded or p.all_in or p.chips == 0:
            # Check if we've gone full circle since last raise
            active_can_act = [x for x in players
                              if not x.folded and not x.all_in and x.chips > 0]
            if not active_can_act:
                break
            continue

        to_call = max(0, current_bet - p.bet_this_street)

        # Done condition: no one else to act and everyone has called
        still_need_to_act = [x for x in players
                             if not x.folded and not x.all_in
                             and x.chips > 0 and x.pid != p.pid
                             and x.bet_this_street < current_bet]
        already_resolved = (to_call == 0 and p.pid in acted
                            and not any(x.bet_this_street < current_bet
                                        for x in players
                                        if not x.folded and not x.all_in))
        if already_resolved and not still_need_to_act:
            break

        # Build game state
        position = action_order.index(i)
        n_active = sum(1 for x in players if not x.folded)
        active_stacks = {x.pid: x.chips for x in players if not x.folded}

        gs = GameState(
            hole=p.hole, community=community,
            pot=pot, to_call=to_call,
            min_raise=min_raise, my_stack=p.chips,
            active_stacks=active_stacks,
            street=street, position=position,
            n_active=n_active,
            already_bet=p.bet_this_street,
            aggressor_raised_this_street=aggressor_raised,
            player_id=p.pid,
            bet_history=[]
        )

        strat_fn = strategies[i]
        try:
            action, amount = strat_fn(gs)
        except Exception:
            action, amount = ("fold", 0)

        acted.add(p.pid)

        if action == "fold":
            p.folded = True
            # If only one remains, done
            remaining = [x for x in players if not x.folded]
            if len(remaining) == 1:
                return pot

        elif action in ("check",):
            if to_call > 0:
                # Can't check when facing a bet — fold
                p.folded = True
                remaining = [x for x in players if not x.folded]
                if len(remaining) == 1:
                    return pot

        elif action == "all_in":
            actual = p.chips
            p.chips = 0
            pot += actual
            p.bet_this_street += actual
            p.total_bet_this_hand += actual
            p.all_in = True
            if p.bet_this_street > current_bet:
                current_bet = p.bet_this_street
                aggressor_raised = True
                last_raiser = i
                # Reset acted for those who haven't matched
                acted = {p.pid}
                laps = 0

        elif action == "call":
            actual = min(to_call, p.chips)
            p.chips -= actual
            pot += actual
            p.bet_this_street += actual
            p.total_bet_this_hand += actual
            if p.chips == 0:
                p.all_in = True

        elif action == "raise":
            amount = max(amount, gs.min_raise)
            # raise amount is total street bet target
            total_target = min(p.bet_this_street + amount, p.chips + p.bet_this_street)
            actual_add = total_target - p.bet_this_street
            actual_add = min(actual_add, p.chips)
            p.chips -= actual_add
            pot += actual_add
            p.bet_this_street += actual_add
            p.total_bet_this_hand += actual_add
            if p.chips == 0:
                p.all_in = True
            if p.bet_this_street > current_bet:
                current_bet = p.bet_this_street
                aggressor_raised = True
                min_raise = p.bet_this_street - current_bet if p.bet_this_street > current_bet else min_raise
                last_raiser = i
                acted = {p.pid}
                laps = 0

        # Check if action round is done
        can_act = [x for x in players
                   if not x.folded and not x.all_in and x.chips > 0]
        needs_to_call = [x for x in can_act if x.bet_this_street < current_bet]
        if not can_act or (not needs_to_call and all(x.pid in acted for x in can_act)):
            break

    return pot


# ─────────────────────────────────────────────
# SHOWDOWN
# ─────────────────────────────────────────────

def showdown(players: List[Player], community: List[Card], pot: int) -> List[Tuple]:
    """Determine winners and split pot. Returns list of (player, amount_won)."""
    contenders = [p for p in players if not p.folded]
    if len(contenders) == 1:
        return [(contenders[0], pot)]

    # Score each contender
    scored = [(best_hand(p.hole, community), p) for p in contenders]
    max_score = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == max_score]

    # Handle side pots simply: split evenly among winners
    share = pot // len(winners)
    remainder = pot - share * len(winners)
    result = [(w, share) for w in winners]
    if remainder > 0:
        result[0] = (result[0][0], result[0][1] + remainder)
    return result


# ─────────────────────────────────────────────
# SINGLE HAND
# ─────────────────────────────────────────────

def play_hand(players: List[Player], dealer_idx: int,
              strategies, small_blind: int) -> None:
    """Play one hand, mutate player.chips in place."""
    active_players = [p for p in players if p.chips > 0]
    if len(active_players) < 2:
        return

    for p in players:
        p.reset_hand()

    deck = fresh_deck()
    ptr = 0

    # Deal hole cards
    for p in active_players:
        p.hole = [deck[ptr], deck[ptr+1]]
        ptr += 2

    community: List[Card] = []
    pot = 0

    # Pre-flop
    pot = run_betting_street(active_players, pot, "preflop",
                             community, dealer_idx, strategies, small_blind)
    remaining = [p for p in active_players if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += pot
        return

    # Flop
    community.extend([deck[ptr], deck[ptr+1], deck[ptr+2]]); ptr += 3
    pot = run_betting_street(active_players, pot, "flop",
                             community, dealer_idx, strategies, small_blind)
    remaining = [p for p in active_players if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += pot
        return

    # Turn
    community.append(deck[ptr]); ptr += 1
    pot = run_betting_street(active_players, pot, "turn",
                             community, dealer_idx, strategies, small_blind)
    remaining = [p for p in active_players if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += pot
        return

    # River
    community.append(deck[ptr]); ptr += 1
    pot = run_betting_street(active_players, pot, "river",
                             community, dealer_idx, strategies, small_blind)
    remaining = [p for p in active_players if not p.folded]
    if len(remaining) == 1:
        remaining[0].chips += pot
        return

    # Showdown
    payouts = showdown(active_players, community, pot)
    for winner, amount in payouts:
        winner.chips += amount


# ─────────────────────────────────────────────
# TOURNAMENT  (play until one player remains)
# ─────────────────────────────────────────────

def run_tournament(starting_chips: int = 1000,
                   small_blind: int = 10,
                   max_hands: int = 2000) -> int:
    """Run one tournament. Returns pid of winner (0-indexed)."""
    n = len(STRATEGIES)
    players = [Player(i, starting_chips) for i in range(n)]
    strat_fns = [s[1] for s in STRATEGIES]

    dealer_idx = random.randint(0, n - 1)
    blind = small_blind
    hands_played = 0

    for hand_num in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid
        if len(alive) == 0:
            return random.choice(players).pid

        # Escalate blinds every 100 hands
        blind = small_blind * (1 + hand_num // 100)

        # Rotate dealer among alive players
        alive_ids = {p.pid for p in alive}
        while players[dealer_idx].chips == 0:
            dealer_idx = (dealer_idx + 1) % n

        play_hand(players, dealer_idx, strat_fns, blind)

        dealer_idx = (dealer_idx + 1) % n
        while players[dealer_idx % n].chips == 0:
            dealer_idx += 1
        dealer_idx %= n

        hands_played += 1

    # Time limit: richest player wins
    return max(range(n), key=lambda i: players[i].chips)


# ─────────────────────────────────────────────
# HISTOGRAM OUTPUT
# ─────────────────────────────────────────────

def print_histogram(wins: Counter, n_sims: int) -> None:
    max_w = max(wins.values()) if wins else 1
    bar_width = 40

    print()
    print("=" * 70)
    print("  TEXAS HOLD'EM TOURNAMENT RESULTS  —  {} SIMULATIONS".format(n_sims))
    print("=" * 70)
    print()

    # Sort by wins descending
    order = sorted(range(len(STRATEGIES)), key=lambda i: wins.get(i, 0), reverse=True)

    for rank, pid in enumerate(order, 1):
        name = STRATEGY_NAMES[pid]
        w = wins.get(pid, 0)
        pct = 100.0 * w / n_sims
        bar_len = int(bar_width * w / max_w) if max_w > 0 else 0
        bar = "█" * bar_len + "░" * (bar_width - bar_len)
        label = f"P{pid+1}"
        tag = " ← MANIAC (all-in)" if pid == 0 else ""
        print(f"  #{rank}  {label} {name:<28}{tag}")
        print(f"       [{bar}] {w:>3} wins ({pct:5.1f}%)")
        print()

    print("=" * 70)
    print()

    # Narrative summary
    winner_pid = max(range(len(STRATEGIES)), key=lambda i: wins.get(i, 0))
    winner_name = STRATEGY_NAMES[winner_pid]
    maniac_wins = wins.get(0, 0)
    maniac_pct = 100.0 * maniac_wins / n_sims

    print(f"  CHAMPION: P{winner_pid+1} — {winner_name}")
    print(f"  The Maniac (all-in every turn): {maniac_wins} wins ({maniac_pct:.1f}%)")
    print()

    if maniac_wins > n_sims * 0.20:
        print("  Verdict: The Maniac caused CHAOS — variance rewarded recklessness.")
    elif maniac_wins > n_sims * 0.10:
        print("  Verdict: The Maniac scraped some wins — mostly got coolered out early.")
    else:
        print("  Verdict: Maniac HUMILIATED — the algos ate it alive. RIP suflair gpt.")
    print()
    print("=" * 70)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    N_SIMS = 100
    STARTING_CHIPS = 1500
    SMALL_BLIND = 15

    print()
    print("  Texas Hold'em Poker Simulator  —  6 Players, {} tournaments".format(N_SIMS))
    print()
    print("  Strategies:")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  [SIMPLE: if my_turn → ALL_IN fi]" if i == 0 else ""
        print(f"    P{i+1}: {name}{tag}")
    print()
    print(f"  Starting chips: {STARTING_CHIPS}  |  Small blind: {SMALL_BLIND}")
    print()
    print("  Running simulations", end="", flush=True)

    wins: Counter = Counter()

    for sim in range(N_SIMS):
        if sim % 10 == 0:
            print(".", end="", flush=True)
        winner_pid = run_tournament(
            starting_chips=STARTING_CHIPS,
            small_blind=SMALL_BLIND
        )
        wins[winner_pid] += 1

    print(" done!")

    print_histogram(wins, N_SIMS)


if __name__ == "__main__":
    main()
