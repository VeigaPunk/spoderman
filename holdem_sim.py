#!/usr/bin/env python3
"""
Texas Hold'em Poker — 6-player Tournament Simulation
Player 1  : Simple all-in maniac
Players 2-6: Elaborate strategies (TAG, LAG, Positional, GTO-Approx, Adaptive Shark)
Run 100 tournaments; histogram shows who dominated.
"""

import random
import itertools
from collections import Counter

# ── Card primitives ───────────────────────────────────────────────────────────
RANKS    = '23456789TJQKA'
SUITS    = 'shdc'
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}

def make_deck():
    return [(r, s) for r in RANKS for s in SUITS]

# ── Hand evaluation ───────────────────────────────────────────────────────────
def hand_rank(five_cards):
    vals  = sorted([RANK_VAL[c[0]] for c in five_cards], reverse=True)
    suits = [c[1] for c in five_cards]
    flush    = len(set(suits)) == 1
    straight = len(set(vals)) == 5 and vals[0] - vals[4] == 4
    if set(vals) == {14, 2, 3, 4, 5}:
        straight, vals = True, [5, 4, 3, 2, 1]
    cnt  = Counter(vals)
    grp  = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    gv   = [v for v, _ in grp]
    gc   = [c for _, c in grp]
    if straight and flush: return (8, vals)
    if gc[0] == 4:         return (7, gv)
    if gc[:2] == [3, 2]:   return (6, gv)
    if flush:              return (5, vals)
    if straight:           return (4, vals)
    if gc[0] == 3:         return (3, gv)
    if gc[:2] == [2, 2]:   return (2, gv)
    if gc[0] == 2:         return (1, gv)
    return (0, vals)

def best_of_seven(cards):
    return max(hand_rank(combo) for combo in itertools.combinations(cards, 5))

# ── Monte Carlo equity estimate ───────────────────────────────────────────────
def mc_equity(hole, board, n_opp, n_sim=100):
    dead  = set(map(tuple, list(hole) + list(board)))
    deck  = [c for c in make_deck() if tuple(c) not in dead]
    wins  = 0
    for _ in range(n_sim):
        d = deck[:]
        random.shuffle(d)
        needed   = 5 - len(board)
        full_brd = list(board) + d[:needed]
        d        = d[needed:]
        my_hand  = best_of_seven(list(hole) + full_brd)
        won = True
        for _ in range(n_opp):
            if len(d) < 2:
                break
            opp = best_of_seven(d[:2] + full_brd)
            d   = d[2:]
            if opp > my_hand:
                won = False
                break
        if won:
            wins += 1
    return wins / n_sim

# ── Player ────────────────────────────────────────────────────────────────────
class Player:
    def __init__(self, pid, chips, strategy):
        self.pid       = pid
        self.chips     = chips
        self.strategy  = strategy
        self.hole      = []
        self.folded    = False
        self.all_in    = False
        self.round_bet = 0  # chips committed this betting round

    def reset(self):
        self.hole      = []
        self.folded    = False
        self.all_in    = False
        self.round_bet = 0

