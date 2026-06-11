"""
Texas Hold'em Simulation: 6 players, 100 games.
Player 1 = "Maniac" (always all-in).
Players 2-6 = five elaborate strategies.
Outputs a winner histogram.
"""

import random
from collections import Counter
from itertools import combinations
from enum import IntEnum

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

SUITS = "♠♥♦♣"
RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for s in SUITS for r in RANKS]

def card_str(c):
    return c[0] + c[1]

# ---------------------------------------------------------------------------
# Hand evaluator — returns a comparable tuple (higher = better)
# ---------------------------------------------------------------------------

class HandRank(IntEnum):
    HIGH_CARD      = 1
    ONE_PAIR       = 2
    TWO_PAIR       = 3
    THREE_OF_A_KIND= 4
    STRAIGHT       = 5
    FLUSH          = 6
    FULL_HOUSE     = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9

def _rank_vals(cards):
    return sorted([RANK_VAL[c[0]] for c in cards], reverse=True)

def evaluate_best5(seven):
    """Return the best 5-card hand score from up to 7 cards."""
    best = None
    for five in combinations(seven, 5):
        score = score_5(five)
        if best is None or score > best:
            best = score
    return best

def score_5(cards):
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    # Straight detection (handle A-low)
    unique = sorted(set(vals))
    straight = False
    straight_high = 0
    if len(unique) == 5:
        if unique[-1] - unique[0] == 4:
            straight = True
            straight_high = unique[-1]
        elif unique == [2, 3, 4, 5, 14]:   # wheel
            straight = True
            straight_high = 5
    counts = Counter(vals)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda k: (counts[k], k), reverse=True)

    if straight and flush:
        return (HandRank.STRAIGHT_FLUSH, straight_high)
    if freq[0] == 4:
        quad = groups[0]; kicker = groups[1]
        return (HandRank.FOUR_OF_A_KIND, quad, kicker)
    if freq[:2] == [3, 2]:
        return (HandRank.FULL_HOUSE, groups[0], groups[1])
    if flush:
        return (HandRank.FLUSH, *vals)
    if straight:
        return (HandRank.STRAIGHT, straight_high)
    if freq[0] == 3:
        trip = groups[0]; kickers = sorted([g for g in groups if g != trip], reverse=True)
        return (HandRank.THREE_OF_A_KIND, trip, *kickers)
    if freq[:2] == [2, 2]:
        p1, p2 = groups[0], groups[1]
        kicker = groups[2]
        return (HandRank.TWO_PAIR, p1, p2, kicker)
    if freq[0] == 2:
        pair = groups[0]; kickers = sorted([g for g in groups if g != pair], reverse=True)
        return (HandRank.ONE_PAIR, pair, *kickers)
    return (HandRank.HIGH_CARD, *vals)

# ---------------------------------------------------------------------------
# Pot-odds / hand-strength helpers
# ---------------------------------------------------------------------------

def hand_strength_estimate(hole, community, samples=200):
    """Monte-Carlo hand strength: fraction of random opponent hands we beat."""
    deck = [c for c in make_deck() if c not in hole and c not in community]
    needed = 5 - len(community)
    wins = ties = total = 0
    for _ in range(samples):
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        opp_hole = deck[needed:needed+2]
        my_score  = evaluate_best5(list(hole) + board)
        opp_score = evaluate_best5(list(opp_hole) + board)
        if my_score > opp_score:
            wins += 1
        elif my_score == opp_score:
            ties += 1
        total += 1
    return (wins + ties * 0.5) / total if total else 0.5

def pot_odds(call_amount, pot):
    """Fraction of pot we must contribute to call."""
    if call_amount == 0:
        return 0.0
    return call_amount / (pot + call_amount)

# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

SMALL_BLIND = 50
BIG_BLIND   = 100

class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid        = pid
        self.chips      = chips
        self.strategy   = strategy_fn
        self.hole       = []
        self.folded     = False
        self.all_in     = False
        self.bet_this_round = 0

    def reset_for_hand(self):
        self.hole   = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def is_active(self):
        return not self.folded and not self.all_in and self.chips > 0

    def __repr__(self):
        return f"P{self.pid}(${self.chips})"

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# ---- Strategy 0: Maniac — always shove all-in ----
def strategy_maniac(pid, hole, community, pot, to_call, my_chips, active_players, street):
    return ("raise", my_chips)   # all-in every time

