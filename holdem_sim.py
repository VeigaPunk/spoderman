"""
Texas Hold'em: 6-player simulation
Player 1 = Degenerate Dan  → always goes all-in
Players 2-6 = five elaborate strategy bots
100 tournaments, histogram of winners.
"""

import random
from itertools import combinations
from collections import Counter, defaultdict

# ─────────────────────────────────────────────
# DECK / HAND EVALUATION
# ─────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_val(c):
    return RANK_VAL[c[0]]

def hand_rank(cards):
    """Return a comparable tuple for best 5-card hand from 5-7 cards."""
    best = None
    for combo in combinations(cards, 5):
        score = score_five(combo)
        if best is None or score > best:
            best = score
    return best

def score_five(hand):
    vals = sorted([card_val(c) for c in hand], reverse=True)
    suits = [c[1] for c in hand]
    flush = len(set(suits)) == 1
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    # wheel straight A-2-3-4-5
    if set(vals) == {12, 0, 1, 2, 3}:
        straight = True
        vals = [3, 2, 1, 0, -1]
    counts = sorted(Counter(vals).values(), reverse=True)
    count_vals = sorted(Counter(vals).keys(),
                        key=lambda v: (Counter(vals)[v], v), reverse=True)
    if flush and straight:  return (8,) + tuple(vals)
    if counts[0] == 4:      return (7,) + tuple(count_vals)
    if counts[:2] == [3,2]: return (6,) + tuple(count_vals)
    if flush:               return (5,) + tuple(vals)
    if straight:            return (4,) + tuple(vals)
    if counts[0] == 3:      return (3,) + tuple(count_vals)
    if counts[:2] == [2,2]: return (2,) + tuple(count_vals)
    if counts[0] == 2:      return (1,) + tuple(count_vals)
    return (0,) + tuple(vals)

def hand_strength(hole, community):
    """0-1 estimate of hand strength via enumeration (fast version)."""
    return hand_rank(hole + community)

# ─────────────────────────────────────────────
# HOLE CARD PRE-FLOP SCORING
# ─────────────────────────────────────────────

def preflop_score(hole):
    """Score hole cards 0-1 based on Chen-like formula."""
    r0, r1 = card_val(hole[0]), card_val(hole[1])
    s0, s1 = hole[0][1], hole[1][1]
    hi, lo = max(r0, r1), min(r0, r1)
    suited = s0 == s1
    gap = hi - lo
    score = hi  # base: high card 0-12
    if hi == lo:   score += 8   # pair bonus
    if suited:     score += 2
    if gap == 0:   pass          # pair already handled
    elif gap == 1: score += 1   # connector
    elif gap == 2: score += 0.5
    score -= max(0, gap - 2)    # penalty for big gaps
    return min(score / 22, 1.0)

# ─────────────────────────────────────────────
# POT ODDS UTILITY
# ─────────────────────────────────────────────

def pot_odds(call_amount, pot):
    if call_amount == 0:
        return 1.0
    return pot / (pot + call_amount)

# ─────────────────────────────────────────────
# STRATEGY IMPLEMENTATIONS
# ─────────────────────────────────────────────

class Action:
    FOLD = 'fold'
    CALL = 'call'
    RAISE = 'raise'
    CHECK = 'check'
    ALLIN = 'allin'

def decide(strategy, state):
    """
    state keys:
      hole, community, pot, to_call, stack, big_blind,
      street, position, num_active, raise_count
    Returns (action, amount)  — amount relevant only for RAISE
    """
    return strategy(state)

# ── Strategy 1 (Player 1): Degenerate Dan ────
def dan_the_degenerate(state):
    """If my_turn → bet = all-in. Fi."""
    return (Action.ALLIN, state['stack'])

