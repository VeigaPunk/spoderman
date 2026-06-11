"""
Texas Hold'em Poker Simulation — 6 players, 100 games
Player 1  = The Maniac (always all-in)
Players 2-6 = 5 elaborate strategies
"""
import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────
# Card primitives
# ─────────────────────────────────────────────
RANKS   = "23456789TJQKA"
SUITS   = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ─────────────────────────────────────────────
# Hand evaluator (best 5 from 7)
# ─────────────────────────────────────────────
def score_five(cards):
    ranks  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits  = [c[1] for c in cards]
    flush  = len(set(suits)) == 1
    uniq   = sorted(set(ranks), reverse=True)
    straight = len(uniq) == 5 and (uniq[0] - uniq[4] == 4)
    if set(ranks) == {14, 2, 3, 4, 5}:
        straight = True
        ranks = [5, 4, 3, 2, 1]
    cnt = Counter(ranks)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    freqs  = sorted(cnt.values(), reverse=True)
    if straight and flush: return (8, ranks)
    if freqs[0] == 4:      return (7, groups)
    if freqs[:2] == [3,2]: return (6, groups)
    if flush:              return (5, ranks)
    if straight:           return (4, ranks)
    if freqs[0] == 3:      return (3, groups)
    if freqs[:2] == [2,2]: return (2, groups)
    if freqs[0] == 2:      return (1, groups)
    return (0, ranks)

def best_hand(hole, board):
    return max(score_five(c) for c in combinations(hole + board, 5))

# ─────────────────────────────────────────────
# Fast equity estimator (MC, 60 samples)
# ─────────────────────────────────────────────
def equity(hole, board, n_opp, n=60):
    known   = set(map(tuple, hole + board))
    deck    = [c for c in make_deck() if tuple(c) not in known]
    needed  = 5 - len(board)
    wins = 0
    for _ in range(n):
        sample  = random.sample(deck, needed + 2 * n_opp)
        full_board = board + sample[:needed]
        my  = best_hand(hole, full_board)
        win = True
        for i in range(n_opp):
            opp_hole = [sample[needed + 2*i], sample[needed + 2*i + 1]]
            if best_hand(opp_hole, full_board) > my:
                win = False
                break
        if win:
            wins += 1
    return wins / n

def preflop_strength(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1,r2), min(r1,r2)
    s = (hi + lo) / 28.0
    if hi == lo:        s += 0.30
    if suited:          s += 0.05
    if hi - lo <= 2:    s += 0.05
    return min(s, 1.0)

def pot_odds(to_call, pot):
    return pot / (pot + to_call) if to_call > 0 else 1.0

# ═══════════════════════════════════════════
#  STRATEGIES
# ═══════════════════════════════════════════

# ── P1: The Maniac ────────────────────────
def strategy_maniac(p, gs):
    """Always shove. YOLO."""
    return ("raise", p["chips"])

# ── P2: GTO Approximator ──────────────────
def strategy_gto(p, gs):
    """
    Range-based pre-flop, pot-sized post-flop value bets,
    alpha-balanced bluffing frequency, mixed-strategy randomisation.
    """
    hole, board = p["hole"], gs["community"]
    to_call, pot, chips = gs["to_call"], gs["pot"], p["chips"]
    street, n_opp, bb   = gs["street"], gs["n_opp"], gs["bb"]

    if street == "preflop":
        s = preflop_strength(hole)
        if s > 0.75:
            return ("raise", min(chips, max(to_call*3, bb*3)))
        if s > 0.45:
            if to_call <= bb*4:
                return ("call", to_call)
        return ("fold", 0)

    eq = equity(hole, board, n_opp)
    req = pot_odds(to_call, pot)

    if eq > 0.70:
        mult = 1.5 if random.random() < 0.15 else 0.75
        bet  = min(chips, max(int(pot * mult), to_call + 1))
        return ("raise", bet)
    if eq > req + 0.05:
        if to_call == 0:
            return ("raise", min(chips, int(pot * 0.5)))
        return ("call", to_call)
    if eq < 0.25 and to_call > 0:
        bluff_freq = eq / (1 - eq + 0.001)
        if random.random() < bluff_freq and chips > pot:
            return ("raise", min(chips, int(pot * 0.75)))
        return ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    return ("call", to_call) if eq >= req else ("fold", 0)

