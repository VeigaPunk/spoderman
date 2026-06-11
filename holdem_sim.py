"""
Texas Hold'em 6-player simulation — 100 tournaments.
Player 1: The Degenerate (all-in every hand)
Players 2-6: Five elaborate strategy bots

Optimized: precomputed rank tables, low Monte Carlo samples, fast hand eval.
"""

import random
from collections import Counter
from itertools import combinations

# ── Card primitives ──────────────────────────────────────────────────────────

RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

DECK = [(r, s) for r in RANKS for s in SUITS]

def new_deck():
    d = DECK[:]
    random.shuffle(d)
    return d

# ── Fast 5-card hand scorer ──────────────────────────────────────────────────

def score_5(cards):
    rv = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    sv = [c[1] for c in cards]
    flush = len(set(sv)) == 1
    # Straight check (including wheel A-2-3-4-5)
    straight = len(set(rv)) == 5 and (rv[0] - rv[4] == 4)
    wheel    = rv == [14,5,4,3,2]
    if wheel:
        straight = True
        rv = [5,4,3,2,1]
    cnt = Counter(rv)
    grps = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    g_vals = [v for v, _ in grps]
    g_cnts = [c for _, c in grps]

    if flush and straight:   return (8, rv)
    if g_cnts[0] == 4:       return (7, g_vals)
    if g_cnts[:2] == [3, 2]: return (6, g_vals)
    if flush:                return (5, rv)
    if straight:             return (4, rv)
    if g_cnts[0] == 3:       return (3, g_vals)
    if g_cnts[:2] == [2, 2]: return (2, g_vals)
    if g_cnts[0] == 2:       return (1, g_vals)
    return (0, rv)

def best_hand(seven):
    return max(score_5(c) for c in combinations(seven, 5))

# ── Preflop hand strength (cheap, no Monte Carlo) ────────────────────────────

def preflop_strength(hole):
    """Return 0..1 rough preflop hand strength via Chen-like heuristic."""
    r0, r1 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r0, r1), min(r0, r1)
    pair = (r0 == r1)
    gap  = hi - lo

    score = hi / 14.0  # base from high card
    if pair:          score += 0.35
    if suited:        score += 0.06
    if gap == 0:      score += 0.10   # connected
    elif gap == 1:    score += 0.06
    elif gap == 2:    score += 0.02
    score -= max(0, gap - 3) * 0.05
    return min(1.0, score)

# ── Post-flop equity (fast Monte Carlo, low samples) ─────────────────────────

def estimate_equity(hole, community, num_opponents, n=60):
    if num_opponents == 0:
        return 1.0
    blocked = set(map(tuple, hole + community))
    remaining = [c for c in DECK if tuple(c) not in blocked]
    needed = 5 - len(community)
    wins = 0
    for _ in range(n):
        d = remaining[:]
        random.shuffle(d)
        board = list(community) + d[:needed]
        idx   = needed
        my_score = best_hand(hole + board)
        beat = True
        for _ in range(num_opponents):
            opp = [d[idx], d[idx+1]]
            idx += 2
            if best_hand(opp + board) >= my_score:
                beat = False
                break
        if beat:
            wins += 1
    return wins / n

def pot_odds(to_call, pot):
    if to_call == 0:
        return 0.0
    return to_call / (pot + to_call)

# ── Strategies ───────────────────────────────────────────────────────────────
# Signature: (hole, community, pot, to_call, my_chips, min_raise, stage, n_opp)
# Returns:   ("fold"|"call"|"raise", raise_total_chips)

