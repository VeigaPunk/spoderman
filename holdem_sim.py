"""
Texas Hold'em Poker Simulation
6 players, 100 tournaments.
Player 1: The Maniac (always all-in)
Players 2-6: Elaborate strategic bots
"""

import random
from collections import Counter
from itertools import combinations
import sys

# ─── Card primitives ────────────────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

def card_str(c):
    suit_sym = {"c": "♣", "d": "♦", "h": "♥", "s": "♠"}
    return c[0] + suit_sym[c[1]]

# ─── Hand evaluation (7-card best 5) ────────────────────────────────────────

def hand_rank(cards):
    """Return a comparable tuple for a 5-card hand."""
    vals = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    straight = (vals == list(range(vals[0], vals[0] - 5, -1))) or (vals == [14, 5, 4, 3, 2])
    if straight and vals[0] == 14 and vals[1] == 5:
        vals = [5, 4, 3, 2, 1]
    counts = sorted(Counter(vals).values(), reverse=True)
    groups = sorted(Counter(vals).keys(), key=lambda v: (Counter(vals)[v], v), reverse=True)
    if flush and straight:  cat = 8
    elif counts[0] == 4:    cat = 7
    elif counts[:2] == [3, 2]: cat = 6
    elif flush:             cat = 5
    elif straight:          cat = 4
    elif counts[0] == 3:    cat = 3
    elif counts[:2] == [2, 2]: cat = 2
    elif counts[0] == 2:    cat = 1
    else:                   cat = 0
    return (cat,) + tuple(groups)

def best_hand(hole, board):
    best = None
    for combo in combinations(hole + board, 5):
        r = hand_rank(list(combo))
        if best is None or r > best:
            best = r
    return best

# ─── Monte Carlo equity estimation ──────────────────────────────────────────

def estimate_equity(hole, board, n_opponents, deck_remaining, simulations=40):
    wins = 0
    for _ in range(simulations):
        d = deck_remaining[:]
        random.shuffle(d)
        needed = 5 - len(board)
        sim_board = board + d[:needed]
        d = d[needed:]
        my_best = best_hand(hole, sim_board)
        beat = True
        for _ in range(n_opponents):
            opp_hole = d[:2]
            d = d[2:]
            if best_hand(opp_hole, sim_board) >= my_best:
                beat = False
                break
        if beat:
            wins += 1
    return wins / simulations

# ─── Preflop hand strength (Chen formula simplified) ────────────────────────

def preflop_strength(hole):
    r1, r2 = RANK_VAL[hole[0][0]], RANK_VAL[hole[1][0]]
    hi, lo = max(r1, r2), min(r1, r2)
    suited = hole[0][1] == hole[1][1]
    pair = (r1 == r2)
    score = hi
    if pair:
        score = max(hi * 2, 5)
    if suited:
        score += 2
    gap = hi - lo - 1
    if not pair:
        score -= max(0, gap - 1)
    if lo >= 11 and hi >= 11 and not pair:
        score += 1
    return score / 20.0  # normalize roughly 0..1

# ─── Pot odds helper ────────────────────────────────────────────────────────

def pot_odds(to_call, pot):
    if to_call == 0:
        return 1.0
    return pot / (pot + to_call)

# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGIES
# ═══════════════════════════════════════════════════════════════════════════

class Strategy:
    def decide(self, player, game_state):
        """Return ('fold'|'call'|'raise', amount)"""
        raise NotImplementedError


# ── Strategy 0: The Maniac ──────────────────────────────────────────────────
class ManiakAllin(Strategy):
    """if my_turn; then bet = All in; fi"""
    name = "☠ Maniac All-In"

    def decide(self, player, gs):
        return ('raise', player.chips)  # always shove


# ── Strategy 1: GTO-ish Equity Bot ─────────────────────────────────────────
class GTOEquityBot(Strategy):
    """Estimates equity via Monte Carlo, sizes bets proportionally."""
    name = "♟ GTO Equity Bot"

    def decide(self, player, gs):
        equity = estimate_equity(
            player.hole, gs['board'],
            gs['active_opponents'],
            gs['deck_remaining'], simulations=40
        )
        to_call = gs['to_call']
        pot = gs['pot']
        odds = pot_odds(to_call, pot)

        if equity < odds * 0.8:
            return ('fold', 0)
        elif equity > 0.65:
            bet = min(player.chips, int(pot * (equity * 1.5)))
            return ('raise', max(bet, to_call * 2))
        else:
            return ('call', to_call)


