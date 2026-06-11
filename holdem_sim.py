"""
Texas Hold'em Poker Simulation
6 players, 100 games, histogram of winners.
Player 1: Simple All-In strategy
Players 2-6: Elaborate strategies
"""

import random
import itertools
from collections import Counter
import sys

# ─────────────────────────────────────────────
# CARD / DECK PRIMITIVES
# ─────────────────────────────────────────────

RANKS = '23456789TJQKA'
SUITS = 'cdhs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ─────────────────────────────────────────────
# HAND EVALUATION  (returns comparable tuple)
# ─────────────────────────────────────────────

def hand_rank(cards):
    """Evaluate best 5-card hand out of up to 7 cards."""
    best = None
    for combo in itertools.combinations(cards, 5):
        score = _score5(combo)
        if best is None or score > best:
            best = score
    return best

def _score5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush   = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5) or \
               (ranks == [14, 5, 4, 3, 2])  # wheel
    if straight and ranks[0] == 5:          # wheel – ace plays low
        ranks = [5, 4, 3, 2, 1]

    cnt   = Counter(ranks)
    groups = sorted(cnt.values(), reverse=True)
    vals   = sorted(cnt.keys(), key=lambda x: (cnt[x], x), reverse=True)

    if flush and straight:  return (8, vals)
    if groups == [4, 1]:    return (7, vals)
    if groups == [3, 2]:    return (6, vals)
    if flush:               return (5, vals)
    if straight:            return (4, vals)
    if groups[0] == 3:      return (3, vals)
    if groups[:2] == [2,2]: return (2, vals)
    if groups[0] == 2:      return (1, vals)
    return (0, vals)

# ─────────────────────────────────────────────
# GAME STATE
# ─────────────────────────────────────────────

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20

class Player:
    def __init__(self, pid, chips, strategy_fn):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy_fn
        self.hole     = []
        self.bet      = 0        # chips committed this round
        self.folded   = False
        self.all_in   = False

    def reset_for_hand(self):
        self.hole    = []
        self.bet     = 0
        self.folded  = False
        self.all_in  = False

    def __repr__(self):
        return f"P{self.pid}(${self.chips})"


class GameState:
    """Snapshot passed to strategy functions – read-only view."""
    def __init__(self, player, community, pot, current_bet, players_info,
                 street, position, num_active):
        self.my_hole       = player.hole[:]
        self.my_chips      = player.chips
        self.my_bet        = player.bet
        self.community     = community[:]
        self.pot           = pot
        self.current_bet   = current_bet   # highest bet on table this round
        self.to_call       = max(0, current_bet - player.bet)
        self.players_info  = players_info  # list of (chips, folded, all_in) per player
        self.street        = street        # 'preflop','flop','turn','river'
        self.position      = position      # 0-indexed seat from dealer
        self.num_active    = num_active    # players still in hand

# ─────────────────────────────────────────────
# STRATEGY HELPERS
# ─────────────────────────────────────────────

def hand_strength(hole, community):
    """Monte-Carlo estimate of win probability."""
    if not community:
        # preflop: use simple lookup table approximation
        r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
        suited  = hole[0][1] == hole[1][1]
        hi, lo  = max(r1, r2), min(r1, r2)
        score   = hi * 0.07 + lo * 0.05 + (0.04 if suited else 0) + \
                  (0.15 if hi == lo else 0)   # pair bonus
        return min(score, 0.95)

    deck   = make_deck()
    known  = set(tuple(c) for c in hole + community)
    remain = [c for c in deck if c not in known]

    wins = 0
    trials = 200
    cards_needed = 5 - len(community)
    for _ in range(trials):
        sample = random.sample(remain, cards_needed + 2)
        opp    = sample[:2]
        board  = community + sample[2:]
        my_score  = hand_rank(hole + board)
        opp_score = hand_rank(opp  + board)
        if my_score > opp_score:
            wins += 1
        elif my_score == opp_score:
            wins += 0.5
    return wins / trials

def pot_odds(state):
    if state.pot + state.to_call == 0:
        return 1.0
    return state.pot / (state.pot + state.to_call)

# ─────────────────────────────────────────────
# THE 6 STRATEGIES
# ─────────────────────────────────────────────

# ── Strategy 0: ALWAYS ALL-IN (Player 1) ─────
def strategy_allin(state):
    """If my turn, bet = ALL IN."""
    return ('raise', state.my_chips)


