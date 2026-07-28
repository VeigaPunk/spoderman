"""
Texas Hold'em Poker Simulation
Player 1: The Maniac (always all-in)
Players 2-6: Five elaborate strategy bots
100 tournament simulations -> histogram of winners
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────
#  CARD ENGINE
# ─────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def hand_rank(cards):
    """Best 5-card ranking tuple out of 5-7 cards."""
    best = None
    for combo in combinations(cards, 5):
        score = _score5(combo)
        if best is None or score > best:
            best = score
    return best

def _score5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0] - 5, -1)) or
                ranks == [14, 5, 4, 3, 2])
    if straight and ranks == [14, 5, 4, 3, 2]:
        ranks = [5, 4, 3, 2, 1]

    cnt = Counter(ranks)
    counts = sorted(cnt.values(), reverse=True)
    rank_groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)

    if flush and straight:
        return (8, ranks)
    if counts[0] == 4:
        return (7, rank_groups)
    if counts[:2] == [3, 2]:
        return (6, rank_groups)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts[0] == 3:
        return (3, rank_groups)
    if counts[:2] == [2, 2]:
        return (2, rank_groups)
    if counts[0] == 2:
        return (1, rank_groups)
    return (0, ranks)

def estimate_equity(hole, community, num_opponents, iterations=150):
    """Monte Carlo equity: fraction of rollouts where our hand wins."""
    wins = 0
    base_deck = [c for c in make_deck() if c not in hole and c not in community]
    needed = 5 - len(community)
    num_opponents = max(1, num_opponents)
    for _ in range(iterations):
        deck = base_deck[:]
        random.shuffle(deck)
        board = list(community) + deck[:needed]
        idx = needed
        my_rank = hand_rank(list(hole) + board)
        won = True
        for _ in range(num_opponents):
            opp_hole = [deck[idx], deck[idx + 1]]
            idx += 2
            if hand_rank(opp_hole + board) > my_rank:
                won = False
                break
        if won:
            wins += 1
    return wins / iterations

# ─────────────────────────────────────────────
#  PLAYER
# ─────────────────────────────────────────────

class Player:
    def __init__(self, name, strategy_fn, stack):
        self.name = name
        self.strategy_fn = strategy_fn
        self.stack = stack
        self.hole = []
        self.in_hand = False
        self.bet_this_street = 0

    def act(self, state, to_call, min_raise):
        if self.stack == 0:
            return ("check", 0)
        action, amount = self.strategy_fn(
            hole=self.hole,
            community=state["community"],
            stack=self.stack,
            pot=state["pot"],
            to_call=to_call,
            min_raise=min_raise,
            street=state["street"],
            num_active=state["num_active"],
            big_blind=state["big_blind"],
        )
        if action == "allin":
            return ("raise", self.stack)
        if action == "raise":
            return ("raise", min(max(amount, min_raise), self.stack))
        if action == "call":
            return ("call", min(to_call, self.stack))
        if action == "check":
            return ("check", 0) if to_call == 0 else ("fold", 0)
        return ("fold", 0)

# ─────────────────────────────────────────────
#  THE SIX STRATEGIES
# ─────────────────────────────────────────────

def strategy_maniac(hole, community, stack, pot, to_call, min_raise,
                    street, num_active, big_blind):
    # if my_turn Then bet = All in Fi
    return ("allin", stack)


def strategy_shark(hole, community, stack, pot, to_call, min_raise,
                   street, num_active, big_blind):
    """Tight-aggressive: premium preflop ranges + MC equity postflop."""
    bb = big_blind
    if street == "preflop":
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited = hole[0][1] == hole[1][1]
        pair = r1 == r2
        hi, lo = max(r1, r2), min(r1, r2)
        if (pair and hi >= 11) or (hi == 14 and lo >= 12):
            if to_call > stack // 2:
                return ("allin", stack)
            return ("raise", min(stack, max(4 * bb, to_call + 3 * bb)))
        if (pair and hi >= 7) or (hi >= 12 and lo >= 10) or (suited and hi == 14):
            if to_call <= 3 * bb:
                return ("call", to_call)
            return ("fold", 0)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    equity = estimate_equity(hole, community, num_active - 1)
    if equity > 0.80:
        if to_call > 0 and to_call >= stack // 2:
            return ("allin", stack)
        return ("raise", max(int(pot * 0.75), min_raise))
    if equity > 0.60:
        if to_call == 0:
            return ("raise", max(int(pot * 0.5), min_raise))
        if to_call <= pot * 0.4:
            return ("call", to_call)
        return ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_calculator(hole, community, stack, pot, to_call, min_raise,
                        street, num_active, big_blind):
    """Pure pot-odds math with implied-odds adjustment on draw streets."""
    equity = estimate_equity(hole, community, num_active - 1)
    required = to_call / (pot + to_call) if to_call > 0 else 0.0
    implied = 1.25 if street in ("flop", "turn") else 1.0
    eff = min(equity * implied, 1.0)

    if eff > required + 0.18:
        size = max(int(pot * 0.6), min_raise)
        if size >= stack:
            return ("allin", stack)
        return ("raise", size)
    if eff > required:
        return ("call", to_call) if to_call > 0 else ("check", 0)
    return ("check", 0) if to_call == 0 else ("fold", 0)


def strategy_psychologist(hole, community, stack, pot, to_call, min_raise,
                          street, num_active, big_blind):
    """Board-texture reads: bluffs scary boards, slow-plays monsters."""
    equity = estimate_equity(hole, community, num_active - 1)

    board_ranks = [RANK_VAL[c[0]] for c in community]
    paired_board = len(board_ranks) != len(set(board_ranks))
    flush_possible = (len(community) >= 3 and
                      max(Counter(c[1] for c in community).values()) >= 3)
    scary = paired_board or flush_possible
    bluff_chance = 0.35 if scary else 0.12

    if equity > 0.72:
        if random.random() < 0.25 and to_call == 0:
            return ("check", 0)  # trap
        return ("raise", max(int(pot * 0.6), min_raise))
    if equity > 0.50:
        if to_call == 0:
            return ("raise", max(int(pot * 0.4), min_raise))
        if to_call <= pot * 0.45:
            return ("call", to_call)
        return ("fold", 0)
    if to_call == 0 and street != "preflop" and random.random() < bluff_chance:
        return ("raise", max(int(pot * 0.55), min_raise))
    return ("check", 0) if to_call == 0 else ("fold", 0)


def strategy_survivalist(hole, community, stack, pot, to_call, min_raise,
                         street, num_active, big_blind):
    """Tournament M-ratio play: push/fold short, tight medium, loose deep."""
    equity = estimate_equity(hole, community, num_active - 1)
    m = stack / max(1, big_blind + big_blind // 2)

    if m < 6:  # short: push or fold
        if equity > 0.50:
            return ("allin", stack)
        return ("check", 0) if to_call == 0 else ("fold", 0)
    if m < 15:  # medium: tight
        if equity > 0.65:
            return ("raise", max(3 * big_blind, min_raise))
        if equity > 0.50 and to_call <= 2 * big_blind:
            return ("call", to_call)
        return ("check", 0) if to_call == 0 else ("fold", 0)
    # deep: speculative
    if equity > 0.58:
        return ("raise", max(int(pot * 0.6), min_raise))
    if equity > 0.40 and to_call <= int(pot * 0.3):
        return ("call", to_call)
    return ("check", 0) if to_call == 0 else ("fold", 0)


_adaptor_pots = []

def strategy_adaptor(hole, community, stack, pot, to_call, min_raise,
                     street, num_active, big_blind):
    """Counter-adjusts to table aggression measured from observed pot sizes."""
    equity = estimate_equity(hole, community, num_active - 1)
    recent = _adaptor_pots[-15:]
    avg_pot = sum(recent) / len(recent) if recent else 3 * big_blind
    aggro = avg_pot / (3 * big_blind)
    _adaptor_pots.append(pot)

    raise_thr = min(0.80, max(0.52, 0.60 + (aggro - 1) * 0.08))
    call_thr = min(0.60, max(0.32, 0.42 + (aggro - 1) * 0.08))

    if equity > raise_thr:
        if to_call >= stack // 2:
            return ("allin", stack)
        return ("raise", max(int(pot * 0.65), min_raise))
    if equity > call_thr:
        if to_call == 0:
            return ("check", 0)
        if to_call <= pot * 0.5:
            return ("call", to_call)
        return ("fold", 0)
    return ("check", 0) if to_call == 0 else ("fold", 0)

# ─────────────────────────────────────────────
#  HAND ENGINE (with side pots)
# ─────────────────────────────────────────────

def betting_round(players, state, order):
    current_bet = max(p.bet_this_street for p in players)
    min_raise = state["big_blind"]
    queue = [p for p in order if p.in_hand and p.stack > 0]
    to_act = list(queue)

    guard = 0
    while to_act and guard < 200:
        guard += 1
        p = to_act.pop(0)
        if not p.in_hand or p.stack == 0:
            continue
        if len([x for x in players if x.in_hand]) <= 1:
            break

        to_call = max(0, current_bet - p.bet_this_street)
        state["num_active"] = len([x for x in players if x.in_hand])
        action, amount = p.act(state, to_call, min_raise)

        if action == "fold":
            p.in_hand = False
        elif action == "call":
            pay = min(amount, p.stack)
            p.stack -= pay
            p.bet_this_street += pay
            state["pot"] += pay
        elif action == "check":
            pass
        elif action == "raise":
            pay = min(amount, p.stack)
            p.stack -= pay
            p.bet_this_street += pay
            state["pot"] += pay
            if p.bet_this_street > current_bet:
                raise_size = p.bet_this_street - current_bet
                if raise_size >= min_raise or p.stack == 0:
                    min_raise = max(min_raise, raise_size)
                current_bet = p.bet_this_street
                # everyone else still in gets to respond
                to_act = [x for x in order
                          if x.in_hand and x.stack > 0 and x is not p
                          and x.bet_this_street < current_bet]

    return len([p for p in players if p.in_hand]) > 1


def distribute_pot(players, contributions, community):
    """Side-pot aware distribution at showdown."""
    in_showdown = [p for p in players if p.in_hand]
    if len(in_showdown) == 1:
        in_showdown[0].stack += sum(contributions.values())
        return

    ranks = {p: hand_rank(p.hole + community) for p in in_showdown}
    remaining = dict(contributions)

    while any(v > 0 for v in remaining.values()):
        eligible = [p for p in in_showdown if remaining.get(p, 0) > 0]
        if not eligible:
            # leftover money from folded players goes to best hand
            leftovers = sum(v for v in remaining.values() if v > 0)
            best = max(in_showdown, key=lambda p: ranks[p])
            best.stack += leftovers
            break
        layer = min(remaining[p] for p in eligible)
        pot_layer = 0
        for p in list(remaining):
            take = min(remaining[p], layer)
            pot_layer += take
            remaining[p] -= take
        best_rank = max(ranks[p] for p in eligible)
        winners = [p for p in eligible if ranks[p] == best_rank]
        share = pot_layer // len(winners)
        for w in winners:
            w.stack += share
        winners[0].stack += pot_layer - share * len(winners)  # odd chips


def play_hand(players, dealer_idx, blinds):
    deck = make_deck()
    random.shuffle(deck)
    sb, bb = blinds

    actives = [p for p in players if p.stack > 0]
    n = len(actives)
    if n < 2:
        return

    for p in players:
        p.in_hand = False
        p.bet_this_street = 0
        p.hole = []
    for p in actives:
        p.in_hand = True

    contributions = {p: 0 for p in actives}

    state = {"pot": 0, "community": [], "street": "preflop",
             "big_blind": bb, "num_active": n}

    sb_p = actives[dealer_idx % n]
    bb_p = actives[(dealer_idx + 1) % n]
    for p, amt in ((sb_p, sb), (bb_p, bb)):
        pay = min(amt, p.stack)
        p.stack -= pay
        p.bet_this_street += pay
        state["pot"] += pay

    idx = 0
    for p in actives:
        p.hole = [deck[idx], deck[idx + 1]]
        idx += 2

    def end_street():
        for p in actives:
            contributions[p] += p.bet_this_street
            p.bet_this_street = 0

    utg = (dealer_idx + 2) % n
    order = actives[utg:] + actives[:utg]
    betting_round(players, state, order)
    end_street()

    streets = [("flop", 3), ("turn", 1), ("river", 1)]
    post_order = actives[dealer_idx % n:] + actives[:dealer_idx % n]

    for street, ncards in streets:
        if len([p for p in players if p.in_hand]) <= 1:
            break
        state["community"] += deck[idx:idx + ncards]
        idx += ncards
        state["street"] = street
        live = [p for p in post_order if p.in_hand and p.stack > 0]
        if len(live) >= 2:
            betting_round(players, state, post_order)
        end_street()

    survivors = [p for p in players if p.in_hand]
    if len(survivors) == 1:
        survivors[0].stack += sum(contributions.values())
    else:
        # run out remaining board for all-in showdowns
        while len(state["community"]) < 5:
            state["community"].append(deck[idx])
            idx += 1
        distribute_pot(players, contributions, state["community"])

# ─────────────────────────────────────────────
#  TOURNAMENT
# ─────────────────────────────────────────────

def run_tournament(starting_chips=1500):
    global _adaptor_pots
    _adaptor_pots = []

    players = [
        Player("Maniac",       strategy_maniac,       starting_chips),
        Player("Shark",        strategy_shark,        starting_chips),
        Player("Calculator",   strategy_calculator,   starting_chips),
        Player("Psychologist", strategy_psychologist, starting_chips),
        Player("Survivalist",  strategy_survivalist,  starting_chips),
        Player("Adaptor",      strategy_adaptor,      starting_chips),
    ]

    blinds = (25, 50)
    dealer = 0
    hand_num = 0
    while sum(1 for p in players if p.stack > 0) > 1 and hand_num < 1000:
        play_hand(players, dealer, blinds)
        dealer += 1
        hand_num += 1
        if hand_num % 25 == 0:
            blinds = (blinds[0] * 2, blinds[1] * 2)

    alive = [p for p in players if p.stack > 0]
    return max(alive, key=lambda p: p.stack).name if alive else "Draw"

# ─────────────────────────────────────────────
#  100 SIMS + HISTOGRAM
# ─────────────────────────────────────────────

def main(n=100):
    labels = {
        "Maniac":       "P1 THE MANIAC       (if my_turn: ALL-IN fi)",
        "Shark":        "P2 THE SHARK        (tight-aggressive)",
        "Calculator":   "P3 THE CALCULATOR   (pot-odds math)",
        "Psychologist": "P4 THE PSYCHOLOGIST (bluffs & texture)",
        "Survivalist":  "P5 THE SURVIVALIST  (M-ratio preservation)",
        "Adaptor":      "P6 THE ADAPTOR      (table-aggro reader)",
    }

    print("=" * 62)
    print(f" TEXAS HOLD'EM — {n} TOURNAMENTS, 6 PLAYERS, EQUAL STACKS")
    print("=" * 62)

    results = Counter()
    for i in range(n):
        results[run_tournament()] += 1
        if (i + 1) % 20 == 0:
            print(f"   ... {i + 1}/{n} tournaments complete")

    print()
    print("-" * 62)
    print(" WINNER WINNER CHICKEN DINNER — HISTOGRAM")
    print("-" * 62)
    print()
    max_wins = max(results.values())
    for key in ["Maniac", "Shark", "Calculator", "Psychologist",
                "Survivalist", "Adaptor"]:
        wins = results.get(key, 0)
        bar = "█" * round(wins / max_wins * 40) if max_wins else ""
        print(f" {labels[key]:<46} {wins:>3} ({wins / n * 100:4.0f}%)")
        print(f"   {bar}")
    print()
    champ = results.most_common(1)[0][0]
    print(f" CHAMPION ACROSS {n} SIMS: {labels[champ]}")
    print("=" * 62)


if __name__ == "__main__":
    random.seed(2026)
    main(100)
