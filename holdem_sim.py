"""
Texas Hold'em Poker Simulation
Player 1  : The Degenerate (always goes all-in)
Players 2-6: Five elaborate strategy bots
100 tournaments, equal starting stacks.
Outputs a winner histogram.
"""

import random
import collections
from itertools import combinations

# ---------------------------------------------------------------------------
# Card / Deck primitives
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    return c[0] + c[1]

# ---------------------------------------------------------------------------
# Hand evaluator  (returns a comparable tuple, higher = better)
# ---------------------------------------------------------------------------

def hand_rank(cards):
    """Evaluate best 5-card hand from up to 7 cards."""
    best = None
    for combo in combinations(cards, 5):
        v = eval5(combo)
        if best is None or v > best:
            best = v
    return best

def eval5(cards):
    ranks = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (ranks == list(range(ranks[0], ranks[0]-5, -1)) or
                ranks == [12, 3, 2, 1, 0])  # A-low straight
    if straight and ranks[0] == 12 and ranks[1] == 3:
        ranks = [3, 2, 1, 0, -1]  # wheel
    counts = sorted(collections.Counter(ranks).values(), reverse=True)
    rank_groups = [r for cnt in sorted(set(counts), reverse=True)
                   for r in sorted([r for r, c in collections.Counter(ranks).items() if c == cnt], reverse=True)]

    if flush and straight:
        return (8, ranks)
    if counts == [4, 1]:
        return (7, rank_groups)
    if counts == [3, 2]:
        return (6, rank_groups)
    if flush:
        return (5, ranks)
    if straight:
        return (4, ranks)
    if counts[0] == 3:
        return (3, rank_groups)
    if counts[:2] == [2, 2]:
        return (2, rank_groups)
    if counts[0] == 2:
        return (1, rank_groups)
    return (0, ranks)

# ---------------------------------------------------------------------------
# Equity estimator via Monte Carlo (fast, N=200 rollouts)
# ---------------------------------------------------------------------------

def estimate_equity(hole, board, n_opponents, n_samples=200):
    deck = [c for c in make_deck() if c not in hole and c not in board]
    wins = 0
    needed = 5 - len(board)
    for _ in range(n_samples):
        d = deck[:]
        random.shuffle(d)
        run_board = board + d[:needed]
        d = d[needed:]
        my_hand = hand_rank(hole + run_board)
        best_opp = None
        for _ in range(n_opponents):
            opp_hole = [d.pop(), d.pop()]
            oh = hand_rank(opp_hole + run_board)
            if best_opp is None or oh > best_opp:
                best_opp = oh
        if my_hand >= best_opp:
            wins += 1
    return wins / n_samples

# ---------------------------------------------------------------------------
# Game state snapshot passed to each strategy
# ---------------------------------------------------------------------------

class GameState:
    def __init__(self, hole, board, pot, to_call, my_stack, min_raise,
                 big_blind, street, n_opponents_active, position, n_total_players):
        self.hole = hole
        self.board = board
        self.pot = pot
        self.to_call = to_call           # chips needed to call
        self.my_stack = my_stack
        self.min_raise = min_raise
        self.big_blind = big_blind
        self.street = street             # 0=pre, 1=flop, 2=turn, 3=river
        self.n_opponents = n_opponents_active
        self.position = position         # 0=early, 1=middle, 2=late/dealer
        self.n_total = n_total_players

# ---------------------------------------------------------------------------
# Strategy return values: ("fold"|"call"|"raise", amount)
# amount only used for "raise"
# ---------------------------------------------------------------------------

# === Strategy 0: The Degenerate (always all-in) ===========================

def strategy_degenerate(gs):
    return ("raise", gs.my_stack)

# === Strategy 1: GTO-Lite (equity-based, pot-odds, position-aware) ========

def strategy_gto_lite(gs):
    equity = estimate_equity(gs.hole, gs.board, gs.n_opponents, n_samples=150)
    pot_odds = gs.to_call / (gs.pot + gs.to_call) if (gs.pot + gs.to_call) > 0 else 0
    pos_bonus = 0.04 * gs.position  # late position gets more credit

    if equity + pos_bonus < pot_odds * 0.9:
        return ("fold", 0)

    edge = equity + pos_bonus - pot_odds
    if edge > 0.20 and gs.my_stack > gs.min_raise:
        raise_size = min(gs.my_stack, int(gs.pot * (0.75 + equity)))
        return ("raise", max(raise_size, gs.min_raise))
    if equity + pos_bonus >= pot_odds:
        return ("call", 0)
    return ("fold", 0)

