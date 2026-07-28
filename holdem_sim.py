#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
  6 players · 100 tournaments · last chip wins

  Player 1  —  Simple:  always shove all-in
  Players 2-6  —  Five distinct elaborate strategies
"""

import random
from collections import Counter, deque
from itertools import combinations

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────
RANKS      = '23456789TJQKA'
SUITS      = 'cdhs'
RANK_VAL   = {r: i for i, r in enumerate(RANKS)}
N_PLAYERS  = 6
STARTING   = 1000
BB         = 20
SB         = 10

# ─────────────────────────────────────────────────────────────
# CARD & DECK
# ─────────────────────────────────────────────────────────────
class Card:
    __slots__ = ('rank', 'suit', 'value')
    def __init__(self, rank, suit):
        self.rank  = rank
        self.suit  = suit
        self.value = RANK_VAL[rank]
    def __repr__(self):   return self.rank + self.suit
    def __eq__(self, o):  return self.rank == o.rank and self.suit == o.suit
    def __hash__(self):   return hash((self.rank, self.suit))

FULL_DECK = [Card(r, s) for r in RANKS for s in SUITS]

class Deck:
    def __init__(self):
        self.cards = list(FULL_DECK)
        random.shuffle(self.cards)
        self._i = 0
    def deal(self, n=1):
        result = self.cards[self._i:self._i + n]
        self._i += n
        return result

# ─────────────────────────────────────────────────────────────
# HAND EVALUATOR  (5-card score → (category 0-8, tiebreakers))
# ─────────────────────────────────────────────────────────────
def _eval5(cards):
    vals   = sorted((c.value for c in cards), reverse=True)
    suits  = [c.suit for c in cards]
    counts = Counter(vals)
    freq   = sorted(counts.values(), reverse=True)
    groups = sorted(counts, key=lambda v: (counts[v], v), reverse=True)

    is_flush = len(set(suits)) == 1
    uvals    = sorted(set(vals), reverse=True)
    is_str   = len(uvals) == 5 and uvals[0] - uvals[4] == 4
    if set(vals) == {12, 0, 1, 2, 3}:          # wheel A-2-3-4-5
        is_str, vals, groups = True, [3,2,1,0,-1], [3,2,1,0,-1]

    if is_str and is_flush: return (8, vals)
    if freq[0] == 4:         return (7, groups)
    if freq[:2] == [3, 2]:   return (6, groups)
    if is_flush:             return (5, vals)
    if is_str:               return (4, vals)
    if freq[0] == 3:         return (3, groups)
    if freq[:2] == [2, 2]:   return (2, groups)
    if freq[0] == 2:         return (1, groups)
    return (0, groups)

def best_hand(hole, board):
    pool = hole + board
    if len(pool) < 5:
        return (0, sorted((c.value for c in pool), reverse=True))
    return max(_eval5(list(c)) for c in combinations(pool, 5))

# ─────────────────────────────────────────────────────────────
# PLAYER STATE
# ─────────────────────────────────────────────────────────────
class Player:
    __slots__ = ('pid', 'chips', 'hole', 'folded', 'allin', 'invested')
    def __init__(self, pid, chips):
        self.pid      = pid
        self.chips    = chips
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.invested = 0          # chips put in this hand (side-pot tracking)
    def reset(self):
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.invested = 0

# ─────────────────────────────────────────────────────────────
# GAME STATE  (read-only snapshot passed to strategies)
# ─────────────────────────────────────────────────────────────
class GameState:
    __slots__ = ('board', 'pot', 'current_bet', 'stage', 'players', 'n_active')
    def __init__(self):
        self.board       = []
        self.pot         = 0
        self.current_bet = 0
        self.stage       = 'preflop'
        self.players     = []     # ordered list for position reference
        self.n_active    = 0

# ─────────────────────────────────────────────────────────────
#  STRATEGIES
#  Convention for decide() return value:
#    ('fold', 0)       — muck cards
#    ('call', 0)       — call/check (engine enforces to_call minimum)
#    ('raise', X)      — put X chips into the pot (engine enforces min-call)
# ─────────────────────────────────────────────────────────────
class Strategy:
    name = "Base"
    def decide(self, player, gs, to_call):
        raise NotImplementedError


# ══════════════════════════════════════════════════════════════
#  PLAYER 1 — The Maniac  (simple: shove every hand forever)
# ══════════════════════════════════════════════════════════════
class AlwaysAllIn(Strategy):
    name = "The Maniac  [SIMPLE: ALL-IN ALWAYS]"
    def decide(self, player, gs, to_call):
        return ('raise', player.chips)


# ══════════════════════════════════════════════════════════════
#  PLAYER 2 — Tight Aggressive (TAG)
#   Only plays premium / strong hands preflop; bets/raises big
#   when ahead, folds anything marginal post-flop.
# ══════════════════════════════════════════════════════════════
class TightAggressive(Strategy):
    name = "Tight Aggressive (TAG)"

    _PREMIUM = {frozenset(['A','A']), frozenset(['K','K']),
                frozenset(['Q','Q']), frozenset(['J','J'])}
    _STRONG  = {frozenset(['T','T']), frozenset(['9','9']), frozenset(['8','8']),
                frozenset(['A','K']), frozenset(['A','Q']), frozenset(['K','Q'])}

    def _tier(self, hole):
        r = frozenset(c.rank for c in hole)
        if r in self._PREMIUM: return 3
        if r in self._STRONG:  return 2
        v = sorted(RANK_VAL[c.rank] for c in hole)
        if hole[0].suit == hole[1].suit and v[1]-v[0] <= 2 and v[0] >= 4:
            return 1
        return 0

    def decide(self, player, gs, to_call):
        pot = gs.pot
        if gs.stage == 'preflop':
            t = self._tier(player.hole)
            if t == 3:
                return ('raise', min(player.chips, 3*BB + to_call))
            if t == 2:
                return ('call', to_call) if to_call <= 3*BB else ('fold', 0)
            if t == 1 and to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        cat = best_hand(player.hole, gs.board)[0]
        if cat >= 5:  return ('raise', min(player.chips, pot))
        if cat >= 3:  return ('raise', min(player.chips, pot // 2))
        if cat >= 1 and to_call <= pot // 4: return ('call', to_call)
        return ('call', 0) if to_call == 0 else ('fold', 0)


# ══════════════════════════════════════════════════════════════
#  PLAYER 3 — Loose Aggressive (LAG)
#   Plays a wide range, bluffs ~28 % of the time post-flop,
#   applies constant pressure with bets and raises.
# ══════════════════════════════════════════════════════════════
class LooseAggressive(Strategy):
    name = "Loose Aggressive (LAG)"

    def decide(self, player, gs, to_call):
        pot = gs.pot

        if gs.stage == 'preflop':
            v  = sorted(RANK_VAL[c.rank] for c in player.hole)
            playable = (v[0] == v[1]                             # any pair
                        or v[1] >= 8                             # broadway
                        or (player.hole[0].suit == player.hole[1].suit and v[1] >= 5)
                        or random.random() < 0.28)               # bluff-enter
            if playable:
                bet = min(player.chips, max(2*BB + to_call, pot // 3 + to_call))
                return ('raise', bet)
            return ('fold', 0) if to_call > 0 else ('call', 0)

        cat   = best_hand(player.hole, gs.board)[0]
        bluff = random.random() < 0.28
        if cat >= 2 or bluff:
            return ('raise', min(player.chips, max(BB, pot // 2)))
        if to_call == 0:    return ('call', 0)
        if to_call <= BB*2: return ('call', to_call)
        return ('fold', 0)


# ══════════════════════════════════════════════════════════════
#  PLAYER 4 — GTO Approximator
#   Runs lightweight Monte Carlo equity estimation, then
#   compares equity vs pot-odds to make balanced decisions.
#   Mixes in small probe bets when equity > 50 % and no bet.
# ══════════════════════════════════════════════════════════════
class GTOApproximator(Strategy):
    name = "GTO Approximator"

    def _equity(self, hole, board, n_opp, trials=40):
        known = {id(c) for c in hole + board}
        deck  = [c for c in FULL_DECK if id(c) not in known]
        wins  = 0
        for _ in range(trials):
            random.shuffle(deck)
            opp   = [deck[2*i:2*i+2] for i in range(n_opp)]
            run   = board + deck[2*n_opp: 2*n_opp + (5 - len(board))]
            mine  = best_hand(hole, run)
            if all(mine >= best_hand(o, run) for o in opp):
                wins += 1
        return wins / trials

    def decide(self, player, gs, to_call):
        n_opp = max(1, gs.n_active - 1)
        pot   = gs.pot
        eq    = self._equity(player.hole, gs.board, min(n_opp, 3))
        p_odds = to_call / (pot + to_call) if pot + to_call > 0 else 0

        if eq > 0.65:
            bet = min(player.chips, int(pot * eq) + to_call)
            return ('raise', max(bet, BB + to_call))
        if eq > p_odds + 0.05:
            return ('call', to_call)
        if to_call == 0:
            return ('raise', min(player.chips, pot // 3)) if eq > 0.5 else ('call', 0)
        return ('fold', 0)


# ══════════════════════════════════════════════════════════════
#  PLAYER 5 — Position Aware Pro
#   Tight in early seats, wide in late seats. Steals from BTN.
#   Scales bluff frequency and bet sizing with position.
# ══════════════════════════════════════════════════════════════
class PositionAwarePro(Strategy):
    name = "Position Aware Pro"

    def _pos(self, player, gs):
        active = [p for p in gs.players if not p.folded]
        if len(active) <= 1: return 1.0
        ids = [p.pid for p in active]
        try:    i = ids.index(player.pid)
        except: i = 0
        return i / (len(ids) - 1)   # 0 = UTG / early,  1 = BTN / late

    def _hs(self, hole):
        v = sorted(RANK_VAL[c.rank] for c in hole)
        return min(1.0, (v[0]+v[1])/24.0
                   + (0.25 if v[0]==v[1] else 0)
                   + (0.04 if hole[0].suit == hole[1].suit else 0))

    def decide(self, player, gs, to_call):
        pos = self._pos(player, gs)
        pot = gs.pot

        if gs.stage == 'preflop':
            threshold = 0.56 - 0.30 * pos   # 0.56 early → 0.26 late
            if self._hs(player.hole) >= threshold:
                bet = min(player.chips, int(BB*(2.5 + pos*1.5)) + to_call)
                return ('raise', bet)
            return ('fold', 0) if to_call > 0 else ('call', 0)

        cat   = best_hand(player.hole, gs.board)[0]
        bluff = random.random() < (0.12 + 0.22 * pos)
        if cat >= 3 or (cat >= 1 and pos > 0.6) or bluff:
            bet = min(player.chips, int(pot*(0.4 + 0.4*pos)) + to_call)
            return ('raise', bet)
        if to_call == 0:    return ('call', 0)
        if to_call <= BB*2: return ('call', to_call)
        return ('fold', 0)


# ══════════════════════════════════════════════════════════════
#  PLAYER 6 — Pot-Odds Calculator
#   Maps current hand category → equity estimate, adjusts for
#   flush/straight draws using outs × remaining-streets rule,
#   applies implied-odds multiplier, then bet/call/fold.
# ══════════════════════════════════════════════════════════════
class PotOddsCalculator(Strategy):
    name = "Pot Odds Calculator"

    _CAT_EQ = {8:.97, 7:.94, 6:.89, 5:.83, 4:.73, 3:.63, 2:.49, 1:.29, 0:.14}

    def _equity(self, hole, board):
        cat  = best_hand(hole, board)[0]
        base = self._CAT_EQ[cat]

        if len(board) < 5:
            rem_streets   = 2 - max(0, len(board) - 3)
            cards_left    = 52 - 2 - len(board)
            # Flush draw
            sc = Counter(c.suit for c in hole+board)
            if max(sc.values()) == 4:
                base = max(base, 0.33 + 9*rem_streets/max(cards_left,1))
            # Open-ended straight draw
            vs = sorted({RANK_VAL[c.rank] for c in hole+board})
            for i in range(len(vs)-3):
                if vs[i+3]-vs[i] <= 4:
                    base = max(base, 0.29 + 8*rem_streets/max(cards_left,1))
                    break
        return min(base, 0.97)

    def decide(self, player, gs, to_call):
        pot   = gs.pot
        eq    = self._equity(player.hole, gs.board)
        imp   = eq * 1.25   # implied odds factor
        p_odds = to_call/(pot+to_call) if pot+to_call > 0 else 0

        if imp > 0.70:
            bet = min(player.chips, int(pot*0.75) + to_call)
            return ('raise', max(bet, BB + to_call))
        if imp > p_odds + 0.08:
            return ('call', to_call)
        if to_call == 0:
            return ('raise', min(player.chips, pot//4)) if eq > 0.45 else ('call', 0)
        return ('fold', 0)


# ─────────────────────────────────────────────────────────────
# STRATEGY REGISTRY  (index = player id)
# ─────────────────────────────────────────────────────────────
STRATS = [
    AlwaysAllIn(),          # P1  ← simple
    TightAggressive(),      # P2
    LooseAggressive(),      # P3
    GTOApproximator(),      # P4
    PositionAwarePro(),     # P5
    PotOddsCalculator(),    # P6
]

LABELS = [
    ("P1 · The Maniac  [ALL-IN EVERY HAND]",  True),
    ("P2 · Tight Aggressive (TAG)",            False),
    ("P3 · Loose Aggressive (LAG)",            False),
    ("P4 · GTO Approximator",                  False),
    ("P5 · Position Aware Pro",                False),
    ("P6 · Pot Odds Calculator",               False),
]

# ─────────────────────────────────────────────────────────────
# BETTING ENGINE
# ─────────────────────────────────────────────────────────────
def betting_round(order, gs, sc, cur_bet):
    """
    order    : list[Player] in acting order for this street
    gs       : GameState (mutated: pot, current_bet)
    sc       : dict {pid: chips_committed_this_street}
    cur_bet  : highest chip level committed so far this street
    Returns (pot, sc, cur_bet) after all action.
    """
    n = len(order)
    if n == 0:
        return gs.pot, sc, cur_bet

    queue = deque(order)

    while queue:
        p = queue.popleft()
        if p.folded or p.chips == 0:
            if p.chips == 0:
                p.allin = True
            continue

        to_call = max(0, cur_bet - sc.get(p.pid, 0))
        gs.current_bet = cur_bet
        action, amount = STRATS[p.pid].decide(p, gs, to_call)

        if action == 'fold':
            p.folded = True
            if sum(1 for x in order if not x.folded) <= 1:
                break
            continue

        # Determine chips going in
        if action == 'call':
            put = min(to_call, p.chips)
        else:   # raise: amount is how many chips player wants to commit
            put = max(min(to_call, p.chips),    # at least call
                      min(amount, p.chips))

        p.chips   -= put
        p.invested += put
        sc[p.pid]  = sc.get(p.pid, 0) + put
        gs.pot    += put

        new_level = sc[p.pid]
        if new_level > cur_bet:
            cur_bet = new_level
            cur_pos = order.index(p)
            still   = [order[(cur_pos+1+i)%n] for i in range(n-1)]
            queue   = deque(x for x in still if not x.folded and x.chips > 0)

        if p.chips == 0:
            p.allin = True

    return gs.pot, sc, cur_bet

# ─────────────────────────────────────────────────────────────
# SIDE-POT RESOLUTION
# ─────────────────────────────────────────────────────────────
def resolve_pots(in_hand, all_players, board):
    """Distribute pot(s) to in_hand players, respecting side pots."""
    contributors = sorted((p for p in all_players if p.invested > 0),
                          key=lambda p: p.invested)
    awards  = Counter()
    prev    = 0

    for cp in contributors:
        cap = cp.invested
        if cap <= prev:
            continue
        side = sum(max(0, min(p.invested, cap) - min(p.invested, prev))
                   for p in all_players)
        eligible = [p for p in in_hand if p.invested >= cap] or list(in_hand)
        if not eligible:
            prev = cap
            continue
        scores  = {p.pid: best_hand(p.hole, board) for p in eligible}
        best    = max(scores.values())
        winners = [p for p in eligible if scores[p.pid] == best]
        share, rem = divmod(side, len(winners))
        for w in winners:
            awards[w.pid] += share
        awards[winners[0].pid] += rem
        prev = cap

    return awards

# ─────────────────────────────────────────────────────────────
# PLAY ONE HAND
# ─────────────────────────────────────────────────────────────
def play_hand(players):
    """Modify players[i].chips in-place. players is already seat-ordered."""
    alive = [p for p in players if p.chips > 0]
    if len(alive) < 2:
        return
    for p in players:
        p.reset()
    alive = [p for p in players if p.chips > 0]
    n = len(alive)

    deck = Deck()
    gs   = GameState()
    gs.players = alive

    for p in alive:
        p.hole = deck.deal(2)

    # Post blinds
    def post(p, amt):
        a = min(amt, p.chips)
        p.chips -= a; p.invested += a; gs.pot += a
        return a

    sb = post(alive[0], SB)
    bbl = post(alive[1], BB)
    sc  = {alive[0].pid: sb, alive[1].pid: bbl}
    cur = bbl

    # Pre-flop: UTG first (index 2) or HU: SB first
    gs.stage    = 'preflop'
    gs.n_active = n
    pf_order = [alive[2%n], *alive[3%n:], *alive[:2]] if n > 2 else [alive[0], alive[1]]
    gs.pot, sc, cur = betting_round(pf_order, gs, sc, cur)

    def remaining():
        return [p for p in alive if not p.folded]

    ih = remaining()
    if len(ih) == 1: ih[0].chips += gs.pot; return

    for street, n_cards in [('flop',3),('turn',1),('river',1)]:
        gs.board  += deck.deal(n_cards)
        gs.stage   = street
        act_order  = [p for p in alive if not p.folded]
        gs.n_active = len(act_order)
        gs.pot, sc, cur = betting_round(act_order, gs, {}, 0)
        ih = remaining()
        if len(ih) == 1: ih[0].chips += gs.pot; return

    # Showdown
    awards = resolve_pots(ih, alive, gs.board)
    for pid, amt in awards.items():
        next(p for p in players if p.pid == pid).chips += amt

# ─────────────────────────────────────────────────────────────
# TOURNAMENT  (play until one player has all chips)
# ─────────────────────────────────────────────────────────────
def run_tournament():
    players = [Player(i, STARTING) for i in range(N_PLAYERS)]
    for _ in range(3000):   # safety cap
        alive = [p for p in players if p.chips > 0]
        if len(alive) <= 1:
            break
        random.shuffle(alive)   # rotate seats / dealer position
        play_hand(alive)
    return max(players, key=lambda p: p.chips).pid

# ─────────────────────────────────────────────────────────────
# MAIN  ·  100 simulations  +  ASCII histogram
# ─────────────────────────────────────────────────────────────
def main():
    N_SIMS = 100
    wins   = Counter()

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   TEXAS HOLD'EM · 6 PLAYERS · 100 TOURNAMENTS · LAST CHIP   ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("  Player 1  →  simple  : ALL-IN on every single turn")
    print("  Players 2-6 →  elaborate strategies (TAG / LAG / GTO / POS / POT)")
    print()
    print("  Simulating", end='', flush=True)
    for i in range(N_SIMS):
        if i % 10 == 0:
            print(f" {i}", end='', flush=True)
        wins[run_tournament()] += 1
    print(f" {N_SIMS} ✓\n")

    W     = 40          # histogram bar max width
    maxw  = max(wins.values()) if wins else 1

    hdr = f"  {'PLAYER':<44}  {'W':>3}  {'%':>5}   HISTOGRAM"
    sep = f"  {'─'*44}  {'─'*3}  {'─'*5}   {'─'*W}"
    print(hdr)
    print(sep)

    for pid in range(N_PLAYERS):
        w     = wins.get(pid, 0)
        pct   = w / N_SIMS * 100
        bar   = '█' * int(W * w / maxw)
        label, simple = LABELS[pid]
        tag   = "  ← YOU" if simple else ""
        print(f"  {label+tag:<44}  {w:>3}  {pct:>4.1f}%   {bar}")

    print(sep)
    print()

    champ = max(range(N_PLAYERS), key=lambda i: wins.get(i, 0))
    clabel, csimple = LABELS[champ]
    print(f"  🏆  CHAMPION: {clabel}  ({wins[champ]} / {N_SIMS} wins)")
    if csimple:
        print("  ⚡  CHAOS REIGNS — the mindless shover took the crown!")
        print("      (variance is a helluva drug)")
    else:
        print("  💡  Skill & strategy humiliated the all-in maniac.")
    print()


if __name__ == '__main__':
    random.seed(42)
    main()
