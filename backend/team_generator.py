from dataclasses import dataclass
from itertools import combinations
from math import comb
from random import randrange, shuffle

from backend.models import Membership


@dataclass
class GeneratedTeam:
    name: str
    players: list[Membership]


def team_label(index: int) -> str:
    return f"Team {chr(65 + index)}"


def _rating(player: Membership) -> float:
    return float(player.rating)


def _team_total(players: list[Membership]) -> float:
    return sum(_rating(player) for player in players)


def _spread(teams: list[list[Membership]]) -> float:
    totals = [_team_total(team) for team in teams]
    return max(totals) - min(totals)


def _snake_draft(players: list[Membership], team_count: int) -> list[list[Membership]]:
    ordered = sorted(players, key=_rating, reverse=True)
    teams: list[list[Membership]] = [[] for _ in range(team_count)]
    going_forward = True
    index = 0

    for player in ordered:
        teams[index].append(player)
        if going_forward:
            if index == team_count - 1:
                going_forward = False
            else:
                index += 1
        else:
            if index == 0:
                going_forward = True
            else:
                index -= 1

    return teams


def _improve(teams: list[list[Membership]], rounds: int = 400) -> list[list[Membership]]:
    best = [list(team) for team in teams]
    best_spread = _spread(best)

    for _ in range(rounds):
        i = randrange(len(best))
        j = randrange(len(best))
        if i == j or not best[i] or not best[j]:
            continue
        a = randrange(len(best[i]))
        b = randrange(len(best[j]))
        best[i][a], best[j][b] = best[j][b], best[i][a]
        current = _spread(best)
        if current <= best_spread:
            best_spread = current
        else:
            best[i][a], best[j][b] = best[j][b], best[i][a]

    return best


def _choose_unassigned(
    players: list[Membership],
    remainder: int,
) -> list[Membership]:
    if remainder <= 0:
        return []

    ordered = sorted(players, key=_rating, reverse=True)
    # Spread sit-outs across the rating list so one band is not excluded.
    step = len(ordered) / remainder
    chosen = []
    used = set()
    for i in range(remainder):
        index = min(len(ordered) - 1, int(i * step + step / 2))
        while index in used:
            index = (index + 1) % len(ordered)
        used.add(index)
        chosen.append(ordered[index])
    return chosen


def generate_balanced_teams(
    players: list[Membership],
    players_per_team: int,
) -> tuple[list[GeneratedTeam], list[Membership]]:
    if players_per_team < 2:
        raise ValueError("At least 2 players per team are required")

    team_count = len(players) // players_per_team
    remainder = len(players) % players_per_team

    if team_count == 0:
        return [], list(players)

    unassigned = _choose_unassigned(players, remainder)
    unassigned_ids = {player.id for player in unassigned}
    assigned = [player for player in players if player.id not in unassigned_ids]

    if team_count == 1:
        generated = [GeneratedTeam(team_label(0), assigned)]
        return generated, unassigned

    pool_size = len(assigned)
    exact_ok = (
        team_count <= 3
        and players_per_team <= 5
        and comb(pool_size - 1, players_per_team - 1) <= 8000
    )

    if exact_ok and team_count == 2:
        indexed = list(range(pool_size))
        best = None
        for extras in combinations(indexed[1:], players_per_team - 1):
            team_a_idx = (0,) + extras
            team_b_idx = tuple(i for i in indexed if i not in team_a_idx)
            team_a = [assigned[i] for i in team_a_idx]
            team_b = [assigned[i] for i in team_b_idx]
            spread = _spread([team_a, team_b])
            if best is None or spread < best[0]:
                best = (spread, [team_a, team_b])
        teams = best[1] if best else _snake_draft(assigned, team_count)
    else:
        teams = _improve(_snake_draft(assigned, team_count))

    shuffle(teams)
    generated = [
        GeneratedTeam(team_label(index), team)
        for index, team in enumerate(teams)
    ]
    return generated, unassigned
