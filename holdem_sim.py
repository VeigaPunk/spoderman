#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
Player 1: Simple all-in strategy
Players 2-6: Elaborate strategies
100 simulations — histogram of winners
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────── Card primitives ────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ─────────────────────────── Hand evaluation ────────────────────────────────

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards. Returns comparable tuple."""
    best = None
    for combo in combinations(cards, 5):
        val = five_card_rank(combo)
        if best is None or val > best:
            best = val
    return best

def five_card_rank(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5) or ranks == [14, 5, 4, 3, 2]
    if straight and ranks == [14, 5, 4, 3, 2]:
        ranks = [5, 4, 3, 2, 1]

    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda r: (counts[r], r), reverse=True)

    if flush and straight:    return (8,) + tuple(ranks)
    if freq == [4, 1]:        return (7,) + tuple(groups)
    if freq == [3, 2]:        return (6,) + tuple(groups)
    if flush:                 return (5,) + tuple(ranks)
    if straight:              return (4,) + tuple(ranks)
    if freq[0] == 3:          return (3,) + tuple(groups)
    if freq[:2] == [2, 2]:    return (2,) + tuple(groups)
    if freq[0] == 2:          return (1,) + tuple(groups)
    return (0,) + tuple(ranks)

# ─────────────────────────── Monte Carlo equity ─────────────────────────────

def estimate_equity(hole, community, num_opponents, trials=200):
    """Estimate win probability for hole cards via Monte Carlo."""
    known = set(map(tuple, hole + community))
    deck = [c for c in make_deck() if tuple(c) not in known]
    wins = 0
    for _ in range(trials):
        sample = random.sample(deck, (5 - len(community)) + 2 * num_opponents)
        board = community + sample[:5 - len(community)]
        opp_cards = sample[5 - len(community):]
        my_rank = hand_rank(hole + board)
        beat_all = True
        for i in range(num_opponents):
            opp_hole = opp_cards[i*2:(i+1)*2]
            if hand_rank(opp_hole + board) >= my_rank:
                beat_all = False
                break
        if beat_all:
            wins += 1
    return wins / trials

# ─────────────────────────── Strategies ─────────────────────────────────────

def strategy_all_in(player, game_state):
    """Player 1: always go all-in."""
    return ("raise", player["chips"])

def strategy_tight_aggressive(player, game_state):
    """
    Strategy 2 — Tight-Aggressive (TAG): Only play premium hands pre-flop,
    bet/raise aggressively when in a strong position, fold weak hands.
    """
    hole = player["hole"]
    community = game_state["community"]
    to_call = game_state["to_call"]
    pot = game_state["pot"]
    num_active = game_state["num_active"]
    chips = player["chips"]
    street = game_state["street"]

    if street == "preflop":
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        paired = r1 == r2
        suited = hole[0][1] == hole[1][1]
        high = max(r1, r2)
        low = min(r1, r2)
        gap = high - low

        # Premium hands
        if paired and high >= RANK_VAL["T"]:
            bet = min(chips, pot * 3 + to_call * 2)
            return ("raise", max(to_call * 2, bet))
        if high >= RANK_VAL["A"] and low >= RANK_VAL["T"]:
            return ("raise", min(chips, max(to_call * 2, pot // 2)))
        if high >= RANK_VAL["K"] and suited and gap <= 2:
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        if to_call <= chips // 20:
            return ("call", to_call)
        return ("fold", 0)

    equity = estimate_equity(hole, community, num_active - 1)
    if equity > 0.70:
        return ("raise", min(chips, pot))
    if equity > 0.50:
        if to_call == 0:
            return ("bet", min(chips, pot // 2))
        return ("call", to_call)
    if equity > 0.30 and to_call == 0:
        return ("check", 0)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_loose_passive(player, game_state):
    """
    Strategy 3 — Loose-Passive (calling station): Calls wide, rarely raises,
    chases draws hoping to hit the nuts on the river.
    """
    hole = player["hole"]
    community = game_state["community"]
    to_call = game_state["to_call"]
    pot = game_state["pot"]
    chips = player["chips"]
    num_active = game_state["num_active"]

    if to_call == 0:
        return ("check", 0)

    # Will call anything up to 40% of stack
    if to_call <= chips * 0.40:
        return ("call", to_call)

    # Desperate: call all-in if pot odds look good
    if pot > chips * 2:
        return ("call", to_call)

    return ("fold", 0)


def strategy_positional_gto(player, game_state):
    """
    Strategy 4 — GTO-inspired positional play: uses pot odds, implied odds,
    position awareness, and semi-bluffing on draws.
    """
    hole = player["hole"]
    community = game_state["community"]
    to_call = game_state["to_call"]
    pot = game_state["pot"]
    chips = player["chips"]
    num_active = game_state["num_active"]
    street = game_state["street"]
    position = game_state.get("position", 0)  # 0=early, 1=middle, 2=late/button

    # Pot odds
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    if street == "preflop":
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        paired = r1 == r2
        suited = hole[0][1] == hole[1][1]
        high = max(r1, r2)
        low = min(r1, r2)
        gap = high - low

        # Playability score
        score = 0
        if paired: score += (high - 2) * 2
        score += high + low
        if suited: score += 4
        score -= gap * 2
        if position == 2: score += 6   # button bonus
        if position == 0: score -= 4   # UTG penalty

        if score >= 22:
            return ("raise", min(chips, max(to_call * 3, pot)))
        if score >= 14:
            if to_call == 0: return ("bet", min(chips, pot // 3))
            return ("call", to_call)
        if score >= 8 and position == 2 and to_call == 0:
            return ("bet", min(chips, pot // 4))  # position steal
        if to_call == 0:
            return ("check", 0)
        if pot_odds < 0.15:
            return ("call", to_call)
        return ("fold", 0)

    equity = estimate_equity(hole, community, num_active - 1, trials=300)

    # Semi-bluff on draws
    if street in ("flop", "turn"):
        draw_equity = _draw_strength(hole, community)
        if draw_equity > 0.35 and to_call == 0 and position == 2:
            return ("bet", min(chips, pot // 3))

    if equity > pot_odds + 0.10:
        if to_call == 0:
            bet_size = min(chips, int(pot * (0.5 + equity)))
            return ("bet", bet_size)
        return ("raise", min(chips, pot))
    if equity > pot_odds:
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def _draw_strength(hole, community):
    """Rough draw-potential heuristic: flush/straight draw detection."""
    all_cards = hole + community
    suits = [c[1] for c in all_cards]
    ranks = sorted(set(RANK_VAL[c[0]] for c in all_cards))
    flush_draw = max(suits.count(s) for s in set(suits)) >= 4
    straight_draw = any(
        sum(1 for r in ranks if lo <= r <= lo + 4) >= 4
        for lo in range(2, 11)
    )
    if flush_draw and straight_draw: return 0.55
    if flush_draw or straight_draw:  return 0.38
    return 0.10


def strategy_bluff_maniac(player, game_state):
    """
    Strategy 5 — Maniac Bluffer: hyper-aggressive, bets/raises with almost
    anything, uses bet-sizing to pressure opponents, selectively backs down
    only against re-raises with truly weak hands.
    """
    hole = player["hole"]
    community = game_state["community"]
    to_call = game_state["to_call"]
    pot = game_state["pot"]
    chips = player["chips"]
    num_active = game_state["num_active"]
    street = game_state["street"]

    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    hand_score = r1 + r2

    # Occasionally slow-play monsters
    if street == "preflop" and r1 == r2 and r1 >= RANK_VAL["Q"]:
        if random.random() < 0.3:
            return ("call", to_call)

    # 80% of the time, raise/bet aggressively
    if random.random() < 0.80:
        size = min(chips, max(to_call + pot // 2, pot * 2))
        return ("raise", size)

    # 20%: call or check to keep people in
    if to_call == 0:
        return ("check", 0)
    if to_call <= chips * 0.15:
        return ("call", to_call)
    return ("fold", 0)


def strategy_exploitative_adaptive(player, game_state):
    """
    Strategy 6 — Exploitative/Adaptive: tracks opponent tendencies (aggression
    frequency stored in game_state), adjusts ranges dynamically, value-bets
    thin, and punishes predictable players with targeted bluffs.
    """
    hole = player["hole"]
    community = game_state["community"]
    to_call = game_state["to_call"]
    pot = game_state["pot"]
    chips = player["chips"]
    num_active = game_state["num_active"]
    street = game_state["street"]
    pid = player["id"]

    # Read opponent aggression model (stored in shared state)
    opp_stats = game_state.get("opp_stats", {})
    avg_agg = sum(v.get("agg", 0.5) for k, v in opp_stats.items() if k != pid)
    avg_agg = avg_agg / max(1, len(opp_stats) - (1 if pid in opp_stats else 0))
    # If opponents are loose/passive, value-bet thinner
    value_threshold = 0.45 if avg_agg < 0.40 else 0.55

    if street == "preflop":
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        paired = r1 == r2
        suited = hole[0][1] == hole[1][1]
        high, low = max(r1, r2), min(r1, r2)

        pf_score = (high + low) + (4 if suited else 0) + (high * 2 if paired else 0)
        # Widen range vs passive table
        threshold = 22 if avg_agg > 0.5 else 18

        if pf_score >= threshold:
            size = min(chips, max(to_call * 2.5, pot * 0.75))
            return ("raise", int(size))
        if pf_score >= threshold - 6:
            if to_call == 0: return ("check", 0)
            return ("call", to_call)
        if to_call == 0: return ("check", 0)
        return ("fold", 0)

    equity = estimate_equity(hole, community, num_active - 1, trials=250)

    # Thin value bet vs calling stations
    if equity > value_threshold:
        if to_call == 0:
            size = int(pot * (0.4 + equity * 0.6))
            return ("bet", min(chips, size))
        if equity > 0.60:
            return ("raise", min(chips, pot))
        return ("call", to_call)

    # Bluff-catch: call if pot odds justify and opponent is aggressive
    pot_odds = to_call / (pot + to_call + 1)
    if equity > pot_odds and avg_agg > 0.6:
        return ("call", to_call)

    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


STRATEGIES = [
    strategy_all_in,             # Player 1
    strategy_tight_aggressive,   # Player 2
    strategy_loose_passive,      # Player 3
    strategy_positional_gto,     # Player 4
    strategy_bluff_maniac,       # Player 5
    strategy_exploitative_adaptive,  # Player 6
]

STRATEGY_NAMES = [
    "P1:AllIn",
    "P2:TAG",
    "P3:Passive",
    "P4:GTO",
    "P5:Maniac",
    "P6:Adaptive",
]

# ─────────────────────────── Game engine ────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

class Player:
    def __init__(self, pid, chips, strategy):
        self.id       = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.folded   = False
        self.all_in   = False
        self.bet_this_round = 0

    def is_active(self):
        return not self.folded and self.chips > 0

    def reset_round(self):
        self.hole              = []
        self.folded            = False
        self.all_in            = False
        self.bet_this_round    = 0


def run_betting_round(players, pot, community, street, dealer_idx, opp_stats):
    """Run one street of betting. Returns updated pot."""
    active = [p for p in players if not p.folded and p.chips > 0]
    if len(active) <= 1:
        return pot

    # Reset per-street bets
    current_bet = 0
    last_aggressor = None

    # Determine order
    if street == "preflop":
        start = (dealer_idx + 3) % len(players)  # UTG
        # Post blinds
        sb_idx = (dealer_idx + 1) % len(players)
        bb_idx = (dealer_idx + 2) % len(players)
        sb_p = players[sb_idx]
        bb_p = players[bb_idx]
        if not sb_p.folded and sb_p.chips > 0:
            sb_amt = min(SMALL_BLIND, sb_p.chips)
            sb_p.chips -= sb_amt
            sb_p.bet_this_round += sb_amt
            pot += sb_amt
        if not bb_p.folded and bb_p.chips > 0:
            bb_amt = min(BIG_BLIND, bb_p.chips)
            bb_p.chips -= bb_amt
            bb_p.bet_this_round += bb_amt
            pot += bb_amt
        current_bet = BIG_BLIND
    else:
        start = (dealer_idx + 1) % len(players)

    n = len(players)
    acted = set()
    order = [(start + i) % n for i in range(n)]

    while True:
        progress = False
        for idx in order:
            p = players[idx]
            if p.folded or p.chips == 0:
                acted.add(idx)
                continue
            if idx in acted and p.bet_this_round >= current_bet:
                continue

            to_call = max(0, current_bet - p.bet_this_round)
            num_active = sum(1 for x in players if not x.folded and x.chips > 0)

            gs = {
                "community": community,
                "to_call":   min(to_call, p.chips),
                "pot":       pot,
                "street":    street,
                "num_active": num_active,
                "position":  (idx - dealer_idx) % n / max(1, n - 1),
                "opp_stats": opp_stats,
            }
            gs["position"] = 2 if (idx - dealer_idx) % n in (0, n-1) else (
                             0 if (idx - dealer_idx) % n <= 2 else 1)

            action, amount = p.strategy(
                {"id": p.id, "hole": p.hole, "chips": p.chips},
                gs
            )

            # Track aggression for adaptive strategy
            pid = p.id
            if pid not in opp_stats:
                opp_stats[pid] = {"agg": 0.5, "actions": 0}
            opp_stats[pid]["actions"] += 1
            if action in ("raise", "bet"):
                opp_stats[pid]["agg"] = (opp_stats[pid]["agg"] * 0.9 + 0.1)
            else:
                opp_stats[pid]["agg"] = (opp_stats[pid]["agg"] * 0.9)

            if action == "fold":
                p.folded = True
                acted.add(idx)
                progress = True
            elif action in ("check", "call"):
                actual = min(to_call, p.chips)
                p.chips -= actual
                p.bet_this_round += actual
                pot += actual
                if p.chips == 0:
                    p.all_in = True
                acted.add(idx)
                progress = True
            elif action in ("raise", "bet"):
                amount = int(amount)
                if amount <= to_call:
                    amount = to_call  # treat as call
                actual = min(amount, p.chips)
                p.chips -= actual
                p.bet_this_round += actual
                pot += actual
                if actual > to_call:
                    current_bet = p.bet_this_round
                    last_aggressor = idx
                    # Everyone else needs to act again
                    acted = {idx}
                else:
                    acted.add(idx)
                if p.chips == 0:
                    p.all_in = True
                progress = True

            remaining = [x for x in players if not x.folded and x.chips > 0]
            if len(remaining) <= 1:
                return pot

        # Check if all active players have matched the bet
        unfinished = [
            i for i, p in enumerate(players)
            if not p.folded and p.chips > 0
            and (i not in acted or p.bet_this_round < current_bet)
        ]
        if not unfinished:
            break
        if not progress:
            break

    # Reset per-round bets for next street
    for p in players:
        p.bet_this_round = 0

    return pot


def showdown(players, community, pot):
    """Award pot to best hand(s) at showdown."""
    contenders = [p for p in players if not p.folded]
    if not contenders:
        return

    best_rank = None
    winners = []
    for p in contenders:
        rank = hand_rank(p.hole + community)
        if best_rank is None or rank > best_rank:
            best_rank = rank
            winners = [p]
        elif rank == best_rank:
            winners.append(p)

    share = pot // len(winners)
    remainder = pot % len(winners)
    for i, w in enumerate(winners):
        w.chips += share + (1 if i == 0 else 0) * remainder


def run_tournament():
    """Run one full tournament until one player has all chips. Returns winner id."""
    players = [
        Player(i + 1, STARTING_CHIPS, STRATEGIES[i])
        for i in range(6)
    ]

    opp_stats = {}
    dealer_idx = 0
    max_hands = 500

    for hand_num in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].id

        for p in players:
            p.reset_round()

        # Deal
        deck = make_deck()
        random.shuffle(deck)
        card_idx = 0
        for p in alive:
            p.hole = [deck[card_idx], deck[card_idx + 1]]
            card_idx += 2

        community = []
        pot = 0

        # Preflop
        pot = run_betting_round(players, pot, community, "preflop", dealer_idx, opp_stats)
        still_in = [p for p in players if not p.folded]
        if len(still_in) == 1:
            still_in[0].chips += pot
            dealer_idx = (dealer_idx + 1) % len(players)
            continue

        # Flop
        community = [deck[card_idx], deck[card_idx+1], deck[card_idx+2]]
        card_idx += 3
        pot = run_betting_round(players, pot, community, "flop", dealer_idx, opp_stats)
        still_in = [p for p in players if not p.folded]
        if len(still_in) == 1:
            still_in[0].chips += pot
            dealer_idx = (dealer_idx + 1) % len(players)
            continue

        # Turn
        community.append(deck[card_idx]); card_idx += 1
        pot = run_betting_round(players, pot, community, "turn", dealer_idx, opp_stats)
        still_in = [p for p in players if not p.folded]
        if len(still_in) == 1:
            still_in[0].chips += pot
            dealer_idx = (dealer_idx + 1) % len(players)
            continue

        # River
        community.append(deck[card_idx]); card_idx += 1
        pot = run_betting_round(players, pot, community, "river", dealer_idx, opp_stats)
        still_in = [p for p in players if not p.folded]
        if len(still_in) == 1:
            still_in[0].chips += pot
        else:
            showdown(still_in, community, pot)

        dealer_idx = (dealer_idx + 1) % len(players)

    # Time limit: whoever has most chips wins
    alive = [p for p in players if p.chips > 0]
    return max(alive, key=lambda p: p.chips).id


# ─────────────────────────── Run 100 sims ───────────────────────────────────

def main():
    NUM_SIMS = 100
    print(f"Running {NUM_SIMS} Texas Hold'em tournaments...")
    print("=" * 60)

    wins = Counter()
    for sim in range(NUM_SIMS):
        if sim % 10 == 0:
            print(f"  Sim {sim+1}-{min(sim+10, NUM_SIMS)}...")
        winner_id = run_tournament()
        wins[winner_id] += 1

    print("\n" + "=" * 60)
    print("RESULTS — Last Player Standing (100 tournaments)")
    print("=" * 60)

    max_wins = max(wins.values()) if wins else 1
    bar_scale = 40 / max_wins

    for pid in range(1, 7):
        name = STRATEGY_NAMES[pid - 1]
        w = wins.get(pid, 0)
        bar = "█" * int(w * bar_scale)
        marker = " ← THE ALL-IN MANIAC" if pid == 1 else ""
        print(f"  {name:<18} | {bar:<40} | {w:3d} wins ({w}%){marker}")

    print("=" * 60)
    top = wins.most_common(1)[0]
    print(f"\nTournament Champion: {STRATEGY_NAMES[top[0]-1]} with {top[1]} wins")

    all_in_wins = wins.get(1, 0)
    elaborate_wins = sum(wins.get(p, 0) for p in range(2, 7))
    print(f"\nSimple All-In  : {all_in_wins} wins")
    print(f"Elaborate algos: {elaborate_wins} wins")
    if all_in_wins > elaborate_wins / 5:
        print("\nChaos reigns — the all-in donkey is giving those algos nightmares.")
    else:
        print("\nThe elaborate strategies crushed the all-in lunatic. Skill > luck (eventually).")

if __name__ == "__main__":
    random.seed(42)
    main()
