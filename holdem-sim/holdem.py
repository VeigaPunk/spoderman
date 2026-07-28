"""No-limit Texas Hold'em tournament simulator.

6 players, identical starting stacks. Player 1 shoves every turn.
Players 2-6 run elaborate strategies. Nobody knows anybody's strategy.
100 tournaments -> histogram of the last player standing.
"""

import random
from collections import Counter
from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}


def new_deck(rng):
    deck = [(RANK_VAL[r], s) for r in RANKS for s in SUITS]
    rng.shuffle(deck)
    return deck


# ---------------------------------------------------------------- evaluator

def rank5(cards):
    """Score a 5-card hand. Higher tuple wins."""
    vals = sorted((c[0] for c in cards), reverse=True)
    suits = {c[1] for c in cards}
    flush = len(suits) == 1
    counts = Counter(vals)
    groups = sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))
    shape = [g[1] for g in groups]
    ordered = [g[0] for g in groups]

    straight_high = 0
    uniq = sorted(set(vals), reverse=True)
    if len(uniq) == 5:
        if uniq[0] - uniq[4] == 4:
            straight_high = uniq[0]
        elif uniq == [14, 5, 4, 3, 2]:
            straight_high = 5

    if flush and straight_high:
        return (8, straight_high)
    if shape == [4, 1]:
        return (7, ordered[0], ordered[1])
    if shape == [3, 2]:
        return (6, ordered[0], ordered[1])
    if flush:
        return (5, *vals)
    if straight_high:
        return (4, straight_high)
    if shape == [3, 1, 1]:
        return (3, ordered[0], ordered[1], ordered[2])
    if shape == [2, 2, 1]:
        return (2, ordered[0], ordered[1], ordered[2])
    if shape == [2, 1, 1, 1]:
        return (1, ordered[0], *ordered[1:])
    return (0, *vals)


def best7(cards):
    return max(rank5(c) for c in combinations(cards, 5))


# ---------------------------------------------------------------- helpers

def chen_score(hole):
    """Chen formula for preflop hand strength."""
    (v1, s1), (v2, s2) = sorted(hole, reverse=True)
    pts = {14: 10, 13: 8, 12: 7, 11: 6}.get(v1, v1 / 2)
    if v1 == v2:
        pts = max(pts * 2, 5)
    if s1 == s2:
        pts += 2
    gap = v1 - v2
    if v1 != v2:
        pts -= {1: 0, 2: 1, 3: 2, 4: 4}.get(gap, 5)
        if gap <= 2 and v1 < 12:
            pts += 1
    return pts


def hand_strength(hole, board):
    """Crude made-hand strength in [0,1] once a flop exists."""
    score = best7(list(hole) + list(board))
    cat = score[0]
    base = cat / 8.0
    if cat == 1:  # one pair: is it top pair or better?
        pair_val = score[1]
        board_high = max(c[0] for c in board)
        if pair_val >= board_high:
            base += 0.06
    return min(base + max(c[0] for c in hole) / 140.0, 1.0)


def count_outs(hole, board):
    """Approximate flush/straight draw outs."""
    cards = list(hole) + list(board)
    outs = 0
    suit_counts = Counter(c[1] for c in cards)
    if any(n == 4 for n in suit_counts.values()):
        outs += 9
    vals = sorted({c[0] for c in cards})
    vset = set(vals)
    if 14 in vset:
        vset.add(1)
    for lo in range(1, 11):
        window = set(range(lo, lo + 5))
        missing = window - vset
        if len(missing) == 1:
            outs += 4
            break
    return outs


def mc_equity(hole, board, n_opp, rng, rollouts=40):
    """Monte Carlo equity vs n_opp random hands."""
    known = set(hole) | set(board)
    stub = [(RANK_VAL[r], s) for r in RANKS for s in SUITS if (RANK_VAL[r], s) not in known]
    wins = 0.0
    need_board = 5 - len(board)
    n_opp = min(n_opp, 2)  # cap for speed; approximates multiway
    for _ in range(rollouts):
        draw = rng.sample(stub, need_board + 2 * n_opp)
        full = list(board) + draw[:need_board]
        mine = best7(list(hole) + full)
        beaten = tied = False
        for k in range(n_opp):
            opp = draw[need_board + 2 * k: need_board + 2 * k + 2]
            theirs = best7(opp + full)
            if theirs > mine:
                beaten = True
                break
            if theirs == mine:
                tied = True
        if not beaten:
            wins += 0.5 if tied else 1.0
    return wins / rollouts