# ── P3: Tight Aggressor ───────────────────
def strategy_tight_aggressor(p, gs):
    """
    Plays only top-20% preflop hands. Fires big c-bets on strong boards.
    Surrenders immediately when equity drops below threshold.
    """
    hole, board = p["hole"], gs["community"]
    to_call, pot, chips = gs["to_call"], gs["pot"], p["chips"]
    street, n_opp, bb   = gs["street"], gs["n_opp"], gs["bb"]

    if street == "preflop":
        s = preflop_strength(hole)
        thresh = 0.68 + n_opp * 0.015
        if s > thresh:
            return ("raise", min(chips, bb * (3 + n_opp)))
        return ("fold", 0)

    eq = equity(hole, board, n_opp)
    if eq > 0.55:
        if to_call == 0:
            return ("raise", min(chips, int(pot * 0.65)))
        if to_call <= pot * 0.5:
            return ("call", to_call)
        if eq > 0.70:
            return ("raise", min(chips, to_call + int(pot * 0.5)))
        return ("call", to_call)
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

# ── P4: Adaptive Chameleon ────────────────
def strategy_chameleon(p, gs):
    """
    Tracks table aggression. Bluffs loose tables; value-bets tight ones.
    Uses SPR to decide hand commitment. Steals blinds vs passive lineups.
    """
    hole, board = p["hole"], gs["community"]
    to_call, pot, chips = gs["to_call"], gs["pot"], p["chips"]
    street, n_opp, bb   = gs["street"], gs["n_opp"], gs["bb"]
    agg = gs.get("opp_agg", 0.5)
    spr = chips / max(pot, 1)

    if street == "preflop":
        s = preflop_strength(hole)
        if agg < 0.4 and s > 0.35 and n_opp <= 2:
            return ("raise", min(chips, bb*3))
        if s > 0.65:
            return ("raise", min(chips, bb * (3 + int((1-agg)*3))))
        if s > 0.50 and to_call <= bb*2:
            return ("call", to_call)
        return ("fold", 0)

    eq = equity(hole, board, n_opp)
    if spr < 2 and eq > 0.45:
        return ("raise", chips)

    if agg > 0.6:
        if eq > 0.60:
            return ("raise", min(chips, max(int(pot*(0.5+agg*0.3)), to_call+1)))
        if to_call > 0 and eq < 0.45:
            return ("fold", 0)
        if to_call == 0:
            return ("check", 0)
        return ("call", to_call) if eq >= pot_odds(to_call, pot) else ("fold", 0)
    else:
        if random.random() < 0.30 and chips > pot*0.5 and to_call == 0:
            return ("raise", min(chips, int(pot*0.60)))
        if eq > 0.50:
            if to_call == 0:
                return ("raise", min(chips, int(pot*0.55)))
            return ("call", to_call)
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

# ── P5: Pot-Odds Mathematician ────────────
def strategy_mathematician(p, gs):
    """
    Pure EV calculation. Counts draw outs. Never bluffs.
    Folds anything with negative implied EV. Bets exactly for value.
    """
    hole, board = p["hole"], gs["community"]
    to_call, pot, chips = gs["to_call"], gs["pot"], p["chips"]
    street, n_opp, bb   = gs["street"], gs["n_opp"], gs["bb"]

    if street == "preflop":
        r1,r2 = sorted([RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]], reverse=True)
        pair    = r1 == r2
        suited  = hole[0][1] == hole[1][1]
        conn    = abs(r1-r2) <= 2
        bway    = r1 >= 11 and r2 >= 10
        if pair and r1 >= 8:
            return ("raise", min(chips, bb*4))
        if bway and to_call <= bb*3:
            return ("call", to_call)
        if suited and conn and r1 >= 7 and to_call <= bb*2:
            return ("call", to_call)
        if pair and to_call <= bb*2:
            return ("call", to_call)
        return ("fold", 0)

    eq  = equity(hole, board, n_opp)
    ev  = eq * pot - (1 - eq) * to_call

    if ev > 0:
        if to_call == 0:
            return ("raise", min(chips, int(pot*0.6)))
        if eq > 0.65:
            return ("raise", min(chips, to_call + int(pot*0.5)))
        return ("call", to_call)

    # Draw implied odds
    outs   = _count_outs(hole, board)
    left   = 52 - len(hole) - len(board)
    draw_eq = outs / max(left, 1)
    impl_ev = draw_eq * (pot + chips*0.3) - (1-draw_eq)*to_call
    if impl_ev > 0 and street != "river":
        return ("call", to_call)

    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)