# ── Strategy 1: TIGHT-AGGRESSIVE (TAG) ───────
def strategy_tag(state):
    """
    Play only premium hands. Raise big when strong, fold the rest.
    Post-flop: continue only with top-pair+ or draws to the nuts.
    """
    strength = hand_strength(state.my_hole, state.community)
    to_call  = state.to_call

    if state.street == 'preflop':
        r1, r2 = RANK_VAL[state.my_hole[0][0]], RANK_VAL[state.my_hole[1][0]]
        hi, lo = max(r1, r2), min(r1, r2)
        suited  = state.my_hole[0][1] == state.my_hole[1][1]
        premium = (hi >= 12 and lo >= 10) or (hi == lo and hi >= 8) or \
                  (hi == 14 and lo >= 8) or (suited and hi >= 12)

        if not premium:
            if to_call == 0:
                return ('check', 0)
            if to_call <= BIG_BLIND:
                return ('call', to_call)
            return ('fold', 0)

        # premium – raise 3x BB or pot-size raise
        raise_to = max(BIG_BLIND * 3, state.current_bet * 2 + BIG_BLIND)
        raise_by = max(0, raise_to - state.my_bet)
        if raise_by > state.my_chips:
            return ('raise', state.my_chips)
        return ('raise', raise_by)

    # post-flop
    odds = pot_odds(state)
    if strength < 0.45 and to_call > 0:
        return ('fold', 0)
    if strength < 0.55:
        if to_call == 0:
            return ('check', 0)
        if to_call <= state.pot * 0.25:
            return ('call', to_call)
        return ('fold', 0)
    # strong hand
    bet_size = int(state.pot * 0.75)
    if to_call > 0:
        bet_size = max(bet_size, to_call)
    bet_size = min(bet_size, state.my_chips)
    return ('raise', bet_size)


# ── Strategy 2: LOOSE-AGGRESSIVE (LAG) ───────
def strategy_lag(state):
    """
    Play many hands. Apply constant pressure. Bluff frequently.
    Three-bet light, float the flop, fire multiple barrels.
    """
    strength = hand_strength(state.my_hole, state.community)
    to_call  = state.to_call

    # fold only true garbage
    threshold = 0.28 if state.street == 'preflop' else 0.25

    # random bluff ~20% of the time even when weak
    bluffing = random.random() < 0.20

    if strength < threshold and not bluffing:
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

    # aggression factor: bet 60-120% of pot
    aggression = random.uniform(0.6, 1.2)
    bet_size = int(state.pot * aggression)
    if state.street == 'preflop':
        bet_size = max(BIG_BLIND * 3, int(state.current_bet * 2.5))

    if to_call > bet_size:
        # re-raise if our intended bet is smaller than what we owe
        bet_size = to_call + int(state.pot * 0.5)
    bet_size = min(bet_size, state.my_chips)
    if bet_size <= 0:
        return ('check', 0)
    return ('raise', bet_size)


# ── Strategy 3: GTO-INSPIRED BALANCED ────────
def strategy_gto(state):
    """
    Mix raising, calling, and folding at frequencies that approximate
    a balanced unexploitable strategy. Uses hand-strength buckets +
    randomised actions to remain unpredictable.
    """
    strength = hand_strength(state.my_hole, state.community)
    to_call  = state.to_call
    r        = random.random()

    # bucket the hand
    if strength >= 0.80:   bucket = 'nut'
    elif strength >= 0.60: bucket = 'strong'
    elif strength >= 0.42: bucket = 'medium'
    elif strength >= 0.30: bucket = 'weak'
    else:                  bucket = 'air'

    bet_unit = max(BIG_BLIND, int(state.pot * 0.67))

    if bucket == 'nut':
        # always raise, size = pot
        raise_by = min(state.pot + to_call, state.my_chips)
        return ('raise', max(raise_by, to_call + 1))

    if bucket == 'strong':
        if r < 0.70:
            raise_by = min(bet_unit, state.my_chips)
            return ('raise', max(raise_by, to_call + 1) if raise_by > to_call else to_call)
        return ('call', min(to_call, state.my_chips))

    if bucket == 'medium':
        if to_call == 0:
            if r < 0.40:
                return ('raise', min(int(state.pot * 0.4), state.my_chips))
            return ('check', 0)
        if to_call <= state.pot * 0.35:
            return ('call', to_call)
        if r < 0.15:
            return ('raise', min(state.pot, state.my_chips))
        return ('fold', 0)

    if bucket == 'weak':
        if to_call == 0:
            if r < 0.20:   # mixed bluff bet
                return ('raise', min(int(state.pot * 0.33), state.my_chips))
            return ('check', 0)
        if r < 0.10 and to_call <= BIG_BLIND * 2:
            return ('call', to_call)
        return ('fold', 0)

    # air
    if to_call == 0 and r < 0.12:
        return ('raise', min(int(state.pot * 0.5), state.my_chips))
    if to_call == 0:
        return ('check', 0)
    return ('fold', 0)


