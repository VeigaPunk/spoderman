#!/usr/bin/env python3
"""
Texas Hold'em 100-simulation tournament.
Player 1 = "The Maniac"  (always shoves all-in)
Players 2-6 = five elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────────────────────────────────────
# Card primitives
# ─────────────────────────────────────────────────────────────────────────────
RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RANK_V = {r: i for i, r in enumerate(RANKS, 2)}   # '2'->2 … 'A'->14


def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


# ─────────────────────────────────────────────────────────────────────────────
# 5-card hand evaluator  (returns comparable tuple; larger = better)
# ─────────────────────────────────────────────────────────────────────────────
def best_hand(cards):
    best = None
    for five in combinations(cards, 5):
        s = _score5(five)
        if best is None or s > best:
            best = s
    return best


def _score5(cards):
    ranks  = sorted([RANK_V[c[0]] for c in cards], reverse=True)
    suits  = [c[1] for c in cards]
    flush  = len(set(suits)) == 1
    uniq   = len(set(ranks))
    straight = uniq == 5 and (ranks[0] - ranks[4] == 4)
    if uniq == 5 and set(ranks) == {14, 2, 3, 4, 5}:   # wheel
        straight = True; ranks = [5, 4, 3, 2, 1]
    cnt    = Counter(ranks)
    groups = [r for _, r in sorted(((v, k) for k, v in cnt.items()), reverse=True)]
    freqs  = sorted(cnt.values(), reverse=True)
    if flush and straight:  return (8, ranks)
    if freqs[0] == 4:       return (7, groups)
    if freqs[:2] == [3, 2]: return (6, groups)
    if flush:               return (5, ranks)
    if straight:            return (4, ranks)
    if freqs[0] == 3:       return (3, groups)
    if freqs[:2] == [2, 2]: return (2, groups)
    if freqs[0] == 2:       return (1, groups)
    return (0, ranks)


# ─────────────────────────────────────────────────────────────────────────────
# Fast hand-strength: uses hand-category + rank to produce 0.0–1.0
# No Monte Carlo needed — deterministic relative strength.
# ─────────────────────────────────────────────────────────────────────────────
def hand_strength(hole, community):
    """
    Returns float 0–1 representing absolute hand strength.
    Pre-flop: Chen formula normalised.
    Post-flop: rank category (0-8) mapped to [0,1] with rank tie-break.
    """
    if not community:
        return _chen_strength(hole)
    all_cards = hole + community
    score = best_hand(all_cards)
    category = score[0]        # 0=high card … 8=straight flush
    # sub-strength from top ranks in the group
    top = score[1][0] if score[1] else 2
    sub = (top - 2) / 12.0    # 0–1 within category
    return (category + sub) / 8.5   # normalise to ~0–1


def _chen_strength(hole):
    """Chen formula normalised to 0–1 (preflop only)."""
    r1, r2 = sorted([RANK_V[hole[0][0]], RANK_V[hole[1][0]]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    # Base score = higher card
    score = {14: 10, 13: 8, 12: 7, 11: 6, 10: 5}.get(r1, r1 / 2.0)
    if r1 == r2:  score = max(score * 2, 5)
    if suited:    score += 2
    gap = r1 - r2
    if gap == 0:  pass
    elif gap == 1: score += 1
    elif gap == 2: pass
    elif gap == 3: score -= 1
    elif gap == 4: score -= 2
    else:          score -= 4
    if r1 != r2 and r2 >= 11: score += 1
    return max(0.0, min(1.0, score / 20.0))


# ─────────────────────────────────────────────────────────────────────────────
# Player
# ─────────────────────────────────────────────────────────────────────────────
class Player:
    __slots__ = ("pid", "chips", "strategy_fn", "hole",
                 "folded", "bet_this_street", "all_in",
                 "aggression_score", "hands_seen")

    def __init__(self, pid, chips, fn):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = fn
        self.hole = []
        self.folded = False
        self.bet_this_street = 0
        self.all_in = False
        self.aggression_score = 0.5   # Bayesian tracking
        self.hands_seen = 0

    def reset(self):
        self.hole = []; self.folded = False
        self.bet_this_street = 0; self.all_in = False


# ─────────────────────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════
#  STRATEGY 1 — THE MANIAC   (Player 1)
#  if my_turn:
#      bet = all_in
#  fi
# ══════════════════════════════════════════════════════════════
def s_maniac(p, gs):
    return ("raise", p.chips)


# ══════════════════════════════════════════════════════════════
#  STRATEGY 2 — GTO Tight-Aggressive (TAG)
#  Strong pre-flop range, pot-sized value bets, disciplined folds
# ══════════════════════════════════════════════════════════════
def s_tag(p, gs):
    strength = hand_strength(p.hole, gs["community"])
    pot       = gs["pot"]
    call_amt  = gs["call_amount"]
    bb        = gs["big_blind"]

    # Premium — raise big
    if strength >= 0.70:
        return ("raise", max(bb, int(pot * 0.80)))
    # Strong — value bet
    if strength >= 0.52:
        if call_amt == 0:
            return ("raise", max(bb, int(pot * 0.55)))
        return ("call", call_amt)
    # Marginal — check/call small
    if strength >= 0.38:
        if call_amt == 0:
            return ("check", 0)
        if call_amt <= pot * 0.25:
            return ("call", call_amt)
        return ("fold", 0)
    # Weak
    if call_amt == 0:
        return ("check", 0)
    return ("fold", 0)


# ══════════════════════════════════════════════════════════════
#  STRATEGY 3 — CALLING STATION (Loose-Passive)
#  Almost never folds, almost never raises, bleeds chips slowly
# ══════════════════════════════════════════════════════════════
def s_station(p, gs):
    strength = hand_strength(p.hole, gs["community"])
    pot       = gs["pot"]
    call_amt  = gs["call_amount"]
    bb        = gs["big_blind"]

    if call_amt == 0:
        if strength >= 0.80 and random.random() < 0.4:
            return ("raise", max(bb, int(pot * 0.25)))
        return ("check", 0)

    # Very loose call threshold
    max_call_ratio = 0.55 + strength * 0.3
    if call_amt <= (pot + call_amt) * max_call_ratio:
        return ("call", call_amt)
    if call_amt <= bb:
        return ("call", call_amt)
    return ("fold", 0)


# ══════════════════════════════════════════════════════════════
#  STRATEGY 4 — LAG (Loose-Aggressive)
#  Bluffs often in position, applies relentless pressure,
#  semi-bluffs draws, polarised range on river
# ══════════════════════════════════════════════════════════════
def s_lag(p, gs):
    strength = hand_strength(p.hole, gs["community"])
    pot       = gs["pot"]
    call_amt  = gs["call_amount"]
    bb        = gs["big_blind"]
    position  = gs.get("position", 1)   # 0=early 1=mid 2=late

    # Bluff equity grows with position
    effective = strength + 0.10 * position

    if effective >= 0.62:
        bet = int(pot * (0.65 + 0.15 * random.random()))
        return ("raise", max(bb, bet))

    if effective >= 0.42:
        if call_amt == 0:
            if position >= 1:
                return ("raise", max(bb, int(pot * 0.50)))
            return ("check", 0)
        if call_amt <= pot * 0.45:
            return ("call", call_amt)
        if position == 2 and random.random() < 0.30:
            return ("raise", int(call_amt * 2.5))
        return ("fold", 0)

    if call_amt == 0:
        if position == 2 and random.random() < 0.38:
            return ("raise", max(bb, int(pot * 0.60)))
        return ("check", 0)
    return ("fold", 0)


# ══════════════════════════════════════════════════════════════
#  STRATEGY 5 — BAYESIAN ADAPTIVE
#  Tracks each opponent's aggression score, updates beliefs,
#  adjusts call thresholds and sizing dynamically
# ══════════════════════════════════════════════════════════════
def s_bayesian(p, gs):
    strength  = hand_strength(p.hole, gs["community"])
    pot       = gs["pot"]
    call_amt  = gs["call_amount"]
    bb        = gs["big_blind"]
    opp_agg   = gs.get("opp_aggression", {})

    # Weighted average aggression of opponents still in
    avg_agg = (sum(opp_agg.values()) / len(opp_agg)) if opp_agg else 0.5

    # Against aggressive opponents, widen fold range (they bluff less)
    # Against passive opponents, call wider (they only bet strong)
    fold_threshold  = 0.28 + 0.22 * avg_agg    # 0.28 – 0.50
    value_threshold = 0.55 + 0.10 * avg_agg    # 0.55 – 0.65

    if strength >= value_threshold:
        sizing = 0.65 if avg_agg < 0.60 else 0.50
        return ("raise", max(bb, int(pot * sizing)))

    if strength >= fold_threshold:
        if call_amt == 0:
            bet = int(pot * (0.35 + 0.15 * (1 - avg_agg)))
            return ("raise", max(bb, bet))
        # Pot-odds check
        if call_amt <= pot * (0.45 - 0.15 * avg_agg):
            return ("call", call_amt)
        return ("fold", 0)

    if call_amt == 0:
        return ("check", 0)
    return ("fold", 0)


# ══════════════════════════════════════════════════════════════
#  STRATEGY 6 — ICM STACK-AWARE
#  Tournament equity: short stack shoves/folds; big stack bullies;
#  medium stack plays solid +EV poker
# ══════════════════════════════════════════════════════════════
def s_icm(p, gs):
    strength     = hand_strength(p.hole, gs["community"])
    pot          = gs["pot"]
    call_amt     = gs["call_amount"]
    bb           = gs["big_blind"]
    stack_sizes  = gs.get("stack_sizes", {})

    total = sum(stack_sizes.values()) or (p.chips * 6)
    share = p.chips / total if total > 0 else 1 / 6

    if share < 0.10:                          # --- short stack: shove/fold
        if strength >= 0.44:
            return ("raise", p.chips)
        if call_amt == 0:
            return ("check", 0)
        return ("fold", 0)

    if share >= 0.40:                         # --- chip leader: bully
        if strength >= 0.38 and call_amt == 0:
            return ("raise", max(bb, int(pot * 0.75)))
        if strength >= 0.52:
            return ("raise", max(bb, int(pot * 0.55)))
        if call_amt > 0 and strength >= 0.33:
            return ("call", call_amt)
        if call_amt == 0:
            return ("check", 0)
        return ("fold", 0)

    # --- medium stack: clean +EV
    if strength >= 0.65:
        return ("raise", max(bb, int(pot * 0.65)))
    if strength >= 0.46:
        if call_amt == 0:
            return ("raise", max(bb, int(pot * 0.40)))
        if call_amt <= pot * 0.35:
            return ("call", call_amt)
        return ("fold", 0)
    if call_amt == 0:
        return ("check", 0)
    return ("fold", 0)


# ─────────────────────────────────────────────────────────────────────────────
# Strategy registry
# ─────────────────────────────────────────────────────────────────────────────
STRATEGIES = [s_maniac, s_tag, s_station, s_lag, s_bayesian, s_icm]
NAMES = [
    "Maniac (ALWAYS ALL-IN)",
    "TAG  (tight-aggressive)",
    "Calling Station       ",
    "LAG  (loose-aggressive)",
    "Bayesian Adaptive     ",
    "ICM  Stack-Aware      ",
]


# ─────────────────────────────────────────────────────────────────────────────
# Betting-round engine
# ─────────────────────────────────────────────────────────────────────────────
def betting_round(players, community, pot, bb, game_meta):
    """
    One betting round.  Returns new pot total.
    `players` is already filtered to non-busted players.
    """
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) <= 1:
        return pot

    for p in players:
        p.bet_this_street = 0

    current_bet = 0
    opp_agg     = game_meta.setdefault("opp_agg",
                    {p.pid: 0.5 for p in players})

    def state(player, pos):
        stacks = {p.pid: p.chips for p in players if not p.folded}
        num_a  = sum(1 for p in players if not p.folded and not p.all_in)
        return {
            "community":     community,
            "pot":           pot,
            "call_amount":   max(0, current_bet - player.bet_this_street),
            "big_blind":     bb,
            "position":      pos,
            "num_active":    max(2, num_a),
            "opp_aggression": {pid: v for pid, v in opp_agg.items()
                                if pid != player.pid},
            "stack_sizes":   stacks,
        }

    queue = [p for p in players if not p.folded and not p.all_in]
    safety = 0

    while queue and safety < len(players) * 6:
        safety += 1
        player = queue.pop(0)
        if player.folded or player.all_in:
            continue

        pos    = min(2, queue.index(queue[0]) if queue else 0)
        action, amount = player.strategy_fn(player, state(player, pos))
        call_needed    = max(0, current_bet - player.bet_this_street)

        if action == "fold":
            player.folded = True

        elif action in ("check", "call"):
            actual = min(call_needed, player.chips)
            player.chips           -= actual
            player.bet_this_street += actual
            pot                    += actual
            if player.chips == 0:
                player.all_in = True
            # re-queue if someone raised after them — handled below

        elif action == "raise":
            target   = max(int(amount), current_bet + bb)
            target   = min(target, player.chips + player.bet_this_street)
            spend    = min(target - player.bet_this_street, player.chips)
            player.chips           -= spend
            player.bet_this_street += spend
            pot                    += spend
            if player.bet_this_street > current_bet:
                current_bet = player.bet_this_street
                # Re-queue everyone who hasn't matched yet
                for p in players:
                    if (not p.folded and not p.all_in
                            and p.pid != player.pid
                            and p.bet_this_street < current_bet
                            and p not in queue):
                        queue.append(p)
                opp_agg[player.pid] = min(1.0,
                    opp_agg.get(player.pid, 0.5) + 0.08)
            if player.chips == 0:
                player.all_in = True

    game_meta["opp_agg"] = opp_agg
    return pot


# ─────────────────────────────────────────────────────────────────────────────
# Full hand
# ─────────────────────────────────────────────────────────────────────────────
def play_hand(players, dealer_idx, bb):
    """
    Play one complete Texas Hold'em hand.
    `players` = list of all Player objects (busted ones already removed).
    Mutates player.chips in place.
    """
    n = len(players)
    if n < 2:
        return

    for p in players:
        p.reset()

    deck = make_deck()
    random.shuffle(deck)
    community = []
    pot       = 0
    meta      = {}
    card_ptr  = [0]

    def deal(k=1):
        cards = deck[card_ptr[0]: card_ptr[0] + k]
        card_ptr[0] += k
        return cards

    # ── blinds ──────────────────────────────────────────────
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n
    sb     = bb // 2

    def post(p, amt):
        nonlocal pot
        actual = min(amt, p.chips)
        p.chips -= actual
        p.bet_this_street = actual
        pot += actual
        if p.chips == 0:
            p.all_in = True

    post(players[sb_idx], sb)
    post(players[bb_idx], bb)

    # ── deal hole cards ──────────────────────────────────────
    for p in players:
        p.hole = deal(2)

    # ── pre-flop: current bet = bb ───────────────────────────
    for p in players:
        if p.bet_this_street < bb and not p.all_in and not p.folded:
            pass   # betting round handles it

    # Pre-flop: queue starts after bb, current_bet already = bb
    # We re-use betting_round but seed current_bet via SB/BB bets
    pot = betting_round(players, community, pot, bb, meta)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot; return

    # ── flop ────────────────────────────────────────────────
    community.extend(deal(3))
    for p in players: p.bet_this_street = 0
    pot = betting_round(players, community, pot, bb, meta)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot; return

    # ── turn ─────────────────────────────────────────────────
    community.extend(deal(1))
    for p in players: p.bet_this_street = 0
    pot = betting_round(players, community, pot, bb, meta)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot; return

    # ── river ────────────────────────────────────────────────
    community.extend(deal(1))
    for p in players: p.bet_this_street = 0
    pot = betting_round(players, community, pot, bb, meta)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot; return

    # ── showdown ─────────────────────────────────────────────
    best  = None
    winners = []
    for p in alive:
        r = best_hand(p.hole + community)
        if best is None or r > best:
            best = r; winners = [p]
        elif r == best:
            winners.append(p)

    share = pot // len(winners)
    rem   = pot % len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += rem


# ─────────────────────────────────────────────────────────────────────────────
# Tournament (play until one player has all chips)
# ─────────────────────────────────────────────────────────────────────────────
def play_tournament(starting_chips=10_000, init_bb=100):
    players = [Player(i, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer  = 0
    bb      = init_bb
    hand_no = 0

    while True:
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid
        if len(alive) == 0:
            return 0   # shouldn't happen

        play_hand(alive, dealer % len(alive), bb)
        dealer  += 1
        hand_no += 1

        # Escalate blinds every 80 hands to prevent runaway games
        if hand_no % 80 == 0:
            bb = min(bb * 2, starting_chips // 4)

        # Hard safety cap
        if hand_no > 3000:
            alive = [p for p in players if p.chips > 0]
            return max(alive, key=lambda p: p.chips).pid


# ─────────────────────────────────────────────────────────────────────────────
# 100 simulations
# ─────────────────────────────────────────────────────────────────────────────
def run_sims(n=100):
    wins = Counter()
    for i in range(n):
        w = play_tournament()
        wins[w] += 1
        if (i + 1) % 25 == 0:
            print(f"  ... {i+1}/{n} tournaments complete")
    return wins


# ─────────────────────────────────────────────────────────────────────────────
# Histogram
# ─────────────────────────────────────────────────────────────────────────────
BAR_WIDTH = 48

def histogram(wins, n=100):
    max_w = max(wins.values()) if wins else 1

    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + " 🏆  WINNER WINNER CHICKEN DINNER  — 100 TOURNAMENT RESULTS  🏆".center(78) + "║")
    print("╠" + "═" * 78 + "╣")
    print(f"║  {'Player & Strategy':<36} {'W':>3}  {'%':>5}  Histogram" + " " * 18 + "║")
    print("╠" + "─" * 78 + "╣")

    for pid in range(6):
        w     = wins.get(pid, 0)
        pct   = w / n * 100
        bar   = "█" * int(w / max_w * BAR_WIDTH)
        tag   = " ← THE MANIAC (always all-in)" if pid == 0 else ""
        label = f"P{pid+1}  {NAMES[pid]}"
        line  = f"║  {label:<36} {w:>3}  {pct:>4.1f}%  {bar}"
        # pad to width
        line  = line.ljust(79) + "║"
        print(line)
        if tag:
            print(f"║  {'':36}         {tag}".ljust(79) + "║")

    print("╠" + "═" * 78 + "╣")

    best = max(wins, key=wins.get)
    print(f"║  Champion: P{best+1} — {NAMES[best].strip():<52} ║")
    if best == 0:
        print(f"║  GPT-level 'elaborate' strategies got HUMILIATED by the braindead maniac.  ║")
    else:
        print(f"║  The all-in maniac got crushed by P{best+1}.  RIP Maniac. RIP suflair-GPT.  ║")
    print("╚" + "═" * 78 + "╝")
    print()

    # Dot-plot (each char = 1 win)
    print("  Dot-plot  (each '■' = 1 tournament win out of 100)\n")
    for pid in range(6):
        w     = wins.get(pid, 0)
        label = f"P{pid+1}"
        row   = "■" * w + "·" * (n - w)
        print(f"  {label}  {row[:50]}  {w:>2}W")
        if n > 50:
            print(f"       {row[50:]}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    random.seed(42)
    print("\n  Texas Hold'em Showdown — 6 players, 100 tournaments")
    print("  Player 1 = Maniac (all-in every hand)")
    print("  Players 2-6 = TAG, Calling Station, LAG, Bayesian, ICM\n")
    wins = run_sims(100)
    histogram(wins)
