"""
Texas Hold'em Poker Simulation
6 players, 100 games, histogram of winners.

Player 1: The Unhinged — always shoves all-in, no questions asked.
Players 2-6: Five elaborate strategy bots.
"""

import random
import itertools
from collections import Counter
from enum import IntEnum

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS)}


def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]


def card_str(c):
    return c[0] + c[1]


# ---------------------------------------------------------------------------
# Hand evaluation (returns a comparable tuple, higher = better)
# ---------------------------------------------------------------------------

class HandRank(IntEnum):
    HIGH_CARD       = 0
    ONE_PAIR        = 1
    TWO_PAIR        = 2
    THREE_OF_A_KIND = 3
    STRAIGHT        = 4
    FLUSH           = 5
    FULL_HOUSE      = 6
    FOUR_OF_A_KIND  = 7
    STRAIGHT_FLUSH  = 8
    ROYAL_FLUSH     = 9


def _rank_vals(cards):
    return sorted([RANK_VAL[c[0]] for c in cards], reverse=True)


def _best_five(cards):
    """Return the best 5-card hand score from up to 7 cards."""
    best = None
    for combo in itertools.combinations(cards, 5):
        score = _eval5(combo)
        if best is None or score > best:
            best = score
    return best


def _eval5(cards):
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1

    # Check straight
    is_straight = False
    straight_high = vals[0]
    if vals[0] - vals[4] == 4 and len(set(vals)) == 5:
        is_straight = True
    # Wheel: A-2-3-4-5
    if set(vals) == {12, 0, 1, 2, 3}:
        is_straight = True
        straight_high = 3

    counts = Counter(vals)
    freq = sorted(counts.values(), reverse=True)
    # Sort groups: primary by count, secondary by rank value
    groups = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    sorted_vals = [v for v, _ in groups]

    if is_straight and is_flush:
        if vals[0] == 12 and vals[1] == 11:
            return (HandRank.ROYAL_FLUSH, vals)
        return (HandRank.STRAIGHT_FLUSH, [straight_high])

    if freq[0] == 4:
        return (HandRank.FOUR_OF_A_KIND, sorted_vals)

    if freq[0] == 3 and freq[1] == 2:
        return (HandRank.FULL_HOUSE, sorted_vals)

    if is_flush:
        return (HandRank.FLUSH, vals)

    if is_straight:
        return (HandRank.STRAIGHT, [straight_high])

    if freq[0] == 3:
        return (HandRank.THREE_OF_A_KIND, sorted_vals)

    if freq[0] == 2 and freq[1] == 2:
        return (HandRank.TWO_PAIR, sorted_vals)

    if freq[0] == 2:
        return (HandRank.ONE_PAIR, sorted_vals)

    return (HandRank.HIGH_CARD, vals)


# ---------------------------------------------------------------------------
# Monte Carlo equity estimator (used by some strategies)
# ---------------------------------------------------------------------------

def estimate_equity(hole, community, n_opponents, n_samples=200):
    """Rough win probability for our hole cards via random rollout."""
    wins = 0
    known = set(map(tuple, hole + community))
    deck_left = [c for c in make_deck() if tuple(c) not in known]

    needed = 5 - len(community)
    for _ in range(n_samples):
        sample = random.sample(deck_left, needed + 2 * n_opponents)
        board = list(community) + sample[:needed]
        my_score = _best_five(hole + board)
        won = True
        for i in range(n_opponents):
            opp_hole = sample[needed + 2*i: needed + 2*i + 2]
            if _best_five(opp_hole + board) > my_score:
                won = False
                break
        if won:
            wins += 1
    return wins / n_samples


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

def _hole_strength(hole):
    """Quick pre-flop hand strength 0-1."""
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    pair = r1 == r2
    hi = max(r1, r2)
    lo = min(r1, r2)
    gap = hi - lo

    score = (hi + lo) / 24.0   # base rank score
    if pair:
        score += 0.25
    if suited:
        score += 0.06
    if gap <= 2 and not pair:
        score += 0.04   # connector bonus
    return min(score, 1.0)


def _pot_odds(call_amount, pot):
    if call_amount == 0:
        return 1.0
    return pot / (pot + call_amount) if (pot + call_amount) > 0 else 0


