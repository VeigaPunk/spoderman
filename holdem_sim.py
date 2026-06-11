#!/usr/bin/env python3
"""
Texas Hold'em Poker Tournament Simulation
Player 1 : Simple All-In every turn
Players 2-6: Elaborate strategies
100 tournaments, all players start with equal chips.
Outputs histogram of last-man-standing.
"""

import random
import sys
from collections import Counter, defaultdict
from itertools import combinations

# ─────────────────────────────────────────────────────────────────────────────
# Card primitives
# ─────────────────────────────────────────────────────────────────────────────

RANKS  = "23456789TJQKA"
SUITS  = "cdhs"
RANK_V = {r: i for i, r in enumerate(RANKS, 2)}   # '2'→2 … 'A'→14

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ─────────────────────────────────────────────────────────────────────────────
# Hand evaluator  (returns comparable tuple — higher is better)
# ─────────────────────────────────────────────────────────────────────────────

def _hand_score(five):
    ranks = sorted([RANK_V[c[0]] for c in five], reverse=True)
    suits = [c[1] for c in five]

    flush    = len(set(suits)) == 1
    straight = (max(ranks) - min(ranks) == 4 and len(set(ranks)) == 5)
    if set(ranks) == {14, 2, 3, 4, 5}:          # wheel
        straight, ranks = True, [5, 4, 3, 2, 1]

    cnt     = Counter(ranks)
    groups  = sorted(cnt.values(), reverse=True)
    ordered = sorted(cnt, key=lambda r: (cnt[r], r), reverse=True)

    if straight and flush: return (8, ranks)
    if groups[0] == 4:     return (7, ordered)
    if groups[:2]==[3,2]:  return (6, ordered)
    if flush:              return (5, ranks)
    if straight:           return (4, ranks)
    if groups[0] == 3:     return (3, ordered)
    if groups[:2]==[2,2]:  return (2, ordered)
    if groups[0] == 2:     return (1, ordered)
    return (0, ranks)

def best_of_7(cards):
    return max(_hand_score(combo) for combo in combinations(cards, 5))

# ─────────────────────────────────────────────────────────────────────────────
# Monte-Carlo equity estimator
# ─────────────────────────────────────────────────────────────────────────────

