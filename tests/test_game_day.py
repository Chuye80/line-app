"""The game day lifecycle: starting, playing, scoring and finishing.

The scenario used throughout is one round robin between the three generated
teams, with results chosen so that every column of the standings table has to be
computed correctly for the table to come out in the expected order:

    Team A 2 - 1 Team B     A win
    Team A 0 - 0 Team C     draw
    Team B 3 - 0 Team C     B win

which gives A 4 points, B 3 points and C 1 point.
"""

from __future__ import annotations

import pytest

from conftest import (
    add_virtual,
    build_squad,
    create_open_game,
    join_group,
    play_match,
    score_goal,
    start_game_day,
    team_players,
)


def scheduled_day(admin, group_id):
    create_open_game(admin, group_id)
    build_squad(admin, group_id)


def live_day(admin, group_id) -> dict:
    scheduled_day(admin, group_id)
    return start_game_day(admin, group_id)


def played_out(admin, group_id) -> dict:
    """A live day with the whole round robin played to the scoreline above."""

    day = live_day(admin, group_id)
    matches = day["matches"]

    play_match(
        admin, group_id, day, matches[0]["id"], [("Team A", 2), ("Team B", 1)]
    )
    play_match(admin, group_id, day, matches[1]["id"], [])
    play_match(
        admin, group_id, day, matches[2]["id"], [("Team B", 3)]
    )

    return day


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------


def test_a_game_day_cannot_start_without_teams(group, group_owner):
    create_open_game(group_owner, group["id"])

    response = group_owner.post(f"/groups/{group['id']}/game/start")

    assert response.status_code == 400
    assert "Generate the teams" in response.json()["detail"]


def test_starting_lays_out_a_round_robin(group, group_owner):
    day = live_day(group_owner, group["id"])

    assert day["status"] == "live"
    assert day["started_at"] is not None

    fixtures = [(item["home_team"], item["away_team"]) for item in day["matches"]]

    assert fixtures == [
        ("Team A", "Team B"),
        ("Team A", "Team C"),
        ("Team B", "Team C"),
    ]
    assert all(item["status"] == "scheduled" for item in day["matches"])
    assert day["current_match_id"] is None
    assert day["next_match_id"] == day["matches"][0]["id"]


def test_a_plain_member_cannot_start_the_game_day(group, group_owner, make_user):
    scheduled_day(group_owner, group["id"])

    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    assert member.post(f"/groups/{group['id']}/game/start").status_code == 403


def test_starting_twice_is_refused(group, group_owner):
    live_day(group_owner, group["id"])

    response = group_owner.post(f"/groups/{group['id']}/game/start")

    assert response.status_code == 409
    assert response.json()["detail"] == "The Game Day has already started"


# ---------------------------------------------------------------------------
# Registration closes when the day starts
# ---------------------------------------------------------------------------


def test_registration_is_closed_once_the_day_is_live(group, group_owner):
    live_day(group_owner, group["id"])

    latecomer = add_virtual(group_owner, group["id"], "Latecomer")

    response = group_owner.post(
        f"/groups/{group['id']}/game/register/{latecomer['id']}"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "The Game Day has already started"


def test_the_squad_cannot_be_changed_once_the_day_is_live(group, group_owner):
    day = live_day(group_owner, group["id"])
    playing = team_players(day, "Team A")[0]

    unregister = group_owner.post(
        f"/groups/{group['id']}/game/unregister/{playing['id']}"
    )
    regenerate = group_owner.post(f"/groups/{group['id']}/generate-teams")

    assert unregister.status_code == 409
    assert regenerate.status_code == 409


def test_registration_data_is_kept_when_the_day_starts(group, group_owner):
    """The rows are the record of who turned up, so they must survive."""

    scheduled_day(group_owner, group["id"])

    before = group_owner.get(f"/groups/{group['id']}").json()
    assert len(before["game"]["participants"]) == 12

    start_game_day(group_owner, group["id"])

    after = group_owner.get(f"/groups/{group['id']}").json()

    assert after["game"]["status"] == "live"
    assert len(after["game"]["participants"]) == 12


def test_a_member_leaving_a_live_day_keeps_the_squad_intact(
    group, group_owner, make_user
):
    scheduled_day(group_owner, group["id"])
    start_game_day(group_owner, group["id"])

    # A real member who is not in the squad can still leave the group.
    member = make_user("Bystander")
    join_group(group_owner, member, group["id"])

    assert member.delete(f"/groups/{group['id']}/leave").status_code == 200

    day = group_owner.get(f"/groups/{group['id']}/game-day").json()

    assert sum(len(team["players"]) for team in day["teams"]) == 12


# ---------------------------------------------------------------------------
# Playing a match
# ---------------------------------------------------------------------------


def test_only_one_match_can_be_in_progress(group, group_owner):
    day = live_day(group_owner, group["id"])
    first, second = day["matches"][0], day["matches"][1]

    assert (
        group_owner.post(
            f"/groups/{group['id']}/matches/{first['id']}/start"
        ).status_code
        == 200
    )

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{second['id']}/start"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Finish the match in progress first"


def test_starting_the_same_match_twice_is_harmless(group, group_owner):
    day = live_day(group_owner, group["id"])
    match_id = day["matches"][0]["id"]

    group_owner.post(f"/groups/{group['id']}/matches/{match_id}/start")
    again = group_owner.post(f"/groups/{group['id']}/matches/{match_id}/start")

    assert again.status_code == 200
    assert again.json()["current_match_id"] == match_id


def test_a_match_cannot_be_completed_before_it_kicks_off(group, group_owner):
    day = live_day(group_owner, group["id"])
    match_id = day["matches"][0]["id"]

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match_id}/complete"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "That match has not kicked off yet"


