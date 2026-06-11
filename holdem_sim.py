#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
6 players, 100 tournaments
Player 1: Simple ALL-IN strategy
Players 2-6: 5 elaborate strategies
"""

import random
import collections
from itertools import combinations

# ─────────────────────────────────────────────────────────────
# CARD / DECK
# ─────────────────────────────────────────────────────────────

RANKS = list(range(2, 15))          # 2-14, Ace = 14
SUITS = ['s', 'h', 'd', 'c']
RANK_SYM = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',
            9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

class Card:
    __slots__ = ('rank', 'suit')
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
    def __repr__(self):
        return f"{RANK_SYM[self.rank]}{self.suit}"

class Deck:
    def __init__(self):
        self.cards = [Card(r, s) for r in RANKS for s in SUITS]
        random.shuffle(self.cards)

    def deal(self, n=1):
        out = self.cards[:n]
        self.cards = self.cards[n:]
        return out

# ─────────────────────────────────────────────────────────────
# HAND EVALUATOR  (returns comparable tuple, higher = better)
# ─────────────────────────────────────────────────────────────

HR = {'high_card':0,'one_pair':1,'two_pair':2,'three_of_a_kind':3,
      'straight':4,'flush':5,'full_house':6,'four_of_a_kind':7,'straight_flush':8}

def score_5(cards):
    ranks = sorted([c.rank for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    flush = len(set(suits)) == 1

    straight, s_high = False, 0
    if ranks[0]-ranks[4] == 4 and len(set(ranks)) == 5:
        straight, s_high = True, ranks[0]
    if set(ranks) == {14,2,3,4,5}:          # wheel
        straight, s_high = True, 5

    cnt = collections.Counter(ranks)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    vals = sorted(cnt.values(), reverse=True)

    if straight and flush:
        return (HR['straight_flush'], s_high)
    if vals[0] == 4:
        return (HR['four_of_a_kind'], groups[0], groups[1])
    if vals[0] == 3 and vals[1] == 2:
        return (HR['full_house'], groups[0], groups[1])
    if flush:
        return (HR['flush'],) + tuple(ranks)
    if straight:
        return (HR['straight'], s_high)
    if vals[0] == 3:
        kickers = [r for r in ranks if cnt[r] != 3]
        return (HR['three_of_a_kind'], groups[0]) + tuple(kickers)
    if vals[0] == 2 and vals[1] == 2:
        pairs = sorted([r for r,c in cnt.items() if c==2], reverse=True)
        kick = [r for r,c in cnt.items() if c==1][0]
        return (HR['two_pair'], pairs[0], pairs[1], kick)
    if vals[0] == 2:
        pair = groups[0]
        kickers = sorted([r for r in ranks if r != pair], reverse=True)
        return (HR['one_pair'], pair) + tuple(kickers)
    return (HR['high_card'],) + tuple(ranks)

def best_hand(cards):
    """Best 5-card score from up to 7 cards."""
    return max(score_5(combo) for combo in combinations(cards, 5))

# ─────────────────────────────────────────────────────────────
# PREFLOP STRENGTH TABLES
# ─────────────────────────────────────────────────────────────

STRONG_PAIRS_AND_BROADWAY = {
    (14,14),(13,13),(12,12),(11,11),(10,10),(9,9),(8,8),
    (14,13),(14,12),(14,11),(13,12),(13,11),(12,11),
}
MEDIUM_HANDS = {
    (7,7),(6,6),(5,5),(4,4),(3,3),(2,2),
    (14,10),(14,9),(13,10),(12,10),(11,10),
    (10,9),(9,8),(8,7),(7,6),(6,5),
}

def preflop_tier(hole):
    r = tuple(sorted([hole[0].rank, hole[1].rank], reverse=True))
    suited = hole[0].suit == hole[1].suit
    if r in STRONG_PAIRS_AND_BROADWAY:
        return 'strong'
    if r in MEDIUM_HANDS or (suited and r[0] >= 10):
        return 'medium'
    return 'weak'

def equity_estimate(hole, community):
    """Rough equity estimate: 0-1 scale."""
    if not community:
        return {'strong':0.72,'medium':0.50,'weak':0.27}[preflop_tier(hole)]
    score = best_hand(hole + community)
    hand_class = score[0]
    # 0-8 range → map to ~0.15 – 0.95
    return min(0.95, 0.15 + hand_class * 0.10)

# ─────────────────────────────────────────────────────────────
# PLAYER & GAME STATE
# ─────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid          = pid
        self.chips        = chips
        self.strategy_fn  = strategy_fn
        self.hole         = []
        self.folded       = False
        self.all_in       = False
        self.bet_round    = 0          # chips committed this street

    def reset_for_hand(self):
        self.hole      = []
        self.folded    = False
        self.all_in    = False
        self.bet_round = 0

class GameState:
    """Read-only snapshot passed to strategy functions."""
    def __init__(self, players, community, pot, current_bet, dealer_pos, street):
        self.players      = players
        self.community    = community
        self.pot          = pot
        self.current_bet  = current_bet
        self.dealer_pos   = dealer_pos
        self.street       = street
        self.active       = [p for p in players if not p.folded and p.chips > 0]

# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
#   STRATEGY LIBRARY
#   Each function: (player, state) → ('fold'|'call'|'raise', amount)
#   amount for 'raise' = total new chips to put in THIS action
# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────

# ── Strategy 1 ── SIMPLE ALL-IN (Player 1) ──────────────────
def s_allin(player, state):
    """If my_turn then bet = ALL IN fi."""
    return ('raise', player.chips)


# ── Strategy 2 ── TIGHT-AGGRESSIVE (TAG) ────────────────────
def s_tag(player, state):
    """
    Classic TAG: only opens premium holdings, bets 3-bet sizing,
    folds marginal hands to significant pressure post-flop.
    """
    hole     = player.hole
    community = state.community
    equity   = equity_estimate(hole, community)
    call_amt = max(0, state.current_bet - player.bet_round)
    pot      = state.pot

    if state.street == 'preflop':
        tier = preflop_tier(hole)
        if tier == 'strong':
            size = min(player.chips, max(state.current_bet * 3, pot))
            return ('raise', size)
        if tier == 'medium' and call_amt <= pot * 0.15:
            return ('call', call_amt)
        return ('fold', 0)

    # Post-flop
    if equity >= 0.65:
        return ('raise', min(player.chips, max(call_amt, int(pot * 0.75))))
    if equity >= 0.42 and call_amt <= pot * 0.33:
        return ('call', call_amt)
    if call_amt == 0:
        return ('call', 0)   # free check
    return ('fold', 0)


# ── Strategy 3 ── LOOSE-AGGRESSIVE (LAG) ─────────────────────
def s_lag(player, state):
    """
    LAG: wide open range, frequent semi-bluffs and continuation bets,
    adjusts aggression down vs. more players to avoid multiway disasters.
    """
    hole      = player.hole
    community = state.community
    equity    = equity_estimate(hole, community)
    call_amt  = max(0, state.current_bet - player.bet_round)
    pot       = state.pot
    n_active  = len(state.active)

    # Fewer opponents → bluff more
    bluff_floor = 0.28 if n_active <= 3 else 0.42

    if state.street == 'preflop':
        tier = preflop_tier(hole)
        if tier == 'strong':
            return ('raise', min(player.chips, int(pot * 2.2)))
        if tier == 'medium' or n_active <= 3:
            if random.random() < 0.55:
                return ('raise', min(player.chips, int(pot * 1.6)))
            return ('call', call_amt)
        if call_amt == 0 or call_amt <= pot * 0.08:
            return ('call', call_amt)
        if random.random() < 0.22:
            return ('raise', min(player.chips, int(pot * 2.0)))
        return ('fold', 0)

    if equity >= bluff_floor or random.random() < 0.18:
        size = int(pot * random.uniform(0.5, 1.2))
        return ('raise', min(player.chips, max(size, call_amt)))
    if call_amt <= pot * 0.25:
        return ('call', call_amt)
    return ('fold', 0)


# ── Strategy 4 ── POT-ODDS / GTO-LITE ───────────────────────
def s_pot_odds(player, state):
    """
    Calculates pot-odds breakeven and compares to estimated equity.
    Raises for value when equity greatly exceeds pot odds; occasional
    small bluff-raises to stay unexploitable.
    """
    hole      = player.hole
    community = state.community
    equity    = equity_estimate(hole, community)
    call_amt  = max(0, state.current_bet - player.bet_round)
    pot       = state.pot

    if call_amt == 0:
        if equity >= 0.55:
            return ('raise', min(player.chips, max(1, int(pot * 0.60))))
        return ('call', 0)   # check

    pot_odds = call_amt / (pot + call_amt)

    if equity > pot_odds + 0.12:
        size = min(player.chips, int(pot * 0.80))
        if size > call_amt * 1.5:
            return ('raise', size)
        return ('call', call_amt)
    if equity > pot_odds:
        return ('call', call_amt)
    # Fold, with small bluff frequency
    if random.random() < 0.07:
        return ('raise', min(player.chips, pot))
    return ('fold', 0)


# ── Strategy 5 ── POSITION-AWARE ────────────────────────────
def s_position(player, state):
    """
    Leverages table position heavily.
    Late position → wide steal range and overbet; early position → tight.
    Uses position equity premium on all streets.
    """
    hole      = player.hole
    community = state.community
    equity    = equity_estimate(hole, community)
    call_amt  = max(0, state.current_bet - player.bet_round)
    pot       = state.pot
    active    = state.active
    n_active  = len(active)

    # Relative position: 0=early, 1=late
    try:
        my_idx = active.index(player)
        pos = my_idx / max(1, n_active - 1)
    except ValueError:
        pos = 0.5

    late = pos >= 0.6

    if state.street == 'preflop':
        tier = preflop_tier(hole)
        if tier == 'strong':
            mult = 2.2 if late else 1.5
            return ('raise', min(player.chips, int(pot * mult)))
        if tier == 'medium':
            if late:
                return ('raise', min(player.chips, int(pot * 1.6)))
            if pos > 0.3 and call_amt <= pot * 0.18:
                return ('call', call_amt)
            return ('fold', 0)
        # Weak hand
        if late and call_amt <= pot * 0.12:
            if random.random() < 0.40:   # steal attempt
                return ('raise', min(player.chips, int(pot * 2.5)))
        return ('fold', 0)

    eff_eq = equity + 0.10 * pos   # position bonus

    if eff_eq >= 0.60:
        mult = 0.85 if late else 0.60
        bet = max(call_amt, min(player.chips, int(pot * mult)))
        return ('raise', bet)
    if eff_eq >= 0.40:
        if call_amt <= pot * 0.30:
            return ('call', call_amt)
        if late and call_amt == 0:
            return ('raise', min(player.chips, int(pot * 0.5)))
        return ('fold', 0)
    if call_amt == 0:
        return ('call', 0)
    return ('fold', 0)


# ── Strategy 6 ── EXPLOITATIVE / ADAPTIVE ───────────────────
def s_exploitative(player, state):
    """
    Exploitative: reads the table.
    Counts all-in maniacs → loosens calling range vs. them.
    Identifies weak/tight opponents (few all-ins) → value bets large.
    """
    hole      = player.hole
    community = state.community
    equity    = equity_estimate(hole, community)
    call_amt  = max(0, state.current_bet - player.bet_round)
    pot       = state.pot
    active    = state.active

    allin_frac = sum(1 for p in active if p.all_in) / max(1, len(active))
    # Against maniacs, call wider; against rocks, tighten up a bit
    if allin_frac > 0.20:
        call_thresh = 0.33
        value_mult  = 1.2
    else:
        call_thresh = 0.44
        value_mult  = 0.80

    if state.street == 'preflop':
        tier = preflop_tier(hole)
        if tier == 'strong':
            return ('raise', min(player.chips, int(pot * 2.6)))
        if tier == 'medium':
            if call_amt <= pot * 0.25 or equity >= call_thresh:
                return ('call', call_amt)
            return ('fold', 0)
        if call_amt == 0:
            return ('call', 0)
        if equity >= call_thresh - 0.05 and call_amt <= pot * 0.18:
            return ('call', call_amt)
        return ('fold', 0)

    if equity >= 0.65:
        size = min(player.chips, int(pot * value_mult * random.uniform(0.9, 1.4)))
        return ('raise', max(call_amt, size))
    if equity >= call_thresh:
        if call_amt == 0:
            return ('raise', min(player.chips, int(pot * 0.50)))
        return ('call', call_amt)
    if call_amt == 0:
        return ('call', 0)
    return ('fold', 0)


# ─────────────────────────────────────────────────────────────
# STRATEGY REGISTRY
# ─────────────────────────────────────────────────────────────

STRATEGY_NAME = {
    1: "AlwaysAllIn  (SIMPLE)",
    2: "TightAggressive     ",
    3: "LooseAggressive     ",
    4: "PotOdds/GTO-Lite    ",
    5: "PositionAware       ",
    6: "Exploitative/Adaptive",
}

STRATEGY_FN = {
    1: s_allin,
    2: s_tag,
    3: s_lag,
    4: s_pot_odds,
    5: s_position,
    6: s_exploitative,
}

# ─────────────────────────────────────────────────────────────
# BETTING ROUND ENGINE
# ─────────────────────────────────────────────────────────────

def run_betting_round(players, pot, current_bet, community, dealer_pos, street):
    """Execute one betting street. Returns (pot, current_bet)."""
    n = len(players)

    # Reset per-street commitment
    for p in players:
        p.bet_round = 0

    # Seat order: left of dealer
    order = []
    for i in range(1, n + 1):
        p = players[(dealer_pos + i) % n]
        if not p.folded and not p.all_in and p.chips > 0:
            order.append(p)

    if len(order) == 0:
        return pot, current_bet

    queue     = list(order)
    acted_since_raise = set()
    iters     = 0

    while queue and iters < 80:
        iters += 1
        player = queue.pop(0)

        if player.folded or player.chips == 0:
            player.all_in = player.chips == 0
            continue

        state  = GameState(players, community, pot, current_bet, dealer_pos, street)
        action, amount = player.strategy_fn(player, state)

        call_needed = max(0, current_bet - player.bet_round)

        if action == 'fold':
            player.folded = True

        elif action == 'call':
            actual = min(call_needed, player.chips)
            player.chips    -= actual
            player.bet_round += actual
            pot             += actual
            if player.chips == 0:
                player.all_in = True

        elif action == 'raise':
            # amount = chips player wants to put in this action
            total_in = max(min(amount, player.chips), min(call_needed, player.chips))
            player.chips    -= total_in
            pot             += total_in
            new_committed    = player.bet_round + total_in
            player.bet_round = new_committed

            if player.chips == 0:
                player.all_in = True

            if new_committed > current_bet:
                current_bet = new_committed
                # Re-queue all other live players who haven't acted since this raise
                for other in order:
                    if (other is not player
                            and not other.folded
                            and not other.all_in
                            and other.chips > 0
                            and other not in queue):
                        queue.append(other)

        # Stop if only one non-folded player left
        alive = [p for p in players if not p.folded]
        if len(alive) <= 1:
            break

    return pot, current_bet


# ─────────────────────────────────────────────────────────────
# PLAY ONE COMPLETE HAND
# ─────────────────────────────────────────────────────────────

SB = 10
BB = 20

def play_hand(players, dealer_pos):
    """Play one hand; return new dealer_pos."""
    n     = len(players)
    deck  = Deck()
    pot   = 0
    community = []

    for p in players:
        p.reset_for_hand()

    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return (dealer_pos + 1) % n

    # ── post blinds ────────────────────────────
    def next_with_chips(start):
        idx = (start + 1) % n
        for _ in range(n):
            if players[idx].chips > 0:
                return idx
            idx = (idx + 1) % n
        return -1

    sb_idx = next_with_chips(dealer_pos)
    bb_idx = next_with_chips(sb_idx)
    if sb_idx == bb_idx or bb_idx == -1:
        return (dealer_pos + 1) % n

    sb_p, bb_p = players[sb_idx], players[bb_idx]

    sb_amt = min(SB, sb_p.chips);  sb_p.chips -= sb_amt;  pot += sb_amt;  sb_p.bet_round = sb_amt
    bb_amt = min(BB, bb_p.chips);  bb_p.chips -= bb_amt;  pot += bb_amt;  bb_p.bet_round = bb_amt
    current_bet = BB

    # ── deal hole cards ─────────────────────────
    for p in alive:
        p.hole = deck.deal(2)

    def live():
        return [p for p in players if not p.folded]

    # Pre-flop
    pot, current_bet = run_betting_round(players, pot, current_bet, community, dealer_pos, 'preflop')
    if len(live()) <= 1:
        live()[0].chips += pot if live() else 0
        return (dealer_pos + 1) % n

    # Flop
    community += deck.deal(3)
    pot, current_bet = run_betting_round(players, pot, 0, community, dealer_pos, 'flop')
    if len(live()) <= 1:
        if live(): live()[0].chips += pot
        return (dealer_pos + 1) % n

    # Turn
    community += deck.deal(1)
    pot, current_bet = run_betting_round(players, pot, 0, community, dealer_pos, 'turn')
    if len(live()) <= 1:
        if live(): live()[0].chips += pot
        return (dealer_pos + 1) % n

    # River
    community += deck.deal(1)
    pot, current_bet = run_betting_round(players, pot, 0, community, dealer_pos, 'river')

    survivors = live()
    if len(survivors) == 1:
        survivors[0].chips += pot
    elif survivors:
        scored = sorted(
            [(best_hand(p.hole + community), p) for p in survivors],
            key=lambda x: x[0], reverse=True
        )
        top_score = scored[0][0]
        winners   = [p for sc, p in scored if sc == top_score]
        share     = pot // len(winners)
        for w in winners:
            w.chips += share

    return (dealer_pos + 1) % n


# ─────────────────────────────────────────────────────────────
# TOURNAMENT  (play until one player holds all chips)
# ─────────────────────────────────────────────────────────────

def run_tournament(starting_chips=1500, max_hands=8000):
    players = [Player(pid, starting_chips, STRATEGY_FN[pid]) for pid in range(1, 7)]
    dealer  = 0
    for _ in range(max_hands):
        if sum(1 for p in players if p.chips > 0) <= 1:
            break
        dealer = play_hand(players, dealer)
    winner = max(players, key=lambda p: p.chips)
    return winner.pid


# ─────────────────────────────────────────────────────────────
# ASCII HISTOGRAM
# ─────────────────────────────────────────────────────────────

BAR_CHARS = "▏▎▍▌▋▊▉█"

def ascii_bar(val, max_val, width=44):
    filled = int(val / max_val * width)
    part   = int((val / max_val * width - filled) * 8)
    bar    = "█" * filled
    if part and filled < width:
        bar += BAR_CHARS[part]
    return bar

def print_histogram(results, n_sims):
    counts  = collections.Counter(results)
    max_cnt = max(counts.values()) if counts else 1

    border = "═" * 72
    print()
    print(border)
    print("     ★  WINNER WINNER CHICKEN DINNER  —  100-TOURNAMENT RESULTS  ★")
    print(border)
    print(f"  {'#':<3}  {'Strategy':<26} {'Wins':>4} {'Pct':>6}   Histogram")
    print("─" * 72)

    for pid in range(1, 7):
        wins = counts.get(pid, 0)
        pct  = wins / n_sims * 100
        bar  = ascii_bar(wins, max_cnt)
        tag  = "  ◄ THE MADLAD" if pid == 1 else ""
        name = STRATEGY_NAME[pid]
        print(f"  P{pid}  {name:<26} {wins:>4} {pct:>5.1f}%   {bar}{tag}")

    print("─" * 72)
    most_pid, most_wins = counts.most_common(1)[0]
    label = STRATEGY_NAME[most_pid].strip()
    print(f"  Total sims : {n_sims}")
    print(f"  CHAMPION   : Player {most_pid}  [{label}]  with {most_wins} wins")
    print(border)
    print()


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    random.seed(42)          # reproducible run; remove for fresh randomness
    N      = 100
    CHIPS  = 1500

    print(f"\n  Texas Hold'em Simulator  |  {N} tournaments  |  {CHIPS} chips/player")
    print("  Player 1 : SIMPLE ALL-IN    |    Players 2-6 : elaborate strategies")
    print()

    results = []
    for i in range(N):
        winner = run_tournament(starting_chips=CHIPS)
        results.append(winner)
        if (i + 1) % 20 == 0:
            print(f"  ... {i+1}/{N} done", flush=True)

    print_histogram(results, N)