# ── Strategy 4: EXPLOITATIVE ADAPTIVE ────────
def strategy_exploitative(state):
    """
    Tracks implied stack-to-pot ratios and opponent stack sizes.
    Plays exploitatively: jam when short-stacked, pot-control when deep.
    Adjusts aggression based on position and number of active opponents.
    """
    strength = hand_strength(state.my_hole, state.community)
    to_call  = state.to_call
    spr      = state.my_chips / max(state.pot, 1)   # stack-to-pot ratio

    # short stack: push-fold territory
    if state.my_chips <= BIG_BLIND * 10:
        if strength >= 0.40:
            return ('raise', state.my_chips)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

    # low SPR → big hand required
    if spr < 3:
        threshold = 0.62
    elif spr < 8:
        threshold = 0.50
    else:
        threshold = 0.40

    positional_bonus = 0.04 * (state.position / max(state.num_active, 1))
    eff_strength     = strength + positional_bonus

    if eff_strength < threshold:
        if to_call == 0:
            return ('check', 0)
        if to_call <= BIG_BLIND:
            return ('call', to_call)
        return ('fold', 0)

    # value bet sizing by SPR
    if spr < 3:
        bet_frac = 1.0
    elif spr < 6:
        bet_frac = 0.75
    else:
        bet_frac = 0.55

    bet_size = int(state.pot * bet_frac)
    bet_size = max(bet_size, to_call + BIG_BLIND)
    bet_size = min(bet_size, state.my_chips)
    return ('raise', bet_size)


# ── Strategy 5: PROBABILISTIC RISK-AVERSE ────
def strategy_risk_averse(state):
    """
    Kelly-Criterion inspired bet sizing. Only bet when EV is clearly
    positive. Keeps a large chip reserve; avoids coin-flips.
    Prefers calling to raising unless hand is a big favourite.
    """
    strength = hand_strength(state.my_hole, state.community)
    to_call  = state.to_call

    # Kelly fraction: f = (b*p - q) / b where b = pot odds in decimal
    b        = state.pot / max(to_call, 1) if to_call > 0 else 99
    p        = strength
    q        = 1 - p
    kelly    = (b * p - q) / max(b, 0.01) if b > 0 else p - 0.5

    # Never commit more than 25% of stack unless kelly is very high
    max_commit = int(state.my_chips * min(0.25, max(0.0, kelly)))

    if kelly <= 0:
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)

    if kelly < 0.15:
        if to_call == 0:
            return ('check', 0)
        if to_call <= max_commit:
            return ('call', to_call)
        return ('fold', 0)

    if kelly < 0.40:
        if to_call == 0:
            bet = min(int(state.pot * 0.4), max_commit)
            if bet > 0:
                return ('raise', bet)
            return ('check', 0)
        if to_call <= max_commit:
            return ('call', to_call)
        return ('fold', 0)

    # strong kelly → raise for value
    bet = min(int(state.pot * 0.8), state.my_chips)
    bet = max(bet, to_call)
    return ('raise', min(bet, state.my_chips))


STRATEGIES = [
    strategy_allin,        # Player 1 (index 0)
    strategy_tag,          # Player 2
    strategy_lag,          # Player 3
    strategy_gto,          # Player 4
    strategy_exploitative, # Player 5
    strategy_risk_averse,  # Player 6
]

STRATEGY_NAMES = [
    "ALL-IN Bot",
    "Tight-Aggressive (TAG)",
    "Loose-Aggressive (LAG)",
    "GTO Balanced",
    "Exploitative Adaptive",
    "Probabilistic Risk-Averse",
]

# ─────────────────────────────────────────────
# BETTING ROUND ENGINE
# ─────────────────────────────────────────────

