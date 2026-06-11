"""
Texas Hold'em Poker Tournament Simulator
100 tournaments, 6 players, histogram of winners.
Player 1: YOLO All-In always
Players 2-6: Elaborate strategies (GTO, Tight-Aggressive, Loose-Aggressive, Pot Control, Bluff Machine)
"""

import random
import sys
from collections import Counter
from itertools import combinations

# ─────────────────────── CARD ENGINE ───────────────────────

RANKS = list(range(2, 15))  # 2..14 (14=Ace)
SUITS = ['♠', '♥', '♦', '♣']
RANK_NAMES = {2:'2',3:'3',4:'4',5:'5',6:'6',7:'7',8:'8',9:'9',10:'T',11:'J',12:'Q',13:'K',14:'A'}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def hand_rank(cards):
    """Return a comparable tuple representing the best 5-card hand from up to 7 cards."""
    best = None
    for combo in combinations(cards, 5):
        val = score_five(combo)
        if best is None or val > best:
            best = val
    return best

def score_five(cards):
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5) or ranks == [14,5,4,3,2]
    if ranks == [14,5,4,3,2]:
        ranks = [5,4,3,2,1]
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    counts = [g[1] for g in groups]
    ordered = [g[0] for g in groups]

    if flush and straight:   return (8, ordered)
    if counts[0] == 4:       return (7, ordered)
    if counts[:2] == [3,2]:  return (6, ordered)
    if flush:                return (5, ordered)
    if straight:             return (4, ordered)
    if counts[0] == 3:       return (3, ordered)
    if counts[:2] == [2,2]:  return (2, ordered)
    if counts[0] == 2:       return (1, ordered)
    return (0, ordered)

# ─────────────────────── HAND STRENGTH ESTIMATION ───────────────────────

def estimate_strength(hole, community):
    """Monte Carlo hand strength estimate (100 samples)."""
    known = hole + community
    deck = [c for c in make_deck() if c not in known]
    wins = 0
    trials = 80
    needed = 5 - len(community)
    for _ in range(trials):
        opp_hole = random.sample(deck, 2)
        remaining = [c for c in deck if c not in opp_hole]
        board_extra = random.sample(remaining, needed)
        board = community + board_extra
        my_hand = hand_rank(hole + board)
        opp_hand = hand_rank(opp_hole + board)
        if my_hand > opp_hand:
            wins += 1
        elif my_hand == opp_hand:
            wins += 0.5
    return wins / trials

def quick_preflop_strength(hole):
    """Fast preflop hand strength heuristic 0..1."""
    r1, r2 = hole[0][0], hole[1][0]
    s1, s2 = hole[0][1], hole[1][1]
    hi, lo = max(r1,r2), min(r1,r2)
    score = 0.0
    # pairs
    if hi == lo:
        score = 0.5 + (hi - 2) / 24.0
    else:
        score = (hi - 2) / 24.0 * 0.7 + (lo - 2) / 24.0 * 0.3
        if s1 == s2: score += 0.05   # suited
        if hi - lo <= 3: score += 0.05  # connected
    return min(score, 1.0)

# ─────────────────────── STRATEGIES ───────────────────────

class Strategy:
    name = "Base"

    def decide(self, player, game_state):
        """Return ('fold'|'call'|'raise', amount)"""
        raise NotImplementedError


class YoloAllIn(Strategy):
    """Player 1: always go all-in, no thoughts, no fear."""
    name = "YOLO All-In"

    def decide(self, player, gs):
        return ('raise', player.chips)