def test_a_completed_match_cannot_be_replayed(group, group_owner):
    day = live_day(group_owner, group["id"])
    match_id = day["matches"][0]["id"]

    play_match(group_owner, group["id"], day, match_id, [])

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match_id}/start"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "That match has already been played"


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


def test_a_goal_updates_the_score_and_lists_the_scorer(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker, provider = team_players(day, "Team A")[:2]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    updated = score_goal(
        group_owner,
        group["id"],
        match["id"],
        "Team A",
        striker["id"],
        provider["id"],
    )

    live = next(item for item in updated["matches"] if item["id"] == match["id"])

    assert (live["home_score"], live["away_score"]) == (1, 0)
    assert len(live["goals"]) == 1
    assert live["goals"][0]["scorer_name"] == striker["name"]
    assert live["goals"][0]["assist_name"] == provider["name"]


def test_a_goal_may_have_no_assist(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    updated = score_goal(
        group_owner, group["id"], match["id"], "Team A", striker["id"], None
    )

    live = next(item for item in updated["matches"] if item["id"] == match["id"])

    assert live["goals"][0]["assist_membership_id"] is None
    assert live["goals"][0]["assist_name"] is None


def test_a_player_cannot_assist_his_own_goal(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team A",
            "scorer_membership_id": striker["id"],
            "assist_membership_id": striker["id"],
        },
    )

    assert response.status_code == 422


def test_the_scorer_must_play_for_the_scoring_team(group, group_owner):
    """The bug this guards: crediting somebody who is not on that team."""

    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    opponent = team_players(day, "Team B")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team A",
            "scorer_membership_id": opponent["id"],
            "assist_membership_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The scorer is not playing for that team"


def test_the_assisting_player_must_be_a_team_mate(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]
    opponent = team_players(day, "Team B")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team A",
            "scorer_membership_id": striker["id"],
            "assist_membership_id": opponent["id"],
        },
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "The assisting player is not playing for that team"
    )


def test_a_team_not_in_the_match_cannot_score_in_it(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    outsider = team_players(day, "Team C")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team C",
            "scorer_membership_id": outsider["id"],
            "assist_membership_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "That team is not playing in this match"


def test_goals_cannot_be_added_to_a_completed_match(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    play_match(group_owner, group["id"], day, match["id"], [])

    response = group_owner.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team A",
            "scorer_membership_id": striker["id"],
            "assist_membership_id": None,
        },
    )

    assert response.status_code == 409