# ---- Strategy 1: Tight-Aggressive (TAG) ----
# Plays premium hands hard, folds junk, adjusts to pot odds.
def strategy_tag(pid, hole, community, pot, to_call, my_chips, active_players, street):
    hs = hand_strength_estimate(hole, community, samples=150)
    po = pot_odds(to_call, pot)
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    high_pair = r1 == r2 and r1 >= 10          # TT+
    premium   = (r1 >= 13 and r2 >= 10) or (r1 >= 12 and r2 >= 12)   # AK, AQ, KK+
    if street == "preflop":
        if high_pair or premium:
            bet = min(my_chips, max(pot * 3, to_call * 3, BIG_BLIND * 4))
            return ("raise", int(bet))
        if hs > 0.60 or (suited and min(r1,r2) >= 9):
            if to_call <= my_chips * 0.12:
                return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    # post-flop
    if hs > 0.80:
        bet = min(my_chips, int(pot * 0.75))
        return ("raise", max(bet, to_call + BIG_BLIND))
    if hs > 0.60 and hs > po + 0.10:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ---- Strategy 2: Loose-Passive (Calling Station) ----
# Calls almost anything, rarely raises, hopes for miracle draws.
def strategy_calling_station(pid, hole, community, pot, to_call, my_chips, active_players, street):
    hs = hand_strength_estimate(hole, community, samples=100)
    po = pot_odds(to_call, pot)
    # call if pot odds are anywhere near positive, or just check
    if to_call == 0:
        return ("check", 0)
    if to_call <= my_chips * 0.35:
        return ("call", to_call)
    if hs > 0.75:
        return ("call", to_call)
    return ("fold", 0)

