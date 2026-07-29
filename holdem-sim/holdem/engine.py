"""No-limit Texas Hold'em tournament engine.

Supports blinds with escalation, full betting rounds, all-ins and side pots.
Strategies only ever see a legal-information observation dict — never each
other's code, holdings, or intentions.
"""

import random

from .cards import eval7, new_deck


class _HandState:
    __slots__ = ("hole", "folded", "all_in", "street_bet", "total")

    def __init__(self):
        self.hole = ()
        self.folded = False
        self.all_in = False
        self.street_bet = 0   # chips put in during the current street
        self.total = 0        # chips put in during the whole hand


class Player:
    def __init__(self, seat, name, strategy, stack):
        self.seat = seat
        self.name = name
        self.strategy = strategy
        self.stack = stack


class Tournament:
    """Freezeout: play hands until one player holds all the chips."""

    def __init__(self, strategies, names, start_stack=1000, sb=10,
                 blind_double_every=15, seed=0):
        self.rng = random.Random(seed)
        self.players = [Player(i, names[i], strategies[i], start_stack)
                        for i in range(len(strategies))]
        self.start_sb = sb
        self.blind_double_every = blind_double_every
        self.button = self.rng.randrange(len(self.players))
        self.hand_no = 0
        self.bust_order = []  # seats in order of elimination

    # ------------------------------------------------------------------ #

    def blinds(self):
        level = self.hand_no // self.blind_double_every
        sb = min(self.start_sb * (2 ** level), 10 ** 9)
        return sb, sb * 2

    def run(self, max_hands=2000):
        while sum(1 for p in self.players if p.stack > 0) > 1:
            if self.hand_no >= max_hands:
                break
            self.play_hand()
        alive = [p for p in self.players if p.stack > 0]
        winner = max(alive, key=lambda p: p.stack)
        return winner.seat

    # ------------------------------------------------------------------ #

    def play_hand(self):
        total_chips = sum(p.stack for p in self.players)
        alive = [p for p in self.players if p.stack > 0]
        n_all = len(self.players)

        # move the button to the next living seat
        b = self.button
        for step in range(1, n_all + 1):
            if self.players[(b + step) % n_all].stack > 0:
                self.button = (b + step) % n_all
                break

        # hand order: seat after the button first (SB), button last.
        # Heads-up: button is SB and acts first preflop.
        if len(alive) == 2:
            btn_p = self.players[self.button]
            other = next(p for p in alive if p.seat != btn_p.seat)
            hp = [btn_p, other]
        else:
            hp = []
            for step in range(1, n_all + 1):
                p = self.players[(self.button + step) % n_all]
                if p.stack > 0:
                    hp.append(p)

        n = len(hp)
        state = [_HandState() for _ in range(n)]
        sb, bb = self.blinds()
        self.hand_no += 1

        def pay(j, amount):
            amount = min(amount, hp[j].stack)
            hp[j].stack -= amount
            state[j].street_bet += amount
            state[j].total += amount
            if hp[j].stack == 0:
                state[j].all_in = True
            return amount

        pay(0, sb)
        pay(1, bb)

        deck = new_deck()
        self.rng.shuffle(deck)
        for j in range(n):
            state[j].hole = (deck.pop(), deck.pop())
        board = []

        raises = 0
        last_aggressor = None

        def unfolded():
            return [j for j in range(n) if not state[j].folded]

        def make_obs(j, street, current_bet, min_raise):
            st = state[j]
            return {
                "street": street,
                "hole": st.hole,
                "board": tuple(board),
                "pot": sum(s.total for s in state),
                "to_call": min(current_bet - st.street_bet, hp[j].stack),
                "current_bet": current_bet,
                "my_street_bet": st.street_bet,
                "min_raise_to": current_bet + min_raise,
                "stack": hp[j].stack,
                "big_blind": bb,
                "order_index": j,
                "n_players": n,
                "n_unfolded": len(unfolded()),
                "opp_stacks": tuple(hp[k].stack for k in range(n)
                                    if k != j and not state[k].folded),
                "raises_this_street": raises,
                "i_am_aggressor": last_aggressor == j,
                "hand_no": self.hand_no,
            }

        def betting_round(street, first_idx, current_bet, min_raise):
            nonlocal raises, last_aggressor
            raises = 0 if street != "preflop" else raises
            need = {j: True for j in range(n)
                    if not state[j].folded and not state[j].all_in}
            idx = first_idx
            guard = 0
            while any(need.values()):
                guard += 1
                assert guard < 10000, "betting round failed to terminate"
                if len(unfolded()) == 1:
                    return
                j = idx % n
                idx += 1
                st = state[j]
                if st.folded or st.all_in or not need.get(j, False):
                    continue

                obs = make_obs(j, street, current_bet, min_raise)
                try:
                    action, amount = hp[j].strategy.act(obs)
                except Exception:
                    action, amount = "fold", 0

                to_call = current_bet - st.street_bet
                if action == "fold" and to_call <= 0:
                    action = "call"  # never fold for free

                if action == "raise":
                    raise_to = min(int(amount), st.street_bet + hp[j].stack)
                    is_all_in = raise_to == st.street_bet + hp[j].stack
                    if raise_to <= current_bet:
                        action = "call"
                    elif raise_to < current_bet + min_raise and not is_all_in:
                        action = "call"  # undersized non-all-in raise -> call
                    else:
                        pay(j, raise_to - st.street_bet)
                        min_raise = max(min_raise, raise_to - current_bet)
                        current_bet = raise_to
                        raises += 1
                        last_aggressor = j
                        for k in range(n):
                            if k != j and not state[k].folded and not state[k].all_in:
                                need[k] = True
                        need[j] = False
                        continue

                if action == "call":
                    if to_call > 0:
                        pay(j, to_call)
                    need[j] = False
                else:  # fold
                    st.folded = True
                    need[j] = False

        # --- preflop ---
        current_bet, min_raise = bb, bb
        first = 0 if n == 2 else 2 % n
        betting_round("preflop", first, current_bet, min_raise)

        # --- flop, turn, river ---
        for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
            if len(unfolded()) == 1:
                break
            for _ in range(ncards):
                board.append(deck.pop())
            for st in state:
                st.street_bet = 0
            last_aggressor = None
            postflop_first = 1 if n == 2 else 0
            betting_round(street, postflop_first, 0, bb)

        # deal out the board if the hand goes to showdown short of 5 cards
        if len(unfolded()) > 1:
            while len(board) < 5:
                board.append(deck.pop())

        self._award_pots(hp, state, board)
        for p in self.players:
            if p.stack == 0 and p.seat not in self.bust_order:
                self.bust_order.append(p.seat)
        assert sum(p.stack for p in self.players) == total_chips, "chips leaked"

    # ------------------------------------------------------------------ #

    def _award_pots(self, hp, state, board):
        n = len(hp)
        contribs = [state[j].total for j in range(n)]
        live = [j for j in range(n) if not state[j].folded]

        if len(live) == 1:
            hp[live[0]].stack += sum(contribs)
            return

        scores = {j: eval7(list(state[j].hole) + board) for j in live}
        prev = 0
        for level in sorted(set(c for c in contribs if c > 0)):
            pot = sum(min(c, level) - min(c, prev) for c in contribs)
            prev = level
            if pot == 0:
                continue
            eligible = [j for j in live if contribs[j] >= level]
            if not eligible:  # dead money from folded players only
                eligible = live
            if len(eligible) == 1:
                hp[eligible[0]].stack += pot  # includes uncalled-bet refunds
                continue
            best = max(scores[j] for j in eligible)
            winners = [j for j in eligible if scores[j] == best]
            share, rem = divmod(pot, len(winners))
            for i, j in enumerate(winners):
                hp[j].stack += share + (1 if i < rem else 0)