def betting_round(players, community, pot, street, dealer_idx):
    """Run one street of betting. Returns updated pot."""
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) <= 1:
        return pot

    # reset per-round bets for this street
    for p in players:
        p.bet = 0

    current_bet = 0
    if street == 'preflop':
        # post blinds
        live = [p for p in players if not p.folded]
        sb_idx = (dealer_idx + 1) % len(live)
        bb_idx = (dealer_idx + 2) % len(live)
        sb_p   = live[sb_idx % len(live)]
        bb_p   = live[bb_idx % len(live)]
        sb_amt = min(SMALL_BLIND, sb_p.chips)
        bb_amt = min(BIG_BLIND,   bb_p.chips)
        sb_p.chips -= sb_amt; sb_p.bet = sb_amt; pot += sb_amt
        bb_p.chips -= bb_amt; bb_p.bet = bb_amt; pot += bb_amt
        if bb_p.chips == 0: bb_p.all_in = True
        if sb_p.chips == 0: sb_p.all_in = True
        current_bet = bb_amt
        # action starts left of BB
        start_idx = (bb_idx + 1) % len(live)
        order = live[start_idx:] + live[:start_idx]
    else:
        live  = [p for p in players if not p.folded]
        start = (dealer_idx + 1) % len(live)
        order = live[start:] + live[:start]

    # Track last raiser to know when action is closed
    last_aggressor = None
    acted = set()

    queue = list(order)
    i = 0
    while i < len(queue):
        p = queue[i]
        i += 1

        if p.folded or p.all_in:
            continue

        # action is closed if everyone has acted and no new raise
        remaining = [x for x in queue[i:] if not x.folded and not x.all_in]
        if not remaining and p in acted and last_aggressor != p:
            # everyone called / checked
            pass

        to_call = max(0, current_bet - p.bet)
        num_active_now = sum(1 for x in players if not x.folded and not x.all_in)
        pos = queue.index(p) if p in queue else 0

        state = GameState(
            player       = p,
            community    = community,
            pot          = pot,
            current_bet  = current_bet,
            players_info = [(x.chips, x.folded, x.all_in) for x in players],
            street       = street,
            position     = pos,
            num_active   = num_active_now,
        )

        action, amount = p.strategy(state)

        if action == 'fold':
            p.folded = True

        elif action == 'check':
            if to_call > 0:
                # can't check; treat as call
                call_amt = min(to_call, p.chips)
                pot += call_amt
                p.bet   += call_amt
                p.chips -= call_amt
                if p.chips == 0:
                    p.all_in = True

        elif action == 'call':
            call_amt = min(to_call, p.chips)
            pot += call_amt
            p.bet   += call_amt
            p.chips -= call_amt
            if p.chips == 0:
                p.all_in = True

        elif action == 'raise':
            # amount = additional chips on top of what p already put in
            amount   = max(1, int(amount))
            total_in = p.bet + amount          # total committed after raise
            if total_in < current_bet:
                # not enough to raise – treat as call
                call_amt = min(to_call, p.chips)
                pot += call_amt
                p.bet   += call_amt
                p.chips -= call_amt
            else:
                put_in  = min(amount, p.chips)
                pot    += put_in
                p.bet  += put_in
                p.chips -= put_in
                if p.bet > current_bet:
                    current_bet    = p.bet
                    last_aggressor = p
                    # re-open action for everyone else who hasn't acted since raise
                    for reopen in players:
                        if reopen is not p and not reopen.folded and not reopen.all_in:
                            if reopen not in queue[i:]:
                                queue.append(reopen)
            if p.chips == 0:
                p.all_in = True

        acted.add(p)

    return pot


# ─────────────────────────────────────────────
# SHOWDOWN
# ─────────────────────────────────────────────

def showdown(players, community, pot):
    """Award pot to winner(s). Returns list of winner pids."""
    eligible = [p for p in players if not p.folded]
    if not eligible:
        return []
    if len(eligible) == 1:
        eligible[0].chips += pot
        return [eligible[0].pid]

    scores = [(hand_rank(p.hole + community), p) for p in eligible]
    best   = max(s[0] for s in scores)
    winners = [p for score, p in scores if score == best]
    share   = pot // len(winners)
    remainder = pot - share * len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += remainder
    return [w.pid for w in winners]


# ─────────────────────────────────────────────
# ONE FULL HAND
# ─────────────────────────────────────────────

def play_hand(players, dealer_idx):
    """Play a single hand. Modifies player chip counts in place."""
    # reset
    for p in players:
        p.reset_for_hand()

    deck = make_deck()
    random.shuffle(deck)

    # deal hole cards
    for p in players:
        if p.chips > 0:
            p.hole = [deck.pop(), deck.pop()]
        else:
            p.folded = True

    community = []
    pot = 0

    # streets
    for street in ['preflop', 'flop', 'turn', 'river']:
        if street == 'flop':
            community += [deck.pop(), deck.pop(), deck.pop()]
        elif street in ('turn', 'river'):
            community.append(deck.pop())

        active = [p for p in players if not p.folded]
        if len(active) <= 1:
            break

        pot = betting_round(players, community, pot, street, dealer_idx)

        active = [p for p in players if not p.folded]
        if len(active) <= 1:
            break

    # award pot
    active = [p for p in players if not p.folded]
    if len(active) == 1:
        active[0].chips += pot
        return active[0].pid

    return showdown(players, community, pot)


