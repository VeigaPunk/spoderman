"""No-Limit Texas Hold'em tournament simulator.

6 players, equal starting stacks, escalating blinds, play until one remains.
Player 1 goes all-in every time it acts. Players 2-6 run distinct elaborate
strategies. No strategy has any knowledge of the others' logic.
"""

import random
import sys
from collections import Counter
from itertools import combinations

RANKS = list(range(2, 15))  # 2..14 (A=14)
SUITS = 'shdc'
FULL_DECK = [(r, s) for r in RANKS for s in SUITS]


# ---------------------------------------------------------------- hand eval

def eval5(cards):
    """Rank a 5-card hand. Higher tuple wins."""
    ranks = sorted((c[0] for c in cards), reverse=True)
    counts = Counter(ranks)
    by_count = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    flush = len({c[1] for c in cards}) == 1
    uniq = sorted(set(ranks), reverse=True)
    straight_high = 0
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_high = 5
    if flush and straight_high:
        return (8, straight_high)
    if by_count[0][1] == 4:
        return (7, by_count[0][0], by_count[1][0])
    if by_count[0][1] == 3 and by_count[1][1] == 2:
        return (6, by_count[0][0], by_count[1][0])
    if flush:
        return (5, *ranks)
    if straight_high:
        return (4, straight_high)
    if by_count[0][1] == 3:
        kickers = [r for r in ranks if r != by_count[0][0]]
        return (3, by_count[0][0], *kickers)
    if by_count[0][1] == 2 and by_count[1][1] == 2:
        hi, lo = by_count[0][0], by_count[1][0]
        kicker = by_count[2][0]
        return (2, hi, lo, kicker)
    if by_count[0][1] == 2:
        kickers = [r for r in ranks if r != by_count[0][0]]
        return (1, by_count[0][0], *kickers)
    return (0, *ranks)


def eval7(cards):
    return max(eval5(c) for c in combinations(cards, 5))


def chen_score(hole):
    (r1, s1), (r2, s2) = sorted(hole, reverse=True)
    base_map = {14: 10.0, 13: 8.0, 12: 7.0, 11: 6.0}
    base = base_map.get(r1, r1 / 2.0)
    if r1 == r2:
        return max(5.0, base * 2)
    score = base
    if s1 == s2:
        score += 2
    gap = r1 - r2 - 1
    score -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 12:
        score += 1
    return score


def mc_equity(hole, community, n_opp, rng, trials=30):
    """Monte Carlo equity vs n_opp random hands."""
    deck = [c for c in FULL_DECK if c not in hole and c not in community]
    need_board = 5 - len(community)
    wins = 0.0
    for _ in range(trials):
        drawn = rng.sample(deck, need_board + 2 * n_opp)
        board = community + drawn[:need_board]
        mine = eval7(hole + board)
        best_opp = max(
            eval7(drawn[need_board + 2 * i:need_board + 2 * i + 2] + board)
            for i in range(n_opp)
        )
        if mine > best_opp:
            wins += 1.0
        elif mine == best_opp:
            wins += 0.5
    return wins / trials


# ---------------------------------------------------------------- strategies

class Strategy:
    name = 'base'

    def act(self, state, rng):
        raise NotImplementedError

    def observe(self, event):
        pass


class AllInAndy(Strategy):
    """Player 1. if my_turn then bet = All in fi"""
    name = 'AllInAndy(P1)'

    def act(self, state, rng):
        return ('raise', state['my_bet'] + state['stack'])


