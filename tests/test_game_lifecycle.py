"""Scheduling a game, generating teams, and what happens at kickoff."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from conftest import add_virtual, create_game, create_open_game, future, join_group
from backend.models import Game, Registration, TeamAssignment
from backend.services import MAX_GAME_PLAYERS


def register_full_squad(group_owner, group_id, ratings=None):
    ratings = ratings or [5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 1, 1]

    players = [
        add_virtual(group_owner, group_id, f"Player {index:02d}", rating=rating)
        for index, rating in enumerate(ratings)
    ]

    for player in players:
        group_owner.post(f"/groups/{group_id}/game/register/{player['id']}")

    return players


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_a_game_in_the_past_is_rejected(group, group_owner):
    response = group_owner.post(
        f"/groups/{group['id']}/game",
        json={
            "game_datetime": (
                datetime.now(timezone.utc) - timedelta(hours=1)
            ).isoformat(),
            "priority_hours": 24,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Game must be in the future"


def test_scheduling_a_new_game_replaces_the_previous_one(group, group_owner, db):
    create_open_game(group_owner, group["id"], hours_ahead=24)
    create_open_game(group_owner, group["id"], hours_ahead=48)

    games = db.execute(
        select(func.count()).select_from(Game).where(Game.group_id == group["id"])
    ).scalar_one()

    assert games == 1


def test_a_timezone_aware_kickoff_is_stored_as_sent(group, group_owner):
    kickoff = future(30).replace(microsecond=0)

    response = group_owner.post(
        f"/groups/{group['id']}/game",
        json={"game_datetime": kickoff.isoformat(), "priority_hours": 6},
    )

    stored = datetime.fromisoformat(response.json()["game_datetime"])

    assert stored == kickoff


def test_priority_window_opens_the_configured_number_of_hours_before_kickoff(
    group, group_owner
):
    kickoff = future(48).replace(microsecond=0)

    response = group_owner.post(
        f"/groups/{group['id']}/game",
        json={"game_datetime": kickoff.isoformat(), "priority_hours": 12},
    )

    body = response.json()

    assert datetime.fromisoformat(body["regular_registration_opens"]) == (
        kickoff - timedelta(hours=12)
    )


@pytest.mark.parametrize("priority_hours", [-1, 169])
def test_an_out_of_range_priority_window_is_rejected(
    group, group_owner, priority_hours
):
    response = group_owner.post(
        f"/groups/{group['id']}/game",
        json={
            "game_datetime": future(48).isoformat(),
            "priority_hours": priority_hours,
        },
    )

    assert response.status_code == 422


def test_deleting_a_game_clears_its_registrations(group, group_owner, db):
    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])

    assert group_owner.delete(f"/groups/{group['id']}/game").status_code == 200

    assert group_owner.get(f"/groups/{group['id']}").json()["game"] is None
    assert (
        db.execute(select(func.count()).select_from(Registration)).scalar_one() == 0
    )


def test_deleting_a_game_when_there_is_none_is_harmless(group, group_owner):
    assert group_owner.delete(f"/groups/{group['id']}/game").status_code == 200


# ---------------------------------------------------------------------------
# Kickoff
# ---------------------------------------------------------------------------


def test_a_game_stops_being_active_at_kickoff_without_destroying_it(
    group, group_owner, db
):
    """Reading a group must not delete data.

    The previous implementation deleted the game row - and with it every
    registration and generated team - from inside `GET /groups/{id}`, the
    moment kickoff passed. The frontend polls that endpoint, so the fixture
    erased itself as the match began.
    """

    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    game_id = db.execute(select(Game.id)).scalar_one()

    # Move the whole fixture into the past, keeping the priority window valid.
    db.execute(
        text(
            "update games set game_datetime = now() - interval '1 minute', "
            "regular_registration_opens = now() - interval '2 minutes'"
        )
    )
    db.commit()

    assert group_owner.get(f"/groups/{group['id']}").json()["game"] is None

    # The record and everything hanging off it survives.
    assert db.execute(select(func.count()).select_from(Game)).scalar_one() == 1
    assert (
        db.execute(
            select(func.count())
            .select_from(Registration)
            .where(Registration.game_id == game_id)
        ).scalar_one()
        == MAX_GAME_PLAYERS
    )
    assert (
        db.execute(
            select(func.count())
            .select_from(TeamAssignment)
            .where(TeamAssignment.game_id == game_id)
        ).scalar_one()
        == MAX_GAME_PLAYERS
    )


def test_a_past_game_does_not_block_scheduling_the_next_one(group, group_owner, db):
    create_open_game(group_owner, group["id"])

    db.execute(
        text(
            "update games set game_datetime = now() - interval '1 hour', "
            "regular_registration_opens = now() - interval '2 hours'"
        )
    )
    db.commit()

    create_open_game(group_owner, group["id"], hours_ahead=24)

    assert group_owner.get(f"/groups/{group['id']}").json()["game"] is not None


# ---------------------------------------------------------------------------
# Team generation
# ---------------------------------------------------------------------------


def test_teams_require_a_full_squad(group, group_owner):
    create_open_game(group_owner, group["id"])

    for index in range(MAX_GAME_PLAYERS - 1):
        player = add_virtual(group_owner, group["id"], f"Player {index:02d}")
        group_owner.post(f"/groups/{group['id']}/game/register/{player['id']}")

    response = group_owner.post(f"/groups/{group['id']}/generate-teams")

    assert response.status_code == 400
    assert "12" in response.json()["detail"]


def test_generated_teams_cover_every_participant_once(group, group_owner):
    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])

    teams = group_owner.post(f"/groups/{group['id']}/generate-teams").json()

    assert [team["name"] for team in teams] == ["Team A", "Team B", "Team C"]
    assert all(len(team["players"]) == 4 for team in teams)

    assigned = [
        player["id"] for team in teams for player in team["players"]
    ]
    assert len(set(assigned)) == MAX_GAME_PLAYERS


def test_generated_teams_report_their_totals(group, group_owner):
    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])

    teams = group_owner.post(f"/groups/{group['id']}/generate-teams").json()

    for team in teams:
        expected = sum(player["rating"] for player in team["players"])
        assert team["total_rating"] == expected
        assert team["average_rating"] == pytest.approx(expected / 4)

    totals = [team["total_rating"] for team in teams]
    assert max(totals) - min(totals) <= 1


def test_regenerating_replaces_the_previous_assignment(group, group_owner, db):
    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])

    group_owner.post(f"/groups/{group['id']}/generate-teams")
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    assert (
        db.execute(select(func.count()).select_from(TeamAssignment)).scalar_one()
        == MAX_GAME_PLAYERS
    )


def test_a_participant_leaving_clears_the_generated_teams(group, group_owner):
    create_open_game(group_owner, group["id"])
    players = register_full_squad(group_owner, group["id"])

    group_owner.post(f"/groups/{group['id']}/generate-teams")
    assert group_owner.get(f"/groups/{group['id']}").json()["teams"] != []

    group_owner.post(
        f"/groups/{group['id']}/game/unregister/{players[0]['id']}"
    )

    assert group_owner.get(f"/groups/{group['id']}").json()["teams"] == []


def test_joining_the_waiting_list_leaves_the_generated_teams_alone(
    group, group_owner
):
    """A queued player does not change who is on the pitch.

    The previous implementation cleared the line-up on any registration, so a
    thirteenth person signing up silently destroyed the admin's teams.
    """

    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    latecomer = add_virtual(group_owner, group["id"], "Latecomer")
    group_owner.post(f"/groups/{group['id']}/game/register/{latecomer['id']}")

    body = group_owner.get(f"/groups/{group['id']}").json()

    assert len(body["game"]["waiting_list"]) == 1
    assert len(body["teams"]) == 3


def test_manual_team_adjustment_requires_a_complete_valid_split(
    group, group_owner
):
    create_open_game(group_owner, group["id"])
    players = register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    group_id = group["id"]
    ids = [player["id"] for player in players]

    lopsided = [
        {"membership_id": ids[index], "team_name": "Team A" if index < 5 else
         ("Team B" if index < 9 else "Team C")}
        for index in range(12)
    ]
    assert group_owner.put(
        f"/groups/{group_id}/teams", json={"assignments": lopsided}
    ).status_code == 400

    incomplete = [
        {"membership_id": ids[index], "team_name": "Team A"} for index in range(4)
    ]
    assert group_owner.put(
        f"/groups/{group_id}/teams", json={"assignments": incomplete}
    ).status_code == 400

    unknown_team = [
        {"membership_id": ids[index], "team_name": "Team D"} for index in range(12)
    ]
    assert group_owner.put(
        f"/groups/{group_id}/teams", json={"assignments": unknown_team}
    ).status_code == 422


def test_a_valid_manual_adjustment_is_saved(group, group_owner):
    create_open_game(group_owner, group["id"])
    players = register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    ids = [player["id"] for player in players]
    assignments = [
        {
            "membership_id": ids[index],
            "team_name": ["Team A", "Team B", "Team C"][index // 4],
        }
        for index in range(12)
    ]

    response = group_owner.put(
        f"/groups/{group['id']}/teams", json={"assignments": assignments}
    )

    assert response.status_code == 200

    teams = {team["name"]: {p["id"] for p in team["players"]} for team in
             response.json()}

    assert teams["Team A"] == set(ids[0:4])
    assert teams["Team B"] == set(ids[4:8])
    assert teams["Team C"] == set(ids[8:12])


def test_changing_a_participants_rating_clears_the_teams(group, group_owner):
    create_open_game(group_owner, group["id"])
    players = register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    group_owner.put(
        f"/groups/{group['id']}/members/{players[0]['id']}",
        json={"name": players[0]["name"], "rating": 1, "is_subscriber": False,
              "is_admin": False},
    )

    assert group_owner.get(f"/groups/{group['id']}").json()["teams"] == []


def test_renaming_a_reserve_does_not_clear_the_teams(group, group_owner):
    create_open_game(group_owner, group["id"])
    register_full_squad(group_owner, group["id"])
    group_owner.post(f"/groups/{group['id']}/generate-teams")

    reserve = add_virtual(group_owner, group["id"], "Reserve")

    group_owner.put(
        f"/groups/{group['id']}/members/{reserve['id']}",
        json={"name": "Renamed", "rating": 3, "is_subscriber": False,
              "is_admin": False},
    )

    assert len(group_owner.get(f"/groups/{group['id']}").json()["teams"]) == 3


# ---------------------------------------------------------------------------
# Join flow
# ---------------------------------------------------------------------------


def test_join_request_approval_makes_a_plain_member(group, group_owner, make_user):
    applicant = make_user("Applicant")

    assert applicant.get(f"/groups/{group['id']}/membership-status").json()[
        "state"
    ] == "none"

    applicant.post(f"/groups/{group['id']}/join-request")

    assert applicant.get(f"/groups/{group['id']}/membership-status").json()[
        "state"
    ] == "pending"

    join_group(group_owner, applicant, group["id"])

    status = applicant.get(f"/groups/{group['id']}/membership-status").json()
    assert status["state"] == "member"
    assert status["is_admin"] is False


def test_a_declined_applicant_can_apply_again(group, group_owner, make_user):
    applicant = make_user("Applicant")
    applicant.post(f"/groups/{group['id']}/join-request")

    request_id = group_owner.get(f"/groups/{group['id']}/join-requests").json()[0][
        "id"
    ]
    group_owner.post(f"/groups/{group['id']}/join-requests/{request_id}/decline")

    assert applicant.get(f"/groups/{group['id']}/membership-status").json()[
        "state"
    ] == "declined"

    assert applicant.post(f"/groups/{group['id']}/join-request").status_code == 200
    assert applicant.get(f"/groups/{group['id']}/membership-status").json()[
        "state"
    ] == "pending"


def test_an_existing_member_cannot_request_to_join(group, group_owner):
    response = group_owner.post(f"/groups/{group['id']}/join-request")

    assert response.status_code == 400


def test_a_second_request_while_one_is_pending_is_a_no_op(group, make_user, db):
    from backend.models import JoinRequest

    applicant = make_user("Applicant")

    applicant.post(f"/groups/{group['id']}/join-request")
    response = applicant.post(f"/groups/{group['id']}/join-request")

    assert response.status_code == 200
    assert response.json()["message"] == "Request already pending"
    assert (
        db.execute(select(func.count()).select_from(JoinRequest)).scalar_one() == 1
    )


def test_a_request_cannot_be_approved_through_another_group(
    group, group_owner, make_user
):
    other_owner = make_user("Other Owner")
    other = other_owner.post("/groups", json={"name": "Other"}).json()

    applicant = make_user("Applicant")
    applicant.post(f"/groups/{group['id']}/join-request")
    request_id = group_owner.get(f"/groups/{group['id']}/join-requests").json()[0][
        "id"
    ]

    response = other_owner.post(
        f"/groups/{other['id']}/join-requests/{request_id}/approve"
    )

    assert response.status_code == 404


def test_display_names_come_from_the_signup_profile(group, group_owner, make_user):
    applicant = make_user("Yossi Cohen")
    applicant.post(f"/groups/{group['id']}/join-request")

    pending = group_owner.get(f"/groups/{group['id']}/join-requests").json()

    assert pending[0]["user_name"] == "Yossi Cohen"

    join_group(group_owner, applicant, group["id"])

    members = group_owner.get(f"/groups/{group['id']}").json()["members"]
    assert "Yossi Cohen" in {member["name"] for member in members}
