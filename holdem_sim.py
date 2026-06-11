"""
Texas Hold'em: 100 tournament simulations
Player 1 : YOLO (always all-in)
Players 2-6 : five elaborate strategy bots

Fast version: hand strength estimated via heuristic scoring, no per-decision
Monte Carlo, so 100 full tournaments complete in seconds.
"""

import random
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ---------------------------------------------------------------------------
# Hand evaluator  (returns a comparable tuple, higher = better)
# ---------------------------------------------------------------------------
def hand_rank(cards):
    best = None
    for combo in combinations(cards, 5):
        score = score_5(combo)
        if best is None or score > best:
            best = score
    return best

def score_5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0] - 5, -1)) or
                ranks == [14, 5, 4, 3, 2])
    if straight and ranks[0] == 14 and ranks[1] == 5:
        ranks = [5, 4, 3, 2, 1]
    cnt = Counter(ranks)
    counts = sorted(cnt.values(), reverse=True)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    if flush and straight: return (8, ranks)
    if counts[0] == 4:      return (7, groups)
    if counts[:2] == [3,2]: return (6, groups)
    if flush:               return (5, ranks)
    if straight:            return (4, ranks)
    if counts[0] == 3:      return (3, groups)
    if counts[:2] == [2,2]: return (2, groups)
    if counts[0] == 2:      return (1, groups)
    return (0, ranks)

# ---------------------------------------------------------------------------
# Fast hand-strength heuristic (0.0 – 1.0), no sampling
# ---------------------------------------------------------------------------
def fast_strength(hole, community):
    """
    Returns a float [0,1] estimating relative hand strength.
    Pre-flop: based on Chen formula approximation.
    Post-flop: based on best-hand category + kicker.
    """
    if not community:
        return _preflop_strength(hole)
    best = hand_rank(hole + community)
    # Normalize: category 0-8, sub-score by leading rank value
    cat = best[0]
    top = best[1][0] if best[1] else 2
    # Raw score: category weight + kicker nudge
    raw = cat * 14 + top
    return min(1.0, raw / (8 * 14 + 14))