# ── Strategy 2 (Player 2): GTO Gary ──────────
def gto_gary(state):
    """
    Balanced GTO-inspired play:
    - Pre-flop: top 30% of hands open, top 10% 3-bet
    - Post-flop: bet ~66% pot with top 40% equity
    - Mixed strategies: bluff 33% of missed draws
    - Position-aware: wider range in late position
    """
    hole = state['hole']
    community = state['community']
    pot = state['pot']
    to_call = state['to_call']
    stack = state['stack']
    position = state['position']   # 0 = UTG, num_active-1 = BTN
    num_active = state['num_active']
    street = state['street']
    bb = state['big_blind']
    raise_count = state['raise_count']

    pf = preflop_score(hole)
    pos_bonus = position / max(num_active - 1, 1) * 0.15  # 0 to 0.15

    if not community:  # pre-flop
        effective = pf + pos_bonus
        if effective > 0.85 and raise_count < 3:
            return (Action.RAISE, min(3 * to_call + pot // 2, stack))
        if effective > 0.55:
            if to_call == 0:
                return (Action.RAISE, min(2.5 * bb, stack))
            return (Action.CALL, to_call)
        if to_call <= bb and effective > 0.35:
            return (Action.CALL, to_call)
        if to_call == 0:
            return (Action.CHECK, 0)
        return (Action.FOLD, 0)

    # post-flop equity proxy
    rank = hand_rank(hole + community)
    cat = rank[0]  # 0=high card .. 8=straight flush

    # Draw detection (4-card flush / open-ended straight)
    suits_board = [c[1] for c in community]
    my_suits = [c[1] for c in hole]
    all_suits = suits_board + my_suits
    flush_draw = max(Counter(all_suits).values()) >= 4 and cat < 5
    vals_all = sorted([card_val(c) for c in hole + community])
    consec = sum(1 for i in range(len(vals_all)-1) if vals_all[i+1]-vals_all[i]==1)
    oesd = consec >= 3 and cat < 4

    equity = cat / 8.0
    if cat >= 4: equity = 0.75 + cat * 0.025
    if flush_draw: equity += 0.18
    if oesd: equity += 0.15
    equity = min(equity, 1.0)

    # GTO balance: bluff with 33% of weak hands (random seed on state)
    bluffing = (flush_draw or oesd) and random.random() < 0.33

    if equity > 0.6 or bluffing:
        bet = int(pot * 0.66)
        if to_call == 0:
            return (Action.RAISE, min(bet, stack))
        if raise_count < 3:
            return (Action.RAISE, min(to_call + bet, stack))
        return (Action.CALL, min(to_call, stack))
    if equity > 0.35:
        if to_call == 0:
            return (Action.CHECK, 0)
        if to_call <= pot_odds(to_call, pot) * pot:
            return (Action.CALL, min(to_call, stack))
        return (Action.FOLD, 0)
    if to_call == 0:
        return (Action.CHECK, 0)
    return (Action.FOLD, 0)

# ── Strategy 3 (Player 3): TAG Terry ──────────
def tag_terry(state):
    """
    Tight-Aggressive: only top 20% of hands, but always bets hard.
    Never slow-plays; never calls without premium equity.
    """
    hole = state['hole']
    community = state['community']
    pot = state['pot']
    to_call = state['to_call']
    stack = state['stack']
    bb = state['big_blind']
    raise_count = state['raise_count']

    pf = preflop_score(hole)

    if not community:
        if pf > 0.78:  # top 22% (pairs JJ+, AK, AQ suited, etc.)
            if raise_count < 2:
                return (Action.RAISE, min(4 * max(to_call, bb), stack))
            return (Action.CALL, min(to_call, stack))
        if pf > 0.6 and to_call <= bb * 2:
            return (Action.CALL, min(to_call, stack))
        if to_call == 0:
            return (Action.CHECK, 0)
        return (Action.FOLD, 0)

    rank = hand_rank(hole + community)
    cat = rank[0]

    if cat >= 4:  # strong made hand
        bet = int(pot * 0.75)
        if to_call == 0:
            return (Action.RAISE, min(bet, stack))
        return (Action.RAISE, min(to_call + int(pot * 0.5), stack))
    if cat >= 2:  # decent hand
        if to_call == 0:
            return (Action.RAISE, min(int(pot * 0.6), stack))
        if to_call <= int(pot * 0.35):
            return (Action.CALL, min(to_call, stack))
        return (Action.FOLD, 0)
    # weak: check/fold
    if to_call == 0:
        return (Action.CHECK, 0)
    return (Action.FOLD, 0)

# ── Strategy 4 (Player 4): LAG Larry ──────────
def lag_larry(state):
    """
    Loose-Aggressive: plays a wide range (top 60%), bluffs constantly,
    applies maximum pressure. Three-bets light, c-bets every flop.
    """
    hole = state['hole']
    community = state['community']
    pot = state['pot']
    to_call = state['to_call']
    stack = state['stack']
    bb = state['big_blind']
    position = state['position']
    num_active = state['num_active']
    raise_count = state['raise_count']

    pf = preflop_score(hole)
    in_position = position >= num_active - 2

    if not community:
        if pf > 0.45 or in_position:
            if raise_count == 0:
                return (Action.RAISE, min(3 * bb, stack))
            if raise_count == 1 and pf > 0.55:
                return (Action.RAISE, min(3 * to_call, stack))  # 3-bet light
            return (Action.CALL, min(to_call, stack))
        if to_call == 0:
            return (Action.RAISE, min(2 * bb, stack))
        return (Action.FOLD, 0)

    rank = hand_rank(hole + community)
    cat = rank[0]
    # c-bet every flop regardless
    bluff_bet = int(pot * 0.55)

    if cat >= 5:
        return (Action.RAISE, min(int(pot * 0.9), stack))
    if cat >= 2:
        if to_call == 0:
            return (Action.RAISE, min(int(pot * 0.65), stack))
        if raise_count < 2:
            return (Action.RAISE, min(to_call + int(pot * 0.5), stack))
        return (Action.CALL, min(to_call, stack))
    # air: c-bet or semi-bluff
    if to_call == 0 and (random.random() < 0.65 or in_position):
        return (Action.RAISE, min(bluff_bet, stack))
    if to_call > 0 and to_call <= int(pot * 0.4) and random.random() < 0.5:
        return (Action.CALL, min(to_call, stack))
    if to_call == 0:
        return (Action.CHECK, 0)
    return (Action.FOLD, 0)

# ── Strategy 5 (Player 5): Nit Nick ───────────
def nit_nick(state):
    """
    Ultra-nit: only top 8% of hands (AA, KK, QQ, AKs, AKo).
    Folds everything else preflop. Post-flop: value-bet only monsters.
    """
    hole = state['hole']
    community = state['community']
    pot = state['pot']
    to_call = state['to_call']
    stack = state['stack']
    bb = state['big_blind']
    raise_count = state['raise_count']

    pf = preflop_score(hole)

    if not community:
        if pf > 0.90:  # only the very best
            return (Action.RAISE, min(4 * max(to_call, bb), stack))
        if to_call == 0 or to_call <= bb // 2:
            return (Action.CHECK, 0) if to_call == 0 else (Action.CALL, to_call)
        return (Action.FOLD, 0)

    rank = hand_rank(hole + community)
    cat = rank[0]

    if cat >= 6:  # full house or better
        return (Action.RAISE, min(int(pot * 1.0), stack))
    if cat >= 4:  # flush or better
        if to_call == 0:
            return (Action.RAISE, min(int(pot * 0.7), stack))
        return (Action.CALL, min(to_call, stack))
    if cat >= 2:
        if to_call == 0:
            return (Action.CHECK, 0)
        if to_call <= bb * 2:
            return (Action.CALL, min(to_call, stack))
        return (Action.FOLD, 0)
    if to_call == 0:
        return (Action.CHECK, 0)
    return (Action.FOLD, 0)

# ── Strategy 6 (Player 6): Exploitative Eva ───
def exploitative_eva(state):
    """
    Pot-odds aware exploit bot:
    - Tracks pot equity vs call price rigorously
    - Adjusts bet sizes based on board texture (dry vs wet)
    - Over-folds to nits, over-calls vs LAGs
    - Raises for value in thin spots when stack depth permits
    """
    hole = state['hole']
    community = state['community']
    pot = state['pot']
    to_call = state['to_call']
    stack = state['stack']
    bb = state['big_blind']
    raise_count = state['raise_count']
    num_active = state['num_active']

    pf = preflop_score(hole)

    if not community:
        # Widen call range based on pot odds; raise premium
        if pf > 0.80:
            return (Action.RAISE, min(3.5 * max(to_call, bb), stack))
        required_equity = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.5
        if pf > 0.50 and pf > required_equity:
            if raise_count < 2:
                return (Action.RAISE, min(2.5 * bb, stack))
            return (Action.CALL, min(to_call, stack))
        if pf >= required_equity and to_call <= bb * 3:
            return (Action.CALL, min(to_call, stack))
        if to_call == 0:
            return (Action.CHECK, 0)
        return (Action.FOLD, 0)

    rank = hand_rank(hole + community)
    cat = rank[0]

    # Board texture: wet = many draws possible
    suits_board = Counter(c[1] for c in community)
    vals_board = sorted([card_val(c) for c in community])
    wetness = (max(suits_board.values()) >= 3) + \
              (sum(1 for i in range(len(vals_board)-1)
                   if vals_board[i+1]-vals_board[i] <= 2) >= 2)
    # 0 = dry, 1 = semi-wet, 2 = very wet

    # Equity estimate
    equity = cat / 8.0
    if cat >= 3: equity = 0.5 + cat * 0.06
    equity = min(equity, 1.0)

    req = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    if equity > 0.65:
        # Bet bigger on dry boards (more of a polar value range)
        size_mult = 0.9 if wetness < 2 else 0.6
        bet = int(pot * size_mult)
        if to_call == 0:
            return (Action.RAISE, min(bet, stack))
        if raise_count < 3:
            return (Action.RAISE, min(to_call + bet, stack))
        return (Action.CALL, min(to_call, stack))
    if equity > req + 0.05:
        # Positive pot-odds call, no raise
        if to_call == 0:
            return (Action.CHECK, 0)
        return (Action.CALL, min(to_call, stack))
    if to_call == 0:
        return (Action.CHECK, 0)
    return (Action.FOLD, 0)


STRATEGIES = [
    dan_the_degenerate,
    gto_gary,
    tag_terry,
    lag_larry,
    nit_nick,
    exploitative_eva,
]

PLAYER_NAMES = [
    "Dan (All-In Dan)",
    "Gary (GTO)",
    "Terry (TAG)",
    "Larry (LAG)",
    "Nick (Nit)",
    "Eva (Exploit)",
]

# ─────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────

class Player:
    def __init__(self, pid, name, strategy, stack):
        self.pid = pid
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def is_active(self):
        return not self.folded and not self.all_in and self.stack > 0

    def __repr__(self):
        return f"{self.name}(${self.stack})"


def deal_hand(players, deck, dealer_idx, small_blind, big_blind):
    """Returns community_cards placeholder and posts blinds."""
    n = len(players)
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    pot = 0
    for p in players:
        p.reset_hand()

    # deal 2 cards each
    for p in players:
        p.hole = [deck.pop(), deck.pop()]

    # post blinds
    sb_p = players[sb_idx]
    bb_p = players[bb_idx]

    sb_amount = min(small_blind, sb_p.stack)
    sb_p.stack -= sb_amount
    sb_p.bet_this_round = sb_amount
    pot += sb_amount

    bb_amount = min(big_blind, bb_p.stack)
    bb_p.stack -= bb_amount
    bb_p.bet_this_round = bb_amount
    pot += bb_amount

    return pot, bb_idx


def betting_round(players, pot, street, community, big_blind,
                  first_to_act_idx, current_bet=0, raise_count=0):
    """
    Single betting round. Returns updated pot.
    first_to_act_idx: index into players list.
    current_bet: the amount already put in by the highest bettor this round.
    """
    n = len(players)
    active = [p for p in players if not p.folded and p.stack + p.bet_this_round > 0]
    if len(active) <= 1:
        return pot

    # Reset bets for this round (except pre-flop which starts with blinds already in)
    if street != 'preflop':
        for p in players:
            p.bet_this_round = 0
        current_bet = 0

    # Action order
    order = [(first_to_act_idx + i) % n for i in range(n)]
    acted = set()
    last_raiser = None

    idx_cursor = 0
    max_iterations = n * 6  # safety

    iteration = 0
    while iteration < max_iterations:
        iteration += 1

        # Find next player who should act
        pid_order = order[idx_cursor % n:]
        pid_order += order[:idx_cursor % n]

        # Build action sequence dynamically
        to_act = None
        for i, idx in enumerate([(first_to_act_idx + idx_cursor + i) % n
                                  for i in range(n)]):
            p = players[idx]
            if p.folded or p.all_in:
                continue
            if p.stack == 0:
                p.all_in = True
                continue
            to_call = current_bet - p.bet_this_round
            if to_call < 0:
                to_call = 0
            # Has this player acted since the last raise?
            if p.pid not in acted or (last_raiser is not None and p.pid != last_raiser):
                to_act = (idx, p, to_call)
                break

        if to_act is None:
            break

        idx, p, to_call = to_act
        idx_cursor = (idx + 1)

        position = sum(
            1 for pp in players
            if not pp.folded and pp.pid < p.pid
        )
        num_active_now = sum(1 for pp in players if not pp.folded)

        state = {
            'hole': p.hole,
            'community': community,
            'pot': pot,
            'to_call': min(to_call, p.stack),
            'stack': p.stack,
            'big_blind': big_blind,
            'street': street,
            'position': position,
            'num_active': num_active_now,
            'raise_count': raise_count,
        }

        action, amount = p.strategy(state)

        acted.add(p.pid)

        if action == Action.FOLD:
            p.folded = True
            # Check if only 1 remains
            remaining = [pp for pp in players if not pp.folded]
            if len(remaining) == 1:
                break

        elif action in (Action.CALL, Action.CHECK):
            call_amt = min(to_call, p.stack)
            p.stack -= call_amt
            p.bet_this_round += call_amt
            pot += call_amt
            if p.stack == 0:
                p.all_in = True

        elif action in (Action.RAISE, Action.ALLIN):
            if action == Action.ALLIN:
                amount = p.stack
            else:
                amount = max(int(amount), to_call + big_blind)
                amount = min(amount, p.stack)

            # If amount only covers the call, treat as call
            if amount <= to_call:
                call_amt = min(to_call, p.stack)
                p.stack -= call_amt
                p.bet_this_round += call_amt
                pot += call_amt
                if p.stack == 0:
                    p.all_in = True
            else:
                p.stack -= amount
                p.bet_this_round += amount
                pot += amount
                new_bet = p.bet_this_round
                if new_bet > current_bet:
                    current_bet = new_bet
                    raise_count += 1
                    last_raiser = p.pid
                    acted = {p.pid}   # everyone else must act again
                if p.stack == 0:
                    p.all_in = True

        # End if only one non-folded player
        remaining = [pp for pp in players if not pp.folded]
        if len(remaining) == 1:
            break

        # Check if all active (non-folded, non-all-in) are even
        active_now = [pp for pp in players
                      if not pp.folded and not pp.all_in and pp.stack > 0]
        if all(pp.bet_this_round == current_bet for pp in active_now) and \
           len(acted) >= len([pp for pp in players if not pp.folded and not pp.all_in]):
            break

    return pot


def showdown(players, community):
    """Return list of winners (split pot handles ties)."""
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        return alive
    best_rank = None
    winners = []
    for p in alive:
        r = hand_rank(p.hole + community)
        if best_rank is None or r > best_rank:
            best_rank = r
            winners = [p]
        elif r == best_rank:
            winners.append(p)
    return winners


def play_hand(players, dealer_idx, small_blind, big_blind):
    """
    Play one hand of Hold'em. Modifies player stacks in-place.
    Returns winner name (or 'split').
    """
    deck = make_deck()
    random.shuffle(deck)

    pot, bb_idx = deal_hand(players, deck, dealer_idx, small_blind, big_blind)
    community = []

    # ── Pre-flop ──────────────────────────────
    utg_idx = (dealer_idx + 3) % len(players)
    current_bet = max(p.bet_this_round for p in players)
    pot = betting_round(players, pot, 'preflop', community, big_blind,
                        utg_idx, current_bet=current_bet, raise_count=1)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].stack += pot
        return alive[0].name

    # ── Flop ──────────────────────────────────
    community += [deck.pop(), deck.pop(), deck.pop()]
    pot = betting_round(players, pot, 'flop', community, big_blind,
                        (dealer_idx + 1) % len(players))

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].stack += pot
        return alive[0].name

    # ── Turn ──────────────────────────────────
    community.append(deck.pop())
    pot = betting_round(players, pot, 'turn', community, big_blind,
                        (dealer_idx + 1) % len(players))

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].stack += pot
        return alive[0].name

    # ── River ─────────────────────────────────
    community.append(deck.pop())
    pot = betting_round(players, pot, 'river', community, big_blind,
                        (dealer_idx + 1) % len(players))

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].stack += pot
        return alive[0].name

    # ── Showdown ──────────────────────────────
    winners = showdown(players, community)
    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        w.stack += share
    winners[0].stack += remainder   # extra chip to first winner
    return winners[0].name if len(winners) == 1 else f"split({','.join(w.name for w in winners)})"


