"""
Texas Hold'em: 100 tournament simulations
Player 1 : YOLO (always all-in)
Players 2-6 : five elaborate strategy bots
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

def card_str(c):
    return c[0] + c[1]

# ---------------------------------------------------------------------------
# Hand evaluator  (returns a comparable tuple, higher = better)
# ---------------------------------------------------------------------------
def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards."""
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
        ranks = [5, 4, 3, 2, 1]  # wheel
    counts = sorted(Counter(ranks).values(), reverse=True)
    groups = sorted(Counter(ranks).keys(),
                    key=lambda r: (Counter(ranks)[r], r), reverse=True)
    if flush and straight:
        return (8, ranks)
    if counts[0] == 4:
        return (7, groups)
    if counts[:2] == [3, 2]:
        return (6, groups)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts[0] == 3:
        return (3, groups)
    if counts[:2] == [2, 2]:
        return (2, groups)
    if counts[0] == 2:
        return (1, groups)
    return (0, ranks)

# ---------------------------------------------------------------------------
# Simple hand-strength estimator used by bots (Monte Carlo, few iters)
# ---------------------------------------------------------------------------
def estimate_win_prob(hole, community, n_opponents, n_samples=120):
    known = set(map(tuple, hole + community))
    deck = [c for c in make_deck() if tuple(c) not in known]
    needed = 5 - len(community)
    wins = 0
    for _ in range(n_samples):
        sample = random.sample(deck, needed + 2 * n_opponents)
        board = community + list(sample[:needed])
        my_rank = hand_rank(hole + board)
        beat = all(hand_rank(list(sample[needed + i*2: needed + i*2 + 2]) + board)
                   < my_rank for i in range(n_opponents))
        if beat:
            wins += 1
    return wins / n_samples

# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

def strategy_yolo(hole, community, pot, to_call, my_chips, n_opponents,
                  stage, position, street_bet):
    """Always go all-in."""
    return ("raise", my_chips)


def strategy_tight_aggressive(hole, community, pot, to_call, my_chips,
                               n_opponents, stage, position, street_bet):
    """TAG: only plays premium hands, bets big when ahead."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    # Pre-flop hand tiers
    premium = hi >= 12 or (hi == r1 == r2) or (hi >= 10 and lo >= 10)
    playable = hi >= 10 or (suited and hi >= 9) or (hi == r1 == r2)

    if stage == "preflop":
        if premium:
            raise_to = min(my_chips, max(to_call * 3, int(pot * 0.75)))
            return ("raise", raise_to)
        if playable and to_call < my_chips * 0.12:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = estimate_win_prob(hole, community, n_opponents, 80)
    if prob > 0.70:
        bet = min(my_chips, int(pot * 0.85))
        return ("raise", max(bet, to_call))
    if prob > 0.50 and to_call < my_chips * 0.25:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_loose_passive(hole, community, pot, to_call, my_chips,
                            n_opponents, stage, position, street_bet):
    """Limp in with many hands, rarely raises, calls a lot."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    hi = max(r1, r2)

    if stage == "preflop":
        if hi >= 8 or abs(r1 - r2) <= 2:
            if to_call < my_chips * 0.15:
                return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = estimate_win_prob(hole, community, n_opponents, 60)
    if prob > 0.35:
        if to_call == 0 and prob > 0.55:
            bet = min(my_chips, int(pot * 0.30))
            return ("raise", bet)
        if to_call < my_chips * 0.30:
            return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_positional_bluffer(hole, community, pot, to_call, my_chips,
                                  n_opponents, stage, position, street_bet):
    """Plays position hard: late position aggression, bluffs when heads-up."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi = max(r1, r2)
    in_position = position >= n_opponents  # simplistic: last or near-last to act

    if stage == "preflop":
        if hi >= 12 or r1 == r2:
            return ("raise", min(my_chips, max(to_call * 3, int(pot * 0.6))))
        if in_position and (hi >= 9 or suited):
            return ("raise", min(my_chips, max(to_call * 2, int(pot * 0.4))))
        if to_call < my_chips * 0.08:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = estimate_win_prob(hole, community, n_opponents, 80)
    bluff = in_position and n_opponents == 1 and random.random() < 0.30

    if prob > 0.60 or bluff:
        bet = min(my_chips, int(pot * (0.9 if bluff else 0.75)))
        return ("raise", max(bet, to_call))
    if prob > 0.40 and to_call < my_chips * 0.20:
        return ("call", to_call)
    if to_call == 0:
        if in_position and random.random() < 0.20:  # probe bet
            return ("raise", min(my_chips, int(pot * 0.30)))
        return ("check", 0)
    return ("fold", 0)


def strategy_pot_odds_calculator(hole, community, pot, to_call, my_chips,
                                   n_opponents, stage, position, street_bet):
    """Pure math: calls when pot odds exceed hand equity."""
    if to_call == 0 and stage == "preflop":
        return ("check", 0)
    if to_call == 0 and stage != "preflop":
        prob = estimate_win_prob(hole, community, n_opponents, 90)
        if prob > 0.55:
            bet = min(my_chips, int(pot * 0.65))
            return ("raise", bet)
        return ("check", 0)

    prob = estimate_win_prob(hole, community, n_opponents, 90)
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1
    if prob > pot_odds + 0.05:  # need equity edge
        if prob > 0.65:
            raise_size = min(my_chips, int(pot * 0.80))
            return ("raise", max(raise_size, to_call))
        return ("call", to_call)
    return ("fold", 0)


def strategy_adaptive_gto(hole, community, pot, to_call, my_chips,
                            n_opponents, stage, position, street_bet):
    """GTO-flavored: balances value/bluff ratio, mixed frequencies."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pair = r1 == r2

    # Preflop opening ranges (position-weighted)
    if stage == "preflop":
        hand_score = hi + lo * 0.5 + (2 if suited else 0) + (5 if pair else 0)
        threshold = 16 - position * 0.8  # open wider in late position
        if hand_score >= threshold:
            size = min(my_chips, max(to_call * 3, int(pot * 0.55)))
            return ("raise", size)
        if to_call < my_chips * 0.06:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    prob = estimate_win_prob(hole, community, n_opponents, 100)
    # Mixed strategy: use randomness to be unexploitable
    rand = random.random()
    if prob > 0.75:
        bet = min(my_chips, int(pot * 0.90))
        return ("raise", max(bet, to_call))
    if prob > 0.55:
        if rand < 0.70:
            bet = min(my_chips, int(pot * 0.60))
            return ("raise", max(bet, to_call))
        return ("call", to_call)
    if prob > 0.35:
        if to_call == 0:
            if rand < 0.25:  # balanced bluff frequency
                return ("raise", min(my_chips, int(pot * 0.45)))
            return ("check", 0)
        if to_call < my_chips * 0.18:
            return ("call", to_call)
    if to_call == 0:
        if rand < 0.15:  # pure bluff
            return ("raise", min(my_chips, int(pot * 0.40)))
        return ("check", 0)
    return ("fold", 0)