# ─────────────────────────────────────────────
# ONE FULL TOURNAMENT  (hands until 1 player left)
# ─────────────────────────────────────────────

def run_tournament(verbose=False):
    players = [Player(i+1, STARTING_CHIPS, STRATEGIES[i]) for i in range(6)]
    dealer  = 0
    hand_no = 0

    while sum(1 for p in players if p.chips > 0) > 1:
        hand_no += 1
        if hand_no > 5000:   # safety valve
            break

        # remove busted players from rotation
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break

        d_idx  = dealer % len(alive)
        play_hand(alive, d_idx)
        dealer += 1

        if verbose and hand_no % 50 == 0:
            status = ', '.join(f"P{p.pid}:${p.chips}" for p in players)
            print(f"  Hand {hand_no}: {status}")

    survivors = [p for p in players if p.chips > 0]
    if survivors:
        return survivors[0].pid
    # everyone busted simultaneously (rare) – give to chip leader
    return max(players, key=lambda p: p.chips).pid


# ─────────────────────────────────────────────
# 100 SIMULATIONS + HISTOGRAM
# ─────────────────────────────────────────────

def run_simulations(n=100):
    print(f"\n{'='*60}")
    print(f"  TEXAS HOLD'EM — {n} TOURNAMENT SIMULATIONS")
    print(f"  Starting chips per player: ${STARTING_CHIPS}")
    print(f"  Blinds: ${SMALL_BLIND}/${BIG_BLIND}")
    print(f"{'='*60}\n")

    print("Player strategies:")
    for i, name in enumerate(STRATEGY_NAMES):
        tag = "  ← THE SIMPLE ALL-IN BOT" if i == 0 else ""
        print(f"  Player {i+1}: {name}{tag}")
    print()

    wins = Counter()
    for sim in range(1, n+1):
        random.seed(sim * 31337)    # reproducible but varied
        winner = run_tournament()
        wins[winner] += 1
        if sim % 10 == 0:
            print(f"  Simulation {sim:3d}/{n} complete...", flush=True)

    print(f"\n{'='*60}")
    print(f"  RESULTS — Who's the Rounder?")
    print(f"  (winner winner chicken dinner)")
    print(f"{'='*60}\n")

    # ── ASCII histogram ──────────────────────────────────
    bar_max  = 40
    most     = max(wins.values()) if wins else 1

    print(f"  {'Player':<28} {'Wins':>5}  {'%':>6}  Histogram")
    print(f"  {'-'*28} {'-'*5}  {'-'*6}  {'-'*bar_max}")

    # sort by wins descending
    order = sorted(range(1, 7), key=lambda pid: wins.get(pid, 0), reverse=True)
    for pid in order:
        w    = wins.get(pid, 0)
        pct  = w / n * 100
        bar  = '█' * int(bar_max * w / most)
        name = STRATEGY_NAMES[pid - 1]
        marker = " ◀ ALL-IN BOT" if pid == 1 else ""
        print(f"  P{pid} {name:<26}{marker}")
        print(f"  {'':>4} {w:>5}  {pct:>5.1f}%  {bar}")
        print()

    champ_pid = max(wins, key=wins.get)
    print(f"{'='*60}")
    print(f"  CHAMPION: Player {champ_pid} — {STRATEGY_NAMES[champ_pid-1]}")
    print(f"  Wins: {wins[champ_pid]}/{n} ({wins[champ_pid]/n*100:.1f}%)")
    if champ_pid == 1:
        print(f"\n  *** THE ALL-IN BOT WINS! CHAOS REIGNS! ***")
        print(f"  sufflair GPT has been absolutely HUMILIATED. 💀")
    else:
        print(f"\n  The All-In Bot (P1) won {wins.get(1,0)} times ({wins.get(1,0)/n*100:.1f}%)")
        print(f"  Calculated strategy prevails over reckless all-ins.")
    print(f"{'='*60}\n")

    return wins


if __name__ == '__main__':
    verbose = '--verbose' in sys.argv
    run_simulations(100)