# ── Game engine ───────────────────────────────────────────────────────────────
class HoldEm:
    def __init__(self, players, sb=10, bb=20):
        self.players = players
        self.sb      = sb
        self.bb      = bb
        self.btn     = 0
        self.pot     = 0
        self.board   = []

    def alive(self):
        return [p for p in self.players if p.chips > 0]

    def play_hand(self):
        alive = self.alive()
        n     = len(alive)
        if n < 2:
            return

        for p in alive:
            p.reset()
        self.pot   = 0
        self.board = []

        deck = make_deck()
        random.shuffle(deck)
        for p in alive:
            p.hole = [deck.pop(), deck.pop()]

        # Post blinds
        if n == 2:
            sb_idx, bb_idx = self.btn % n, (self.btn + 1) % n
        else:
            sb_idx, bb_idx = (self.btn + 1) % n, (self.btn + 2) % n

        self._post(alive[sb_idx], self.sb)
        self._post(alive[bb_idx], self.bb)

        # Pre-flop: action starts left of BB
        start = self.btn % n if n == 2 else (self.btn + 3) % n
        if not self._betting_round(alive, start, self.bb):
            self._showdown(alive)
            self.btn = (self.btn + 1) % max(len(self.alive()), 1)
            return

        # Flop, Turn, River
        draws = [3, 1, 1]
        for street in draws:
            self.board += [deck.pop() for _ in range(street)]
            for p in alive:
                if not p.folded:
                    p.round_bet = 0
            post_start = (self.btn + 1) % n
            if not self._betting_round(alive, post_start, 0):
                break

        self._showdown(alive)
        self.btn = (self.btn + 1) % max(len(self.alive()), 1)

    def _post(self, player, amount):
        amount          = min(amount, player.chips)
        player.chips   -= amount
        player.round_bet = amount
        self.pot       += amount
        if player.chips == 0:
            player.all_in = True

    def _betting_round(self, players, start_idx, current_max):
        """Returns True if round completed normally, False if hand ended early."""
        n    = len(players)
        need = {p.pid for p in players if not p.folded and not p.all_in}

        safety = 0
        idx    = start_idx

        while need and safety < n * 8:
            safety += 1
            p = players[idx % n]
            idx += 1

            if p.pid not in need:
                continue

            still_in = [x for x in players if not x.folded]
            if len(still_in) == 1:
                still_in[0].chips += self.pot
                self.pot = 0
                return False

            opps    = [x for x in players if not x.folded and x.pid != p.pid]
            to_call = max(0, current_max - p.round_bet)

            action, val = p.strategy.decide(
                p, self.board, self.pot, to_call, current_max, opps
            )

            # Invalid check → treat as call/check depending on to_call
            if action == 'check' and to_call > 0:
                action = 'call'

            if action == 'fold':
                p.folded = True
                need.discard(p.pid)
                remaining = [x for x in players if not x.folded]
                if len(remaining) == 1:
                    remaining[0].chips += self.pot
                    self.pot = 0
                    return False

            elif action == 'call':
                contrib    = min(to_call, p.chips)
                p.chips   -= contrib
                p.round_bet += contrib
                self.pot  += contrib
                if p.chips == 0:
                    p.all_in = True
                need.discard(p.pid)

            elif action == 'raise':
                # val = desired total round_bet after raise
                new_total = max(val, current_max + 1)
                new_total = min(new_total, p.chips + p.round_bet)
                contrib   = min(new_total - p.round_bet, p.chips)
                p.chips   -= contrib
                p.round_bet += contrib
                self.pot  += contrib
                if p.chips == 0:
                    p.all_in = True
                current_max = p.round_bet
                need.discard(p.pid)
                for other in players:
                    if other.pid != p.pid and not other.folded and not other.all_in:
                        need.add(other.pid)

            elif action == 'check':
                need.discard(p.pid)

        return True

    def _showdown(self, players):
        in_hand = [p for p in players if not p.folded]
        if len(in_hand) == 1:
            in_hand[0].chips += self.pot
            self.pot = 0
            return
        evals   = {p.pid: best_of_seven(p.hole + self.board) for p in in_hand}
        best    = max(evals.values())
        winners = [p for p in in_hand if evals[p.pid] == best]
        share, rem = divmod(self.pot, len(winners))
        for i, w in enumerate(winners):
            w.chips += share + (rem if i == 0 else 0)
        self.pot = 0


# ══════════════════════════════════════════════════════════════════════════════
#  STRATEGIES
# ══════════════════════════════════════════════════════════════════════════════

# ── Strategy 1: Simple ────────────────────────────────────────────────────────
class AlwaysAllIn:
    """
    if my_turn
        bet = All in
    fi
    """
    name = "Always All-In (maniac)"

    def decide(self, player, board, pot, to_call, cur_max, opps):
        return ('raise', player.chips + player.round_bet)


