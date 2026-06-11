"""
Texas Hold'em 6-player simulation.
Player 1 : "Suflair GPT" — always goes all-in.
Players 2-6: five elaborate strategy bots.
100 tournaments, each starting with equal chips.
Prints a winner histogram at the end.
"""

import random
import itertools
from collections import Counter, defaultdict
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Card primitives
# ---------------------------------------------------------------------------
RANKS = list(range(2, 15))  # 2-14, where 14=Ace
SUITS = ["s", "h", "d", "c"]
RANK_NAMES = {2:"2",3:"3",4:"4",5:"5",6:"6",7:"7",8:"8",9:"9",10:"T",11:"J",12:"Q",13:"K",14:"A"}

Card = Tuple[int, str]   # (rank, suit)


def new_deck() -> List[Card]:
    deck = [(r, s) for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


# ---------------------------------------------------------------------------
# Hand evaluation  (returns a comparable tuple — higher is better)
# ---------------------------------------------------------------------------
def hand_rank(cards: List[Card]) -> Tuple:
    """Evaluate best 5-card hand from up to 7 cards."""
    best = None
    for combo in itertools.combinations(cards, 5):
        score = _score5(list(combo))
        if best is None or score > best:
            best = score
    return best


def _score5(cards: List[Card]) -> Tuple:
    ranks = sorted([c[0] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    is_flush = len(set(suits)) == 1

    # Straight detection (handle A-low)
    unique = sorted(set(ranks), reverse=True)
    is_straight = False
    straight_high = 0
    if len(unique) == 5:
        if unique[0] - unique[4] == 4:
            is_straight = True
            straight_high = unique[0]
        # A-2-3-4-5
        elif unique == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5

    counts = Counter(ranks)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda r: (counts[r], r), reverse=True)

    if is_straight and is_flush:
        return (8, straight_high)
    if freq[0] == 4:
        return (7, groups[0], groups[1])
    if freq[:2] == [3, 2]:
        return (6, groups[0], groups[1])
    if is_flush:
        return (5,) + tuple(ranks)
    if is_straight:
        return (4, straight_high)
    if freq[0] == 3:
        return (3, groups[0]) + tuple(groups[1:])
    if freq[:2] == [2, 2]:
        pair_ranks = sorted([g for g in groups[:2]], reverse=True)
        kicker = groups[2]
        return (2, pair_ranks[0], pair_ranks[1], kicker)
    if freq[0] == 2:
        return (1, groups[0]) + tuple(groups[1:])
    return (0,) + tuple(ranks)


# ---------------------------------------------------------------------------
# Monte-Carlo equity estimator (fast, sampled)
# ---------------------------------------------------------------------------
def estimate_equity(hole: List[Card], community: List[Card],
                    num_opponents: int, samples: int = 200) -> float:
    known = set(map(tuple, hole + community))
    remaining = [c for c in [(r, s) for r in RANKS for s in SUITS]
                 if tuple(c) not in known]
    wins = 0
    for _ in range(samples):
        deck = remaining[:]
        random.shuffle(deck)
        ptr = 0
        board = community[:]
        needed = 5 - len(board)
        board += deck[ptr:ptr + needed]
        ptr += needed
        my_best = hand_rank(hole + board)
        beat = False
        for _ in range(num_opponents):
            opp = deck[ptr:ptr + 2]
            ptr += 2
            if ptr > len(deck):
                break
            opp_best = hand_rank(opp + board)
            if opp_best >= my_best:
                beat = True
                break
        if not beat:
            wins += 1
    return wins / samples


# ---------------------------------------------------------------------------
# Player state
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, pid: int, chips: int, strategy_fn):
        self.pid = pid
        self.chips = chips
        self.strategy_fn = strategy_fn
        self.hole: List[Card] = []
        self.folded = False
        self.all_in = False
        self.current_bet = 0  # amount bet this street

    def reset_for_hand(self):
        self.hole = []
        self.folded = False
        self.all_in = False
        self.current_bet = 0

    def is_active(self):
        return not self.folded and not self.all_in and self.chips > 0


# ---------------------------------------------------------------------------
# Six strategies
# ---------------------------------------------------------------------------

def strategy_always_allin(player: Player, game_state: dict) -> str:
    """Player 1 / Suflair GPT: if my_turn then bet = ALL IN fi"""
    return "allin"


def strategy_tight_aggressive(player: Player, game_state: dict) -> str:
    """
    TAG — only plays strong hands; bets/raises aggressively when in.
    Pre-flop: plays top ~15% of hands.
    Post-flop: bets if equity > 0.55, folds otherwise.
    """
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    num_active = game_state["num_active_opponents"]

    if not community:  # pre-flop
        r1, r2 = player.hole[0][0], player.hole[1][0]
        suited = player.hole[0][1] == player.hole[1][1]
        hi, lo = max(r1, r2), min(r1, r2)
        # Tier 1: AA KK QQ JJ AKs AKo — always raise
        if hi >= 11 and lo >= 10:
            return "raise"
        if hi == 14 and lo >= 10:
            return "raise"
        # Tier 2: TT 99 AQs AJs KQs — raise
        if hi >= 12 and lo >= 9:
            return "raise" if suited else "call"
        if hi == 14 and lo >= 9 and suited:
            return "raise"
        # Tier 3: small pairs and suited connectors — call if cheap
        if hi == lo and hi >= 7:
            return "call" if call_amount <= player.chips * 0.1 else "fold"
        if suited and hi - lo == 1 and hi >= 9:
            return "call" if call_amount <= player.chips * 0.06 else "fold"
        return "fold"
    else:
        equity = estimate_equity(player.hole, community, num_active, samples=150)
        if equity > 0.65:
            return "raise"
        if equity > 0.45:
            return "call" if call_amount <= pot * 0.6 else "fold"
        return "fold"


def strategy_loose_passive(player: Player, game_state: dict) -> str:
    """
    Calling station — plays many hands, rarely raises, reluctant to fold.
    """
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    num_active = game_state["num_active_opponents"]

    if not community:
        r1, r2 = player.hole[0][0], player.hole[1][0]
        hi = max(r1, r2)
        # Fold only real trash out of position
        if hi < 7 and abs(r1 - r2) > 5:
            return "fold"
        return "call"
    else:
        equity = estimate_equity(player.hole, community, num_active, samples=100)
        if equity > 0.3:
            return "call" if call_amount <= player.chips * 0.4 else "fold"
        return "fold"


def strategy_position_aware(player: Player, game_state: dict) -> str:
    """
    Positional — plays more hands in late position, fewer in early.
    Uses pot odds + equity to decide sizing.
    """
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    position = game_state["position"]        # 0=earliest … n-1=latest (BTN/dealer)
    num_players = game_state["num_active_opponents"] + 1
    num_active = game_state["num_active_opponents"]
    is_late = position >= num_players - 2

    if not community:
        r1, r2 = player.hole[0][0], player.hole[1][0]
        hi, lo = max(r1, r2), min(r1, r2)
        suited = player.hole[0][1] == player.hole[1][1]

        premium = (hi >= 13 and lo >= 10) or (hi == 14 and lo >= 9)
        good    = (hi >= 11 and lo >= 8) or (suited and hi - lo <= 2 and hi >= 8)
        speculative = (hi == lo and hi >= 5) or (suited and hi >= 7)

        if premium:
            return "raise"
        if good:
            return "raise" if is_late else "call"
        if speculative and is_late:
            return "call" if call_amount <= player.chips * 0.07 else "fold"
        return "fold"
    else:
        equity = estimate_equity(player.hole, community, num_active, samples=150)
        pot_odds = call_amount / (pot + call_amount + 1e-9)
        if equity > pot_odds + 0.10:
            return "raise" if is_late and equity > 0.60 else "call"
        if equity > pot_odds:
            return "call"
        return "fold"


def strategy_gto_approx(player: Player, game_state: dict) -> str:
    """
    GTO-inspired — mixes bluffs probabilistically, uses blockers heuristic.
    Raises strong value, occasionally bluffs (33% of semi-bluff spots).
    """
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    num_active = game_state["num_active_opponents"]

    if not community:
        r1, r2 = player.hole[0][0], player.hole[1][0]
        hi, lo = max(r1, r2), min(r1, r2)
        suited = player.hole[0][1] == player.hole[1][1]

        if hi >= 12 and lo >= 10:          # value range
            return "raise"
        if hi == 14:                        # ace-x — mix
            return "raise" if lo >= 8 or suited else "call" if lo >= 5 else "fold"
        if hi == lo and hi >= 8:           # mid-high pairs
            return "raise"
        if suited and abs(hi - lo) <= 2 and hi >= 9:
            return "raise" if random.random() < 0.5 else "call"
        # bluff with low suited connectors occasionally
        if suited and abs(hi - lo) == 1 and hi >= 6:
            return "call" if random.random() < 0.3 else "fold"
        return "fold"
    else:
        equity = estimate_equity(player.hole, community, num_active, samples=150)
        if equity > 0.70:
            return "raise"
        if equity > 0.50:
            return "call"
        # semi-bluff or pure bluff with some freq
        if equity > 0.30 and random.random() < 0.25:
            return "raise"
        if equity > 0.20 and call_amount <= pot * 0.4:
            return "call"
        return "fold"


def strategy_adaptive_aggressor(player: Player, game_state: dict) -> str:
    """
    Adaptive — scales aggression to stack depth; pushes fold equity
    when short-stacked; plays more conservatively deep.
    """
    community = game_state["community"]
    call_amount = game_state["call_amount"]
    pot = game_state["pot"]
    num_active = game_state["num_active_opponents"]
    avg_stack = game_state["avg_stack"]

    stack_ratio = player.chips / (avg_stack + 1e-9)
    short = stack_ratio < 0.5
    deep  = stack_ratio > 1.8

    if not community:
        r1, r2 = player.hole[0][0], player.hole[1][0]
        hi, lo = max(r1, r2), min(r1, r2)
        suited = player.hole[0][1] == player.hole[1][1]

        if short:
            # shove or fold
            shove_hand = hi >= 12 or (hi == 14) or (hi == lo and hi >= 9) or \
                         (suited and hi >= 11)
            return "allin" if shove_hand else "fold"
        elif deep:
            # very selective deep-stack play
            premium = (hi >= 13 and lo >= 11) or (hi == 14 and lo >= 12)
            return "raise" if premium else ("call" if (hi >= 10 and suited) else "fold")
        else:
            # normal
            if hi >= 12 and lo >= 9:
                return "raise"
            if hi == 14 and lo >= 8:
                return "raise" if suited else "call"
            if hi == lo and hi >= 8:
                return "raise"
            if suited and hi - lo <= 2 and hi >= 9:
                return "call"
            return "fold"
    else:
        equity = estimate_equity(player.hole, community, num_active, samples=150)
        if short:
            return "allin" if equity > 0.35 else "fold"
        if equity > 0.60:
            return "raise"
        if equity > 0.40:
            return "call" if call_amount <= pot * 0.7 else "fold"
        return "fold"


STRATEGIES = [
    ("Suflair GPT (always all-in)", strategy_always_allin),
    ("Tight-Aggressive TAG",        strategy_tight_aggressive),
    ("Loose-Passive Calling Station", strategy_loose_passive),
    ("Position-Aware Pro",          strategy_position_aware),
    ("GTO Approximator",            strategy_gto_approx),
    ("Adaptive Stack Aggressor",    strategy_adaptive_aggressor),
]


# ---------------------------------------------------------------------------
# Betting engine
# ---------------------------------------------------------------------------
BIG_BLIND = 20

def run_betting_round(players: List[Player], pot: int, community: List[Card],
                      dealer_idx: int, preflop: bool = False) -> int:
    """
    Simple betting loop. Returns updated pot.
    'current_bet' on each player is the total they've put in this street.
    """
    active = [p for p in players if not p.folded and not p.all_in and p.chips > 0]
    if len(active) <= 1:
        return pot

    # Determine start order and initial bet
    street_bet = 0  # highest bet so far this street
    if preflop:
        # blinds
        sb_idx = (dealer_idx + 1) % len(players)
        bb_idx = (dealer_idx + 2) % len(players)
        for i, idx in enumerate([sb_idx, bb_idx]):
            p = players[idx]
            blind = BIG_BLIND // 2 if i == 0 else BIG_BLIND
            amt = min(blind, p.chips)
            p.chips -= amt
            p.current_bet += amt
            pot += amt
            if p.chips == 0:
                p.all_in = True
        street_bet = BIG_BLIND
        # action starts left of BB
        start_idx = (bb_idx + 1) % len(players)
    else:
        start_idx = (dealer_idx + 1) % len(players)

    # Build ordered action list
    order = []
    idx = start_idx
    for _ in range(len(players)):
        p = players[idx]
        if not p.folded and not p.all_in and p.chips > 0:
            order.append(p)
        idx = (idx + 1) % len(players)

    if not order:
        return pot

    acted = set()
    queue = list(order)
    last_aggressor = None

    while queue:
        p = queue.pop(0)
        if p.folded or p.all_in or p.chips == 0:
            continue
        if p.pid in acted and p.pid != last_aggressor:
            # Everyone acted and no new raise — stop
            # but we need to let players who faced a raise act again
            pass

        call_amount = max(0, street_bet - p.current_bet)

        num_active_opponents = sum(
            1 for x in players if not x.folded and not x.all_in and x.pid != p.pid
        )
        avg_stack = (sum(x.chips for x in players if not x.folded) /
                     max(1, sum(1 for x in players if not x.folded)))

        position = order.index(p) if p in order else 0

        game_state = {
            "community": community,
            "call_amount": call_amount,
            "pot": pot,
            "position": position,
            "num_active_opponents": num_active_opponents,
            "avg_stack": avg_stack,
            "street_bet": street_bet,
            "player_chips": p.chips,
        }

        action = p.strategy_fn(p, game_state)

        if action == "fold":
            p.folded = True
            acted.add(p.pid)

        elif action == "call":
            amount = min(call_amount, p.chips)
            p.chips -= amount
            p.current_bet += amount
            pot += amount
            if p.chips == 0:
                p.all_in = True
            acted.add(p.pid)

        elif action == "raise":
            # Raise to 3x current bet (or pot-sized), capped at chips
            raise_to = max(street_bet * 3, street_bet + BIG_BLIND * 2)
            total_needed = raise_to - p.current_bet
            amount = min(total_needed, p.chips)
            p.chips -= amount
            p.current_bet += amount
            pot += amount
            new_bet_level = p.current_bet
            if new_bet_level > street_bet:
                street_bet = new_bet_level
                last_aggressor = p.pid
                # Re-queue everyone else who hasn't folded
                for other in players:
                    if (not other.folded and not other.all_in
                            and other.chips > 0 and other.pid != p.pid
                            and other not in queue):
                        queue.append(other)
            if p.chips == 0:
                p.all_in = True
            acted.add(p.pid)

        elif action == "allin":
            amount = p.chips
            p.chips = 0
            p.current_bet += amount
            pot += amount
            if amount + p.current_bet - amount > street_bet:
                street_bet = p.current_bet
                last_aggressor = p.pid
                for other in players:
                    if (not other.folded and not other.all_in
                            and other.chips > 0 and other.pid != p.pid
                            and other not in queue):
                        queue.append(other)
            p.all_in = True
            acted.add(p.pid)

    return pot


# ---------------------------------------------------------------------------
# Showdown
# ---------------------------------------------------------------------------
def showdown(players: List[Player], community: List[Card], pot: int):
    """Award pot to best hand(s) among non-folded players."""
    contenders = [p for p in players if not p.folded]
    if not contenders:
        return
    if len(contenders) == 1:
        contenders[0].chips += pot
        return

    scored = [(hand_rank(p.hole + community), p) for p in contenders]
    best_score = max(s for s, _ in scored)
    winners = [p for s, p in scored if s == best_score]
    share = pot // len(winners)
    remainder = pot - share * len(winners)
    for w in winners:
        w.chips += share
    if remainder:
        winners[0].chips += remainder  # give leftover to first winner


# ---------------------------------------------------------------------------
# Single hand
# ---------------------------------------------------------------------------
def play_hand(players: List[Player], dealer_idx: int) -> int:
    """Play one hand. Returns dealer_idx for next hand."""
    deck = new_deck()
    community: List[Card] = []

    for p in players:
        p.reset_for_hand()
        if p.chips > 0:
            p.hole = [deck.pop(), deck.pop()]

    pot = 0
    alive = [p for p in players if p.chips > 0]
    if len(alive) <= 1:
        return dealer_idx

    # Pre-flop
    pot = run_betting_round(players, pot, community, dealer_idx, preflop=True)
    remaining = [p for p in players if not p.folded and p.chips >= 0]
    if sum(1 for p in players if not p.folded) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % len(players)

    # Flop
    community += [deck.pop(), deck.pop(), deck.pop()]
    for p in players:
        p.current_bet = 0
    pot = run_betting_round(players, pot, community, dealer_idx)
    if sum(1 for p in players if not p.folded) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % len(players)

    # Turn
    community.append(deck.pop())
    for p in players:
        p.current_bet = 0
    pot = run_betting_round(players, pot, community, dealer_idx)
    if sum(1 for p in players if not p.folded) <= 1:
        showdown(players, community, pot)
        return (dealer_idx + 1) % len(players)

    # River
    community.append(deck.pop())
    for p in players:
        p.current_bet = 0
    pot = run_betting_round(players, pot, community, dealer_idx)

    showdown(players, community, pot)
    return (dealer_idx + 1) % len(players)


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------
STARTING_CHIPS = 1000

def run_tournament() -> int:
    """Run one tournament. Returns pid (1-indexed) of winner."""
    players = [Player(i + 1, STARTING_CHIPS, STRATEGIES[i][1])
               for i in range(6)]
    dealer_idx = 0
    max_hands = 2000

    for _ in range(max_hands):
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid

        # Advance dealer to a player still alive
        while players[dealer_idx].chips == 0:
            dealer_idx = (dealer_idx + 1) % len(players)

        dealer_idx = play_hand(players, dealer_idx)
        dealer_idx = dealer_idx % len(players)

    # Fallback: chip leader
    return max(players, key=lambda p: p.chips).pid


# ---------------------------------------------------------------------------
# 100 simulations + histogram
# ---------------------------------------------------------------------------
def run_simulations(n: int = 100):
    print(f"\nRunning {n} Texas Hold'em tournaments…\n")
    wins: Counter = Counter()

    for i in range(n):
        if (i + 1) % 10 == 0:
            print(f"  Completed {i+1}/{n} tournaments…")
        winner = run_tournament()
        wins[winner] += 1

    print("\n" + "=" * 60)
    print("  WINNER WINNER CHICKEN DINNER — TOURNAMENT RESULTS")
    print("=" * 60)
    print(f"\n  {'Player':<36} {'Wins':>5}  {'Bar'}")
    print(f"  {'-'*36}  {'-'*5}  {'-'*25}")

    max_wins = max(wins.values()) if wins else 1
    bar_width = 40

    for pid, (name, _) in enumerate(STRATEGIES, start=1):
        count = wins.get(pid, 0)
        bar_len = int(bar_width * count / max_wins)
        bar = "█" * bar_len
        pct = count / n * 100
        label = f"P{pid}: {name}"
        marker = " ← Suflair GPT" if pid == 1 else ""
        print(f"  {label:<36} {count:>4}x  {bar} {pct:.1f}%{marker}")

    print()
    champion_pid = wins.most_common(1)[0][0]
    champion_name = STRATEGIES[champion_pid - 1][0]
    print(f"  🏆  Champion: P{champion_pid} — {champion_name}")
    print(f"      ({wins[champion_pid]} wins / {n} tournaments = "
          f"{wins[champion_pid]/n*100:.1f}%)")
    print()

    suflair_wins = wins.get(1, 0)
    print(f"  💀  Suflair GPT (always all-in): {suflair_wins} wins / {n} "
          f"= {suflair_wins/n*100:.1f}% — sufficiently humiliated.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    random.seed(42)
    run_simulations(100)
