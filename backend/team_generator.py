"""Balanced team generation.

Twelve registered players are split into three teams of four so that the gap
between the strongest and the weakest team's total rating is as small as
possible. When several splits tie for the smallest gap one of them is chosen at
random, so repeated generations for the same squad produce variety.

The search enumerates every distinct split. The previous implementation
materialised all 11,550 of them (each holding three lists of ORM objects)
before looking at any of them; this version streams the search, keeps only the
current winner, and skips the half of the search space that merely relabels
teams B and C.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from random import Random
from typing import Sequence

from backend.models import TEAM_NAMES, Membership


TEAM_SIZE = 4
REQUIRED_PLAYERS = TEAM_SIZE * len(TEAM_NAMES)


@dataclass(frozen=True)
class GeneratedTeam:
    name: str
    players: list[Membership]


def _best_split(
    ratings: Sequence[int],
    rng: Random,
) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    total = sum(ratings)

    best_spread: int | None = None
    best: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]] | None = None
    ties = 0

    # Player 0 is pinned to the first team: every split has that player
    # somewhere, so fixing them removes a pure relabelling of the three teams.
    for extra_a in combinations(range(1, REQUIRED_PLAYERS), TEAM_SIZE - 1):
        team_a = (0,) + extra_a
        remaining = [i for i in range(REQUIRED_PLAYERS) if i not in team_a]
        total_a = sum(ratings[i] for i in team_a)

        # Pinning the lowest remaining player to team B likewise removes the
        # duplicate that only swaps teams B and C.
        pinned, rest = remaining[0], remaining[1:]

        for extra_b in combinations(rest, TEAM_SIZE - 1):
            team_b = (pinned,) + extra_b
            total_b = sum(ratings[i] for i in team_b)
            total_c = total - total_a - total_b

            spread = max(total_a, total_b, total_c) - min(total_a, total_b, total_c)

            if best_spread is not None and spread > best_spread:
                continue

            team_c = tuple(i for i in rest if i not in extra_b)

            if best_spread is None or spread < best_spread:
                best_spread = spread
                best = (team_a, team_b, team_c)
                ties = 1
                continue

            # Reservoir sampling: every split sharing the best spread ends up
            # equally likely without holding them all in memory.
            ties += 1

            if rng.randrange(ties) == 0:
                best = (team_a, team_b, team_c)

    assert best is not None
    return best


def generate_balanced_teams(
    players: Sequence[Membership],
    rng: Random | None = None,
) -> list[GeneratedTeam]:
    if len(players) != REQUIRED_PLAYERS:
        raise ValueError(f"Exactly {REQUIRED_PLAYERS} players are required")

    rng = rng or Random()
    ratings = [player.rating for player in players]

    groups = _best_split(ratings, rng)

    # Team A is pinned to the first player and team B to the lowest remaining
    # one, so without this the last two labels would be assigned systematically
    # rather than at random.
    head, tail = groups[0], [groups[1], groups[2]]
    rng.shuffle(tail)

    return [
        GeneratedTeam(name, [players[index] for index in indices])
        for name, indices in zip(TEAM_NAMES, [head, *tail])
    ]