# === Strategy 2: TAG – Tight-Aggressive ====================================

PREMIUM_HANDS = {
    frozenset(["A", "A"]), frozenset(["K", "K"]), frozenset(["Q", "Q"]),
    frozenset(["J", "J"]), frozenset(["T", "T"]),
}
STRONG_HANDS = {
    frozenset(["9", "9"]), frozenset(["8", "8"]),
    frozenset(["A", "K"]), frozenset(["A", "Q"]), frozenset(["A", "J"]),
    frozenset(["K", "Q"]),
}

def strategy_tag(gs):
    hole_ranks = frozenset(c[0] for c in gs.hole)
    suited = gs.hole[0][1] == gs.hole[1][1]

    if gs.street == 0:  # pre-flop
        if hole_ranks in PREMIUM_HANDS:
            raise_size = min(gs.my_stack, max(gs.min_raise, gs.big_blind * 4))
            return ("raise", raise_size)
        if hole_ranks in STRONG_HANDS or (suited and "A" in hole_ranks):
            if gs.to_call <= gs.big_blind * 3:
                return ("call", 0)
            if gs.position == 2:
                return ("call", 0)
            return ("fold", 0)
        if gs.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    # post-flop: use equity
    equity = estimate_equity(gs.hole, gs.board, gs.n_opponents, 120)
    if equity > 0.65:
        return ("raise", min(gs.my_stack, int(gs.pot * 0.75)))
    if equity > 0.40:
        return ("call", 0)
    if gs.to_call == 0:
        return ("call", 0)
    return ("fold", 0)

# === Strategy 3: LAG – Loose-Aggressive (bluff-heavy) =====================

def strategy_lag(gs):
    equity = estimate_equity(gs.hole, gs.board, gs.n_opponents, 100)
    bluff_threshold = 0.28 - 0.03 * gs.n_opponents  # bluff less vs more players

    # Steal in late position pre-flop
    if gs.street == 0 and gs.position == 2 and gs.to_call <= gs.big_blind * 2:
        if random.random() < 0.55:
            return ("raise", min(gs.my_stack, gs.big_blind * 3))

    if equity > 0.55:
        size = min(gs.my_stack, int(gs.pot * random.uniform(0.6, 1.2)))
        return ("raise", max(size, gs.min_raise))

    if equity > bluff_threshold and random.random() < 0.40:
        size = min(gs.my_stack, int(gs.pot * 0.5))
        if size >= gs.min_raise:
            return ("raise", size)

    if equity >= 0.30 or gs.to_call == 0:
        return ("call", 0)
    return ("fold", 0)

# === Strategy 4: Pot-Control (ICM-aware, stack preservation) ==============

def strategy_pot_control(gs):
    equity = estimate_equity(gs.hole, gs.board, gs.n_opponents, 120)
    spr = gs.my_stack / gs.pot if gs.pot > 0 else 99  # stack-to-pot ratio

    # Short stack: commit or fold
    if spr < 3:
        if equity > 0.45:
            return ("raise", gs.my_stack)
        if gs.to_call == 0 or equity > 0.30:
            return ("call", 0)
        return ("fold", 0)

    # Deep stack: control pot size, don't over-commit without nuts
    if equity > 0.75:
        size = min(gs.my_stack, int(gs.pot * 0.65))
        return ("raise", max(size, gs.min_raise))
    if equity > 0.50:
        return ("call", 0)
    if gs.to_call == 0:
        return ("call", 0)
    if gs.to_call <= gs.pot * 0.20:
        return ("call", 0)
    return ("fold", 0)

# === Strategy 5: Nash Push/Fold (short-stack shove-or-fold) ===============

def strategy_push_fold(gs):
    """Simplified Nash push/fold: shove with strong hands, fold otherwise."""
    M_ratio = gs.my_stack / (gs.big_blind * 1.5) if gs.big_blind > 0 else 99

    equity = estimate_equity(gs.hole, gs.board, gs.n_opponents, 100)

    if M_ratio < 10:
        # Push/fold mode
        shove_threshold = 0.35 + 0.02 * max(0, 10 - M_ratio)
        if equity > shove_threshold:
            return ("raise", gs.my_stack)
        if gs.to_call == 0:
            return ("call", 0)
        return ("fold", 0)

    # Normal stack: tighter play
    if equity > 0.60:
        size = min(gs.my_stack, int(gs.pot * 0.80))
        return ("raise", max(size, gs.min_raise))
    if equity > 0.42:
        return ("call", 0)
    if gs.to_call == 0:
        return ("call", 0)
    return ("fold", 0)