# ---------------------------------------------------------------------------
# Strategy function signatures:
#   (hole, community, pot, my_stack, call_amount,
#    current_bet, n_active_opponents, street, round_num)
# Returns: action in {"fold", "call", "raise:<amount>", "check", "allin"}
# ---------------------------------------------------------------------------

# ── Strategy 0 (Player 1): The Unhinged ────────────────────────────────────

def strategy_unhinged(hole, community, pot, my_stack, call_amount,
                      current_bet, n_active_opponents, street, round_num):
    """Always shove. Every. Single. Time."""
    return "allin"


# ── Strategy 1 (Player 2): The Tight Nit ───────────────────────────────────

def strategy_tight_nit(hole, community, pot, my_stack, call_amount,
                       current_bet, n_active_opponents, street, round_num):
    """
    Only plays premium hands pre-flop.
    Post-flop: folds if equity < 0.5, otherwise value-bets.
    """
    hs = _hole_strength(hole)

    if street == "preflop":
        if hs >= 0.80:                           # AA, KK, QQ, AK-ish
            raise_to = min(my_stack, max(current_bet * 3, pot // 2))
            return f"raise:{raise_to}"
        if hs >= 0.65 and call_amount <= pot // 4:
            return "call"
        if call_amount == 0:
            return "check"
        return "fold"

    # Post-flop
    equity = estimate_equity(hole, community, n_active_opponents, 150)
    if equity >= 0.70:
        bet = min(my_stack, int(pot * 0.75))
        return f"raise:{bet}"
    if equity >= 0.50:
        return "call" if call_amount <= int(pot * 0.3) else "fold"
    if call_amount == 0:
        return "check"
    return "fold"


# ── Strategy 2 (Player 3): The Aggressive Bluffer ──────────────────────────

def strategy_bluffer(hole, community, pot, my_stack, call_amount,
                     current_bet, n_active_opponents, street, round_num):
    """
    Raises frequently, bluffs on scary boards, semi-bluffs draws,
    backs off when equity is truly hopeless.
    """
    hs = _hole_strength(hole)
    bluff_dice = random.random()

    if street == "preflop":
        if hs >= 0.55 or bluff_dice < 0.30:     # wide 3-bet range
            raise_to = min(my_stack, max(current_bet * 3, pot))
            return f"raise:{raise_to}"
        if call_amount == 0:
            return "check"
        return "call"

    equity = estimate_equity(hole, community, n_active_opponents, 150)

    # Scare-card bluff: bet pot-sized when board is coordinated
    high_cards = sum(1 for c in community if RANK_VAL[c[0]] >= 10)
    scary = high_cards >= 3

    if equity >= 0.55:
        bet = min(my_stack, int(pot * 1.0))
        return f"raise:{bet}"
    if bluff_dice < 0.40 and (scary or equity >= 0.30):
        bet = min(my_stack, int(pot * 0.80))
        return f"raise:{bet}"
    if call_amount == 0:
        return "check"
    if call_amount <= int(pot * 0.25):
        return "call"
    return "fold"


# ── Strategy 3 (Player 4): The GTO Approximator ────────────────────────────

def strategy_gto_approx(hole, community, pot, my_stack, call_amount,
                        current_bet, n_active_opponents, street, round_num):
    """
    Blends value-bets, check-raises, and folds according to rough
    GTO frequencies driven by equity thresholds and randomisation.
    """
    hs = _hole_strength(hole)
    r = random.random()

    if street == "preflop":
        # 3-bet range: top 20% of hands + 5% pure bluff
        if hs >= 0.78 or (hs < 0.45 and r < 0.05):
            raise_to = min(my_stack, max(current_bet * 3, int(pot * 0.5)))
            return f"raise:{raise_to}"
        # Call range: 45-78% equity hands
        if hs >= 0.45 and call_amount <= int(pot * 0.4):
            return "call"
        if call_amount == 0:
            return "check"
        return "fold"

    equity = estimate_equity(hole, community, n_active_opponents, 200)
    pot_odd = _pot_odds(call_amount, pot)

    if equity > 0.65:
        # Value bet, randomise sizing
        sizing = 0.5 + r * 0.5          # 50-100% pot
        bet = min(my_stack, int(pot * sizing))
        return f"raise:{bet}"
    if equity > pot_odd:                 # +EV call
        if r < 0.3 and current_bet < my_stack // 3:  # occasional check-raise
            return "check"
        return "call"
    if r < 0.15 and call_amount == 0:   # pure bluff check-raise
        bet = min(my_stack, int(pot * 0.6))
        return f"raise:{bet}"
    if call_amount == 0:
        return "check"
    return "fold"


# ── Strategy 4 (Player 5): The Stack Bully ─────────────────────────────────

def strategy_stack_bully(hole, community, pot, my_stack, call_amount,
                         current_bet, n_active_opponents, street, round_num):
    """
    Exploits chip-stack leverage. Goes nuclear on short stacks,
    plays conservatively when pot-committed and equity is low.
    """
    hs = _hole_strength(hole)
    equity = estimate_equity(hole, community, n_active_opponents, 150) if community else hs

    # Big stack aggression: if we have chips, pressure opponents
    stack_pressure = my_stack / max(pot + 1, 1)

    if street == "preflop":
        if hs >= 0.70:
            raise_to = min(my_stack, max(current_bet * 4, int(pot * 0.8)))
            return f"raise:{raise_to}"
        # Positional squeeze if we're big
        if stack_pressure > 5 and hs >= 0.50:
            raise_to = min(my_stack, int(pot * 0.6))
            return f"raise:{raise_to}"
        if call_amount == 0:
            return "check"
        if call_amount <= int(pot * 0.2):
            return "call"
        return "fold"

    if equity >= 0.60:
        # Overbet to apply maximum pressure
        bet = min(my_stack, int(pot * (1.0 + min(stack_pressure * 0.1, 0.5))))
        return f"raise:{bet}"
    if equity >= 0.40 and call_amount <= int(pot * 0.35):
        return "call"
    if call_amount == 0:
        return "check"
    return "fold"


# ── Strategy 5 (Player 6): The Pot-Control Thinker ─────────────────────────

def strategy_pot_controller(hole, community, pot, my_stack, call_amount,
                            current_bet, n_active_opponents, street, round_num):
    """
    Keeps pots small with medium-strength hands, only bloats pot with monsters.
    Reads board texture for draw-heavy vs dry boards and adjusts accordingly.
    """
    hs = _hole_strength(hole)

    if street == "preflop":
        if hs >= 0.82:
            raise_to = min(my_stack, max(current_bet * 3, int(pot * 0.6)))
            return f"raise:{raise_to}"
        if hs >= 0.55 and call_amount <= int(pot * 0.25):
            return "call"
        if call_amount == 0:
            return "check"
        return "fold"

    equity = estimate_equity(hole, community, n_active_opponents, 200)

    # Board texture: count flush / straight draws
    suit_counts = Counter(c[1] for c in community)
    flush_draw = max(suit_counts.values()) >= 3 if community else False
    cvals = sorted([RANK_VAL[c[0]] for c in community])
    connected = (cvals[-1] - cvals[0] <= 4) if len(cvals) >= 2 else False
    wet_board = flush_draw or connected

    if equity >= 0.75:
        bet = min(my_stack, int(pot * (1.2 if wet_board else 0.7)))
        return f"raise:{bet}"
    if equity >= 0.55:
        if wet_board:
            # Protect against draws
            bet = min(my_stack, int(pot * 0.65))
            return f"raise:{bet}"
        # Dry board: pot control — just call or check
        if call_amount == 0:
            return "check"
        if call_amount <= int(pot * 0.30):
            return "call"
        return "fold"
    if equity >= 0.40 and call_amount == 0:
        return "check"
    if equity >= 0.35 and call_amount <= int(pot * 0.20):
        return "call"
    if call_amount == 0:
        return "check"
    return "fold"


STRATEGIES = [
    strategy_unhinged,          # Player 1
    strategy_tight_nit,         # Player 2
    strategy_bluffer,           # Player 3
    strategy_gto_approx,        # Player 4
    strategy_stack_bully,       # Player 5
    strategy_pot_controller,    # Player 6
]

STRATEGY_NAMES = [
    "P1 The Unhinged (all-in bot)",
    "P2 Tight Nit",
    "P3 Aggressive Bluffer",
    "P4 GTO Approximator",
    "P5 Stack Bully",
    "P6 Pot-Control Thinker",
]

# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

STARTING_CHIPS = 1000
SMALL_BLIND    = 10
BIG_BLIND      = 20
STREETS        = ["preflop", "flop", "turn", "river"]


class Player:
    def __init__(self, pid, chips, strategy):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.bet      = 0       # chips in current street's pot
        self.folded   = False
        self.allin    = False

    def reset_hand(self):
        self.hole    = []
        self.bet     = 0
        self.folded  = False
        self.allin   = False

    @property
    def active(self):
        return not self.folded and not self.allin and self.chips > 0


def _deal_hole(players, deck):
    for p in players:
        p.hole = [deck.pop(), deck.pop()]


def _collect_blinds(players, dealer_idx):
    n = len(players)
    sb_idx  = (dealer_idx + 1) % n
    bb_idx  = (dealer_idx + 2) % n

    sb_player = players[sb_idx]
    bb_player = players[bb_idx]

    sb_amt = min(SMALL_BLIND, sb_player.chips)
    bb_amt = min(BIG_BLIND,   bb_player.chips)

    sb_player.chips -= sb_amt
    sb_player.bet    = sb_amt
    bb_player.chips -= bb_amt
    bb_player.bet    = bb_amt

    if sb_player.chips == 0:
        sb_player.allin = True
    if bb_player.chips == 0:
        bb_player.allin = True

    return sb_amt + bb_amt, bb_idx


def _street_betting(players, community, pot, first_to_act, street, round_num):
    """
    Run one street of betting. Returns updated pot.
    """
    n = len(players)
    current_bet  = max(p.bet for p in players)
    last_raiser  = -1
    acted        = set()   # track who has acted since last raise
    order        = [(first_to_act + i) % n for i in range(n)]

    i = 0
    while True:
        if i >= len(order) * 3:   # safety: max 3 full orbits
            break

        idx = order[i % len(order)]
        p   = players[idx]
        i  += 1

        if p.folded or p.allin or p.chips == 0:
            continue

        call_amount = current_bet - p.bet
        call_amount = min(call_amount, p.chips)

        n_active_opp = sum(1 for q in players if q.pid != p.pid and not q.folded and not q.allin)

        action = p.strategy(
            p.hole, community, pot,
            p.chips, call_amount, current_bet,
            n_active_opp, street, round_num
        )

        # Resolve action
        if action == "fold":
            p.folded = True
        elif action in ("check", "call"):
            contribute = call_amount
            p.chips -= contribute
            p.bet   += contribute
            pot     += contribute
            if p.chips == 0:
                p.allin = True
        elif action == "allin":
            contribute = p.chips
            p.chips = 0
            p.bet  += contribute
            pot    += contribute
            if p.bet > current_bet:
                current_bet = p.bet
                last_raiser = idx
                acted = {idx}
            p.allin = True
        elif action.startswith("raise:"):
            raise_amt = int(action.split(":")[1])
            raise_amt = max(raise_amt, call_amount + 1)
            raise_amt = min(raise_amt, p.chips)
            p.chips  -= raise_amt
            p.bet    += raise_amt
            pot      += raise_amt
            if p.bet > current_bet:
                current_bet = p.bet
                last_raiser = idx
                acted = {idx}
            if p.chips == 0:
                p.allin = True

        acted.add(idx)

        # Check if betting is closed
        players_needing_action = [
            q for q in players
            if not q.folded and not q.allin and q.chips > 0
            and (q.bet < current_bet or q.pid not in [players[j].pid for j in acted])
        ]
        # Simpler termination: everyone who can act has acted and bets are equal
        can_act = [q for q in players if not q.folded and not q.allin and q.chips > 0]
        all_even = all(q.bet == current_bet for q in can_act)
        all_acted = all(
            q.pid in {players[j % n].pid for j in range(first_to_act, first_to_act + n)}
            for q in can_act
        )
        if all_even and len(acted) >= len(can_act):
            break

    # Reset per-street bets
    for p in players:
        p.bet = 0

    return pot


def _showdown(players, community):
    """Return list of winners (pid list)."""
    contenders = [p for p in players if not p.folded]
    if len(contenders) == 1:
        return [contenders[0].pid]

    scores = {p.pid: _best_five(p.hole + community) for p in contenders}
    best   = max(scores.values())
    return [pid for pid, sc in scores.items() if sc == best]


def _award_pot(players, pot, community):
    """Distribute pot to winner(s); handles side pots naively."""
    winners = _showdown(players, community)
    share   = pot // len(winners)
    remainder = pot - share * len(winners)
    for p in players:
        if p.pid in winners:
            p.chips += share
    # Give remainder to first winner (doesn't matter much)
    players_map = {p.pid: p for p in players}
    players_map[winners[0]].chips += remainder


def play_hand(players, dealer_idx, round_num):
    """Play one hand. Returns dealer_idx for next hand."""
    for p in players:
        p.reset_hand()

    deck = make_deck()
    random.shuffle(deck)

    pot, bb_idx = _collect_blinds(players, dealer_idx)
    _deal_hole(players, deck)

    community = []

    # Pre-flop: action starts left of BB
    n = len(players)
    first_preflop = (bb_idx + 1) % n
    pot = _street_betting(players, community, pot, first_preflop, "preflop", round_num)

    # Check if hand is over early
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return (dealer_idx + 1) % n

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    first_post = (dealer_idx + 1) % n
    pot = _street_betting(players, community, pot, first_post, "flop", round_num)
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return (dealer_idx + 1) % n

    # Turn
    community.append(deck.pop())
    pot = _street_betting(players, community, pot, first_post, "turn", round_num)
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return (dealer_idx + 1) % n

    # River
    community.append(deck.pop())
    pot = _street_betting(players, community, pot, first_post, "river", round_num)

    _award_pot(players, pot, community)
    return (dealer_idx + 1) % n


def play_game():
    """
    Play one full game until one player has all chips.
    Returns the pid of the winner (0-indexed).
    """
    players = [
        Player(i, STARTING_CHIPS, STRATEGIES[i])
        for i in range(6)
    ]

    dealer_idx = 0
    round_num  = 0
    MAX_ROUNDS = 2000   # safety cap

    while round_num < MAX_ROUNDS:
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid

        # Rotate dealer among players who still have chips
        dealer_idx = play_hand(players, dealer_idx, round_num)
        round_num += 1

    # If we hit the cap, return chip leader
    return max(players, key=lambda p: p.chips).pid


# ---------------------------------------------------------------------------
# Run 100 simulations
# ---------------------------------------------------------------------------

def run_simulations(n=100):
    win_counts = Counter()
    for game_num in range(n):
        if (game_num + 1) % 10 == 0:
            print(f"  ... completed {game_num + 1}/{n} games", flush=True)
        winner_pid = play_game()
        win_counts[winner_pid] += 1
    return win_counts


# ---------------------------------------------------------------------------
# Histogram output
# ---------------------------------------------------------------------------

def print_histogram(win_counts, n_games):
    print()
    print("=" * 62)
    print("  TEXAS HOLD'EM — 100-GAME SIMULATION RESULTS")
    print("  Last player standing histogram (winner winner chicken dinner)")
    print("=" * 62)
    print()

    max_wins = max(win_counts.values()) if win_counts else 1
    bar_width = 40

    for pid in range(6):
        wins = win_counts.get(pid, 0)
        pct  = wins / n_games * 100
        bar  = "█" * int(bar_width * wins / max_wins) if wins else ""
        name = STRATEGY_NAMES[pid]
        tag  = " ◄ THE SHAMELESS ALL-IN BOT" if pid == 0 else ""
        print(f"  {name}{tag}")
        print(f"  {bar:<{bar_width}} {wins:>3} wins ({pct:5.1f}%)")
        print()

    # Crown the winner
    champion_pid  = max(win_counts, key=win_counts.get)
    champion_name = STRATEGY_NAMES[champion_pid]
    print("=" * 62)
    print(f"  CHAMPION: {champion_name}")
    print(f"  with {win_counts[champion_pid]} wins out of {n_games} games ({win_counts[champion_pid]/n_games*100:.1f}%)")
    if champion_pid == 0:
        print()
        print("  Welp. The monkey won. Chaos > strategy, apparently.")
        print("  In the words of the great philosophers: bruh.")
    else:
        gaps = sorted(win_counts.items(), key=lambda x: -x[1])
        if gaps[0][0] != 0:
            unhinged_wins = win_counts.get(0, 0)
            print()
            print(f"  The Unhinged all-in bot only won {unhinged_wins} time(s).")
            print(f"  Suflair GPT would have played the same way and gotten cooked. GGs.")
    print("=" * 62)


if __name__ == "__main__":
    print("Running 100 Texas Hold'em simulations...")
    print(f"  Starting chips per player: {STARTING_CHIPS}")
    print(f"  Blinds: {SMALL_BLIND}/{BIG_BLIND}")
    print()

    random.seed(42)   # reproducible chaos
    results = run_simulations(100)
    print_histogram(results, 100)
