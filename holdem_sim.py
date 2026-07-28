"""
Texas Hold'em Poker Simulation
6 Players, 100 Tournaments, Winner Histogram

Player 1: AlwaysAllIn (simple) - the degen
Players 2-6: 5 elaborate strategies
"""

import random
from collections import Counter
from itertools import combinations

# ──────────────────────────────────────────────
# Card primitives
# ──────────────────────────────────────────────

SUITS = ['s', 'h', 'd', 'c']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}


class Card:
    __slots__ = ('rank', 'suit', 'value')

    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
        self.value = RANK_VAL[rank]

    def __repr__(self):
        return f"{self.rank}{self.suit}"


class Deck:
    def __init__(self):
        self.cards = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)

    def deal(self, n=1):
        out, self.cards = self.cards[:n], self.cards[n:]
        return out


# ──────────────────────────────────────────────
# Hand evaluator  (best 5 from N cards)
# ──────────────────────────────────────────────

def _score5(cards):
    vals = sorted([c.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    uniq = sorted(set(vals), reverse=True)
    is_str8 = False
    str8_hi = 0
    if len(uniq) == 5 and uniq[0] - uniq[4] == 4:
        is_str8, str8_hi = True, uniq[0]
    elif uniq == [14, 5, 4, 3, 2]:
        is_str8, str8_hi = True, 5
        vals = [5, 4, 3, 2, 1]

    cnt = Counter(vals)
    groups = sorted(cnt, key=lambda x: (cnt[x], x), reverse=True)
    freqs = [cnt[g] for g in groups]

    if is_str8 and is_flush:
        return (8, [str8_hi])
    if freqs[0] == 4:
        return (7, groups)
    if freqs[:2] == [3, 2]:
        return (6, groups)
    if is_flush:
        return (5, vals)
    if is_str8:
        return (4, [str8_hi])
    if freqs[0] == 3:
        return (3, groups)
    if freqs[:2] == [2, 2]:
        return (2, groups)
    if freqs[0] == 2:
        return (1, groups)
    return (0, vals)


def best_hand(cards):
    best = None
    for combo in combinations(cards, 5):
        s = _score5(list(combo))
        if best is None or s > best:
            best = s
    return best


# ──────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────

class Strategy:
    name = "Base"

    def decide(self, player, gs):
        """Return ('fold'|'check'|'call'|'raise', amount)."""
        raise NotImplementedError


# ── Strategy 0 ─────────────────────────────────
class AlwaysAllIn(Strategy):
    """Player 1's galaxy-brain play: shove every single hand."""
    name = "AlwaysAllIn"

    def decide(self, player, gs):
        return ('raise', player.chips)


# ── Strategy 1 ─────────────────────────────────
class TightAggressive(Strategy):
    """
    TAG: Fold most hands pre-flop, but when you play, play hard.
    Pre-flop: only premium pairs (TT+) and broadway combinations.
    Post-flop: value-bet made hands, fold marginal ones to heat.
    """
    name = "Tight-Aggressive"

    _PREMIUM = frozenset([
        ('A','A'), ('K','K'), ('Q','Q'), ('J','J'), ('T','T'),
        ('A','K'), ('A','Q'), ('K','Q'),
    ])

    def _preflop_tier(self, hole):
        ranks = tuple(sorted([c.rank for c in hole],
                              key=lambda r: RANK_VAL[r], reverse=True))
        if ranks in self._PREMIUM:
            return 'premium'
        vals = sorted([c.value for c in hole], reverse=True)
        pair = vals[0] == vals[1]
        suited = hole[0].suit == hole[1].suit
        if pair and vals[0] >= 7:
            return 'good'
        if suited and abs(vals[0] - vals[1]) <= 2 and vals[0] >= 9:
            return 'speculative'
        return 'trash'

    def decide(self, player, gs):
        ca = gs['call_amount']
        pot = gs['pot']
        bb = gs['big_blind']
        comm = gs['community']
        phase = gs['phase']

        if phase == 'preflop':
            tier = self._preflop_tier(player.hole)
            if tier == 'premium':
                return ('raise', min(player.chips, max(bb * 4, pot // 2 + ca)))
            if tier == 'good':
                if ca == 0:
                    return ('raise', min(player.chips, bb * 3))
                if ca <= bb * 3:
                    return ('call', ca)
                return ('fold', 0)
            if tier == 'speculative':
                if ca <= bb * 2:
                    return ('call', ca)
                return ('fold', 0)
            if ca == 0:
                return ('check', 0)
            return ('fold', 0)

        rank, _ = best_hand(player.hole + comm)
        if rank >= 6:          # Full house+
            return ('raise', min(player.chips, pot))
        if rank >= 4:          # Straight+
            if ca == 0:
                return ('raise', min(player.chips, pot // 2))
            if ca <= player.chips * 0.35:
                return ('call', ca)
            return ('fold', 0)
        if rank >= 2:          # Two pair+
            if ca == 0:
                return ('check', 0)
            if ca <= player.chips * 0.15:
                return ('call', ca)
            return ('fold', 0)
        if ca == 0:
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 2 ─────────────────────────────────
class LooseAggressive(Strategy):
    """
    LAG: Play a wide range, apply constant pressure with big bets.
    Continuation bets almost every flop. Bluffs frequently.
    Position matters a lot — wider range in late position.
    """
    name = "Loose-Aggressive"

    def _hand_score(self, hole):
        vals = sorted([c.value for c in hole], reverse=True)
        suited = hole[0].suit == hole[1].suit
        gap = abs(vals[0] - vals[1])
        score = vals[0] + vals[1] * 0.6
        if vals[0] == vals[1]:
            score += vals[0]
        if suited:
            score += 3
        if gap == 0:
            score += 2
        elif gap == 1:
            score += 1
        return score

    def decide(self, player, gs):
        ca = gs['call_amount']
        pot = gs['pot']
        bb = gs['big_blind']
        comm = gs['community']
        phase = gs['phase']
        position = gs.get('position', 0.5)  # 0=early, 1=late

        if phase == 'preflop':
            score = self._hand_score(player.hole)
            # Dynamic threshold: looser in position
            threshold = 18 - position * 7
            if score >= threshold:
                bet = min(player.chips, bb * (3 + int(position * 2)))
                return ('raise', max(bet, ca + bb))
            if score >= threshold - 5:
                if ca <= bb * 3:
                    return ('call', ca)
            if ca == 0:
                return ('check', 0)
            # Occasional squeeze bluff
            if random.random() < 0.2 and ca <= bb * 4:
                return ('raise', min(player.chips, ca * 3 + pot // 3))
            return ('fold', 0)

        rank, _ = best_hand(player.hole + comm)
        if rank >= 3:          # Trips or better — bet big
            bet = min(player.chips, max(int(pot * 0.9), bb))
            return ('raise', bet)
        if rank >= 1:          # Pair — c-bet often
            if ca == 0:
                if random.random() < 0.65:
                    return ('raise', min(player.chips, max(int(pot * 0.6), bb)))
                return ('check', 0)
            if ca <= player.chips * 0.20:
                return ('call', ca)
            return ('fold', 0)
        # No pair — bluff from position, check/fold out of it
        if ca == 0:
            if position > 0.55 and random.random() < 0.45:
                return ('raise', min(player.chips, max(int(pot * 0.55), bb)))
            return ('check', 0)
        if ca <= bb * 2 and random.random() < 0.3:
            return ('call', ca)
        return ('fold', 0)


# ── Strategy 3 ─────────────────────────────────
class GTOInspired(Strategy):
    """
    GTO-ish: pot-odds + fast equity estimate + mixed frequencies.
    Calls when EV > 0, raises with strong equity, bluffs at
    balanced frequencies to avoid being exploitable.
    """
    name = "GTO-Inspired"

    def _equity_preflop(self, hole, n_opp):
        vals = sorted([c.value for c in hole], reverse=True)
        suited = hole[0].suit == hole[1].suit
        pair = vals[0] == vals[1]

        if pair and vals[0] >= 12:
            eq = 0.78
        elif pair and vals[0] >= 8:
            eq = 0.58
        elif pair:
            eq = 0.50
        elif vals[0] >= 13 and vals[1] >= 11:
            eq = 0.63
        elif vals[0] >= 12 and vals[1] >= 10:
            eq = 0.58
        elif suited and abs(vals[0]-vals[1]) <= 2 and vals[0] >= 8:
            eq = 0.46
        elif vals[0] >= 11:
            eq = 0.50
        else:
            eq = 0.38
        # Multi-way penalty
        eq = max(0.1, eq - (n_opp - 1) * 0.07)
        return eq

    def _equity_postflop(self, hole, comm, n_opp):
        """Quick 40-trial Monte Carlo."""
        deck = [Card(r, s) for s in SUITS for r in RANKS]
        used = {(c.rank, c.suit) for c in hole + comm}
        avail = [c for c in deck if (c.rank, c.suit) not in used]

        need = (5 - len(comm)) + 2 * n_opp
        if len(avail) < need:
            return 0.5

        wins = 0
        trials = 40
        my_score = best_hand(hole + comm)

        for _ in range(trials):
            sample = random.sample(avail, need)
            runout = sample[:5-len(comm)]
            my_full = best_hand(hole + comm + runout)
            beat = False
            for i in range(n_opp):
                opp_h = sample[5-len(comm) + i*2: 5-len(comm) + i*2+2]
                opp_s = best_hand(opp_h + comm + runout)
                if opp_s >= my_full:
                    beat = True
                    break
            wins += not beat
        return wins / trials

    def decide(self, player, gs):
        ca = gs['call_amount']
        pot = gs['pot']
        bb = gs['big_blind']
        comm = gs['community']
        phase = gs['phase']
        n_opp = max(1, gs['active_opponents'])

        if phase == 'preflop':
            eq = self._equity_preflop(player.hole, n_opp)
        else:
            eq = self._equity_postflop(player.hole, comm, n_opp)

        if ca == 0:
            if eq > 0.58:
                bet = min(player.chips, max(int(pot * 0.70), bb))
                return ('raise', bet)
            if eq > 0.42:
                if random.random() < (eq - 0.42) * 4:   # Freq proportional
                    bet = min(player.chips, max(int(pot * 0.50), bb))
                    return ('raise', bet)
                return ('check', 0)
            # Bluff range at low equity
            if eq < 0.28 and random.random() < 0.22:
                return ('raise', min(player.chips, max(int(pot * 0.55), bb)))
            return ('check', 0)

        # Facing a bet: compute EV
        total_pot = pot + ca
        ev = eq * total_pot - ca
        if ev > 0:
            if eq > 0.62:
                raise_to = min(player.chips, ca * 2 + int(pot * 0.5))
                return ('raise', raise_to)
            return ('call', ca)
        # Occasional bluff-raise even when behind
        if random.random() < 0.08 and ca <= player.chips * 0.15:
            return ('raise', min(player.chips, int(pot * 0.6)))
        return ('fold', 0)


# ── Strategy 4 ─────────────────────────────────
class RockSolid(Strategy):
    """
    Rock: ultra-tight, passive. Only plays the nuts or near-nuts.
    Won't bluff. Very predictable, but rarely loses big pots.
    Surviving in tournaments by avoiding bad spots.
    """
    name = "Rock"

    _ULTRA_PREMIUM = frozenset([
        ('A','A'), ('K','K'), ('Q','Q'), ('J','J'),
        ('A','K'), ('A','Q'),
    ])

    def _premium_preflop(self, hole):
        ranks = tuple(sorted([c.rank for c in hole],
                              key=lambda r: RANK_VAL[r], reverse=True))
        return ranks in self._ULTRA_PREMIUM

    def decide(self, player, gs):
        ca = gs['call_amount']
        pot = gs['pot']
        bb = gs['big_blind']
        comm = gs['community']
        phase = gs['phase']

        if phase == 'preflop':
            if self._premium_preflop(player.hole):
                if ca == 0:
                    return ('raise', min(player.chips, bb * 4))
                # Reraise or call
                if ca <= player.chips * 0.40:
                    return ('raise', min(player.chips, ca * 3))
                return ('call', min(ca, player.chips))
            if ca == 0:
                return ('check', 0)
            return ('fold', 0)

        rank, _ = best_hand(player.hole + comm)
        if rank >= 7:          # Quads or better
            return ('raise', min(player.chips, pot * 2))
        if rank >= 5:          # Flush+
            if ca == 0:
                return ('raise', min(player.chips, int(pot * 0.7)))
            if ca <= player.chips * 0.5:
                return ('call', ca)
            return ('fold', 0)
        if rank >= 3:          # Trips+
            if ca == 0:
                return ('raise', min(player.chips, int(pot * 0.5)))
            if ca <= player.chips * 0.25:
                return ('call', ca)
            return ('fold', 0)
        if rank >= 1:          # Pair
            if ca == 0:
                return ('check', 0)
            if ca <= player.chips * 0.08:
                return ('call', ca)
            return ('fold', 0)
        if ca == 0:
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 5 ─────────────────────────────────
class PositionAware(Strategy):
    """
    Position-Aware Adaptive: reads table dynamics and adjusts.
    Short-stack mode (push/fold). Exploits tight players by
    stealing, adjusts sizing to SPR. Most sophisticated of the 5.
    """
    name = "Position-Aware"

    def _preflop_score(self, hole):
        vals = sorted([c.value for c in hole], reverse=True)
        suited = hole[0].suit == hole[1].suit
        pair = vals[0] == vals[1]
        gap = abs(vals[0] - vals[1])
        s = vals[0] + vals[1] * 0.55
        if pair:
            s += vals[0] * 1.4
        if suited:
            s += 3
        if gap <= 1:
            s += 2
        elif gap <= 3:
            s += 1
        return s

    def decide(self, player, gs):
        ca = gs['call_amount']
        pot = gs['pot']
        bb = gs['big_blind']
        comm = gs['community']
        phase = gs['phase']
        position = gs.get('position', 0.5)
        n_opp = max(1, gs['active_opponents'])

        # ── Push-fold mode when short-stacked ──
        if player.chips <= bb * 12:
            if phase == 'preflop':
                score = self._preflop_score(player.hole)
                threshold = 20 - position * 6  # wider shove range in position
                if score >= threshold:
                    return ('raise', player.chips)
                if ca == 0:
                    return ('check', 0)
                return ('fold', 0)

        # ── Pre-flop normal ──
        if phase == 'preflop':
            score = self._preflop_score(player.hole)
            raise_thresh = 21 - position * 7
            call_thresh = 15 - position * 4

            if score >= raise_thresh:
                sizing = int(bb * (2.5 + position * 1.5) + pot * 0.1)
                return ('raise', min(player.chips, sizing))
            if score >= call_thresh:
                if ca == 0:
                    return ('check', 0)
                if ca <= bb * 4:
                    return ('call', ca)
                return ('fold', 0)
            if ca == 0:
                return ('check', 0)
            # Steal from late position
            if position > 0.65 and ca <= bb and random.random() < 0.35:
                return ('raise', min(player.chips, bb * 3))
            return ('fold', 0)

        # ── Post-flop ──
        rank, _ = best_hand(player.hole + comm)
        spr = player.chips / max(pot, 1)

        if rank >= 5:          # Flush or better — build the pot
            if ca == 0:
                sizing = int(pot * (0.6 + position * 0.2))
                return ('raise', min(player.chips, max(sizing, bb)))
            return ('call', min(ca, player.chips))

        if rank >= 3:          # Trips+ — value bet, don't slowplay
            if ca == 0:
                sizing = int(pot * (0.5 + position * 0.15))
                return ('raise', min(player.chips, max(sizing, bb)))
            if ca <= player.chips * 0.3:
                if random.random() < 0.75:
                    return ('raise', min(player.chips, ca + int(pot * 0.35)))
                return ('call', ca)
            return ('fold', 0)

        if rank >= 1:          # Pair
            if ca == 0:
                if position > 0.6 and spr > 3 and random.random() < 0.5:
                    return ('raise', min(player.chips, int(pot * 0.45)))
                return ('check', 0)
            if ca <= player.chips * 0.14:
                return ('call', ca)
            return ('fold', 0)

        # Nothing — position bluffs only
        if ca == 0:
            if position > 0.72 and random.random() < 0.38:
                return ('raise', min(player.chips, int(pot * 0.52)))
            return ('check', 0)
        if ca <= bb * 1.5 and position > 0.8 and random.random() < 0.25:
            return ('call', ca)
        return ('fold', 0)


# ──────────────────────────────────────────────
# Player object
# ──────────────────────────────────────────────

class Player:
    def __init__(self, pid, strategy, chips):
        self.pid = pid
        self.strategy = strategy
        self.name = strategy.name
        self.chips = chips
        self.hole = []
        self.bet = 0        # current street bet
        self.folded = False
        self.allin = False

    def reset(self):
        self.hole = []
        self.bet = 0
        self.folded = False
        self.allin = False


# ──────────────────────────────────────────────
# Betting round (queue-based, clean termination)
# ──────────────────────────────────────────────

def betting_round(active, phase, comm, pot, start_idx, big_blind, is_preflop):
    """
    active: list of Player in seat order.
    start_idx: index into active[] of first actor.
    Returns updated pot.
    """
    n = len(active)
    max_bet = max(p.bet for p in active)

    # Build ordered action queue
    order = [(start_idx + i) % n for i in range(n)]
    queue = [i for i in order if not active[i].folded and not active[i].allin]

    acted_since_last_raise = set()

    while queue:
        idx = queue.pop(0)
        p = active[idx]

        if p.folded or p.allin:
            continue

        ca = max(0, max_bet - p.bet)
        ca = min(ca, p.chips)

        # Build game state
        pos_rank = order.index(idx) / max(len(order) - 1, 1)
        gs = {
            'phase': phase,
            'community': comm,
            'pot': pot,
            'call_amount': ca,
            'big_blind': big_blind,
            'active_opponents': sum(1 for x in active if not x.folded and x is not p),
            'position': pos_rank,
        }

        action, amount = p.strategy.decide(p, gs)

        if action == 'fold':
            p.folded = True
            if sum(1 for x in active if not x.folded) == 1:
                return pot
        elif action in ('check', 'call'):
            p.chips -= ca
            p.bet += ca
            pot += ca
            if p.chips == 0:
                p.allin = True
            acted_since_last_raise.add(idx)
        elif action == 'raise':
            # Pay call first
            p.chips -= ca
            p.bet += ca
            pot += ca
            extra = min(max(int(amount), 1), p.chips)
            if extra > 0:
                p.chips -= extra
                p.bet += extra
                pot += extra
                max_bet = p.bet
                acted_since_last_raise = {idx}
                # Re-queue everyone not folded/allin who isn't this player
                queue = [
                    (idx + 1 + i) % n
                    for i in range(n - 1)
                    if not active[(idx + 1 + i) % n].folded
                    and not active[(idx + 1 + i) % n].allin
                    and (idx + 1 + i) % n != idx
                ]
            else:
                acted_since_last_raise.add(idx)
            if p.chips == 0:
                p.allin = True

        # Termination: everyone eligible has acted and matched
        eligible = [i for i, x in enumerate(active)
                    if not x.folded and not x.allin]
        if all(active[i].bet >= max_bet for i in eligible):
            if all(i in acted_since_last_raise for i in eligible):
                break

    return pot


# ──────────────────────────────────────────────
# Single hand of Hold'em
# ──────────────────────────────────────────────

def play_hand(players, dealer_idx, big_blind):
    """
    players: only those with chips > 0 (seated).
    Returns pid of hand winner (chips already updated).
    """
    n = len(players)
    for p in players:
        p.reset()

    deck = Deck()
    comm = []
    pot = 0

    # Post blinds
    sb_i = (dealer_idx + 1) % n
    bb_i = (dealer_idx + 2) % n

    small = big_blind // 2
    sb_amt = min(small, players[sb_i].chips)
    bb_amt = min(big_blind, players[bb_i].chips)

    players[sb_i].chips -= sb_amt
    players[sb_i].bet = sb_amt
    if players[sb_i].chips == 0:
        players[sb_i].allin = True
    pot += sb_amt

    players[bb_i].chips -= bb_amt
    players[bb_i].bet = bb_amt
    if players[bb_i].chips == 0:
        players[bb_i].allin = True
    pot += bb_amt

    # Deal hole cards
    for p in players:
        p.hole = deck.deal(2)

    # ── Pre-flop ──
    utg = (dealer_idx + 3) % n
    pot = betting_round(players, 'preflop', comm, pot, utg, big_blind, True)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return alive[0].pid

    # ── Flop ──
    comm += deck.deal(3)
    for p in players:
        p.bet = 0
    first_after = (dealer_idx + 1) % n
    pot = betting_round(players, 'flop', comm, pot, first_after, big_blind, False)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return alive[0].pid

    # ── Turn ──
    comm += deck.deal(1)
    for p in players:
        p.bet = 0
    pot = betting_round(players, 'turn', comm, pot, first_after, big_blind, False)

    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return alive[0].pid

    # ── River ──
    comm += deck.deal(1)
    for p in players:
        p.bet = 0
    pot = betting_round(players, 'river', comm, pot, first_after, big_blind, False)

    # ── Showdown ──
    alive = [p for p in players if not p.folded]
    if len(alive) == 1:
        alive[0].chips += pot
        return alive[0].pid

    scored = [(best_hand(p.hole + comm), p) for p in alive]
    best = max(scored, key=lambda x: x[0])[0]
    winners = [p for s, p in scored if s == best]

    share = pot // len(winners)
    for w in winners:
        w.chips += share
    winners[0].chips += pot - share * len(winners)  # leftover pennies
    return winners[0].pid


# ──────────────────────────────────────────────
# Tournament
# ──────────────────────────────────────────────

def run_tournament(strategies, starting_chips=1500, init_bb=20, max_hands=600):
    players = [Player(i + 1, s, starting_chips) for i, s in enumerate(strategies)]
    bb = init_bb
    dealer = 0

    for hand_num in range(max_hands):
        seated = [p for p in players if p.chips > 0]
        if len(seated) <= 1:
            break

        # Escalate blinds every 60 hands to avoid stalling
        if hand_num > 0 and hand_num % 60 == 0:
            bb = min(bb * 2, starting_chips // 3)

        play_hand(seated, dealer % len(seated), bb)
        dealer += 1

    alive = [p for p in players if p.chips > 0]
    if not alive:
        return None
    return max(alive, key=lambda p: p.chips).pid


# ──────────────────────────────────────────────
# Histogram printer
# ──────────────────────────────────────────────

HAND_LABELS = {
    0: 'High Card', 1: 'Pair', 2: 'Two Pair', 3: 'Trips',
    4: 'Straight', 5: 'Flush', 6: 'Full House',
    7: 'Quads', 8: 'Straight Flush',
}


def print_histogram(wins, names, n):
    BAR = 42
    mx = max(wins.values()) if wins else 1

    lines = []
    lines.append("")
    lines.append("╔══════════════════════════════════════════════════════════════════╗")
    lines.append("║        TEXAS HOLD'EM — 100 TOURNAMENT SIMULATION RESULTS        ║")
    lines.append("║             Who's the last player standing?                      ║")
    lines.append("╚══════════════════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  {'Player':<26}  {'Wins':>4}   {'%':>5}   Histogram")
    lines.append("  " + "─" * 65)

    MARKER = "█"
    HALF   = "▌"

    for pid in sorted(names):
        name = names[pid]
        w = wins.get(pid, 0)
        pct = w / n * 100
        bar_f = w / mx * BAR
        full  = int(bar_f)
        half  = 1 if (bar_f - full) >= 0.5 else 0
        bar = MARKER * full + (HALF if half else "")

        tag = "  ← THE DEGEN" if pid == 1 else ""
        label = f"P{pid}: {name}{tag}"
        lines.append(f"  {label:<33}  {w:>3}   {pct:>4.1f}%   {bar}")

    lines.append("")
    lines.append("  " + "─" * 65)

    # Champion
    champion_pid = max(wins, key=wins.get) if wins else None
    if champion_pid:
        champ_name = names[champion_pid]
        champ_wins = wins[champion_pid]
        p1_wins = wins.get(1, 0)

        lines.append(f"\n  🏆  CHAMPION: P{champion_pid} ({champ_name}) — {champ_wins}/{n} wins ({champ_wins/n*100:.1f}%)")

        lines.append("")
        if champion_pid == 1:
            lines.append("  !! THE ALL-IN MONKEY WINS !! suflair gpt just got BODIED by a")
            lines.append("  one-line if-statement. Variance is a cruel god.")
        else:
            if p1_wins == 0:
                lines.append("  Player 1 (AlwaysAllIn): ZERO wins. Sent home broke every time.")
                lines.append("  Strategy > luck. suflair gpt thoroughly humiliated. 💀")
            else:
                lines.append(f"  Player 1 (AlwaysAllIn): {p1_wins} wins out of {n}.")
                expected = n / len(names)
                lines.append(f"  Expected by chance: ~{expected:.0f}. The chaos got them {p1_wins}.")
                if p1_wins < expected:
                    lines.append("  Still below fair share. suflair gpt's methods: exposed.")
                else:
                    lines.append("  Lucky degen. But the field still outperforms over time.")

    lines.append("\n╚══════════════════════════════════════════════════════════════════╝")
    lines.append("")
    print("\n".join(lines))


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

if __name__ == '__main__':
    STRATEGIES = [
        AlwaysAllIn(),        # Player 1 — the degen
        TightAggressive(),    # Player 2
        LooseAggressive(),    # Player 3
        GTOInspired(),        # Player 4
        RockSolid(),          # Player 5
        PositionAware(),      # Player 6
    ]
    NAMES = {i + 1: s.name for i, s in enumerate(STRATEGIES)}
    N_SIMS = 100
    STARTING_CHIPS = 1500

    print(f"\nRunning {N_SIMS} Texas Hold'em Tournaments...")
    print(f"Starting chips: {STARTING_CHIPS} each")
    print(f"\nStrategies:")
    for pid, name in NAMES.items():
        tag = "  ← simple (always all-in)" if pid == 1 else ""
        print(f"  P{pid}: {name}{tag}")
    print()

    wins = Counter()
    for i in range(N_SIMS):
        if (i + 1) % 25 == 0:
            print(f"  ... {i + 1}/{N_SIMS} tournaments done")
        w = run_tournament(STRATEGIES, STARTING_CHIPS)
        if w:
            wins[w] += 1

    print_histogram(wins, NAMES, N_SIMS)