# ── Strategy 2: Tight-Aggressive ─────────────────────────────────────────────
class TightAggressive:
    """
    TAG — premium hands only pre-flop, value-bets hard when equity > 60%.
    Folds to pressure when behind. The disciplined grinder.
    """
    name = "Tight-Aggressive (TAG)"

    PREMIUM = {
        frozenset({'A', 'A'}), frozenset({'K', 'K'}), frozenset({'Q', 'Q'}),
        frozenset({'J', 'J'}), frozenset({'T', 'T'}), frozenset({'A', 'K'}),
        frozenset({'A', 'Q'}), frozenset({'A', 'J'}), frozenset({'K', 'Q'}),
    }

    def _tier(self, hole):
        r1, r2 = hole[0][0], hole[1][0]
        if frozenset({r1, r2}) in self.PREMIUM:
            return 2
        v1, v2 = RANK_VAL[r1], RANK_VAL[r2]
        if r1 == r2 and v1 >= 7:
            return 1
        if min(v1, v2) >= 10 and abs(v1 - v2) <= 2:
            return 1
        return 0

    def decide(self, player, board, pot, to_call, cur_max, opps):
        tier = self._tier(player.hole)

        if not board:  # pre-flop
            if tier == 2:
                target = max(cur_max * 3, 60)
                return ('raise', min(target, player.chips + player.round_bet))
            if tier == 1:
                if to_call == 0:
                    return ('check', 0)
                if to_call <= pot * 0.15:
                    return ('call', to_call)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        # post-flop: monte carlo equity
        eq = mc_equity(player.hole, board, len(opps), 80)
        if eq > 0.60:
            bet = int(pot * 0.75)
            return ('raise', player.round_bet + min(bet, player.chips))
        if eq > 0.40:
            if to_call == 0:
                return ('check', 0)
            if to_call <= pot * 0.30:
                return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 3: Loose-Aggressive ─────────────────────────────────────────────
class LooseAggressive:
    """
    LAG — plays wide, attacks pots with frequent bets and bluffs.
    Balances aggression with equity reads via Monte Carlo.
    Exploits passive opponents; volatile bankroll swings.
    """
    name = "Loose-Aggressive (LAG)"

    def decide(self, player, board, pot, to_call, cur_max, opps):
        v1 = RANK_VAL[player.hole[0][0]]
        v2 = RANK_VAL[player.hole[1][0]]
        suited  = player.hole[0][1] == player.hole[1][1]
        is_pair = v1 == v2

        if not board:  # pre-flop
            score = (v1 + v2) / 2 + (2 if suited else 0) + (4 if is_pair else 0)
            play  = score >= 9 or random.random() < 0.28
            if play:
                if random.random() < 0.60:
                    target = int(cur_max * 2.5 + 20)
                    return ('raise', min(target, player.chips + player.round_bet))
                return ('call', min(to_call, player.chips))
            if to_call == 0:
                return ('check', 0)
            if to_call <= player.chips * 0.06:
                return ('call', to_call)
            return ('fold', 0)

        eq = mc_equity(player.hole, board, len(opps), 60)

        if eq > 0.50:
            bet = int(pot * random.uniform(0.6, 1.0))
            return ('raise', player.round_bet + min(bet, player.chips))
        if eq > 0.30:
            if to_call == 0:
                # occasional bluff c-bet
                if random.random() < 0.30:
                    return ('raise', player.round_bet + int(pot * 0.55))
                return ('check', 0)
            if to_call <= pot * 0.40:
                return ('call', to_call)
        if to_call == 0:
            # pure bluff
            if random.random() < 0.22:
                return ('raise', player.round_bet + int(pot * 0.50))
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 4: Position-Aware ────────────────────────────────────────────────
class PositionalAware:
    """
    Uses table position as the primary filter.
    Early position: plays only the top 10% of hands.
    Late position: opens up to 35%, steals blinds aggressively.
    Adjusts post-flop bet sizing by position and board texture.
    """
    name = "Position-Aware"

    def _pos_from_opp_count(self, n_opps):
        total = n_opps + 1
        if total <= 2:
            return 'late'
        if total <= 4:
            return 'middle'
        return 'early'

    def _preflop_ok(self, hole, pos):
        vals = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
        hi, lo   = vals
        is_pair  = hi == lo
        suited   = hole[0][1] == hole[1][1]
        if pos == 'late':
            return is_pair or hi >= 10 or (hi >= 9 and lo >= 7 and suited) or hi >= 12
        if pos == 'middle':
            return (is_pair and hi >= 7) or hi >= 12 or (hi >= 11 and lo >= 9)
        # early: very tight
        return (is_pair and hi >= 10) or (hi >= 13 and lo >= 12)

    def decide(self, player, board, pot, to_call, cur_max, opps):
        pos = self._pos_from_opp_count(len(opps))

        if not board:
            ok = self._preflop_ok(player.hole, pos)
            if ok:
                if pos == 'late' and to_call == 0:
                    bet = max(cur_max * 2, 40)
                    return ('raise', player.round_bet + min(bet, player.chips))
                if to_call <= player.chips * 0.10:
                    return ('call', min(to_call, player.chips))
                return ('fold', 0)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq = mc_equity(player.hole, board, len(opps), 90)

        if eq > 0.55 and pos == 'late':
            bet = int(pot * 0.70)
            return ('raise', player.round_bet + min(bet, player.chips))
        if eq > 0.42:
            if to_call == 0:
                return ('check', 0)
            if to_call <= pot * 0.35:
                return ('call', to_call)
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 5: GTO-Approximate ──────────────────────────────────────────────
class GTOApprox:
    """
    Implements a mixed strategy inspired by GTO principles:
    - Pot odds vs. equity thresholds drive every decision
    - Balanced betting ranges: value bets + bluffs at fixed frequencies
    - Raises sized to create correct EV across opponent calling ranges
    - Randomizes bet size to remain unexploitable
    """
    name = "GTO-Approximate"

    def _preflop_score(self, hole):
        v1, v2 = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
        score  = v1 + v2 * 0.8
        if v1 == v2:                                   score += v1 * 1.2
        if hole[0][1] == hole[1][1]:                   score += 4
        if abs(v1 - v2) <= 2 and v1 != v2:            score += 3
        return score

    def decide(self, player, board, pot, to_call, cur_max, opps):
        if not board:
            sc = self._preflop_score(player.hole)
            if sc >= 24:
                target = cur_max * 3 + 20
                return ('raise', min(target, player.chips + player.round_bet))
            pot_odds = to_call / (pot + to_call + 1) if to_call > 0 else 0
            if sc >= 18 and pot_odds < 0.30:
                return ('call', min(to_call, player.chips))
            if to_call == 0:
                return ('check', 0)
            if sc >= 14 and pot_odds < 0.13 and random.random() < 0.45:
                return ('call', min(to_call, player.chips))
            return ('fold', 0)

        eq       = mc_equity(player.hole, board, len(opps), 120)
        pot_odds = to_call / (pot + to_call + 1) if to_call > 0 else 0

        if eq > pot_odds + 0.12:
            if eq > 0.65:
                # strong value bet
                bet = int(pot * random.uniform(0.55, 0.90))
                return ('raise', player.round_bet + min(bet, player.chips))
            if to_call == 0:
                bet = int(pot * random.uniform(0.30, 0.60))
                return ('raise', player.round_bet + min(bet, player.chips))
            return ('call', min(to_call, player.chips))

        if eq > pot_odds:
            if to_call == 0:
                return ('check', 0)
            return ('call', min(to_call, player.chips))

        if to_call == 0:
            # balanced bluff frequency ≈ 18%
            if random.random() < 0.18:
                return ('raise', player.round_bet + int(pot * 0.40))
            return ('check', 0)
        return ('fold', 0)