class GTOBalanced(Strategy):
    """
    GTO-inspired: uses estimated hand strength to mix calls/raises/folds.
    Defends appropriate frequencies, doesn't over-fold or over-bluff.
    """
    name = "GTO Balanced"

    def decide(self, player, gs):
        strength = gs.get_strength(player)
        pot = gs.pot
        to_call = gs.current_bet - player.bet_in_round
        stack = player.chips

        # pot odds
        if to_call > 0:
            pot_odds = to_call / (pot + to_call)
        else:
            pot_odds = 0

        # GTO mixed strategy thresholds
        if strength > 0.80:
            # value raise, size 2/3 pot
            raise_amount = min(int(pot * 0.67) + to_call, stack)
            return ('raise', max(raise_amount, to_call + gs.big_blind))
        elif strength > 0.55:
            # call or small raise with top-of-range hands
            if random.random() < 0.35:
                raise_amount = min(int(pot * 0.4) + to_call, stack)
                return ('raise', max(raise_amount, to_call + gs.big_blind))
            return ('call', to_call)
        elif strength > pot_odds + 0.05:
            return ('call', to_call)
        elif strength > 0.30 and to_call == 0:
            # bluff with blockers when checking is free
            if random.random() < 0.25:
                return ('raise', min(int(pot * 0.5), stack))
            return ('call', 0)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)


class TightAggressive(Strategy):
    """
    TAG: Only plays premium hands, but bets/raises hard when it does.
    Tight preflop selection, aggressive postflop when holding strong hands.
    """
    name = "Tight-Aggressive"

    def decide(self, player, gs):
        strength = gs.get_strength(player)
        pot = gs.pot
        to_call = gs.current_bet - player.bet_in_round
        stack = player.chips

        # very tight preflop threshold
        preflop_thresh = 0.65 if gs.street == 'preflop' else 0.50

        if strength > 0.85:
            # big value bet
            raise_amount = min(int(pot * 0.85) + to_call, stack)
            return ('raise', max(raise_amount, to_call + gs.big_blind))
        elif strength > preflop_thresh:
            if to_call == 0:
                # bet for value
                return ('raise', min(int(pot * 0.6), stack))
            return ('call', to_call)
        elif to_call == 0:
            return ('call', 0)  # free check
        else:
            return ('fold', 0)  # fold marginal hands to pressure


class LooseAggressive(Strategy):
    """
    LAG: Plays wide range, applies constant pressure, steals pots frequently.
    Uses position and aggression to compensate for weaker hand selection.
    """
    name = "Loose-Aggressive"

    def decide(self, player, gs):
        strength = gs.get_strength(player)
        pot = gs.pot
        to_call = gs.current_bet - player.bet_in_round
        stack = player.chips
        position_bonus = 0.05 if gs.is_late_position(player) else 0

        effective_strength = strength + position_bonus

        if effective_strength > 0.70:
            raise_amount = min(int(pot * 0.75) + to_call, stack)
            return ('raise', max(raise_amount, to_call + gs.big_blind))
        elif effective_strength > 0.40:
            # wide semi-bluff range
            if random.random() < 0.45:
                raise_amount = min(int(pot * 0.55) + to_call, stack)
                return ('raise', max(raise_amount, to_call + gs.big_blind))
            return ('call', to_call)
        elif effective_strength > 0.25 or to_call == 0:
            if to_call == 0 and random.random() < 0.50:
                # steal attempt
                return ('raise', min(int(pot * 0.45) + gs.big_blind, stack))
            return ('call', to_call)
        else:
            if random.random() < 0.30:
                return ('call', to_call)
            return ('fold', 0)


class PotControl(Strategy):
    """
    Pot Control: Keeps the pot manageable with medium-strength hands.
    Avoid big confrontations without nutted hands; extract value carefully.
    """
    name = "Pot Control"

    def decide(self, player, gs):
        strength = gs.get_strength(player)
        pot = gs.pot
        to_call = gs.current_bet - player.bet_in_round
        stack = player.chips
        committed_ratio = player.total_invested / max(player.starting_chips, 1)

        if strength > 0.85:
            # only raise big with premium hands
            raise_amount = min(int(pot * 0.65) + to_call, stack)
            return ('raise', max(raise_amount, to_call + gs.big_blind))
        elif strength > 0.60:
            # pot control: call, don't raise unless short-stacked
            if committed_ratio > 0.50 or stack < gs.big_blind * 8:
                raise_amount = min(int(pot * 0.40) + to_call, stack)
                return ('raise', max(raise_amount, to_call + gs.big_blind))
            return ('call', to_call)
        elif strength > 0.40:
            if to_call <= gs.big_blind * 2:
                return ('call', to_call)
            return ('fold', 0)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)


