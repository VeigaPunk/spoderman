"""
Texas Hold'em Poker Tournament Simulator
100 tournaments: Player 1 (YOLO All-In) vs Players 2-6 (Elaborate Strategies)
"""

import random
from collections import Counter
from itertools import combinations
from enum import IntEnum

# ─── Card primitives ──────────────────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
        self.val = RANK_VAL[rank]

    def __repr__(self):
        return f"{self.rank}{self.suit}"

    def __lt__(self, other):
        return self.val < other.val

    def __eq__(self, other):
        return self.val == other.val and self.suit == other.suit

    def __hash__(self):
        return hash((self.rank, self.suit))


def make_deck():
    return [Card(r, s) for r in RANKS for s in SUITS]


# ─── Hand evaluation ──────────────────────────────────────────────────────────

class HandRank(IntEnum):
    HIGH_CARD      = 1
    ONE_PAIR       = 2
    TWO_PAIR       = 3
    THREE_OF_A_KIND = 4
    STRAIGHT       = 5
    FLUSH          = 6
    FULL_HOUSE     = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9
    ROYAL_FLUSH    = 10


def best_hand(cards):
    """Return (HandRank, [tiebreak values]) for the best 5-card hand from cards."""
    best = None
    for combo in combinations(cards, 5):
        score = evaluate_5(list(combo))
        if best is None or score > best:
            best = score
    return best


