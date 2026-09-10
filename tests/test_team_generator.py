"""Team balancing rules."""

from __future__ import annotations

import itertools
from random import Random

import pytest

from backend.models import TEAM_NAMES, Membership
from backend.team_generator import (
    REQUIRED_PLAYERS,
    TEAM_SIZE,
    generate_balanced_teams,
)


def squad(ratings: list[int]) -> list[Membership]:
    return [
        Membership(display_name=f"P{index}", rating=rating)
        for index, rating in enumerate(ratings)
    ]


def optimal_spread(ratings: list[int]) -> int:
    """Smallest achievable gap, found by brute force over every split."""

    best = None

    for team_a in itertools.combinations(range(REQUIRED_PLAYERS), TEAM_SIZE):
        rest = [i for i in range(REQUIRED_PLAYERS) if i not in team_a]

        for team_b in itertools.combinations(rest, TEAM_SIZE):
            team_c = [i for i in rest if i not in team_b]

            totals = [
                sum(ratings[i] for i in team_a),
                sum(ratings[i] for i in team_b),
                sum(ratings[i] for i in team_c),
            ]

            spread = max(totals) - min(totals)
            best = spread if best is None else min(best, spread)

    assert best is not None
    return best


RATING_CASES = [
    [5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1, 1],
    [3] * 12,
    [5, 5, 5, 5, 1, 1, 1, 1, 3, 3, 3, 3],
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 5],
    [5, 4, 4, 4, 4, 3, 3, 3, 3, 2, 2, 1],
    [1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 1, 2],
]


@pytest.mark.parametrize("ratings", RATING_CASES)
def test_generates_three_teams_of_four_covering_every_player(ratings):
    teams = generate_balanced_teams(squad(ratings), rng=Random(7))

    assert [team.name for team in teams] == list(TEAM_NAMES)
    assert all(len(team.players) == TEAM_SIZE for team in teams)

    assigned = [player for team in teams for player in team.players]
    assert len(assigned) == REQUIRED_PLAYERS
    assert len({id(player) for player in assigned}) == REQUIRED_PLAYERS


@pytest.mark.parametrize("ratings", RATING_CASES)
def test_split_is_as_balanced_as_theoretically_possible(ratings):
    teams = generate_balanced_teams(squad(ratings), rng=Random(11))

    totals = [sum(player.rating for player in team.players) for team in teams]

    assert max(totals) - min(totals) == optimal_spread(ratings)


def test_equal_ratings_produce_perfectly_level_teams():
    teams = generate_balanced_teams(squad([3] * 12), rng=Random(1))

    totals = {sum(player.rating for player in team.players) for team in teams}

    assert totals == {12}


def test_average_rating_matches_the_players_on_the_team():
    teams = generate_balanced_teams(
        squad([5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1, 1]), rng=Random(3)
    )

    for team in teams:
        total = sum(player.rating for player in team.players)
        assert total / len(team.players) == pytest.approx(total / TEAM_SIZE)


def test_repeated_generation_varies_when_several_splits_tie():
    players = squad([3] * 12)

    signatures = {
        tuple(
            tuple(sorted(player.display_name for player in team.players))
            for team in generate_balanced_teams(players, rng=Random(seed))
        )
        for seed in range(25)
    }

    assert len(signatures) > 1


def test_generation_is_reproducible_for_a_given_seed():
    players = squad([5, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 5])

    first = generate_balanced_teams(players, rng=Random(99))
    second = generate_balanced_teams(players, rng=Random(99))

    assert [
        [player.display_name for player in team.players] for team in first
    ] == [[player.display_name for player in team.players] for team in second]


@pytest.mark.parametrize("size", [0, 1, 11, 13, 16])
def test_rejects_a_squad_that_is_not_twelve_players(size):
    with pytest.raises(ValueError):
        generate_balanced_teams(squad([3] * size))
