"""
Texas Hold'em Poker Simulation
6 players, 100 games.
Player 1 (AllIn_Maniac): always goes all-in.
Players 2-6: elaborate strategies (GTO, TAG, LAG, Position, Bluff).
"""
import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────
# CARDS
# ─────────────────────────────────────────────
SUITS = ['s', 'h', 'd', 'c']
RANKS = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

class Card:
    __slots__ = ('rank', 'suit', 'value')
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
        self.value = RANK_VAL[rank]
    def __repr__(self):
        return f"{self.rank}{self.suit}"
    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit
    def __hash__(self):
        return hash((self.rank, self.suit))

FULL_DECK = [Card(r, s) for s in SUITS for r in RANKS]

def fresh_deck():
    deck = FULL_DECK[:]
    random.shuffle(deck)
    return deck

# ─────────────────────────────────────────────
# HAND EVALUATION
# ─────────────────────────────────────────────
def eval_five(cards):
    """Score exactly 5 cards; higher = better."""
    vals = sorted([c.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    cnt = Counter(vals)
    groups = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    group_counts = [g[1] for g in groups]
    ranked_vals = [v for v, _ in groups for _ in range(cnt[v])]

    is_flush = len(set(suits)) == 1
    is_str8 = len(set(vals)) == 5 and vals[0] - vals[4] == 4
    # Wheel A-2-3-4-5
    if set(vals) == {12, 0, 1, 2, 3}:
        is_str8 = True
        vals = [3, 2, 1, 0, -1]
        ranked_vals = vals

    if is_str8 and is_flush:
        return (8, vals[0])
    if group_counts[0] == 4:
        return (7, *ranked_vals)
    if group_counts[:2] == [3, 2]:
        return (6, *ranked_vals)
    if is_flush:
        return (5, *vals)
    if is_str8:
        return (4, vals[0])
    if group_counts[0] == 3:
        return (3, *ranked_vals)
    if group_counts[:2] == [2, 2]:
        return (2, *ranked_vals)
    if group_counts[0] == 2:
        return (1, *ranked_vals)
    return (0, *vals)

def best_hand(all_cards):
    return max(eval_five(list(c)) for c in combinations(all_cards, 5))

# ─────────────────────────────────────────────
# HAND STRENGTH (sampled equity)
# ─────────────────────────────────────────────
def hand_strength(hole, community, samples=80):
    used = set(hole + community)
    deck_rem = [c for c in FULL_DECK if c not in used]
    need = 5 - len(community)
    my_rank = best_hand(hole + community) if len(community) >= 3 else None

    wins = ties = total = 0
    for _ in range(samples):
        board_extra = random.sample(deck_rem, need) if need > 0 else []
        full_board = community + board_extra
        opp_hole = random.sample([c for c in deck_rem if c not in board_extra], 2)
        my_r = best_hand(hole + full_board)
        op_r = best_hand(opp_hole + full_board)
        if my_r > op_r:
            wins += 1
        elif my_r == op_r:
            ties += 1
        total += 1
    return (wins + 0.5 * ties) / total if total else 0.5

def preflop_quick(hole):
    """Fast pre-flop strength heuristic."""
    c1, c2 = hole
    v1, v2 = max(c1.value, c2.value), min(c1.value, c2.value)
    suited = c1.suit == c2.suit
    paired = c1.rank == c2.rank
    gap = v1 - v2

    if paired:
        return 0.45 + v1 / 28.0  # 0.45..0.91
    base = (v1 + v2) / 28.0
    if suited:
        base += 0.04
    if gap == 1:
        base += 0.02
    elif gap == 0:
        base += 0.04
    return min(0.88, max(0.05, base))

def get_strength(hole, community):
    if not community:
        return preflop_quick(hole)
    return hand_strength(hole, community)

# ─────────────────────────────────────────────
# PLAYER
# ─────────────────────────────────────────────
class Player:
    def __init__(self, name, strategy_fn, chips=1000):
        self.name = name
        self.strategy_fn = strategy_fn
        self.chips = chips
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0  # chips committed this street

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

    def act(self, state):
        return self.strategy_fn(self, state)

# ─────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────

# 1. Simple: always all-in
def s_allin(player, state):
    return 'allin', player.chips

# 2. GTO-inspired: pot odds + hand strength + balanced ranges
def s_gto(player, state):
    strength = get_strength(player.hole, state['community'])
    call_need = state['cur_bet'] - player.bet
    pot = state['pot']

    if call_need > 0:
        pot_odds = call_need / (pot + call_need + 1e-9)
        if strength < pot_odds - 0.05:
            return 'fold', 0

    if strength > 0.82:
        return 'raise', min(player.chips, max(state['min_raise'], pot * 2))
    if strength > 0.65:
        bet = min(player.chips, max(state['min_raise'], int(pot * 0.7)))
        return 'raise', bet
    if strength > 0.48:
        if call_need == 0:
            return 'check', 0
        return 'call', call_need
    # Occasional bluff
    if call_need == 0 and random.random() < 0.12:
        return 'raise', min(player.chips, state['min_raise'])
    if call_need > 0 and call_need > player.chips * 0.35:
        return 'fold', 0
    return 'check', 0

# 3. Tight-Aggressive (TAG): premium hands only, punish post-flop
def s_tag(player, state):
    strength = get_strength(player.hole, state['community'])
    call_need = state['cur_bet'] - player.bet
    pot = state['pot']
    street = state['street']

    # Very tight pre-flop
    if street == 'preflop' and strength < 0.60:
        return ('fold', 0) if call_need > 0 else ('check', 0)

    if strength > 0.78:
        return 'raise', min(player.chips, max(state['min_raise'], pot * 3))
    if strength > 0.58:
        if call_need == 0:
            return 'check', 0
        if call_need < player.chips * 0.25:
            return 'call', call_need
        return 'fold', 0
    if call_need == 0:
        return 'check', 0
    return 'fold', 0

# 4. Loose-Aggressive (LAG): wide range, constant pressure
def s_lag(player, state):
    strength = get_strength(player.hole, state['community'])
    call_need = state['cur_bet'] - player.bet
    pot = state['pot']
    pos = state['position']
    n_act = state['n_active']
    # late position bonus
    pos_bonus = 0.08 if pos >= n_act // 2 else 0.0
    eff = min(0.99, strength + pos_bonus)

    if eff > 0.55:
        amt = min(player.chips, max(state['min_raise'], int(pot * (0.5 + random.random() * 0.5))))
        return 'raise', amt
    if eff > 0.38:
        if call_need == 0:
            if random.random() < 0.45:
                return 'raise', min(player.chips, max(state['min_raise'], pot // 2))
            return 'check', 0
        if call_need < player.chips * 0.28:
            return 'call', call_need
        return 'fold', 0
    # Bluff / probe with weak hands
    if call_need == 0 and random.random() < 0.28:
        return 'raise', min(player.chips, state['min_raise'])
    if call_need > 0:
        return 'fold', 0
    return 'check', 0

# 5. Position-Based: adjusts thresholds by seat
def s_position(player, state):
    strength = get_strength(player.hole, state['community'])
    call_need = state['cur_bet'] - player.bet
    pot = state['pot']
    pos = state['position']
    n_act = state['n_active']
    rel = pos / max(n_act - 1, 1)  # 0=UTG, 1=BTN

    fold_thresh = 0.42 - rel * 0.14
    raise_thresh = 0.72 - rel * 0.16

    if strength > raise_thresh:
        size = int(pot * (0.75 + rel * 0.6))
        return 'raise', min(player.chips, max(state['min_raise'], size))
    if strength > fold_thresh:
        if call_need == 0:
            if rel > 0.55 and random.random() < 0.35:
                return 'raise', min(player.chips, max(state['min_raise'], pot // 3))
            return 'check', 0
        limit = player.chips * (0.15 + rel * 0.22)
        if call_need <= limit:
            return 'call', call_need
        return 'fold', 0
    if call_need == 0:
        return 'check', 0
    return 'fold', 0

# 6. Bluff-Artist: polar bets (monster or air), traps mid-range
def s_bluff(player, state):
    strength = get_strength(player.hole, state['community'])
    call_need = state['cur_bet'] - player.bet
    pot = state['pot']
    street = state['street']

    if strength > 0.78:
        return 'raise', min(player.chips, max(state['min_raise'], pot * 2))
    if strength > 0.52:
        # Trap: slow-play strong hands
        if call_need == 0:
            return 'check', 0
        return 'call', call_need
    # Bluff territory
    bluff_p = {'preflop': 0.30, 'flop': 0.38, 'turn': 0.22, 'river': 0.14}.get(street, 0.2)
    if random.random() < bluff_p:
        size = int(pot * (0.55 + random.random() * 0.7))
        return 'raise', min(player.chips, max(state['min_raise'], size))
    if call_need > 0:
        return 'fold', 0
    return 'check', 0

# ─────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────
SB = 10
BB = 20

def run_hand(players, dealer_idx):
    """
    Run one hand. Returns index of winner (last man standing or showdown).
    Modifies players[i].chips in place.
    """
    n = len(players)
    active = [p for p in players if p.chips > 0]
    if len(active) < 2:
        return

    for p in active:
        p.reset_hand()

    deck = fresh_deck()
    for p in active:
        p.hole = [deck.pop(), deck.pop()]

    # Blinds
    n_a = len(active)
    sb_p = active[dealer_idx % n_a]
    bb_p = active[(dealer_idx + 1) % n_a]
    utg_idx = (dealer_idx + 2) % n_a

    sb_amt = min(SB, sb_p.chips)
    bb_amt = min(BB, bb_p.chips)
    sb_p.chips -= sb_amt; sb_p.bet = sb_amt
    bb_p.chips -= bb_amt; bb_p.bet = bb_amt
    if sb_p.chips == 0: sb_p.all_in = True
    if bb_p.chips == 0: bb_p.all_in = True
    pot = sb_amt + bb_amt

    community = []
    streets = [
        ('preflop', []),
        ('flop',    [deck.pop(), deck.pop(), deck.pop()]),
        ('turn',    [deck.pop()]),
        ('river',   [deck.pop()]),
    ]

    for street_name, new_cards in streets:
        community.extend(new_cards)

        if street_name == 'preflop':
            cur_bet = bb_amt
            first = utg_idx
        else:
            cur_bet = 0
            first = (dealer_idx + 1) % n_a
            for p in active:
                p.bet = 0

        pot = _betting_round(active, pot, cur_bet, first, community, street_name, n_a)

        alive = [p for p in active if not p.folded]
        if len(alive) == 1:
            alive[0].chips += pot
            return

    # Showdown
    contenders = [p for p in active if not p.folded]
    if contenders:
        _showdown(contenders, community, pot)

def _betting_round(active, pot, cur_bet, first_idx, community, street, n_a):
    min_raise = BB

    # Build action order starting from first_idx
    order = []
    for i in range(len(active)):
        p = active[(first_idx + i) % len(active)]
        if not p.folded and not p.all_in:
            order.append(p)

    if not order:
        return pot

    acted = set()
    ptr = 0
    safety = 0

    while safety < 200:
        safety += 1
        if not order:
            break
        player = order[ptr % len(order)]

        if player.folded or player.all_in:
            ptr += 1
            continue

        can_go = [p for p in active if not p.folded and not p.all_in]
        if not can_go:
            break

        # If everyone has matched cur_bet and everyone who can has acted
        if all(p.bet >= cur_bet for p in can_go) and player in acted:
            # Check if any player still hasn't acted yet
            unacted = [p for p in can_go if p not in acted]
            if not unacted:
                break

        pos_in_active = active.index(player) if player in active else 0
        n_active_now = len([p for p in active if not p.folded])

        state = {
            'community': community,
            'pot': pot,
            'cur_bet': cur_bet,
            'min_raise': max(min_raise, cur_bet + BB),
            'position': pos_in_active,
            'n_active': n_active_now,
            'street': street,
        }

        action, amount = player.act(state)
        call_need = max(0, cur_bet - player.bet)

        if action == 'fold':
            player.folded = True
            alive = [p for p in active if not p.folded]
            if len(alive) == 1:
                return pot
        elif action in ('check', 'call'):
            if call_need > 0:
                spend = min(call_need, player.chips)
                player.chips -= spend
                player.bet += spend
                pot += spend
                if player.chips == 0:
                    player.all_in = True
        elif action in ('raise', 'allin'):
            if action == 'allin':
                amount = player.chips
            # total amount is raise ABOVE cur_bet
            total_target = cur_bet + max(amount, BB)
            spend = min(total_target - player.bet, player.chips)
            spend = max(spend, min(call_need, player.chips))  # at least call
            player.chips -= spend
            player.bet += spend
            pot += spend
            if player.bet > cur_bet:
                new_raise = player.bet - cur_bet
                if new_raise >= min_raise or player.chips == 0:
                    min_raise = new_raise
                cur_bet = player.bet
                # Everyone else must act again
                acted = {player}
            if player.chips == 0:
                player.all_in = True

        acted.add(player)
        ptr += 1

        # Re-evaluate order (players may have folded/gone all-in)
        order = [p for p in order if not p.folded and not p.all_in]
        if not order:
            break
        ptr = ptr % max(len(order), 1)

    return pot

def _showdown(contenders, community, pot):
    scored = [(best_hand(p.hole + community), p) for p in contenders]
    best = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == best]
    share = pot // len(winners)
    rem = pot % len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += rem

# ─────────────────────────────────────────────
# SIMULATION RUNNER
# ─────────────────────────────────────────────
STRATEGY_MAP = [
    ("AllIn_Maniac",   s_allin),     # Player 1 — the simple one
    ("GTO_Pro",        s_gto),
    ("TAG_Rock",       s_tag),
    ("LAG_Shark",      s_lag),
    ("Position_King",  s_position),
    ("Bluff_Artist",   s_bluff),
]

def simulate(n_sims=100, start_chips=1000, max_hands=600):
    wins = Counter()

    for sim_i in range(n_sims):
        players = [Player(name, fn, start_chips) for name, fn in STRATEGY_MAP]
        dealer = 0

        for hand_n in range(max_hands):
            alive = [p for p in players if p.chips > 0]
            if len(alive) <= 1:
                break
            # Dealer position within alive players
            run_hand(alive, dealer % len(alive))
            dealer += 1

        alive = [p for p in players if p.chips > 0]
        if alive:
            champion = max(alive, key=lambda p: p.chips)
            wins[champion.name] += 1

        if (sim_i + 1) % 10 == 0:
            print(f"  ... {sim_i + 1}/{n_sims} sims done", flush=True)

    return wins

# ─────────────────────────────────────────────
# HISTOGRAM PRINTER
# ─────────────────────────────────────────────
def print_histogram(wins, n_sims):
    total = sum(wins.values())
    ranked = sorted(STRATEGY_MAP, key=lambda x: wins.get(x[0], 0), reverse=True)
    max_w = max((wins.get(n, 0) for n, _ in ranked), default=1)
    BAR = 42

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   TEXAS HOLD'EM — 100 SIMULATION RESULTS                    ║")
    print("║   WINNER WINNER CHICKEN DINNER — Last Chip Holder           ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  {'Player':<18}  {'Wins':>4}  {'%':>6}  Bar                         ║")
    print("╠══════════════════════════════════════════════════════════════╣")

    medals = ['🥇','🥈','🥉','  ','  ','  ']
    for rank_i, (name, _) in enumerate(ranked):
        w = wins.get(name, 0)
        pct = w / n_sims * 100
        bar_len = int(w / max(max_w, 1) * BAR)
        bar = '█' * bar_len + '░' * (BAR - bar_len)
        medal = medals[rank_i]
        tag = " ← ALL-IN BOT" if name == "AllIn_Maniac" else ""
        line = f"║ {medal} {name:<17} {w:>4}  {pct:>5.1f}%  {bar}{tag}"
        # pad to width 64
        line = line.ljust(63) + "║"
        print(line)

    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Total sims: {n_sims}  |  6 players  |  1000 chips each         ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    champ_name = ranked[0][0]
    allin_w = wins.get('AllIn_Maniac', 0)
    allin_pct = allin_w / n_sims * 100

    print(f"  *** CHAMPION: {champ_name} with {wins.get(champ_name,0)} wins ***")
    print()
    if allin_w == wins.get(champ_name, 0):
        print("  PURE CHAOS WINS. The all-in monkey defeats everyone.")
        print("  Poker is rigged, apparently. Suflair GPT would love this.")
    elif allin_pct < 12:
        print(f"  AllIn_Maniac: {allin_w} wins ({allin_pct:.1f}%) — HUMILIATED.")
        print("  Brainless aggression got wrecked by actual strategy.")
        print("  Suflair GPT == AllIn_Maniac confirmed. GET REKT.")
    else:
        print(f"  AllIn_Maniac scraped {allin_w} wins ({allin_pct:.1f}%) — still bottom tier.")
        print("  Suflair GPT tries to all-in knowledge it doesn't have. Sad.")

if __name__ == '__main__':
    print("Texas Hold'em Poker Simulation")
    print("================================")
    print("Strategies:")
    print("  Player 1  — AllIn_Maniac   : if my_turn: bet = ALL IN")
    print("  Player 2  — GTO_Pro        : pot odds + balanced ranges")
    print("  Player 3  — TAG_Rock       : premium hands only, bet hard")
    print("  Player 4  — LAG_Shark      : wide range, constant pressure")
    print("  Player 5  — Position_King  : position-adjusted thresholds")
    print("  Player 6  — Bluff_Artist   : polarized polar betting + traps")
    print()
    print("Running 100 simulations (this may take ~60s)...")
    print()

    random.seed(1337)
    wins = simulate(n_sims=100, start_chips=1000, max_hands=600)
    print_histogram(wins, n_sims=100)