def evaluate_5(cards):
    vals = sorted([c.val for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1
    is_straight = (vals == list(range(vals[0], vals[0]-5, -1)) or
                   vals == [14, 5, 4, 3, 2])  # wheel
    if is_straight and vals == [14, 5, 4, 3, 2]:
        vals = [5, 4, 3, 2, 1]

    counts = Counter(vals)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda k: (counts[k], k), reverse=True)

    if is_straight and is_flush:
        if vals[0] == 14:
            return (HandRank.ROYAL_FLUSH, vals)
        return (HandRank.STRAIGHT_FLUSH, vals)
    if freq[0] == 4:
        return (HandRank.FOUR_OF_A_KIND, groups)
    if freq[:2] == [3, 2]:
        return (HandRank.FULL_HOUSE, groups)
    if is_flush:
        return (HandRank.FLUSH, vals)
    if is_straight:
        return (HandRank.STRAIGHT, vals)
    if freq[0] == 3:
        return (HandRank.THREE_OF_A_KIND, groups)
    if freq[:2] == [2, 2]:
        return (HandRank.TWO_PAIR, groups)
    if freq[0] == 2:
        return (HandRank.ONE_PAIR, groups)
    return (HandRank.HIGH_CARD, vals)


# ─── Monte Carlo equity estimator ─────────────────────────────────────────────

def estimate_equity(hole, community, num_opponents, iterations=200):
    """Rough win-rate estimate via Monte Carlo."""
    wins = 0
    deck_remaining = [c for c in make_deck()
                      if c not in hole and c not in community]
    needed = 5 - len(community)
    for _ in range(iterations):
        random.shuffle(deck_remaining)
        board = community + deck_remaining[:needed]
        opp_cards = deck_remaining[needed:]
        my_best = best_hand(hole + board)
        win = True
        for i in range(num_opponents):
            opp_hole = opp_cards[i*2: i*2+2]
            if len(opp_hole) < 2:
                break
            opp_best = best_hand(opp_hole + board)
            if opp_best >= my_best:
                win = False
                break
        if win:
            wins += 1
    return wins / iterations


def hand_strength_preflop(hole):
    """Quick preflop strength heuristic [0..1]."""
    a, b = sorted(hole, reverse=True)
    suited = a.suit == b.suit
    gap = a.val - b.val
    score = (a.val + b.val) / 28.0  # normalize max pair AA = 28
    if a.val == b.val:
        score += 0.25
    if suited:
        score += 0.05
    if gap == 1:
        score += 0.05
    return min(score, 1.0)


# ─── Player / Strategy ────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, strategy_fn, chips=1000):
        self.pid = pid
        self.strategy_fn = strategy_fn
        self.chips = chips
        self.hole = []
        self.folded = False
        self.all_in = False
        self.current_bet = 0

    def act(self, game_state):
        return self.strategy_fn(self, game_state)

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.current_bet = 0


# ─── Strategies ───────────────────────────────────────────────────────────────

# ── Strategy 1: GTO-ish Tight-Aggressive ─────────────────────────────────────
def strategy_tight_aggressive(player, gs):
    """
    Pre-flop: tight range, raise premiums.
    Post-flop: equity-driven decisions with pot-odds check.
    Raises 3x pot on strong hands, calls with >35% equity.
    """
    to_call = gs['to_call']
    pot     = gs['pot']
    phase   = gs['phase']
    community = gs['community']
    num_opp   = gs['active_opponents']

    if phase == 'preflop':
        strength = hand_strength_preflop(player.hole)
        if strength > 0.78:                          # premium: raise big
            amount = min(pot * 3 + to_call, player.chips)
            return ('raise', max(amount, to_call * 2 + 1))
        elif strength > 0.60:                        # decent: call
            return ('call', min(to_call, player.chips))
        elif strength > 0.50 and to_call == 0:       # speculative: limp
            return ('call', 0)
        else:
            return ('fold', 0) if to_call > 0 else ('check', 0)

    # post-flop
    equity = estimate_equity(player.hole, community, num_opp, 150)
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

    if equity > 0.65:
        bet = min(int(pot * 0.75), player.chips)
        return ('raise', max(bet, to_call + 1))
    elif equity > 0.40 and equity > pot_odds:
        return ('call', min(to_call, player.chips))
    elif to_call == 0:
        return ('check', 0)
    else:
        return ('fold', 0)


# ── Strategy 2: Pot-Odds Calling Station ─────────────────────────────────────
def strategy_pot_odds_caller(player, gs):
    """
    Calls whenever pot-odds exceed estimated equity.
    Rarely raises — prefers to see cheap showdowns.
    Will bluff-raise once per hand on the river if checked to.
    """
    to_call   = gs['to_call']
    pot       = gs['pot']
    phase     = gs['phase']
    community = gs['community']
    num_opp   = gs['active_opponents']
    street_action = gs.get('street_bets', 0)

    if phase == 'preflop':
        strength = hand_strength_preflop(player.hole)
        if strength > 0.55 or to_call == 0:
            return ('call', min(to_call, player.chips))
        return ('fold', 0)

    equity = estimate_equity(player.hole, community, num_opp, 120)
    pot_odds = to_call / (pot + to_call + 1)

    if equity >= pot_odds * 0.9:
        if equity > 0.70 and to_call == 0 and phase == 'river':
            bet = min(int(pot * 0.5), player.chips)
            return ('raise', bet)
        return ('call', min(to_call, player.chips))
    return ('fold', 0) if to_call > 0 else ('check', 0)


# ── Strategy 3: Aggressive Bluffer (LAG) ─────────────────────────────────────
def strategy_lag_bluffer(player, gs):
    """
    Loose-Aggressive: raises wide preflop, barrels bluffs on scary boards,
    uses position-aware semi-bluffs, and fires triple-barrel on air.
    Randomizes bluff frequency so it's hard to read.
    """
    to_call   = gs['to_call']
    pot       = gs['pot']
    phase     = gs['phase']
    community = gs['community']
    num_opp   = gs['active_opponents']
    position  = gs.get('position', 0)

    if phase == 'preflop':
        strength = hand_strength_preflop(player.hole)
        # play wide in late position, tight in early
        threshold = 0.45 - (position / (num_opp + 1)) * 0.15
        if strength > threshold:
            if strength > 0.65 or random.random() < 0.35:  # bluff-raise freq
                amount = min(pot * 2.5 + to_call, player.chips)
                return ('raise', max(int(amount), to_call * 2 + 1))
            return ('call', min(to_call, player.chips))
        return ('fold', 0) if to_call > 0 else ('check', 0)

    equity = estimate_equity(player.hole, community, num_opp, 120)
    bluff_chance = 0.30 if phase == 'flop' else (0.20 if phase == 'turn' else 0.15)

    if equity > 0.55 or random.random() < bluff_chance:
        bet = min(int(pot * (0.6 + random.random() * 0.4)), player.chips)
        return ('raise', max(bet, to_call + 1))
    elif equity > 0.30 and to_call <= pot * 0.25:
        return ('call', min(to_call, player.chips))
    return ('fold', 0) if to_call > 0 else ('check', 0)


# ── Strategy 4: ICM-Aware Stack Bully ────────────────────────────────────────
def strategy_stack_bully(player, gs):
    """
    Adjusts aggression based on stack sizes relative to opponents.
    Big stack: applies maximum pressure to short stacks.
    Short stack: shoves or folds only (no middling).
    Medium stack: standard GTO range.
    """
    to_call   = gs['to_call']
    pot       = gs['pot']
    phase     = gs['phase']
    community = gs['community']
    num_opp   = gs['active_opponents']
    avg_stack = gs.get('avg_stack', player.chips)

    ratio = player.chips / (avg_stack + 1)
    is_big_stack   = ratio > 1.4
    is_short_stack = ratio < 0.5

    if phase == 'preflop':
        strength = hand_strength_preflop(player.hole)
        if is_short_stack:
            if strength > 0.55:
                return ('raise', player.chips)   # shove
            return ('fold', 0)
        if is_big_stack:
            if strength > 0.40:
                amount = min(pot * 4 + to_call, player.chips)
                return ('raise', max(int(amount), to_call * 3 + 1))
            return ('call', min(to_call, player.chips)) if to_call < player.chips * 0.05 else ('fold', 0)
        # medium stack
        if strength > 0.65:
            return ('raise', min(pot * 2 + to_call, player.chips))
        elif strength > 0.50:
            return ('call', min(to_call, player.chips))
        return ('fold', 0) if to_call > 0 else ('check', 0)

    equity = estimate_equity(player.hole, community, num_opp, 120)

    if is_big_stack and equity > 0.35:
        bet = min(int(pot * 1.2), player.chips)
        return ('raise', max(bet, to_call + 1))
    elif is_short_stack:
        if equity > 0.45:
            return ('raise', player.chips)
        return ('fold', 0) if to_call > 0 else ('check', 0)
    else:
        if equity > 0.50:
            bet = min(int(pot * 0.65), player.chips)
            return ('raise', max(bet, to_call + 1))
        elif equity > 0.35:
            return ('call', min(to_call, player.chips))
        return ('fold', 0) if to_call > 0 else ('check', 0)


# ── Strategy 5: Frequency-Balanced Range Player ───────────────────────────────
def strategy_range_balancer(player, gs):
    """
    Balances betting frequencies across hand strengths to avoid being exploitable.
    Mixes value bets and bluffs at fixed ratios (2:1).
    Uses board texture analysis to adjust c-bet frequency.
    Slowplays monsters occasionally to trap.
    """
    to_call   = gs['to_call']
    pot       = gs['pot']
    phase     = gs['phase']
    community = gs['community']
    num_opp   = gs['active_opponents']

    # board wetness (how many draws present)
    def board_wetness(cards):
        if not cards:
            return 0
        vals  = [c.val for c in cards]
        suits = [c.suit for c in cards]
        suit_counts = Counter(suits)
        flush_draw = max(suit_counts.values()) >= 2
        val_range  = max(vals) - min(vals)
        return (1 if flush_draw else 0) + (1 if val_range <= 4 else 0)

    if phase == 'preflop':
        strength = hand_strength_preflop(player.hole)
        # balanced open-raise range
        if strength > 0.72:
            # occasionally slowplay premiums
            if random.random() < 0.15:
                return ('call', min(to_call, player.chips))
            return ('raise', min(pot * 2.5 + to_call, player.chips))
        elif strength > 0.52:
            return ('call', min(to_call, player.chips)) if to_call < player.chips * 0.10 else ('fold', 0)
        return ('fold', 0) if to_call > 0 else ('check', 0)

    equity   = estimate_equity(player.hole, community, num_opp, 120)
    wetness  = board_wetness(community)
    # higher c-bet frequency on dry boards
    cbet_freq = 0.75 - wetness * 0.15

    if equity > 0.60:
        # value bet but sometimes check to balance
        if random.random() < 0.80:
            bet = min(int(pot * (0.5 + equity * 0.3)), player.chips)
            return ('raise', max(bet, to_call + 1))
        return ('call', min(to_call, player.chips)) if to_call > 0 else ('check', 0)
    elif equity > 0.40:
        if to_call == 0 and random.random() < cbet_freq:
            bet = min(int(pot * 0.5), player.chips)
            return ('raise', max(bet, 1))
        return ('call', min(to_call, player.chips)) if equity * (pot + to_call) > to_call else (('check', 0) if to_call == 0 else ('fold', 0))
    elif to_call == 0 and random.random() < 0.20:   # bluff 20% of air
        bet = min(int(pot * 0.45), player.chips)
        return ('raise', max(bet, 1))
    return ('fold', 0) if to_call > 0 else ('check', 0)


# ── Strategy 0: The YOLO All-In Machine ──────────────────────────────────────
def strategy_yolo_all_in(player, gs):
    """
    If my_turn
    Then bet = All in
    Fi
    """
    return ('raise', player.chips)


STRATEGY_NAMES = {
    0: "YOLO All-In",
    1: "Tight-Aggressive (GTO)",
    2: "Pot-Odds Caller",
    3: "LAG Bluffer",
    4: "Stack Bully",
    5: "Range Balancer",
}

STRATEGIES = [
    strategy_yolo_all_in,        # Player 1
    strategy_tight_aggressive,   # Player 2
    strategy_pot_odds_caller,    # Player 3
    strategy_lag_bluffer,        # Player 4
    strategy_stack_bully,        # Player 5
    strategy_range_balancer,     # Player 6
]


# ─── Game Engine ──────────────────────────────────────────────────────────────

class PokerGame:
    def __init__(self, players, small_blind=10, big_blind=20):
        self.players    = players
        self.sb         = small_blind
        self.bb         = big_blind
        self.dealer_pos = 0

    def run_tournament(self):
        """Run until one player has all chips. Return winner pid."""
        hand_num = 0
        while sum(1 for p in self.players if p.chips > 0) > 1:
            hand_num += 1
            self._play_hand()
            if hand_num > 2000:   # safety valve
                break
        survivors = [p for p in self.players if p.chips > 0]
        return survivors[0].pid if survivors else -1

    def _play_hand(self):
        active = [p for p in self.players if p.chips > 0]
        if len(active) < 2:
            return

        for p in active:
            p.reset_for_hand()

        deck = make_deck()
        random.shuffle(deck)

        # deal hole cards
        for p in active:
            p.hole = [deck.pop(), deck.pop()]

        community = []
        pot       = 0

        # post blinds
        n = len(active)
        sb_idx = self.dealer_pos % n
        bb_idx = (self.dealer_pos + 1) % n
        sb_player = active[sb_idx]
        bb_player = active[bb_idx]

        sb_amt = min(self.sb, sb_player.chips)
        bb_amt = min(self.bb, bb_player.chips)
        sb_player.chips     -= sb_amt
        sb_player.current_bet = sb_amt
        bb_player.chips     -= bb_amt
        bb_player.current_bet = bb_amt
        pot += sb_amt + bb_amt

        # betting rounds
        for phase, cards_to_deal in [('preflop', 0), ('flop', 3), ('turn', 1), ('river', 1)]:
            if phase != 'preflop':
                for _ in range(cards_to_deal):
                    community.append(deck.pop())
                for p in active:
                    p.current_bet = 0

            pot = self._betting_round(active, community, pot, phase,
                                      current_bet=bb_amt if phase == 'preflop' else 0,
                                      start_idx=(bb_idx + 1) % n if phase == 'preflop' else sb_idx)

            live = [p for p in active if not p.folded]
            if len(live) <= 1:
                break

        # showdown
        live = [p for p in active if not p.folded]
        if len(live) == 1:
            live[0].chips += pot
        else:
            scores = [(best_hand(p.hole + community), p) for p in live]
            best_score = max(s for s, _ in scores)
            winners = [p for s, p in scores if s == best_score]
            share = pot // len(winners)
            for w in winners:
                w.chips += share
            # leftover chip to first winner
            live[0].chips += pot - share * len(winners)

        self.dealer_pos = (self.dealer_pos + 1) % len(self.players)

    def _betting_round(self, active, community, pot, phase,
                       current_bet=0, start_idx=0):
        n = len(active)
        live = [p for p in active if not p.folded and not p.all_in]
        if not live:
            return pot

        avg_stack = sum(p.chips for p in active) / len(active)
        active_opponents_count = len([p for p in active if not p.folded]) - 1

        acted = set()
        last_raiser = None
        idx = start_idx % n

        max_iters = n * 4
        iters = 0
        while iters < max_iters:
            iters += 1
            p = active[idx % n]
            idx += 1

            if p.folded or p.all_in:
                continue

            to_call = max(0, current_bet - p.current_bet)

            # if everyone who can act has acted and no raise pending, stop
            live_can_act = [q for q in active if not q.folded and not q.all_in]
            if len(acted) >= len(live_can_act) and last_raiser is None:
                break
            if p.pid in acted and p.pid != last_raiser:
                # they already acted and no one raised since
                all_acted = all(q.pid in acted for q in live_can_act)
                if all_acted:
                    break

            gs = {
                'to_call':          to_call,
                'pot':              pot,
                'phase':            phase,
                'community':        community,
                'active_opponents': active_opponents_count,
                'avg_stack':        avg_stack,
                'position':         idx % n,
                'street_bets':      current_bet,
            }

            action, amount = p.act(gs)

            if action == 'fold':
                p.folded = True
                acted.add(p.pid)
                live_left = [q for q in active if not q.folded]
                if len(live_left) <= 1:
                    break

            elif action == 'check':
                acted.add(p.pid)

            elif action == 'call':
                call_amt = min(to_call, p.chips)
                p.chips       -= call_amt
                p.current_bet += call_amt
                pot           += call_amt
                if p.chips == 0:
                    p.all_in = True
                acted.add(p.pid)

            elif action == 'raise':
                total_put_in = min(amount, p.chips)
                if total_put_in <= to_call:
                    # treat as call
                    call_amt = min(to_call, p.chips)
                    p.chips       -= call_amt
                    p.current_bet += call_amt
                    pot           += call_amt
                    if p.chips == 0:
                        p.all_in = True
                    acted.add(p.pid)
                else:
                    p.chips       -= total_put_in
                    old_bet        = p.current_bet
                    p.current_bet += total_put_in
                    pot           += total_put_in
                    if p.current_bet > current_bet:
                        current_bet  = p.current_bet
                        last_raiser  = p.pid
                        acted        = {p.pid}   # everyone must re-act
                    else:
                        acted.add(p.pid)
                    if p.chips == 0:
                        p.all_in = True

            # stop if only one non-folded player left
            if len([q for q in active if not q.folded]) <= 1:
                break

        return pot


# ─── Run 100 tournaments ──────────────────────────────────────────────────────

def run_simulations(n=100, starting_chips=1000):
    win_counts = Counter()

    for sim in range(n):
        players = []
        for i, strat in enumerate(STRATEGIES):
            players.append(Player(pid=i, strategy_fn=strat, chips=starting_chips))

        game = PokerGame(players, small_blind=10, big_blind=20)
        winner_pid = game.run_tournament()
        win_counts[winner_pid] += 1

    return win_counts


# ─── Histogram renderer ───────────────────────────────────────────────────────

def render_histogram(win_counts, n_sims):
    print()
    print("=" * 65)
    print("  🃏  TEXAS HOLD'EM — 100-TOURNAMENT RESULTS  🃏")
    print("=" * 65)
    print(f"  {n_sims} tournaments  |  6 players  |  1,000 chips each")
    print("-" * 65)
    print(f"  {'Player':<6}  {'Strategy':<26}  {'Wins':>4}  {'%':>5}  Bar")
    print("-" * 65)

    max_wins = max(win_counts.values()) if win_counts else 1
    bar_max  = 30

    for pid in range(6):
        wins  = win_counts.get(pid, 0)
        pct   = wins / n_sims * 100
        bar   = "#" * int(wins / max_wins * bar_max)
        name  = STRATEGY_NAMES[pid]
        tag   = " <-- YOLO" if pid == 0 else ""
        print(f"  P{pid+1:<5}  {name:<26}  {wins:>4}  {pct:>4.1f}%  {bar}{tag}")

    print("-" * 65)
    top_pid   = max(win_counts, key=win_counts.get) if win_counts else -1
    top_name  = STRATEGY_NAMES.get(top_pid, "Unknown")
    top_wins  = win_counts.get(top_pid, 0)
    print(f"\n  WINNER WINNER CHICKEN DINNER: P{top_pid+1} — {top_name}")
    print(f"  ({top_wins} wins out of {n_sims} tournaments, {top_wins/n_sims*100:.1f}%)")
    print("=" * 65)
    print()

    if top_pid == 0:
        print("  *** suflair GPT has been HUMILIATED ***")
        print("  *** The YOLO bot conquered all elaborate strategies ***")
        print("  *** Chaos theory: 1 — Game theory: 0 ***")
    else:
        print(f"  (YOLO All-In won {win_counts.get(0,0)} times — sometimes chaos works)")
        print(f"  Elaborate strategy '{top_name}' dominated the table.")
        print("  suflair GPT would have built something smarter... maybe.")
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    random.seed(42)
    N = 100
    print(f"\nRunning {N} Texas Hold'em tournaments...")
    print("Player 1: YOLO All-In   |   Players 2-6: Elaborate strategies")
    print("No player knows anyone else's strategy.\n")

    results = run_simulations(N, starting_chips=1000)
    render_histogram(results, N)
