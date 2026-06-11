"""
Texas Hold'em Poker Tournament Simulator
- 6 players, 100 tournaments
- Player 1: the dumbest strategy ever (always all-in)
- Players 2-6: 5 elaborate strategies
- Histogram of last-man-standing winners
"""

import random
import itertools
from collections import Counter, defaultdict

# ─────────────────────────────────────────────
# CARDS
# ─────────────────────────────────────────────

RANKS  = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
SUITS  = ['♠','♥','♦','♣']
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}


class Card:
    __slots__ = ('rank', 'suit', 'value')

    def __init__(self, rank, suit):
        self.rank  = rank
        self.suit  = suit
        self.value = RANK_VAL[rank]

    def __repr__(self):
        return f"{self.rank}{self.suit}"

    def __hash__(self):
        return hash((self.rank, self.suit))

    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit


FULL_DECK = [Card(r, s) for r in RANKS for s in SUITS]


class Deck:
    def __init__(self):
        self.cards = FULL_DECK[:]
        random.shuffle(self.cards)

    def deal(self, n=1):
        out, self.cards = self.cards[:n], self.cards[n:]
        return out


# ─────────────────────────────────────────────
# HAND EVALUATOR  (best 5 from N cards)
# ─────────────────────────────────────────────

def _score5(cards):
    """Return a comparable score tuple for exactly 5 cards."""
    vals  = sorted((c.value for c in cards), reverse=True)
    suits = [c.suit for c in cards]

    flush    = len(set(suits)) == 1
    straight = len(set(vals)) == 5 and (vals[0] - vals[4] == 4)
    # wheel: A-2-3-4-5
    if set(vals) == {14, 2, 3, 4, 5}:
        straight = True
        vals = [5, 4, 3, 2, 1]

    cnt    = Counter(vals)
    groups = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    gvals  = [v for v, _ in groups]
    freqs  = [c for _, c in groups]

    if straight and flush:        return (8, vals)
    if freqs[0] == 4:             return (7, gvals)
    if freqs[:2] == [3, 2]:       return (6, gvals)
    if flush:                     return (5, vals)
    if straight:                  return (4, vals)
    if freqs[0] == 3:             return (3, gvals)
    if freqs[:2] == [2, 2]:       return (2, gvals)
    if freqs[0] == 2:             return (1, gvals)
    return (0, vals)


def best_hand(cards):
    """Best 5-card score from a list of 5-7 cards."""
    if len(cards) == 5:
        return _score5(cards)
    return max(_score5(list(c)) for c in itertools.combinations(cards, 5))


# ─────────────────────────────────────────────
# HAND-STRENGTH ESTIMATE  (Monte Carlo, fast)
# ─────────────────────────────────────────────

def _remaining_deck(known_cards):
    known = set(known_cards)
    return [c for c in FULL_DECK if c not in known]


def hand_equity(hole, board, num_opponents, trials=150):
    """Win-rate estimate vs `num_opponents` random holdings."""
    if num_opponents <= 0:
        return 1.0
    remaining = _remaining_deck(hole + board)
    cards_to_come = 5 - len(board)
    wins = 0
    for _ in range(trials):
        sample = random.sample(remaining, cards_to_come + num_opponents * 2)
        full_board = board + sample[:cards_to_come]
        my_score   = best_hand(hole + full_board)
        beat = False
        for i in range(num_opponents):
            opp = sample[cards_to_come + i*2: cards_to_come + i*2 + 2]
            if best_hand(opp + full_board) >= my_score:
                beat = True
                break
        if not beat:
            wins += 1
    return wins / trials


def preflop_rank(hole):
    """Quick 0-1 pre-flop hand quality estimate."""
    c1, c2 = hole
    hi, lo  = max(c1.value, c2.value), min(c1.value, c2.value)
    suited  = c1.suit == c2.suit
    paired  = hi == lo

    if paired:
        if hi >= 10: return 0.95
        if hi >= 7:  return 0.75
        return 0.55
    if hi == 14:
        if lo >= 10: return 0.88 + (0.04 if suited else 0)
        return 0.55 + (0.05 if suited else 0)
    if hi >= 10 and lo >= 10:
        return 0.70 + (0.05 if suited else 0)
    if hi >= 10 and lo >= 7:
        return 0.55 + (0.05 if suited else 0)
    gap = hi - lo
    if suited and gap <= 2:
        return 0.48
    if gap <= 1:
        return 0.40
    return max(0.10, (hi + lo) / 28 * 0.45 + (0.05 if suited else 0))


