import random
from collections import Counter
from itertools import combinations

# ── Card primitives ──────────────────────────────────────────────────────────

RANKS = list(range(2, 15))   # 2-14 (14=Ace)
SUITS = ['s', 'h', 'd', 'c']

def new_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def hand_rank(cards):
    best = None
    for combo in combinations(cards, 5):
        score = score_5(combo)
        if best is None or score > best:
            best = score
    return best

def score_5(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    cnt = Counter(ranks)
    freq = sorted(cnt.values(), reverse=True)
    is_flush = len(set(suits)) == 1
    is_straight = (len(set(ranks)) == 5 and ranks[0] - ranks[4] == 4)
    if set(ranks) == {14, 2, 3, 4, 5}:
        is_straight = True
        ranks = [5, 4, 3, 2, 1]

    if is_straight and is_flush:
        return (8, ranks)
    if freq[0] == 4:
        quad = [r for r, c in cnt.items() if c == 4][0]
        kicker = [r for r, c in cnt.items() if c == 1]
        return (7, [quad] + sorted(kicker, reverse=True))
    if freq[0] == 3 and freq[1] == 2:
        trip = [r for r, c in cnt.items() if c == 3][0]
        pair = [r for r, c in cnt.items() if c == 2][0]
        return (6, [trip, pair])
    if is_flush:
        return (5, ranks)
    if is_straight:
        return (4, ranks)
    if freq[0] == 3:
        trip = [r for r, c in cnt.items() if c == 3][0]
        kicks = sorted([r for r, c in cnt.items() if c == 1], reverse=True)
        return (3, [trip] + kicks)
    if freq[0] == 2 and freq[1] == 2:
        pairs = sorted([r for r, c in cnt.items() if c == 2], reverse=True)
        kick = [r for r, c in cnt.items() if c == 1]
        return (2, pairs + kick)
    if freq[0] == 2:
        pair = [r for r, c in cnt.items() if c == 2][0]
        kicks = sorted([r for r, c in cnt.items() if c == 1], reverse=True)
        return (1, [pair] + kicks)
    return (0, ranks)

# ── Monte-Carlo equity estimator ─────────────────────────────────────────────

def estimate_equity(hole, community, deck, iters=100):
    wins = 0
    for _ in range(iters):
        random.shuffle(deck)
        needed = 5 - len(community)
        board = community + deck[:needed]
        opp_hole = deck[needed:needed+2]
        my_score = hand_rank(hole + board)
        opp_score = hand_rank(opp_hole + board)
        if my_score >= opp_score:
            wins += 1
    return wins / iters

# ── Game state passed to strategies ──────────────────────────────────────────

class GameState:
    def __init__(self, hole, community, pot, my_chips, to_call, min_raise,
                 stage, active_count, position, num_players, big_blind):
        self.hole = hole
        self.community = community
        self.pot = pot
        self.my_chips = my_chips
        self.to_call = to_call          # chips needed to call (0 = can check)
        self.min_raise = min_raise
        self.stage = stage              # 'pre','flop','turn','river'
        self.active_count = active_count
        self.position = position
        self.num_players = num_players
        self.big_blind = big_blind

    def available_deck(self):
        used = set(map(tuple, self.hole + self.community))
        return [c for c in new_deck() if tuple(c) not in used]

# ── Action helpers ────────────────────────────────────────────────────────────

def action_fold():              return ('fold', 0)
def action_call(gs):            return ('call', min(gs.to_call, gs.my_chips))
def action_check():             return ('check', 0)
def action_raise(gs, amount):
    amt = max(gs.min_raise, amount)
    amt = min(amt, gs.my_chips)
    return ('raise', amt)
def action_allin(gs):           return ('raise', gs.my_chips)

def can_check(gs):              return gs.to_call == 0

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1 — GTO-ish equity-based
# ─────────────────────────────────────────────────────────────────────────────

def strategy_gto(gs):
    """Equity-driven: estimate win probability via Monte Carlo, size bets accordingly."""
    deck = gs.available_deck()
    equity = estimate_equity(gs.hole, gs.community, deck, iters=120)

    pot_odds = gs.to_call / (gs.pot + gs.to_call) if gs.to_call > 0 else 0

    if equity > 0.80:
        return action_raise(gs, int(gs.pot * 0.75))
    elif equity > 0.60:
        if gs.to_call == 0:
            return action_raise(gs, int(gs.pot * 0.5))
        elif equity > pot_odds + 0.10:
            return action_raise(gs, int(gs.to_call * 2))
        else:
            return action_call(gs)
    elif equity > 0.45:
        if can_check(gs):
            return action_check()
        elif equity > pot_odds:
            return action_call(gs)
        else:
            return action_fold()
    else:
        if can_check(gs):
            return action_check()
        if gs.position >= gs.num_players // 2 and random.random() < 0.15:
            return action_raise(gs, gs.big_blind * 3)   # positional bluff
        return action_fold()

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2 — Tight-Aggressive (TAG)
# ─────────────────────────────────────────────────────────────────────────────

PREMIUM_SUITED = {(14, 13), (14, 12), (14, 11), (13, 12)}

def hole_strength(hole):
    r1, r2 = sorted([hole[0][0], hole[1][0]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    if r1 == r2:
        if r1 >= 10: return 'premium'
        if r1 >= 7:  return 'strong'
        return 'marginal'
    if suited and (r1, r2) in PREMIUM_SUITED: return 'premium'
    if r1 >= 13 and r2 >= 10:                 return 'strong'
    if suited and r1 >= 10 and r2 >= 8:       return 'strong'
    if r1 >= 11 and r2 >= 9:                  return 'marginal'
    return 'weak'

def strategy_tag(gs):
    """Tight-Aggressive: play few hands, play them hard."""
    strength = hole_strength(gs.hole)

    if gs.stage == 'pre':
        if strength == 'premium':
            return action_raise(gs, gs.big_blind * 4)
        elif strength == 'strong':
            if gs.to_call <= gs.big_blind * 3:
                return action_call(gs)
            return action_fold()
        elif strength == 'marginal':
            if can_check(gs):
                return action_check()
            if gs.to_call <= gs.big_blind:
                return action_call(gs)
            return action_fold()
        else:
            if can_check(gs):
                return action_check()
            return action_fold()

    deck = gs.available_deck()
    equity = estimate_equity(gs.hole, gs.community, deck, iters=100)

    if equity > 0.70:
        return action_raise(gs, int(gs.pot * 0.80))
    elif equity > 0.55:
        if can_check(gs):
            return action_raise(gs, int(gs.pot * 0.40))
        return action_call(gs)
    elif equity > 0.40:
        if can_check(gs):
            return action_check()
        if gs.to_call < gs.pot * 0.30:
            return action_call(gs)
        return action_fold()
    else:
        if can_check(gs):
            return action_check()
        return action_fold()

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 3 — Loose-Aggressive (LAG) / Maniac
# ─────────────────────────────────────────────────────────────────────────────

def strategy_lag(gs):
    """Loose-Aggressive: constant pressure, frequent bluffs, wide ranges."""
    deck = gs.available_deck()

    if gs.stage == 'pre':
        if gs.to_call <= gs.big_blind * 5 or can_check(gs):
            return action_raise(gs, gs.big_blind * random.randint(3, 6))
        else:
            r1, r2 = gs.hole[0][0], gs.hole[1][0]
            if max(r1, r2) >= 9 or random.random() < 0.45:
                return action_call(gs)
            return action_fold()

    equity = estimate_equity(gs.hole, gs.community, deck, iters=80)

    if gs.stage == 'flop' and random.random() < 0.80:   # relentless c-bet
        return action_raise(gs, int(gs.pot * random.uniform(0.5, 1.0)))

    if equity > 0.50:
        return action_raise(gs, int(gs.pot * random.uniform(0.6, 1.2)))

    if can_check(gs):
        if random.random() < 0.30:
            return action_raise(gs, int(gs.pot * 0.5))   # stab bluff
        return action_check()

    if gs.to_call < gs.my_chips * 0.25:
        return action_call(gs)
    return action_fold()

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 4 — Position & Pot-control (PPO)
# ─────────────────────────────────────────────────────────────────────────────

def strategy_ppo(gs):
    """Exploit positional advantage; control pot size relative to hand strength."""
    late = gs.position >= gs.num_players * 0.6
    deck = gs.available_deck()

    if gs.stage == 'pre':
        r1, r2 = sorted([gs.hole[0][0], gs.hole[1][0]], reverse=True)
        suited = gs.hole[0][1] == gs.hole[1][1]
        connected = abs(r1 - r2) <= 2

        if r1 >= 12 or (r1 >= 10 and r2 >= 10):
            return action_raise(gs, gs.big_blind * 3)
        if late and (suited or connected or r1 >= 9):
            if gs.to_call <= gs.big_blind * 3:
                return action_call(gs)
            return action_raise(gs, gs.big_blind * 3)
        if can_check(gs):
            return action_check()
        if gs.to_call <= gs.big_blind:
            return action_call(gs)
        return action_fold()

    equity = estimate_equity(gs.hole, gs.community, deck, iters=100)

    if late:
        if equity > 0.60:
            return action_raise(gs, int(gs.pot * 0.60))
        elif equity > 0.45:
            if can_check(gs):
                return action_check()
            return action_call(gs)
    else:
        if equity > 0.70:
            return action_raise(gs, int(gs.pot * 0.50))
        elif equity > 0.50:
            if can_check(gs):
                return action_check()
            if gs.to_call < gs.pot * 0.35:
                return action_call(gs)

    if can_check(gs):
        return action_check()
    if gs.to_call > gs.my_chips * 0.4 and equity < 0.50:
        return action_fold()
    if equity < 0.35:
        return action_fold()
    return action_call(gs)

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 5 — Exploitative / Stack-aware Adaptive
# ─────────────────────────────────────────────────────────────────────────────

def strategy_adaptive(gs):
    """Adapts to stack depth: push/fold when short, SPR-aware when deep."""
    deck = gs.available_deck()
    equity = estimate_equity(gs.hole, gs.community, deck, iters=100)
    spr = gs.my_chips / max(gs.pot, 1)   # stack-to-pot ratio

    if gs.my_chips <= gs.big_blind * 10:   # push/fold territory
        if equity > 0.45 or hole_strength(gs.hole) in ('premium', 'strong'):
            return action_allin(gs)
        if can_check(gs):
            return action_check()
        return action_fold()

    if gs.stage == 'pre':
        s = hole_strength(gs.hole)
        if s == 'premium':
            return action_raise(gs, gs.big_blind * 4)
        elif s == 'strong':
            if gs.to_call <= gs.big_blind * 3:
                return action_raise(gs, gs.big_blind * 3)
            return action_fold()
        elif s == 'marginal' and can_check(gs):
            return action_check()
        elif s == 'marginal' and gs.to_call <= gs.big_blind:
            return action_call(gs)
        if can_check(gs):
            return action_check()
        return action_fold()

    if spr < 2 and equity > 0.40:   # pot-committed
        return action_allin(gs)

    if equity > 0.75:
        if spr > 4:
            return action_raise(gs, int(gs.pot * 0.55))   # keep them in
        return action_allin(gs)
    elif equity > 0.55:
        if can_check(gs):
            return action_raise(gs, int(gs.pot * 0.45))
        elif gs.to_call < gs.pot * 0.40:
            return action_call(gs)
        return action_fold()
    elif equity > 0.42:
        if can_check(gs):
            return action_check()
        if gs.to_call < gs.pot * 0.25:
            return action_call(gs)
        return action_fold()
    else:
        if can_check(gs):
            return action_check()
        return action_fold()

# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 0 — Player #1: "if my_turn then bet = All in fi"
# ─────────────────────────────────────────────────────────────────────────────

def strategy_allin(gs):
    return action_allin(gs)

# ── Players ──────────────────────────────────────────────────────────────────

STRATEGY_NAMES = {
    0: 'P1:AllIn',
    1: 'P2:GTO',
    2: 'P3:TAG',
    3: 'P4:LAG',
    4: 'P5:PPO',
    5: 'P6:Adaptive',
}

STRATEGIES = [
    strategy_allin,
    strategy_gto,
    strategy_tag,
    strategy_lag,
    strategy_ppo,
    strategy_adaptive,
]

class Player:
    def __init__(self, pid, chips, strategy_fn, name):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = strategy_fn
        self.name = name
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.all_in = False

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.bet_this_round = 0
        self.all_in = False

# ── Engine ───────────────────────────────────────────────────────────────────

def run_betting_round(players, community, pot, big_blind, stage, dealer_pos):
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) <= 1:
        return pot

    for p in players:
        p.bet_this_round = 0

    current_bet = 0
    num_in_hand = len([p for p in players if not p.folded])

    order = []
    start = (dealer_pos + 1) % len(players)
    for i in range(len(players)):
        idx = (start + i) % len(players)
        if not players[idx].folded and not players[idx].all_in:
            order.append(players[idx])

    if not order:
        return pot

    acted = set()
    i = 0
    max_iter = len(order) * (len(order) + 2)
    iteration = 0

    while iteration < max_iter:
        iteration += 1
        if not order:
            break
        p = order[i % len(order)]
        i += 1

        if p.folded or p.all_in:
            continue

        to_call = max(0, current_bet - p.bet_this_round)
        min_raise = max(big_blind, current_bet * 2 - p.bet_this_round)

        gs = GameState(
            hole=p.hole, community=community, pot=pot, my_chips=p.chips,
            to_call=to_call, min_raise=min_raise, stage=stage,
            active_count=num_in_hand, position=order.index(p),
            num_players=len(order), big_blind=big_blind,
        )

        action, amount = p.strategy_fn(gs)

        if action == 'fold':
            p.folded = True
            order = [x for x in order if x.pid != p.pid]
            i = max(0, i - 1)
            acted.discard(p.pid)
            if len([x for x in players if not x.folded]) <= 1:
                break
        elif action == 'check':
            acted.add(p.pid)
        elif action == 'call':
            actual = min(amount, p.chips)
            p.chips -= actual
            p.bet_this_round += actual
            pot += actual
            if p.chips == 0:
                p.all_in = True
                order = [x for x in order if x.pid != p.pid]
                i = max(0, i - 1)
            acted.add(p.pid)
        elif action == 'raise':
            actual = min(amount, p.chips)
            p.chips -= actual
            p.bet_this_round += actual
            pot += actual
            if p.bet_this_round > current_bet:
                current_bet = p.bet_this_round
                acted = {p.pid}
            if p.chips == 0:
                p.all_in = True
                order = [x for x in order if x.pid != p.pid]
                i = max(0, i - 1)
            else:
                acted.add(p.pid)

        remaining = [x for x in order if not x.folded and not x.all_in]
        if all(x.pid in acted for x in remaining):
            if all(x.bet_this_round >= current_bet or x.chips == 0 for x in remaining):
                break

    return pot

def run_hand(players, dealer_pos, big_blind):
    for p in players:
        p.reset_hand()

    active_players = [p for p in players if p.chips > 0]
    if len(active_players) < 2:
        return

    deck = new_deck()
    random.shuffle(deck)

    n = len(active_players)
    sb_pos = (dealer_pos + 1) % n
    bb_pos = (dealer_pos + 2) % n

    pot = 0
    sb = active_players[sb_pos]
    bb = active_players[bb_pos]

    sb_amt = min(big_blind // 2, sb.chips)
    bb_amt = min(big_blind, bb.chips)

    sb.chips -= sb_amt; sb.bet_this_round = sb_amt; pot += sb_amt
    bb.chips -= bb_amt; bb.bet_this_round = bb_amt; pot += bb_amt

    if sb.chips == 0: sb.all_in = True
    if bb.chips == 0: bb.all_in = True

    card_idx = 0
    for p in active_players:
        p.hole = [deck[card_idx], deck[card_idx+1]]
        card_idx += 2

    community = []

    pot = run_betting_round(active_players, community, pot, big_blind, 'pre', bb_pos % n)

    for stage, n_cards in (('flop', 3), ('turn', 1), ('river', 1)):
        still_in = [p for p in active_players if not p.folded]
        if len(still_in) <= 1:
            break
        community += deck[card_idx:card_idx + n_cards]
        card_idx += n_cards
        pot = run_betting_round(active_players, community, pot, big_blind, stage, dealer_pos)

    still_in = [p for p in active_players if not p.folded]
    if len(still_in) == 1:
        still_in[0].chips += pot
        return

    best = None
    winners = []
    for p in still_in:
        score = hand_rank(p.hole + community)
        if best is None or score > best:
            best = score
            winners = [p]
        elif score == best:
            winners.append(p)

    share = pot // len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += pot % len(winners)

# ── Tournament ───────────────────────────────────────────────────────────────

def run_tournament(starting_chips=10000, big_blind_start=100):
    players = [Player(i, starting_chips, STRATEGIES[i], STRATEGY_NAMES[i]) for i in range(6)]

    big_blind = big_blind_start
    hand_num = 0
    dealer_pos = 0

    while True:
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid

        if hand_num > 0 and hand_num % 20 == 0:
            big_blind = int(big_blind * 1.5)

        run_hand(alive, dealer_pos % len(alive), big_blind)
        dealer_pos += 1
        hand_num += 1

        if hand_num > 3000:
            alive = [p for p in players if p.chips > 0]
            return max(alive, key=lambda p: p.chips).pid

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    NUM_SIMS = 100

    print("=" * 62)
    print("  TEXAS HOLD'EM — 100 TOURNAMENT SIMULATIONS (6 players)")
    print("=" * 62)
    print()
    print("Players (10,000 chips each, blinds 50/100 escalating):")
    for pid, name in STRATEGY_NAMES.items():
        tag = '  <-- "if my_turn then bet = All in fi"' if pid == 0 else ''
        print(f"  {name}{tag}")
    print()

    wins = Counter()
    for i in range(NUM_SIMS):
        wins[run_tournament()] += 1
        if (i + 1) % 10 == 0:
            print(f"  ... {i+1}/100 tournaments complete")

    print()
    print("=" * 62)
    print("  WINNER WINNER CHICKEN DINNER — HISTOGRAM (n=100)")
    print("=" * 62)
    print()

    max_wins = max(wins.values())
    BAR = 40
    for pid in range(6):
        w = wins.get(pid, 0)
        bar = '#' * int(round((w / max_wins) * BAR))
        marker = '  <== CHAMPION' if w == max_wins else ('  (zero. brutal.)' if w == 0 else '')
        print(f"  {STRATEGY_NAMES[pid]:>12} |{bar:<{BAR}}| {w:>3}{marker}")

    print()
    print("  FINAL STANDINGS:")
    for rank, (pid, w) in enumerate(sorted(wins.items(), key=lambda x: -x[1]), 1):
        print(f"   {rank}. {STRATEGY_NAMES[pid]} — {w} wins ({w}%)")

    print()
    suflair = wins.get(0, 0)
    if suflair >= max_wins:
        print("  The shove-monkey actually won the meta. Poker is a cruel game.")
    elif suflair > 0:
        print(f"  All-in monkey stole {suflair} tournaments. Variance is undefeated.")
    else:
        print("  All-in monkey went 0/100. As the math gods intended.")
    print("=" * 62)

if __name__ == '__main__':
    random.seed(42)
    main()