# ---------------------------------------------------------------- strategies
# Each strategy gets a view dict and returns ("fold"|"call"|"raise", amount).
# view: hole, board, pot, to_call, stack, min_raise, position, n_active,
#       n_seated, big_blind, street, rng

def strat_allin_andy(v):
    """Player 1. if my_turn then bet = All in fi."""
    return ("raise", v["stack"])


def strat_tag_tycoon(v):
    """Tight-aggressive. Chen-formula preflop, value-bets made hands."""
    rng = v["rng"]
    if v["street"] == "preflop":
        pts = chen_score(v["hole"])
        pos_bonus = 1.5 if v["position"] >= v["n_active"] - 2 else 0
        pts += pos_bonus
        if pts >= 10:
            return ("raise", min(v["stack"], max(v["min_raise"], 3 * v["big_blind"] + v["to_call"])))
        if pts >= 7.5:
            return ("call", 0) if v["to_call"] <= 4 * v["big_blind"] else ("fold", 0)
        if pts >= 6 and v["to_call"] == 0:
            return ("call", 0)
        return ("fold", 0) if v["to_call"] > 0 else ("call", 0)
    hs = hand_strength(v["hole"], v["board"])
    if hs >= 0.55:
        bet = min(v["stack"], max(v["min_raise"], int(v["pot"] * 0.75)))
        return ("raise", bet)
    if hs >= 0.30:
        if v["to_call"] <= v["pot"] // 3:
            return ("call", 0)
        return ("fold", 0)
    if v["to_call"] == 0:
        return ("call", 0)
    return ("fold", 0)


def strat_lag_lunatic(v):
    """Loose-aggressive. Semi-bluffs draws, fires random barrels."""
    rng = v["rng"]
    if v["street"] == "preflop":
        pts = chen_score(v["hole"])
        if pts >= 9 or (pts >= 5 and rng.random() < 0.45):
            return ("raise", min(v["stack"], max(v["min_raise"], int(2.5 * v["big_blind"]) + v["to_call"])))
        if pts >= 4 and v["to_call"] <= 3 * v["big_blind"]:
            return ("call", 0)
        return ("fold", 0) if v["to_call"] > 0 else ("call", 0)
    hs = hand_strength(v["hole"], v["board"])
    outs = count_outs(v["hole"], v["board"])
    draw_equity = outs * (0.04 if v["street"] == "flop" else 0.02)
    power = max(hs, draw_equity)
    if power >= 0.5 or (rng.random() < 0.22 and v["to_call"] == 0):
        bet = min(v["stack"], max(v["min_raise"], int(v["pot"] * rng.choice([0.5, 0.8, 1.1]))))
        return ("raise", bet)
    if power >= 0.25 and v["to_call"] <= v["pot"] // 2:
        return ("call", 0)
    if v["to_call"] == 0:
        return ("call", 0)
    return ("fold", 0)


