#!/usr/bin/env python3
"""
Texas Hold'em Poker Tournament Simulation
100 tournaments, 6 players, histogram of final winners.
Player 1: The YOLO — all-in every single time.
Players 2-6: elaborate strategy bots.
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────────────────────────────────────
# CARD ENGINE
# ─────────────────────────────────────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}


def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


def card_str(c):
    return c[0] + c[1]


def hand_rank(cards):
    """Return a comparable tuple for the best 5-card hand from 5-7 cards."""
    best = None
    for combo in combinations(cards, 5):
        score = score_five(combo)
        if best is None or score > best:
            best = score
    return best


def score_five(cards):
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    # wheel straight A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        straight = True
        vals = [5, 4, 3, 2, 1]

    counts = sorted(Counter(vals).values(), reverse=True)
    count_vals = sorted(
        Counter(vals).keys(),
        key=lambda v: (Counter(vals)[v], v),
        reverse=True
    )

    if straight and flush:
        return (8, vals)
    if counts[0] == 4:
        return (7, count_vals)
    if counts[:2] == [3, 2]:
        return (6, count_vals)
    if flush:
        return (5, vals)
    if straight:
        return (4, vals)
    if counts[0] == 3:
        return (3, count_vals)
    if counts[:2] == [2, 2]:
        return (2, count_vals)
    if counts[0] == 2:
        return (1, count_vals)
    return (0, vals)


# ─────────────────────────────────────────────────────────────────────────────
# HAND STRENGTH ESTIMATION  (Monte-Carlo, light)
# ─────────────────────────────────────────────────────────────────────────────

def preflop_strength(hole):
    """Fast pre-flop hand strength 0-1 based on known rankings."""
    r1, r2 = sorted([RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    paired = r1 == r2
    gap = r1 - r2
    score = (r1 * 1.5 + r2) / 30  # baseline
    if paired:
        score += 0.15 + r1 * 0.01
    if suited:
        score += 0.06
    if gap <= 1 and not paired:
        score += 0.04
    return min(score, 1.0)


def estimate_win_prob(hole, community, n_opponents, samples=60):
    """Quick Monte-Carlo win-probability estimate."""
    known = set(map(tuple, hole + community))
    remaining = [c for c in make_deck() if tuple(c) not in known]
    n_opp = max(1, min(n_opponents, 5))
    wins = 0
    for _ in range(samples):
        deck = remaining[:]
        random.shuffle(deck)
        needed = 5 - len(community)
        board = community + deck[:needed]
        deck = deck[needed:]
        my_rank = hand_rank(hole + board)
        beat = True
        for _ in range(n_opp):
            opp = deck[:2]
            deck = deck[2:]
            if hand_rank(opp + board) > my_rank:
                beat = False
                break
        if beat:
            wins += 1
    return wins / samples


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def strategy_yolo(player, game_state):
    """
    THE SIMPLE ONE — Player 1.
    if my_turn:
        bet = ALL IN
    fi
    """
    return ("raise", player["chips"])


def strategy_tight_aggressive(player, game_state):
    """
    Strategy 2 — TAG (Tight-Aggressive).
    Only plays premium hands; raises hard when it does.
    Folds anything below threshold pre-flop.
    """
    hole = player["hole"]
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    chips = player["chips"]
    n_opp = game_state["active_opponents"]

    # Pre-flop: only play top-tier hands
    if len(community) == 0:
        pf = preflop_strength(hole)
        if pf < 0.68:
            if call_amount == 0:
                return ("check", 0)
            return ("fold", 0)
        win_prob = pf
    else:
        win_prob = estimate_win_prob(hole, community, n_opp, samples=50)

    if win_prob > 0.70:
        raise_size = min(chips, max(call_amount * 3, pot // 2))
        return ("raise", raise_size)
    elif win_prob > 0.45:
        if call_amount <= chips:
            return ("call", call_amount)
        return ("fold", 0)
    else:
        if call_amount == 0:
            return ("check", 0)
        return ("fold", 0)


def strategy_loose_passive(player, game_state):
    """
    Strategy 3 — Fish (Loose-Passive).
    Calls almost anything, rarely raises, bleeds chips slowly.
    Thinks every hand is 'almost good'.
    """
    hole = player["hole"]
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    chips = player["chips"]
    n_opp = game_state["active_opponents"]

    win_prob = preflop_strength(hole) if len(community) == 0 else \
               estimate_win_prob(hole, community, n_opp, samples=40)

    # Will call up to 30% of stack with any hand > 20% equity
    if win_prob > 0.20:
        affordable = call_amount <= chips * 0.30
        if call_amount == 0:
            return ("check", 0)
        if affordable:
            return ("call", call_amount)
        # Too expensive even for a fish
        return ("fold", 0)
    if call_amount == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_pot_odds_pro(player, game_state):
    """
    Strategy 4 — Pot-Odds Calculator.
    Makes every decision based on pot-odds vs equity.
    Raises when EV is strongly positive, calls when marginally +EV.
    """
    hole = player["hole"]
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    chips = player["chips"]
    n_opp = game_state["active_opponents"]

    win_prob = preflop_strength(hole) if len(community) == 0 else \
               estimate_win_prob(hole, community, n_opp, samples=50)
    pot_odds = call_amount / (pot + call_amount) if (pot + call_amount) > 0 else 0
    ev_raise = win_prob * pot - (1 - win_prob) * call_amount

    if call_amount == 0:
        # Free check or value bet
        if win_prob > 0.60:
            bet = min(chips, max(pot // 3, game_state["big_blind"]))
            return ("raise", bet)
        return ("check", 0)

    if win_prob > pot_odds + 0.10:  # comfortably +EV
        if win_prob > 0.65 and ev_raise > pot * 0.3:
            raise_to = min(chips, int(pot * 0.75))
            return ("raise", max(raise_to, call_amount))
        return ("call", call_amount)
    elif win_prob > pot_odds:  # marginally +EV
        return ("call", call_amount)
    else:
        return ("fold", 0)


def strategy_position_bluffer(player, game_state):
    """
    Strategy 5 — Position-Aware Bluffer.
    Plays position: aggressive in late position, conservative early.
    Fires bluffs when in position with fold equity.
    """
    hole = player["hole"]
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    chips = player["chips"]
    position = game_state.get("position", 3)  # 1=early, 6=late/button
    n_opp = game_state["active_opponents"]

    win_prob = preflop_strength(hole) if len(community) == 0 else \
               estimate_win_prob(hole, community, n_opp, samples=50)
    in_position = position >= 4

    if in_position:
        # Steal / semi-bluff in late position
        if win_prob > 0.40 or (n_opp <= 2 and random.random() < 0.35):
            bluff_size = min(chips, int(pot * 0.65))
            return ("raise", max(bluff_size, call_amount + game_state["big_blind"]))
        if call_amount == 0:
            return ("check", 0)
        if win_prob > 0.30:
            return ("call", call_amount)
        return ("fold", 0)
    else:
        # Early position: play tight
        if win_prob > 0.60:
            raise_size = min(chips, int(pot * 0.5))
            return ("raise", max(raise_size, call_amount))
        if win_prob > 0.40 and call_amount <= pot // 4:
            return ("call", call_amount)
        if call_amount == 0:
            return ("check", 0)
        return ("fold", 0)


def strategy_adaptive_gto(player, game_state):
    """
    Strategy 6 — Adaptive GTO-Inspired.
    Tracks pot commitment, stack-to-pot ratio, adjusts aggression
    dynamically. Mixes frequencies to remain unexploitable.
    """
    hole = player["hole"]
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    chips = player["chips"]
    n_opp = game_state["active_opponents"]
    street = len(community)  # 0=preflop, 3=flop, 4=turn, 5=river

    spr = chips / pot if pot > 0 else 999  # stack-to-pot ratio
    committed = game_state.get("player_invested", 0) / max(chips, 1)

    # Mixing frequencies: GTO uses randomization
    mix_roll = random.random()

    if street == 0:
        pf = preflop_strength(hole)
        if pf >= 0.80:  # premium
            raise_size = min(chips, game_state["big_blind"] * 3)
            return ("raise", raise_size)
        elif pf >= 0.65:  # playable
            if call_amount <= game_state["big_blind"] * 4:
                return ("call", call_amount) if call_amount > 0 else ("check", 0)
            return ("fold", 0)
        else:
            if call_amount == 0:
                return ("check", 0) if mix_roll < 0.15 else ("fold", 0)
            return ("fold", 0)

    win_prob = estimate_win_prob(hole, community, n_opp, samples=50)

    # Post-flop: SPR-based strategy
    if spr < 1.5:  # short stack, commit or fold
        if win_prob > 0.35:
            return ("raise", chips)
        return ("fold", 0) if call_amount > 0 else ("check", 0)

    if win_prob > 0.70:
        # Value bet sizing: pot * 0.6–0.9 depending on street
        bet_frac = 0.6 + (street - 3) * 0.1
        bet = min(chips, int(pot * bet_frac))
        return ("raise", max(bet, call_amount + 1))
    elif win_prob > 0.50:
        if call_amount == 0:
            if mix_roll < 0.40:  # balance with some checks
                return ("check", 0)
            return ("raise", min(chips, pot // 3))
        if call_amount <= pot // 2:
            return ("call", call_amount)
        return ("fold", 0)
    elif win_prob > 0.30 and mix_roll < 0.25:  # occasional bluff
        bluff_bet = min(chips, int(pot * 0.55))
        return ("raise", max(bluff_bet, call_amount + 1))
    else:
        if call_amount == 0:
            return ("check", 0)
        return ("fold", 0)


STRATEGIES = [
    strategy_yolo,
    strategy_tight_aggressive,
    strategy_loose_passive,
    strategy_pot_odds_pro,
    strategy_position_bluffer,
    strategy_adaptive_gto,
]

STRATEGY_NAMES = [
    "YOLO (All-In Always)",
    "Tight-Aggressive (TAG)",
    "Loose-Passive (Fish)",
    "Pot-Odds Pro",
    "Position Bluffer",
    "Adaptive GTO",
]


# ─────────────────────────────────────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND = 10
BIG_BLIND = 20


def run_hand(players, dealer_idx):
    """Run one complete hand. Mutates players[i]['chips']."""
    n = len(players)
    active = [i for i, p in enumerate(players) if p["chips"] > 0]
    if len(active) < 2:
        return

    # Post blinds
    sb_idx = active[(dealer_idx + 1) % len(active)]
    bb_idx = active[(dealer_idx + 2) % len(active)]

    pot = 0
    player_invested = [0] * n

    def post_blind(idx, amount):
        nonlocal pot
        actual = min(players[idx]["chips"], amount)
        players[idx]["chips"] -= actual
        player_invested[idx] += actual
        pot += actual
        return actual

    post_blind(sb_idx, SMALL_BLIND)
    bb_actual = post_blind(bb_idx, BIG_BLIND)

    # Deal hole cards
    deck = make_deck()
    random.shuffle(deck)
    for i in active:
        players[i]["hole"] = [deck.pop(), deck.pop()]

    community = []
    current_bet = bb_actual

    def betting_round(starting_idx_offset, community_cards):
        nonlocal pot, current_bet
        round_active = [i for i in active if players[i]["chips"] > 0 or
                        player_invested[i] > 0]
        # who can still act
        can_act = [i for i in active if players[i]["chips"] > 0]
        if len(can_act) <= 1:
            return

        order = []
        start = starting_idx_offset % len(active)
        for k in range(len(active)):
            idx = active[(start + k) % len(active)]
            if players[idx]["chips"] > 0:
                order.append(idx)

        acted = set()
        last_raiser = None
        pointer = 0

        while True:
            if pointer >= len(order):
                break
            idx = order[pointer]
            pointer += 1

            if idx in acted and idx != last_raiser:
                # everyone acted and no new raise
                if last_raiser is None:
                    break
            if players[idx]["chips"] == 0:
                acted.add(idx)
                continue

            call_amount = max(0, current_bet - player_invested[idx])
            call_amount = min(call_amount, players[idx]["chips"])

            # Build game state visible to strategy (no opponent hole cards)
            position = order.index(idx) + 1  # 1=earliest, len=latest
            game_state = {
                "community": community_cards,
                "call_amount": call_amount,
                "pot": pot,
                "big_blind": BIG_BLIND,
                "active_opponents": len([j for j in active if j != idx and
                                         (players[j]["chips"] > 0 or player_invested[j] == current_bet)]),
                "position": position,
                "player_invested": player_invested[idx],
            }

            action, amount = players[idx]["strategy"](players[idx], game_state)

            if action == "fold":
                active.remove(idx)
                order.remove(idx)
                pointer = min(pointer, len(order))
                if len(active) == 1:
                    return
            elif action == "check":
                acted.add(idx)
            elif action == "call":
                actual = min(call_amount, players[idx]["chips"])
                players[idx]["chips"] -= actual
                player_invested[idx] += actual
                pot += actual
                acted.add(idx)
            elif action == "raise":
                total_put_in = player_invested[idx] + amount
                if total_put_in <= current_bet and amount < players[idx]["chips"]:
                    # treat as call if raise amount doesn't exceed current bet
                    actual = min(call_amount, players[idx]["chips"])
                    players[idx]["chips"] -= actual
                    player_invested[idx] += actual
                    pot += actual
                    acted.add(idx)
                else:
                    # call then raise on top
                    actual_call = min(call_amount, players[idx]["chips"])
                    players[idx]["chips"] -= actual_call
                    player_invested[idx] += actual_call
                    pot += actual_call

                    raise_extra = min(amount, players[idx]["chips"])
                    players[idx]["chips"] -= raise_extra
                    player_invested[idx] += raise_extra
                    pot += raise_extra

                    if player_invested[idx] > current_bet:
                        current_bet = player_invested[idx]
                        last_raiser = idx
                        # re-open action: everyone else can respond
                        for j in order:
                            if j != idx:
                                acted.discard(j)
                    acted.add(idx)

            # Check if only one active left
            if len(active) == 1:
                return

            # End condition: all active players have acted and bet is matched
            can_still_act = [j for j in active if j not in acted and
                              players[j]["chips"] > 0]
            mismatched = [j for j in active if players[j]["chips"] > 0 and
                          player_invested[j] < current_bet]
            if not can_still_act and not mismatched:
                break

    # Pre-flop betting (start left of BB)
    start_offset = (active.index(bb_idx) + 1) % len(active) if bb_idx in active else 0
    betting_round(start_offset, community)
    if len(active) == 1:
        players[active[0]]["chips"] += pot
        return

    # Reset bets for post-flop
    current_bet = 0
    player_invested = [0] * n

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    betting_round(1, community)  # start left of dealer
    if len(active) == 1:
        players[active[0]]["chips"] += pot
        return

    current_bet = 0
    player_invested = [0] * n

    # Turn
    community.append(deck.pop())
    betting_round(1, community)
    if len(active) == 1:
        players[active[0]]["chips"] += pot
        return

    current_bet = 0
    player_invested = [0] * n

    # River
    community.append(deck.pop())
    betting_round(1, community)
    if len(active) == 1:
        players[active[0]]["chips"] += pot
        return

    # Showdown
    if len(active) > 1:
        ranks = [(hand_rank(players[i]["hole"] + community), i) for i in active]
        best = max(ranks, key=lambda x: x[0])[0]
        winners = [i for r, i in ranks if r == best]
        share = pot // len(winners)
        for w in winners:
            players[w]["chips"] += share
        remainder = pot - share * len(winners)
        if remainder and winners:
            players[winners[0]]["chips"] += remainder


def run_tournament():
    """Run one full tournament until one player has all chips. Return winner index (0-based)."""
    players = []
    for i, strat in enumerate(STRATEGIES):
        players.append({
            "name": f"P{i+1}:{STRATEGY_NAMES[i]}",
            "strategy": strat,
            "chips": STARTING_CHIPS,
            "hole": [],
        })

    dealer_idx = 0
    hand_num = 0
    max_hands = 5000  # safety cap

    while hand_num < max_hands:
        alive = [i for i, p in enumerate(players) if p["chips"] > 0]
        if len(alive) == 1:
            return alive[0]

        run_hand(players, dealer_idx)
        dealer_idx = (dealer_idx + 1) % len(players)
        hand_num += 1

    # Timed out: winner is the chip leader
    alive = [i for i, p in enumerate(players) if p["chips"] > 0]
    return max(alive, key=lambda i: players[i]["chips"])


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION + HISTOGRAM
# ─────────────────────────────────────────────────────────────────────────────

def run_simulations(n=100):
    print(f"\n{'='*65}")
    print("  TEXAS HOLD'EM TOURNAMENT SIMULATOR — 100 RUNS")
    print(f"{'='*65}")
    print(f"  Starting chips per player: {STARTING_CHIPS}")
    print(f"  Blinds: {SMALL_BLIND}/{BIG_BLIND}")
    print(f"  Players:")
    for i, name in enumerate(STRATEGY_NAMES):
        tag = " ← THE YOLO" if i == 0 else ""
        print(f"    P{i+1}: {name}{tag}")
    print(f"{'='*65}\n")

    win_counts = Counter()

    for sim in range(1, n + 1):
        winner = run_tournament()
        win_counts[winner] += 1
        if sim % 10 == 0:
            print(f"  Simulations complete: {sim}/{n}...")

    print(f"\n{'='*65}")
    print("  RESULTS — WHO IS THE LAST PLAYER STANDING?")
    print(f"{'='*65}\n")

    # Sort by player index for clean display
    results = sorted(win_counts.items(), key=lambda x: x[0])

    max_wins = max(win_counts.values()) if win_counts else 1
    bar_width = 40

    print(f"  {'Player':<40} {'Wins':>5}  {'%':>6}  Histogram")
    print(f"  {'-'*40} {'----':>5}  {'-----':>6}  {'-'*bar_width}")

    for player_idx, wins in results:
        name = STRATEGY_NAMES[player_idx]
        label = f"P{player_idx+1}: {name}"
        pct = wins / n * 100
        bar_len = int(wins / max_wins * bar_width)
        bar = "█" * bar_len
        star = " ★" if player_idx == 0 else ""
        print(f"  {label:<40} {wins:>5}  {pct:>5.1f}%  {bar}{star}")

    # Also list players who won 0
    for i in range(len(STRATEGIES)):
        if i not in win_counts:
            name = STRATEGY_NAMES[i]
            label = f"P{i+1}: {name}"
            star = " ★" if i == 0 else ""
            print(f"  {label:<40} {0:>5}  {0:>5.1f}%  {star}")

    print(f"\n{'='*65}")
    champion_idx = win_counts.most_common(1)[0][0]
    champion_wins = win_counts.most_common(1)[0][1]
    print(f"  WINNER WINNER CHICKEN DINNER: P{champion_idx+1} — {STRATEGY_NAMES[champion_idx]}")
    print(f"  ({champion_wins}/{n} tournaments = {champion_wins/n*100:.1f}% win rate)")

    yolo_wins = win_counts.get(0, 0)
    print(f"\n  YOLO (all-in every time) won: {yolo_wins}/{n} = {yolo_wins/n*100:.1f}%")

    if yolo_wins == champion_wins:
        print("  Chaos reigns supreme. The YOLO stands tall. GPT is humiliated.")
    elif yolo_wins > 0:
        print(f"  The YOLO still claimed {yolo_wins} trophies. Pure chaos vs. calculated elegance.")
    else:
        print("  The elaborate strategies crushed the YOLO. Math beats madness. GPT stays humiliated anyway.")

    print(f"{'='*65}\n")
    return win_counts


if __name__ == "__main__":
    random.seed(42)
    run_simulations(100)