class TagTitan(Strategy):
    """Tight-aggressive: positional Chen ranges preflop, equity-driven
    value betting postflop, disciplined pot-odds folds."""
    name = 'TagTitan(P2)'

    def act(self, state, rng):
        st, to_call, pot, stack = state['street'], state['to_call'], state['pot'], state['stack']
        bb = state['big_blind']
        if st == 'preflop':
            score = chen_score(state['hole'])
            late = state['position'] <= 1
            open_th = 8.0 if late else 9.5
            facing_big = to_call > 3 * bb
            if facing_big:
                if score >= 11:
                    return ('raise', state['my_bet'] + min(stack, to_call * 3))
                if score >= 9.5 and to_call < stack * 0.15:
                    return ('call',)
                return ('fold',)
            if score >= open_th + 2:
                return ('raise', min(state['my_bet'] + stack, to_call + 3 * bb + state['my_bet']))
            if score >= open_th:
                return ('raise', state['my_bet'] + to_call + 2 * bb) if to_call <= bb else ('call',)
            if score >= 6.5 and to_call <= bb:
                return ('call',)
            return ('fold',) if to_call > 0 else ('call',)
        eq = mc_equity(state['hole'], state['community'], max(1, state['num_in_hand'] - 1), rng)
        if to_call == 0:
            if eq > 0.55:
                return ('raise', state['my_bet'] + min(stack, max(bb, int(pot * 0.66))))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.72:
            return ('raise', state['my_bet'] + min(stack, to_call + pot))
        if eq > pot_odds + 0.05:
            return ('call',)
        return ('fold',)


class LagLoki(Strategy):
    """Loose-aggressive: wide opens, relentless c-bets, timed bluff-raises,
    pressure on capped ranges."""
    name = 'LagLoki(P3)'

    def __init__(self):
        self.was_preflop_raiser = False

    def act(self, state, rng):
        st, to_call, pot, stack = state['street'], state['to_call'], state['pot'], state['stack']
        bb = state['big_blind']
        if st == 'preflop':
            score = chen_score(state['hole'])
            self.was_preflop_raiser = False
            if to_call > 4 * bb:
                if score >= 10:
                    self.was_preflop_raiser = True
                    return ('raise', state['my_bet'] + min(stack, to_call * 3))
                if score >= 7.5:
                    return ('call',)
                if rng.random() < 0.08:
                    return ('call',)
                return ('fold',)
            if score >= 6.5 or rng.random() < 0.18:
                self.was_preflop_raiser = True
                return ('raise', state['my_bet'] + min(stack, to_call + 3 * bb))
            if score >= 5 and to_call <= bb:
                return ('call',)
            return ('fold',) if to_call > 0 else ('call',)
        eq = mc_equity(state['hole'], state['community'], max(1, state['num_in_hand'] - 1), rng)
        bluffing = rng.random() < 0.13
        if to_call == 0:
            if eq > 0.5 or (self.was_preflop_raiser and rng.random() < 0.65) or bluffing:
                return ('raise', state['my_bet'] + min(stack, max(bb, int(pot * 0.75))))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > 0.65 or bluffing:
            return ('raise', state['my_bet'] + min(stack, to_call + int(pot * 1.2)))
        if eq > pot_odds:
            return ('call',)
        return ('fold',)


class MathMage(Strategy):
    """Pure expected-value machine: Monte Carlo equity every decision,
    calls exactly on pot odds, value-raises big equity edges."""
    name = 'MathMage(P4)'

    def act(self, state, rng):
        to_call, pot, stack = state['to_call'], state['pot'], state['stack']
        bb = state['big_blind']
        n_opp = max(1, state['num_in_hand'] - 1)
        eq = mc_equity(state['hole'], state['community'], n_opp, rng, trials=40)
        fair_share = 1.0 / state['num_in_hand']
        if to_call == 0:
            if eq > fair_share * 1.6:
                return ('raise', state['my_bet'] + min(stack, max(bb, int(pot * 0.6))))
            return ('call',)
        pot_odds = to_call / (pot + to_call)
        if eq > max(0.62, fair_share * 2.2):
            return ('raise', state['my_bet'] + min(stack, to_call + pot))
        if eq > pot_odds:
            return ('call',)
        return ('fold',)