def _count_outs(hole, board):
    cards = hole + board
    ranks = [RANK_VAL[c[0]] for c in cards]
    suits = [c[1] for c in cards]
    outs  = 0
    sc    = Counter(suits)
    if max(sc.values()) == 4:
        outs += 9
    uniq = sorted(set(ranks))
    for i in range(len(uniq)-3):
        w = uniq[i:i+4]
        if w[-1]-w[0] == 3: outs += 8
        if w[-1]-w[0] == 4: outs += 4
    return min(outs, 21)

# ── P6: Stack-Pressure Specialist ─────────
def strategy_stack_pressure(p, gs):
    """
    Short-stack: push-fold Nash ranges. Deep-stack: speculative play.
    Applies ICM pressure when heads-up. Targets elimination spots.
    """
    hole, board = p["hole"], gs["community"]
    to_call, pot, chips = gs["to_call"], gs["pot"], p["chips"]
    street, n_opp, bb   = gs["street"], gs["n_opp"], gs["bb"]
    avg_stack = gs.get("avg_stack", chips)
    stack_bb  = chips / max(bb, 1)
    rel       = chips / max(avg_stack, 1)

    if street == "preflop":
        s = preflop_strength(hole)
        if stack_bb < 15:
            thresh = max(0.30, 0.75 - stack_bb*0.03)
            return ("raise", chips) if s > thresh else ("fold", 0)
        if rel > 1.5:
            if s > 0.40 and to_call <= bb*3:
                return ("call", to_call)
            if s > 0.65:
                return ("raise", min(chips, bb*4))
            return ("fold", 0)
        if s > 0.60:
            return ("raise", min(chips, bb*3))
        if s > 0.45 and to_call <= bb*2:
            return ("call", to_call)
        return ("fold", 0)

    eq = equity(hole, board, n_opp)
    icm = 0.85 if n_opp <= 1 else 1.0

    if eq * icm > 0.65:
        if to_call == 0:
            return ("raise", min(chips, int(pot*0.80)))
        return ("raise", min(chips, to_call*3))
    if eq * icm > 0.50:
        if to_call == 0:
            return ("raise", min(chips, int(pot*0.45)))
        if to_call <= pot*0.4:
            return ("call", to_call)
        return ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    return ("call", to_call) if eq >= pot_odds(to_call, pot) else ("fold", 0)

# ─────────────────────────────────────────────
# Strategy registry
# ─────────────────────────────────────────────
STRATEGIES = [
    ("The Maniac",              strategy_maniac),
    ("GTO Approximator",        strategy_gto),
    ("Tight Aggressor",         strategy_tight_aggressor),
    ("Adaptive Chameleon",      strategy_chameleon),
    ("Pot-Odds Mathematician",  strategy_mathematician),
    ("Stack-Pressure Spec.",    strategy_stack_pressure),
]

