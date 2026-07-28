"""No-limit Texas Hold'em tournament simulator.

6 players, identical starting stacks. Players 2-6 run elaborate strategies;
Player 1 runs: if my_turn then bet = ALL IN fi.
100 tournaments, histogram of winners.
"""

import random
import sys
from collections import Counter
from itertools import combinations

# ---------------------------------------------------------------- cards

def new_deck():
    return [(r, s) for r in range(2, 15) for s in range(4)]


def eval5(cards):
    ranks = sorted((c[0] for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    groups = sorted(Counter(ranks).items(), key=lambda x: (-x[1], -x[0]))
    ordered = tuple(r for r, n in groups for _ in range(n))
    uniq = sorted(set(ranks), reverse=True)
    sh = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            sh = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            sh = 5
    if flush and sh:
        return (8, sh)
    if groups[0][1] == 4:
        return (7,) + ordered
    if groups[0][1] == 3 and groups[1][1] == 2:
        return (6,) + ordered
    if flush:
        return (5,) + tuple(ranks)
    if sh:
        return (4, sh)
    if groups[0][1] == 3:
        return (3,) + ordered
    if groups[0][1] == 2 and groups[1][1] == 2:
        return (2,) + ordered
    if groups[0][1] == 2:
        return (1,) + ordered
    return (0,) + tuple(ranks)


def eval7(cards):
    return max(eval5(c) for c in combinations(cards, 5))


def chen(hole):
    (r1, s1), (r2, s2) = hole
    hi, lo = max(r1, r2), min(r1, r2)
    score = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}.get(hi, hi / 2.0)
    if r1 == r2:
        return max(score * 2, 5.0)
    if s1 == s2:
        score += 2
    gap = hi - lo - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and hi < 12:
        score += 1
    return score


def hand_info(hole, board):
    score = eval7(list(hole) + board)
    cat = score[0]
    btop = max(r for r, _ in board)
    hole_ranks = [r for r, _ in hole]
    top_pair = cat == 1 and btop in hole_ranks
    overpair = cat == 1 and hole_ranks[0] == hole_ranks[1] and hole_ranks[0] > btop
    suits = Counter(s for _, s in list(hole) + board)
    flush_draw = cat < 5 and max(suits.values()) == 4
    ranks = {r for r, _ in list(hole) + board}
    oesd = cat < 4 and any(len({x, x + 1, x + 2, x + 3} & ranks) == 4 for x in range(2, 12))
    return cat, (top_pair or overpair), flush_draw, oesd, score


def mc_equity(hole, board, n_opp, iters=36):
    dead = set(hole) | set(board)
    deck = [c for c in new_deck() if c not in dead]
    n_opp = min(n_opp, 3)
    need = 2 * n_opp + (5 - len(board))
    wins = 0.0
    for _ in range(iters):
        sample = random.sample(deck, need)
        full = board + sample[2 * n_opp:]
        mine = eval7(list(hole) + full)
        best_op = max(eval7(sample[2 * i:2 * i + 2] + full) for i in range(n_opp))
        if mine > best_op:
            wins += 1
        elif mine == best_op:
            wins += 0.5
    return wins / iters

# ---------------------------------------------------------------- strategies

class AllInMonkey:
    """Player 1: if my_turn then bet = All in fi"""
    name = "All-In Monkey"

    def act(self, o):
        return ('raise', o['my_bet'] + o['stack'])


class TAGShark:
    """Tight-aggressive: Chen-formula preflop ranges by position, value-bets
    made hands 2/3 pot, semi-bluffs draws on pot odds, folds to big pressure
    without the goods."""
    name = "TAG Shark"

    def act(self, o):
        if o['street'] == 'preflop':
            sc = chen(o['hole'])
            thresh = 8.5 - 2.5 * o['pos']
            tc = o['to_call']
            big = tc >= 0.5 * o['stack']
            if big:
                return ('call',) if sc >= 10 else ('fold',)
            if tc <= o['bb']:
                if sc >= thresh:
                    return ('raise', o['current_bet'] + 3 * o['bb'])
                return ('call',) if tc == 0 else ('fold',)
            if sc >= 12:
                return ('raise', o['current_bet'] * 3)
            if sc >= 9.5 and tc <= 0.15 * o['stack']:
                return ('call',)
            return ('fold',)
        cat, tp, fd, oesd, _ = hand_info(o['hole'], o['board'])
        pot, tc = o['pot'], o['to_call']
        if cat >= 2:
            if tc == 0:
                return ('raise', o['my_bet'] + max(int(0.66 * pot), o['bb']))
            return ('raise', int(o['current_bet'] * 2.5))
        if tp:
            if tc == 0:
                return ('raise', o['my_bet'] + max(int(0.5 * pot), o['bb']))
            return ('call',) if tc <= 0.6 * pot else ('fold',)
        if fd or oesd:
            return ('call',) if tc <= 0.35 * pot else ('fold',)
        return ('call',) if tc == 0 else ('fold',)


class LAGManiac:
    """Loose-aggressive: wide opening range, frequent 3-bets, barrels and
    bluffs at random frequencies, hard to put on a hand."""
    name = "LAG Maniac"

    def act(self, o):
        r = random.random()
        if o['street'] == 'preflop':
            sc = chen(o['hole'])
            tc = o['to_call']
            if tc >= 0.5 * o['stack']:
                return ('call',) if sc >= 9 else ('fold',)
            if sc >= 7 and r < 0.35:
                return ('raise', o['current_bet'] + 3 * o['bb'])
            if sc >= 5 or r < 0.25:
                if tc <= 3 * o['bb']:
                    return ('raise', o['current_bet'] + 3 * o['bb']) if r < 0.5 else ('call',)
                return ('call',) if sc >= 7 else ('fold',)
            return ('call',) if tc == 0 else ('fold',)
        cat, tp, fd, oesd, _ = hand_info(o['hole'], o['board'])
        pot, tc = o['pot'], o['to_call']
        if tc == 0:
            if cat >= 1 or fd or oesd or r < 0.4:
                return ('raise', o['my_bet'] + max(int(0.6 * pot), o['bb']))
            return ('call',)
        if cat >= 2 or (cat >= 1 and r < 0.7):
            if r < 0.2:
                return ('raise', int(o['current_bet'] * 2.5))
            return ('call',) if tc <= pot else ('fold',)
        if fd or oesd:
            return ('call',) if tc <= 0.6 * pot else ('fold',)
        return ('call',) if r < 0.12 and tc <= 0.3 * pot else ('fold',)


class RockNit:
    """Ultra-tight rock: only plays premium hands preflop, only continues
    postflop with overpair / top-pair-strong-kicker or better, then plays
    them fast."""
    name = "Rock Nit"

    def act(self, o):
        if o['street'] == 'preflop':
            (r1, _), (r2, _) = o['hole']
            pair = r1 == r2
            hi, lo = max(r1, r2), min(r1, r2)
            premium = (pair and hi >= 10) or (hi == 14 and lo >= 12)
            monster = (pair and hi >= 12) or (hi == 14 and lo == 13)
            tc = o['to_call']
            if tc >= 0.5 * o['stack']:
                return ('call',) if monster else ('fold',)
            if premium:
                return ('raise', o['current_bet'] + 4 * o['bb'])
            return ('call',) if tc == 0 else ('fold',)
        cat, tp, _, _, _ = hand_info(o['hole'], o['board'])
        (r1, _), (r2, _) = o['hole']
        strong_tp = tp and (r1 == r2 or min(r1, r2) >= 11)
        pot, tc = o['pot'], o['to_call']
        if cat >= 2 or strong_tp:
            if tc == 0:
                return ('raise', o['my_bet'] + max(int(0.75 * pot), o['bb']))
            return ('raise', int(o['current_bet'] * 3))
        if tp and tc <= 0.3 * pot:
            return ('call',)
        return ('call',) if tc == 0 else ('fold',)


class EquityQuant:
    """The mathematician: Monte-Carlo equity estimation every decision,
    compares equity against pot odds, value-raises when equity dominates."""
    name = "Equity Quant"

    def act(self, o):
        n_opp = o['num_live'] - 1
        eq = mc_equity(o['hole'], list(o['board']), n_opp)
        pot, tc = o['pot'], o['to_call']
        if tc == 0:
            if eq > 1.0 / o['num_live'] + 0.15:
                return ('raise', o['my_bet'] + max(int(0.7 * pot), o['bb']))
            return ('call',)
        po = tc / (pot + tc)
        if eq > po + 0.28 and eq > 0.55:
            return ('raise', int((o['current_bet'] + tc + pot) * 0.9))
        if eq > po + 0.03:
            return ('call',)
        return ('fold',)


class AdaptiveProfessor:
    """Exploitative: profiles every opponent's aggression frequency from
    observed actions and widens/tightens calling ranges accordingly —
    snap-calls chronic shovers with far weaker holdings."""
    name = "Adaptive Professor"

    def __init__(self):
        self.acts = Counter()
        self.raises = Counter()

    def observe(self, pid, kind):
        self.acts[pid] += 1
        if kind == 'raise':
            self.raises[pid] += 1

    def aggro(self, pid):
        if self.acts[pid] < 5:
            return 0.3
        return self.raises[pid] / self.acts[pid]

    def act(self, o):
        agg = self.aggro(o['aggressor']) if o['aggressor'] is not None else 0.3
        maniac = agg > 0.75
        if o['street'] == 'preflop':
            sc = chen(o['hole'])
            tc = o['to_call']
            if tc >= 0.5 * o['stack']:
                need = 7.5 if maniac else 10
                return ('call',) if sc >= need else ('fold',)
            thresh = 8.0 - 2.0 * o['pos']
            if tc <= o['bb']:
                if sc >= thresh:
                    return ('raise', o['current_bet'] + 3 * o['bb'])
                return ('call',) if tc == 0 else ('fold',)
            need = (8 if maniac else 9.5)
            if sc >= need:
                return ('call',) if sc < 12 else ('raise', o['current_bet'] * 3)
            return ('fold',)
        cat, tp, fd, oesd, _ = hand_info(o['hole'], o['board'])
        pot, tc = o['pot'], o['to_call']
        if cat >= 2:
            if tc == 0:
                return ('raise', o['my_bet'] + max(int(0.66 * pot), o['bb']))
            return ('raise', int(o['current_bet'] * 2.5))
        if tp:
            if tc == 0:
                return ('raise', o['my_bet'] + max(int(0.5 * pot), o['bb']))
            limit = pot if maniac else 0.55 * pot
            return ('call',) if tc <= limit else ('fold',)
        if cat == 1 and maniac and tc <= 0.7 * pot:
            return ('call',)
        if fd or oesd:
            return ('call',) if tc <= 0.35 * pot else ('fold',)
        return ('call',) if tc == 0 else ('fold',)

# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack
        self.hole = None
        self.folded = False
        self.all_in = False
        self.bet_round = 0
        self.total = 0


def pay(p, amt):
    amt = min(amt, p.stack)
    p.stack -= amt
    p.bet_round += amt
    p.total += amt
    if p.stack == 0:
        p.all_in = True
    return amt


def betting_round(players, first, current_bet, min_raise, board, street, bb_amt,
                  act_rank, observers, aggressor):
    n = len(players)
    queue = [(first + k) % n for k in range(n)
             if not players[(first + k) % n].folded and not players[(first + k) % n].all_in]
    while queue:
        idx = queue.pop(0)
        p = players[idx]
        if p.folded or p.all_in:
            continue
        if sum(1 for q in players if not q.folded) == 1:
            return
        to_call = current_bet - p.bet_round
        pot = sum(q.total for q in players)
        obs = {
            'hole': p.hole, 'board': board, 'street': street,
            'to_call': to_call, 'pot': pot, 'stack': p.stack,
            'current_bet': current_bet, 'my_bet': p.bet_round,
            'min_raise_to': current_bet + min_raise, 'bb': bb_amt,
            'num_live': sum(1 for q in players if not q.folded),
            'pos': act_rank[idx] / max(n - 1, 1), 'pid': p.pid,
            'aggressor': aggressor,
        }
        action = p.strategy.act(obs)
        kind = action[0]
        if kind == 'fold' and to_call == 0:
            kind = 'call'
        if kind == 'fold':
            p.folded = True
        elif kind == 'call':
            pay(p, to_call)
        elif kind == 'raise':
            target = min(action[1], p.bet_round + p.stack)
            if target <= current_bet:
                pay(p, to_call)
                kind = 'call'
            else:
                if target < current_bet + min_raise and p.bet_round + p.stack > target:
                    target = min(current_bet + min_raise, p.bet_round + p.stack)
                pay(p, target - p.bet_round)
                if p.bet_round - current_bet >= min_raise:
                    min_raise = p.bet_round - current_bet
                current_bet = p.bet_round
                aggressor = p.pid
                queue = [(idx + k) % n for k in range(1, n)
                         if not players[(idx + k) % n].folded
                         and not players[(idx + k) % n].all_in]
        for ob in observers:
            if ob is not p.strategy:
                ob.observe(p.pid, kind if to_call > 0 or kind == 'raise' else 'check')


def award(players, board):
    conts = [p.total for p in players]
    live = [p for p in players if not p.folded]
    if len(live) == 1:
        live[0].stack += sum(conts)
        return
    scores = {p.pid: eval7(list(p.hole) + board) for p in live}
    prev = 0
    for lv in sorted({c for c in conts if c > 0}):
        pot = sum(min(c, lv) - min(c, prev) for c in conts)
        eligible = [p for p in live if p.total >= lv] or live
        best = max(scores[p.pid] for p in eligible)
        winners = [p for p in eligible if scores[p.pid] == best]
        share = pot // len(winners)
        for w in winners:
            w.stack += share
        winners[0].stack += pot - share * len(winners)
        prev = lv


def play_hand(players, button, sb_amt, bb_amt):
    n = len(players)
    deck = new_deck()
    random.shuffle(deck)
    for p in players:
        p.hole = (deck.pop(), deck.pop())
        p.folded = False
        p.all_in = False
        p.bet_round = 0
        p.total = 0
    board = []
    if n == 2:
        sb_i, bb_i = button, (button + 1) % n
        first_pre, first_post = button, (button + 1) % n
    else:
        sb_i, bb_i = (button + 1) % n, (button + 2) % n
        first_pre, first_post = (button + 3) % n, sb_i
    pay(players[sb_i], sb_amt)
    pay(players[bb_i], bb_amt)
    act_rank = {}
    for k in range(n):
        act_rank[(first_pre + k) % n] = k
    observers = [p.strategy for p in players if hasattr(p.strategy, 'observe')]

    betting_round(players, first_pre, bb_amt, bb_amt, board, 'preflop', bb_amt,
                  act_rank, observers, None)
    for street, cards in (('flop', 3), ('turn', 1), ('river', 1)):
        if sum(1 for p in players if not p.folded) <= 1:
            break
        deck.pop()
        board += [deck.pop() for _ in range(cards)]
        if sum(1 for p in players if not p.folded and not p.all_in) >= 2:
            for p in players:
                p.bet_round = 0
            betting_round(players, first_post, 0, bb_amt, board, street, bb_amt,
                          act_rank, observers, None)
    while len(board) < 5 and sum(1 for p in players if not p.folded) > 1:
        deck.pop()
        board.append(deck.pop())
    award(players, board)

# ---------------------------------------------------------------- tournament

STRATS = {
    1: AllInMonkey,
    2: TAGShark,
    3: LAGManiac,
    4: RockNit,
    5: EquityQuant,
    6: AdaptiveProfessor,
}
START_STACK = 1000


def run_tournament(seed):
    random.seed(seed)
    players = [Player(pid, cls(), START_STACK) for pid, cls in STRATS.items()]
    button = 0
    hand_no = 0
    while len(players) > 1 and hand_no < 3000:
        level = hand_no // 15
        sb = 10 * (2 ** min(level, 8))
        play_hand(players, button % len(players), sb, 2 * sb)
        hand_no += 1
        survivors = [p for p in players if p.stack > 0]
        if len(survivors) < len(players):
            players = survivors
        button += 1
    return max(players, key=lambda p: p.stack).pid, hand_no


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    wins = Counter()
    lengths = []
    for i in range(n_sims):
        winner, hands = run_tournament(seed=1000 + i)
        wins[winner] += 1
        lengths.append(hands)
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{n_sims} tournaments done", flush=True)
    print(f"\navg tournament length: {sum(lengths) / len(lengths):.0f} hands\n")
    names = {pid: cls.name for pid, cls in STRATS.items()}
    print(f"{'Player':>7}  {'Strategy':<20} {'Wins':>5}")
    for pid in sorted(STRATS):
        bar = '#' * wins[pid]
        print(f"{pid:>7}  {names[pid]:<20} {wins[pid]:>5}  {bar}")
    with open('sim_results.csv', 'w') as f:
        f.write("player,strategy,wins\n")
        for pid in sorted(STRATS):
            f.write(f"{pid},{names[pid]},{wins[pid]}\n")
    return wins


if __name__ == '__main__':
    main()