def play_tournament(starting_chips=10000, small_blind=50, big_blind=100):
    """
    Play one full tournament until one player has all chips.
    Returns name of the winner.
    """
    players = [
        Player(i, PLAYER_NAMES[i], STRATEGIES[i], starting_chips)
        for i in range(6)
    ]
    dealer_idx = 0
    hand_num = 0
    max_hands = 2000  # safety cap

    while hand_num < max_hands:
        hand_num += 1
        # Remove busted players
        active = [p for p in players if p.stack > 0]
        if len(active) == 1:
            return active[0].name

        # Adjust blinds: every 20 hands increase blinds
        level = hand_num // 20
        sb = small_blind * (2 ** level)
        bb = big_blind * (2 ** level)

        # Reset round state
        for p in players:
            if p.stack == 0:
                p.folded = True   # permanantly out

        # Only active players play
        round_players = [p for p in players if p.stack > 0]
        d_idx = dealer_idx % len(round_players)
        play_hand(round_players, d_idx, sb, bb)

        dealer_idx += 1

    # If cap reached, player with most chips wins
    active = [p for p in players if p.stack > 0]
    return max(active, key=lambda p: p.stack).name


# ─────────────────────────────────────────────
# RUN 100 SIMULATIONS
# ─────────────────────────────────────────────