def _preflop_strength(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pair = r1 == r2
    # Chen-ish: max rank score + pair bonus + suited bonus + connectedness
    score = hi / 2.0
    if pair:        score += max(5, score)
    if suited:      score += 2
    score += max(0, 4 - (hi - lo))  # connectedness
    return min(1.0, score / 26.0)

# ---------------------------------------------------------------------------
# Equity estimator used by analytical bots (light Monte Carlo, few iters)
# Only called once per street, not per action
# ---------------------------------------------------------------------------
def estimate_equity(hole, community, n_opponents, n_samples=40):
    known = set(map(tuple, hole + community))
    deck = [c for c in make_deck() if tuple(c) not in known]
    needed = 5 - len(community)
    wins = 0
    for _ in range(n_samples):
        sample = random.sample(deck, needed + 2 * n_opponents)
        board = community + list(sample[:needed])
        my_rank = hand_rank(hole + board)
        beat = all(
            hand_rank(list(sample[needed + i*2: needed + i*2 + 2]) + board) < my_rank
            for i in range(n_opponents)
        )
        if beat:
            wins += 1
    return wins / n_samples

# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

def strategy_yolo(hole, community, pot, to_call, my_chips,
                  n_opponents, stage, position, street_max, _equity_cache):
    """Always go all-in."""
    return ("raise", my_chips)


def strategy_tight_aggressive(hole, community, pot, to_call, my_chips,
                               n_opponents, stage, position, street_max, equity_cache):
    """TAG: premium hands only, bets big when ahead."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pair = r1 == r2

    if stage == "preflop":
        premium = hi >= 12 or pair or (hi >= 10 and lo >= 10)
        playable = hi >= 10 or (suited and hi >= 9) or pair
        if premium:
            return ("raise", min(my_chips, max(to_call * 3, int(pot * 0.75))))
        if playable and to_call < my_chips * 0.12:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = equity_cache[0]
    if prob > 0.68:
        return ("raise", min(my_chips, max(to_call, int(pot * 0.85))))
    if prob > 0.48 and to_call < my_chips * 0.25:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_loose_passive(hole, community, pot, to_call, my_chips,
                            n_opponents, stage, position, street_max, equity_cache):
    """Limp wide, call a lot, rarely raises."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    hi = max(r1, r2)

    if stage == "preflop":
        if hi >= 8 or abs(r1 - r2) <= 2:
            if to_call < my_chips * 0.15:
                return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = equity_cache[0]
    if prob > 0.55:
        if to_call == 0:
            return ("raise", min(my_chips, int(pot * 0.30)))
        if to_call < my_chips * 0.30:
            return ("call", to_call)
    elif prob > 0.32:
        if to_call < my_chips * 0.30:
            return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_positional_bluffer(hole, community, pot, to_call, my_chips,
                                  n_opponents, stage, position, street_max, equity_cache):
    """Late-position aggression + heads-up bluffs."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi = max(r1, r2)
    in_pos = position >= n_opponents

    if stage == "preflop":
        if hi >= 12 or r1 == r2:
            return ("raise", min(my_chips, max(to_call * 3, int(pot * 0.6))))
        if in_pos and (hi >= 9 or suited):
            return ("raise", min(my_chips, max(to_call * 2, int(pot * 0.4))))
        if to_call < my_chips * 0.08:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = equity_cache[0]
    bluff = in_pos and n_opponents == 1 and random.random() < 0.28

    if prob > 0.58 or bluff:
        bet = min(my_chips, int(pot * (0.9 if bluff else 0.72)))
        return ("raise", max(bet, to_call))
    if prob > 0.38 and to_call < my_chips * 0.20:
        return ("call", to_call)
    if to_call == 0:
        if in_pos and random.random() < 0.18:
            return ("raise", min(my_chips, int(pot * 0.28)))
        return ("check", 0)
    return ("fold", 0)


def strategy_pot_odds(hole, community, pot, to_call, my_chips,
                       n_opponents, stage, position, street_max, equity_cache):
    """Pure math: call/raise only when equity exceeds pot odds."""
    prob = equity_cache[0]

    if to_call == 0:
        if prob > 0.52:
            return ("raise", min(my_chips, int(pot * 0.65)))
        return ("check", 0)

    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0
    if prob > pot_odds + 0.06:
        if prob > 0.62:
            return ("raise", min(my_chips, max(to_call, int(pot * 0.80))))
        return ("call", to_call)
    return ("fold", 0)


def strategy_adaptive_gto(hole, community, pot, to_call, my_chips,
                            n_opponents, stage, position, street_max, equity_cache):
    """GTO-flavoured: position-weighted ranges, balanced bluff frequencies."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pair = r1 == r2

    if stage == "preflop":
        score = hi + lo * 0.5 + (2 if suited else 0) + (5 if pair else 0)
        threshold = 16 - position * 0.8
        if score >= threshold:
            return ("raise", min(my_chips, max(to_call * 3, int(pot * 0.55))))
        if to_call < my_chips * 0.06:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = equity_cache[0]
    rand = random.random()
    if prob > 0.74:
        return ("raise", min(my_chips, max(to_call, int(pot * 0.90))))
    if prob > 0.54:
        if rand < 0.68:
            return ("raise", min(my_chips, max(to_call, int(pot * 0.60))))
        return ("call", to_call)
    if prob > 0.34:
        if to_call == 0:
            if rand < 0.22:
                return ("raise", min(my_chips, int(pot * 0.42)))
            return ("check", 0)
        if to_call < my_chips * 0.18:
            return ("call", to_call)
    if to_call == 0:
        if rand < 0.13:
            return ("raise", min(my_chips, int(pot * 0.38)))
        return ("check", 0)
    return ("fold", 0)


STRATEGIES = [
    strategy_yolo,
    strategy_tight_aggressive,
    strategy_loose_passive,
    strategy_positional_bluffer,
    strategy_pot_odds,
    strategy_adaptive_gto,
]

STRATEGY_NAMES = [
    "YOLO (All-In)",
    "Tight-Aggressive",
    "Loose-Passive",
    "Positional Bluffer",
    "Pot-Odds Calculator",
    "Adaptive GTO",
]

# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------
STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

def run_hand(players, dealer_idx):
    active = [p for p in players if p["chips"] > 0]
    n = len(active)
    if n < 2:
        return players

    deck = make_deck()
    random.shuffle(deck)

    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    def post(idx, amount):
        actual = min(active[idx]["chips"], amount)
        active[idx]["chips"] -= actual
        return actual

    sb_paid = post(sb_idx, SMALL_BLIND)
    bb_paid = post(bb_idx, BIG_BLIND)

    hole_cards = [[deck.pop(), deck.pop()] for _ in range(n)]

    pot = sb_paid + bb_paid
    folded = [False] * n
    community = []

    # Equity cache per player per street: computed once at start of street
    equity_caches = [[0.5] for _ in range(n)]

    def refresh_equity(stage):
        if stage == "preflop":
            for i in range(n):
                equity_caches[i][0] = _preflop_strength(hole_cards[i])
        else:
            opp = sum(1 for j in range(n) if not folded[j]) - 1
            opp = max(1, opp)
            for i in range(n):
                if not folded[i]:
                    equity_caches[i][0] = estimate_equity(
                        hole_cards[i], community, opp, n_samples=30)

    def betting_round(stage, first_to_act):
        nonlocal pot
        refresh_equity(stage)

        cur_bets = [0] * n
        if stage == "preflop":
            cur_bets[sb_idx] = sb_paid
            cur_bets[bb_idx] = bb_paid
        street_max = max(cur_bets)

        order = [(first_to_act + i) % n for i in range(n)]
        acted = set()
        idx_ptr = 0
        max_iters = n * 6

        for _ in range(max_iters):
            idx = order[idx_ptr % len(order)]
            idx_ptr += 1

            still_in = [j for j in range(n) if not folded[j]]
            if len(still_in) == 1:
                break

            if folded[idx] or active[idx]["chips"] == 0:
                acted.add(idx)
            else:
                to_call = max(0, street_max - cur_bets[idx])
                to_call = min(to_call, active[idx]["chips"])
                opp_left = sum(1 for j in range(n)
                               if not folded[j] and j != idx)

                action, amount = active[idx]["strategy"](
                    hole_cards[idx], community[:],
                    pot, to_call, active[idx]["chips"],
                    opp_left, stage, idx, street_max,
                    equity_caches[idx]
                )

                if action == "fold":
                    folded[idx] = True
                    acted.add(idx)
                elif action == "check":
                    acted.add(idx)
                elif action == "call":
                    paid = min(to_call, active[idx]["chips"])
                    active[idx]["chips"] -= paid
                    cur_bets[idx] += paid
                    pot += paid
                    acted.add(idx)
                elif action == "raise":
                    paid = min(amount, active[idx]["chips"])
                    active[idx]["chips"] -= paid
                    cur_bets[idx] += paid
                    pot += paid
                    if cur_bets[idx] > street_max:
                        street_max = cur_bets[idx]
                        acted = {idx}
                    acted.add(idx)

            in_play = [j for j in range(n)
                       if not folded[j] and active[j]["chips"] > 0]
            all_acted = all(j in acted or folded[j] or active[j]["chips"] == 0
                            for j in range(n))
            bets_equal = all(cur_bets[j] == street_max for j in in_play)
            if all_acted and bets_equal:
                break

        return [j for j in range(n) if not folded[j]]

    def award(winner_idx):
        active[winner_idx]["chips"] += pot

    # Preflop
    survivors = betting_round("preflop", (bb_idx + 1) % n)
    if len(survivors) == 1:
        award(survivors[0]); return players

    community += [deck.pop(), deck.pop(), deck.pop()]
    survivors = betting_round("flop", sb_idx % n)
    if len(survivors) == 1:
        award(survivors[0]); return players

    community.append(deck.pop())
    survivors = betting_round("turn", sb_idx % n)
    if len(survivors) == 1:
        award(survivors[0]); return players

    community.append(deck.pop())
    survivors = betting_round("river", sb_idx % n)
    if len(survivors) == 1:
        award(survivors[0]); return players

    # Showdown
    ranked = [(hand_rank(hole_cards[i] + community), i) for i in survivors]
    best   = max(r for r, _ in ranked)
    winners = [i for r, i in ranked if r == best]
    share  = pot // len(winners)
    rem    = pot % len(winners)
    for w in winners:
        active[w]["chips"] += share
    active[winners[0]]["chips"] += rem

    return players


def run_tournament():
    players = [
        {"id": i + 1, "chips": STARTING_CHIPS, "strategy": STRATEGIES[i]}
        for i in range(6)
    ]
    dealer   = 0
    hand_num = 0

    while sum(1 for p in players if p["chips"] > 0) > 1 and hand_num < 3000:
        live = [p for p in players if p["chips"] > 0]
        dealer = dealer % len(live)
        players = run_hand(players, dealer)
        dealer  = (dealer + 1) % max(1, sum(1 for p in players if p["chips"] > 0))
        hand_num += 1

    survivors = [p for p in players if p["chips"] > 0]
    if not survivors:
        return random.randint(1, 6)
    return max(survivors, key=lambda p: p["chips"])["id"]


# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------
N_SIMS = 100
print(f"Running {N_SIMS} Texas Hold'em tournament simulations...")
print("Player 1: YOLO (always all-in)")
print("Players 2-6: elaborate strategy bots\n")

win_counts = Counter()
for sim in range(N_SIMS):
    if (sim + 1) % 10 == 0:
        print(f"  sim {sim+1}/{N_SIMS}...")
    winner_id = run_tournament()
    win_counts[winner_id] += 1

# ---------------------------------------------------------------------------
# Histogram
# ---------------------------------------------------------------------------
BAR = 42
max_w = max(win_counts.values()) if win_counts else 1

print("\n" + "=" * 70)
print("   TOURNAMENT RESULTS  —  100 Simulations")
print("   Last Player Standing  =  WINNER WINNER CHICKEN DINNER")
print("=" * 70)

for pid in range(1, 7):
    name  = STRATEGY_NAMES[pid - 1]
    wins  = win_counts.get(pid, 0)
    bar   = "█" * int(wins / max_w * BAR)
    tag   = "  ◄ YOLO" if pid == 1 else ""
    print(f"P{pid} {name:<24} |{bar:<{BAR}}| {wins:>3}{tag}")

print("=" * 70)
print(f"\nExpected wins (uniform): {N_SIMS/6:.1f} per player\n")

print("--- Win Rate ---")
yolo_wins = win_counts.get(1, 0)
for pid in range(1, 7):
    name  = STRATEGY_NAMES[pid - 1]
    wins  = win_counts.get(pid, 0)
    pct   = wins / N_SIMS * 100
    note  = ""
    if pid == 1:
        note = "  ← YOLO wins!" if wins > N_SIMS / 6 else "  ← HUMILIATED"
    print(f"  P{pid}  {name:<24}  {wins:>3}/{N_SIMS}  ({pct:5.1f}%){note}")

print("\nSuflair GPT status: ABSOLUTELY REKT by a Python script. 🃏")