# ─────────────────────────────────────────────
# PLAYER
# ─────────────────────────────────────────────

class Player:
    def __init__(self, name, strategy, chips=1000):
        self.name       = name
        self.strategy   = strategy
        self.chips      = chips
        self.hole       = []
        self.folded     = False
        self.all_in     = False
        self.street_bet = 0   # amount committed this betting round
        self.total_wins = 0

    def reset(self):
        self.hole       = []
        self.folded     = False
        self.all_in     = False
        self.street_bet = 0

    def act(self, state):
        if self.folded or self.all_in or self.chips == 0:
            return 'check', 0
        return self.strategy(self, state)

    def __repr__(self):
        return f"{self.name}(${self.chips})"


# ─────────────────────────────────────────────
# STRATEGY 0 – THE BONEHEAD  (Player 1)
# ─────────────────────────────────────────────

def strat_allin(player, state):
    """If my_turn: bet = ALL IN. Full stop."""
    return 'raise', player.chips


# ─────────────────────────────────────────────
# STRATEGY 1 – TIGHT AGGRESSIVE (TAG)
# ─────────────────────────────────────────────

def strat_tag(player, state):
    """
    Only enters pots with premium holdings.
    When it does play, it bets and raises hard.
    Folds anything below threshold without mercy.
    """
    hole    = player.hole
    board   = state['board']
    pot     = state['pot']
    to_call = state['to_call'] - player.street_bet
    phase   = state['phase']
    n_opp   = state['active'] - 1
    bb      = state['bb']

    if phase == 'preflop':
        rank = preflop_rank(hole)
        if rank >= 0.80:
            bet = min(max(pot * 3, bb * 4), player.chips)
            return 'raise', int(bet)
        if rank >= 0.60:
            if to_call <= player.chips * 0.06:
                return 'call', to_call
            return 'fold', 0
        if to_call == 0:
            return 'check', 0
        return 'fold', 0

    equity = hand_equity(hole, board, n_opp)
    if equity >= 0.72:
        bet = min(int(pot * 0.80), player.chips)
        return 'raise', max(bet, to_call + bb)
    if equity >= 0.52:
        if to_call == 0:
            return 'check', 0
        if to_call <= pot * 0.30:
            return 'call', to_call
        return 'fold', 0
    if to_call == 0:
        return 'check', 0
    return 'fold', 0


# ─────────────────────────────────────────────
# STRATEGY 2 – LOOSE AGGRESSIVE (LAG)
# ─────────────────────────────────────────────

def strat_lag(player, state):
    """
    Plays a wide range, fires bullets relentlessly.
    Uses position to steal pots and keep opponents guessing.
    Bluffs with purpose on favourable board textures.
    """
    hole     = player.hole
    board    = state['board']
    pot      = state['pot']
    to_call  = state['to_call'] - player.street_bet
    phase    = state['phase']
    n_opp    = state['active'] - 1
    pos_frac = state['pos_frac']   # 0=early, 1=late
    bb       = state['bb']

    if phase == 'preflop':
        rank      = preflop_rank(hole)
        threshold = 0.50 - pos_frac * 0.15   # looser in position
        if rank >= threshold:
            if rank >= 0.75:
                bet = min(int(pot * 4), player.chips)
                return 'raise', max(bet, bb * 4)
            if to_call <= player.chips * 0.12:
                return 'call', to_call
            return 'raise', min(int(pot * 2.5), player.chips)
        if to_call == 0:
            if pos_frac > 0.65 and random.random() < 0.25:
                return 'raise', bb * 3
            return 'check', 0
        if to_call <= bb and pos_frac > 0.5:
            return 'call', to_call
        return 'fold', 0

    equity = hand_equity(hole, board, n_opp)
    bluff   = random.random() < 0.22 + pos_frac * 0.10

    if equity >= 0.55:
        bet = min(int(pot * (0.80 + pos_frac * 0.40)), player.chips)
        return 'raise', max(bet, to_call + bb)
    if equity >= 0.38 or bluff:
        if to_call == 0:
            bet = min(int(pot * (0.45 + pos_frac * 0.25)), player.chips)
            return 'raise', max(bet, 1)
        if to_call <= pot * 0.45:
            return 'call', to_call
    if to_call == 0:
        return 'check', 0
    return 'fold', 0


