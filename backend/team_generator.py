from dataclasses import dataclass
from itertools import combinations
from random import choice

from backend.models import Membership


@dataclass
class GeneratedTeam:
    name: str
    players: list[Membership]


def _team_total(players: list[Membership]) -> int:
    return sum(player.rating for player in players)


def generate_balanced_teams(
    players: list[Membership],
) -> list[GeneratedTeam]:
    if len(players) != 12:
        raise ValueError("Exactly 12 players are required")

    indexed = list(range(12))
    candidates = []

    # Fix player 0 in Team A to eliminate equivalent permutations.
    for team_a_extra in combinations(indexed[1:], 3):
        team_a_idx = (0,) + team_a_extra
        remaining_after_a = [
            i for i in indexed if i not in team_a_idx
        ]

        for team_b_idx in combinations(remaining_after_a, 4):
            team_c_idx = tuple(
                i for i in remaining_after_a if i not in team_b_idx
            )

            team_a = [players[i] for i in team_a_idx]
            team_b = [players[i] for i in team_b_idx]
            team_c = [players[i] for i in team_c_idx]

            totals = [
                _team_total(team_a),
                _team_total(team_b),
                _team_total(team_c),
            ]

            spread = max(totals) - min(totals)

            candidates.append(
                (
                    spread,
                    team_a,
                    team_b,
                    team_c,
                )
            )

    best_spread = min(item[0] for item in candidates)

    best = [
        item
        for item in candidates
        if item[0] == best_spread
    ]

    _, team_a, team_b, team_c = choice(best)

    return [
        GeneratedTeam("Team A", team_a),
        GeneratedTeam("Team B", team_b),
        GeneratedTeam("Team C", team_c),
    ]