class NitNinja(Strategy):
    """Ultra-tight rock: folds almost everything, but when it plays,
    it plays for stacks. Waits for the maniacs to donate."""
    name = 'NitNinja(P5)'

    def act(self, state, rng):
        st, to_call, pot, stack = state['street'], state['to_call'], state['pot'], state['stack']
        bb = state['big_blind']
        if st == 'preflop':
            score = chen_score(state['hole'])
            if score >= 12:
                return ('raise', state['my_bet'] + stack)
            if score >= 10:
                return ('raise', state['my_bet'] + min(stack, to_call + 4 * bb))
            if score >= 8.5 and to_call <= 2 * bb:
                return ('call',)
            return ('fold',) if to_call > 0 else ('call',)
        eq = mc_equity(state['hole'], state['community'], max(1, state['num_in_hand'] - 1), rng)
        if eq > 0.78:
            return ('raise', state['my_bet'] + stack)
        if to_call == 0:
            if eq > 0.6:
                return ('raise', state['my_bet'] + min(stack, int(pot * 0.5) or bb))
            return ('call',)
        if eq > to_call / (pot + to_call) + 0.12:
            return ('call',)
        return ('fold',)


class Chameleon(Strategy):
    """Adaptive exploiter: profiles table aggression from observed actions,
    tightens vs maniacs / steals vs passives, switches to ICM-ish
    push-fold when short-stacked."""
    name = 'Chameleon(P6)'

    def __init__(self):
        self.actions_seen = 0
        self.raises_seen = 0

    def observe(self, event):
        if event['street'] == 'preflop':
            self.actions_seen += 1
            if event['action'] == 'raise':
                self.raises_seen += 1

    def table_aggression(self):
        if self.actions_seen < 10:
            return 0.3
        return self.raises_seen / self.actions_seen

    def act(self, state, rng):
        st, to_call, pot, stack = state['street'], state['to_call'], state['pot'], state['stack']
        bb = state['big_blind']
        aggro = self.table_aggression()
        if stack < 8 * bb:  # push/fold mode
            score = chen_score(state['hole'])
            th = 7.0 if aggro > 0.45 else 6.0
            if st == 'preflop':
                if score >= th:
                    return ('raise', state['my_bet'] + stack)
                return ('fold',) if to_call > 0 else ('call',)
            eq = mc_equity(state['hole'], state['community'], max(1, state['num_in_hand'] - 1), rng)
            if eq > 0.5:
                return ('raise', state['my_bet'] + stack)
            return ('fold',) if to_call > 0 else ('call',)
        if st == 'preflop':
            score = chen_score(state['hole'])
            # vs aggressive table: tighten calls, trap with premiums
            call_th = 8.5 if aggro > 0.45 else 6.5
            raise_th = 11.0 if aggro > 0.45 else 8.5
            steal = state['position'] <= 1 and aggro < 0.3 and to_call <= bb
            if score >= raise_th or (steal and score >= 6):
                return ('raise', state['my_bet'] + min(stack, to_call + 3 * bb))
            if score >= call_th and to_call < stack * 0.12:
                return ('call',)
            return ('fold',) if to_call > 0 else ('call',)
        eq = mc_equity(state['hole'], state['community'], max(1, state['num_in_hand'] - 1), rng)
        margin = 0.1 if aggro > 0.45 else 0.03
        if to_call == 0:
            if eq > 0.58:
                return ('raise', state['my_bet'] + min(stack, max(bb, int(pot * 0.7))))
            return ('call',)
        if eq > 0.75:
            return ('raise', state['my_bet'] + min(stack, to_call + pot))
        if eq > to_call / (pot + to_call) + margin:
            return ('call',)
        return ('fold',)


# ---------------------------------------------------------------- engine

class Player:
    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack
        self.reset_hand()

    def reset_hand(self):
        self.hole = []
        self.in_hand = False
        self.all_in = False
        self.bet = 0        # current street
        self.total_bet = 0  # whole hand


def post(player, amount):
    amt = min(amount, player.stack)
    player.stack -= amt
    player.bet += amt
    player.total_bet += amt
    if player.stack == 0:
        player.all_in = True
    return amt