# ---- Strategy 3: GTO-Lite (balanced mixed strategy) ----
# Approximates game-theory-optimal play using hand buckets and randomized
# bluff frequencies.  Bets polarised: either strong hands or pure bluffs.
def strategy_gto_lite(pid, hole, community, pot, to_call, my_chips, active_players, street):
    hs = hand_strength_estimate(hole, community, samples=150)
    po = pot_odds(to_call, pot)
    n_opponents = max(1, active_players - 1)
    # Bluff frequency inversely proportional to opponents (fewer = bluff more)
    bluff_freq = max(0.10, 0.33 / n_opponents)
    is_bluff = random.random() < bluff_freq
    if street == "preflop":
        r1, r2 = sorted([RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]], reverse=True)
        # Value range: strong hands
        if hs > 0.72 or (r1 >= 12 and r2 >= 10):
            size = min(my_chips, max(to_call * 3, pot // 2, BIG_BLIND * 3))
            return ("raise", int(size))
        # Bluff 3-bet with suited connectors
        if is_bluff and r1 - r2 <= 1 and hole[0][1] == hole[1][1] and to_call < my_chips * 0.08:
            size = min(my_chips, max(to_call * 3, BIG_BLIND * 4))
            return ("raise", int(size))
        if hs > po + 0.05 and to_call <= my_chips * 0.10:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    # Post-flop: value bet 2/3 pot with value range, bluff 1/3 pot
    if hs > 0.78:
        size = min(my_chips, int(pot * 0.67))
        return ("raise", max(size, to_call + BIG_BLIND))
    if is_bluff and to_call == 0:
        bluff_size = min(my_chips, int(pot * 0.33))
        return ("raise", max(bluff_size, BIG_BLIND))
    if hs > po + 0.08:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ---- Strategy 4: Positional Exploiter ----
# Adjusts aggression based on position (index in active player list) and
# exploits perceived player tendencies via bet sizing tells.
def strategy_positional(pid, hole, community, pot, to_call, my_chips, active_players, street):
    hs = hand_strength_estimate(hole, community, samples=150)
    po = pot_odds(to_call, pot)
    # Approximate position: higher pid ~ later position at table
    position_score = (pid % 6) / 5.0   # 0=early, 1=late
    # Later position allows wider opening range
    open_threshold = 0.65 - position_score * 0.15   # 0.50 in late position
    cont_threshold = 0.55 - position_score * 0.10
    if street == "preflop":
        if hs > open_threshold:
            # Size based on position: bigger in early, smaller in late
            multiplier = 4 - position_score * 1.5
            size = min(my_chips, int(BIG_BLIND * multiplier + to_call))
            return ("raise", size)
        if hs > po + 0.05 and to_call <= my_chips * 0.08:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    if hs > cont_threshold:
        # Late position: smaller sizing (range advantage)
        frac = 0.75 - position_score * 0.25
        size = min(my_chips, int(pot * frac))
        return ("raise", max(size, to_call + BIG_BLIND))
    if hs > po:
        return ("call", to_call)
    # Late position: bluff with decent equity
    if position_score > 0.6 and to_call == 0 and hs > 0.35:
        return ("raise", min(my_chips, int(pot * 0.4)))
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ---- Strategy 5: Short-Stack Shover ----
# Once stack dips below 15 big blinds, shoves wide.  Otherwise plays solid poker.
def strategy_short_stack(pid, hole, community, pot, to_call, my_chips, active_players, street):
    hs = hand_strength_estimate(hole, community, samples=120)
    po = pot_odds(to_call, pot)
    short = my_chips < BIG_BLIND * 15
    if short:
        # Shove any hand with decent equity
        if hs > 0.42:
            return ("raise", my_chips)
        if to_call == 0:
            return ("check", 0)
        if to_call <= my_chips * 0.25:
            return ("call", to_call)
        return ("fold", 0)
    # Deep stack: conventional solid play
    if street == "preflop":
        r1, r2 = sorted([RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]], reverse=True)
        if r1 >= 10 and r2 >= 9:
            size = min(my_chips, BIG_BLIND * 4 + to_call)
            return ("raise", size)
        if hs > 0.62 and to_call <= my_chips * 0.10:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    if hs > 0.70:
        size = min(my_chips, int(pot * 0.65))
        return ("raise", max(size, to_call + BIG_BLIND))
    if hs > po + 0.05:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

STRATEGIES = [
    ("Maniac (All-In)",       strategy_maniac),
    ("Tight-Aggressive",      strategy_tag),
    ("Calling Station",       strategy_calling_station),
    ("GTO-Lite",              strategy_gto_lite),
    ("Positional Exploiter",  strategy_positional),
    ("Short-Stack Shover",    strategy_short_stack),
]

# ---------------------------------------------------------------------------
# Betting round engine
# ---------------------------------------------------------------------------

def betting_round(players, pot, street, dealer_offset=0):
    """Run one street of betting. Returns updated pot."""
    active = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
    if len(active) <= 1:
        return pot

    # Current highest bet this street across all players
    current_bet = max(p.bet_this_round for p in players)

    # Track who has acted since the last raise
    acted = set()
    order = active[:]
    idx = 0
    max_iter = len(players) * 4   # safety valve
    iters = 0

    while iters < max_iter:
        iters += 1
        alive = [p for p in order if not p.folded and not p.all_in and p.chips > 0]
        if not alive:
            break
        # Find next player who hasn't acted OR needs to react to a raise
        player = order[idx % len(order)]
        idx += 1
        if player.folded or player.all_in or player.chips <= 0:
            continue
        to_call = max(0, current_bet - player.bet_this_round)
        community = []   # community is managed outside; pass empty for strategy sig

        action, amount = player.strategy(
            player.pid,
            player.hole,
            community,   # strategies get community from game_state; simplified here
            pot,
            min(to_call, player.chips),
            player.chips,
            len([p for p in players if not p.folded]),
            street,
        )

        if action == "fold":
            player.folded = True
            acted.add(player.pid)
        elif action == "check":
            if to_call > 0:
                # Can't check — must at least call; treat as fold
                player.folded = True
            acted.add(player.pid)
        elif action == "call":
            chips_in = min(player.chips, to_call)
            player.chips -= chips_in
            player.bet_this_round += chips_in
            pot += chips_in
            if player.chips == 0:
                player.all_in = True
            acted.add(player.pid)
        elif action == "raise":
            raise_to = min(player.chips, max(int(amount), to_call + BIG_BLIND))
            chips_in = raise_to
            player.chips -= chips_in
            player.bet_this_round += chips_in
            pot += chips_in
            if player.chips == 0:
                player.all_in = True
            new_bet = player.bet_this_round
            if new_bet > current_bet:
                current_bet = new_bet
                acted = {player.pid}   # everyone else needs to react
            else:
                acted.add(player.pid)

        # Check if all active players have acted at the current bet level
        still_active = [p for p in players
                        if not p.folded and not p.all_in and p.chips > 0
                        and p.pid not in acted]
        if not still_active:
            break

    return pot

# ---------------------------------------------------------------------------
# Full hand engine
# ---------------------------------------------------------------------------

def play_hand(players):
    """Play one hand, return (winner_pid, chips_won) or distribute to winners."""
    # Reset per-hand state
    for p in players:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    # Deal hole cards
    for i, p in enumerate(players):
        if p.chips > 0:
            p.hole = [deck[i*2], deck[i*2+1]]

    card_ptr = [len(players) * 2]

    def burn_deal(n):
        card_ptr[0] += 1   # burn
        cards = deck[card_ptr[0]:card_ptr[0]+n]
        card_ptr[0] += n
        return cards

    pot = 0
    alive = [p for p in players if p.chips > 0]

    # Post blinds
    if len(alive) >= 2:
        sb = alive[0]
        bb = alive[1]
        sb_post = min(sb.chips, SMALL_BLIND)
        bb_post = min(bb.chips, BIG_BLIND)
        sb.chips -= sb_post; sb.bet_this_round += sb_post; pot += sb_post
        bb.chips -= bb_post; bb.bet_this_round += bb_post; pot += bb_post
        if sb.chips == 0: sb.all_in = True
        if bb.chips == 0: bb.all_in = True

    community = []

    def do_street(street_name, community):
        for p in players:
            if not p.folded and not p.all_in:
                # Inject current community into strategy via closure trick:
                # we monkey-patch a wrapper so strategy sees real community
                pass
        # Monkey-patch all players' strategies to pass community
        originals = {}
        for p in players:
            originals[p.pid] = p.strategy
            comm = list(community)
            strat = p.strategy
            def make_wrapper(s, c):
                def wrapper(pid, hole, _comm, pot, to_call, chips, ap, street):
                    return s(pid, hole, c, pot, to_call, chips, ap, street)
                return wrapper
            p.strategy = make_wrapper(strat, comm)
        nonlocal pot
        pot = betting_round(players, pot, street_name)
        for p in players:
            p.strategy = originals[p.pid]
            p.bet_this_round = 0

    # Preflop
    do_street("preflop", community)

    # Check if hand is over
    still_in = [p for p in players if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
        return still_in[0].pid

    # Flop
    community.extend(burn_deal(3))
    do_street("flop", community)
    still_in = [p for p in players if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
        return still_in[0].pid

    # Turn
    community.extend(burn_deal(1))
    do_street("turn", community)
    still_in = [p for p in players if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
        return still_in[0].pid

    # River
    community.extend(burn_deal(1))
    do_street("river", community)
    still_in = [p for p in players if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
        return still_in[0].pid

    # Showdown
    if not still_in:
        return None
    scores = []
    for p in still_in:
        if p.hole:
            sc = evaluate_best5(p.hole + community)
            scores.append((sc, p))
    if not scores:
        return None
    scores.sort(key=lambda x: x[0], reverse=True)
    best_score = scores[0][0]
    winners = [p for sc, p in scores if sc == best_score]
    share = pot // len(winners)
    remainder = pot - share * len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += remainder   # give remainder to first winner
    return winners[0].pid

# ---------------------------------------------------------------------------
# Tournament engine
# ---------------------------------------------------------------------------

def run_tournament(starting_chips=10_000):
    """Run one tournament. Returns the pid of the last player standing."""
    players = [
        Player(i+1, starting_chips, STRATEGIES[i][1])
        for i in range(len(STRATEGIES))
    ]
    hand_count = 0
    max_hands = 2000   # prevent infinite loops

    while sum(1 for p in players if p.chips > 0) > 1 and hand_count < max_hands:
        active = [p for p in players if p.chips > 0]
        if len(active) < 2:
            break
        play_hand(active)
        # Eliminate broke players (chips <= 0 but handle rounding)
        for p in players:
            if p.chips < 0:
                p.chips = 0
        hand_count += 1

    survivors = [p for p in players if p.chips > 0]
    if not survivors:
        return None
    return max(survivors, key=lambda p: p.chips).pid

# ---------------------------------------------------------------------------
# Histogram printer
# ---------------------------------------------------------------------------

def print_histogram(win_counts, n_sims):
    print("\n" + "="*62)
    print("  🃏  TEXAS HOLD'EM — 100-TOURNAMENT WINNER HISTOGRAM  🃏")
    print("="*62)
    max_wins = max(win_counts.values()) if win_counts else 1
    bar_width = 40

    for i, (name, _) in enumerate(STRATEGIES):
        pid    = i + 1
        wins   = win_counts.get(pid, 0)
        bar_len = int(wins / max_wins * bar_width)
        bar    = "█" * bar_len
        pct    = wins / n_sims * 100
        label  = f"P{pid} {name[:24]}"
        marker = " ← MANIAC (all-in)" if pid == 1 else ""
        print(f"  {label:<30} {bar:<40} {wins:>3} ({pct:5.1f}%){marker}")

    print("="*62)
    top_pid = max(win_counts, key=win_counts.get)
    top_name = STRATEGIES[top_pid - 1][0]
    top_wins = win_counts[top_pid]
    print(f"\n  WINNER WINNER CHICKEN DINNER: P{top_pid} — {top_name}")
    print(f"  Dominated with {top_wins}/{n_sims} tournament victories.\n")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    N_SIMS         = 100
    STARTING_CHIPS = 10_000

    print(f"\nRunning {N_SIMS} Texas Hold'em tournaments…")
    print(f"  Starting chips per player: {STARTING_CHIPS:,}")
    print(f"  Blinds: {SMALL_BLIND}/{BIG_BLIND}\n")

    print("Players:")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  ← all-in every hand" if i == 0 else ""
        print(f"  P{i+1}: {name}{tag}")
    print()

    win_counts = Counter()
    for sim in range(1, N_SIMS + 1):
        winner_pid = run_tournament(STARTING_CHIPS)
        if winner_pid is not None:
            win_counts[winner_pid] += 1
        if sim % 10 == 0:
            print(f"  Completed {sim}/{N_SIMS} tournaments…")

    print_histogram(win_counts, N_SIMS)