# ── Strategy 6: Adaptive Shark ────────────────────────────────────────────────
class AdaptiveShark:
    """
    Stack-aware exploitative play:
    - Bullies short stacks when holding a chip advantage (2x average)
    - Tightens range when short-stacked to avoid coin flips
    - Tracks pot-commitment thresholds dynamically
    - Mixes semi-bluffs with nut-flush and open-ended draws
    - Adjusts bet sizing based on fold equity estimates
    """
    name = "Adaptive Shark"

    def decide(self, player, board, pot, to_call, cur_max, opps):
        if not opps:
            return ('check', 0)

        avg_opp    = sum(o.chips for o in opps) / len(opps)
        stack_edge = player.chips / max(avg_opp, 1)

        v1, v2 = sorted([RANK_VAL[c[0]] for c in player.hole], reverse=True)
        is_pair = v1 == v2
        suited  = player.hole[0][1] == player.hole[1][1]

        if not board:
            play = (is_pair or v1 >= 12 or
                    (v1 >= 11 and v2 >= 9) or
                    (v1 >= 10 and suited and v2 >= 8))

            if play:
                if stack_edge >= 1.5 and cur_max > 0:
                    # Pressure smaller stacks
                    target = min(cur_max * 4, player.chips + player.round_bet)
                    return ('raise', target)
                if to_call == 0:
                    bet = random.choice([20, 40, 60])
                    return ('raise', player.round_bet + min(bet, player.chips))
                if to_call <= player.chips * 0.12:
                    return ('call', min(to_call, player.chips))
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        eq       = mc_equity(player.hole, board, len(opps), 110)
        pot_odds = to_call / (pot + to_call + 1) if to_call > 0 else 0

        if stack_edge >= 2.0:
            # Big-stack bully mode
            if eq > 0.33 or (to_call == 0 and random.random() < 0.40):
                bet = int(pot * 0.85)
                return ('raise', player.round_bet + min(bet, player.chips))
            if to_call > 0 and to_call <= pot * 0.22:
                return ('call', to_call)
            if to_call == 0:
                return ('check', 0)
            return ('fold', 0)

        if eq > pot_odds + 0.15:
            bet = int(pot * 0.70)
            return ('raise', player.round_bet + min(bet, player.chips))
        if eq > pot_odds:
            if to_call == 0:
                return ('check', 0)
            return ('call', min(to_call, player.chips))
        if to_call == 0:
            return ('check', 0)
        return ('fold', 0)