class BluffMachine(Strategy):
    """
    Bluff Machine: High bluff frequency, polarized betting (nuts or air).
    Uses board texture, scare cards, and opponent tendencies to bluff optimally.
    """
    name = "Bluff Machine"

    def decide(self, player, gs):
        strength = gs.get_strength(player)
        pot = gs.pot
        to_call = gs.current_bet - player.bet_in_round
        stack = player.chips

        # scare card bonus: if board has high cards or flush draws, bluff more
        scare_bonus = self._scare_factor(gs.community)

        if strength > 0.80:
            # over-bet for value or deceptive
            raise_amount = min(int(pot * 1.2) + to_call, stack)
            return ('raise', max(raise_amount, to_call + gs.big_blind))
        elif strength > 0.55:
            if random.random() < 0.50:
                raise_amount = min(int(pot * 0.80) + to_call, stack)
                return ('raise', max(raise_amount, to_call + gs.big_blind))
            return ('call', to_call)
        elif random.random() < (0.40 + scare_bonus):
            # pure bluff
            raise_amount = min(int(pot * 0.90) + to_call, stack)
            if stack > raise_amount:
                return ('raise', raise_amount)
            return ('call', to_call)
        elif to_call <= gs.big_blind * 2:
            return ('call', to_call)
        elif to_call == 0:
            return ('call', 0)
        else:
            return ('fold', 0)

    def _scare_factor(self, community):
        if not community:
            return 0
        high_cards = sum(1 for c in community if c[0] >= 12)
        return min(high_cards * 0.06, 0.18)


STRATEGIES = [
    YoloAllIn(),       # Player 1
    GTOBalanced(),     # Player 2
    TightAggressive(), # Player 3
    LooseAggressive(), # Player 4
    PotControl(),      # Player 5
    BluffMachine(),    # Player 6
]

# ─────────────────────── GAME OBJECTS ───────────────────────

class Player:
    def __init__(self, pid, chips, strategy):
        self.pid = pid
        self.chips = chips
        self.strategy = strategy
        self.hole = []
        self.bet_in_round = 0
        self.total_invested = 0
        self.starting_chips = chips
        self.folded = False
        self.all_in = False

    def reset_for_hand(self, starting_chips):
        self.starting_chips = self.chips
        self.hole = []
        self.bet_in_round = 0
        self.total_invested = 0
        self.folded = False
        self.all_in = False

    @property
    def name(self):
        return f"P{self.pid}({self.strategy.name})"


class GameState:
    def __init__(self, players, pot, current_bet, big_blind, street, community, dealer_idx):
        self.players = players
        self.pot = pot
        self.current_bet = current_bet
        self.big_blind = big_blind
        self.street = street
        self.community = community
        self.dealer_idx = dealer_idx
        self._strength_cache = {}

    def get_strength(self, player):
        pid = player.pid
        if pid in self._strength_cache:
            return self._strength_cache[pid]
        if self.street == 'preflop':
            s = quick_preflop_strength(player.hole)
        else:
            s = estimate_strength(player.hole, self.community)
        self._strength_cache[pid] = s
        return s

    def is_late_position(self, player):
        active = [p for p in self.players if not p.folded and p.chips > 0]
        if len(active) < 2:
            return True
        idx = active.index(player) if player in active else 0
        return idx >= len(active) - 2


# ─────────────────────── BETTING ROUND ───────────────────────

