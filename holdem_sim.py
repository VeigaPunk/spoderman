"""
Texas Hold'em Poker Simulation
6 players, 100 tournaments, histogram of winners.
Player 1 = "YOLO" (always all-in)
Players 2-6 = 5 elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────────────────
# Card primitives
# ─────────────────────────────────────────────────────────
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}  # 2..14

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ─────────────────────────────────────────────────────────
# Hand evaluator  (returns (category, tiebreakers))
# category: 8=straight flush, 7=quads, 6=full house,
#           5=flush, 4=straight, 3=trips, 2=two-pair,
#           1=pair, 0=high card
# ─────────────────────────────────────────────────────────
def best_hand(cards):
    """Best 5-card hand from up to 7 cards."""
    best = (-1, [])
    for five in combinations(cards, 5):
        val = evaluate_five(five)
        if val > best:
            best = val
    return best

def evaluate_five(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5)
    # wheel straight A-2-3-4-5
    if set(ranks) == {14, 2, 3, 4, 5}:
        straight = True
        ranks = [5, 4, 3, 2, 1]

    counts = Counter(ranks)
    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    group_sizes = [g[1] for g in groups]
    group_ranks = [g[0] for g in groups]

    if straight and flush:
        return (8, ranks)
    if group_sizes[0] == 4:
        return (7, group_ranks)
    if group_sizes[:2] == [3, 2]:
        return (6, group_ranks)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if group_sizes[0] == 3:
        return (3, group_ranks)
    if group_sizes[:2] == [2, 2]:
        return (2, group_ranks)
    if group_sizes[0] == 2:
        return (1, group_ranks)
    return (0, ranks)

# ─────────────────────────────────────────────────────────
# Hand strength estimator (Monte Carlo, fast)
# ─────────────────────────────────────────────────────────
def estimate_hand_strength(hole, community, num_opponents, samples=50):
    """Win probability estimate via random sampling."""
    deck = [c for c in make_deck() if c not in hole and c not in community]
    wins = 0
    needed = 5 - len(community)
    for _ in range(samples):
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        my_hand = best_hand(list(hole) + board)
        beat_all = True
        off = needed
        for _ in range(num_opponents):
            opp = best_hand([deck[off], deck[off+1]] + board)
            off += 2
            if opp >= my_hand:
                beat_all = False
                break
        if beat_all:
            wins += 1
    return wins / samples

def pot_odds(call_amount, pot):
    if call_amount == 0:
        return 1.0
    return pot / (pot + call_amount)

def position_class(seat_index, num_active):
    third = num_active / 3
    if seat_index < third:
        return "early"
    elif seat_index < 2 * third:
        return "mid"
    return "late"

# ─────────────────────────────────────────────────────────
# Strategy 1 — YOLO (player 1)
# ─────────────────────────────────────────────────────────
def strategy_yolo(state):
    """If my_turn Then bet = All in Fi"""
    return ("raise", state["my_stack"])

# ─────────────────────────────────────────────────────────
# Hole-card tiering shared by strategies
# ─────────────────────────────────────────────────────────
PREMIUM_SUITED = {("A","K"),("A","Q"),("A","J"),("K","Q")}
PREMIUM_OFF = {("A","K"),("A","Q"),("K","Q"),("A","J")}

def _hole_tier(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    if r1 < r2:
        r1, r2 = r2, r1
    suited = hole[0][1] == hole[1][1]
    hi, lo = RANKS[r1-2], RANKS[r2-2]
    if hi == lo and hi in "AKQJT":
        return 1
    if suited and (hi, lo) in PREMIUM_SUITED:
        return 1
    if not suited and (hi, lo) in PREMIUM_OFF:
        return 1
    if hi == lo:
        return 2
    if suited and r1 >= 10:
        return 2
    if r1 >= 12 and r2 >= 10:
        return 2
    if suited and r1 - r2 <= 3:
        return 3
    return 4

# ─────────────────────────────────────────────────────────
# Strategy 2 — TAG (Tight-Aggressive)
# Premium hands only; bets and raises hard when strong.
# ─────────────────────────────────────────────────────────
def strategy_tag(state):
    hole, community = state["hole"], state["community"]
    call_amt, pot = state["call_amount"], state["pot"]
    stack, num_opp = state["my_stack"], state["active_opponents"]
    street = state["street"]

    tier = _hole_tier(hole)

    if street == "preflop":
        if tier == 1:
            raise_to = min(stack, max(call_amt * 3, pot // 2))
            return ("raise", raise_to)
        if tier == 2:
            if call_amt <= max(pot, state["big_blind"] * 3) * 0.35:
                return ("call", call_amt)
            return ("fold", 0)
        return ("fold", 0)
    else:
        strength = estimate_hand_strength(hole, community, num_opp)
        odds = pot_odds(call_amt, pot)
        if strength > 0.70:
            raise_to = min(stack, pot * 2 // 3)
            return ("raise", max(raise_to, call_amt))
        if strength > odds:
            return ("call", call_amt)
        return ("fold", 0)

# ─────────────────────────────────────────────────────────
# Strategy 3 — LAG (Loose-Aggressive)
# Plays wide range, applies constant pressure, bluffs.
# ─────────────────────────────────────────────────────────
def strategy_lag(state):
    hole, community = state["hole"], state["community"]
    call_amt, pot = state["call_amount"], state["pot"]
    stack, num_opp = state["my_stack"], state["active_opponents"]
    street, position = state["street"], state["position"]

    tier = _hole_tier(hole)

    if street == "preflop":
        playable = tier <= 3 or position == "late"
        if not playable:
            return ("fold", 0)
        if tier == 1:
            return ("raise", min(stack, pot + call_amt * 3))
        if position == "late" and call_amt <= state["big_blind"] * 4:
            return ("raise", min(stack, call_amt * 2 + pot // 4))
        if call_amt <= stack // 8:
            return ("call", call_amt)
        return ("fold", 0)
    else:
        strength = estimate_hand_strength(hole, community, num_opp)
        bluff = (street in ("flop","turn") and strength < 0.35 and
                 random.random() < 0.30 and position == "late")
        if bluff or strength > 0.55:
            raise_to = min(stack, pot * 3 // 4)
            return ("raise", max(raise_to, call_amt))
        odds = pot_odds(call_amt, pot)
        if strength > odds * 0.85:
            return ("call", call_amt)
        return ("fold", 0)

# ─────────────────────────────────────────────────────────
# Strategy 4 — GTO-Inspired (Mixed frequencies)
# Balances value bets and semi-bluffs based on equity.
# ─────────────────────────────────────────────────────────
def strategy_gto(state):
    hole, community = state["hole"], state["community"]
    call_amt, pot = state["call_amount"], state["pot"]
    stack, num_opp = state["my_stack"], state["active_opponents"]
    street = state["street"]

    tier = _hole_tier(hole)

    if street == "preflop":
        if tier <= 2:
            return ("raise", min(stack, call_amt * 3 + pot // 4))
        if tier == 3:
            if random.random() < 0.5 and call_amt <= state["big_blind"] * 3:
                return ("raise", min(stack, call_amt * 2))
            if call_amt <= stack // 10:
                return ("call", call_amt)
        return ("fold", 0)
    else:
        strength = estimate_hand_strength(hole, community, num_opp)
        if strength > 0.65:
            bet = min(stack, int(pot * 0.75))
            return ("raise", max(bet, call_amt))
        if strength > 0.30 and random.random() < 0.33:
            bet = min(stack, pot // 2)
            return ("raise", max(bet, call_amt))
        odds = pot_odds(call_amt, pot)
        if strength > odds:
            return ("call", call_amt)
        return ("fold", 0)

# ─────────────────────────────────────────────────────────
# Strategy 5 — ICM / Stack-aware (tournament survival)
# Tightens up as stack shrinks; shoves when desperate.
# ─────────────────────────────────────────────────────────
def strategy_icm(state):
    hole, community = state["hole"], state["community"]
    call_amt, pot = state["call_amount"], state["pot"]
    stack, num_opp = state["my_stack"], state["active_opponents"]
    street = state["street"]

    m_ratio = stack / max(state["big_blind"], 1)
    tier = _hole_tier(hole)

    if street == "preflop":
        if m_ratio < 10:  # desperate — shove or fold
            if tier <= 3 or (tier == 4 and random.random() < 0.2):
                return ("raise", stack)
            return ("fold", 0)
        if m_ratio < 20:  # medium — tighter
            if tier <= 2:
                return ("raise", min(stack, call_amt * 3))
            return ("fold", 0)
        if tier <= 2:
            return ("raise", min(stack, call_amt * 3))
        if tier == 3 and call_amt <= stack // 10:
            return ("call", call_amt)
        return ("fold", 0)
    else:
        strength = estimate_hand_strength(hole, community, num_opp)
        if m_ratio < 10 and strength > 0.40:
            return ("raise", stack)
        odds = pot_odds(call_amt, pot)
        if strength > 0.65:
            return ("raise", min(stack, pot * 2 // 3))
        if strength > odds:
            return ("call", call_amt)
        return ("fold", 0)

# ─────────────────────────────────────────────────────────
# Strategy 6 — Exploitative / Read-based
# Adjusts to board texture and table aggression.
# ─────────────────────────────────────────────────────────
def _board_texture(community):
    """Return (flush_possible, straight_possible, paired)."""
    if len(community) < 3:
        return False, False, False
    suits = [c[1] for c in community]
    ranks = [RANK_VAL[c[0]] for c in community]
    flush_possible = max(Counter(suits).values()) >= 3
    straight_possible = (max(ranks) - min(ranks)) <= 4 and len(set(ranks)) >= 3
    paired = len(ranks) != len(set(ranks))
    return flush_possible, straight_possible, paired

def strategy_exploitative(state):
    hole, community = state["hole"], state["community"]
    call_amt, pot = state["call_amount"], state["pot"]
    stack, num_opp = state["my_stack"], state["active_opponents"]
    street = state["street"]
    opp_aggression = state.get("opp_aggression", 0.5)

    tier = _hole_tier(hole)
    flush_draw, str_draw, paired_board = _board_texture(community)

    if street == "preflop":
        # vs aggressive table: tighten and trap
        threshold = 2 if opp_aggression > 0.6 else 3
        if tier <= threshold:
            return ("raise", min(stack, call_amt * 3))
        if tier == 3 and call_amt <= max(pot, state["big_blind"] * 3) * 0.25:
            return ("call", call_amt)
        return ("fold", 0)
    else:
        strength = estimate_hand_strength(hole, community, num_opp)
        danger = flush_draw or str_draw
        if danger:
            if strength > 0.70:
                return ("raise", min(stack, pot * 3 // 4))
            odds = pot_odds(call_amt, pot)
            if strength > odds:
                return ("call", call_amt)
            return ("fold", 0)
        if strength > 0.55 or (strength > 0.35 and random.random() < 0.25):
            raise_to = min(stack, pot * 2 // 3)
            return ("raise", max(raise_to, call_amt))
        odds = pot_odds(call_amt, pot)
        if strength > odds:
            return ("call", call_amt)
        return ("fold", 0)

# ─────────────────────────────────────────────────────────
# Strategies registry
# ─────────────────────────────────────────────────────────
STRATEGY_NAMES = {
    1: "YOLO (All-In Every Hand)",
    2: "TAG (Tight-Aggressive)",
    3: "LAG (Loose-Aggressive)",
    4: "GTO-Inspired (Balanced)",
    5: "ICM/Stack-Aware (Survival)",
    6: "Exploitative (Read-Based)",
}
STRATEGIES = {
    1: strategy_yolo,
    2: strategy_tag,
    3: strategy_lag,
    4: strategy_gto,
    5: strategy_icm,
    6: strategy_exploitative,
}

# ─────────────────────────────────────────────────────────
# Game engine
# ─────────────────────────────────────────────────────────
class Player:
    def __init__(self, pid, strategy_id, stack):
        self.pid = pid
        self.sid = strategy_id
        self.stack = stack
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.total_committed = 0  # for side pots
        self.total_aggression_acts = 0

def deal(deck, n):
    cards = deck[:n]
    del deck[:n]
    return cards

def run_betting_round(players, deck, community, street, big_blind, button_idx):
    """Single street betting. Money accrues in players' total_committed."""
    n = len(players)
    order = []
    idx = (button_idx + 1) % n
    for _ in range(n):
        if not players[idx].folded and players[idx].stack > 0:
            order.append(idx)
        idx = (idx + 1) % n

    if len(order) <= 1:
        return

    for p in players:
        p.bet_this_round = 0

    current_bet = 0

    def commit(p, amount):
        actual = min(amount, p.stack)
        p.stack -= actual
        p.bet_this_round += actual
        p.total_committed += actual
        return actual

    if street == "preflop":
        sb_idx, bb_idx = order[0], order[1] if len(order) > 1 else order[0]
        commit(players[sb_idx], big_blind // 2)
        commit(players[bb_idx], big_blind)
        current_bet = big_blind
        order = order[2:] + order[:2]  # UTG first, BB last

    acted = set()
    safety = 0
    while safety < 200:
        safety += 1
        moved = False
        for idx in order:
            p = players[idx]
            if p.folded or p.stack == 0:
                continue
            if idx in acted and p.bet_this_round >= current_bet:
                continue
            call_amt = min(max(0, current_bet - p.bet_this_round), p.stack)
            pot_now = sum(x.total_committed for x in players)
            active_opps = sum(1 for x in players if not x.folded and x.pid != p.pid)
            opp_agg = sum(x.total_aggression_acts for x in players if not x.folded and x.pid != p.pid)
            opp_agg_rate = opp_agg / max(1, active_opps * 3)

            state = {
                "hole": p.hole,
                "community": community,
                "call_amount": call_amt,
                "pot": max(pot_now, 1),
                "my_stack": p.stack,
                "active_opponents": active_opps,
                "street": street,
                "position": position_class(order.index(idx), len(order)),
                "big_blind": big_blind,
                "opp_aggression": min(1.0, opp_agg_rate),
            }

            action, amount = STRATEGIES[p.sid](state)
            acted.add(idx)
            moved = True

            if action == "fold":
                if call_amt == 0:
                    # free check instead of folding when nothing to call
                    continue
                p.folded = True
            elif action == "call":
                commit(p, call_amt)
            elif action == "raise":
                # amount = extra chips beyond the call
                extra = max(0, int(amount))
                min_raise = big_blind
                if extra < min_raise and p.stack > call_amt + min_raise:
                    extra = min_raise
                commit(p, call_amt + extra)
                if p.bet_this_round > current_bet:
                    current_bet = p.bet_this_round
                    for other in order:
                        if other != idx:
                            acted.discard(other)
                p.total_aggression_acts += 1

        if not moved:
            break
        still_in = [i for i in order if not players[i].folded and players[i].stack > 0]
        if all(players[i].bet_this_round >= current_bet or players[i].stack == 0
               for i in still_in) and all(i in acted for i in still_in):
            break

def award_pots(players, community):
    """Side-pot-aware showdown using total_committed."""
    contenders = [p for p in players if not p.folded]
    total_pot = sum(p.total_committed for p in players)
    if total_pot == 0:
        return
    if len(contenders) == 1:
        contenders[0].stack += total_pot
        for p in players:
            p.total_committed = 0
        return

    scores = {p.pid: best_hand(list(p.hole) + community) for p in contenders}

    # Build side pots by commitment levels
    commits = sorted(set(p.total_committed for p in players if p.total_committed > 0))
    prev = 0
    for level in commits:
        pot_chunk = 0
        for p in players:
            contrib = min(p.total_committed, level) - min(p.total_committed, prev)
            pot_chunk += contrib
        eligible = [p for p in contenders if p.total_committed >= level]
        if not eligible:
            # money from folders below any contender level → goes to best overall
            eligible = contenders
        best = max(scores[p.pid] for p in eligible)
        winners = [p for p in eligible if scores[p.pid] == best]
        share = pot_chunk // len(winners)
        rem = pot_chunk % len(winners)
        for i, w in enumerate(winners):
            w.stack += share + (rem if i == 0 else 0)
        prev = level
    for p in players:
        p.total_committed = 0

def play_hand(players, button_idx, big_blind):
    deck = make_deck()
    random.shuffle(deck)

    alive = [p for p in players if p.stack > 0]
    if len(alive) < 2:
        return button_idx

    for p in players:
        p.folded = p.stack == 0
        p.hole = []
        p.bet_this_round = 0
        p.total_committed = 0

    for p in alive:
        p.hole = deal(deck, 2)

    community = []
    for street, n_comm in [("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)]:
        if street != "preflop":
            community += deal(deck, n_comm)
        run_betting_round(players, deck, community, street, big_blind, button_idx)
        still_in = [p for p in players if not p.folded]
        if len(still_in) <= 1:
            break
        # everyone all-in? skip to runout
        can_act = [p for p in still_in if p.stack > 0]
        if len(can_act) <= 1 and street != "river":
            while len(community) < 5:
                community += deal(deck, 1)
            break

    award_pots(players, community)

    # Advance button to next living player
    n = len(players)
    cur = button_idx
    for _ in range(n):
        cur = (cur + 1) % n
        if players[cur].stack > 0:
            return cur
    return button_idx

def run_tournament(starting_chips=1000, big_blind=20):
    players = [Player(i+1, i+1, starting_chips) for i in range(6)]
    button_idx = 0
    hand_count = 0
    max_hands = 1000

    while True:
        alive = [p for p in players if p.stack > 0]
        if len(alive) == 1:
            return alive[0].pid
        if len(alive) == 0:
            return random.randint(1, 6)
        if hand_count >= max_hands:
            return max(alive, key=lambda p: p.stack).pid
        button_idx = play_hand(players, button_idx, big_blind)
        hand_count += 1
        if hand_count % 25 == 0:
            big_blind = int(big_blind * 1.5)  # escalating blinds

# ─────────────────────────────────────────────────────────
# Run simulations + histogram
# ─────────────────────────────────────────────────────────
def run_simulations(n=100, starting_chips=1000):
    print(f"Running {n} Texas Hold'em tournaments (6 players, {starting_chips} chips each)...\n")
    wins = Counter()
    for i in range(n):
        winner = run_tournament(starting_chips=starting_chips)
        wins[winner] += 1
        if (i+1) % 10 == 0:
            print(f"  {i+1}/{n} done — current tally: " +
                  " ".join(f"P{p}:{wins.get(p,0)}" for p in range(1,7)))
    return wins

def print_histogram(wins, n_sims):
    print("\n" + "="*70)
    print("  TEXAS HOLD'EM — TOURNAMENT WINNER HISTOGRAM (100 sims)")
    print("="*70)
    max_wins = max(wins.values()) if wins else 1
    bar_width = 30
    for pid in range(1, 7):
        w = wins.get(pid, 0)
        bar = "█" * max(1 if w else 0, round(bar_width * w / max_wins))
        pct = w / n_sims * 100
        print(f"  P{pid} {STRATEGY_NAMES[pid]:<30} {w:>3} |{bar:<30}| {pct:.0f}%")
    print("="*70)
    best_pid = max(range(1, 7), key=lambda p: wins.get(p, 0))
    print(f"\n  WINNER WINNER CHICKEN DINNER: Player {best_pid} — {STRATEGY_NAMES[best_pid]}")
    print(f"  ({wins[best_pid]}/{n_sims} tournament wins)\n")

if __name__ == "__main__":
    random.seed(42)
    N = 100
    wins = run_simulations(n=N)
    print_histogram(wins, N)
