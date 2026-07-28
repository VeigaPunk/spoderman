"""
Texas Hold'em Poker Simulation
6 players, 100 tournaments, histogram of winners.
Player 1: YOLO — if my turn, bet = ALL IN
Players 2-6: Elaborate strategy bots
"""

import random
import itertools
from collections import Counter

# ─────────────────────────────────────────────────────────────
# CARD ENGINE
# ─────────────────────────────────────────────────────────────

RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

STRAIGHT_FLUSH  = 8
FOUR_OF_A_KIND  = 7
FULL_HOUSE      = 6
FLUSH           = 5
STRAIGHT        = 4
THREE_OF_A_KIND = 3
TWO_PAIR        = 2
ONE_PAIR        = 1
HIGH_CARD       = 0

def eval5(cards):
    vals  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    cnt   = Counter(vals)
    groups = sorted(cnt.values(), reverse=True)
    is_flush    = len(set(suits)) == 1
    unique_vals = sorted(set(vals), reverse=True)
    is_straight = (len(unique_vals) == 5 and unique_vals[0] - unique_vals[4] == 4)
    # Wheel: A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        is_straight = True
        vals = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return (STRAIGHT_FLUSH,  vals)
    if groups[0] == 4:
        q = [v for v, c in cnt.items() if c == 4]
        k = [v for v, c in cnt.items() if c == 1]
        return (FOUR_OF_A_KIND, sorted(q, reverse=True) + sorted(k, reverse=True))
    if groups[0] == 3 and groups[1] == 2:
        t = [v for v, c in cnt.items() if c == 3]
        p = [v for v, c in cnt.items() if c == 2]
        return (FULL_HOUSE,     sorted(t, reverse=True) + sorted(p, reverse=True))
    if is_flush:
        return (FLUSH,          vals)
    if is_straight:
        return (STRAIGHT,       vals)
    if groups[0] == 3:
        t = [v for v, c in cnt.items() if c == 3]
        k = sorted([v for v, c in cnt.items() if c == 1], reverse=True)
        return (THREE_OF_A_KIND, sorted(t, reverse=True) + k)
    if groups[0] == 2 and groups[1] == 2:
        p = sorted([v for v, c in cnt.items() if c == 2], reverse=True)
        k = [v for v, c in cnt.items() if c == 1]
        return (TWO_PAIR,       p + sorted(k, reverse=True))
    if groups[0] == 2:
        p = [v for v, c in cnt.items() if c == 2]
        k = sorted([v for v, c in cnt.items() if c == 1], reverse=True)
        return (ONE_PAIR,       sorted(p, reverse=True) + k)
    return (HIGH_CARD, vals)

def best_hand(cards):
    return max(eval5(combo) for combo in itertools.combinations(cards, 5))

# ─────────────────────────────────────────────────────────────
# MONTE CARLO HAND-STRENGTH ESTIMATOR
# ─────────────────────────────────────────────────────────────

def estimate_strength(hole, community, num_opponents=5, samples=150):
    deck = [c for c in make_deck() if c not in hole and c not in community]
    wins = 0
    for _ in range(samples):
        random.shuffle(deck)
        needed = 5 - len(community)
        board  = list(community) + deck[:needed]
        my     = best_hand(hole + board)
        idx    = needed
        lost   = False
        for _ in range(num_opponents):
            opp = best_hand([deck[idx], deck[idx+1]] + board)
            idx += 2
            if opp > my:
                lost = True
                break
        if not lost:
            wins += 1
    return wins / samples

# ─────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy_fn, name):
        self.pid         = pid
        self.chips       = chips
        self.strategy_fn = strategy_fn
        self.name        = name
        self.hole        = []
        self.folded      = False
        self.all_in      = False
        self.invested    = 0   # total chips put in this street

    def decide(self, gs):
        return self.strategy_fn(self, gs)

# ── Strategy 0: YOLO ─────────────────────────────────────────
def strategy_yolo(player, gs):
    """If my turn then bet = ALL IN fi"""
    return ("raise", player.chips)