def equity(hole, board, n_opps, n_samples=30):
    """Win probability estimate via Monte Carlo."""
    deck  = [c for c in make_deck() if c not in hole and c not in board]
    wins  = 0
    for _ in range(n_samples):
        d  = deck[:]
        random.shuffle(d)
        sim_board = board + d[:5 - len(board)]
        tail      = d[5 - len(board):]
        my_score  = best_of_7(hole + sim_board)
        i_win = True
        for k in range(min(n_opps, len(tail) // 2)):
            opp_score = best_of_7([tail[k*2], tail[k*2+1]] + sim_board)
            if opp_score >= my_score:
                i_win = False
                break
        if i_win:
            wins += 1
    return wins / n_samples

# ─────────────────────────────────────────────────────────────────────────────
# Player
# ─────────────────────────────────────────────────────────────────────────────

class Player:
    def __init__(self, pid, chips, strategy):
        self.pid      = pid
        self.chips    = chips
        self.strategy = strategy
        self.hole     = []
        self.folded   = False
        self.allin    = False
        self.bet      = 0          # chips committed this round

    def reset(self):
        self.hole   = []
        self.folded = False
        self.allin  = False
        self.bet    = 0

# ─────────────────────────────────────────────────────────────────────────────
# Strategy helpers
# ─────────────────────────────────────────────────────────────────────────────

def _gs(player, board, pot, to_call, stage, position, n_opps, raises=0):
    return dict(board=board, pot=pot, to_call=to_call,
                stage=stage, position=position, n_opps=n_opps,
                raises=raises)

# ── 1. Simple: ALWAYS ALL-IN ─────────────────────────────────────────────────

def strat_maniac(player, gs):
    """bet ALL the chips, every single time."""
    return ('raise', player.chips)

# ── 2. GTO-inspired ──────────────────────────────────────────────────────────

def strat_gto(player, gs):
    """
    Pot-odds + equity baseline.
    Raises when equity exceeds pot-odds by a margin.
    Bluffs at low frequency to stay balanced.
    """
    eq  = equity(player.hole, gs['board'], gs['n_opps'], n_samples=28)
    pot = gs['pot']
    tc  = gs['to_call']
    pot_odds = tc / (pot + tc) if tc > 0 else 0.0

    if tc == 0:
        if eq > 0.68:
            return ('raise', min(int(pot * 0.75), player.chips))
        if eq > 0.38 or random.random() < 0.12:   # bluff 12%
            sz = int(pot * random.uniform(0.4, 0.8))
            if sz > 0:
                return ('raise', min(sz, player.chips))
        return ('call', 0)   # check
    else:
        if eq > pot_odds + 0.08:
            if eq > 0.78:
                return ('raise', min(int(pot * 0.9), player.chips))
            return ('call', min(tc, player.chips))
        if eq > pot_odds - 0.04:
            return ('call', min(tc, player.chips))
        return ('fold', 0)

# ── 3. Tight-Aggressive (TAG) ─────────────────────────────────────────────────

def strat_tag(player, gs):
    """
    Plays premium/strong hands only. Folds trash.
    When in, bets large. Respects re-raises.
    """
    hole = player.hole
    r1, r2 = RANK_V[hole[0][0]], RANK_V[hole[1][0]]
    suited = hole[0][1] == hole[1][1]
    hi, lo = max(r1, r2), min(r1, r2)
    pos    = gs['position']   # 0=early 1=mid 2=late
    tc     = gs['to_call']
    pot    = gs['pot']
    n_opps = gs['n_opps']

    if gs['stage'] == 'preflop':
        premium  = (hi >= 13 and lo >= 12) or (hi == 14 and lo >= 11) or (hi == lo >= 10)
        strong   = hi >= 12 or hi == lo >= 7 or (suited and hi >= 11 and lo >= 9)
        playable = (hi >= 10 and lo >= 8) or hi == lo >= 5 or (suited and hi - lo <= 2 and hi >= 8)

        if premium:
            bet = max(tc * 3, int(pot * 2.5) + tc)
            return ('raise', min(bet, player.chips))
        if strong and pos >= 1:
            if tc > player.chips * 0.18:
                return ('fold', 0)
            return ('call', min(tc, player.chips))
        if playable and pos == 2:
            if tc > player.chips * 0.10:
                return ('fold', 0)
            return ('call', min(tc, player.chips))
        if tc == 0:
            return ('call', 0)
        return ('fold', 0)

    eq = equity(hole, gs['board'], n_opps, n_samples=22)
    if tc == 0:
        if eq > 0.60:
            return ('raise', min(int(pot * 0.85), player.chips))
        return ('call', 0)
    if eq > 0.58:
        return ('raise', min(int(pot * 0.90), player.chips))
    if eq > 0.38 and tc <= player.chips * 0.22:
        return ('call', min(tc, player.chips))
    return ('fold', 0)

# ── 4. Loose-Aggressive (LAG) ────────────────────────────────────────────────

def strat_lag(player, gs):
    """
    Wide range, constant pressure. Bluffs often. Steals in late position.
    Forces opponents into tough spots by making many pots huge.
    """
    hole   = player.hole
    tc     = gs['to_call']
    pot    = gs['pot']
    pos    = gs['position']
    n_opps = gs['n_opps']
    eq     = equity(hole, gs['board'], n_opps, n_samples=18)
    bluff  = 0.38 if pos == 2 else 0.22

    if tc == 0:
        if eq > 0.50 or random.random() < bluff:
            sz = int(pot * random.uniform(0.55, 1.25))
            return ('raise', min(max(sz, 1), player.chips))
        return ('call', 0)

    fold_thresh = 0.10 if pos >= 1 else 0.16
    if eq < fold_thresh and random.random() > bluff:
        return ('fold', 0)
    if eq > 0.45 or (random.random() < bluff and tc < player.chips * 0.35):
        sz = int((pot + tc) * random.uniform(0.65, 1.55))
        return ('raise', min(max(sz, tc), player.chips))
    if tc <= player.chips * 0.28:
        return ('call', min(tc, player.chips))
    return ('fold', 0)

# ── 5. Slow-play Trapper ──────────────────────────────────────────────────────

def strat_trapper(player, gs):
    """
    Checks monsters early to induce bluffs; springs the trap on turn/river.
    Calls wide early, raises big late. Folds marginal hands quietly.
    """
    hole   = player.hole
    tc     = gs['to_call']
    pot    = gs['pot']
    stage  = gs['stage']
    n_opps = gs['n_opps']
    late   = stage in ('turn', 'river')
    eq     = equity(hole, gs['board'], n_opps, n_samples=22)

    if tc == 0:
        if eq > 0.82 and not late:
            return ('call', 0)              # slow-play: check the monster
        if eq > 0.72:
            return ('raise', min(int(pot * 1.15), player.chips))
        if eq > 0.42:
            return ('raise', min(int(pot * 0.50), player.chips))
        return ('call', 0)

    if eq > 0.78 and not late:
        return ('call', min(tc, player.chips))   # disguise strength
    if eq > 0.68:
        return ('raise', min(int(pot * 1.45), player.chips))
    if eq > 0.32 and tc <= player.chips * 0.20:
        return ('call', min(tc, player.chips))
    return ('fold', 0)

# ── 6. Position-Pro ───────────────────────────────────────────────────────────

def strat_position(player, gs):
    """
    Position is everything. Iron-tight UTG, steal-happy on the button.
    Adjusts aggression dynamically with table pressure (raises_faced).
    Respects 3-bets from tight seats.
    """
    hole    = player.hole
    tc      = gs['to_call']
    pot     = gs['pot']
    pos     = gs['position']       # 0 early · 1 mid · 2 late/button
    n_opps  = gs['n_opps']
    raises  = gs['raises']
    eq      = equity(hole, gs['board'], n_opps, n_samples=22)
    pos_bonus = [0.0, 0.07, 0.18][pos]
    adj     = min(eq + pos_bonus, 1.0) * (0.70 if raises >= 2 else 1.0)
    fold_t  = [0.52, 0.40, 0.27][pos]
    raise_t = [0.76, 0.64, 0.54][pos]

    if tc == 0:
        if adj > raise_t:
            sz = int(pot * random.uniform(0.60, 1.00))
            return ('raise', min(max(sz, 1), player.chips))
        if adj > fold_t:
            if pos == 2 and random.random() < 0.38:   # button steal
                return ('raise', min(int(pot * 0.65), player.chips))
            return ('call', 0)
        return ('call', 0)

    if adj > raise_t:
        return ('raise', min(int(pot * 1.00), player.chips))
    if adj > fold_t and tc <= player.chips * 0.30:
        return ('call', min(tc, player.chips))
    return ('fold', 0)

# ─────────────────────────────────────────────────────────────────────────────
# Strategy registry
# ─────────────────────────────────────────────────────────────────────────────

STRATEGY_FN = {
    1: strat_maniac,
    2: strat_gto,
    3: strat_tag,
    4: strat_lag,
    5: strat_trapper,
    6: strat_position,
}

STRATEGY_NAME = {
    1: "AllIn-Maniac",
    2: "GTO-Solver  ",
    3: "TAG-Sniper  ",
    4: "LAG-Bully   ",
    5: "Trapper     ",
    6: "Position-Pro",
}

# ─────────────────────────────────────────────────────────────────────────────
# Game engine
# ─────────────────────────────────────────────────────────────────────────────

class HoldemTournament:
    def __init__(self, n_players=6, chips=1000, small_blind=10):
        self.n   = n_players
        self.sb  = small_blind
        self.bb  = small_blind * 2
        self.players = [Player(i+1, chips, STRATEGY_FN[i+1]) for i in range(n_players)]
        self.btn = 0

    def _alive(self):
        return [p for p in self.players if p.chips > 0]

    def _deal_hand(self):
        deck = make_deck()
        random.shuffle(deck)
        alive = self._alive()
        for i, p in enumerate(alive):
            p.reset()
            p.hole = [deck[i*2], deck[i*2+1]]
        return deck, alive

    def _post_blinds(self, alive):
        n   = len(alive)
        sb  = alive[self.btn % n]
        bb  = alive[(self.btn+1) % n]
        sb_amt = min(self.sb, sb.chips)
        bb_amt = min(self.bb, bb.chips)
        sb.chips -= sb_amt; sb.bet = sb_amt
        bb.chips -= bb_amt; bb.bet = bb_amt
        if sb.chips == 0: sb.allin = True
        if bb.chips == 0: bb.allin = True
        return sb_amt + bb_amt, bb_amt

    def _can_act(self, p):
        return not p.folded and not p.allin and p.chips > 0

    def _betting_round(self, alive, first_idx, pot, street_bet, board, stage):
        n        = len(alive)
        raises   = 0
        acted    = set()
        idx      = first_idx % n
        guard    = n * 6

        for _ in range(guard):
            p = alive[idx % n]
            idx += 1

            if not self._can_act(p):
                continue

            tc = max(0, street_bet - p.bet)

            # position class (rough)
            active_cnt = sum(1 for x in alive if not x.folded)
            pos_class  = min(2, (2 * ((idx-1) % max(active_cnt,1))) // max(active_cnt,1))

            n_opps = sum(1 for x in alive if not x.folded and x.pid != p.pid)
            gs = dict(board=board, pot=pot, to_call=tc, stage=stage,
                      position=pos_class, n_opps=max(n_opps, 1), raises=raises)

            action, amount = p.strategy(p, gs)

            if action == 'fold':
                p.folded = True

            elif action == 'call':
                amt = min(tc, p.chips)
                p.chips -= amt
                p.bet   += amt
                pot     += amt
                if p.chips == 0:
                    p.allin = True

            elif action == 'raise':
                # amount is extra on top of call, but we cap at chips
                total = min(max(amount, tc), p.chips)
                p.chips -= total
                p.bet   += total
                pot     += total
                if p.chips == 0:
                    p.allin = True
                if p.bet > street_bet:
                    street_bet = p.bet
                    raises    += 1
                    acted      = {p.pid}   # everyone must act again

            acted.add(p.pid)

            # end-of-round check
            still_to_act = [
                x for x in alive
                if not x.folded and not x.allin and x.chips > 0
                and (x.bet < street_bet or x.pid not in acted)
            ]
            if not still_to_act:
                break

        return pot, street_bet

    def _showdown(self, alive, board, pot):
        contenders = [p for p in alive if not p.folded]
        if not contenders:
            return
        if len(contenders) == 1:
            contenders[0].chips += pot
            return
        scored = []
        for p in contenders:
            all_cards = p.hole + board
            sc = best_of_7(all_cards) if len(all_cards) >= 5 else _hand_score(all_cards)
            scored.append((sc, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][0]
        winners = [p for sc, p in scored if sc == best]
        share, rem = divmod(pot, len(winners))
        for w in winners:
            w.chips += share
        winners[0].chips += rem

    def play_hand(self):
        deck, alive = self._deal_hand()
        if len(alive) < 2:
            return
        n   = len(alive)
        pot, street_bet = self._post_blinds(alive)
        board    = []
        card_ptr = [n * 2]

        def draw(k):
            cards = deck[card_ptr[0]: card_ptr[0]+k]
            card_ptr[0] += k
            return cards

        stages_info = [
            ('preflop', 0, (self.btn+2) % n),
            ('flop',    3, (self.btn+1) % n),
            ('turn',    1, (self.btn+1) % n),
            ('river',   1, (self.btn+1) % n),
        ]

        for stage, n_cards, first_idx in stages_info:
            board += draw(n_cards)

            # reset per-round bets on post-flop streets
            if stage != 'preflop':
                for p in alive:
                    p.bet = 0
                street_bet = 0

            pot, street_bet = self._betting_round(
                alive, first_idx, pot, street_bet, board, stage)

            active = [p for p in alive if not p.folded]
            if len(active) == 1:
                active[0].chips += pot
                self.btn = (self.btn + 1) % n
                return

            if sum(1 for p in active if not p.allin) <= 1:
                while len(board) < 5:
                    board += draw(1)
                break

        self._showdown(alive, board, pot)
        self.btn = (self.btn + 1) % n

    def run(self, hand_limit=15000):
        for _ in range(hand_limit):
            if len(self._alive()) <= 1:
                break
            self.play_hand()
        alive = self._alive()
        return alive[0].pid if alive else None

# ─────────────────────────────────────────────────────────────────────────────
# Simulation runner
# ─────────────────────────────────────────────────────────────────────────────

def simulate(n_sims=100, chips=1000):
    wins = defaultdict(int)
    for i in range(n_sims):
        t = HoldemTournament(n_players=6, chips=chips, small_blind=10)
        w = t.run()
        if w:
            wins[w] += 1
        if (i+1) % 20 == 0:
            print(f"  ... {i+1}/{n_sims} done", file=sys.stderr, flush=True)
    return wins

# ─────────────────────────────────────────────────────────────────────────────
# Histogram printer
# ─────────────────────────────────────────────────────────────────────────────

def histogram(wins, n_sims):
    BAR = 44
    total = sum(wins.values())

    print()
    print("╔" + "═"*63 + "╗")
    print("║   TEXAS HOLD'EM — 100 TOURNAMENT SIMULATIONS                 ║")
    print("║   Last Player Standing  •  Winner Winner Chicken Dinner      ║")
    print("╠" + "═"*63 + "╣")
    print("║  Player  Strategy        Wins  Pct   Bar                     ║")
    print("╠" + "═"*63 + "╣")

    peak = max(wins.values(), default=1)
    for pid in range(1, 7):
        w    = wins.get(pid, 0)
        pct  = w / n_sims * 100
        bar  = round(w / peak * BAR)
        blk  = "█" * bar
        mrkr = " ◄ ALL-IN MANIAC" if pid == 1 else ""
        name = STRATEGY_NAME[pid]
        print(f"║  P{pid}  {name}  {w:>3}  {pct:4.1f}%  {blk:<{BAR}}{mrkr}")

    print("╠" + "═"*63 + "╣")

    if wins:
        champ_id   = max(wins, key=wins.get)
        champ_name = STRATEGY_NAME[champ_id].strip()
        champ_w    = wins[champ_id]
        print(f"║  CHAMPION → P{champ_id}  {champ_name}  —  {champ_w} wins ({champ_w}%)")
        print("╠" + "═"*63 + "╣")
        if champ_id == 1:
            print("║  🤣  THE ALL-IN MANIAC WINS!!  SUFLAIR GPT OBLITERATED!!   ║")
            print("║     yolo > GTO confirmed. Quants are crying. Chaos wins.   ║")
        else:
            p1_w = wins.get(1, 0)
            print(f"║  Brains beat the cave-troll this time.                      ║")
            print(f"║  Maniac P1 only took {p1_w} of 100. Math holds.             ║")

    print("╚" + "═"*63 + "╝")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("━"*65)
    print("  Texas Hold'em Poker Simulation")
    print("  6 players · 1000 chips each · 100 tournaments")
    print()
    print("  P1  AllIn-Maniac   — bet ALL IN every single action")
    print("  P2  GTO-Solver     — pot-odds + equity balanced play")
    print("  P3  TAG-Sniper     — tight hand selection, big bets when in")
    print("  P4  LAG-Bully      — wide range, constant aggression, bluffs")
    print("  P5  Trapper        — slow-plays monsters, springs trap late")
    print("  P6  Position-Pro   — position-first, steals from button")
    print("━"*65)

    random.seed()   # true randomness
    wins = simulate(n_sims=100, chips=1000)
    histogram(wins, n_sims=100)