# ── Strategy 2: Tight-Aggressive (TAG) ─────────────────────────────────────
class TightAggressive(Strategy):
    """Plays only strong hands but bets them hard."""
    name = "🎯 Tight-Aggressive TAG"

    PREFLOP_THRESH = 0.55  # only play top ~35% of hands

    def decide(self, player, gs):
        board = gs['board']
        to_call = gs['to_call']
        pot = gs['pot']
        street = gs['street']

        if street == 'preflop':
            strength = preflop_strength(player.hole)
            if strength < self.PREFLOP_THRESH:
                return ('fold', 0) if to_call > 0 else ('call', 0)
            if strength > 0.75:
                raise_size = min(player.chips, pot * 3 + to_call * 2)
                return ('raise', int(raise_size))
            return ('call', to_call)

        # post-flop: use equity
        equity = estimate_equity(
            player.hole, board, gs['active_opponents'],
            gs['deck_remaining'], simulations=40
        )
        if equity < 0.35:
            return ('fold', 0)
        elif equity > 0.55:
            raise_size = min(player.chips, int(pot * 0.75))
            return ('raise', max(raise_size, to_call))
        return ('call', to_call)


# ── Strategy 3: Loose-Passive Caller (calling station) ─────────────────────
class CallingStation(Strategy):
    """Calls almost anything, rarely raises — bleeds slowly."""
    name = "📞 Calling Station"

    def decide(self, player, gs):
        to_call = gs['to_call']
        pot = gs['pot']
        # fold only if pot odds are terrible and hand is hopeless
        equity = estimate_equity(
            player.hole, gs['board'], gs['active_opponents'],
            gs['deck_remaining'], simulations=40
        )
        if equity < 0.12 and to_call > pot * 0.5:
            return ('fold', 0)
        if to_call > player.chips * 0.4 and equity < 0.25:
            return ('fold', 0)
        return ('call', to_call)


# ── Strategy 4: Position-Aware Bluffer ──────────────────────────────────────
class PositionBluffer(Strategy):
    """Bluffs aggressively in late position, folds early with weak hands."""
    name = "🎭 Position Bluffer"

    def decide(self, player, gs):
        pos = gs['position']          # 0=early, n-1=late (dealer)
        n_active = gs['n_active']
        relative_pos = pos / max(n_active - 1, 1)  # 0..1
        to_call = gs['to_call']
        pot = gs['pot']
        equity = estimate_equity(
            player.hole, gs['board'], gs['active_opponents'],
            gs['deck_remaining'], simulations=40
        )

        # late position aggression
        if relative_pos > 0.6:
            if equity > 0.3 or random.random() < 0.30:  # 30% bluff freq late
                bluff_size = min(player.chips, int(pot * 0.65))
                return ('raise', max(bluff_size, to_call))
        if equity < pot_odds(to_call, pot) * 0.7:
            return ('fold', 0)
        return ('call', to_call)


# ── Strategy 5: Pot-Control / Trapper ───────────────────────────────────────
class Trapper(Strategy):
    """Slow-plays big hands to keep opponents in, then bombs the river."""
    name = "🕷 Trapper"

    def decide(self, player, gs):
        street = gs['street']
        to_call = gs['to_call']
        pot = gs['pot']
        equity = estimate_equity(
            player.hole, gs['board'], gs['active_opponents'],
            gs['deck_remaining'], simulations=40
        )

        if equity > 0.80 and street in ('flop', 'turn'):
            # slow-play: just call to keep people in
            return ('call', to_call)
        if equity > 0.75 and street == 'river':
            # time to strike
            return ('raise', min(player.chips, int(pot * 1.2)))
        if equity > 0.55:
            size = min(player.chips, int(pot * 0.5))
            return ('raise', max(size, to_call))
        if equity < pot_odds(to_call, pot) * 0.75:
            return ('fold', 0)
        return ('call', to_call)