def strategy_degenerate(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """If my turn → bet = ALL IN."""
    return ("raise", my_chips)

def strategy_tag(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """Tight-Aggressive: only plays strong hands, value-bets hard."""
    if stage == "preflop":
        s = preflop_strength(hole)
        if s >= 0.78:
            return ("raise", min(my_chips, max(min_raise, pot * 3)))
        if s >= 0.60:
            if to_call <= my_chips * 0.07:
                return ("call", 0)
            return ("fold", 0)
        return ("fold", 0) if to_call > 0 else ("call", 0)
    eq = estimate_equity(hole, community, n_opp)
    odds = pot_odds(to_call, pot)
    if eq >= 0.65:
        return ("raise", min(my_chips, max(min_raise, int(pot * 0.75))))
    if eq > odds:
        return ("call", 0)
    return ("fold", 0) if to_call > 0 else ("call", 0)

def strategy_lag(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """Loose-Aggressive: wide range, frequent bluffs, big sizing."""
    if stage == "preflop":
        s = preflop_strength(hole)
        if s >= 0.55 or (s >= 0.45 and to_call < my_chips * 0.10):
            return ("raise", min(my_chips, max(min_raise, int(pot * 2.5))))
        return ("call", 0) if to_call == 0 else ("fold", 0)
    eq = estimate_equity(hole, community, n_opp)
    bluff = random.random() < 0.22
    if eq >= 0.52 or bluff:
        return ("raise", min(my_chips, max(min_raise, int(pot * 1.0))))
    if eq > pot_odds(to_call, pot):
        return ("call", 0)
    return ("call", 0) if to_call == 0 else ("fold", 0)

def strategy_gto(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """GTO-inspired: mixed frequencies, varied sizings to avoid exploitability."""
    if stage == "preflop":
        s = preflop_strength(hole)
        r = random.random()
        if s >= 0.70:
            size = 0.75 if r < 0.5 else 1.1
            return ("raise", min(my_chips, max(min_raise, int(pot * size))))
        if s >= 0.50:
            if r < 0.45:
                return ("raise", min(my_chips, max(min_raise, int(pot * 0.6))))
            return ("call", 0) if to_call <= my_chips * 0.08 else ("fold", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)
    eq = estimate_equity(hole, community, n_opp)
    odds = pot_odds(to_call, pot)
    r = random.random()
    if eq >= 0.68:
        size = 0.75 if r < 0.55 else 1.0
        return ("raise", min(my_chips, max(min_raise, int(pot * size))))
    if eq >= 0.50:
        if r < 0.50:
            return ("raise", min(my_chips, max(min_raise, int(pot * 0.5))))
        return ("call", 0) if (to_call == 0 or eq > odds) else ("fold", 0)
    if eq > odds:
        if r < 0.10:
            return ("raise", min(my_chips, max(min_raise, int(pot * 0.55))))
        return ("call", 0)
    return ("call", 0) if to_call == 0 else ("fold", 0)

def strategy_icm(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """Stack-Pressure / ICM-aware: shoves short, plays conservatively deep."""
    if stage == "preflop":
        s = preflop_strength(hole)
        spr = my_chips / max(pot, BIG_BLIND)
        if spr < 8:
            return ("raise", my_chips) if s >= 0.40 else ("fold", 0)
        if s >= 0.68:
            return ("raise", min(my_chips, max(min_raise, int(pot * 3))))
        return ("call", 0) if (s >= 0.50 and to_call <= my_chips * 0.06) else (("fold", 0) if to_call > 0 else ("call", 0))
    eq = estimate_equity(hole, community, n_opp)
    odds = pot_odds(to_call, pot)
    spr = my_chips / max(pot, 1)
    if spr < 5:
        return ("raise", my_chips) if eq >= 0.33 else ("fold", 0)
    if spr < 15:
        if eq >= 0.60:
            return ("raise", min(my_chips, max(min_raise, int(pot * 0.8))))
        return ("call", 0) if eq > odds else (("fold", 0) if to_call > 0 else ("call", 0))
    if eq >= 0.68:
        return ("raise", min(my_chips, max(min_raise, int(pot * 0.65))))
    return ("call", 0) if eq > odds + 0.08 else (("fold", 0) if to_call > 0 else ("call", 0))

def strategy_exploitative(hole, community, pot, to_call, my_chips, min_raise, stage, n_opp):
    """Exploitative: steals small pots, tightens in bloated pots, reads aggression."""
    if stage == "preflop":
        s = preflop_strength(hole)
        steal = (pot < BIG_BLIND * 2 and n_opp <= 2)
        if steal and s >= 0.45:
            return ("raise", min(my_chips, max(min_raise, int(pot * 3))))
        if s >= 0.65:
            return ("raise", min(my_chips, max(min_raise, int(pot * 2.5))))
        if s >= 0.50:
            return ("call", 0) if to_call <= my_chips * 0.07 else ("fold", 0)
        return ("call", 0) if to_call == 0 else ("fold", 0)
    eq   = estimate_equity(hole, community, n_opp)
    odds = pot_odds(to_call, pot)
    bloated = pot > BIG_BLIND * 8
    steal   = (pot < BIG_BLIND * 3 and n_opp <= 2)
    if steal:
        return ("raise", min(my_chips, max(min_raise, int(pot * 2.5))))
    if bloated:
        if eq >= 0.66:
            return ("raise", min(my_chips, max(min_raise, int(pot * 0.5))))
        return ("call", 0) if eq > odds + 0.07 else (("fold", 0) if to_call > 0 else ("call", 0))
    if eq >= 0.57:
        return ("raise", min(my_chips, max(min_raise, int(pot * 0.75))))
    return ("call", 0) if eq > odds else (("fold", 0) if to_call > 0 else ("call", 0))

# ── Roster ───────────────────────────────────────────────────────────────────

STRATEGIES = [
    ("The Degenerate",    strategy_degenerate),
    ("Tight-Aggressive",  strategy_tag),
    ("Loose-Aggressive",  strategy_lag),
    ("GTO-Inspired",      strategy_gto),
    ("Stack-Pressure",    strategy_icm),
    ("Exploitative",      strategy_exploitative),
]

# ── Game constants ────────────────────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND    = 25
BIG_BLIND      = 50

# ── Hand engine ───────────────────────────────────────────────────────────────

def play_hand(players, dealer_idx):
    """
    Play one hand. `players` = list of dicts with id/name/strategy/chips.
    Mutates chips in-place.
    """
    active = [p for p in players if p["chips"] > 0]
    n = len(active)
    if n < 2:
        return

    deck = new_deck()
    holes = {p["id"]: [deck.pop(), deck.pop()] for p in active}
    community = []
    pot = 0

    # Post blinds
    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n
    sb_p   = active[sb_idx % n]
    bb_p   = active[bb_idx % n]
    sb_amt = min(SMALL_BLIND, sb_p["chips"])
    bb_amt = min(BIG_BLIND,   bb_p["chips"])
    sb_p["chips"] -= sb_amt
    bb_p["chips"] -= bb_amt
    pot += sb_amt + bb_amt
    contribs_blind = {p["id"]: 0 for p in active}
    contribs_blind[sb_p["id"]] = sb_amt
    contribs_blind[bb_p["id"]] = bb_amt

    def do_street(stage, start_idx, init_bet, init_contribs):
        nonlocal pot
        n_act = len(active)
        folded    = set()
        contribs  = dict(init_contribs)
        cur_bet   = init_bet
        min_raise = BIG_BLIND
        acted     = set()

        order = [(start_idx + i) % n_act for i in range(n_act)]

        i = 0
        while True:
            idx = order[i % len(order)]
            p   = active[idx]
            pid = p["id"]

            if pid in folded or p["chips"] == 0:
                acted.add(pid)
                i += 1
            else:
                to_call = min(p["chips"], max(0, cur_bet - contribs[pid]))
                alive_opp = [x for x in active if x["id"] != pid and x["id"] not in folded]
                n_opp = len(alive_opp)

                action, amount = p["strategy"](
                    holes[pid], community, pot, to_call,
                    p["chips"], min_raise, stage, n_opp
                )

                if action == "fold":
                    folded.add(pid)
                elif action == "raise":
                    total = min(p["chips"], max(to_call, int(amount)))
                    pot += total
                    p["chips"] -= total
                    contribs[pid] += total
                    if contribs[pid] > cur_bet:
                        min_raise = max(min_raise, contribs[pid] - cur_bet)
                        cur_bet   = contribs[pid]
                        acted     = {pid}
                else:  # call / check
                    pot += to_call
                    p["chips"] -= to_call
                    contribs[pid] += to_call

                acted.add(pid)
                i += 1

            # termination check
            live = [x for x in active if x["id"] not in folded]
            if len(live) <= 1:
                break
            can_act = [x for x in live if x["chips"] > 0 and x["id"] not in acted]
            need_call = [x for x in live if x["chips"] > 0 and contribs.get(x["id"],0) < cur_bet and x["id"] not in folded]
            if not can_act and not need_call:
                break

        return folded

    # Pre-flop: action starts left of BB
    pf_start = (bb_idx + 1) % n
    folded = do_street("preflop", pf_start, bb_amt, contribs_blind)

    def remaining():
        return [p for p in active if p["id"] not in folded]

    def award(winner):
        winner["chips"] += pot

    if len(remaining()) == 1:
        award(remaining()[0]); return

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    folded |= do_street("flop", 0, 0, {p["id"]: 0 for p in active})
    if len(remaining()) == 1:
        award(remaining()[0]); return

    # Turn
    community.append(deck.pop())
    folded |= do_street("turn", 0, 0, {p["id"]: 0 for p in active})
    if len(remaining()) == 1:
        award(remaining()[0]); return

    # River
    community.append(deck.pop())
    folded |= do_street("river", 0, 0, {p["id"]: 0 for p in active})
    rem = remaining()
    if len(rem) == 1:
        award(rem[0]); return

    if not rem:
        return

    # Showdown
    scores   = {p["id"]: best_hand(holes[p["id"]] + community) for p in rem}
    top      = max(scores.values())
    winners  = [p for p in rem if scores[p["id"]] == top]
    share    = pot // len(winners)
    leftover = pot % len(winners)
    for w in winners:
        w["chips"] += share
    if leftover:
        winners[0]["chips"] += leftover

# ── Tournament ────────────────────────────────────────────────────────────────

def run_tournament():
    players = [
        {"id": i, "name": STRATEGIES[i][0], "strategy": STRATEGIES[i][1],
         "chips": STARTING_CHIPS}
        for i in range(len(STRATEGIES))
    ]
    dealer = 0
    for _ in range(3000):
        alive = [p for p in players if p["chips"] > 0]
        if len(alive) == 1:
            return alive[0]["name"]
        if not alive:
            break
        play_hand(players, dealer % len(alive))
        dealer += 1
    alive = [p for p in players if p["chips"] > 0]
    if not alive:
        return "No winner"
    return max(alive, key=lambda p: p["chips"])["name"]

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    N_SIMS = 100
    print(f"Running {N_SIMS} Texas Hold'em tournaments (6 players, {STARTING_CHIPS} chips each)...\n")
    wins = Counter()
    for i in range(N_SIMS):
        w = run_tournament()
        wins[w] += 1
        if (i + 1) % 10 == 0:
            print(f"  [{i+1:3d}/100] done — current leader: {max(wins, key=wins.get)} ({max(wins.values())} wins)")

    BAR = 42
    order = [name for name, _ in STRATEGIES]
    top_count = max(wins.values()) if wins else 1

    print()
    print("╔" + "═"*62 + "╗")
    print("║  LAST PLAYER STANDING — 100 Tournament Histogram          ║")
    print("╠" + "═"*62 + "╣")
    print(f"║  {'Strategy':<22}  {'W':>4}  {'%':>5}  {'Bar':<28}║")
    print("╠" + "═"*62 + "╣")
    for name in order:
        w   = wins.get(name, 0)
        pct = w / N_SIMS * 100
        bar = "█" * int(w / top_count * BAR)
        tag = " ◄ YOU" if name == "The Degenerate" else ""
        line = f"║  {name:<22}  {w:>4}  {pct:>4.1f}%  {bar:<28}║"
        # Pad to fit box
        print(line[:64].ljust(63) + "║")
    print("╠" + "═"*62 + "╣")

    champ       = max(order, key=lambda n: wins.get(n, 0))
    degen_wins  = wins.get("The Degenerate", 0)
    champ_wins  = wins.get(champ, 0)

    if champ == "The Degenerate":
        verdict = f"The Degenerate WINS with {degen_wins} titles. Chaos reigns. GPT weeps."
    else:
        verdict = (f"Champ: {champ} ({champ_wins}W). "
                   f"Degenerate: {degen_wins}W. "
                   f"Strategy wins by {champ_wins - degen_wins}.")
    print(f"║  {verdict:<60}║")
    print("╚" + "═"*62 + "╝")

if __name__ == "__main__":
    main()
