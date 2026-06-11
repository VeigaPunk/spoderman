import random
import itertools
from collections import Counter
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ─────────────────────────── CARD ENGINE ────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards. Returns comparable tuple."""
    best = None
    for combo in itertools.combinations(cards, 5):
        score = score_5(combo)
        if best is None or score > best:
            best = score
    return best

def score_5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0]-5, -1)))
    # wheel straight A-2-3-4-5
    if not straight and ranks == [14,5,4,3,2]:
        straight = True
        ranks = [5,4,3,2,1]
    cnt = sorted(Counter(ranks).values(), reverse=True)
    cnt_ranks = sorted(Counter(ranks).keys(), key=lambda r: (Counter(ranks)[r], r), reverse=True)
    if straight and flush:
        return (8, ranks)
    if cnt[0] == 4:
        return (7, cnt_ranks)
    if cnt[:2] == [3,2]:
        return (6, cnt_ranks)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if cnt[0] == 3:
        return (3, cnt_ranks)
    if cnt[:2] == [2,2]:
        return (2, cnt_ranks)
    if cnt[0] == 2:
        return (1, cnt_ranks)
    return (0, ranks)

# ─────────────────────────── HAND STRENGTH ESTIMATOR ────────────────

def estimate_strength(hole, community, n_opponents=4, samples=200):
    """Monte Carlo hand strength: fraction of rollouts we win."""
    known = set(map(tuple, hole + community))
    remaining_deck = [c for c in make_deck() if tuple(c) not in known]
    wins = 0
    for _ in range(samples):
        deck = remaining_deck[:]
        random.shuffle(deck)
        needed = 5 - len(community)
        board = community + deck[:needed]
        deck = deck[needed:]
        my_rank = hand_rank(hole + board)
        beat = True
        for _ in range(n_opponents):
            opp = deck[:2]
            deck = deck[2:]
            if hand_rank(opp + board) > my_rank:
                beat = False
                break
        if beat:
            wins += 1
    return wins / samples

def pot_odds(call_amount, pot):
    if call_amount == 0:
        return 1.0
    return pot / (pot + call_amount)

def hand_category(hole, community):
    """Quick preflop/postflop category for rule-based logic."""
    if not community:
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited = hole[0][1] == hole[1][1]
        pair = r1 == r2
        high = max(r1, r2)
        gap = abs(r1 - r2)
        if pair and high >= 10: return 'premium_pair'
        if pair: return 'mid_pair'
        if high >= 12 and gap <= 1: return 'premium'
        if high >= 10: return 'playable'
        if suited and gap <= 2: return 'speculative'
        return 'trash'
    return None

# ─────────────────────────── STRATEGIES ─────────────────────────────

def strategy_allin(state):
    """Player 1 — YOLO: always shove."""
    return ('raise', state['player_stack'])

def strategy_tight_aggressive(state):
    """
    Strategy 2 — Nit Assassin
    Plays very few hands but bets hard when it does.
    Folds trash, calls/raises only premium holdings.
    """
    hole = state['hole']
    community = state['community']
    call_amount = state['call_amount']
    pot = state['pot']
    stack = state['player_stack']
    stage = state['stage']
    opponents_left = state['opponents_left']

    if stage == 'preflop':
        cat = hand_category(hole, community)
        if cat in ('premium_pair', 'premium'):
            raise_size = min(stack, max(pot * 3, call_amount * 4))
            return ('raise', raise_size)
        if cat == 'mid_pair' and call_amount <= pot * 0.2:
            return ('call', call_amount)
        if call_amount == 0:
            return ('check', 0)
        return ('fold', 0)

    strength = estimate_strength(hole, community, opponents_left, 150)
    odds = pot_odds(call_amount, pot)

    if strength > 0.80:
        return ('raise', min(stack, pot))
    if strength > 0.60 and call_amount <= pot * 0.4:
        return ('call', call_amount)
    if strength > 0.50 and call_amount == 0:
        return ('check', 0)
    if strength > 0.40 and strength > odds:
        return ('call', call_amount)
    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)

def strategy_loose_passive(state):
    """
    Strategy 3 — The Calling Station
    Calls almost anything, rarely raises, loves to see cards cheap.
    """
    hole = state['hole']
    community = state['community']
    call_amount = state['call_amount']
    pot = state['pot']
    stack = state['player_stack']
    stage = state['stage']
    opponents_left = state['opponents_left']

    if stage == 'preflop':
        cat = hand_category(hole, community)
        if cat == 'trash' and call_amount > pot * 0.5:
            return ('fold', 0)
        if call_amount == 0:
            return ('check', 0)
        return ('call', call_amount)

    strength = estimate_strength(hole, community, opponents_left, 100)
    if strength > 0.75 and call_amount == 0:
        bet = min(stack, pot // 2)
        return ('raise', bet)
    if call_amount == 0:
        return ('check', 0)
    if strength > 0.25 or call_amount <= pot * 0.3:
        return ('call', call_amount)
    return ('fold', 0)

def strategy_bluffer(state):
    """
    Strategy 4 — The Phantom Raiser
    Semi-bluffs aggressively on draws; fires continuation bets;
    gives up on rivers when called down.
    """
    hole = state['hole']
    community = state['community']
    call_amount = state['call_amount']
    pot = state['pot']
    stack = state['player_stack']
    stage = state['stage']
    opponents_left = state['opponents_left']
    bets_this_street = state.get('bets_this_street', 0)

    if stage == 'preflop':
        cat = hand_category(hole, community)
        if cat in ('trash',) and call_amount > pot * 0.3:
            return ('fold', 0)
        if random.random() < 0.35 and call_amount == 0:
            return ('raise', min(stack, pot * 2))
        if call_amount == 0:
            return ('check', 0)
        if cat in ('premium_pair','premium','mid_pair','playable'):
            return ('raise', min(stack, call_amount * 3))
        return ('call', call_amount)

    strength = estimate_strength(hole, community, opponents_left, 100)

    has_draw = _has_draw(hole, community)
    if stage in ('flop', 'turn'):
        if (strength > 0.5 or has_draw) and bets_this_street == 0:
            return ('raise', min(stack, int(pot * 0.75)))
        if strength > 0.65:
            return ('raise', min(stack, pot))
        if strength > 0.35 and call_amount <= pot * 0.5:
            return ('call', call_amount)
        if call_amount == 0:
            return ('check', 0)
        if random.random() < 0.20:
            return ('call', call_amount)
        return ('fold', 0)

    # river — give up bluffs, value-bet monsters
    if strength > 0.70:
        return ('raise', min(stack, pot))
    if strength > 0.45 and call_amount <= pot * 0.3:
        return ('call', call_amount)
    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)

def _has_draw(hole, community):
    if len(community) < 3:
        return False
    cards = hole + community
    suits = [c[1] for c in cards]
    ranks = sorted([RANK_VAL[c[0]] for c in cards])
    flush_draw = max(Counter(suits).values()) >= 4
    # open ended straight draw
    oesd = False
    for i in range(len(ranks)-3):
        window = ranks[i:i+4]
        if window[-1] - window[0] == 3 and len(set(window)) == 4:
            oesd = True
    return flush_draw or oesd

def strategy_gto_approx(state):
    """
    Strategy 5 — GTO Ghost
    Approximates GTO by mixing strategies based on pot odds vs equity.
    Uses randomisation to remain unexploitable.
    """
    hole = state['hole']
    community = state['community']
    call_amount = state['call_amount']
    pot = state['pot']
    stack = state['player_stack']
    stage = state['stage']
    opponents_left = state['opponents_left']

    if stage == 'preflop':
        cat = hand_category(hole, community)
        weights = {
            'premium_pair': ('raise', 0.95),
            'premium':      ('raise', 0.85),
            'mid_pair':     ('raise', 0.55),
            'playable':     ('raise', 0.30),
            'speculative':  ('call', 0.60),
            'trash':        ('fold', 0.80),
        }
        action_pref, aggr_prob = weights.get(cat, ('fold', 0.90))
        if action_pref == 'fold':
            if random.random() < aggr_prob:
                if call_amount == 0: return ('check', 0)
                return ('fold', 0)
            return ('call', call_amount)
        if random.random() < aggr_prob:
            size = min(stack, max(call_amount * 3, pot))
            return ('raise', size)
        return ('call', call_amount) if call_amount > 0 else ('check', 0)

    strength = estimate_strength(hole, community, opponents_left, 150)
    odds = pot_odds(call_amount, pot)

    # Mixed strategy based on equity buckets
    if strength > 0.85:
        if random.random() < 0.8:
            return ('raise', min(stack, pot))
        return ('call', call_amount) if call_amount > 0 else ('check', 0)
    if strength > 0.65:
        if call_amount == 0:
            return ('raise', min(stack, pot // 2)) if random.random() < 0.6 else ('check', 0)
        if random.random() < 0.5:
            return ('raise', min(stack, int(pot * 0.75)))
        return ('call', call_amount)
    if strength > 0.45:
        if strength > odds:
            return ('call', call_amount) if call_amount > 0 else ('check', 0)
        if call_amount == 0:
            return ('check', 0)
        if random.random() < 0.15:
            return ('call', call_amount)
        return ('fold', 0)
    if call_amount == 0:
        return ('check', 0)
    if random.random() < 0.08:
        return ('raise', min(stack, int(pot * 0.5)))
    return ('fold', 0)

def strategy_position_player(state):
    """
    Strategy 6 — The Positional Predator
    Heavily exploits position: plays wider in late position,
    squeezes from the button, check-raises out of position.
    """
    hole = state['hole']
    community = state['community']
    call_amount = state['call_amount']
    pot = state['pot']
    stack = state['player_stack']
    stage = state['stage']
    opponents_left = state['opponents_left']
    position = state.get('position', 0)   # 0=early … 1=late
    bets_this_street = state.get('bets_this_street', 0)

    if stage == 'preflop':
        cat = hand_category(hole, community)
        # Late position: widen range
        playable_threshold = 0.5 if position > 0.6 else 0.8
        play_map = {'premium_pair':1,'premium':1,'mid_pair':0.85,'playable':0.65,'speculative':0.45,'trash':0.15}
        if random.random() > play_map.get(cat, 0.1) * (1 + 0.3 * position):
            if call_amount == 0: return ('check', 0)
            return ('fold', 0)
        if cat in ('premium_pair','premium') or (position > 0.7 and cat in ('mid_pair','playable')):
            size = min(stack, max(call_amount * 3, pot))
            return ('raise', size)
        return ('call', call_amount) if call_amount > 0 else ('check', 0)

    strength = estimate_strength(hole, community, opponents_left, 150)

    # Out of position: check-raise traps
    if position < 0.4 and call_amount == 0 and strength > 0.70 and bets_this_street == 0:
        return ('check', 0)  # plan to check-raise next action

    if position > 0.6:
        if strength > 0.55 and call_amount == 0:
            return ('raise', min(stack, int(pot * 0.65)))
        if strength > 0.45 and call_amount <= pot * 0.4:
            return ('call', call_amount)
        if strength > 0.35 and call_amount == 0:
            return ('check', 0)
    else:
        if strength > 0.65 and call_amount == 0:
            return ('raise', min(stack, int(pot * 0.5)))
        if strength > 0.50 and call_amount <= pot * 0.3:
            return ('call', call_amount)

    odds = pot_odds(call_amount, pot)
    if strength > odds and call_amount <= pot * 0.5:
        return ('call', call_amount)
    if call_amount == 0:
        return ('check', 0)
    return ('fold', 0)

STRATEGIES = [
    strategy_allin,
    strategy_tight_aggressive,
    strategy_loose_passive,
    strategy_bluffer,
    strategy_gto_approx,
    strategy_position_player,
]
STRATEGY_NAMES = [
    "P1: YOLO All-In",
    "P2: Nit Assassin",
    "P3: Calling Station",
    "P4: Phantom Raiser",
    "P5: GTO Ghost",
    "P6: Positional Predator",
]

# ─────────────────────────── GAME ENGINE ─────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND = 10
BIG_BLIND = 20

class Player:
    def __init__(self, pid, strategy, chips):
        self.pid = pid
        self.strategy = strategy
        self.chips = chips
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

    def reset_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0

def run_hand(players, dealer_idx):
    """Run a single hand. Returns chip deltas dict {pid: delta}."""
    n = len(players)
    active = [p for p in players if p.chips > 0]
    if len(active) < 2:
        return {}

    for p in players:
        p.reset_hand()

    deck = make_deck()
    random.shuffle(deck)

    # deal hole cards
    for p in active:
        p.hole = [deck.pop(), deck.pop()]

    community = []
    pot = 0
    side_pots = []

    # blinds
    active_indices = [i for i, p in enumerate(players) if p.chips > 0]
    n_active = len(active_indices)
    sb_idx = active_indices[(dealer_idx + 1) % n_active]
    bb_idx = active_indices[(dealer_idx + 2) % n_active]

    def post_blind(pidx, amount):
        nonlocal pot
        p = players[pidx]
        actual = min(p.chips, amount)
        p.chips -= actual
        p.bet += actual
        pot += actual
        if p.chips == 0:
            p.all_in = True
        return actual

    post_blind(sb_idx, SMALL_BLIND)
    post_blind(bb_idx, BIG_BLIND)

    def betting_round(stage, first_to_act_offset=0):
        nonlocal pot
        still_in = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
        if len(still_in) <= 1:
            return

        current_bet = max(p.bet for p in players)
        checked_or_called = set()
        last_raiser = None

        order = [p for p in players if not p.folded and p.chips > 0]
        # rotate to first actor
        if stage == 'preflop':
            start = (active_indices.index(bb_idx) + 1) % n_active
            order_ids = [active_indices[(start + i) % n_active] for i in range(n_active)]
            order = [players[i] for i in order_ids if not players[i].folded and players[i].chips > 0]
        else:
            start = (dealer_idx + 1) % n_active
            order_ids = [active_indices[(start + i) % n_active] for i in range(n_active)]
            order = [players[i] for i in order_ids if not players[i].folded and players[i].chips > 0]

        max_iter = len(order) * 4
        iterations = 0
        idx = 0
        while iterations < max_iter:
            iterations += 1
            to_act = [p for p in order if not p.folded and not p.all_in and p.chips > 0]
            if not to_act:
                break
            # check if betting is closed
            uncalled = [p for p in to_act if p.bet < current_bet or p not in checked_or_called]
            if not uncalled and last_raiser is not None:
                break
            if not uncalled and last_raiser is None:
                break

            p = uncalled[0] if uncalled else to_act[0]
            if p in checked_or_called and p != last_raiser:
                break

            call_amount = max(0, current_bet - p.bet)
            call_amount = min(call_amount, p.chips)

            opponents_left = len([x for x in players if not x.folded and x.pid != p.pid])
            position_val = order.index(p) / max(len(order)-1, 1)
            bets_this = sum(1 for x in players if x.bet > (SMALL_BLIND if stage=='preflop' else 0))

            state = {
                'hole': p.hole,
                'community': community,
                'call_amount': call_amount,
                'pot': pot,
                'player_stack': p.chips,
                'stage': stage,
                'opponents_left': opponents_left,
                'position': position_val,
                'bets_this_street': bets_this,
            }

            action, amount = p.strategy(state)

            if action == 'fold':
                p.folded = True
                checked_or_called.discard(p)
                order = [x for x in order if x != p]
                continue
            elif action == 'check':
                if call_amount > 0:
                    # forced to call or fold; treat as call
                    actual = min(call_amount, p.chips)
                    p.chips -= actual
                    p.bet += actual
                    pot += actual
                    if p.chips == 0:
                        p.all_in = True
                checked_or_called.add(p)
            elif action == 'call':
                actual = min(call_amount, p.chips)
                p.chips -= actual
                p.bet += actual
                pot += actual
                if p.chips == 0:
                    p.all_in = True
                checked_or_called.add(p)
            elif action == 'raise':
                min_raise = call_amount + BIG_BLIND
                raise_total = max(int(amount), min_raise)
                raise_total = min(raise_total, p.chips)
                p.chips -= raise_total
                p.bet += raise_total
                pot += raise_total
                if p.bet > current_bet:
                    current_bet = p.bet
                    last_raiser = p
                    checked_or_called = {p}
                if p.chips == 0:
                    p.all_in = True
                else:
                    checked_or_called.add(p)

            # remove fully acted players
            remaining = [x for x in to_act if not x.folded and not x.all_in and x.chips > 0]
            unchecked = [x for x in remaining if x.bet < current_bet]
            if not unchecked and all(x in checked_or_called for x in remaining):
                break

        # reset bets for next street
        for p in players:
            p.bet = 0

    # preflop
    betting_round('preflop')

    still_contesting = [p for p in players if not p.folded]
    if len(still_contesting) <= 1:
        winner = still_contesting[0] if still_contesting else None
        if winner:
            delta = {p.pid: -p.bet for p in players}
            # pot already deducted from chips; winner gets pot back
            winner.chips += pot
            delta[winner.pid] += pot
        return {}

    # flop
    deck.pop()  # burn
    community += [deck.pop(), deck.pop(), deck.pop()]
    betting_round('flop')

    still_contesting = [p for p in players if not p.folded]
    if len(still_contesting) <= 1:
        winner = still_contesting[0] if still_contesting else None
        if winner:
            winner.chips += pot
        return {}

    # turn
    deck.pop()
    community.append(deck.pop())
    betting_round('turn')

    still_contesting = [p for p in players if not p.folded]
    if len(still_contesting) <= 1:
        winner = still_contesting[0] if still_contesting else None
        if winner:
            winner.chips += pot
        return {}

    # river
    deck.pop()
    community.append(deck.pop())
    betting_round('river')

    # showdown
    contenders = [p for p in players if not p.folded]
    if not contenders:
        return {}
    if len(contenders) == 1:
        contenders[0].chips += pot
        return {}

    ranked = sorted(contenders, key=lambda p: hand_rank(p.hole + community), reverse=True)
    best = hand_rank(ranked[0].hole + community)
    winners = [p for p in ranked if hand_rank(p.hole + community) == best]
    share = pot // len(winners)
    remainder = pot % len(winners)
    for p in winners:
        p.chips += share
    winners[0].chips += remainder
    return {}

def run_tournament():
    """Run one tournament (eliminating players until 1 remains). Return winner pid."""
    players = [Player(i+1, STRATEGIES[i], STARTING_CHIPS) for i in range(6)]
    dealer = 0
    max_hands = 500

    for hand_num in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        run_hand(players, dealer % len(alive))
        dealer += 1

    alive = [p for p in players if p.chips > 0]
    if alive:
        return max(alive, key=lambda p: p.chips).pid
    return -1

# ─────────────────────────── SIMULATION ──────────────────────────────

print("Running 100 Texas Hold'em tournament simulations...")
print("Player 1: YOLO All-In  |  Players 2-6: Elaborate strategies")
print("─" * 60)

N_SIMS = 100
wins = Counter()

for sim in range(N_SIMS):
    winner_pid = run_tournament()
    wins[winner_pid] += 1
    if (sim + 1) % 10 == 0:
        print(f"  Completed {sim+1}/100 simulations...")

print("\n" + "═" * 60)
print("RESULTS — LAST PLAYER STANDING (100 tournaments)")
print("═" * 60)
for pid in range(1, 7):
    name = STRATEGY_NAMES[pid-1]
    w = wins.get(pid, 0)
    bar = "█" * w + "░" * (100 - w)
    print(f"  {name:<28}  {w:>3} wins  |{bar}|")
print("═" * 60)

# ─────────────────────────── HISTOGRAM ───────────────────────────────

fig, ax = plt.subplots(figsize=(13, 7))
fig.patch.set_facecolor('#0d1117')
ax.set_facecolor('#0d1117')

colors = ['#ff4444', '#4488ff', '#44cc44', '#ffaa00', '#aa44ff', '#00cccc']
x = np.arange(1, 7)
win_counts = [wins.get(i, 0) for i in range(1, 7)]

bars = ax.bar(x, win_counts, color=colors, edgecolor='white', linewidth=0.8, width=0.65, zorder=3)

# annotate bars
for bar, count in zip(bars, win_counts):
    if count > 0:
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                str(count), ha='center', va='bottom', color='white',
                fontsize=13, fontweight='bold')

ax.set_xticks(x)
ax.set_xticklabels(STRATEGY_NAMES, rotation=20, ha='right', color='white', fontsize=10)
ax.set_ylabel('Tournaments Won  (out of 100)', color='#aaaaaa', fontsize=12)
ax.set_title('Texas Hold\'em — 100 Simulations\nWinner Winner Chicken Dinner 🐔', color='white', fontsize=16, fontweight='bold', pad=18)
ax.tick_params(colors='white')
ax.spines['bottom'].set_color('#444')
ax.spines['left'].set_color('#444')
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.yaxis.grid(True, color='#222', linestyle='--', zorder=0)
ax.set_ylim(0, max(win_counts) + 8)

# legend note
note_lines = [
    "P1  YOLO All-In       → Always shoves entire stack",
    "P2  Nit Assassin      → Tight-aggressive, premium hands only",
    "P3  Calling Station   → Loose-passive, sees every flop cheap",
    "P4  Phantom Raiser    → Semi-bluffs, C-bets, fires barrels",
    "P5  GTO Ghost         → Mixed equity-based GTO approximation",
    "P6  Positional Pred.  → Exploits position, squeezes & check-raises",
]
note = "\n".join(note_lines)
fig.text(0.01, -0.04, note, fontsize=7.5, color='#888888',
         verticalalignment='top', fontfamily='monospace',
         transform=ax.transAxes)

plt.tight_layout()
plt.savefig('/home/user/spoderman/poker_histogram.png', dpi=150, bbox_inches='tight',
            facecolor=fig.get_facecolor())
print("\nHistogram saved → poker_histogram.png")