# ─────────────────────────────────────────────
# STRATEGY 3 – MATHEMATICAL / GTO-INSPIRED
# ─────────────────────────────────────────────

def strat_math(player, state):
    """
    Every decision grounded in pot-odds vs equity.
    Uses mixed strategy (randomised bet/check) to stay unexploitable.
    Sizes bets proportionally to hand strength and pot.
    """
    hole    = player.hole
    board   = state['board']
    pot     = state['pot']
    to_call = state['to_call'] - player.street_bet
    phase   = state['phase']
    n_opp   = state['active'] - 1
    bb      = state['bb']

    if phase == 'preflop':
        rank = preflop_rank(hole)
        if to_call > 0:
            pot_odds = to_call / (pot + to_call + 1e-6)
            if rank > pot_odds + 0.08:
                if rank >= 0.78:
                    bet = min(int(pot * 3), player.chips)
                    return 'raise', max(bet, to_call * 2)
                return 'call', to_call
            return 'fold', 0
        if rank >= 0.45:
            bet = int(bb * (1 + rank * 3))
            return 'raise', min(bet, player.chips)
        return 'check', 0

    equity = hand_equity(hole, board, n_opp)
    if to_call > 0:
        pot_odds = to_call / (pot + to_call + 1e-6)
        if equity > pot_odds + 0.04:
            if equity >= 0.65:
                bet = min(int(pot * equity), player.chips)
                return 'raise', max(bet, to_call * 2)
            return 'call', to_call
        return 'fold', 0

    # Mixed strategy: bet with prob ~ equity
    if random.random() < equity:
        bet = min(int(pot * 0.55), player.chips)
        return 'raise', max(bet, bb)
    return 'check', 0


# ─────────────────────────────────────────────
# STRATEGY 4 – POSITIONAL
# ─────────────────────────────────────────────

def strat_positional(player, state):
    """
    Position is everything. Plays extremely tight out of position,
    extremely wide and aggressive in position.
    Check-raises with monster hands, steals with position-enhanced bluffs.
    """
    hole     = player.hole
    board    = state['board']
    pot      = state['pot']
    to_call  = state['to_call'] - player.street_bet
    phase    = state['phase']
    n_opp    = state['active'] - 1
    pos_frac = state['pos_frac']
    bb       = state['bb']

    # Threshold slides from 0.72 (early) to 0.38 (button)
    pf_threshold = 0.72 - pos_frac * 0.34

    if phase == 'preflop':
        rank = preflop_rank(hole)
        if rank >= pf_threshold:
            if rank >= 0.75 or pos_frac >= 0.75:
                bet = min(int(pot * (2.0 + pos_frac)), player.chips)
                return 'raise', max(bet, bb * 3)
            return 'call', to_call
        if to_call == 0:
            if pos_frac >= 0.85 and random.random() < 0.35:
                return 'raise', bb * 3
            return 'check', 0
        return 'fold', 0

    equity   = hand_equity(hole, board, n_opp)
    adj      = equity + pos_frac * 0.08

    if adj >= 0.62:
        # Check-raise trap if in position with monster
        if to_call == 0 and pos_frac >= 0.6 and equity >= 0.80:
            return 'check', 0   # trap (opponent likely to bet into us)
        bet = min(int(pot * (0.5 + pos_frac * 0.6)), player.chips)
        return 'raise', max(bet, to_call + bb)
    if adj >= 0.42:
        if to_call == 0:
            if pos_frac >= 0.60:
                bet = min(int(pot * 0.38), player.chips)
                return 'raise', max(bet, bb)
            return 'check', 0
        if to_call <= pot * 0.30:
            return 'call', to_call
    if to_call == 0:
        return 'check', 0
    return 'fold', 0


# ─────────────────────────────────────────────
# STRATEGY 5 – ADAPTIVE / EXPLOIT
# ─────────────────────────────────────────────