# ─────────────────────────────────────────────
# Betting round — clean action-queue model
# ─────────────────────────────────────────────
def do_betting_round(players, street, start_pos, pot, bb, hand_num, community):
    """
    Returns updated pot.  Modifies players in-place (chips, folded, all_in, bet_round).
    Uses a proper action queue: after a raise, all others get another chance.
    Max raises per street capped at 4 to prevent infinite loops.
    """
    live = [p for p in players if not p["folded"] and p["chips"] > 0]
    if len(live) <= 1:
        return pot

    n = len(players)
    # Build order starting from start_pos, wrapping
    order = []
    for i in range(n):
        idx = (start_pos + i) % n
        order.append(idx)

    max_bet      = max(p["bet_round"] for p in players)
    raises_left  = 4
    needs_action = set(i for i in order
                       if not players[i]["folded"] and players[i]["chips"] > 0)

    # opp aggression proxy
    opp_agg = min(0.4 + hand_num * 0.002, 0.8)
    avg_stack = sum(p["chips"] for p in players) / max(1, len(players))

    acted_at_max = set()  # players who have acted at the current max bet level

    # Process queue: remove players as they complete action at current level
    queue = list(order)
    ptr   = 0
    iters = 0
    MAX_ITER = n * 6

    while queue and iters < MAX_ITER:
        iters += 1
        if ptr >= len(queue):
            ptr = 0

        idx = queue[ptr]
        p   = players[idx]

        if p["folded"] or (p["chips"] == 0):
            queue.pop(ptr)
            continue

        live_now = [x for x in players if not x["folded"]]
        if len(live_now) <= 1:
            break

        to_call = max(0, max_bet - p["bet_round"])

        # Already matched and not last raiser's re-open?
        if to_call == 0 and idx in acted_at_max:
            queue.pop(ptr)
            continue

        n_opp = len([x for x in players if not x["folded"] and x["pid"] != p["pid"]])
        gs = {
            "community": community,
            "to_call":   to_call,
            "pot":       pot,
            "street":    street,
            "n_opp":     n_opp,
            "bb":        bb,
            "opp_agg":   opp_agg,
            "avg_stack": avg_stack,
        }

        try:
            action, amount = p["strategy"](p, gs)
        except Exception:
            action, amount = ("fold", 0)

        if action == "fold":
            p["folded"] = True
            queue.pop(ptr)
            continue

        if action in ("check",):
            acted_at_max.add(idx)
            queue.pop(ptr)
            continue

        if action == "call":
            pay = min(p["chips"], to_call)
            p["chips"]    -= pay
            p["bet_round"] += pay
            pot            += pay
            if p["chips"] == 0:
                p["all_in"] = True
            max_bet = max(max_bet, p["bet_round"])
            acted_at_max.add(idx)
            queue.pop(ptr)
            continue

        if action == "raise" and raises_left > 0:
            desired = max(int(amount), max_bet + 1)
            pay     = min(p["chips"], desired - p["bet_round"])
            if pay <= 0:
                # Treat as call/check
                acted_at_max.add(idx)
                queue.pop(ptr)
                continue
            p["chips"]    -= pay
            p["bet_round"] += pay
            pot            += pay
            if p["chips"] == 0:
                p["all_in"] = True
            if p["bet_round"] > max_bet:
                max_bet      = p["bet_round"]
                raises_left -= 1
                # Re-open action for everyone else
                acted_at_max = {idx}
                # Re-add everyone who can still act (except this player)
                queue = [i for i in order
                         if not players[i]["folded"]
                         and players[i]["chips"] > 0
                         and i != idx]
                ptr = 0
            else:
                acted_at_max.add(idx)
                queue.pop(ptr)
            continue

        # raise with no raises_left → treat as call
        pay = min(p["chips"], to_call)
        p["chips"]    -= pay
        p["bet_round"] += pay
        pot            += pay
        if p["chips"] == 0:
            p["all_in"] = True
        acted_at_max.add(idx)
        queue.pop(ptr)

    return pot

# ─────────────────────────────────────────────
# Player dict factory
# ─────────────────────────────────────────────
def make_player(pid, name, strat_fn, chips):
    return {
        "pid":      pid,
        "name":     name,
        "strategy": strat_fn,
        "chips":    chips,
        "hole":     [],
        "folded":   False,
        "all_in":   False,
        "bet_round": 0,
    }

def reset_for_hand(p):
    p["hole"]      = []
    p["folded"]    = False
    p["all_in"]    = False
    p["bet_round"] = 0