def betting_round(players, order, street, community, big_blind, current_bet, last_raise, rng):
    """order: seat-ordered list of players for this hand, starting with first to act."""
    n = len(order)
    to_act = {p.seat for p in order if p.in_hand and not p.all_in}
    idx = 0
    guard = 0
    while to_act and sum(1 for p in order if p.in_hand) > 1:
        guard += 1
        if guard > 500:
            break
        p = order[idx % n]
        idx += 1
        if p.seat not in to_act or not p.in_hand or p.all_in:
            continue
        pot = sum(pl.total_bet for pl in players)
        to_call = current_bet - p.bet
        state = {
            'hole': p.hole, 'community': community, 'street': street,
            'pot': pot, 'to_call': to_call, 'stack': p.stack,
            'my_bet': p.bet, 'big_blind': big_blind,
            'num_in_hand': sum(1 for pl in order if pl.in_hand),
            'position': p.position,
        }
        try:
            action = p.strategy.act(state, rng)
        except Exception:
            action = ('fold',)
        kind = action[0]
        if kind == 'fold' and to_call == 0:
            kind = 'call'
        if kind == 'raise':
            target = min(action[1], p.bet + p.stack)
            min_target = current_bet + last_raise
            if target <= current_bet or (target < min_target and target < p.bet + p.stack):
                kind = 'call'
            else:
                paid_to = target
                raise_size = paid_to - current_bet
                post(p, paid_to - p.bet)
                if raise_size >= last_raise:
                    last_raise = raise_size
                current_bet = paid_to
                to_act = {pl.seat for pl in order if pl.in_hand and not pl.all_in and pl.seat != p.seat}
                _broadcast(order, {'seat': p.seat, 'action': 'raise', 'street': street})
                continue
        if kind == 'call':
            if to_call > 0:
                post(p, to_call)
            to_act.discard(p.seat)
            _broadcast(order, {'seat': p.seat, 'action': 'call' if to_call else 'check', 'street': street})
        else:  # fold
            p.in_hand = False
            to_act.discard(p.seat)
            _broadcast(order, {'seat': p.seat, 'action': 'fold', 'street': street})
    return current_bet


def _broadcast(players, event):
    for p in players:
        try:
            p.strategy.observe(event)
        except Exception:
            pass