def test_a_mistyped_goal_can_be_removed_while_the_match_runs(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")
    updated = score_goal(
        group_owner, group["id"], match["id"], "Team A", striker["id"]
    )

    goal_id = next(
        item for item in updated["matches"] if item["id"] == match["id"]
    )["goals"][0]["id"]

    response = group_owner.delete(
        f"/groups/{group['id']}/matches/{match['id']}/goals/{goal_id}"
    )

    assert response.status_code == 200

    live = next(
        item for item in response.json()["matches"] if item["id"] == match["id"]
    )

    assert (live["home_score"], live["away_score"]) == (0, 0)
    assert live["goals"] == []


def test_removing_a_member_keeps_the_match_result(group, group_owner, db):
    """History must not be rewritten when somebody leaves the group.

    The goal is credited to a team as well as to a player, so deleting the
    player clears the credit without changing the score.
    """

    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")
    score_goal(group_owner, group["id"], match["id"], "Team A", striker["id"])
    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/complete")

    assert (
        group_owner.delete(
            f"/groups/{group['id']}/members/{striker['id']}"
        ).status_code
        == 200
    )

    live = next(
        item
        for item in group_owner.get(f"/groups/{group['id']}/game-day").json()[
            "matches"
        ]
        if item["id"] == match["id"]
    )

    assert (live["home_score"], live["away_score"]) == (1, 0)
    assert live["goals"][0]["scorer_membership_id"] is None
    assert live["goals"][0]["scorer_name"] == "Former member"


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------


def test_standings_reflect_every_completed_match(group, group_owner):
    played_out(group_owner, group["id"])

    table = group_owner.get(f"/groups/{group['id']}/game-day").json()["standings"]

    assert [row["team"] for row in table] == ["Team A", "Team B", "Team C"]
    assert [row["position"] for row in table] == [1, 2, 3]

    first, second, third = table

    assert (first["played"], first["wins"], first["draws"], first["losses"]) == (
        2,
        1,
        1,
        0,
    )
    assert (first["goals_for"], first["goals_against"]) == (2, 1)
    assert (first["goal_difference"], first["points"]) == (1, 4)

    assert (second["wins"], second["draws"], second["losses"]) == (1, 0, 1)
    assert (second["goals_for"], second["goals_against"]) == (4, 2)
    assert (second["goal_difference"], second["points"]) == (2, 3)

    assert (third["wins"], third["draws"], third["losses"]) == (0, 1, 1)
    assert (third["goal_difference"], third["points"]) == (-3, 1)


def test_a_match_in_progress_does_not_count_towards_the_table(group, group_owner):
    """A live score is not a result: the team might still concede."""

    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")
    updated = score_goal(
        group_owner, group["id"], match["id"], "Team A", striker["id"]
    )

    row = next(item for item in updated["standings"] if item["team"] == "Team A")

    assert (row["played"], row["wins"], row["points"]) == (0, 0, 0)

    live = next(item for item in updated["matches"] if item["id"] == match["id"])
    assert live["home_score"] == 1


def test_teams_level_on_every_measure_share_a_position(group, group_owner):
    """Three 0-0 draws leave nobody ahead, so all three share first place."""

    day = live_day(group_owner, group["id"])

    for match in day["matches"]:
        play_match(group_owner, group["id"], day, match["id"], [])

    table = group_owner.get(f"/groups/{group['id']}/game-day").json()["standings"]

    assert [row["position"] for row in table] == [1, 1, 1]
    assert {row["points"] for row in table} == {2}


# ---------------------------------------------------------------------------
# Finishing
# ---------------------------------------------------------------------------


def test_a_game_day_cannot_finish_with_matches_outstanding(group, group_owner):
    day = live_day(group_owner, group["id"])
    play_match(group_owner, group["id"], day, day["matches"][0]["id"], [])

    response = group_owner.post(f"/groups/{group['id']}/game/finish")

    assert response.status_code == 400
    assert response.json()["detail"] == "2 of 3 matches still need to be played"


def test_finishing_crowns_the_champion(group, group_owner):
    played_out(group_owner, group["id"])

    response = group_owner.post(f"/groups/{group['id']}/game/finish")

    assert response.status_code == 200

    finished = response.json()

    assert finished["status"] == "finished"
    assert finished["finished_at"] is not None
    assert finished["champions"] == ["Team A"]


def test_a_tie_at_the_top_produces_co_champions(group, group_owner):
    day = live_day(group_owner, group["id"])

    for match in day["matches"]:
        play_match(group_owner, group["id"], day, match["id"], [])

    finished = group_owner.post(f"/groups/{group['id']}/game/finish").json()

    assert finished["champions"] == ["Team A", "Team B", "Team C"]


def test_a_game_day_cannot_be_finished_twice(group, group_owner):
    played_out(group_owner, group["id"])

    assert group_owner.post(f"/groups/{group['id']}/game/finish").status_code == 200

    again = group_owner.post(f"/groups/{group['id']}/game/finish")

    assert again.status_code == 400
    assert again.json()["detail"] == "No active game"


def test_a_finished_game_day_stays_finished(group, group_owner):
    """The regression behind "refreshing reopens the day".

    The state is stored, not derived from the clock, so re-reading it returns
    the same finished day rather than an active one.
    """

    played_out(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/game/finish")

    for _ in range(3):
        day = group_owner.get(f"/groups/{group['id']}/game-day").json()

        assert day["status"] == "finished"
        assert day["champions"] == ["Team A"]

    # And it is no longer the group's open game day, so the registration
    # screens do not come back either.
    assert group_owner.get(f"/groups/{group['id']}").json()["game"] is None


def test_a_new_game_day_can_be_scheduled_after_one_finishes(group, group_owner):
    played_out(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/game/finish")

    create_open_game(group_owner, group["id"])

    fresh = group_owner.get(f"/groups/{group['id']}/game-day").json()

    assert fresh["status"] == "scheduled"
    assert fresh["matches"] == []


def test_scheduling_is_refused_while_a_day_is_being_played(group, group_owner):
    live_day(group_owner, group["id"])

    from conftest import future

    response = group_owner.post(
        f"/groups/{group['id']}/game",
        json={
            "game_datetime": future(72).isoformat(),
            "priority_hours": 24,
        },
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Finish the current Game Day before scheduling another"
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def test_game_day_statistics_cover_the_whole_squad(group, group_owner):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker, provider = team_players(day, "Team A")[:2]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")
    score_goal(
        group_owner,
        group["id"],
        match["id"],
        "Team A",
        striker["id"],
        provider["id"],
    )
    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/complete")

    stats = group_owner.get(f"/groups/{group['id']}/game-day").json()["statistics"]

    assert len(stats) == 12

    # Sorted with the scorer first.
    assert stats[0]["name"] == striker["name"]
    assert stats[0]["goals"] == 1
    assert stats[0]["assists"] == 0
    assert stats[0]["matches"] == 1
    assert stats[0]["wins"] == 1

    assisted = next(item for item in stats if item["name"] == provider["name"])
    assert (assisted["goals"], assisted["assists"]) == (0, 1)

    # A player on the team that was not involved has played nothing yet.
    bench = next(
        item
        for item in stats
        if item["name"] == team_players(day, "Team C")[0]["name"]
    )
    assert (bench["matches"], bench["goals"]) == (0, 0)


def test_overall_statistics_ignore_a_day_still_in_progress(group, group_owner):
    """Today's numbers must not leak into the accumulated totals."""

    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")
    score_goal(group_owner, group["id"], match["id"], "Team A", striker["id"])

    overall = group_owner.get(f"/groups/{group['id']}/statistics").json()

    assert overall["game_days"] == 0

    # Every member is listed, but the day in progress has contributed nothing.
    assert len(overall["players"]) == 13
    assert all(row["goals"] == 0 for row in overall["players"])
    assert all(row["matches"] == 0 for row in overall["players"])
    assert all(row["game_days"] == 0 for row in overall["players"])


def test_overall_statistics_accumulate_finished_days(group, group_owner):
    played_out(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/game/finish")

    overall = group_owner.get(f"/groups/{group['id']}/statistics").json()

    assert overall["game_days"] == 1

    total_goals = sum(row["goals"] for row in overall["players"])
    assert total_goals == 6

    played = [row for row in overall["players"] if row["game_days"] == 1]

    assert len(played) == 12
    assert all(row["matches"] == 2 for row in played)

    # The admin never took a playing slot, so they have a row of zeroes.
    owner = next(row for row in overall["players"] if row["name"] == "Owner")
    assert (owner["game_days"], owner["matches"], owner["goals"]) == (0, 0, 0)


def test_history_records_each_finished_day_with_its_champion(group, group_owner):
    played_out(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/game/finish")

    history = group_owner.get(f"/groups/{group['id']}/history").json()

    assert len(history) == 1
    assert history[0]["champions"] == ["Team A"]
    assert history[0]["matches_played"] == 3
    assert history[0]["goals"] == 6
    assert [row["team"] for row in history[0]["standings"]] == [
        "Team A",
        "Team B",
        "Team C",
    ]


def test_history_is_empty_until_a_day_finishes(group, group_owner):
    live_day(group_owner, group["id"])

    assert group_owner.get(f"/groups/{group['id']}/history").json() == []


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/game-day", "/statistics", "/history"],
)
def test_a_non_member_cannot_read_game_day_data(group, group_owner, make_user, path):
    played_out(group_owner, group["id"])

    outsider = make_user("Outsider")

    assert outsider.get(f"/groups/{group['id']}{path}").status_code == 403


def test_a_plain_member_cannot_record_a_goal(group, group_owner, make_user):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]
    striker = team_players(day, "Team A")[0]

    group_owner.post(f"/groups/{group['id']}/matches/{match['id']}/start")

    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    response = member.post(
        f"/groups/{group['id']}/matches/{match['id']}/goals",
        json={
            "team_name": "Team A",
            "scorer_membership_id": striker["id"],
            "assist_membership_id": None,
        },
    )

    assert response.status_code == 403


def test_an_admin_cannot_touch_another_groups_match(group, group_owner, make_user):
    day = live_day(group_owner, group["id"])
    match = day["matches"][0]

    other_owner = make_user("Other Owner")
    other = other_owner.post("/groups", json={"name": "Elsewhere"}).json()

    assert (
        other_owner.post(
            f"/groups/{other['id']}/matches/{match['id']}/start"
        ).status_code
        == 400
    )
