"""
Texas Hold'em 6-Player Simulation — 100 games, histogram of winners.
Player 1: The Degen — all-in every single turn.
Players 2-6: Five distinct elaborate strategies.

Fast hand-strength estimation via lookup + lightweight equity heuristics.
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────────────────────────────────────
# CARD ENGINE
# ─────────────────────────────────────────────────────────────────────────────

RANKS  = '23456789TJQKA'
SUITS  = 'cdhs'
RV     = {r: i for i, r in enumerate(RANKS, 2)}   # rank -> int value

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def score_five(cards):
    """Score 5 cards. Returns comparable tuple (category, tiebreakers)."""
    rv = sorted([RV[c[0]] for c in cards], reverse=True)
    su = [c[1] for c in cards]
    flush = len(set(su)) == 1
    straight = (rv == list(range(rv[0], rv[0]-5, -1)) or
                rv == [14, 5, 4, 3, 2])
    if rv == [14, 5, 4, 3, 2]:
        rv = [5, 4, 3, 2, 1]
    cnt = Counter(rv)
    groups = sorted(cnt.keys(), key=lambda r: (cnt[r], r), reverse=True)
    vals = sorted(cnt.values(), reverse=True)
    if straight and flush: return (8, rv)
    if vals[0] == 4:       return (7, groups)
    if vals[:2] == [3,2]:  return (6, groups)
    if flush:              return (5, rv)
    if straight:           return (4, rv)
    if vals[0] == 3:       return (3, groups)
    if vals[:2] == [2,2]:  return (2, groups)
    if vals[0] == 2:       return (1, groups)
    return (0, rv)

def best_hand(cards):
    """Best 5-card score from up to 7 cards."""
    return max(score_five(c) for c in combinations(cards, 5))


# ─────────────────────────────────────────────────────────────────────────────
# FAST HAND STRENGTH (heuristic — no MC loop)
# ─────────────────────────────────────────────────────────────────────────────

def preflop_strength(hole):
    """
    Returns [0,1] estimate of preflop hand strength.
    Based on Sklansky-Chubukov-style tiers.
    """
    r1, r2 = sorted([RV[hole[0][0]], RV[hole[1][0]]], reverse=True)
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2

    # Pairs
    if pair:
        return 0.50 + (r1 - 2) / 12 * 0.40   # 2-2 ~ 0.50, AA ~ 0.90

    gap = r1 - r2
    base = (r1 + r2) / (14 + 13)              # raw high-card value 0..1
    suited_bonus = 0.04 if suited else 0
    gap_penalty  = min(gap, 5) * 0.03

    raw = base - gap_penalty + suited_bonus
    return max(0.05, min(0.75, raw))


def postflop_strength(hole, community):
    """
    Returns approximate equity [0,1] for our hand on the current board.
    Uses actual hand category and some board-texture priors.
    """
    if not community:
        return preflop_strength(hole)

    all_cards = hole + community
    sc = best_hand(all_cards)
    cat = sc[0]   # 0=high card .. 8=straight flush

    # Base equity by hand category (heads-up approximation, 6-player scaled below)
    category_equity = [0.15, 0.35, 0.55, 0.65, 0.75, 0.80, 0.88, 0.94, 0.99]
    equity = category_equity[cat]

    # Scale down for more opponents (still an approximation)
    return equity


def strength_vs_opponents(hole, community, n_opp):
    """Adjust raw equity for number of opponents."""
    eq = postflop_strength(hole, community)
    # Each extra opponent roughly multiplies the loss probability
    return eq ** max(1, n_opp * 0.7)


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

BIG_BLIND = 10

class Strategy:
    name = "Base"
    def decide(self, player, gs):
        raise NotImplementedError


# ── Strategy 0: The Degen ─────────────────────────────────────────────────────

class TheDegenStrategy(Strategy):
    """if my_turn then bet = ALL IN fi"""
    name = "The Degen (ALL-IN)"

    def decide(self, player, gs):
        return ('raise', player['chips'])


# ── Strategy 1: Tight-Aggressive (TAG) ───────────────────────────────────────

class TightAggressiveStrategy(Strategy):
    """
    Plays a narrow range of strong hands. Raises big with premiums,
    folds garbage, bets big for value on good boards, protects equity.
    """
    name = "TAG (Tight-Aggressive)"

    PREMIUM_PREFLOP = 0.62   # threshold to enter pot
    RAISE_THRESHOLD = 0.70

    def decide(self, player, gs):
        hole      = player['hole']
        community = gs['community']
        to_call   = gs['to_call']
        pot       = gs['pot']
        n_opp     = gs['active_opponents']
        bb        = gs['big_blind']

        strength = strength_vs_opponents(hole, community, n_opp)

        if not community:   # preflop
            if strength >= self.RAISE_THRESHOLD:
                return ('raise', min(4 * bb, player['chips']))
            if strength >= self.PREMIUM_PREFLOP and to_call <= 2 * bb:
                return ('call', to_call)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        # Postflop
        pot_odds_needed = to_call / (to_call + pot + 1)
        if strength >= 0.65:
            bet = min(int(pot * 0.75), player['chips'])
            return ('raise', max(bet, to_call))
        if strength > pot_odds_needed + 0.08 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


# ── Strategy 2: Calling Station (Loose-Passive) ───────────────────────────────

class CallingStationStrategy(Strategy):
    """
    Sees every cheap flop, chases draws hoping to hit, never raises.
    Classic passive fish that leaks chips but occasionally sucks out.
    """
    name = "Calling Station (Loose-Passive)"

    def decide(self, player, gs):
        to_call = gs['to_call']
        pot     = gs['pot']
        hole    = player['hole']
        community = gs['community']
        n_opp   = gs['active_opponents']

        if not community:
            # Call any open ≤ 20% of stack, otherwise fold
            if to_call <= player['chips'] * 0.20:
                return ('call', to_call)
            return ('fold', 0)

        strength = strength_vs_opponents(hole, community, n_opp)
        # Call if we have any equity at all or it's free
        if strength >= 0.25 or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


# ── Strategy 3: Position Pro ──────────────────────────────────────────────────

class PositionProStrategy(Strategy):
    """
    Exploits table position aggressively.
    Late position (BTN/CO): steal blinds, c-bet wide.
    Early position: plays tight, lets position do the work.
    """
    name = "Position Pro"

    def decide(self, player, gs):
        hole      = player['hole']
        community = gs['community']
        to_call   = gs['to_call']
        pot       = gs['pot']
        n_opp     = gs['active_opponents']
        bb        = gs['big_blind']
        position  = gs.get('position', 3)   # 0 = button (best)

        is_late = position <= 1
        strength = strength_vs_opponents(hole, community, n_opp)

        if not community:
            if is_late:
                # Steal and 3-bet wide from position
                if strength >= 0.40 or to_call == 0:
                    raise_to = min(int(2.5 * bb), player['chips'])
                    return ('raise', max(raise_to, to_call))
                if to_call <= 2 * bb:
                    return ('call', to_call)
                return ('fold', 0)
            else:
                # Early position: very tight
                if strength >= 0.70:
                    return ('raise', min(3 * bb, player['chips']))
                if to_call == 0:
                    return ('call', 0)
                return ('fold', 0)

        # Postflop
        if is_late:
            # C-bet on flop regardless of strength
            if len(community) == 3 and to_call == 0 and random.random() < 0.65:
                cbet = min(int(pot * 0.55), player['chips'])
                return ('raise', cbet)
            if strength >= 0.55:
                bet = min(int(pot * 0.65), player['chips'])
                return ('raise', max(bet, to_call))
            if strength >= 0.35 or to_call == 0:
                return ('call', to_call)
            return ('fold', 0)
        else:
            if strength >= 0.70:
                bet = min(int(pot * 0.60), player['chips'])
                return ('raise', max(bet, to_call))
            if strength >= 0.50 or to_call == 0:
                return ('call', to_call)
            return ('fold', 0)


# ── Strategy 4: GTO Approximator ─────────────────────────────────────────────

class GtoStrategy(Strategy):
    """
    Balanced mixed-strategy approach: geometric sizing, polarized 3-bets,
    random bluffs to balance value range, frequency-based calls.
    """
    name = "GTO Approximator"

    def decide(self, player, gs):
        hole      = player['hole']
        community = gs['community']
        to_call   = gs['to_call']
        pot       = gs['pot']
        n_opp     = gs['active_opponents']
        bb        = gs['big_blind']

        strength = strength_vs_opponents(hole, community, n_opp)

        if not community:
            if strength >= 0.72:
                # Sometimes flat-call to balance (15% limp-reraise trap)
                if random.random() < 0.15:
                    return ('call', to_call)
                return ('raise', min(3 * bb, player['chips']))
            if strength >= 0.52:
                if to_call <= 2 * bb:
                    act = 'raise' if random.random() < 0.40 else 'call'
                    return (act, min(2 * bb, player['chips']) if act == 'raise' else to_call)
                return ('fold', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        # Geometric pot sizing: 33% flop, 50% turn, 75% river
        geo = [0.33, 0.50, 0.75][min(len(community) - 3, 2)]

        if strength >= 0.75:
            bet = min(int(pot * geo), player['chips'])
            return ('raise', max(bet, to_call))
        if strength >= 0.50:
            return ('call', to_call) if to_call > 0 else ('raise', min(int(pot * geo * 0.5), player['chips']))

        # Balanced bluff frequency: bluff ~25% of air on river
        if strength < 0.25 and to_call == 0 and random.random() < 0.25:
            bluff = min(int(pot * 0.50), player['chips'])
            return ('raise', bluff)

        pot_odds_needed = to_call / (to_call + pot + 1)
        if strength > pot_odds_needed or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


# ── Strategy 5: The Shark ─────────────────────────────────────────────────────

class SharkStrategy(Strategy):
    """
    Adaptive exploitative play: reads board texture, adjusts bet sizing,
    traps with monster hands, semi-bluffs draws, punishes limp-callers.
    Tracks aggregate opponent aggression to exploit tendencies.
    """
    name = "The Shark (Adaptive)"

    def __init__(self):
        self._aggression = {}    # player_id -> raise count seen

    def _texture(self, community):
        if len(community) < 3: return 'dry'
        suits = [c[1] for c in community]
        rvs   = sorted([RV[c[0]] for c in community])
        flush_draw   = max(Counter(suits).values()) >= 3
        str_draw     = rvs[-1] - rvs[0] <= 4
        if flush_draw and str_draw: return 'very_wet'
        if flush_draw or str_draw:  return 'wet'
        return 'dry'

    def notify_action(self, pid, action):
        if action == 'raise':
            self._aggression[pid] = self._aggression.get(pid, 0) + 1

    def _table_tight(self, gs):
        return gs.get('limpers', 0) <= 1

    def decide(self, player, gs):
        hole      = player['hole']
        community = gs['community']
        to_call   = gs['to_call']
        pot       = gs['pot']
        n_opp     = gs['active_opponents']
        bb        = gs['big_blind']
        tex       = self._texture(community)

        strength = strength_vs_opponents(hole, community, n_opp)

        # Texture penalty
        tex_penalty = {'dry': 0.0, 'wet': 0.05, 'very_wet': 0.10}[tex]
        adj = strength - tex_penalty

        if not community:
            # Trap with monsters on occasion (slow-play AA/KK)
            if adj >= 0.80 and random.random() < 0.20:
                return ('call', to_call)   # limp-trap
            if adj >= 0.62:
                raise_sz = min(int(3.5 * bb), player['chips'])
                return ('raise', max(raise_sz, to_call))
            if adj >= 0.45 and to_call <= bb:
                return ('call', to_call)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        # Postflop
        if adj >= 0.72:
            # Overbet on very wet boards to deny equity
            mult = 1.25 if tex == 'very_wet' else 0.75
            bet  = min(int(pot * mult), player['chips'])
            return ('raise', max(bet, to_call))

        if adj >= 0.55:
            if to_call == 0:
                bet = min(int(pot * 0.55), player['chips'])
                return ('raise', bet)
            return ('call', to_call)

        # Semi-bluff draws on wet boards
        if tex in ('wet', 'very_wet') and adj >= 0.35 and to_call == 0:
            if random.random() < 0.40:
                semi = min(int(pot * 0.45), player['chips'])
                return ('raise', semi)
            return ('call', 0)

        pot_odds_needed = to_call / (to_call + pot + 1)
        if adj > pot_odds_needed or to_call == 0:
            return ('call', to_call)
        return ('fold', 0)


# ─────────────────────────────────────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────────────────────────────────────

ALL_STRATEGIES = [
    TheDegenStrategy(),
    TightAggressiveStrategy(),
    CallingStationStrategy(),
    PositionProStrategy(),
    GtoStrategy(),
    SharkStrategy(),
]

STARTING_CHIPS = 1000
SB = 5
BB = BIG_BLIND = 10


def run_game():
    players = [
        {'id': i+1, 'chips': STARTING_CHIPS, 'strategy': ALL_STRATEGIES[i],
         'hole': [], 'active': True, 'bet': 0, 'allin': False}
        for i in range(6)
    ]
    dealer = 0
    hand_num = 0

    while True:
        alive = [p for p in players if p['chips'] > 0]
        if len(alive) == 1:
            return alive[0]['id']
        if hand_num > 3000:
            return max(alive, key=lambda p: p['chips'])['id']
        hand_num += 1
        _play_hand(players, dealer)
        dealer = (dealer + 1) % 6


def _play_hand(players, dealer_idx):
    active = [p for p in players if p['chips'] > 0]
    if len(active) < 2:
        return

    for p in players:
        p['hole']   = []
        p['bet']    = 0
        p['allin']  = False
        p['active'] = p['chips'] > 0

    n = len(active)
    # SB / BB seat indices within active list
    sb_pos = (dealer_idx + 1) % n
    bb_pos = (dealer_idx + 2) % n

    def post(pos, amount):
        p = active[pos]
        amt = min(amount, p['chips'])
        p['chips'] -= amt
        p['bet']   += amt
        if p['chips'] == 0:
            p['allin'] = True
        return amt

    pot  = post(sb_pos, SB) + post(bb_pos, BB)
    cur_bet = BB

    deck = make_deck()
    random.shuffle(deck)
    for p in active:
        p['hole'] = [deck.pop(), deck.pop()]

    community = []

    for street in range(4):
        if   street == 1: community += [deck.pop(), deck.pop(), deck.pop()]
        elif street == 2: community.append(deck.pop())
        elif street == 3: community.append(deck.pop())

        can_act = [p for p in players if p['active'] and not p['allin']]
        if len(can_act) <= 1:
            continue

        start = bb_pos if street == 0 else (dealer_idx + 1) % n
        pot, cur_bet = _bet_round(players, active, pot, cur_bet if street == 0 else 0,
                                  start, community, dealer_idx, n)

    # Showdown
    contenders = [p for p in players if p['active']]
    if not contenders:
        return
    if len(contenders) == 1:
        contenders[0]['chips'] += pot
        return

    scored = sorted(contenders, key=lambda p: best_hand(p['hole'] + community), reverse=True)
    scored[0]['chips'] += pot


def _bet_round(players, active, pot, max_bet, start_pos, community, dealer_idx, n_active):
    acted  = set()
    order  = [(start_pos + i) % len(players) for i in range(len(players))]
    i      = 0
    safety = 0

    while safety < len(players) * 4:
        safety += 1
        p = players[order[i % len(order)]]
        i += 1

        if not p['active'] or p['allin']:
            continue

        to_call = max_bet - p['bet']
        n_opp   = sum(1 for x in players if x['active'] and x['id'] != p['id'])
        gs = {
            'community':        community,
            'to_call':          to_call,
            'pot':              pot,
            'active_opponents': max(n_opp, 1),
            'big_blind':        BB,
            'position':         (order.index(p['id']-1)) % max(n_active, 1),
            'n_active':         sum(1 for x in players if x['active']),
            'limpers':          sum(1 for x in players if x['active'] and x['bet'] == BB and x['id'] != p['id']),
        }

        action, amount = p['strategy'].decide(p, gs)

        if action == 'fold':
            p['active'] = False
            acted.add(p['id'])

        elif action == 'call':
            pay = min(to_call, p['chips'])
            p['chips'] -= pay
            p['bet']   += pay
            pot        += pay
            if p['chips'] == 0: p['allin'] = True
            acted.add(p['id'])

        elif action == 'raise':
            target  = p['bet'] + min(amount, p['chips'])
            new_max = max(target, max_bet)
            pay     = target - p['bet']
            pay     = min(pay, p['chips'])
            p['chips'] -= pay
            p['bet']   += pay
            pot        += pay
            if p['chips'] == 0: p['allin'] = True
            if new_max > max_bet:
                max_bet = new_max
                acted   = {p['id']}   # force others to respond
            acted.add(p['id'])

        # Terminal: all remaining players have matched and acted
        remaining = [x for x in players if x['active'] and not x['allin']]
        if not remaining:
            break
        if all(x['bet'] == max_bet for x in remaining) and all(x['id'] in acted for x in remaining):
            break

    return pot, max_bet


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_sims(n=100):
    wins = Counter()
    for k in range(1, n+1):
        w = run_game()
        wins[w] += 1
        if k % 20 == 0:
            print(f"  {k}/{n} games done...", flush=True)
    return wins


# ─────────────────────────────────────────────────────────────────────────────
# HISTOGRAM RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def histogram(wins, n_sims):
    print()
    print("=" * 72)
    print("   WINNER WINNER CHICKEN DINNER  — 100-GAME TX HOLD'EM SIMULATION")
    print("=" * 72)
    print()

    names    = {i+1: ALL_STRATEGIES[i].name for i in range(6)}
    most     = max(wins.values(), default=1)
    BAR      = 40

    for pid in range(1, 7):
        cnt  = wins.get(pid, 0)
        bar  = '█' * int(cnt / most * BAR)
        pct  = cnt / n_sims * 100
        tag  = " ◄ ALL-IN BOT" if pid == 1 else ""
        lbl  = f"P{pid}  {names[pid]}{tag}"
        print(f"  {lbl:<44}  {bar:<{BAR}}  {cnt:>3}  ({pct:5.1f}%)")

    print()
    print("─" * 72)
    champ = wins.most_common(1)[0]
    print(f"  CHAMPION: Player {champ[0]} — {names[champ[0]]}  ({champ[1]} wins)")
    last  = wins.most_common()[-1]
    print(f"  DUNCE:    Player {last[0]} — {names[last[0]]}  ({last[1]} wins)")
    print("─" * 72)
    print()

    # Roast
    d = wins.get(1, 0)
    print("  [ ROAST CORNER ]")
    if d >= 30:
        print(f"  The Degen won {d}/100 games. Variance said 'hold my beer'.")
        print("  Your elaborate algos got clapped by a braindead GOTO statement.")
    elif d >= 20:
        print(f"  {d} wins for the all-in bot? Chaos is a ladder, apparently.")
    elif d >= 10:
        print(f"  {d} wins for the Degen. Blind squirrel, meet nut.")
    else:
        print(f"  Only {d} wins for the all-in bot. Justice. Sweet, sweet justice.")
        print("  Strategy beats degeneracy, as the poker gods intended.")

    s_wins = wins.get(6, 0)
    g_wins = wins.get(5, 0)
    print()
    print(f"  Shark vs GTO: {s_wins} vs {g_wins} —", end=" ")
    if s_wins > g_wins + 5:   print("reads beat solvers today.")
    elif g_wins > s_wins + 5: print("solver wins. Board is solved.")
    else:                     print("too close to call. Rematch needed.")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     TEXAS HOLD'EM SIMULATION  —  Humiliating GPT        ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    for i, s in enumerate(ALL_STRATEGIES):
        mark = "  ← if my_turn then bet=ALL_IN fi" if i == 0 else ""
        print(f"  P{i+1}: {s.name}{mark}")
    print()
    print(f"  6 players, {STARTING_CHIPS} chips each, blinds {SB}/{BB}")
    print("  Running 100 full games...\n")

    random.seed(2026)
    results = run_sims(100)
    histogram(results, 100)
