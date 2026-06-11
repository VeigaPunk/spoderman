#!/usr/bin/env python3
"""
Texas Hold'em Poker Simulation
Player 1 : Simple "always all-in" strategy
Players 2-6: Elaborate algorithmic strategies
100 tournaments, histogram of winners
"""

import random
from collections import Counter
from itertools import combinations

# ─────────────────────────────────────────────────────────────────────────────
# CARD PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VAL = {r: i for i, r in enumerate(RANKS, 2)}
FULL_DECK = [(r, s) for r in RANKS for s in SUITS]


def make_deck():
    return list(FULL_DECK)


# ─────────────────────────────────────────────────────────────────────────────
# HAND EVALUATOR  (returns comparable tuple for 5-card hand)
# ─────────────────────────────────────────────────────────────────────────────

def hand_rank_5(cards):
    vals  = sorted([RANK_VAL[c[0]] for c in cards], reverse=True)
    suits = [c[1] for c in cards]
    flush = len(set(suits)) == 1
    uniq  = sorted(set(vals), reverse=True)
    straight = (len(uniq) == 5 and uniq[0] - uniq[4] == 4)
    if set(vals) == {14, 2, 3, 4, 5}:
        straight = True
        vals = [5, 4, 3, 2, 1]
    cnt    = Counter(vals)
    counts = sorted(cnt.values(), reverse=True)
    groups = sorted(cnt.keys(), key=lambda v: (cnt[v], v), reverse=True)
    if straight and flush: return (8, vals)
    if counts[0] == 4:     return (7, groups)
    if counts[:2] == [3,2]:return (6, groups)
    if flush:              return (5, vals)
    if straight:           return (4, vals)
    if counts[0] == 3:     return (3, groups)
    if counts[:2] == [2,2]:return (2, groups)
    if counts[0] == 2:     return (1, groups)
    return (0, vals)


def best_hand(cards):
    return max(hand_rank_5(list(c)) for c in combinations(cards, 5))


# ─────────────────────────────────────────────────────────────────────────────
# FAST HAND STRENGTH (no Monte Carlo — use made-hand tier + draw bonus)
# ─────────────────────────────────────────────────────────────────────────────

def fast_strength(hole, community):
    """
    Returns 0-1 estimate of absolute hand strength.
    On preflop: uses Chen score normalised.
    On flop/turn/river: evaluates made hand + draws.
    """
    if len(community) == 0:
        return _preflop_strength(hole)

    all_cards = hole + community
    rank = best_hand(all_cards)[0]   # 0-8 hand category
    base = rank / 8.0

    # Bonus for nut-flush or straight draws on flop/turn
    if len(community) < 5:
        suits_c = [c[1] for c in all_cards]
        flush_draw = max(Counter(suits_c).values()) >= 4
        vals_c = sorted(set(RANK_VAL[c[0]] for c in all_cards), reverse=True)
        consecutive = sum(1 for i in range(len(vals_c)-1) if vals_c[i]-vals_c[i+1]==1)
        oesd = consecutive >= 3
        if flush_draw: base += 0.08
        if oesd:       base += 0.06

    return min(base, 0.99)


def _preflop_strength(hole):
    r1, r2 = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
    suited  = hole[0][1] == hole[1][1]
    paired  = r1 == r2
    score   = r1 / 14.0
    if paired: score = min(0.95, score * 1.5)
    if suited: score += 0.06
    gap = r1 - r2
    score -= gap * 0.03
    return max(0.05, min(0.95, score))


# ─────────────────────────────────────────────────────────────────────────────
# CHEN PREFLOP SCORE  (used by strategies that want a discrete rating)
# ─────────────────────────────────────────────────────────────────────────────

def chen_score(hole):
    r1, r2  = sorted([RANK_VAL[c[0]] for c in hole], reverse=True)
    suited  = hole[0][1] == hole[1][1]
    score   = r1 / 2.0
    if r1 == r2:
        score = max(5, score * 2)
    if suited:
        score += 2
    gap = r1 - r2
    score += [1, 0, -1, -2, -4, -5][min(gap, 5)]
    if r1 < 12 and r2 < 12 and gap < 2:
        score += 1
    return score


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY IMPLEMENTATIONS
# Each takes (hole, chips, game_state) and returns (action, amount).
# action: "fold" | "check" | "call" | "raise"
# amount: for "raise" = total extra chips to put in; for "call" = cost to call
# ─────────────────────────────────────────────────────────────────────────────