def strat_adaptive(player, state):
    """
    Watches the table's aggression level and flips its game-plan.
    Vs passive tables: value-bet thin, bluff more.
    Vs aggressive tables: tighten, trap, wait.
    Dynamically adjusts bet sizing and bluff frequency each street.
    """
    hole       = player.hole
    board      = state['board']
    pot        = state['pot']
    to_call    = state['to_call'] - player.street_bet
    phase      = state['phase']
    n_opp      = state['active'] - 1
    agg        = state['table_agg']   # 0=passive, 1=aggressive
    bb         = state['bb']

    # Against aggression: tighten entry, widen calling range
    pf_thresh = 0.48 + agg * 0.22

    if phase == 'preflop':
        rank = preflop_rank(hole)
        if rank >= pf_thresh:
            if rank >= 0.78:
                # 3-bet big against aggressive, pot-size against passive
                bet = min(int(pot * (3.5 if agg > 0.5 else 2.5)), player.chips)
                return 'raise', max(bet, bb * (4 if agg > 0.5 else 3))
            if to_call <= player.chips * 0.09:
                return 'call', to_call
            return 'raise', min(int(pot * 1.8), player.chips)
        if to_call == 0:
            return 'check', 0
        return 'fold', 0

    equity = hand_equity(hole, board, n_opp)

    # Value-bet threshold: thinner vs passive (they call wide)
    vbet_thresh = 0.68 - (1 - agg) * 0.12
    # Bluff freq: higher vs passive (they fold more to bets)
    bluff_prob  = 0.28 - agg * 0.18

    if equity >= vbet_thresh:
        multiplier = 0.70 + (1 - agg) * 0.30   # bigger vs calling stations
        bet = min(int(pot * multiplier), player.chips)
        return 'raise', max(bet, to_call + bb)

    if equity >= 0.48:
        if to_call == 0:
            check_raise = (agg < 0.4) and equity >= 0.62
            if check_raise:
                return 'check', 0
            return 'raise', min(int(pot * 0.45), player.chips)
        if to_call <= pot * 0.38:
            return 'call', to_call

    if equity < 0.32 and to_call == 0 and random.random() < bluff_prob:
        bet = min(int(pot * 0.60), player.chips)
        return 'raise', max(bet, bb)

    if to_call == 0:
        return 'check', 0
    if to_call <= pot * 0.18 and equity >= 0.36:
        return 'call', to_call
    return 'fold', 0


# ─────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────

