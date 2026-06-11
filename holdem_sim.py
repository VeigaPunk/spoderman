#!/usr/bin/env python3
"""
Texas Hold'em Poker Tournament Simulator
6 players | 100 tournaments | Last chip standing = winner
"""
import random
from collections import defaultdict
from itertools import combinations

# ============================================================
# CARD ENGINE
# ============================================================

RANKS = '23456789TJQKA'
SUITS = 'hdcs'
RV = {r: i for i, r in enumerate(RANKS)}


class Card:
    __slots__ = ('rank', 'suit', 'value')

    def __init__(self, r, s):
        self.rank = r
        self.suit = s
        self.value = RV[r]

    def __repr__(self):
        return f"{self.rank}{self.suit}"


def new_deck():
    cards = [Card(r, s) for r in RANKS for s in SUITS]
    random.shuffle(cards)
    return cards


# ============================================================
# HAND EVALUATOR
# ============================================================

def score5(cards):
    vals = sorted([c.value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    flush = len(set(suits)) == 1

    sv = vals
    straight = (vals[0] - vals[4] == 4 and len(set(vals)) == 5)
    if not straight and vals == [12, 3, 2, 1, 0]:  # wheel A-2-3-4-5
        straight = True
        sv = [3, 2, 1, 0, -1]

    cnt = defaultdict(int)
    for v in vals:
        cnt[v] += 1
    grp = sorted(cnt.items(), key=lambda x: (x[1], x[0]), reverse=True)
    gc = [g[1] for g in grp]
    gv = [g[0] for g in grp]

    if straight and flush: return (8, sv)
    if gc[0] == 4:          return (7, gv)
    if gc[:2] == [3, 2]:    return (6, gv)
    if flush:               return (5, vals)
    if straight:            return (4, sv)
    if gc[0] == 3:          return (3, gv)
    if gc[:2] == [2, 2]:    return (2, gv)
    if gc[0] == 2:          return (1, gv)
    return (0, vals)


def best_hand(cards):
    return max(score5(list(c)) for c in combinations(cards, 5))


# ============================================================
# HAND STRENGTH
# ============================================================

def preflop_strength(hole):
    """Normalised 0-1 estimate of hole card quality."""
    c1, c2 = hole
    v1, v2 = max(c1.value, c2.value), min(c1.value, c2.value)
    suited = c1.suit == c2.suit
    paired = (v1 == v2)
    s = v1 * 0.5
    if paired:
        s = max(s * 2, 5.0)
    if suited:
        s += 2.0
    if not paired:
        gap = v1 - v2
        s += max(0.0, 4.0 - gap * 1.5)
    return min(max(s / 18.0, 0.0), 1.0)


def equity_mc(hole, board, n_opp, trials=120):
    """Monte Carlo equity estimate vs n_opp random hands."""
    known = {(c.rank, c.suit) for c in hole + board}
    pool = [Card(r, s) for r in RANKS for s in SUITS if (r, s) not in known]
    needed = 5 - len(board)
    wins = 0
    for _ in range(trials):
        random.shuffle(pool)
        run_board = board + pool[:needed]
        my = best_hand(hole + run_board)
        idx = needed
        win = True
        for _ in range(n_opp):
            if idx + 2 > len(pool):
                break
            opp = best_hand(pool[idx:idx + 2] + run_board)
            idx += 2
            if opp > my:
                win = False
                break
        if win:
            wins += 1
    return wins / trials


# ============================================================
# STRATEGIES
# ============================================================
# act(hole, board, chips, pot, to_call, bb, n_active, pos) ->
#   (action, amount)
#   action: 'fold' | 'call' | 'raise'
#   amount: chips to commit RIGHT NOW (raise includes call portion)

class Strategy:
    name = "Base"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        raise NotImplementedError


# ------------------------------------------------------------------
# PLAYER 1 — Simple YOLO: always shove
# ------------------------------------------------------------------
class YOLO(Strategy):
    name = "YOLO All-In"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        return ('raise', chips)


# ------------------------------------------------------------------
# PLAYER 2 — Tight-Aggressive (TAG)
#   Only enters with strong hands; bets/raises hard when ahead.
#   Pre-flop: plays top ~20% of hands.
#   Post-flop: bets when equity > 65%, calls with pot odds, else folds.
# ------------------------------------------------------------------
class TAG(Strategy):
    name = "Tight-Aggressive"
    PREMIUM = {
        ('A', 'A'), ('K', 'K'), ('Q', 'Q'), ('J', 'J'), ('T', 'T'),
        ('A', 'K'), ('A', 'Q'), ('A', 'J'), ('K', 'Q'), ('K', 'J'),
    }

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        if not board:
            ranks = tuple(sorted([c.rank for c in hole],
                                  key=lambda r: RV[r], reverse=True))
            suited = hole[0].suit == hole[1].suit
            is_prem = ranks in self.PREMIUM
            is_suited_conn = (suited
                              and RV[ranks[0]] - RV[ranks[1]] <= 2
                              and RV[ranks[0]] >= 8)
            strength = preflop_strength(hole)

            if is_prem:
                amount = min(to_call + bb * 3, chips)
                return ('raise', amount)
            if strength > 0.55 or is_suited_conn:
                if to_call <= bb * 2:
                    return ('call', to_call)
                return ('fold', 0)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        eq = equity_mc(hole, board, max(n_active - 1, 1))
        if eq > 0.65:
            amount = min(to_call + int(pot * 0.75), chips)
            return ('raise', max(amount, to_call + bb))
        if eq > 0.40:
            if to_call <= pot * 0.35:
                return ('call', to_call)
            return ('fold', 0)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


# ------------------------------------------------------------------
# PLAYER 3 — Loose-Aggressive (LAG)
#   Plays wide range; applies relentless pressure via bluffs.
#   Pre-flop: enters top ~50%, raises frequently.
#   Post-flop: bets with equity OR random bluffs; folds only under
#   heavy pressure with air.
# ------------------------------------------------------------------
class LAG(Strategy):
    name = "Loose-Aggressive"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        if not board:
            s = preflop_strength(hole)
            if s > 0.28:
                if s > 0.55 or random.random() < 0.35:
                    amount = min(to_call + bb * 2 + int(pot * 0.5), chips)
                    return ('raise', max(amount, to_call))
                return ('call', to_call)
            if to_call <= bb:
                return ('call', to_call)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        eq = equity_mc(hole, board, max(n_active - 1, 1))
        bluff = random.random() < 0.28
        if eq > 0.42 or bluff:
            bet = min(to_call + int(pot * random.uniform(0.4, 0.95)), chips)
            if bet > to_call:
                return ('raise', bet)
            return ('call', to_call)
        if to_call <= pot * 0.22:
            return ('call', to_call)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


# ------------------------------------------------------------------
# PLAYER 4 — GTO-Inspired (Balanced)
#   Constructs balanced ranges: mixes value bets and bluffs in
#   roughly correct proportions; uses pot-odds correctly.
#   Pre-flop: raises top 15%, calls next 30%, folds the rest.
#   Post-flop: bets pot fraction based on equity; randomises
#   bluff frequency with a 20% blocker-bluff chance.
# ------------------------------------------------------------------
class GTO(Strategy):
    name = "GTO-Inspired"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        if not board:
            s = preflop_strength(hole)
            if s > 0.72:
                amount = min(to_call + bb * 3, chips)
                return ('raise', amount)
            if s > 0.45 and to_call <= bb * 3:
                return ('call', to_call)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        eq = equity_mc(hole, board, max(n_active - 1, 1))
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0

        if to_call == 0:
            if eq > 0.55:
                bet = min(int(pot * 0.6), chips)
                return ('raise', max(bet, bb))
            if eq > 0.30 and random.random() < 0.20:  # balanced bluff
                bet = min(int(pot * 0.45), chips)
                return ('raise', max(bet, bb))
            return ('call', 0)

        if eq > pot_odds + 0.15:
            if eq > 0.65:
                amount = min(to_call + int(pot * 0.75), chips)
                return ('raise', amount)
            return ('call', to_call)
        if eq >= pot_odds:
            return ('call', to_call)
        if random.random() < 0.08:  # occasional polarised bluff-raise
            amount = min(to_call + int(pot * 0.5), chips)
            return ('raise', amount)
        return ('fold', 0)


# ------------------------------------------------------------------
# PLAYER 5 — Position-Aware (Exploitative Positional)
#   Dramatically loosens hand requirements in late position;
#   tightens in early position. Bluff frequency scales with
#   positional advantage (0=early, 1=mid, 2=late/button).
#   Uses "steal" opens on the button and semi-bluff check-raises
#   in position.
# ------------------------------------------------------------------
class POSITION(Strategy):
    name = "Position-Aware"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        # Preflop strength threshold by position: early=tight, late=loose
        threshold = [0.68, 0.52, 0.34][pos]
        bluff_pct = [0.04, 0.14, 0.30][pos]
        bet_size  = [0.50, 0.65, 0.80][pos]

        if not board:
            s = preflop_strength(hole)
            if s > threshold:
                mult = [2, 3, 4][pos]
                amount = min(to_call + bb * mult, chips)
                return ('raise', amount)
            if s > threshold - 0.20 and to_call <= bb * (1 + pos):
                return ('call', to_call)
            if to_call == 0:
                return ('call', 0)
            return ('fold', 0)

        eq = equity_mc(hole, board, max(n_active - 1, 1))

        if eq > 0.52 or (eq > 0.22 and random.random() < bluff_pct):
            bet = min(to_call + int(pot * bet_size), chips)
            if bet > to_call:
                return ('raise', bet)
            return ('call', to_call)

        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0
        if eq >= pot_odds:
            return ('call', to_call)
        if to_call == 0:
            return ('call', 0)
        return ('fold', 0)


# ------------------------------------------------------------------
# PLAYER 6 — Pot-Odds Shark (Pure Math EV)
#   Every decision is driven by expected-value arithmetic.
#   Calls iff EV > 0: equity * (pot) - (1-equity) * to_call > 0.
#   Value-bets strong hands at 80% pot; folds borderline spots
#   unless pot odds are almost break-even, then calls ~12% as
#   bluff-catcher. Never makes speculative plays.
# ------------------------------------------------------------------
class POTODDS(Strategy):
    name = "Pot-Odds Shark"

    def act(self, hole, board, chips, pot, to_call, bb, n_active, pos):
        if not board:
            eq = preflop_strength(hole)
        else:
            eq = equity_mc(hole, board, max(n_active - 1, 1))

        if to_call == 0:
            if eq > 0.55:
                bet = min(int(pot * 0.65), chips)
                return ('raise', max(bet, bb))
            return ('call', 0)

        pot_odds = to_call / (pot + to_call)
        ev = eq * pot - (1.0 - eq) * to_call

        if ev > 0:
            if eq > 0.68:
                amount = min(to_call + int(pot * 0.80), chips)
                return ('raise', max(amount, to_call * 2))
            return ('call', to_call)
        if eq > pot_odds * 0.85 and random.random() < 0.12:
            return ('call', to_call)  # thin call / pot odds rescue
        return ('fold', 0)


# ============================================================
# PLAYER
# ============================================================

class Player:
    __slots__ = ('pid', 'chips', 'strategy', 'hole',
                 'active', 'all_in', 'street_bet')

    def __init__(self, pid, chips, strategy):
        self.pid = pid
        self.chips = chips
        self.strategy = strategy
        self.hole = []
        self.active = True
        self.all_in = False
        self.street_bet = 0

    def __repr__(self):
        return f"P{self.pid}({self.chips})"


# ============================================================
# GAME ENGINE
# ============================================================

class HoldEm:
    def __init__(self, players, sb=50, bb=100):
        self.players = players
        self.sb = sb
        self.bb = bb
        self.btn = 0  # index into living() list

    def living(self):
        return [p for p in self.players if p.chips > 0]

    # ------ Tournament: play until one player holds all chips ------
    def tournament(self):
        for p in self.players:
            p.active = True
        hands = 0
        while len(self.living()) > 1 and hands < 800:
            self.play_hand()
            hands += 1
            for p in self.players:
                if p.chips < 0:
                    p.chips = 0
        alive = self.living()
        return max(alive, key=lambda p: p.chips).pid if alive else self.players[0].pid

    # ------ Single hand ------
    def play_hand(self):
        alive = self.living()
        n = len(alive)
        if n < 2:
            return

        deck = new_deck()
        board = []

        for p in alive:
            p.hole = [deck.pop(), deck.pop()]
            p.active = True
            p.all_in = False
            p.street_bet = 0

        btn = self.btn % n
        if n == 2:
            sb_i, bb_i = btn, (btn + 1) % n
        else:
            sb_i = (btn + 1) % n
            bb_i = (btn + 2) % n

        pot = 0
        sb_p, bb_p = alive[sb_i], alive[bb_i]

        sb_amt = min(self.sb, sb_p.chips)
        sb_p.chips -= sb_amt
        sb_p.street_bet = sb_amt
        pot += sb_amt
        if sb_p.chips == 0:
            sb_p.all_in = True

        bb_amt = min(self.bb, bb_p.chips)
        bb_p.chips -= bb_amt
        bb_p.street_bet = bb_amt
        pot += bb_amt
        if bb_p.chips == 0:
            bb_p.all_in = True

        cur_bet = bb_amt
        utg_i = (bb_i + 1) % n

        # Pre-flop (action starts UTG)
        pot = self._street(alive, pot, cur_bet, utg_i, board)

        # Flop / Turn / River
        for ncards in [3, 1, 1]:
            still = [p for p in alive if p.active]
            if len(still) <= 1:
                break
            for p in alive:
                p.street_bet = 0
            board += [deck.pop() for _ in range(ncards)]
            pot = self._street(alive, pot, 0, sb_i, board)

        # Award pot
        still = [p for p in alive if p.active]
        if len(still) == 1:
            still[0].chips += pot
        elif still:
            scores = [(best_hand(p.hole + board), p) for p in still]
            best_sc = max(s for s, _ in scores)
            winners = [p for s, p in scores if s == best_sc]
            share = pot // len(winners)
            rem = pot - share * len(winners)
            for w in winners:
                w.chips += share
            if rem:
                winners[0].chips += rem

        self.btn = (self.btn + 1) % max(len(self.living()), 1)

    # ------ Betting round ------
    def _street(self, alive, pot, cur_bet, start_i, board):
        n = len(alive)
        # Who must act: set of player ids
        needs = {id(p) for p in alive if p.active and not p.all_in}

        max_iters = n * 12  # enough for 4 raises × full table + buffer
        iters = 0
        i = start_i

        while needs and iters < max_iters:
            iters += 1
            p = alive[i % n]
            i += 1

            if not p.active or p.all_in or id(p) not in needs:
                continue

            needs.discard(id(p))

            to_call = max(0, cur_bet - p.street_bet)
            to_call = min(to_call, p.chips)
            n_active = len([x for x in alive if x.active])
            pos = min(int(alive.index(p) * 3 / max(n, 1)), 2)

            action, amount = p.strategy.act(
                p.hole, board, p.chips, pot,
                to_call, self.bb, n_active, pos
            )

            if action == 'fold':
                p.active = False
                if len([x for x in alive if x.active]) <= 1:
                    needs.clear()
                    break

            elif action == 'call':
                actual = min(to_call, p.chips)
                p.chips -= actual
                p.street_bet += actual
                pot += actual
                if p.chips == 0:
                    p.all_in = True

            elif action == 'raise':
                # amount = total chips to commit right now (includes call)
                actual = max(to_call, min(amount, p.chips))
                p.chips -= actual
                p.street_bet += actual
                pot += actual
                if p.chips == 0:
                    p.all_in = True
                if p.street_bet > cur_bet:
                    cur_bet = p.street_bet
                    for x in alive:
                        if x.active and not x.all_in and x is not p:
                            needs.add(id(x))

        return pot


# ============================================================
# SIMULATION
# ============================================================

STRATEGIES = [YOLO(), TAG(), LAG(), GTO(), POSITION(), POTODDS()]


def run_sims(n=100, start_chips=10_000):
    wins = defaultdict(int)
    for sim in range(1, n + 1):
        players = [Player(i + 1, start_chips, STRATEGIES[i])
                   for i in range(6)]
        game = HoldEm(players, sb=50, bb=100)
        winner = game.tournament()
        wins[winner] += 1
        if sim % 20 == 0:
            print(f"  [{sim:3d}/{n}] sims complete…", flush=True)
    return wins


# ============================================================
# HISTOGRAM
# ============================================================

def print_histogram(wins, n_sims):
    BAR = 44
    mx = max(wins.values()) if wins else 1

    print()
    print("╔" + "═" * 67 + "╗")
    print("║" + "   TEXAS HOLD'EM  ─  100 TOURNAMENT SIMULATION RESULTS".center(67) + "║")
    print("╠" + "═" * 67 + "╣")
    print("║" + "  Each tournament: 6 players, equal starting stacks, last alive wins".ljust(67) + "║")
    print("╚" + "═" * 67 + "╝")
    print()

    rows = []
    for pid in range(1, 7):
        s = STRATEGIES[pid - 1]
        w = wins.get(pid, 0)
        pct = w / n_sims * 100
        filled = round(w / mx * BAR)
        bar = '█' * filled + '░' * (BAR - filled)
        tag = " ★" if pid == 1 else "  "
        rows.append((pid, s.name, w, pct, bar, tag))

    # sort by wins descending for display
    for pid, name, w, pct, bar, tag in sorted(rows, key=lambda r: -r[2]):
        medal = "🥇" if pid == sorted(rows, key=lambda r: -r[2])[0][0] else "  "
        label = f"P{pid}★" if pid == 1 else f"P{pid} "
        print(f"  {label} [{name:19s}] |{bar}| {w:3d}  ({pct:5.1f}%)")
    print()

    # Sorted by pid for reference
    print("  " + "─" * 63)
    print("  FULL LEADERBOARD (by player number):")
    print("  " + "─" * 63)
    for pid, name, w, pct, bar, tag in rows:
        marker = " ← YOLO All-In (no brain, pure guts)" if pid == 1 else ""
        print(f"  P{pid}: {name:20s}  {w:3d} wins  ({pct:5.1f}%){marker}")
    print("  " + "─" * 63)

    # Verdict
    top_pid = max(wins, key=wins.get)
    top_w = wins[top_pid]
    p1_w = wins.get(1, 0)
    print()
    print(f"  CHAMPION  ──▶  P{top_pid} [{STRATEGIES[top_pid-1].name}]")
    print(f"              Took down {top_w}/{n_sims} tournaments ({top_w/n_sims*100:.1f}%)")
    print()
    if top_pid == 1:
        print("  P1 YOLO went full degenerate and STILL WON. Variance is a hell of a drug.")
        print("  suflair GPT watching from the rail, absolutely cooked. 🃏🔥")
    else:
        print(f"  P1 (YOLO All-In) managed only {p1_w} wins. Turns out poker isn't")
        print("  just about shoving every hand. suflair GPT has been HUMILIATED. 🃏")
    print()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print()
    print("┌─────────────────────────────────────────────────────────┐")
    print("│     🃏  TEXAS HOLD'EM POKER TOURNAMENT SIMULATOR  🃏     │")
    print("│         6 strategies · 100 tournaments · 10k chips      │")
    print("└─────────────────────────────────────────────────────────┘")
    print()
    print("  Strategy roster:")
    for i, s in enumerate(STRATEGIES, 1):
        tag = "  ← THE YOLO BOT (if my_turn → bet = all_in)" if i == 1 else ""
        print(f"    P{i}: {s.name}{tag}")
    print()

    random.seed(42)
    wins = run_sims(100, start_chips=10_000)
    print_histogram(wins, 100)
