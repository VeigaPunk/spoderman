"""No-limit Texas Hold'em tournament engine.

Self-contained, dependency-free. Supports 2-9 players, escalating blinds,
all-ins, side pots, split pots and uncalled-bet refunds.

Cards are ints 0..51: rank = card >> 2 (0 = deuce .. 12 = ace),
suit = card & 3.
"""

import random
from dataclasses import dataclass, field

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def card_str(c):
    return RANKS[c >> 2] + SUITS[c & 3]


def _straight_high(ranks):
    """Highest straight top-rank in an iterable of ranks, else None (wheel ok)."""
    rs = set(ranks)
    if 12 in rs:
        rs.add(-1)
    for hi in range(12, 2, -1):
        if all((hi - i) in rs for i in range(5)):
            return hi
    return None


def evaluate(cards):
    """Best 5-card value of 5-7 cards as a comparable tuple (bigger wins).

    Categories: 8 straight flush, 7 quads, 6 full house, 5 flush,
    4 straight, 3 trips, 2 two pair, 1 pair, 0 high card.
    """
    rank_list = [c >> 2 for c in cards]
    cnt = {}
    for r in rank_list:
        cnt[r] = cnt.get(r, 0) + 1
    suit_cnt = {}
    for c in cards:
        s = c & 3
        suit_cnt[s] = suit_cnt.get(s, 0) + 1
    flush_suit = None
    for s, n in suit_cnt.items():
        if n >= 5:
            flush_suit = s
    if flush_suit is not None:
        flush_ranks = sorted((c >> 2 for c in cards if (c & 3) == flush_suit),
                             reverse=True)
        sh = _straight_high(flush_ranks)
        if sh is not None:
            return (8, sh, 0, 0, 0, 0)
    groups = sorted(cnt.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    if groups[0][1] == 4:
        quad = groups[0][0]
        kick = max(r for r in rank_list if r != quad)
        return (7, quad, kick, 0, 0, 0)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, groups[0][0], groups[1][0], 0, 0, 0)
    if flush_suit is not None:
        return (5,) + tuple(flush_ranks[:5])
    sh = _straight_high(rank_list)
    if sh is not None:
        return (4, sh, 0, 0, 0, 0)
    if groups[0][1] == 3:
        t = groups[0][0]
        k1, k2 = sorted((r for r in rank_list if r != t), reverse=True)[:2]
        return (3, t, k1, k2, 0, 0)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        hp, lp = groups[0][0], groups[1][0]
        kick = max(r for r in rank_list if r != hp and r != lp)
        return (2, hp, lp, kick, 0, 0)
    if groups[0][1] == 2:
        p = groups[0][0]
        k1, k2, k3 = sorted((r for r in rank_list if r != p), reverse=True)[:3]
        return (1, p, k1, k2, k3, 0)
    t1, t2, t3, t4, t5 = sorted(rank_list, reverse=True)[:5]
    return (0, t1, t2, t3, t4, t5)


def estimate_equity(hole, board, n_opps, iters, rng):
    """Monte Carlo equity of `hole` on `board` vs n_opps random hands."""
    known = set(hole) | set(board)
    deck = [c for c in range(52) if c not in known]
    need = 5 - len(board)
    wins = 0.0
    for _ in range(iters):
        draw = rng.sample(deck, need + 2 * n_opps)
        full_board = board + draw[:need]
        my = evaluate(hole + full_board)
        best = True
        ties = 1
        idx = need
        for _o in range(n_opps):
            ov = evaluate(draw[idx:idx + 2] + full_board)
            idx += 2
            if ov > my:
                best = False
                break
            if ov == my:
                ties += 1
        if best:
            wins += 1.0 / ties
    return wins / iters


def chen_score(hole):
    """Chen formula pre-flop hand strength (AA=20 ... 72o negative)."""
    r1, r2 = sorted((hole[0] >> 2, hole[1] >> 2), reverse=True)

    def pts(r):
        v = r + 2
        if v == 14:
            return 10.0
        if v == 13:
            return 8.0
        if v == 12:
            return 7.0
        if v == 11:
            return 6.0
        return v / 2.0

    score = pts(r1)
    if r1 == r2:
        return max(5.0, score * 2)
    if (hole[0] & 3) == (hole[1] & 3):
        score += 2
    gap = r1 - r2 - 1
    if gap == 1:
        score -= 1
    elif gap == 2:
        score -= 2
    elif gap == 3:
        score -= 4
    elif gap >= 4:
        score -= 5
    if gap <= 1 and r1 < 10:  # connected-ish, both below queen: straight bonus
        score += 1
    return score