class HoldemGame:
    def __init__(self, players, sb=10, bb=20):
        self.players    = players
        self.sb         = sb
        self.bb         = bb
        self.dealer_idx = 0
        self.table_agg  = 0.50   # running estimate

    # ── tournament ──────────────────────────────

    def run_tournament(self):
        """Play hands until one player remains. Returns winner name."""
        hand_no = 0
        while True:
            alive = [p for p in self.players if p.chips > 0]
            if len(alive) <= 1:
                break
            self.play_hand(alive)
            hand_no += 1
            if hand_no > 800:    # hard cap (shouldn't trigger)
                break
        winner = max(self.players, key=lambda p: p.chips)
        return winner.name

    # ── single hand ─────────────────────────────

    def play_hand(self, alive):
        n   = len(alive)
        deck = Deck()
        pot  = 0
        board = []

        for p in alive:
            p.reset()

        # Blinds
        sb_idx = (self.dealer_idx + 1) % n
        bb_idx = (self.dealer_idx + 2) % n
        sb_p   = alive[sb_idx]
        bb_p   = alive[bb_idx]

        sb_amt = min(self.sb, sb_p.chips)
        bb_amt = min(self.bb, bb_p.chips)
        sb_p.chips      -= sb_amt;  sb_p.street_bet = sb_amt;  pot += sb_amt
        bb_p.chips      -= bb_amt;  bb_p.street_bet = bb_amt;  pot += bb_amt
        if sb_p.chips == 0: sb_p.all_in = True
        if bb_p.chips == 0: bb_p.all_in = True

        # Deal hole cards
        for p in alive:
            p.hole = deck.deal(2)

        # Four streets
        streets = [
            ('preflop', 0,  (self.dealer_idx + 3) % n),
            ('flop',    3,  (self.dealer_idx + 1) % n),
            ('turn',    1,  (self.dealer_idx + 1) % n),
            ('river',   1,  (self.dealer_idx + 1) % n),
        ]

        for phase, new_cards, first_idx in streets:
            board.extend(deck.deal(new_cards))
            alive_now = [p for p in alive if not p.folded]
            if len(alive_now) <= 1:
                break
            can_act = [p for p in alive_now if not p.all_in and p.chips > 0]
            if len(can_act) == 0:
                continue
            pot = self._betting_round(alive, phase, board, pot, first_idx, n)
            alive_now = [p for p in alive if not p.folded]
            if len(alive_now) <= 1:
                break

        # Showdown / award pot
        contestants = [p for p in alive if not p.folded]
        if len(contestants) == 1:
            contestants[0].chips += pot
        else:
            scored = [(best_hand(p.hole + board), p) for p in contestants]
            scored.sort(key=lambda x: x[0], reverse=True)
            top    = scored[0][0]
            winners = [p for s, p in scored if s == top]
            share, rem = divmod(pot, len(winners))
            for w in winners:
                w.chips += share
            winners[0].chips += rem

        self.dealer_idx = (self.dealer_idx + 1) % n

    # ── betting round ────────────────────────────

    def _betting_round(self, alive, phase, board, pot, first_idx, n):
        not_folded = [p for p in alive if not p.folded]
        if not not_folded:
            return pot

        # Reset street bets (except preflop—blinds already in)
        if phase != 'preflop':
            for p in not_folded:
                p.street_bet = 0

        cur_bet = self.bb if phase == 'preflop' else 0

        # Build action order starting at first_idx within alive
        order = []
        for i in range(n):
            p = alive[(first_idx + i) % n]
            if not p.folded:
                order.append(p)

        acted   = set()
        raises  = 0
        actions = 0
        idx     = 0
        max_loops = len(order) * 6

        while max_loops > 0:
            max_loops -= 1
            player = order[idx % len(order)]
            idx   += 1

            if player.folded or player.all_in or player.chips == 0:
                # Skip but check termination
                can_act = [p for p in order if not p.folded and not p.all_in and p.chips > 0]
                if not can_act:
                    break
                settled = all(p.street_bet == cur_bet for p in can_act)
                done    = all(p in acted or p.all_in or p.chips == 0 or p.folded for p in order)
                if settled and done:
                    break
                continue

            to_call  = cur_bet   # total street amount needed
            pos_list = [p for p in order if not p.folded]
            pos_frac = pos_list.index(player) / max(len(pos_list) - 1, 1) if len(pos_list) > 1 else 0.5
            n_active = len(pos_list)

            state = {
                'board':      board,
                'pot':        pot,
                'to_call':    to_call,
                'phase':      phase,
                'active':     n_active,
                'bb':         self.bb,
                'pos_frac':   pos_frac,
                'table_agg':  self.table_agg,
            }

            action, amount = player.act(state)
            actions += 1

            if action == 'fold':
                player.folded = True
                acted.add(id(player))

            elif action == 'check':
                if player.street_bet < cur_bet:
                    # Treat as call/fold
                    deficit = min(cur_bet - player.street_bet, player.chips)
                    if deficit <= self.bb:       # cheap, just call
                        player.chips -= deficit
                        player.street_bet += deficit
                        pot += deficit
                        if player.chips == 0:
                            player.all_in = True
                    else:
                        player.folded = True
                acted.add(id(player))

            elif action == 'call':
                deficit = min(cur_bet - player.street_bet, player.chips)
                player.chips     -= deficit
                player.street_bet += deficit
                pot += deficit
                if player.chips == 0:
                    player.all_in = True
                acted.add(id(player))

            elif action == 'raise':
                # First, cover the current bet
                call_part = min(cur_bet - player.street_bet, player.chips)
                player.chips     -= call_part
                player.street_bet += call_part
                pot += call_part

                # Then push extra chips as the raise
                extra = min(amount, player.chips)
                if extra > 0:
                    player.chips     -= extra
                    player.street_bet += extra
                    pot += extra
                    if player.street_bet > cur_bet:
                        cur_bet = player.street_bet
                        acted   = {id(player)}    # everyone else re-opens
                        raises += 1
                if player.chips == 0:
                    player.all_in = True
                else:
                    acted.add(id(player))

            # Termination check
            can_act = [p for p in order if not p.folded and not p.all_in and p.chips > 0]
            if not can_act:
                break
            settled = all(p.street_bet == cur_bet for p in can_act)
            done    = all(id(p) in acted for p in can_act)
            if settled and done:
                break
            not_folded_now = [p for p in order if not p.folded]
            if len(not_folded_now) <= 1:
                break

        # Update table-aggression EMA
        if actions > 0:
            agg_rate         = raises / actions
            self.table_agg   = 0.75 * self.table_agg + 0.25 * agg_rate

        return pot


# ─────────────────────────────────────────────
# SIMULATION RUNNER
# ─────────────────────────────────────────────