STRATEGIES = [
    strategy_yolo,                 # Player 1
    strategy_tight_aggressive,     # Player 2
    strategy_loose_passive,        # Player 3
    strategy_positional_bluffer,   # Player 4
    strategy_pot_odds_calculator,  # Player 5
    strategy_adaptive_gto,         # Player 6
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
SMALL_BLIND = 10
BIG_BLIND = 20

def run_hand(players, dealer_idx):
    """
    players: list of {"id": int, "chips": int, "strategy": fn, "active": bool}
    Returns updated players list.
    """
    active = [p for p in players if p["chips"] > 0]
    n = len(active)
    if n < 2:
        return players

    deck = make_deck()
    random.shuffle(deck)

    # Post blinds
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n
    bets = [0] * n
    chips_before = [p["chips"] for p in active]

    def post(idx, amount):
        actual = min(active[idx]["chips"], amount)
        active[idx]["chips"] -= actual
        bets[idx] += actual
        return actual

    post(sb_idx % n, SMALL_BLIND)
    post(bb_idx % n, BIG_BLIND)

    # Deal hole cards
    hole_cards = []
    for i in range(n):
        hole_cards.append([deck.pop(), deck.pop()])

    pot = sum(bets)
    folded = [False] * n
    community = []

    def betting_round(stage, first_to_act):
        nonlocal pot
        cur_bets = [0] * n
        street_max = 0
        if stage == "preflop":
            cur_bets[sb_idx % n] = min(active[sb_idx % n]["chips"] + bets[sb_idx % n],
                                        SMALL_BLIND) - bets[sb_idx % n]
            cur_bets[bb_idx % n] = min(active[bb_idx % n]["chips"] + bets[bb_idx % n],
                                        BIG_BLIND) - bets[bb_idx % n]
            # reset per-street bets to track this street
            cur_bets = list(bets[:])  # carry blinds
            street_max = BIG_BLIND

        order = [(first_to_act + i) % n for i in range(n)]
        last_raiser = -1
        acted = set()

        idx_ptr = 0
        max_iter = n * 4
        iters = 0
        while iters < max_iter:
            iters += 1
            idx = order[idx_ptr % len(order)]
            idx_ptr += 1

            if folded[idx] or active[idx]["chips"] == 0:
                acted.add(idx)
                if all(j in acted or folded[j] or active[j]["chips"] == 0
                       for j in range(n)):
                    break
                continue

            to_call = street_max - cur_bets[idx] if stage != "preflop" else \
                      street_max - cur_bets[idx]
            to_call = max(0, to_call)
            to_call = min(to_call, active[idx]["chips"])

            opponents_left = sum(1 for j in range(n)
                                 if not folded[j] and j != idx)

            action, amount = active[idx]["strategy"](
                hole_cards[idx], community[:],
                pot, to_call, active[idx]["chips"],
                opponents_left, stage, idx, street_max
            )

            if action == "fold":
                folded[idx] = True
                acted.add(idx)
            elif action == "check":
                acted.add(idx)
            elif action == "call":
                paid = min(amount, active[idx]["chips"])
                active[idx]["chips"] -= paid
                cur_bets[idx] += paid
                pot += paid
                acted.add(idx)
            elif action == "raise":
                total_this_street = cur_bets[idx] + amount
                raise_to = max(total_this_street,
                               min(active[idx]["chips"] + cur_bets[idx],
                                   total_this_street))
                extra = min(amount, active[idx]["chips"])
                active[idx]["chips"] -= extra
                cur_bets[idx] += extra
                pot += extra
                if cur_bets[idx] > street_max:
                    street_max = cur_bets[idx]
                    last_raiser = idx
                    acted = {idx}
                acted.add(idx)

            still_in = [j for j in range(n) if not folded[j]]
            if len(still_in) == 1:
                break
            if all(j in acted or folded[j] or active[j]["chips"] == 0
                   for j in range(n)):
                # check if bets are equal among non-folded non-allin
                in_play = [j for j in range(n)
                           if not folded[j] and active[j]["chips"] > 0]
                if all(cur_bets[j] == street_max for j in in_play):
                    break

        return [j for j in range(n) if not folded[j]]

    # Preflop
    survivors = betting_round("preflop", (bb_idx + 1) % n)
    if len(survivors) == 1:
        active[survivors[0]]["chips"] += pot
        return players

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    survivors = betting_round("flop", (sb_idx) % n)
    if len(survivors) == 1:
        active[survivors[0]]["chips"] += pot
        return players

    # Turn
    community.append(deck.pop())
    survivors = betting_round("turn", (sb_idx) % n)
    if len(survivors) == 1:
        active[survivors[0]]["chips"] += pot
        return players

    # River
    community.append(deck.pop())
    survivors = betting_round("river", (sb_idx) % n)
    if len(survivors) == 1:
        active[survivors[0]]["chips"] += pot
        return players

    # Showdown
    ranks = [(hand_rank(hole_cards[i] + community), i) for i in survivors]
    best = max(ranks, key=lambda x: x[0])[0]
    winners = [i for r, i in ranks if r == best]
    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        active[w]["chips"] += share
    active[winners[0]]["chips"] += remainder  # give remainder to first winner

    return players


def run_tournament():
    """Run a full tournament until one player remains. Return winner's player ID."""
    players = [
        {"id": i + 1, "chips": STARTING_CHIPS, "strategy": STRATEGIES[i]}
        for i in range(6)
    ]
    dealer = 0
    hand_num = 0
    max_hands = 2000  # safety cap

    while sum(1 for p in players if p["chips"] > 0) > 1 and hand_num < max_hands:
        active_ids = [i for i, p in enumerate(players) if p["chips"] > 0]
        if len(active_ids) < 2:
            break
        dealer = dealer % len(active_ids)
        players = run_hand(players, dealer)
        dealer = (dealer + 1) % max(1, sum(1 for p in players if p["chips"] > 0))
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
        print(f"  sim {sim + 1}/{N_SIMS}...")
    winner_id = run_tournament()
    win_counts[winner_id] += 1

# ---------------------------------------------------------------------------
# Histogram output
# ---------------------------------------------------------------------------
print("\n" + "=" * 60)
print("  TOURNAMENT RESULTS — 100 Simulations")
print("  Winner = Last Player Standing")
print("=" * 60)

max_wins = max(win_counts.values()) if win_counts else 1
bar_scale = 40

for pid in range(1, 7):
    name = STRATEGY_NAMES[pid - 1]
    wins = win_counts.get(pid, 0)
    bar = "█" * int(wins / max_wins * bar_scale)
    marker = " ◄ YOLO" if pid == 1 else ""
    print(f"P{pid} {name:<24} | {bar:<40} {wins:>3} wins{marker}")

print("=" * 60)
total = sum(win_counts.values())
print(f"\nTotal recorded wins: {total}")
print(f"\nExpected wins if uniform: {N_SIMS/6:.1f} per player")

print("\n--- Win Rate ---")
for pid in range(1, 7):
    name = STRATEGY_NAMES[pid - 1]
    wins = win_counts.get(pid, 0)
    pct = wins / N_SIMS * 100
    verdict = ""
    if pid == 1:
        if wins > N_SIMS / 6:
            verdict = "  [YOLO WINS — chaos reigns!]"
        else:
            verdict = "  [YOLO humiliated — brains > brawn]"
    print(f"  P{pid} {name:<24}: {wins:>3} / {N_SIMS}  ({pct:5.1f}%){verdict}")

print("\nSuflair GPT status: REKT by a Python script.")