def betting_round(players, pot, current_bet, big_blind, street, community, dealer_idx):
    active = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
    if len(active) <= 1:
        return pot, current_bet

    gs = GameState(players, pot, current_bet, big_blind, street, community, dealer_idx)
    max_iterations = len(players) * 4
    iterations = 0
    last_raiser = None
    acted = set()

    # order: start left of dealer
    n = len(players)
    order = []
    for i in range(1, n + 1):
        idx = (dealer_idx + i) % n
        if not players[idx].folded and not players[idx].all_in and players[idx].chips > 0:
            order.append(players[idx])

    i = 0
    while iterations < max_iterations:
        iterations += 1
        if not order:
            break
        player = order[i % len(order)]
        i += 1

        if player.folded or player.all_in or player.chips <= 0:
            continue

        # if everyone has acted and no raises pending, end
        to_call = gs.current_bet - player.bet_in_round
        if player.pid in acted and to_call <= 0 and last_raiser != player.pid:
            break

        action, amount = player.strategy.decide(player, gs)

        if action == 'fold':
            player.folded = True
            acted.add(player.pid)

        elif action == 'call':
            call_amount = min(to_call, player.chips)
            player.chips -= call_amount
            player.bet_in_round += call_amount
            player.total_invested += call_amount
            pot += call_amount
            gs.pot = pot
            acted.add(player.pid)

        elif action == 'raise':
            total_put_in = min(amount, player.chips)
            additional = total_put_in
            player.chips -= additional
            player.bet_in_round += additional
            player.total_invested += additional
            pot += additional
            gs.pot = pot

            if player.bet_in_round > gs.current_bet:
                gs.current_bet = player.bet_in_round
                last_raiser = player.pid
                acted = {player.pid}  # reset action tracking on raise

            if player.chips == 0:
                player.all_in = True
            acted.add(player.pid)

        # check if only one non-folded player remains
        still_in = [p for p in players if not p.folded]
        if len(still_in) == 1:
            break

        # check if all active players have acted at current bet level
        active_now = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
        if all(p.pid in acted and (gs.current_bet - p.bet_in_round) <= 0 for p in active_now):
            break

    return pot, gs.current_bet


# ─────────────────────── HAND SIMULATION ───────────────────────