def strat_pot_odds_professor(v):
    """Calls only when pot odds beat estimated equity (rule of 4 and 2)."""
    if v["street"] == "preflop":
        pts = chen_score(v["hole"])
        equity = min(pts / 20.0 + 0.15, 0.85)
    else:
        hs = hand_strength(v["hole"], v["board"])
        outs = count_outs(v["hole"], v["board"])
        equity = min(hs * 0.8 + outs * (0.04 if v["street"] == "flop" else 0.02), 0.95)
    if v["to_call"] == 0:
        if equity > 0.55:
            return ("raise", min(v["stack"], max(v["min_raise"], int(v["pot"] * 0.66) or v["big_blind"] * 2)))
        return ("call", 0)
    pot_odds = v["to_call"] / (v["pot"] + v["to_call"])
    if equity > pot_odds + 0.22:
        return ("raise", min(v["stack"], max(v["min_raise"], v["to_call"] * 2 + v["pot"] // 2)))
    if equity > pot_odds:
        return ("call", 0)
    return ("fold", 0)


def strat_monte_carlo_machiavelli(v):
    """Monte Carlo equity rollouts; bets proportional to edge."""
    rng = v["rng"]
    n_opp = max(v["n_active"] - 1, 1)
    if v["street"] == "preflop":
        pts = chen_score(v["hole"])
        eq = min(pts / 18.0 + 0.18, 0.9)
    else:
        eq = mc_equity(v["hole"], v["board"], n_opp, rng)
    fair_share = 1.0 / v["n_active"]
    edge = eq - fair_share
    if v["to_call"] == 0:
        if edge > 0.18:
            return ("raise", min(v["stack"], max(v["min_raise"], int(v["pot"] * (0.5 + edge)))))
        return ("call", 0)
    pot_odds = v["to_call"] / (v["pot"] + v["to_call"])
    if eq > pot_odds + 0.28:
        return ("raise", min(v["stack"], max(v["min_raise"], v["to_call"] * 2)))
    if eq > pot_odds + 0.03:
        return ("call", 0)
    return ("fold", 0)


def strat_positional_predator(v):
    """Position-driven: steals late, plays snug early, pressures short pots."""
    rng = v["rng"]
    late = v["position"] >= v["n_active"] - 2
    early = v["position"] <= 1
    if v["street"] == "preflop":
        pts = chen_score(v["hole"])
        need = 9 if early else (7 if not late else 5.5)
        if pts >= need + 2:
            return ("raise", min(v["stack"], max(v["min_raise"], 3 * v["big_blind"] + v["to_call"])))
        if pts >= need:
            if late and v["to_call"] <= v["big_blind"] and rng.random() < 0.6:
                return ("raise", min(v["stack"], max(v["min_raise"], int(2.5 * v["big_blind"]))))
            return ("call", 0) if v["to_call"] <= 3 * v["big_blind"] else ("fold", 0)
        return ("fold", 0) if v["to_call"] > 0 else ("call", 0)
    hs = hand_strength(v["hole"], v["board"])
    threshold = 0.45 if late else 0.55
    if hs >= threshold:
        return ("raise", min(v["stack"], max(v["min_raise"], int(v["pot"] * 0.7))))
    if late and v["to_call"] == 0 and rng.random() < 0.3:
        return ("raise", min(v["stack"], max(v["min_raise"], int(v["pot"] * 0.5) or 2 * v["big_blind"])))
    if hs >= 0.25 and v["to_call"] <= v["pot"] // 3:
        return ("call", 0)
    if v["to_call"] == 0:
        return ("call", 0)
    return ("fold", 0)


PLAYERS = [
    ("P1 AllInAndy", strat_allin_andy),
    ("P2 TagTycoon", strat_tag_tycoon),
    ("P3 LagLunatic", strat_lag_lunatic),
    ("P4 PotOddsProf", strat_pot_odds_professor),
    ("P5 MonteCarloMac", strat_monte_carlo_machiavelli),
    ("P6 PositionPred", strat_positional_predator),
]


# ---------------------------------------------------------------- engine

class Seat:
    __slots__ = ("name", "strat", "stack", "hole", "committed", "total", "folded", "allin")

    def __init__(self, name, strat, stack):
        self.name = name
        self.strat = strat
        self.stack = stack
        self.hole = None
        self.committed = 0   # this street
        self.total = 0       # whole hand (for pot building)
        self.folded = False
        self.allin = False

    def put_in(self, amount):
        pay = min(amount, self.stack)
        self.stack -= pay
        self.committed += pay
        self.total += pay
        if self.stack == 0:
            self.allin = True


def betting_round(seats, order, board, street, big_blind, rng, current_bet, min_raise):
    """Run one betting street. Returns nothing; mutates seats."""
    live = [s for s in order if not s.folded and not s.allin]
    if len(live) <= 1:
        return
    need_action = {id(s) for s in live}
    idx = 0
    n = len(order)
    guard = 0
    while need_action and guard < 500:
        guard += 1
        seat = order[idx % n]
        idx += 1
        if seat.folded or seat.allin or id(seat) not in need_action:
            continue
        contenders = [s for s in seats if not s.folded]
        if len(contenders) == 1:
            return
        to_call = current_bet - seat.committed
        pot = sum(s.total for s in seats)
        view = {
            "hole": seat.hole, "board": board, "pot": pot,
            "to_call": to_call, "stack": seat.stack,
            "min_raise": to_call + min_raise,
            "position": order.index(seat), "n_active": len(contenders),
            "n_seated": len(seats), "big_blind": big_blind,
            "street": street, "rng": rng,
        }
        action, amount = seat.strat(view)
        if action == "fold":
            if to_call == 0:
                action = "call"
            else:
                seat.folded = True
                need_action.discard(id(seat))
                continue
        if action == "call":
            seat.put_in(to_call)
            need_action.discard(id(seat))
            continue
        # raise
        amount = max(0, min(amount, seat.stack))
        if amount < to_call + min_raise and amount < seat.stack:
            # not a legal raise -> treat as call
            seat.put_in(to_call)
            need_action.discard(id(seat))
            continue
        seat.put_in(amount)
        if seat.committed > current_bet:
            raise_size = seat.committed - current_bet
            if raise_size >= min_raise:
                min_raise = raise_size
            current_bet = seat.committed
            need_action = {id(s) for s in order if not s.folded and not s.allin}
        need_action.discard(id(seat))


def settle_pots(seats, board):
    """Distribute the pot(s), handling side pots."""
    contenders = [s for s in seats if not s.folded]
    total_pot = sum(s.total for s in seats)
    if len(contenders) == 1:
        contenders[0].stack += total_pot
        return
    scores = {id(s): best7(list(s.hole) + list(board)) for s in contenders}
    caps = sorted({s.total for s in seats if s.total > 0})
    prev = 0
    for cap in caps:
        pot = sum(min(s.total, cap) - min(s.total, prev) for s in seats)
        prev = cap
        eligible = [s for s in contenders if s.total >= cap]
        if not eligible:
            eligible = contenders
        best = max(scores[id(s)] for s in eligible)
        winners = [s for s in eligible if scores[id(s)] == best]
        share, odd = divmod(pot, len(winners))
        for i, w in enumerate(winners):
            w.stack += share + (1 if i < odd else 0)


def play_hand(seats, button, big_blind, rng):
    """One full hand of hold'em among seats with chips."""
    for s in seats:
        s.hole = None
        s.committed = 0
        s.total = 0
        s.folded = False
        s.allin = False
    deck = new_deck(rng)
    for s in seats:
        s.hole = (deck.pop(), deck.pop())
    n = len(seats)
    sb_seat = seats[(button + 1) % n]
    bb_seat = seats[(button + 2) % n] if n > 2 else seats[button % n]
    if n == 2:
        sb_seat = seats[button % n]
        bb_seat = seats[(button + 1) % n]
    for seat, blind in ((sb_seat, big_blind // 2), (bb_seat, big_blind)):
        seat.put_in(blind)

    board = []
    first = (button + 3) % n if n > 2 else button % n
    order = [seats[(first + i) % n] for i in range(n)]
    betting_round(seats, order, board, "preflop", big_blind, rng,
                  current_bet=big_blind, min_raise=big_blind)

    post_first = (button + 1) % n
    post_order = [seats[(post_first + i) % n] for i in range(n)]
    for street, ncards in (("flop", 3), ("turn", 1), ("river", 1)):
        if len([s for s in seats if not s.folded]) <= 1:
            break
        for s in seats:
            s.committed = 0
        deck.pop()  # burn
        board.extend(deck.pop() for _ in range(ncards))
        betting_round(seats, post_order, board, street, big_blind, rng,
                      current_bet=0, min_raise=big_blind)

    while len(board) < 5 and len([s for s in seats if not s.folded]) > 1:
        board.append(deck.pop())
    settle_pots(seats, board)


def play_tournament(rng, start_stack=1000, big_blind=20):
    seats = [Seat(name, strat, start_stack) for name, strat in PLAYERS]
    button = rng.randrange(len(seats))
    hand_no = 0
    bb = big_blind
    while len(seats) > 1 and hand_no < 2000:
        hand_no += 1
        if hand_no % 25 == 0:
            bb *= 2  # blind escalation guarantees termination
        play_hand(seats, button % len(seats), bb, rng)
        seats = [s for s in seats if s.stack > 0]
        button += 1
    if len(seats) == 1:
        return seats[0].name
    return max(seats, key=lambda s: s.stack).name


# ---------------------------------------------------------------- main

def main():
    rng = random.Random(1337)
    n_sims = 100
    wins = Counter()
    for i in range(n_sims):
        winner = play_tournament(rng)
        wins[winner] += 1
        if (i + 1) % 20 == 0:
            print(f"  ... {i + 1}/{n_sims} tournaments done")

    names = [name for name, _ in PLAYERS]
    print("\n=== WINNER WINNER CHICKEN DINNER HISTOGRAM (100 tournaments) ===\n")
    peak = max(wins.values())
    for name in names:
        w = wins[name]
        bar = "#" * round(w * 60 / peak) if peak else ""
        print(f"{name:<18} {w:>3} | {bar}")
    print()

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        counts = [wins[n] for n in names]
        colors = ["#d62728"] + ["#1f77b4"] * 5
        fig, ax = plt.subplots(figsize=(10, 5))
        bars = ax.bar(names, counts, color=colors)
        ax.bar_label(bars)
        ax.set_ylabel("Tournament wins (out of 100)")
        ax.set_title("Last player standing — 100 Hold'em tournaments\n"
                      "(red = the 'if my_turn then ALL IN fi' bot)")
        plt.xticks(rotation=20, ha="right")
        plt.tight_layout()
        plt.savefig("holdem-sim/winners_histogram.png", dpi=120)
        print("Saved holdem-sim/winners_histogram.png")
    except ImportError:
        print("(matplotlib not available; text histogram only)")

    return wins


if __name__ == "__main__":
    main()