# ── Strategy 1: GTO Position ─────────────────────────────────
def strategy_gto(player, gs):
    strength    = estimate_strength(player.hole, gs["community"],
                                    num_opponents=max(1, len(gs["live"]) - 1),
                                    samples=120)
    to_call     = gs["to_call"]
    pot         = gs["pot"]
    position    = gs["position"]
    num_live    = len(gs["live"])
    pos_bonus   = (position / max(1, num_live - 1)) * 0.08

    eff = strength + pos_bonus
    if eff > 0.75:
        bet = min(player.chips, max(pot, to_call * 3))
        return ("raise", bet)
    if eff > 0.45:
        if to_call == 0:
            return ("check", 0)
        pot_odds = to_call / (pot + to_call + 1)
        if strength > pot_odds + 0.05:
            return ("call", to_call)
        return ("fold", 0)
    if eff > 0.25 and to_call == 0:
        return ("check", 0)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ── Strategy 2: TAG (Tight-Aggressive) ───────────────────────
def strategy_tag(player, gs):
    hole      = player.hole
    community = gs["community"]
    to_call   = gs["to_call"]
    pot       = gs["pot"]
    bb        = gs["big_blind"]
    num_live  = max(1, len(gs["live"]) - 1)

    if len(community) == 0:
        r1, r2   = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited   = hole[0][1] == hole[1][1]
        hi, lo   = max(r1, r2), min(r1, r2)
        gap      = hi - lo
        is_pair  = r1 == r2
        premium  = (is_pair and hi >= 10) or (hi == 14 and lo >= 10) or (hi == 13 and lo >= 12)
        playable = is_pair or hi >= 10 or (suited and gap <= 3) or (gap <= 1 and hi >= 9)

        if premium:
            return ("raise", min(player.chips, max(to_call * 3 + 1, pot + 4 * bb)))
        if playable:
            if to_call <= 3 * bb:
                return ("call", min(to_call, player.chips))
            return ("fold", 0)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    strength = estimate_strength(hole, community, num_opponents=num_live, samples=100)
    if strength > 0.70:
        return ("raise", min(player.chips, pot + pot // 2))
    if strength > 0.40:
        if to_call == 0:
            return ("raise", min(player.chips, pot // 2)) if pot > 0 else ("check", 0)
        if to_call <= pot * 0.33:
            return ("call", min(to_call, player.chips))
        return ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ── Strategy 3: LAG (Loose-Aggressive) ───────────────────────
def strategy_lag(player, gs):
    hole      = player.hole
    community = gs["community"]
    to_call   = gs["to_call"]
    pot       = gs["pot"]
    bb        = gs["big_blind"]
    num_live  = max(1, len(gs["live"]) - 1)
    street    = len(community)

    strength = estimate_strength(hole, community, num_opponents=num_live, samples=80)
    bluff    = random.random() < 0.22 and street >= 3 and len(gs["live"]) <= 3

    if strength > 0.55 or bluff:
        bet = min(player.chips, max(pot * 2 // 3, to_call + bb * 2))
        return ("raise", bet)
    if strength > 0.30:
        if to_call == 0:
            return ("raise", min(player.chips, pot // 3 + 1))
        if to_call <= pot * 0.5:
            return ("call", min(to_call, player.chips))
        return ("fold", 0)
    if to_call == 0:
        if random.random() < 0.28 and street >= 1:
            return ("raise", min(player.chips, pot // 4 + 1))
        return ("check", 0)
    if to_call <= bb * 2:
        return ("call", min(to_call, player.chips))
    return ("fold", 0)

# ── Strategy 4: Math / Pot-Odds ──────────────────────────────
def strategy_math(player, gs):
    hole      = player.hole
    community = gs["community"]
    to_call   = gs["to_call"]
    pot       = gs["pot"]
    num_live  = max(1, len(gs["live"]) - 1)

    strength = estimate_strength(hole, community, num_opponents=num_live, samples=140)

    if to_call == 0:
        probe    = min(player.chips, pot // 2)
        ev_bet   = strength * (pot + probe) - (1 - strength) * probe
        if ev_bet > 0 and strength > 0.52:
            return ("raise", probe)
        return ("check", 0)

    pot_odds = to_call / (pot + to_call + 1)
    ev_call  = strength * (pot + to_call) - (1 - strength) * to_call

    if ev_call <= 0:
        return ("fold", 0)
    if strength > pot_odds + 0.20:
        rsize = min(player.chips, max(int(to_call * strength * 3), to_call + 1))
        return ("raise", rsize)
    if strength > pot_odds:
        return ("call", min(to_call, player.chips))
    return ("fold", 0)

# ── Strategy 5: Chameleon (Adaptive) ─────────────────────────
def strategy_chameleon(player, gs):
    hole      = player.hole
    community = gs["community"]
    to_call   = gs["to_call"]
    pot       = gs["pot"]
    bb        = gs["big_blind"]
    num_live  = max(1, len(gs["live"]) - 1)
    agg       = gs.get("agg", 0.5)

    strength = estimate_strength(hole, community, num_opponents=num_live, samples=100)

    if agg > 0.65:
        # Tight/trapping mode against maniacs
        if strength > 0.78:
            if to_call == 0:
                return ("check", 0)          # slowplay
            return ("raise", min(player.chips, pot * 2))
        if strength > 0.55:
            if to_call == 0:
                return ("check", 0)
            return ("call", min(to_call, player.chips))
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)
    else:
        # Loose/stealing mode against passives
        if strength > 0.48:
            return ("raise", min(player.chips, max(pot * 2 // 3, bb * 3)))
        if strength > 0.28:
            if to_call == 0:
                return ("raise", min(player.chips, pot // 3 + 1))
            if to_call <= pot * 0.4:
                return ("call", min(to_call, player.chips))
            return ("fold", 0)
        if to_call == 0:
            if random.random() < 0.32:
                return ("raise", min(player.chips, bb * 3))
            return ("check", 0)
        return ("fold", 0)


STRATEGIES = [
    ("YOLO All-In",      strategy_yolo),
    ("GTO Position",     strategy_gto),
    ("TAG Tight-Agg",    strategy_tag),
    ("LAG Loose-Agg",    strategy_lag),
    ("Math Pot-Odds",    strategy_math),
    ("Chameleon Adapt",  strategy_chameleon),
]

# ─────────────────────────────────────────────────────────────
# BETTING ROUND
# ─────────────────────────────────────────────────────────────

def run_betting_round(seats, community, pot, opening_bet, big_blind, agg_state):
    """
    seats        : list of Player objects that are still alive (not folded, chips>=0)
    opening_bet  : the minimum amount anyone has already put in this street (e.g. BB)
    agg_state    : [raises, total_actions] mutable list for aggression tracking
    Returns updated pot.
    """
    # Who can still act (not folded, not already all-in, has chips)
    can_act = [p for p in seats if not p.folded and not p.all_in and p.chips > 0]
    if not can_act:
        return pot

    # street_bet: how much each player has put in THIS street so far
    # (set before this function is called for blinds; otherwise 0)
    max_invested = max((p.invested for p in seats), default=0)
    current_level = max(opening_bet, max_invested)

    agg_total = agg_state[1]

    # Action order: just go left; up to 4 passes around the table
    acted    = set()
    max_loops = 4
    loop = 0

    while loop < max_loops:
        loop += 1
        progressed = False

        for p in list(can_act):
            if p.folded or p.all_in or p.chips <= 0:
                continue

            to_call = max(0, current_level - p.invested)

            # Skip if already matched the bet and already acted
            if p in acted and to_call == 0:
                continue

            live = [x for x in seats if not x.folded]
            if len(live) <= 1:
                return pot

            position = can_act.index(p) if p in can_act else 0
            gs = {
                "community": community,
                "pot":       pot,
                "to_call":   to_call,
                "live":      live,
                "big_blind": big_blind,
                "position":  position,
                "agg":       agg_state[0] / max(1, agg_state[1]),
            }

            action, amount = p.decide(gs)
            agg_state[1] += 1
            acted.add(p)
            progressed = True

            if action == "fold":
                p.folded = True
                if p in can_act:
                    can_act.remove(p)

            elif action == "check":
                pass  # only legal when to_call == 0

            elif action == "call":
                amt = min(to_call, p.chips)
                p.chips    -= amt
                p.invested += amt
                pot        += amt
                if p.chips == 0:
                    p.all_in = True
                    if p in can_act:
                        can_act.remove(p)

            elif action == "raise":
                # Total desired investment this street
                total_desired = p.invested + max(amount, to_call)
                total_desired = min(total_desired, p.invested + p.chips)
                actual_put    = total_desired - p.invested
                actual_put    = min(actual_put, p.chips)
                actual_put    = max(actual_put, 0)

                p.chips    -= actual_put
                p.invested += actual_put
                pot        += actual_put

                if p.invested > current_level:
                    current_level = p.invested
                    agg_state[0] += 1
                    # reset acted so others must respond
                    acted = {p}

                if p.chips == 0:
                    p.all_in = True
                    if p in can_act:
                        can_act.remove(p)

        # Check if everyone still in has matched
        still_active = [x for x in can_act if not x.folded and not x.all_in and x.chips > 0]
        all_matched  = all(x.invested >= current_level or x.chips == 0 for x in still_active)
        all_acted    = all(x in acted for x in still_active)

        if not progressed or (all_matched and all_acted):
            break

    return pot

# ─────────────────────────────────────────────────────────────
# HAND
# ─────────────────────────────────────────────────────────────

SMALL_BLIND    = 10
BIG_BLIND      = 20
STARTING_CHIPS = 1000

def play_hand(seats, dealer_idx):
    """Play one hand. Seats = players with chips > 0. Returns winner pid."""
    n = len(seats)
    if n < 2:
        return None

    # Reset state
    for p in seats:
        p.hole    = []
        p.folded  = False
        p.all_in  = False
        p.invested = 0

    # Deal
    deck = make_deck()
    random.shuffle(deck)
    idx = 0
    for p in seats:
        p.hole = [deck[idx], deck[idx+1]]
        idx += 2

    # Blinds
    sb_pos = (dealer_idx + 1) % n
    bb_pos = (dealer_idx + 2) % n
    sb     = seats[sb_pos]
    bb     = seats[bb_pos]

    pot = 0
    sb_amt = min(SMALL_BLIND, sb.chips)
    sb.chips   -= sb_amt
    sb.invested = sb_amt
    pot += sb_amt
    if sb.chips == 0:
        sb.all_in = True

    bb_amt = min(BIG_BLIND, bb.chips)
    bb.chips   -= bb_amt
    bb.invested = bb_amt
    pot += bb_amt
    if bb.chips == 0:
        bb.all_in = True

    agg = [0, 1]

    def live():
        return [p for p in seats if not p.folded]

    # Pre-flop: action starts left of BB
    preflop_order = seats[bb_pos+1:] + seats[:bb_pos+1]
    pot = run_betting_round(preflop_order, [], pot, BIG_BLIND, BIG_BLIND, agg)
    if len(live()) <= 1:
        winner = live()[0] if live() else max(seats, key=lambda p: p.chips)
        winner.chips += pot
        return winner.pid

    # Reset per-street investment
    for p in seats:
        p.invested = 0

    # Flop
    community = [deck[idx], deck[idx+1], deck[idx+2]]
    idx += 3
    pot = run_betting_round(seats, community, pot, 0, BIG_BLIND, agg)
    if len(live()) <= 1:
        winner = live()[0] if live() else max(seats, key=lambda p: p.chips)
        winner.chips += pot
        return winner.pid

    for p in seats:
        p.invested = 0

    # Turn
    community.append(deck[idx]); idx += 1
    pot = run_betting_round(seats, community, pot, 0, BIG_BLIND, agg)
    if len(live()) <= 1:
        winner = live()[0] if live() else max(seats, key=lambda p: p.chips)
        winner.chips += pot
        return winner.pid

    for p in seats:
        p.invested = 0

    # River
    community.append(deck[idx]); idx += 1
    pot = run_betting_round(seats, community, pot, 0, BIG_BLIND, agg)

    survivors = live()
    if not survivors:
        # everyone somehow folded — give pot to richest (shouldn't happen)
        winner = max(seats, key=lambda p: p.chips)
        winner.chips += pot
        return winner.pid
    if len(survivors) == 1:
        survivors[0].chips += pot
        return survivors[0].pid

    # Showdown
    scored = [(p, best_hand(p.hole + community)) for p in survivors]
    top_score = max(s for _, s in scored)
    winners   = [p for p, s in scored if s == top_score]
    share     = pot // len(winners)
    rem       = pot % len(winners)
    for w in winners:
        w.chips += share
    if rem:
        winners[0].chips += rem

    return winners[0].pid

# ─────────────────────────────────────────────────────────────
# TOURNAMENT
# ─────────────────────────────────────────────────────────────

def play_tournament(all_players):
    dealer = 0
    for hand_num in range(3000):
        seats = [p for p in all_players if p.chips > 0]
        if len(seats) == 1:
            return seats[0].pid
        if len(seats) == 0:
            break
        play_hand(seats, dealer % len(seats))
        dealer += 1

    # Timeout: richest wins
    return max(all_players, key=lambda p: p.chips).pid

# ─────────────────────────────────────────────────────────────
# SIMULATION
# ─────────────────────────────────────────────────────────────

def run_simulations(num_sims=100):
    wins = {i+1: 0 for i in range(6)}
    names = {i+1: STRATEGIES[i][0] for i in range(6)}

    print(f"\n{'='*62}")
    print(f"  Texas Hold'em — {num_sims} Tournaments")
    print(f"{'='*62}")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  ← THE YOLO MENACE" if i == 0 else ""
        print(f"  Player {i+1}: {name}{tag}")
    print(f"  Starting chips : {STARTING_CHIPS}")
    print(f"  Blinds         : {SMALL_BLIND}/{BIG_BLIND}")
    print(f"{'='*62}\n")

    for sim in range(num_sims):
        players = [
            Player(i+1, STARTING_CHIPS, STRATEGIES[i][1], STRATEGIES[i][0])
            for i in range(6)
        ]
        winner = play_tournament(players)
        if winner:
            wins[winner] += 1

        if (sim + 1) % 10 == 0:
            print(f"  ... {sim+1}/{num_sims} done", flush=True)

    return wins, names


def print_histogram(wins, names, num_sims):
    print(f"\n{'='*62}")
    print(f"  WINNER WINNER CHICKEN DINNER — {num_sims}-Tournament Results")
    print(f"{'='*62}")

    max_w    = max(wins.values()) if any(wins.values()) else 1
    bar_max  = 38

    for pid in sorted(wins.keys()):
        w    = wins[pid]
        pct  = w / num_sims * 100
        bar  = "█" * int(w / max_w * bar_max)
        tag  = "  ★ YOLO" if pid == 1 else ""
        print(f"  P{pid} {names[pid][:20]:<20}{tag}")
        print(f"     [{bar:<{bar_max}}] {w:>3} wins  {pct:5.1f}%")
        print()

    print(f"{'='*62}")
    top      = max(wins, key=wins.get)
    yolo_w   = wins[1]
    yolo_pct = yolo_w / num_sims * 100
    yolo_rank = sorted(wins.values(), reverse=True).index(yolo_w) + 1

    print(f"  Champion: Player {top} — {names[top]}  ({wins[top]} wins)")
    print(f"  YOLO:     {yolo_w} wins ({yolo_pct:.1f}%) — rank #{yolo_rank}/6")

    if yolo_rank == 1:
        verdict = "Chaos wins. Even Sufflair GPT couldn't predict this."
    elif yolo_rank == 2:
        verdict = "2nd place. A broken clock is right twice a day."
    elif yolo_rank >= 5:
        verdict = f"Ranked #{yolo_rank}/6. Sufflair GPT would be proud of this failure."
    else:
        verdict = f"#{yolo_rank}/6. Strategy > luck. Sufflair GPT: thoroughly humiliated."

    print(f"\n  Verdict: {verdict}")
    print(f"{'='*62}\n")


if __name__ == "__main__":
    random.seed(42)
    wins, names = run_simulations(100)
    print_histogram(wins, names, 100)
