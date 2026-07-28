#!/usr/bin/env python3
"""
No-Limit Texas Hold'em tournament simulator.

Six players, equal starting stacks, blinds escalate, last player standing wins.
Player 1 uses the simplest possible strategy (always all-in). Players 2-6 use
five distinct, elaborate strategies. No strategy has access to another
player's strategy — only to public information (actions, stacks, board).

Run: python3 holdem.py [n_sims] [seed]
"""

import random
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Cards & hand evaluation
# ---------------------------------------------------------------------------
# A card is an int 0..51. rank = card // 4 (0 = deuce ... 12 = ace), suit = card % 4.

RANK_NAMES = "23456789TJQKA"
SUIT_NAMES = "cdhs"


def card_str(c):
    return RANK_NAMES[c // 4] + SUIT_NAMES[c % 4]


def eval7(cards):
    """Return a comparable tuple ranking the best 5-card hand out of 7 cards.

    Category: 8 straight flush, 7 quads, 6 full house, 5 flush, 4 straight,
    3 trips, 2 two pair, 1 pair, 0 high card. Higher tuple = better hand.
    """
    ranks = [c // 4 for c in cards]
    suits = [c % 4 for c in cards]

    rank_count = Counter(ranks)
    suit_count = Counter(suits)

    flush_suit = None
    for s, n in suit_count.items():
        if n >= 5:
            flush_suit = s
            break

    def best_straight(rankset):
        # Ace plays low too (wheel).
        rs = set(rankset)
        if 12 in rs:
            rs.add(-1)
        best = None
        for high in range(12, 2, -1):
            if all(high - i in rs for i in range(5)):
                best = high
                break
        return best

    if flush_suit is not None:
        flush_ranks = [c // 4 for c in cards if c % 4 == flush_suit]
        sf = best_straight(flush_ranks)
        if sf is not None:
            return (8, sf)

    # Sort ranks by (count, rank) descending for kicker resolution.
    by_count = sorted(rank_count.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    counts = [n for _, n in by_count]

    if counts[0] == 4:
        quad = by_count[0][0]
        kicker = max(r for r in ranks if r != quad)
        return (7, quad, kicker)

    if counts[0] == 3 and counts[1] >= 2:
        return (6, by_count[0][0], by_count[1][0])

    if flush_suit is not None:
        top5 = sorted((c // 4 for c in cards if c % 4 == flush_suit), reverse=True)[:5]
        return (5, *top5)

    st = best_straight(ranks)
    if st is not None:
        return (4, st)

    if counts[0] == 3:
        trip = by_count[0][0]
        kickers = sorted((r for r in ranks if r != trip), reverse=True)[:2]
        return (3, trip, *kickers)

    if counts[0] == 2 and counts[1] == 2:
        p_hi, p_lo = by_count[0][0], by_count[1][0]
        kicker = max(r for r in ranks if r != p_hi and r != p_lo)
        return (2, p_hi, p_lo, kicker)

    if counts[0] == 2:
        pair = by_count[0][0]
        kickers = sorted((r for r in ranks if r != pair), reverse=True)[:3]
        return (1, pair, *kickers)

    return (0, *sorted(ranks, reverse=True)[:5])


# ---------------------------------------------------------------------------
# Equity & preflop helpers
# ---------------------------------------------------------------------------

def equity_vs_random(hole, board, n_opponents, trials, rng):
    """Monte Carlo equity of `hole` + `board` against n_opponents random hands."""
    if n_opponents <= 0:
        return 1.0
    dead = set(hole) | set(board)
    deck = [c for c in range(52) if c not in dead]
    need_board = 5 - len(board)
    score = 0.0
    for _ in range(trials):
        draw = rng.sample(deck, need_board + 2 * n_opponents)
        full_board = list(board) + draw[:need_board]
        mine = eval7(list(hole) + full_board)
        best_opp = None
        n_best = 0
        for i in range(n_opponents):
            opp = draw[need_board + 2 * i: need_board + 2 * i + 2]
            v = eval7(opp + full_board)
            if best_opp is None or v > best_opp:
                best_opp, n_best = v, 1
            elif v == best_opp:
                n_best += 1
        if mine > best_opp:
            score += 1.0
        elif mine == best_opp:
            score += 1.0 / (1 + n_best)
    return score / trials


def chen_score(hole):
    """Chen formula: classic preflop hand-strength score."""
    r1, r2 = sorted((hole[0] // 4, hole[1] // 4), reverse=True)
    suited = hole[0] % 4 == hole[1] % 4
    pts = {12: 10.0, 11: 8.0, 10: 7.0, 9: 6.0}.get(r1, (r1 + 2) / 2.0)
    if r1 == r2:
        return max(5.0, pts * 2)
    if suited:
        pts += 2
    gap = r1 - r2 - 1
    pts -= {0: 0, 1: 1, 2: 2, 3: 4}.get(gap, 5)
    if gap <= 1 and r1 < 10:
        pts += 1  # connector bonus (straight potential)
    return pts


def made_hand_strength(hole, board):
    """Cheap postflop heuristic in [0, 1]: made-hand quality plus draw potential."""
    full = list(hole) + list(board)
    v = eval7(full)
    board_v = eval7(list(board) + list(board)[:2]) if len(board) >= 5 else None
    cat = v[0]

    base = {0: 0.05, 1: 0.30, 2: 0.55, 3: 0.70, 4: 0.85, 5: 0.88, 6: 0.93,
            7: 0.98, 8: 1.0}[cat]

    # Pair quality: top pair with our hole card vs board pairing itself.
    if cat == 1:
        pair_rank = v[1]
        board_ranks = [c // 4 for c in board]
        hole_ranks = [c // 4 for c in hole]
        if pair_rank not in hole_ranks:
            base = 0.12  # board pair, we have nothing
        elif board_ranks and pair_rank >= max(board_ranks):
            base = 0.45  # top pair
        else:
            base = 0.25  # middle/bottom pair
    if board_v is not None and cat >= 2 and v[0] == board_v[0]:
        base *= 0.6  # the board itself makes most of our "hand"

    # Draws (only relevant before the river).
    if len(board) < 5:
        suits = Counter(c % 4 for c in full)
        if max(suits.values()) == 4 and any(
                Counter(c % 4 for c in hole)[s] >= 1 for s in suits if suits[s] == 4):
            base = max(base, 0.38)  # flush draw
        rs = set(c // 4 for c in full)
        if 12 in rs:
            rs.add(-1)
        for high in range(12, 2, -1):
            window = [high - i in rs for i in range(5)]
            if sum(window) == 4:
                base = max(base, 0.32)  # open-ended / gutshot-ish
                break
    return min(base, 1.0)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------
# Interface: decide(obs, rng) -> ("fold",) | ("call",) | ("raise", raise_to)
# obs is a dict of strictly public info + the player's own hole cards.
# observe(...) receives every public action so adaptive strategies can learn.
# Nobody ever sees another player's strategy or hole cards before showdown.


class Strategy:
    name = "base"

    def new_tournament(self):
        pass

    def observe(self, actor, action, street, to_call, pot, is_all_in):
        pass

    def decide(self, obs, rng):
        raise NotImplementedError


class AllInManiac(Strategy):
    """Player 1. The entire strategy, verbatim:

        if my_turn:
            bet = ALL IN
        fi
    """
    name = "Leeroy (All-In, Always)"

    def decide(self, obs, rng):
        return ("raise", obs["max_raise_to"])


class TAGShark(Strategy):
    """Tight-aggressive professional.

    Preflop: Chen-formula hand selection, tightened out of position and against
    raises; opens for 3bb, 3-bets premiums. Postflop: continuation-bets ~2/3 pot
    with equity or initiative, barrels strong made hands, floats draws when the
    price is right, and folds marginal hands to real aggression. Facing an
    all-in, verifies its equity with a Monte Carlo rollout before committing.
    """
    name = "TAG Shark"

    def decide(self, obs, rng):
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]
        street = obs["street"]

        if street == "preflop":
            score = chen_score(obs["hole"])
            # Positional tightening: early position needs a stronger hand.
            need = 8.5 - 2.5 * obs["position_frac"]
            facing_raise = to_call > bb
            if facing_raise:
                need += 1.5
            if score < need:
                return ("check",) if to_call == 0 else ("fold",)
            if score >= 11:  # premium: raise/3-bet big
                target = max(obs["min_raise_to"], to_call * 3 + pot)
                return ("raise", min(target, obs["max_raise_to"]))
            if not facing_raise:
                return ("raise", min(max(obs["min_raise_to"], 3 * bb),
                                     obs["max_raise_to"]))
            # Facing a raise with a decent-not-premium hand: call small, else fold.
            if to_call <= obs["stack"] * 0.12 or score >= 10:
                return ("call",)
            return ("fold",)

        strength = made_hand_strength(obs["hole"], obs["board"])
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0

        # Big decision (a third of our stack or more): pay for a real answer.
        if to_call > obs["stack"] * 0.33 and to_call > 0:
            eq = equity_vs_random(obs["hole"], obs["board"],
                                  obs["n_opponents"], 60, rng)
            return ("call",) if eq > pot_odds + 0.05 else ("fold",)

        if strength >= 0.55:
            target = obs["my_bet"] + to_call + int(0.66 * (pot + to_call))
            target = max(target, obs["min_raise_to"])
            return ("raise", min(target, obs["max_raise_to"]))
        if strength >= 0.30:
            if to_call == 0:
                return ("check",)
            return ("call",) if strength > pot_odds + 0.08 else ("fold",)
        return ("check",) if to_call == 0 else ("fold",)


class LAGMaverick(Strategy):
    """Loose-aggressive pressure player.

    Attacks with a wide range, three-bets light, semi-bluffs every draw, and
    fires randomized bluffs at pots nobody seems to want. The chaos is
    calculated: bluff frequency scales down as pot commitment scales up, and
    genuine stack-off decisions fall back on equity math.
    """
    name = "LAG Maverick"

    def decide(self, obs, rng):
        bb = obs["big_blind"]
        to_call = obs["to_call"]
        pot = obs["pot"]

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            if to_call > obs["stack"] * 0.35:  # someone shoved: get honest
                eq = equity_vs_random(obs["hole"], [], obs["n_opponents"], 60, rng)
                need = to_call / (pot + to_call)
                return ("call",) if eq > need + 0.03 else ("fold",)
            if score >= 9:
                target = max(obs["min_raise_to"], int(2.5 * (to_call + bb)) + pot // 2)
                return ("raise", min(target, obs["max_raise_to"]))
            if score >= 5 or rng.random() < 0.25:  # wide opens + random spice
                if to_call <= 3 * bb:
                    if to_call == 0 or rng.random() < 0.5:
                        return ("raise", min(max(obs["min_raise_to"], 3 * bb),
                                             obs["max_raise_to"]))
                    return ("call",)
                return ("call",) if score >= 8 else ("fold",)
            return ("check",) if to_call == 0 else ("fold",)

        strength = made_hand_strength(obs["hole"], obs["board"])
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0

        if to_call > obs["stack"] * 0.4 and to_call > 0:
            eq = equity_vs_random(obs["hole"], obs["board"],
                                  obs["n_opponents"], 60, rng)
            return ("call",) if eq > pot_odds else ("fold",)

        # Semi-bluff draws and value-bet made hands with the same big line.
        if strength >= 0.5 or (0.3 <= strength < 0.5 and rng.random() < 0.6):
            target = obs["my_bet"] + to_call + int(0.75 * (pot + to_call))
            return ("raise", min(max(target, obs["min_raise_to"]),
                                 obs["max_raise_to"]))
        # Pure bluff stab at orphan pots.
        if to_call == 0 and rng.random() < 0.30:
            return ("raise", min(max(obs["min_raise_to"],
                                     obs["my_bet"] + int(0.6 * pot)),
                                 obs["max_raise_to"]))
        if to_call == 0:
            return ("check",)
        return ("call",) if strength > pot_odds + 0.05 else ("fold",)


class NitFortress(Strategy):
    """Ultra-tight premium hunter.

    Folds almost everything and waits for the top of the deck: big pairs and
    big-slick-tier hands preflop, two-pair-or-better commitment postflop. When
    the moment comes, it plays for entire stacks without blinking. Designed to
    let maniacs hang themselves.
    """
    name = "Nit Fortress"

    PREMIUM = 10.5  # Chen threshold: TT+, AK, AQs territory

    def decide(self, obs, rng):
        to_call = obs["to_call"]
        pot = obs["pot"]

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            # Late position, unopened pot: steal occasionally with playable hands.
            if (score >= 7.5 and to_call <= obs["big_blind"]
                    and obs["position_frac"] > 0.6):
                return ("raise", min(max(obs["min_raise_to"], 3 * obs["big_blind"]),
                                     obs["max_raise_to"]))
            if score < self.PREMIUM:
                return ("check",) if to_call == 0 else ("fold",)
            # Premium: raise big; call off any shove.
            if to_call >= obs["stack"]:
                return ("call",)
            target = max(obs["min_raise_to"], 4 * obs["big_blind"] + 2 * to_call)
            return ("raise", min(target, obs["max_raise_to"]))

        strength = made_hand_strength(obs["hole"], obs["board"])
        if strength >= 0.55:
            if to_call >= obs["stack"]:
                return ("call",)
            target = obs["my_bet"] + to_call + int(0.8 * (pot + to_call))
            return ("raise", min(max(target, obs["min_raise_to"]),
                                 obs["max_raise_to"]))
        if strength >= 0.4 and to_call <= pot // 3:
            return ("call",) if to_call > 0 else ("check",)
        if to_call == 0:
            return ("check",)
        # Strong overpair-ish holdings still call moderate bets.
        pot_odds = to_call / (pot + to_call)
        if strength >= 0.30 and pot_odds < 0.25:
            return ("call",)
        return ("fold",)


class PotOddsOracle(Strategy):
    """The pure mathematician.

    Every decision is an expected-value computation: Monte Carlo equity versus
    the live opponents, compared against exact pot odds. Raises when equity
    dominates the field average, calls when priced in, folds the instant the
    numbers go negative. No fear, no reads, no tilt — only arithmetic.
    """
    name = "Pot-Odds Oracle"

    def decide(self, obs, rng):
        to_call = obs["to_call"]
        pot = obs["pot"]
        n_opp = obs["n_opponents"]
        trials = 80 if to_call > obs["stack"] // 4 else 45
        eq = equity_vs_random(obs["hole"], obs["board"], n_opp, trials, rng)
        fair_share = 1.0 / (n_opp + 1)

        if to_call == 0:
            if eq > fair_share * 1.6:  # clearly above average: bet for value
                target = obs["my_bet"] + int(0.7 * pot) if pot else obs["min_raise_to"]
                return ("raise", min(max(target, obs["min_raise_to"]),
                                     obs["max_raise_to"]))
            return ("check",)

        pot_odds = to_call / (pot + to_call)
        if eq > max(fair_share * 1.9, pot_odds + 0.22) and to_call < obs["stack"]:
            target = obs["my_bet"] + to_call + int(0.8 * (pot + to_call))
            return ("raise", min(max(target, obs["min_raise_to"]),
                                 obs["max_raise_to"]))
        if eq > pot_odds + 0.02:
            return ("call",)
        return ("fold",)


class TheProfiler(Strategy):
    """Adaptive exploiter.

    Builds a statistical profile of every opponent from public actions alone:
    raise frequency, shove frequency, fold frequency. Against maniacs who shove
    everything, its calling range explodes wide open (equity vs a random hand
    is all that matters). Against nits, a raise means the nuts — get out. The
    counter-puncher of the table.
    """
    name = "The Profiler"

    def new_tournament(self):
        self.actions = Counter()    # (player, kind) -> count
        self.decisions = Counter()  # player -> total observed decisions

    def observe(self, actor, action, street, to_call, pot, is_all_in):
        self.decisions[actor] += 1
        if is_all_in and action == "raise":
            self.actions[(actor, "shove")] += 1
        elif action == "raise":
            self.actions[(actor, "raise")] += 1
        elif action == "fold":
            self.actions[(actor, "fold")] += 1

    def shove_rate(self, player):
        n = self.decisions[player]
        if n < 4:
            return 0.15  # prior: normal players rarely shove
        return self.actions[(player, "shove")] / n

    def decide(self, obs, rng):
        to_call = obs["to_call"]
        pot = obs["pot"]
        bb = obs["big_blind"]
        aggressor = obs["last_aggressor"]

        maniac_factor = self.shove_rate(aggressor) if aggressor is not None else 0.15

        if to_call > 0 and to_call >= obs["stack"] * 0.3:
            # Big money in front of us: how wide is the bettor, really?
            eq = equity_vs_random(obs["hole"], obs["board"],
                                  obs["n_opponents"], 70, rng)
            pot_odds = to_call / (pot + to_call)
            # vs a habitual shover, any equity edge over the price is a snap call;
            # vs someone who almost never shoves, demand a huge margin.
            margin = 0.01 + 0.20 * max(0.0, 1.0 - maniac_factor * 2.5)
            return ("call",) if eq > pot_odds + margin else ("fold",)

        if obs["street"] == "preflop":
            score = chen_score(obs["hole"])
            need = 7.5 - 2.0 * obs["position_frac"]
            if to_call > bb and maniac_factor < 0.3:
                need += 1.5  # a real player raised: respect it
            if score < need:
                return ("check",) if to_call == 0 else ("fold",)
            if score >= 10 or (score >= 8 and maniac_factor > 0.4):
                target = max(obs["min_raise_to"], 3 * bb + 2 * to_call)
                return ("raise", min(target, obs["max_raise_to"]))
            return ("call",) if to_call > 0 else \
                ("raise", min(max(obs["min_raise_to"], int(2.5 * bb)),
                              obs["max_raise_to"]))

        strength = made_hand_strength(obs["hole"], obs["board"])
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
        threshold = pot_odds + (0.02 if maniac_factor > 0.35 else 0.12)

        if strength >= 0.55:
            target = obs["my_bet"] + to_call + int(0.7 * (pot + to_call))
            return ("raise", min(max(target, obs["min_raise_to"]),
                                 obs["max_raise_to"]))
        if to_call == 0:
            return ("check",)
        return ("call",) if strength > threshold else ("fold",)


# ---------------------------------------------------------------------------
# Game engine
# ---------------------------------------------------------------------------

class Player:
    def __init__(self, pid, strategy, stack):
        self.pid = pid
        self.strategy = strategy
        self.stack = stack


def play_hand(players, button, blinds, rng, strategies_all):
    """Play one hand of NLHE among `players` (list of Player, stacks > 0).

    Mutates stacks. Supports side pots (mandatory: player 1 is all-in a lot).
    """
    sb_amt, bb_amt = blinds
    n = len(players)
    deck = list(range(52))
    rng.shuffle(deck)

    holes = {}
    for i, p in enumerate(players):
        holes[p.pid] = [deck.pop(), deck.pop()]

    contributed = {p.pid: 0 for p in players}   # total this hand (side pots)
    street_bet = {p.pid: 0 for p in players}    # committed this street
    folded = set()
    all_in = set()

    def post(p, amount):
        amount = min(amount, p.stack)
        p.stack -= amount
        contributed[p.pid] += amount
        street_bet[p.pid] += amount
        if p.stack == 0:
            all_in.add(p.pid)
        return amount

    # Blinds. Heads-up: button posts SB.
    if n == 2:
        sb_pos, bb_pos = button, (button + 1) % n
    else:
        sb_pos, bb_pos = (button + 1) % n, (button + 2) % n
    post(players[sb_pos], sb_amt)
    post(players[bb_pos], bb_amt)

    board = []

    def pot_total():
        return sum(contributed.values())

    def live():
        return [p for p in players if p.pid not in folded]

    def betting_round(street, first_idx):
        current_bet = max(street_bet.values())
        min_raise = bb_amt
        can_act = [p for p in players
                   if p.pid not in folded and p.pid not in all_in]
        if len(can_act) == 0:
            return
        if len([p for p in players if p.pid not in folded]) < 2:
            return
        # Everyone who can act must act at least once (or until bets equalize).
        pending = set(p.pid for p in can_act)
        idx = first_idx
        guard = 0
        while pending:
            guard += 1
            if guard > 500:
                break
            p = players[idx % n]
            idx += 1
            if p.pid in folded or p.pid in all_in or p.pid not in pending:
                if p.pid in pending:
                    pending.discard(p.pid)
                continue
            if len([q for q in players if q.pid not in folded]) < 2:
                return
            to_call = current_bet - street_bet[p.pid]
            obs = {
                "hole": holes[p.pid],
                "board": list(board),
                "pot": pot_total(),
                "to_call": min(to_call, p.stack),
                "my_bet": street_bet[p.pid],
                "stack": p.stack,
                "big_blind": bb_amt,
                "street": street,
                "n_opponents": len(live()) - 1,
                "position_frac": (((players.index(p) - button) % n) / max(1, n - 1)),
                "min_raise_to": current_bet + min_raise,
                "max_raise_to": street_bet[p.pid] + p.stack,
                "last_aggressor": betting_round.last_aggressor,
            }
            decision = p.strategy.decide(obs, rng)
            kind = decision[0]

            if kind in ("check",) and to_call > 0:
                kind = "fold"  # illegal check = fold (strategies shouldn't do this)

            if kind == "fold":
                folded.add(p.pid)
                pending.discard(p.pid)
                action_name = "fold"
                went_all_in = False
            elif kind in ("call", "check"):
                post(p, to_call)
                pending.discard(p.pid)
                action_name = "call" if to_call > 0 else "check"
                went_all_in = p.pid in all_in
            else:  # raise
                target = decision[1]
                max_to = street_bet[p.pid] + p.stack
                target = min(target, max_to)
                legal_min = current_bet + min_raise
                if target <= current_bet:  # can't even call-raise: treat as call
                    post(p, to_call)
                    pending.discard(p.pid)
                    action_name = "call"
                    went_all_in = p.pid in all_in
                else:
                    if target < legal_min and target < max_to:
                        target = min(legal_min, max_to)
                    raise_size = target - current_bet
                    post(p, target - street_bet[p.pid])
                    if raise_size >= min_raise:
                        min_raise = raise_size
                    current_bet = max(current_bet, street_bet[p.pid])
                    betting_round.last_aggressor = p.pid
                    # Everyone else must respond.
                    pending = set(
                        q.pid for q in players
                        if q.pid not in folded and q.pid not in all_in
                        and q.pid != p.pid)
                    pending.discard(p.pid)
                    action_name = "raise"
                    went_all_in = p.pid in all_in
            for s in strategies_all:
                s.observe(p.pid, action_name, street,
                          to_call, pot_total(), went_all_in)

    betting_round.last_aggressor = None

    # Preflop: first to act is left of BB.
    betting_round.last_aggressor = players[bb_pos].pid
    betting_round("preflop", (bb_pos + 1) % n)

    for street, n_cards in (("flop", 3), ("turn", 1), ("river", 1)):
        if len(live()) < 2:
            break
        for pid in street_bet:
            street_bet[pid] = 0
        board.extend(deck.pop() for _ in range(n_cards))
        actionable = [p for p in players
                      if p.pid not in folded and p.pid not in all_in]
        if len(actionable) >= 2:
            betting_round.last_aggressor = None
            betting_round(street, (button + 1) % n)

    # --- Showdown / pot distribution with side pots -------------------------
    remaining = live()
    if len(remaining) == 1:
        remaining[0].stack += pot_total()
        return

    while len(board) < 5:
        board.append(deck.pop())

    scores = {p.pid: eval7(holes[p.pid] + board) for p in remaining}

    # Side-pot algorithm: peel off contribution layers.
    levels = sorted(set(contributed[p.pid] for p in players if contributed[p.pid] > 0))
    prev = 0
    payouts = Counter()
    for lvl in levels:
        layer = 0
        for p in players:
            chunk = max(0, min(contributed[p.pid], lvl) - prev)
            layer += chunk
        eligible = [p for p in remaining if contributed[p.pid] >= lvl]
        if layer and eligible:
            best = max(scores[p.pid] for p in eligible)
            winners = [p for p in eligible if scores[p.pid] == best]
            share, odd = divmod(layer, len(winners))
            for i, w in enumerate(winners):
                payouts[w.pid] += share + (1 if i < odd else 0)
        elif layer:
            # Everyone at this level folded (can't happen for live layers) —
            # refund proportionally to the sole live player.
            payouts[remaining[0].pid] += layer
        prev = lvl
    for p in players:
        p.stack += payouts[p.pid]


def run_tournament(strategy_factories, starting_stack, rng):
    strategies = {pid: f() for pid, f in strategy_factories.items()}
    for s in strategies.values():
        s.new_tournament()
    players = [Player(pid, strategies[pid], starting_stack)
               for pid in sorted(strategy_factories)]
    button = rng.randrange(len(players))
    hand_no = 0
    sb, bb = 10, 20

    while len(players) > 1 and hand_no < 3000:
        hand_no += 1
        # Blind escalation: double every 15 hands so tournaments terminate.
        level = hand_no // 15
        sb, bb = 10 * (2 ** level), 20 * (2 ** level)
        play_hand(players, button % len(players), (sb, bb), rng,
                  list(strategies.values()))
        # Eliminate busted players; keep seat order for the survivors.
        survivors = [p for p in players if p.stack > 0]
        if len(survivors) < len(players):
            players = survivors
        button += 1
    if len(players) == 1:
        return players[0].pid, hand_no
    return max(players, key=lambda p: p.stack).pid, hand_no  # safety net


# ---------------------------------------------------------------------------
# Simulation harness
# ---------------------------------------------------------------------------

STRATEGY_FACTORIES = {
    1: AllInManiac,
    2: TAGShark,
    3: LAGMaverick,
    4: NitFortress,
    5: PotOddsOracle,
    6: TheProfiler,
}


def main():
    n_sims = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    rng = random.Random(seed)

    starting_stack = 1000
    wins = Counter()
    hand_counts = []

    names = {pid: cls.name for pid, cls in STRATEGY_FACTORIES.items()}

    for sim in range(1, n_sims + 1):
        winner, hands = run_tournament(STRATEGY_FACTORIES, starting_stack, rng)
        wins[winner] += 1
        hand_counts.append(hands)
        if sim % 10 == 0:
            print(f"  ... {sim}/{n_sims} tournaments done", flush=True)

    print()
    print("=" * 66)
    print(f"  TEXAS HOLD'EM — {n_sims} full tournaments, 6 players, "
          f"{starting_stack} chips each")
    print("  Winner = last player standing (winner winner chicken dinner)")
    print("=" * 66)
    print()
    max_wins = max(wins.values()) if wins else 1
    for pid in sorted(STRATEGY_FACTORIES):
        w = wins[pid]
        bar = "█" * round(w / max_wins * 40)
        print(f"  P{pid} {names[pid]:<24} {bar:<40} {w:>3}  ({w / n_sims:.0%})")
    print()
    avg_hands = sum(hand_counts) / len(hand_counts)
    print(f"  Avg tournament length: {avg_hands:.0f} hands "
          f"(min {min(hand_counts)}, max {max(hand_counts)})")
    print()
    return wins, names, n_sims


if __name__ == "__main__":
    main()