PLAYER_DEFS = [
    # (display_name, tag_key, strategy_fn)
    ("Player 1  [YOLO ALL-IN]",   "P1_AllIn",     strat_allin),
    ("Player 2  [TAG]",           "P2_TAG",        strat_tag),
    ("Player 3  [LAG]",           "P3_LAG",        strat_lag),
    ("Player 4  [Mathematical]",  "P4_Math",       strat_math),
    ("Player 5  [Positional]",    "P5_Positional", strat_positional),
    ("Player 6  [Adaptive]",      "P6_Adaptive",   strat_adaptive),
]

STARTING_CHIPS = 1000
NUM_SIMS       = 100


def run(seed=None):
    if seed is not None:
        random.seed(seed)

    wins = defaultdict(int)

    print(f"Running {NUM_SIMS} Texas Hold'em tournaments…")
    print(f"  6 players, {STARTING_CHIPS} chips each, blinds 10/20\n")

    for sim in range(NUM_SIMS):
        players = [Player(name, fn, STARTING_CHIPS) for name, _, fn in PLAYER_DEFS]
        game    = HoldemGame(players, sb=10, bb=20)
        winner  = game.run_tournament()
        wins[winner] += 1

        if (sim + 1) % 20 == 0:
            print(f"  [{sim+1:3d}/{NUM_SIMS}] running…")

    return wins


# ─────────────────────────────────────────────
# HISTOGRAM OUTPUT
# ─────────────────────────────────────────────

def histogram(wins):
    BAR_W   = 42
    total   = sum(wins.values())
    max_w   = max(wins.values()) if wins else 1

    # Map display_name → tag for lookup
    tag_of  = {name: tag for name, tag, _ in PLAYER_DEFS}
    descs = {
        "P1_AllIn":      "Always goes ALL-IN. Every hand. No thoughts, just vibes.",
        "P2_TAG":        "Tight-Aggressive. Premium hands only; hammers opponents hard.",
        "P3_LAG":        "Loose-Aggressive. Plays wide, bluffs often, never lets up.",
        "P4_Math":       "GTO-inspired. Pot odds, equity, mixed strategy, unexploitable.",
        "P5_Positional": "Position master. Steal blinds, punish out-of-position foes.",
        "P6_Adaptive":   "Shape-shifter. Reads table aggression, exploits every pattern.",
    }

    sorted_wins = sorted(
        ((name, wins.get(name, 0)) for name, _, _ in PLAYER_DEFS),
        key=lambda x: x[1], reverse=True
    )

    print()
    print("╔" + "═" * 70 + "╗")
    print("║" + "   🃏  TEXAS HOLD'EM — 100-TOURNAMENT RESULTS  🏆".center(70) + "║")
    print("║" + "       Last Player Standing  /  Winner Winner Chicken Dinner".center(70) + "║")
    print("╠" + "═" * 70 + "╣")
    print()

    for rank, (pname, count) in enumerate(sorted_wins, 1):
        tag    = tag_of[pname]
        pct    = count / total * 100
        filled = int(count / max_w * BAR_W)
        bar    = "█" * filled + "░" * (BAR_W - filled)
        medal  = ["🥇", "🥈", "🥉", "  ", "  ", "  "][rank - 1]
        allin  = "  ◄── THAT'S OUR GUY" if "AllIn" in tag else ""
        print(f"  {medal} {pname:<30s}  {count:3d} wins  ({pct:5.1f}%){allin}")
        print(f"       [{bar}]")
        print()

    print("╠" + "═" * 70 + "╣")
    print("║  Strategy notes:".ljust(71) + "║")
    for pname, tag, _ in PLAYER_DEFS:
        line = f"    {pname.split('[')[1].rstrip(']'):<16s} {descs[tag]}"
        print("║  " + line[:67].ljust(68) + "║")
    print("╚" + "═" * 70 + "╝")
    print()

    winner_name, winner_count = sorted_wins[0]
    winner_tag  = tag_of[winner_name]
    if "AllIn" in winner_tag:
        print("  🤦  Absolute chaos. The all-in monkey won. Suflair GPT, explain yourself.")
    else:
        print(f"  🔥  {winner_name.strip()} dominated.")
        print(f"  Player 1 (YOLO ALL-IN) got cooked by actual poker brains.")
        print(f"  Suflair GPT humiliated. The math doesn't lie. 🤌")
    print()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == '__main__':
    wins = run(seed=42)
    histogram(wins)