# ─────────────────────────────────────────────
# One hand
# ─────────────────────────────────────────────
def play_hand(players, dealer_idx, bb):
    sb = bb // 2
    active = [p for p in players if p["chips"] > 0]
    if len(active) < 2:
        return
    for p in active:
        reset_for_hand(p)

    n = len(active)
    deck = make_deck()
    random.shuffle(deck)
    for i, p in enumerate(active):
        p["hole"] = [deck[i*2], deck[i*2+1]]
    deck = deck[n*2:]

    pot = 0
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n

    def post(p, amt):
        nonlocal pot
        pay = min(p["chips"], amt)
        p["chips"]     -= pay
        p["bet_round"] += pay
        pot            += pay
        if p["chips"] == 0:
            p["all_in"] = True

    post(active[sb_idx], sb)
    post(active[bb_idx], bb)

    community = []
    hand_num  = 1  # placeholder; we pass opp_agg from outside

    # Pre-flop: action starts left of BB
    utg = (bb_idx + 1) % n
    pot = do_betting_round(active, "preflop", utg, pot, bb, hand_num, community)

    def live():
        return [p for p in active if not p["folded"]]

    def award(pot):
        alive = live()
        if not alive:
            return
        if len(alive) == 1:
            alive[0]["chips"] += pot
            return
        # Showdown
        best_score = None
        winners    = []
        for p in alive:
            s = best_hand(p["hole"], community)
            if best_score is None or s > best_score:
                best_score = s
                winners    = [p]
            elif s == best_score:
                winners.append(p)
        share = pot // len(winners)
        for w in winners:
            w["chips"] += share
        # Remainder to first winner (simplification)
        winners[0]["chips"] += pot - share * len(winners)

    if len(live()) <= 1:
        award(pot)
        return

    # Reset bets for post-flop streets
    for p in active: p["bet_round"] = 0
    community += [deck.pop(), deck.pop(), deck.pop()]
    pot = do_betting_round(active, "flop", (dealer_idx+1)%n, pot, bb, hand_num, community)
    if len(live()) <= 1: award(pot); return

    for p in active: p["bet_round"] = 0
    community.append(deck.pop())
    pot = do_betting_round(active, "turn", (dealer_idx+1)%n, pot, bb, hand_num, community)
    if len(live()) <= 1: award(pot); return

    for p in active: p["bet_round"] = 0
    community.append(deck.pop())
    pot = do_betting_round(active, "river", (dealer_idx+1)%n, pot, bb, hand_num, community)
    award(pot)

# ─────────────────────────────────────────────
# Full game (until 1 player has all chips)
# ─────────────────────────────────────────────
STARTING_CHIPS = 1000
MAX_HANDS      = 600

def run_game(seed):
    random.seed(seed)
    players = [make_player(i+1, STRATEGIES[i][0], STRATEGIES[i][1], STARTING_CHIPS)
               for i in range(6)]
    bb       = 20
    dealer   = 0
    for hand in range(MAX_HANDS):
        alive = [p for p in players if p["chips"] > 0]
        if len(alive) == 1:
            return alive[0]
        play_hand(alive, dealer % len(alive), bb)
        dealer += 1
        # Blinds go up every 40 hands
        if (hand + 1) % 40 == 0:
            bb = int(bb * 1.5)
    # Time-out: richest wins
    return max(players, key=lambda p: p["chips"])

# ─────────────────────────────────────────────
# Run 100 sims
# ─────────────────────────────────────────────
def run_sims(n=100):
    wins = Counter()
    print(f"\nRunning {n} Texas Hold'em simulations...\n")
    print("Players:")
    for i, (nm, _) in enumerate(STRATEGIES):
        tag = "  ← THE MANIAC (all-in every hand)" if i == 0 else ""
        print(f"  Player {i+1}: {nm}{tag}")
    print()
    for sim in range(n):
        w = run_game(sim)
        wins[w["pid"]] += 1
        if (sim+1) % 10 == 0:
            print(f"  {sim+1}/{n} done...")
    return wins

def histogram(wins, n):
    print("\n" + "═"*62)
    print("  WINNER WINNER CHICKEN DINNER — 100 Hold'em Simulations")
    print("═"*62 + "\n")
    bar_max = 40
    max_w   = max(wins.values()) if wins else 1
    for i, (nm, _) in enumerate(STRATEGIES):
        pid  = i + 1
        w    = wins.get(pid, 0)
        pct  = w / n * 100
        bar  = "█" * int(w / max_w * bar_max)
        tag  = "  ← MANIAC" if i == 0 else ""
        print(f"  P{pid} {nm:<28}{tag}")
        print(f"     {bar:<40}  {w:3d} wins  ({pct:.1f}%)")
        print()
    champ_pid  = max(wins, key=wins.get)
    champ_name = STRATEGIES[champ_pid-1][0]
    champ_w    = wins[champ_pid]
    print("═"*62)
    print(f"  CHAMPION: Player {champ_pid} — {champ_name}")
    print(f"  Won {champ_w}/{n} ({champ_w/n*100:.1f}%)")
    print("═"*62)
    maniac = wins.get(1, 0)
    print(f"\n  The Maniac (all-in bot): {maniac} wins ({maniac/n*100:.1f}%)")
    if champ_pid == 1:
        print("  Chaos wins today. But Suflair GPT still can't beat proper strategy long-run.")
    else:
        print("  Skill > Luck over 100 games. Suflair GPT's all-in cope is statistically obliterated.")
    print()

if __name__ == "__main__":
    wins = run_sims(100)
    histogram(wins, 100)