def strategy_simple_allin(hole, chips, gs):
    """THE DEGEN — if my_turn; bet = ALL IN; fi"""
    return ("raise", chips)


def strategy_tight_aggressive(hole, chips, gs):
    """
    TAG: Only plays top-20% hands preflop.
    Bets 75% pot for value, folds to heavy resistance without equity.
    Continuation-bets the flop with any top-pair+.
    """
    community = gs["community"]
    pot       = gs["pot"]
    to_call   = gs["to_call"]
    stage     = gs["stage"]

    if stage == "preflop":
        score = chen_score(hole)
        if score >= 10:
            raise_amt = max(to_call * 3, pot // 2 + 10)
            return ("raise", min(chips, raise_amt))
        if score >= 7 and to_call <= pot * 0.15:
            return ("call", min(to_call, chips))
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    strength = fast_strength(hole, community)
    if strength > 0.60:
        bet = max(int(pot * 0.75), to_call)
        return ("raise", min(chips, bet))
    if strength > 0.40 and to_call <= int(pot * 0.35):
        return ("call", min(to_call, chips))
    if to_call == 0:
        return ("check", 0)
    return ("fold", 0)


def strategy_loose_passive(hole, chips, gs):
    """
    CALLING STATION: Sees every flop it can afford.
    Calls down with any made hand. Never bluffs. Never folds cheap.
    Collapses to big bets with nothing.
    """
    community = gs["community"]
    pot       = gs["pot"]
    to_call   = gs["to_call"]
    stage     = gs["stage"]

    if stage == "preflop":
        score = chen_score(hole)
        cheap = to_call <= max(50, int(pot * 0.5))
        if score >= 5 and cheap:
            return ("call", min(to_call, chips))
        if to_call == 0:
            return ("check", 0)
        if to_call <= 20:
            return ("call", min(to_call, chips))
        return ("fold", 0)

    strength = fast_strength(hole, community)
    if strength > 0.25:
        if to_call == 0:
            return ("check", 0)
        if to_call <= int(pot * 0.55):
            return ("call", min(to_call, chips))
        return ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    if to_call <= 30:
        return ("call", min(to_call, chips))
    return ("fold", 0)


def strategy_gto_lite(hole, chips, gs):
    """
    GTO-LITE: Pot-odds + hand strength + 22% bluff frequency.
    In position: opens wider, bets polarised.
    Balances ranges to avoid being exploited on any single street.
    Mixed strategy: occasionally raises with air when fold equity is high.
    """
    community = gs["community"]
    pot       = gs["pot"]
    to_call   = gs["to_call"]
    stage     = gs["stage"]
    position  = gs.get("position", 3)
    n_active  = gs.get("num_active", 3)
    in_pos    = position >= n_active - 2

    if stage == "preflop":
        score = chen_score(hole)
        thresh = 8 if in_pos else 10
        if score >= thresh:
            return ("raise", min(chips, max(to_call * 3, int(pot * 0.8))))
        if score >= (5 if in_pos else 7) and random.random() < 0.22:
            return ("raise", min(chips, max(int(to_call * 2.5), int(pot * 0.6))))
        if score >= 5 and to_call <= int(pot * 0.22):
            return ("call", min(to_call, chips))
        if to_call == 0:
            return ("check", 0)
        return ("fold", 0)

    strength  = fast_strength(hole, community)
    pot_odds  = to_call / (pot + to_call + 1)

    if strength > 0.70:
        return ("raise", min(chips, max(int(pot * 0.85), to_call)))
    if strength > pot_odds + 0.10:
        if to_call == 0:
            bet = int(pot * 0.55)
            return ("raise", min(chips, bet)) if bet > 0 else ("check", 0)
        return ("call", min(to_call, chips))
    # Bluff with low-equity hands when no bet is facing us
    if strength < 0.22 and to_call == 0 and random.random() < 0.22:
        return ("raise", min(chips, int(pot * 0.65)))
    if to_call == 0:
        return ("check", 0)
    return ("call", min(to_call, chips)) if strength > pot_odds else ("fold", 0)


def strategy_shark(hole, chips, gs):
    """
    SHARK (Adaptive Exploitative): Reads table aggression meter.
    vs. passive tables  → steals more, thin value-bets.
    vs. aggressive tables → traps with monsters, check-raises.
    Uses stack-to-pot ratio (SPR) to commit or escape.
    """
    community  = gs["community"]
    pot        = gs["pot"]
    to_call    = gs["to_call"]
    stage      = gs["stage"]
    aggression = gs.get("table_aggression", 0.5)
    n_active   = gs.get("num_active", 3)

    spr = chips / max(pot, 1)

    if stage == "preflop":
        score = chen_score(hole)
        if aggression < 0.4:
            open_t, call_t, rmult = 7,  5, 2.5
        elif aggression > 0.7:
            open_t, call_t, rmult = 11, 8, 4.0
        else:
            open_t, call_t, rmult = 9,  6, 3.0
        if score >= open_t:
            raise_amt = max(int(to_call * rmult + 10), to_call + 10)
            return ("raise", min(chips, raise_amt))
        if score >= call_t and to_call <= int(pot * 0.25):
            return ("call", min(to_call, chips))
        return ("check", 0) if to_call == 0 else ("fold", 0)

    strength = fast_strength(hole, community)
    pot_odds = to_call / (pot + to_call + 1)

    # Low SPR: commit with reasonable equity
    if spr < 2 and strength > 0.38:
        return ("raise", chips)

    if aggression < 0.4:
        # Passive table: bet thin for value
        if strength > 0.52:
            return ("raise", min(chips, max(int(pot * 0.65), to_call)))
        if strength > 0.35 and to_call == 0:
            return ("check", 0)
        return ("call", min(to_call, chips)) if strength > pot_odds else ("fold", 0)

    # Aggressive table: trap or fold marginal
    if strength > 0.75:
        if to_call > 0 and random.random() < 0.40:   # slow-play 40%
            return ("call", min(to_call, chips))
        return ("raise", min(chips, int(pot * 0.90)))
    if strength > 0.52:
        return ("call", min(to_call, chips)) if to_call <= int(pot * 0.40) else ("fold", 0)
    if to_call == 0:
        return ("check", 0)
    return ("call", min(to_call, chips)) if strength > pot_odds else ("fold", 0)


def strategy_icm_wizard(hole, chips, gs):
    """
    ICM WIZARD: Stack-size pressure + positional awareness + push-fold math.
    Short-stacked (M < 5): shove any playable hand.
    Deep-stacked: tighten up OOP, steal from late position.
    Heads-up: plays nearly any two cards.
    """
    community = gs["community"]
    pot       = gs["pot"]
    to_call   = gs["to_call"]
    stage     = gs["stage"]
    position  = gs.get("position", 3)
    n_active  = gs.get("num_active", 3)
    avg_stack = gs.get("avg_stack", chips)

    m_ratio  = chips / max(avg_stack * 0.2, 1)
    is_short = m_ratio < 5
    is_late  = position >= n_active - 1
    is_hu    = n_active <= 2

    if stage == "preflop":
        score = chen_score(hole)
        if is_short:
            thresh = 5 if (is_late or is_hu) else 8
            return ("raise", chips) if score >= thresh else ("fold", 0)
        if is_late or is_hu:
            if score >= 6:
                raise_amt = min(chips, max(to_call * 3, int(pot * 0.7) + 10))
                return ("raise", raise_amt)
            if to_call <= 30:
                return ("call", min(to_call, chips))
            return ("check", 0) if to_call == 0 else ("fold", 0)
        # Early / middle position: tight
        if score >= 10:
            return ("raise", min(chips, max(to_call * 3, int(pot * 0.8))))
        if score >= 7 and to_call <= int(pot * 0.20):
            return ("call", min(to_call, chips))
        return ("check", 0) if to_call == 0 else ("fold", 0)

    strength = fast_strength(hole, community)
    pot_odds = to_call / (pot + to_call + 1)

    if is_short and strength > 0.33:
        return ("raise", chips)
    if is_hu:
        if strength > 0.48:
            return ("raise", min(chips, int(pot * 0.75)))
        if strength > 0.33:
            return ("call", min(to_call, chips)) if to_call > 0 else ("check", 0)
        return ("fold", 0) if to_call > 0 else ("check", 0)
    if strength > 0.62:
        return ("raise", min(chips, int(pot * 0.80)))
    if strength > pot_odds + 0.05:
        if to_call == 0:
            bet = int(pot * 0.50)
            return ("raise", min(chips, bet)) if bet > 0 else ("check", 0)
        return ("call", min(to_call, chips))
    return ("check", 0) if to_call == 0 else ("fold", 0)


STRATEGIES = [
    ("The Degen (All-In)",     strategy_simple_allin),
    ("Tight Aggressive (TAG)", strategy_tight_aggressive),
    ("Calling Station",        strategy_loose_passive),
    ("GTO-Lite",               strategy_gto_lite),
    ("Shark (Exploitative)",   strategy_shark),
    ("ICM Wizard",             strategy_icm_wizard),
]


# ─────────────────────────────────────────────────────────────────────────────
# PLAYER
# ─────────────────────────────────────────────────────────────────────────────

class Player:
    __slots__ = ("pid", "name", "strategy", "chips",
                 "hole", "folded", "all_in", "bet_this_round")

    def __init__(self, pid, name, strategy_fn, chips):
        self.pid    = pid
        self.name   = name
        self.strategy = strategy_fn
        self.chips  = chips
        self.hole   = []
        self.folded = False
        self.all_in = False
        self.bet_this_round = 0

    def reset(self):
        self.hole = []; self.folded = False
        self.all_in = False; self.bet_this_round = 0

    def act(self, gs):
        return self.strategy(self.hole, self.chips, gs)


# ─────────────────────────────────────────────────────────────────────────────
# GAME ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class HoldemGame:
    def __init__(self, players, sb=10, bb=20):
        self.players = players
        self.sb = sb
        self.bb = bb
        self.btn = 0
        self.aggression = 0.5

    # ------------------------------------------------------------------
    def _post_blinds(self):
        alive = [p for p in self.players if p.chips > 0]
        n = len(alive)
        if n < 2:
            return 0, 0
        s = alive[self.btn % n]
        b = alive[(self.btn + 1) % n]
        sa = min(self.sb, s.chips); ba = min(self.bb, b.chips)
        s.chips -= sa; s.bet_this_round = sa
        b.chips -= ba; b.bet_this_round = ba
        if s.chips == 0: s.all_in = True
        if b.chips == 0: b.all_in = True
        return sa + ba, ba

    # ------------------------------------------------------------------
    def _bet_round(self, pot, community, stage, cur_bet, start_off):
        alive = [p for p in self.players if p.chips > 0 and not p.folded]
        if len(alive) <= 1:
            return pot

        order = (alive + alive)[start_off: start_off + len(alive)]
        acted = set()
        last_agg = None
        avg_stack = sum(p.chips for p in self.players if p.chips > 0) / max(1, sum(1 for p in self.players if p.chips > 0))

        safety = 0
        while safety < 300:
            safety += 1
            any_move = False
            for player in order:
                if player.folded or player.all_in or player.chips <= 0:
                    continue
                owe = max(0, cur_bet - player.bet_this_round)
                if player in acted and player is not last_agg and owe == 0:
                    continue

                gs = {
                    "community":       community,
                    "pot":             pot,
                    "to_call":         min(owe, player.chips),
                    "stage":           stage,
                    "position":        order.index(player),
                    "num_active":      sum(1 for p in self.players if not p.folded and p.chips > 0),
                    "avg_stack":       avg_stack,
                    "table_aggression": self.aggression,
                }

                action, amount = player.act(gs)
                acted.add(player)
                any_move = True

                if action == "fold":
                    player.folded = True

                elif action == "call":
                    pay = min(owe, player.chips)
                    player.chips -= pay; player.bet_this_round += pay; pot += pay
                    if player.chips == 0: player.all_in = True

                elif action == "raise":
                    pay = min(amount + owe, player.chips)
                    pay = max(pay, min(owe, player.chips))
                    new_total = player.bet_this_round + pay
                    if new_total > cur_bet:
                        cur_bet = new_total
                        last_agg = player
                        acted = {player}
                        self.aggression = min(1.0, self.aggression + 0.04)
                    player.chips -= pay; player.bet_this_round += pay; pot += pay
                    if player.chips == 0: player.all_in = True
                # "check" → nothing

            can_act = [p for p in order if not p.folded and not p.all_in and p.chips > 0]
            if not can_act:
                break
            if all(p.bet_this_round >= cur_bet for p in can_act):
                break
            if not any_move:
                break

        return pot

    # ------------------------------------------------------------------
    def _award(self, pot, contenders, community):
        if not contenders:
            return
        if len(contenders) == 1:
            contenders[0].chips += pot; return
        scored = []
        for p in contenders:
            if p.hole and len(community) >= 3:
                sc = best_hand(p.hole + community)
            else:
                sc = (0, [0])
            scored.append((sc, p))
        top = max(s for s, _ in scored)
        wins = [p for s, p in scored if s == top]
        share = pot // len(wins)
        for w in wins: w.chips += share
        wins[0].chips += pot % len(wins)

    # ------------------------------------------------------------------
    def play_hand(self):
        deck = make_deck(); random.shuffle(deck)
        alive = [p for p in self.players if p.chips > 0]
        for p in alive:
            p.reset(); p.hole = [deck.pop(), deck.pop()]

        pot, bb_bet = self._post_blinds()
        if pot == 0:
            return

        n = len(alive)
        community = []

        def fighting():
            return [p for p in self.players if not p.folded and p.hole]

        # Pre-flop: UTG acts first (two seats left of btn)
        start = (self.btn + 2) % n
        pot = self._bet_round(pot, community, "preflop", bb_bet, start)
        if len(fighting()) <= 1:
            self._award(pot, fighting() or alive, community)
            self.btn += 1; return

        for street, count in [("flop", 3), ("turn", 1), ("river", 1)]:
            community += [deck.pop() for _ in range(count)]
            for p in self.players:
                if not p.folded: p.bet_this_round = 0
            pot = self._bet_round(pot, community, street, 0, 0)
            if len(fighting()) <= 1:
                self._award(pot, fighting() or alive, community)
                self.btn += 1; return

        self._award(pot, fighting() or alive, community)
        self.btn += 1

    # ------------------------------------------------------------------
    def run_tournament(self, start_chips=1000):
        for p in self.players:
            p.chips = start_chips
        self.aggression = 0.5
        self.btn = 0

        hand = 0
        while sum(1 for p in self.players if p.chips > 0) > 1 and hand < 8000:
            for p in self.players:            # prevent infinite blind-posting loops
                if 0 < p.chips < self.bb:
                    p.chips = self.bb
            self.play_hand()
            hand += 1

        survivors = [p for p in self.players if p.chips > 0]
        return max(survivors, key=lambda p: p.chips) if survivors else self.players[0]


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATION
# ─────────────────────────────────────────────────────────────────────────────

def run_simulations(n=100, start_chips=1000):
    wins = Counter()
    print(f"\nRunning {n} Texas Hold'em tournaments — {start_chips} chips each\n")
    print("Lineup:")
    for i, (name, _) in enumerate(STRATEGIES):
        tag = "  ← always all-in lmao" if i == 0 else ""
        print(f"  Player {i+1}: {name}{tag}")
    print()

    for sim in range(n):
        players = [Player(i+1, nm, fn, start_chips) for i, (nm, fn) in enumerate(STRATEGIES)]
        game = HoldemGame(players, sb=10, bb=20)
        winner = game.run_tournament(start_chips)
        wins[winner.name] += 1

        done = int((sim + 1) / n * 40)
        print(f"\r  [{'█'*done}{'░'*(40-done)}] {sim+1}/{n}", end="", flush=True)

    print("\n")
    return wins


# ─────────────────────────────────────────────────────────────────────────────
# HISTOGRAM
# ─────────────────────────────────────────────────────────────────────────────

def print_histogram(wins, n):
    max_w = max(wins.values(), default=1)
    print("=" * 70)
    print("     WINNER WINNER CHICKEN DINNER  ─  100-TOURNAMENT HISTOGRAM")
    print("=" * 70)
    print()
    for i, (name, _) in enumerate(STRATEGIES):
        w   = wins.get(name, 0)
        pct = w / n * 100
        bar = "█" * int(w / max_w * 36)
        tag = "  ◄ THE DEGEN" if i == 0 else ""
        print(f"  P{i+1} {name:<28} │{bar:<36}│ {w:>3} wins ({pct:5.1f}%){tag}")
    print()
    print("─" * 70)
    print(f"  Tournaments played   : {n}")
    print(f"  Tournaments decided  : {sum(wins.values())}")
    print()

    champ   = max(wins, key=wins.get)
    washout = min(wins, key=wins.get)
    dw      = wins.get("The Degen (All-In)", 0)
    dp      = dw / n * 100

    print(f"  Champion  : {champ} ({wins[champ]} wins)")
    print(f"  Washout   : {washout} ({wins[washout]} wins)")
    print()

    if dp < 10:
        v = f"suflair GPT DEMOLISHED — The Degen won only {dp:.1f}%. Actual skill issue."
    elif dp < 20:
        v = f"suflair GPT got cooked — {dp:.1f}% for the all-in bot. Luck can't fix stupid."
    elif dp < 30:
        v = f"Degen at {dp:.1f}% — variance keeps it alive, but algos own the felt."
    else:
        v = f"Degen at {dp:.1f}%?? Chaos reigns. Poker is a coin flip apparently."

    print(f"  VERDICT   : {v}")
    print("=" * 70)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    random.seed(42)
    wins = run_simulations(100, start_chips=1000)
    print_histogram(wins, 100)