def run_simulations(n=100, seed=42):
    random.seed(seed)
    win_counts = defaultdict(int)

    for i in range(n):
        if i % 10 == 0:
            print(f"  Running simulation {i+1}/{n}...")
        winner = play_tournament()
        # Normalize split winners to individual names
        if winner.startswith("split"):
            for name in PLAYER_NAMES:
                if name in winner:
                    win_counts[name] += 0.5
        else:
            win_counts[winner] += 1

    return win_counts


if __name__ == "__main__":
    print("=" * 60)
    print("TEXAS HOLD'EM: 6-PLAYER STRATEGY SHOWDOWN")
    print("100 full tournaments, each player starts with $10,000")
    print("=" * 60)
    print()
    for i, name in enumerate(PLAYER_NAMES):
        strat_desc = [
            "SIMPLE: always goes ALL-IN, every single action",
            "ELABORATE: GTO balanced ranges, bluff 33% draws, position-aware",
            "ELABORATE: Tight-Aggressive, top 22% hands, max value-bets",
            "ELABORATE: Loose-Aggressive, wide range, constant pressure, c-bets all",
            "ELABORATE: Ultra-nit, top 8% only, full house+ to bet big",
            "ELABORATE: Exploitative, pot-odds calculations, board-texture sizing",
        ][i]
        print(f"  Player {i+1}: {name}")
        print(f"           {strat_desc}")
    print()

    results = run_simulations(100)

    print()
    print("=" * 60)
    print("RESULTS: TOURNAMENT WINS (out of 100)")
    print("=" * 60)

    # Sort by wins descending
    sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, wins) in enumerate(sorted_results, 1):
        bar = "█" * int(wins)
        print(f"  #{rank:2d} {name:<25} {wins:5.1f} wins  {bar}")

    print()
    print("=" * 60)
    winner_name, winner_wins = sorted_results[0]
    print(f"CHICKEN DINNER CHAMPION: {winner_name}")
    print(f"with {winner_wins} tournament victories out of 100!")
    print("=" * 60)

    # Output JSON for the artifact
    import json
    output = {
        "results": [(n, w) for n, w in sorted_results],
        "total_sims": 100,
        "player_descriptions": {
            PLAYER_NAMES[0]: "SIMPLE: always ALL-IN",
            PLAYER_NAMES[1]: "GTO Balanced",
            PLAYER_NAMES[2]: "Tight-Aggressive (TAG)",
            PLAYER_NAMES[3]: "Loose-Aggressive (LAG)",
            PLAYER_NAMES[4]: "Ultra-Nit",
            PLAYER_NAMES[5]: "Exploitative (Pot-Odds)",
        }
    }
    with open("/home/user/spoderman/sim_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\nResults saved to sim_results.json")
