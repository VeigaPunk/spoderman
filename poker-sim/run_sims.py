"""Run 100 Hold'em tournaments and print the winner histogram."""
import sys
import time

from engine import play_tournament
from strategies import roster

N_SIMS = 100


def main():
    entries = roster()
    names = [n for n, _ in entries]
    factories = [f for _, f in entries]
    wins = [0] * len(names)
    hand_counts = []
    t0 = time.time()
    for sim in range(1, N_SIMS + 1):
        winner, hands = play_tournament(factories, names, seed=sim)
        wins[winner] += 1
        hand_counts.append(hands)
        if sim % 10 == 0:
            print(f'  ...{sim}/{N_SIMS} tournaments done '
                  f'({time.time() - t0:.1f}s)', file=sys.stderr)

    print()
    print('=' * 62)
    print(' WINNER WINNER CHICKEN DINNER — 100 TOURNAMENT HISTOGRAM')
    print(' 6 players, 1000 chips each, blinds 10/20 doubling every 25 hands')
    print('=' * 62)
    print()
    longest = max(len(n) for n in names)
    for i, name in enumerate(names):
        bar = '#' * wins[i]
        print(f' {name:<{longest}} | {bar} {wins[i]}')
    print()
    print(f' Avg tournament length: {sum(hand_counts) / len(hand_counts):.0f} hands')
    print(f' Total wall time: {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