# ═══════════════════════════════════════════════════════════════════════════
#  PLAYER
# ═══════════════════════════════════════════════════════════════════════════

class Player:
    def __init__(self, pid, chips, strategy):
        self.pid = pid
        self.chips = chips
        self.strategy = strategy
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def __repr__(self):
        return f"P{self.pid}({self.strategy.name},{self.chips})"


# ═══════════════════════════════════════════════════════════════════════════
#  GAME ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class HoldEmGame:
    SMALL_BLIND = 10
    BIG_BLIND = 20

    def __init__(self, players):
        self.players = players
        self.pot = 0

    def _active(self):
        return [p for p in self.players if not p.folded and p.chips > 0]

    def _deal(self, deck, n):
        cards = deck[:n]
        del deck[:n]
        return cards

    def _collect_bet(self, player, amount):
        amount = min(amount, player.chips)
        player.chips -= amount
        player.bet_this_round += amount
        self.pot += amount
        if player.chips == 0:
            player.all_in = True
        return amount

    def _betting_round(self, deck, board, street, players_in_order):
        """Run one street of betting. Returns True if hand should continue."""
        current_bet = 0
        to_act = list(players_in_order)
        last_raiser = None
        acted = set()

        i = 0
        while i < len(to_act):
            p = to_act[i]
            if p.folded or p.all_in:
                i += 1
                continue

            to_call = max(0, current_bet - p.bet_this_round)
            active_opps = len([x for x in self._active() if x.pid != p.pid])

            gs = {
                'board': board[:],
                'pot': self.pot,
                'to_call': to_call,
                'street': street,
                'deck_remaining': deck[:],
                'active_opponents': active_opps,
                'position': players_in_order.index(p),
                'n_active': len([x for x in players_in_order if not x.folded]),
            }

            action, amount = p.strategy.decide(p, gs)

            if action == 'fold':
                p.folded = True
            elif action == 'call':
                self._collect_bet(p, to_call)
            elif action == 'raise':
                amount = max(amount, to_call + self.BIG_BLIND)
                self._collect_bet(p, amount)
                new_bet = p.bet_this_round
                if new_bet > current_bet:
                    current_bet = new_bet
                    last_raiser = p
                    # re-open action for everyone else
                    for pp in to_act:
                        if pp is not p and not pp.folded and not pp.all_in:
                            if pp not in to_act[i+1:]:
                                to_act.append(pp)

            acted.add(p.pid)
            i += 1

            still_in = [x for x in self.players if not x.folded and not x.all_in]
            if len(still_in) <= 1:
                break

        for p in self.players:
            p.bet_this_round = 0

        return len(self._active()) > 1

    def play_hand(self, dealer_idx):
        deck = make_deck()
        random.shuffle(deck)

        self.pot = 0
        for p in self.players:
            p.folded = False
            p.all_in = False
            p.hole = []
            p.bet_this_round = 0

        active = self._active()
        if len(active) < 2:
            return

        # Blinds
        n = len(active)
        sb_idx = (dealer_idx + 1) % n
        bb_idx = (dealer_idx + 2) % n
        self._collect_bet(active[sb_idx % n], self.SMALL_BLIND)
        active[sb_idx % n].bet_this_round = self.SMALL_BLIND
        self._collect_bet(active[bb_idx % n], self.BIG_BLIND)
        active[bb_idx % n].bet_this_round = self.BIG_BLIND

        # Deal hole cards
        for p in active:
            p.hole = self._deal(deck, 2)

        board = []

        # Pre-flop
        order = active[bb_idx % n + 1:] + active[:bb_idx % n + 1]
        self._betting_round(deck, board, 'preflop', order)

        if len(self._active()) <= 1:
            self._award_pot(board, deck)
            return

        # Flop
        board += self._deal(deck, 3)
        order = active[sb_idx % n:] + active[:sb_idx % n]
        self._betting_round(deck, board, 'flop', order)

        if len(self._active()) <= 1:
            self._award_pot(board, deck)
            return

        # Turn
        board += self._deal(deck, 1)
        self._betting_round(deck, board, 'turn', order)

        if len(self._active()) <= 1:
            self._award_pot(board, deck)
            return

        # River
        board += self._deal(deck, 1)
        self._betting_round(deck, board, 'river', order)
        self._award_pot(board, deck)

    def _award_pot(self, board, deck):
        contenders = [p for p in self.players if not p.folded]
        if not contenders:
            return
        if len(contenders) == 1:
            contenders[0].chips += self.pot
            self.pot = 0
            return

        while len(board) < 5:
            board.append(deck.pop(0))

        ranked = sorted(contenders, key=lambda p: best_hand(p.hole, board), reverse=True)
        # simple: winner takes all (side pots ignored for speed)
        ranked[0].chips += self.pot
        self.pot = 0


