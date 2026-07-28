#!/usr/bin/env python3
"""
Texas Hold'em Tournament Simulator — 100 runs
Player 1 : SIMPLE  — if my_turn: bet = ALL-IN
Players 2-6: Elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────
#  CARDS
# ─────────────────────────────────────────────
RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RVAL   = {r: i for i, r in enumerate(RANKS, 2)}   # '2'->2 … 'A'->14

def new_deck():
    d = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(d)
    return d

# ─────────────────────────────────────────────
#  HAND EVALUATOR  (returns comparable tuple)
# ─────────────────────────────────────────────
def eval5(cards):
    ranks = sorted([RVAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush    = len(set(suits)) == 1
    straight = len(set(ranks)) == 5 and ranks[0] - ranks[4] == 4
    if set(ranks) == {14, 2, 3, 4, 5}:          # wheel A-2-3-4-5
        straight, ranks = True, [5, 4, 3, 2, 1]

    cnt = Counter(ranks)
    groups  = sorted(cnt, key=lambda r: (cnt[r], r), reverse=True)
    freqs   = sorted(cnt.values(), reverse=True)

    if straight and flush:   return (8, ranks)
    if freqs[0] == 4:        return (7, groups)
    if freqs[:2] == [3, 2]:  return (6, groups)
    if flush:                return (5, ranks)
    if straight:             return (4, ranks)
    if freqs[0] == 3:        return (3, groups)
    if freqs[:2] == [2, 2]:  return (2, groups)
    if freqs[0] == 2:        return (1, groups)
    return (0, ranks)

def best_hand(cards):
    if len(cards) <= 5:
        return eval5(cards)
    return max(eval5(list(c)) for c in combinations(cards, 5))

# ─────────────────────────────────────────────
#  HAND-STRENGTH HEURISTIC  (0 … 1)
# ─────────────────────────────────────────────
def preflop_strength(hole):
    r1, r2   = RVAL[hole[0][0]], RVAL[hole[1][0]]
    suited   = hole[0][1] == hole[1][1]
    hi, lo   = max(r1, r2), min(r1, r2)
    paired   = r1 == r2

    if paired:
        s = 0.50 + (hi - 2) / 25.0
    else:
        s = (hi + lo - 4) / 24.0
    if suited:          s += 0.05
    if abs(r1-r2) == 1: s += 0.03   # connector
    return max(0.0, min(1.0, s))

def hand_str(hole, community):
    if not community:
        return preflop_strength(hole)
    rank_cat = best_hand(hole + community)[0]   # 0..8
    hi_hole  = max(RVAL[c[0]] for c in hole)
    return min(1.0, rank_cat / 8.0 + (hi_hole - 2) / 200.0)

# ─────────────────────────────────────────────
#  PLAYER
# ─────────────────────────────────────────────
class Player:
    def __init__(self, pid, chips, strategy_fn, name):
        self.pid         = pid
        self.chips       = chips
        self.strategy_fn = strategy_fn
        self.name        = name
        self.hole        = []
        self.folded      = False
        self.all_in      = False

    def reset(self):
        self.hole   = []
        self.folded = False
        self.all_in = False

class GameInfo:
    """Read-only snapshot passed to each strategy."""
    def __init__(self, pot, current_bet, to_call, community, stage, players):
        self.pot         = pot
        self.current_bet = current_bet
        self.to_call     = to_call
        self.community   = community
        self.stage       = stage
        self.players     = players   # full list (for position calc)

# ─────────────────────────────────────────────
#  BETTING ENGINE
# ─────────────────────────────────────────────
def betting_round(ordered_players, pot, street_bet, init_bets, community, stage):
    bets = dict(init_bets)
    for p in ordered_players:
        if p.pid not in bets:
            bets[p.pid] = 0

    all_players = ordered_players
    queue = [p for p in ordered_players if not p.folded and p.chips > 0]

    while queue:
        player = queue.pop(0)

        if player.folded or player.all_in:
            continue
        if player.chips <= 0:
            player.all_in = True
            continue

        to_call = max(0, street_bet - bets[player.pid])
        info    = GameInfo(pot, street_bet, to_call, list(community), stage, all_players)
        action, amount = player.strategy_fn(player, info)

        if action == 'check' and to_call > 0:
            action = 'call'

        if action == 'fold':
            player.folded = True

        elif action in ('check', 'call'):
            contrib = min(to_call, player.chips)
            player.chips     -= contrib
            bets[player.pid] += contrib
            pot              += contrib
            if player.chips == 0:
                player.all_in = True

        elif action == 'raise':
            call_c = min(to_call, player.chips)
            player.chips     -= call_c
            bets[player.pid] += call_c
            pot              += call_c

            if player.chips > 0 and amount > 0:
                raise_c = min(int(amount), player.chips)
                player.chips     -= raise_c
                bets[player.pid] += raise_c
                pot              += raise_c
                street_bet        = bets[player.pid]

                if player.chips == 0:
                    player.all_in = True

                for p in ordered_players:
                    if (p.pid != player.pid
                            and not p.folded
                            and not p.all_in
                            and p.chips > 0
                            and bets[p.pid] < street_bet
                            and p not in queue):
                        queue.append(p)

        if sum(1 for p in ordered_players if not p.folded) <= 1:
            break

    return pot, street_bet

# ─────────────────────────────────────────────
#  SHOWDOWN
# ─────────────────────────────────────────────
def showdown(players, community, pot):
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return
    scored = [(best_hand(p.hole + community), p) for p in alive]
    top    = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == top]
    share, rem = divmod(pot, len(winners))
    for w in winners:
        w.chips += share
    winners[0].chips += rem

# ─────────────────────────────────────────────
#  ONE HAND
# ─────────────────────────────────────────────
def play_hand(players, dealer_idx, sb_size, bb_size):
    deck = new_deck()
    for p in players:
        p.reset()

    alive = [p for p in players if p.chips > 0]
    n = len(alive)
    if n < 2:
        return

    sb_p = alive[(dealer_idx + 1) % n]
    bb_p = alive[(dealer_idx + 2) % n]

    sb_post = min(sb_size, sb_p.chips)
    sb_p.chips -= sb_post
    if sb_p.chips == 0: sb_p.all_in = True

    bb_post = min(bb_size, bb_p.chips)
    bb_p.chips -= bb_post
    if bb_p.chips == 0: bb_p.all_in = True

    pot        = sb_post + bb_post
    street_bet = bb_post

    for p in alive:
        p.hole = [deck.pop(), deck.pop()]

    community = []

    def survivors():
        return [p for p in players if not p.folded and p.hole]

    def pot_winner():
        w = survivors()[0]; w.chips += pot

    # PREFLOP — action starts UTG = dealer+3
    preflop_order = [alive[(dealer_idx + 3 + i) % n] for i in range(n)]
    init = {sb_p.pid: sb_post, bb_p.pid: bb_post}
    pot, street_bet = betting_round(preflop_order, pot, street_bet, init, community, 'preflop')
    if len(survivors()) == 1: pot_winner(); return

    # FLOP
    community += [deck.pop(), deck.pop(), deck.pop()]
    postflop_order = [alive[(dealer_idx + 1 + i) % n] for i in range(n)]
    pot, street_bet = betting_round(postflop_order, pot, 0, {}, community, 'flop')
    if len(survivors()) == 1: pot_winner(); return

    # TURN
    community.append(deck.pop())
    pot, street_bet = betting_round(postflop_order, pot, 0, {}, community, 'turn')
    if len(survivors()) == 1: pot_winner(); return

    # RIVER
    community.append(deck.pop())
    pot, street_bet = betting_round(postflop_order, pot, 0, {}, community, 'river')
    if len(survivors()) == 1: pot_winner(); return

    showdown([p for p in players if p.hole], community, pot)

# ─────────────────────────────────────────────
#  THE SIX STRATEGIES
# ─────────────────────────────────────────────

# ── 1. THE CHAD: ALWAYS ALL-IN ───────────────
def strat_allin(player, info):
    """if my_turn: bet = ALL IN. Fi."""
    return ('raise', player.chips)


# ── 2. TIGHT-AGGRESSIVE (TAG) ────────────────
def strat_tag(player, info):
    """Premium hands only; aggressive when strong, disciplined folds otherwise."""
    s        = hand_str(player.hole, info.community)
    to_call  = info.to_call
    pot      = info.pot
    cur_bet  = info.current_bet

    if s >= 0.72:
        bet = min(player.chips, max(cur_bet * 3, pot // 2, 20))
        return ('raise', int(bet))
    elif s >= 0.52:
        if to_call == 0:
            return ('check', 0)
        if to_call <= player.chips * 0.18:
            return ('call', to_call)
        return ('fold', 0)
    else:
        return ('check', 0) if to_call == 0 else ('fold', 0)


# ── 3. LOOSE-PASSIVE (Calling Station) ───────
def strat_loose_passive(player, info):
    """Limps everything cheap, rarely raises, calls down with anything decent."""
    s       = hand_str(player.hole, info.community)
    to_call = info.to_call
    pot     = info.pot

    if s >= 0.82:
        bet = min(player.chips, max(pot // 4, 10))
        return ('raise', int(bet))
    elif s >= 0.22 or to_call == 0:
        if to_call == 0:
            return ('check', 0)
        if to_call <= player.chips * 0.45:
            return ('call', to_call)
        return ('fold', 0)
    else:
        return ('check', 0) if to_call == 0 else ('fold', 0)


# ── 4. MANIAC BLUFFER ────────────────────────
def strat_bluffer(player, info):
    """Bluffs 28% of the time regardless of cards; fires big with real hands."""
    s       = hand_str(player.hole, info.community)
    to_call = info.to_call
    pot     = info.pot
    cur_bet = info.current_bet
    bluffing = random.random() < 0.28

    if s >= 0.65 or bluffing:
        bet = min(player.chips, max(pot // 2, cur_bet * 2, 10))
        return ('raise', int(bet))
    elif s >= 0.38 or to_call == 0:
        if to_call == 0:
            return ('check', 0)
        return ('call', min(to_call, player.chips))
    else:
        return ('check', 0) if to_call == 0 else ('fold', 0)


# ── 5. POT-ODDS MATHEMATICIAN ────────────────
def strat_pot_odds(player, info):
    """Calls when equity beats pot odds; re-raises with a big edge. Never tilts."""
    s       = hand_str(player.hole, info.community)
    to_call = info.to_call
    pot     = info.pot

    if to_call <= 0:
        if s >= 0.55:
            bet = min(player.chips, max(pot // 3, 10))
            return ('raise', int(bet))
        return ('check', 0)

    pot_odds = to_call / (pot + to_call)

    if s > pot_odds * 1.9:
        reraise = min(player.chips, to_call * 2 + pot // 4)
        return ('raise', int(reraise))
    elif s > pot_odds * 1.1:
        return ('call', min(to_call, player.chips))
    else:
        return ('fold', 0)


# ── 6. GTO POSITION-AWARE ────────────────────
def strat_position(player, info):
    """Tight early, loose/aggressive late; steals from the button; sizes bets by strength."""
    s       = hand_str(player.hole, info.community)
    to_call = info.to_call
    pot     = info.pot
    cur_bet = info.current_bet

    non_folded = [p for p in info.players if not p.folded]
    n = len(non_folded)
    try:
        seat = next(i for i, p in enumerate(non_folded) if p.pid == player.pid)
    except StopIteration:
        seat = 0
    late = seat / max(n - 1, 1)

    open_thresh  = 0.48 - late * 0.18
    value_thresh = 0.65

    if s >= value_thresh:
        frac = 0.4 + s * 0.3
        bet  = min(player.chips, max(int(pot * frac), cur_bet * 2, 15))
        return ('raise', bet)
    elif s >= open_thresh:
        if to_call == 0:
            if late >= 0.60 and s >= 0.38:
                bet = min(player.chips, max(pot // 3, 12))
                return ('raise', int(bet))
            return ('check', 0)
        if to_call <= player.chips * 0.22:
            return ('call', min(to_call, player.chips))
        return ('fold', 0)
    else:
        return ('check', 0) if to_call == 0 else ('fold', 0)


# ─────────────────────────────────────────────
#  STRATEGY REGISTRY
# ─────────────────────────────────────────────
STRATEGY_DEFS = [
    (strat_allin,         "P1 * ALL-IN CHAD (the simple one)"),
    (strat_tag,           "P2   Tight-Aggressive (TAG)"),
    (strat_loose_passive, "P3   Loose-Passive (Calling Station)"),
    (strat_bluffer,       "P4   Maniac Bluffer"),
    (strat_pot_odds,      "P5   Pot-Odds Mathematician"),
    (strat_position,      "P6   GTO Position-Aware"),
]

# ─────────────────────────────────────────────
#  TOURNAMENT
# ─────────────────────────────────────────────
def run_tournament(starting_chips=1500, sb=15, bb=30, max_hands=8000):
    players = [
        Player(i + 1, starting_chips, fn, name)
        for i, (fn, name) in enumerate(STRATEGY_DEFS)
    ]
    dealer   = 0
    hand_num = 0

    while hand_num < max_hands:
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break

        play_hand(players, dealer % len(alive), sb, bb)
        dealer   += 1
        hand_num += 1

        if hand_num % 40 == 0:
            sb = int(sb * 1.6)
            bb = int(bb * 1.6)

    alive = [p for p in players if p.chips > 0]
    if not alive:
        return None
    return max(alive, key=lambda p: p.chips)

# ─────────────────────────────────────────────
#  MAIN — 100 SIMULATIONS + HISTOGRAM
# ─────────────────────────────────────────────
def main(n_sims=100):
    wins = Counter()
    print(f"\nDealing {n_sims} Texas Hold'em tournaments ...\n")

    for i in range(n_sims):
        random.seed(i * 31337 + 42)
        winner = run_tournament()
        if winner:
            wins[winner.pid] += 1
        if (i + 1) % 20 == 0:
            print(f"  progress: {i + 1}/{n_sims}")

    total   = sum(wins.values()) or 1
    max_win = max(wins.values()) if wins else 1
    BAR_W   = 40

    print()
    print("=" * 78)
    print("   WINNER WINNER CHICKEN DINNER — 100-TOURNAMENT HISTOGRAM")
    print("=" * 78)

    ranking = []
    for pid, (_, name) in enumerate(STRATEGY_DEFS, 1):
        w   = wins.get(pid, 0)
        pct = w / total * 100
        bar = "#" * max(1 if w else 0, int(w / max_win * BAR_W))
        ranking.append((w, pid, name, pct, bar))

    ranking.sort(key=lambda x: (-x[0], x[1]))

    for rank_i, (w, pid, name, pct, bar) in enumerate(ranking, 1):
        print(f"  {rank_i}. {name:<38} {w:>3} wins ({pct:>4.1f}%)  {bar}")

    print("=" * 78)
    champ = ranking[0]
    print(f"\n  CHAMPION: {champ[2].strip()} with {champ[0]} wins ({champ[3]:.1f}%)\n")

    if champ[1] == 1:
        print("  The ALL-IN CHAD humiliated every elaborate strategy. GG.")
    else:
        p1 = next(r for r in ranking if r[1] == 1)
        print(f"  The ALL-IN CHAD finished with {p1[0]} wins ({p1[3]:.1f}%).")

if __name__ == "__main__":
    main(100)