STRATEGIES = [
    strategy_degenerate,  # Player 1 (index 0)
    strategy_gto_lite,    # Player 2
    strategy_tag,         # Player 3
    strategy_lag,         # Player 4
    strategy_pot_control, # Player 5
    strategy_push_fold,   # Player 6
]

STRATEGY_NAMES = [
    "Degenerate (All-In)",
    "GTO-Lite",
    "TAG",
    "LAG",
    "Pot-Control",
    "Nash Push/Fold",
]

# ---------------------------------------------------------------------------
# Texas Hold'em engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, pid, stack, strategy):
        self.pid = pid
        self.stack = stack
        self.strategy = strategy
        self.hole = []
        self.bet_in_round = 0
        self.folded = False
        self.all_in = False

class HoldemGame:
    def __init__(self, players, small_blind=50):
        self.players = players
        self.small_blind = small_blind
        self.big_blind = small_blind * 2
        self.dealer = 0

    def active_players(self):
        return [p for p in self.players if p.stack > 0]

    def play_tournament(self):
        """Returns pid of winner (last player with chips)."""
        hand_num = 0
        while len(self.active_players()) > 1:
            hand_num += 1
            # Escalate blinds every 20 hands
            level = (hand_num - 1) // 20
            sb = self.small_blind * (2 ** level)
            bb = sb * 2
            self._play_hand(sb, bb)
            if hand_num > 5000:  # safety
                break

        alive = self.active_players()
        return alive[0].pid if alive else -1

    def _play_hand(self, sb, bb):
        active = self.active_players()
        if len(active) < 2:
            return

        # Reset per-hand state
        for p in active:
            p.hole = []
            p.bet_in_round = 0
            p.folded = False
            p.all_in = False

        deck = make_deck()
        random.shuffle(deck)

        # Deal hole cards
        for p in active:
            p.hole = [deck.pop(), deck.pop()]

        # Rotate dealer
        self.dealer = (self.dealer + 1) % len(self.players)
        while self.players[self.dealer].stack == 0:
            self.dealer = (self.dealer + 1) % len(self.players)

        dealer_idx = active.index(next(p for p in active if p.pid == self.players[self.dealer].pid))

        def get_player(offset):
            return active[(dealer_idx + offset) % len(active)]

        pot = 0
        board = []

        # Post blinds
        sb_player = get_player(1) if len(active) > 2 else get_player(0)
        bb_player = get_player(2) if len(active) > 2 else get_player(1)

        sb_amount = min(sb, sb_player.stack)
        bb_amount = min(bb, bb_player.stack)

        sb_player.stack -= sb_amount
        sb_player.bet_in_round = sb_amount
        bb_player.stack -= bb_amount
        bb_player.bet_in_round = bb_amount
        if sb_player.stack == 0: sb_player.all_in = True
        if bb_player.stack == 0: bb_player.all_in = True
        pot = sb_amount + bb_amount

        # Streets: pre-flop (no board), flop (3), turn (4), river (5)
        for street_num, n_board_cards in enumerate([0, 3, 1, 1]):
            board += [deck.pop() for _ in range(n_board_cards)]

            # Reset bets for this street
            for p in active:
                p.bet_in_round = 0

            current_bet = bb_amount if street_num == 0 else 0
            if street_num == 0:
                bb_player.bet_in_round = bb_amount

            # Betting order: pre-flop starts left of BB
            if street_num == 0:
                start_offset = 3 if len(active) > 2 else 0
            else:
                start_offset = 1  # left of dealer

            order = [(dealer_idx + start_offset + i) % len(active) for i in range(len(active))]

            pot, current_bet = self._betting_round(
                active, order, pot, current_bet, bb, board, street_num
            )

            in_hand = [p for p in active if not p.folded]
            if len(in_hand) <= 1:
                break

        # Showdown / award pot
        self._award_pot(active, pot, board)

    def _betting_round(self, active, order, pot, current_bet, bb, board, street_num):
        in_hand = [p for p in active if not p.folded and not p.all_in]
        if not in_hand:
            return pot, current_bet

        acted = set()
        i = 0
        max_iter = len(active) * 4

        while i < max_iter:
            idx = order[i % len(order)]
            p = active[idx]
            i += 1

            if p.folded or p.all_in or p.stack == 0:
                if len([x for x in order[:len(active)] if not active[x % len(active)].folded and not active[x % len(active)].all_in and active[x % len(active)].stack > 0]) == 0:
                    break
                acted.add(p.pid)
                continue

            to_call = current_bet - p.bet_in_round
            to_call = min(to_call, p.stack)
            min_raise = max(bb, current_bet + bb)

            n_opp = len([x for x in active if not x.folded and x.pid != p.pid])
            pos = 0 if i < len(active) // 3 else (1 if i < 2 * len(active) // 3 else 2)

            gs = GameState(
                hole=p.hole, board=board, pot=pot,
                to_call=to_call, my_stack=p.stack,
                min_raise=min_raise, big_blind=bb,
                street=street_num, n_opponents_active=max(n_opp, 1),
                position=pos, n_total_players=len(active)
            )

            action, amount = p.strategy(gs)

            if action == "fold":
                p.folded = True
                acted.add(p.pid)
            elif action == "call":
                p.stack -= to_call
                p.bet_in_round += to_call
                pot += to_call
                if p.stack == 0:
                    p.all_in = True
                acted.add(p.pid)
            elif action == "raise":
                amount = max(amount, min_raise)
                amount = min(amount, p.stack)
                total_bet = p.bet_in_round + amount
                additional = amount
                p.stack -= additional
                p.bet_in_round += additional
                pot += additional
                if total_bet > current_bet:
                    current_bet = total_bet
                    acted = {p.pid}  # others must re-act
                if p.stack == 0:
                    p.all_in = True
                acted.add(p.pid)

            still_in = [x for x in active if not x.folded and not x.all_in and x.stack > 0]
            if all(x.pid in acted for x in still_in) and len(still_in) <= 1:
                break
            if all(x.pid in acted for x in still_in) and all(x.bet_in_round >= current_bet for x in still_in):
                break

        return pot, current_bet

    def _award_pot(self, active, pot, board):
        in_hand = [p for p in active if not p.folded]
        if not in_hand:
            return

        if len(in_hand) == 1:
            in_hand[0].stack += pot
            return

        # Evaluate hands
        scored = [(hand_rank(p.hole + board), p) for p in in_hand]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score = scored[0][0]
        winners = [p for score, p in scored if score == best_score]

        share = pot // len(winners)
        remainder = pot % len(winners)
        for p in winners:
            p.stack += share
        winners[0].stack += remainder  # give remainder to first winner

# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------

def run_simulations(n=100, starting_chips=10000):
    n_players = 6
    win_counts = collections.Counter()

    for sim in range(n):
        players = [
            Player(pid=i, stack=starting_chips, strategy=STRATEGIES[i])
            for i in range(n_players)
        ]
        game = HoldemGame(players, small_blind=50)
        winner_pid = game.play_tournament()
        win_counts[winner_pid] += 1

    return win_counts

# ---------------------------------------------------------------------------
# Histogram output
# ---------------------------------------------------------------------------

def print_histogram(win_counts, n_sims):
    print("\n" + "=" * 62)
    print("  SUFLAIR GPT HUMILIATION CHAMBER — 100 TOURNAMENT RESULTS")
    print("=" * 62)
    print(f"  Starting chips: 10,000 each | Sims: {n_sims}")
    print("-" * 62)

    max_wins = max(win_counts.values()) if win_counts else 1
    bar_max = 40

    for pid, name in enumerate(STRATEGY_NAMES):
        wins = win_counts.get(pid, 0)
        bar_len = int(wins / max_wins * bar_max)
        bar = "█" * bar_len
        pct = wins / n_sims * 100
        label = f"P{pid+1} {name}"
        print(f"  {label:<28} {wins:3d} wins ({pct:5.1f}%)  {bar}")

    print("-" * 62)
    top_pid = win_counts.most_common(1)[0][0]
    print(f"  WINNER WINNER CHICKEN DINNER: Player {top_pid+1} — {STRATEGY_NAMES[top_pid]}")
    print("=" * 62 + "\n")

    # Did the degenerate manage to embarrass the smart bots?
    degen_wins = win_counts.get(0, 0)
    smart_wins = sum(win_counts.get(i, 0) for i in range(1, 6))
    print(f"  All-In Degenerate: {degen_wins} wins")
    print(f"  Smart bots total:  {smart_wins} wins")
    if degen_wins > smart_wins / 5:
        print("  Suflair GPT has been HUMILIATED. Chaos beats brains.")
    else:
        print("  The degenerate got folded into oblivion. RIP.")
    print()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Shuffling decks and running 100 tournaments...")
    print("(This may take ~30-60 seconds due to equity sampling)\n")
    random.seed(42)
    results = run_simulations(n=100, starting_chips=10000)
    print_histogram(results, n_sims=100)