# ═══════════════════════════════════════════════════════════════════════════
#  TOURNAMENT
# ═══════════════════════════════════════════════════════════════════════════

STARTING_CHIPS = 1000
STRATEGIES = [
    ManiakAllin(),       # Player 1 - the fool
    GTOEquityBot(),      # Player 2
    TightAggressive(),   # Player 3
    CallingStation(),    # Player 4
    PositionBluffer(),   # Player 5
    Trapper(),           # Player 6
]

def run_tournament():
    """Run one full tournament until one player has all chips. Returns winner pid."""
    players = [Player(i + 1, STARTING_CHIPS, STRATEGIES[i]) for i in range(6)]
    game = HoldEmGame(players)
    dealer = 0
    hand_num = 0
    max_hands = 5000  # safety cap

    while hand_num < max_hands:
        alive = [p for p in players if p.chips > 0]
        if len(alive) == 1:
            return alive[0].pid
        game.play_hand(dealer % len(alive))
        dealer += 1
        hand_num += 1

        # escalate blinds every 100 hands
        if hand_num % 100 == 0:
            game.SMALL_BLIND = min(game.SMALL_BLIND * 2, 200)
            game.BIG_BLIND = min(game.BIG_BLIND * 2, 400)

    alive = [p for p in players if p.chips > 0]
    return max(alive, key=lambda p: p.chips).pid


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    N = 100
    print(f"Running {N} Texas Hold'em tournaments...\n")
    wins = Counter()

    for t in range(N):
        if (t + 1) % 10 == 0:
            print(f"  Simulated {t + 1}/{N} tournaments...", file=sys.stderr)
        winner = run_tournament()
        wins[winner] += 1

    print("\n" + "═" * 60)
    print("  TOURNAMENT RESULTS — Who Is The Rounder?")
    print("═" * 60)

    player_names = {i + 1: STRATEGIES[i].name for i in range(6)}
    max_wins = max(wins.values()) if wins else 1
    bar_width = 40

    print(f"\n{'Player':<5} {'Strategy':<28} {'Wins':>5}  Histogram")
    print("-" * 75)
    for pid in range(1, 7):
        w = wins.get(pid, 0)
        bar_len = int((w / max_wins) * bar_width)
        bar = "█" * bar_len
        pct = w / N * 100
        marker = " ← THE ROUNDER 🏆" if w == max_wins else ""
        print(f"  P{pid}  {player_names[pid]:<28} {w:>3}   {bar:<40} {pct:5.1f}%{marker}")

    print("\n" + "─" * 60)
    top_pid = max(wins, key=wins.get)
    print(f"\n  Winner Winner Chicken Dinner: Player {top_pid}")
    print(f"  {player_names[top_pid]}")
    print(f"  Won {wins[top_pid]} / {N} tournaments ({wins[top_pid]}%)")

    maniac_wins = wins.get(1, 0)
    print(f"\n  Player 1 (☠ Maniac All-In): {maniac_wins}/{N} wins ({maniac_wins}%)")
    if maniac_wins < 20:
        print("  Brainless shoving: humiliated. Strategy > chaos.")
    elif maniac_wins < 40:
        print("  Dumb luck gave the Maniac a few — but skill dominated.")
    else:
        print("  The chaos worked?! (statistical noise — run more sims)")

    print("\n" + "═" * 60)


if __name__ == "__main__":
    main()