def play_hand(players, button, big_blind, rng):
    """players: alive players in seat order. Mutates stacks."""
    n = len(players)
    for p in players:
        p.reset_hand()
        p.in_hand = True
    deck = FULL_DECK[:]
    rng.shuffle(deck)
    for i, p in enumerate(players):
        p.hole = [deck.pop(), deck.pop()]
        p.position = (button - players.index(p)) % n  # 0 = button

    sb_i = button if n == 2 else (button + 1) % n
    bb_i = (sb_i + 1) % n
    post(players[sb_i], big_blind // 2)
    post(players[bb_i], big_blind)

    community = []
    current_bet = big_blind
    last_raise = big_blind
    first = (bb_i + 1) % n
    order = players[first:] + players[:first]
    current_bet = betting_round(players, order, 'preflop', community, big_blind, current_bet, last_raise, rng)

    for street, ncards in (('flop', 3), ('turn', 1), ('river', 1)):
        if sum(1 for p in players if p.in_hand) <= 1:
            break
        if sum(1 for p in players if p.in_hand and not p.all_in) >= 2:
            pass  # betting happens below
        deck.pop()  # burn
        community += [deck.pop() for _ in range(ncards)]
        for p in players:
            p.bet = 0
        first = (button + 1) % n
        order = players[first:] + players[:first]
        if sum(1 for p in players if p.in_hand and not p.all_in) >= 2:
            betting_round(players, order, street, community, big_blind, 0, big_blind, rng)

    # refund uncalled excess
    in_hand = [p for p in players if p.in_hand]
    totals = sorted((p.total_bet for p in players), reverse=True)
    top = max(players, key=lambda p: p.total_bet)
    second = max((p.total_bet for p in players if p is not top), default=0)
    if top.total_bet > second:
        refund = top.total_bet - second
        top.total_bet -= refund
        top.stack += refund
        if top.stack > 0:
            top.all_in = False

    in_hand = [p for p in players if p.in_hand]
    if len(in_hand) == 1:
        in_hand[0].stack += sum(p.total_bet for p in players)
        return

    # showdown with side pots
    ranks = {p.seat: eval7(p.hole + community) for p in in_hand}
    levels = sorted({p.total_bet for p in in_hand})
    prev = 0
    remaining = {p.seat: p.total_bet for p in players}
    for level in levels:
        slice_amt = sum(min(remaining[p.seat], level) - min(remaining[p.seat], prev) for p in players)
        eligible = [p for p in in_hand if p.total_bet >= level]
        if slice_amt > 0 and eligible:
            best = max(ranks[p.seat] for p in eligible)
            winners = [p for p in eligible if ranks[p.seat] == best]
            share = slice_amt // len(winners)
            for w in winners:
                w.stack += share
            winners[0].stack += slice_amt - share * len(winners)
        prev = level
    # any excess above top in-hand level (from folders) goes to overall best hand
    excess = sum(max(0, remaining[p.seat] - prev) for p in players)
    if excess:
        best = max(ranks.values())
        winners = [p for p in in_hand if ranks[p.seat] == best]
        winners[0].stack += excess


def run_tournament(seed, starting_stack=1000):
    rng = random.Random(seed)
    strategies = [AllInAndy(), TagTitan(), LagLoki(), MathMage(), NitNinja(), Chameleon()]
    players = [Player(i, s.name, s, starting_stack) for i, s in enumerate(strategies)]
    alive = players[:]
    button = rng.randrange(len(alive))
    big_blind = 20
    hand_no = 0
    eliminations = []
    while len(alive) > 1 and hand_no < 2000:
        hand_no += 1
        if hand_no % 20 == 0:
            big_blind = min(big_blind * 2, starting_stack * len(players))
        play_hand(alive, button % len(alive), big_blind, rng)
        busted = [p for p in alive if p.stack <= 0]
        eliminations.extend(p.name for p in busted)
        if busted:
            btn_player = alive[button % len(alive)]
            alive = [p for p in alive if p.stack > 0]
            button = alive.index(btn_player) if btn_player in alive else button
        button = (button + 1) % max(1, len(alive))
    winner = max(alive, key=lambda p: p.stack)
    return winner.name, hand_no, eliminations


def main():
    n_sims = 100
    wins = Counter()
    total_hands = 0
    first_out = Counter()
    for i in range(n_sims):
        winner, hands, elims = run_tournament(seed=42_000 + i)
        wins[winner] += 1
        total_hands += hands
        if elims:
            first_out[elims[0]] += 1
        if (i + 1) % 10 == 0:
            print(f'  ... {i + 1}/{n_sims} tournaments done', file=sys.stderr)

    names = ['AllInAndy(P1)', 'TagTitan(P2)', 'LagLoki(P3)', 'MathMage(P4)',
             'NitNinja(P5)', 'Chameleon(P6)']
    print()
    print('=' * 62)
    print(' WINNER WINNER CHICKEN DINNER — 100 tournament histogram')
    print('=' * 62)
    max_w = max(wins.values()) if wins else 1
    for name in names:
        w = wins.get(name, 0)
        bar = '#' * round(w * 40 / max_w)
        print(f'  {name:<15} {w:>3} | {bar}')
    print('=' * 62)
    print(f'  avg tournament length: {total_hands / n_sims:.1f} hands')
    print(f'  first player eliminated (count): '
          + ', '.join(f'{n.split("(")[0]}={first_out.get(n, 0)}' for n in names))
    print('=' * 62)


if __name__ == '__main__':
    main()