def play_hand(players, dealer_idx, big_blind):
    deck = make_deck()
    random.shuffle(deck)

    for p in players:
        p.reset_for_hand(p.chips)

    # deal hole cards
    for p in players:
        if p.chips > 0:
            p.hole = [deck.pop(), deck.pop()]

    # post blinds
    n = len(players)
    active_players = [p for p in players if p.chips > 0]
    if len(active_players) < 2:
        return

    sb_idx = (dealer_idx + 1) % n
    bb_idx = (dealer_idx + 2) % n
    # find next active players for blinds
    def next_active(start):
        for i in range(n):
            idx = (start + i) % n
            if players[idx].chips > 0:
                return idx
        return start

    sb_idx = next_active(dealer_idx + 1)
    bb_idx = next_active(sb_idx + 1)

    sb = min(big_blind // 2, players[sb_idx].chips)
    players[sb_idx].chips -= sb
    players[sb_idx].bet_in_round = sb
    players[sb_idx].total_invested = sb

    bb = min(big_blind, players[bb_idx].chips)
    players[bb_idx].chips -= bb
    players[bb_idx].bet_in_round = bb
    players[bb_idx].total_invested = bb

    pot = sb + bb
    current_bet = bb

    community = []

    # preflop
    pot, current_bet = betting_round(players, pot, current_bet, big_blind, 'preflop', community, dealer_idx)
    for p in players:
        p.bet_in_round = 0

    still_in = [p for p in players if not p.folded and p.chips >= 0]
    if len(still_in) <= 1:
        _award_pot(players, pot, community)
        return

    # flop
    community = [deck.pop() for _ in range(3)]
    pot, current_bet = betting_round(players, pot, 0, big_blind, 'flop', community, dealer_idx)
    for p in players:
        p.bet_in_round = 0

    still_in = [p for p in players if not p.folded]
    if len(still_in) <= 1:
        _award_pot(players, pot, community)
        return

    # turn
    community.append(deck.pop())
    pot, current_bet = betting_round(players, pot, 0, big_blind, 'turn', community, dealer_idx)
    for p in players:
        p.bet_in_round = 0

    still_in = [p for p in players if not p.folded]
    if len(still_in) <= 1:
        _award_pot(players, pot, community)
        return

    # river
    community.append(deck.pop())
    pot, current_bet = betting_round(players, pot, 0, big_blind, 'river', community, dealer_idx)

    _award_pot(players, pot, community)


def _award_pot(players, pot, community):
    contenders = [p for p in players if not p.folded]
    if not contenders:
        return
    if len(contenders) == 1:
        contenders[0].chips += pot
        return

    # evaluate best hand
    scored = []
    for p in contenders:
        if p.hole:
            score = hand_rank(p.hole + community)
        else:
            score = (0, [])
        scored.append((score, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score = scored[0][0]
    winners = [p for s, p in scored if s == best_score]
    share = pot // len(winners)
    remainder = pot % len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += remainder  # give remainder to first winner


# ─────────────────────── TOURNAMENT ───────────────────────

def run_tournament(starting_chips=1000, starting_blind=10):
    players = [Player(i+1, starting_chips, STRATEGIES[i]) for i in range(6)]
    dealer_idx = 0
    big_blind = starting_blind
    hand_count = 0
    blind_increase_interval = 15  # increase blinds every N hands

    while True:
        active = [p for p in players if p.chips > 0]
        if len(active) == 1:
            return active[0].pid

        # blinds escalate
        hand_count += 1
        if hand_count % blind_increase_interval == 0:
            big_blind = min(big_blind * 2, starting_chips)

        play_hand(players, dealer_idx, big_blind)

        # advance dealer
        for _ in range(len(players)):
            dealer_idx = (dealer_idx + 1) % len(players)
            if players[dealer_idx].chips > 0:
                break

        # safety: cap at 500 hands per tournament
        if hand_count > 500:
            surviving = sorted([p for p in players if p.chips > 0], key=lambda x: x.chips, reverse=True)
            return surviving[0].pid if surviving else players[0].pid


# ─────────────────────── HISTOGRAM ───────────────────────

def print_histogram(results, n_sims):
    print()
    print("=" * 62)
    print("  TEXAS HOLD'EM TOURNAMENT SIMULATION — 100 RUNS")
    print("  Last Player Standing (Winner Winner Chicken Dinner)")
    print("=" * 62)
    print()

    max_wins = max(results.values()) if results else 1
    bar_max = 40

    for pid, strategy in zip(range(1, 7), STRATEGIES):
        wins = results.get(pid, 0)
        pct = wins / n_sims * 100
        bar_len = int(wins / max_wins * bar_max)
        bar = '█' * bar_len + '░' * (bar_max - bar_len)

        label = f"P{pid} {strategy.name}"
        marker = " ← 💀 THE CHOSEN ONE" if pid == 1 else ""
        print(f"  {label:<28} {bar}  {wins:>3} wins ({pct:5.1f}%){marker}")

    print()
    print("-" * 62)
    winner_pid = max(results, key=results.get)
    winner_name = STRATEGIES[winner_pid - 1].name
    loser_pid = min(results, key=results.get) if len(results) > 1 else None

    print(f"  CHAMPION:  P{winner_pid} {winner_name} ({results[winner_pid]} wins)")
    if loser_pid:
        print(f"  DUNCE:     P{loser_pid} {STRATEGIES[loser_pid-1].name} ({results.get(loser_pid,0)} wins)")

    if 1 in results:
        yolo_wins = results[1]
        print()
        if yolo_wins > n_sims * 0.20:
            print("  PLOT TWIST: The YOLO All-In ape is actually decent?!")
        elif yolo_wins > n_sims * 0.10:
            print("  The galaxy-brain strategies are sweating bullets rn.")
        else:
            print("  Elaborate strategies: 1 | YOLO degenerate: 0")
            print("  suflair GPT has been HUMILIATED. Stay mad, ChatGPT.")
    print("=" * 62)
    print()


# ─────────────────────── MAIN ───────────────────────

def main():
    N_SIMS = 100
    STARTING_CHIPS = 1500

    print(f"\nRunning {N_SIMS} Texas Hold'em tournaments...")
    print("  Each tournament: 6 players, same starting chips, last one standing wins.\n")
    print("  Strategies:")
    for i, s in enumerate(STRATEGIES):
        tag = " [PLAYER 1 — THE DEGENERATE]" if i == 0 else f" [Player {i+1}]"
        print(f"    {tag:<30} {s.name}")
    print()

    results = Counter()
    for sim in range(N_SIMS):
        if (sim + 1) % 10 == 0:
            print(f"  ... completed {sim+1}/{N_SIMS} tournaments", flush=True)
        winner = run_tournament(starting_chips=STARTING_CHIPS)
        results[winner] += 1

    print_histogram(results, N_SIMS)


if __name__ == '__main__':
    main()