@dataclass
class Obs:
    """Everything a strategy is allowed to see when acting. Own hole cards,
    the board and public information only - never another player's cards or
    code."""
    seat: int
    hole: tuple
    board: list
    street: str
    pot: int
    current_bet: int
    to_call: int
    min_raise: int
    my_stack: int
    my_street_contrib: int
    my_total_contrib: int
    sb: int
    bb: int
    n_players: int
    n_active: int
    n_can_act: int
    is_button: bool
    is_sb: bool
    is_bb: bool
    pos_frac: float
    history: list
    preflop_raise_count: int
    last_aggressor_seat: int
    aggressor_is_allin: bool
    preflop_aggressor_seat: int
    opp_stacks: dict
    hand_no: int


@dataclass
class Player:
    seat: int
    stack: int
    strategy: object
    hole: tuple = None
    folded: bool = False
    allin: bool = False
    acted: bool = False
    street_contrib: int = 0
    total_contrib: int = 0
    pos_frac: float = 0.0
    is_button: bool = False
    is_sb: bool = False
    is_bb: bool = False


class Tournament:
    """Freeze-out sit-and-go: play hands until one player has all the chips."""

    def __init__(self, strategies, start_stack=1000, base_sb=5,
                 hands_per_level=20, seed=0, max_hands=3000, log=None):
        self.rng = random.Random(seed)
        self.players = [Player(seat=i, stack=start_stack, strategy=s)
                        for i, s in enumerate(strategies)]
        self.n_seats = len(self.players)
        self.total_chips = start_stack * self.n_seats
        self.base_sb = base_sb
        self.hands_per_level = hands_per_level
        self.max_hands = max_hands
        self.button_seat = self.rng.randrange(self.n_seats)
        self.hand_no = 0
        self.finish_order = []  # seats in order of elimination
        self.log = log

    # ---------------------------------------------------------------- helpers
    def _blinds(self):
        level = min(self.hand_no // self.hands_per_level, 11)
        sb = self.base_sb * (2 ** level)
        return sb, sb * 2

    def _broadcast(self, event):
        for p in self.players:
            p.strategy.observe(dict(event))
        if self.log is not None:
            self.log.append(event)

    def _commit(self, p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        p.street_contrib += amount
        p.total_contrib += amount
        self.pot += amount
        if p.stack == 0:
            p.allin = True
        return amount

    # ------------------------------------------------------------------ obs
    def _make_obs(self, p, street, current_bet, min_raise):
        active = [q for q in self.hand_players if not q.folded]
        can_act = [q for q in active if not q.allin]
        agg = self.last_aggressor_seat
        agg_allin = False
        if agg is not None:
            agg_p = self.players[agg]
            agg_allin = agg_p.allin
        return Obs(
            seat=p.seat, hole=p.hole, board=list(self.board), street=street,
            pot=self.pot, current_bet=current_bet,
            to_call=max(0, current_bet - p.street_contrib),
            min_raise=min_raise, my_stack=p.stack,
            my_street_contrib=p.street_contrib,
            my_total_contrib=p.total_contrib,
            sb=self.sb, bb=self.bb,
            n_players=len(self.hand_players), n_active=len(active),
            n_can_act=len(can_act),
            is_button=p.is_button, is_sb=p.is_sb, is_bb=p.is_bb,
            pos_frac=p.pos_frac, history=list(self.street_events),
            preflop_raise_count=self.preflop_raise_count,
            last_aggressor_seat=agg, aggressor_is_allin=agg_allin,
            preflop_aggressor_seat=self.preflop_aggressor_seat,
            opp_stacks={q.seat: q.stack for q in active if q is not p},
            hand_no=self.hand_no,
        )

    # -------------------------------------------------------------- betting
    def _apply_action(self, p, action, current_bet, min_raise, street, order):
        to_call = max(0, current_bet - p.street_contrib)
        kind = action[0]
        if kind == "allin":
            target = p.street_contrib + p.stack
            if target > current_bet:
                kind, action = "raise_to", ("raise_to", target)
            else:
                kind = "check_call"
        if kind == "fold" and to_call <= 0:
            kind = "check_call"  # never fold when checking is free
        if kind == "fold":
            p.folded = True
            p.acted = True
            self._event(street, p, "fold", 0, current_bet)
            return current_bet, min_raise
        if kind == "check_call":
            pay = self._commit(p, to_call)
            p.acted = True
            self._event(street, p, "call" if pay > 0 else "check", pay,
                        current_bet)
            return current_bet, min_raise

        # raise_to: target is the player's TOTAL street contribution goal
        target = int(action[1])
        max_target = p.street_contrib + p.stack
        target = min(target, max_target)
        legal_min = current_bet + min_raise
        if target < legal_min:
            # bump undersized raises to the min-raise, or shove if that is all
            target = min(legal_min, max_target)
        if target <= current_bet:
            pay = self._commit(p, to_call)
            p.acted = True
            self._event(street, p, "call" if pay > 0 else "check", pay,
                        current_bet)
            return current_bet, min_raise
        raise_size = target - current_bet
        self._commit(p, target - p.street_contrib)
        if raise_size >= min_raise:
            min_raise = raise_size
        current_bet = target
        p.acted = True
        self.last_aggressor_seat = p.seat
        if street == "preflop":
            self.preflop_raise_count += 1
        for q in order:
            if q is not p and not q.folded and not q.allin:
                q.acted = False
        self._event(street, p, "raise", target, current_bet)
        return current_bet, min_raise

    def _event(self, street, p, action, amount, current_bet):
        ev = {"type": "action", "hand": self.hand_no, "street": street,
              "seat": p.seat, "action": action, "amount": amount,
              "allin": p.allin, "pot": self.pot, "current_bet": current_bet}
        self.street_events.append(ev)
        self._broadcast(ev)

    def _betting_round(self, order, street, current_bet, min_raise):
        n = len(order)
        i = 0
        while True:
            contenders = [p for p in order if not p.folded]
            if len(contenders) <= 1:
                break
            actionable = [p for p in contenders if not p.allin and
                          (not p.acted or p.street_contrib < current_bet)]
            if not actionable:
                break
            if (len(actionable) == 1
                    and actionable[0].street_contrib >= current_bet
                    and all(q.folded or q.allin for q in order
                            if q is not actionable[0])):
                break  # nobody left who could respond to a bet
            p = order[i % n]
            i += 1
            if p.folded or p.allin:
                continue
            if p.acted and p.street_contrib >= current_bet:
                continue
            obs = self._make_obs(p, street, current_bet, min_raise)
            try:
                action = p.strategy.act(obs)
            except Exception:
                action = ("fold",)
            current_bet, min_raise = self._apply_action(
                p, action, current_bet, min_raise, street, order)
        return current_bet

    def _refund_uncalled(self):
        nf = [p for p in self.hand_players if not p.folded]
        if not nf:
            return
        m1 = max(p.street_contrib for p in nf)
        top = [p for p in nf if p.street_contrib == m1]
        if len(top) != 1:
            return
        p = top[0]
        others = [q.street_contrib for q in nf if q is not p]
        second = max(others) if others else 0
        excess = m1 - second
        if excess > 0:
            p.stack += excess
            p.street_contrib -= excess
            p.total_contrib -= excess
            self.pot -= excess
            if p.allin and p.stack > 0:
                p.allin = False

    # ------------------------------------------------------------- side pots
    def _build_pots(self):
        contenders = [p for p in self.hand_players if not p.folded]
        levels = sorted({p.total_contrib for p in contenders
                         if p.total_contrib > 0})
        pots = []
        prev = 0
        for lv in levels:
            amt = sum(max(0, min(q.total_contrib, lv) - prev)
                      for q in self.hand_players)
            eligible = [q for q in contenders if q.total_contrib >= lv]
            if amt > 0:
                pots.append([amt, eligible])
            prev = lv
        distributed = sum(a for a, _ in pots)
        leftover = self.pot - distributed
        if leftover > 0 and pots:  # dead money above the top contender level
            pots[-1][0] += leftover
        return pots

    # ----------------------------------------------------------------- hand
    def play_hand(self):
        hand_players = [p for p in self.players if p.stack > 0]
        n = len(hand_players)
        if n < 2:
            return
        self.sb, self.bb = self._blinds()
        for p in hand_players:
            p.folded = p.allin = p.acted = False
            p.street_contrib = p.total_contrib = 0
            p.is_button = p.is_sb = p.is_bb = False
        self.pot = 0
        self.board = []
        self.street_events = []
        self.preflop_raise_count = 0
        self.last_aggressor_seat = None
        self.preflop_aggressor_seat = None
        self.hand_players = hand_players

        rot = sorted(hand_players,
                     key=lambda p: (p.seat - self.button_seat - 1) % self.n_seats)
        if n == 2:
            btn = next(p for p in hand_players if p.seat == self.button_seat)
            other = next(p for p in hand_players if p is not btn)
            sb_p, bb_p = btn, other
            preflop_order = [sb_p, bb_p]
            postflop_order = [bb_p, sb_p]
        else:
            sb_p, bb_p = rot[0], rot[1]
            preflop_order = rot[2:] + [sb_p, bb_p]
            postflop_order = rot
        btn_p = next(p for p in hand_players if p.seat == self.button_seat)
        btn_p.is_button = True
        sb_p.is_sb = True
        bb_p.is_bb = True
        for idx, p in enumerate(preflop_order):
            p.pos_frac = idx / max(1, n - 1)

        deck = list(range(52))
        self.rng.shuffle(deck)
        for p in hand_players:
            p.hole = (deck.pop(), deck.pop())

        self._broadcast({"type": "hand_start", "hand": self.hand_no,
                         "seats": [p.seat for p in hand_players],
                         "stacks": {p.seat: p.stack for p in hand_players},
                         "button": self.button_seat,
                         "sb_seat": sb_p.seat, "bb_seat": bb_p.seat,
                         "sb": self.sb, "bb": self.bb})

        self._commit(sb_p, self.sb)
        self._commit(bb_p, self.bb)
        current_bet, min_raise = self.bb, self.bb

        streets = [("preflop", 0, preflop_order), ("flop", 3, postflop_order),
                   ("turn", 1, postflop_order), ("river", 1, postflop_order)]
        for street, n_cards, order in streets:
            for _ in range(n_cards):
                self.board.append(deck.pop())
            if street != "preflop":
                for p in hand_players:
                    p.street_contrib = 0
                    p.acted = False
                current_bet, min_raise = 0, self.bb
                self.street_events = []
                self.last_aggressor_seat = None
            current_bet = self._betting_round(order, street, current_bet,
                                              min_raise)
            self._refund_uncalled()
            if street == "preflop":
                self.preflop_aggressor_seat = self.last_aggressor_seat
            if sum(1 for p in hand_players if not p.folded) <= 1:
                break

        contenders = [p for p in hand_players if not p.folded]
        results = {}
        if len(contenders) == 1:
            contenders[0].stack += self.pot
            results[contenders[0].seat] = self.pot
        else:
            pots = self._build_pots()
            scores = {p.seat: evaluate(list(p.hole) + self.board)
                      for p in contenders}
            for amount, eligible in pots:
                best = max(scores[p.seat] for p in eligible)
                winners = [p for p in eligible if scores[p.seat] == best]
                share = amount // len(winners)
                for w in winners:
                    w.stack += share
                    results[w.seat] = results.get(w.seat, 0) + share
                rem = amount - share * len(winners)
                if rem:
                    winners[0].stack += rem
                    results[winners[0].seat] += rem
            self._broadcast({"type": "showdown", "hand": self.hand_no,
                             "board": list(self.board),
                             "holes": {p.seat: p.hole for p in contenders}})
        self.pot = 0
        self._broadcast({"type": "hand_end", "hand": self.hand_no,
                         "winners": results,
                         "stacks": {p.seat: p.stack for p in self.players}})

        assert sum(p.stack for p in self.players) == self.total_chips, \
            "chip conservation violated"

        busted = [p for p in hand_players if p.stack == 0]
        busted.sort(key=lambda p: p.total_contrib)  # shortest stack out first
        for p in busted:
            self.finish_order.append(p.seat)

        self.hand_no += 1
        for step in range(1, self.n_seats + 1):
            cand = (self.button_seat + step) % self.n_seats
            if self.players[cand].stack > 0:
                self.button_seat = cand
                break

    def run(self):
        while (sum(1 for p in self.players if p.stack > 0) > 1
               and self.hand_no < self.max_hands):
            self.play_hand()
        alive = [p for p in self.players if p.stack > 0]
        alive.sort(key=lambda p: p.stack)
        for p in alive:  # normally just the winner; stack order if capped out
            self.finish_order.append(p.seat)
        winner_seat = self.finish_order[-1]
        return {"winner_seat": winner_seat,
                "finish_order": list(self.finish_order),
                "hands_played": self.hand_no}