# ── Tournament runner ─────────────────────────────────────────────────────────
def make_strategies():
    return [
        AlwaysAllIn(),
        TightAggressive(),
        LooseAggressive(),
        PositionalAware(),
        GTOApprox(),
        AdaptiveShark(),
    ]

def run_tournament(starting_chips=1500, sb=10, bb=20):
    strats  = make_strategies()
    players = [Player(i + 1, starting_chips, strats[i]) for i in range(6)]
    game    = HoldEm(players, sb, bb)

    hand_no = 0
    while len(game.alive()) > 1 and hand_no < 2000:
        game.play_hand()
        hand_no += 1
        # Escalating blinds every 30 hands
        if hand_no % 30 == 0:
            game.sb = int(game.sb * 1.5)
            game.bb = int(game.bb * 1.5)

    alive = game.alive()
    return alive[0].pid if alive else None


# ── 100-tournament simulation ─────────────────────────────────────────────────
def run_sims(n=100):
    strats = make_strategies()
    names  = {i + 1: s.name for i, s in enumerate(strats)}
    wins   = Counter()

    W = 68
    print()
    print('═' * W)
    print('  TEXAS HOLD\'EM — 100-TOURNAMENT SIMULATION')
    print('  6 players, equal starting stacks (1500 chips each)')
    print('  Escalating blinds; last player standing wins the tournament')
    print('═' * W)
    print()
    for pid in range(1, 7):
        tag = '  ◄── THE MANIAC' if pid == 1 else ''
        print(f'  Player {pid}  {names[pid]}{tag}')
    print()
    print('Running', end='', flush=True)

    for t in range(n):
        w = run_tournament()
        if w:
            wins[w] += 1
        if (t + 1) % 10 == 0:
            print(f' {t + 1}', end='', flush=True)

    print('\n')
    print('═' * W)
    print('  WINNER WINNER CHICKEN DINNER  —  HISTOGRAM')
    print('  (each █ ≈ 1 tournament win)')
    print('═' * W)

    max_w   = max(wins.values()) if wins else 1
    BAR_MAX = 44

    for pid in range(1, 7):
        w    = wins.get(pid, 0)
        pct  = w / n * 100
        bar  = '█' * int(w / max_w * BAR_MAX)
        pad  = '░' * (BAR_MAX - len(bar))
        tag  = '  ◄ ALL-IN MANIAC' if pid == 1 else ''
        lbl  = names[pid]
        print(f'  P{pid} [{lbl:30s}] {bar}{pad}  {w:3d} ({pct:5.1f}%){tag}')

    print('═' * W)

    champ_pid, champ_wins = wins.most_common(1)[0]
    print(f'\n  CHAMPION  ▶  Player {champ_pid} — {names[champ_pid]}')
    print(f'             {champ_wins} tournament victories out of {n}\n')

    rank = [pid for pid, _ in wins.most_common()]
    if 1 in rank:
        r = rank.index(1) + 1
        if r == 1:
            verdict = "Even a stopped clock is right twice a day. Chaos WON?!"
        elif r <= 2:
            verdict = "Top-2 finish. Lucky chaos, but logic still leads overall."
        elif r <= 3:
            verdict = f"Rank #{r}/6 — barely survived. Strategy still rules."
        else:
            verdict = (f"Rank #{r}/6 — HUMILIATED by players who can actually think. "
                       f"All-in every hand: {wins.get(1,0)} wins. Pathetic.")
    else:
        verdict = "Zero wins. The All-In Maniac won NOTHING. Absolutely obliterated."

    print(f'  All-In Maniac report : {verdict}')
    print(f'\n  Suflair GPT status   : OBLITERATED.')
    print(f'  Poker requires a BRAIN, not a coin flip.\n')
    print('═' * W)


if __name__ == '__main__':
    random.seed(42)
    run_sims(100)
