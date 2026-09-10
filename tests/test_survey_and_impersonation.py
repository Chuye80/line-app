"""The rating survey, and the developer "view as another member" switch.

These two features are tested together because they overlap: the survey is the
most identity-dependent screen in the application, so it is also the clearest
way to prove that impersonation really changes who the request runs as.
"""

from __future__ import annotations

import uuid

from conftest import add_virtual, create_open_game, join_group, start_game_day


ACT_AS = "X-Dev-Act-As"


def rate(actor, group_id: str, ratings: dict[str, float | None]):
    return actor.put(
        f"/groups/{group_id}/survey",
        json={
            "ratings": [
                {"membership_id": membership_id, "rating": value}
                for membership_id, value in ratings.items()
            ]
        },
    )


def players_by_name(survey: dict) -> dict[str, dict]:
    return {item["name"]: item for item in survey["players"]}


# ---------------------------------------------------------------------------
# Who the survey lists
# ---------------------------------------------------------------------------


def test_survey_lists_every_other_member(group, group_owner):
    """Everybody in the group appears except the person filling it in."""

    add_virtual(group_owner, group["id"], "Ann")
    add_virtual(group_owner, group["id"], "Bob")

    survey = group_owner.get(f"/groups/{group['id']}/survey").json()
    names = players_by_name(survey)

    assert set(names) == {"Ann", "Bob"}
    assert group_owner.name not in names


def test_survey_never_contains_the_caller(group, group_owner, make_user):
    """Each member sees the other, and never themselves."""

    member = make_user("Nadia")
    join_group(group_owner, member, group["id"])

    assert list(players_by_name(group_owner.get(f"/groups/{group['id']}/survey").json())) == [
        "Nadia"
    ]
    assert list(players_by_name(member.get(f"/groups/{group['id']}/survey").json())) == [
        "Owner"
    ]


def test_survey_includes_virtual_players_and_flags_them(group, group_owner):
    """A virtual player is still somebody you played with, so still ratable."""

    add_virtual(group_owner, group["id"], "Ann")

    survey = group_owner.get(f"/groups/{group['id']}/survey").json()

    assert survey["players"][0]["is_virtual"] is True


def test_survey_needs_membership(group, group_owner, make_user):
    outsider = make_user("Outsider")

    assert outsider.get(f"/groups/{group['id']}/survey").status_code == 403
    assert rate(outsider, group["id"], {}).status_code == 403


# ---------------------------------------------------------------------------
# Saving answers
# ---------------------------------------------------------------------------


def test_ratings_are_saved_and_shown_again(group, group_owner):
    """Reopening the survey shows what the caller answered last time."""

    ann = add_virtual(group_owner, group["id"], "Ann")
    bob = add_virtual(group_owner, group["id"], "Bob")

    assert players_by_name(
        group_owner.get(f"/groups/{group['id']}/survey").json()
    )["Ann"]["my_rating"] is None

    saved = rate(group_owner, group["id"], {ann["id"]: 4.5, bob["id"]: 2.0})
    assert saved.status_code == 200, saved.text

    reopened = players_by_name(group_owner.get(f"/groups/{group['id']}/survey").json())

    assert reopened["Ann"]["my_rating"] == 4.5
    assert reopened["Bob"]["my_rating"] == 2.0


def test_saving_twice_overwrites_rather_than_duplicates(group, group_owner):
    ann = add_virtual(group_owner, group["id"], "Ann")

    rate(group_owner, group["id"], {ann["id"]: 2.5})
    survey = rate(group_owner, group["id"], {ann["id"]: 5.0}).json()

    assert players_by_name(survey)["Ann"]["my_rating"] == 5.0


def test_a_null_rating_clears_a_previous_answer(group, group_owner):
    ann = add_virtual(group_owner, group["id"], "Ann")

    rate(group_owner, group["id"], {ann["id"]: 3.0})
    survey = rate(group_owner, group["id"], {ann["id"]: None}).json()

    assert players_by_name(survey)["Ann"]["my_rating"] is None


def test_a_partial_submission_leaves_other_answers_alone(group, group_owner):
    """The survey can be filled in a few players at a time."""

    ann = add_virtual(group_owner, group["id"], "Ann")
    bob = add_virtual(group_owner, group["id"], "Bob")

    rate(group_owner, group["id"], {ann["id"]: 4.0, bob["id"]: 4.0})
    survey = rate(group_owner, group["id"], {bob["id"]: 1.0}).json()

    assert players_by_name(survey)["Ann"]["my_rating"] == 4.0
    assert players_by_name(survey)["Bob"]["my_rating"] == 1.0


# ---------------------------------------------------------------------------
# The 1.0 - 5.0 scale in half steps
# ---------------------------------------------------------------------------


def test_every_half_step_of_the_scale_is_accepted(group, group_owner):
    ann = add_virtual(group_owner, group["id"], "Ann")

    for value in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        response = rate(group_owner, group["id"], {ann["id"]: value})

        assert response.status_code == 200, response.text
        assert players_by_name(response.json())["Ann"]["my_rating"] == value


def test_values_off_the_half_step_scale_are_refused(group, group_owner):
    ann = add_virtual(group_owner, group["id"], "Ann")

    for value in (0.5, 0.0, 1.25, 3.1, 4.75, 5.5, 10.0, -3.0):
        assert rate(group_owner, group["id"], {ann["id"]: value}).status_code == 422


# ---------------------------------------------------------------------------
# Privacy: an average is published, an individual answer is not
# ---------------------------------------------------------------------------


def test_nobody_can_read_another_members_answers(group, group_owner, make_user):
    """`my_rating` means *mine*: one member's answers stay their own."""

    member = make_user("Nadia")
    join_group(group_owner, member, group["id"])
    ann = add_virtual(group_owner, group["id"], "Ann")

    rate(group_owner, group["id"], {ann["id"]: 5.0})

    assert players_by_name(member.get(f"/groups/{group['id']}/survey").json())["Ann"][
        "my_rating"
    ] is None


def test_statistics_publish_the_average_without_the_raters(group, group_owner, make_user):
    """The aggregate is the only thing the survey ever exposes."""

    member = make_user("Nadia")
    join_group(group_owner, member, group["id"])
    ann = add_virtual(group_owner, group["id"], "Ann")

    rate(group_owner, group["id"], {ann["id"]: 4.0})
    rate(member, group["id"], {ann["id"]: 3.0})

    statistics = group_owner.get(f"/groups/{group['id']}/statistics").json()
    row = next(item for item in statistics["players"] if item["name"] == "Ann")

    assert row["survey_rating"] == 3.5
    assert row["survey_responses"] == 2
    assert "raters" not in row
    assert "rater_membership_id" not in row


def test_a_player_nobody_rated_has_no_average(group, group_owner):
    add_virtual(group_owner, group["id"], "Ann")

    statistics = group_owner.get(f"/groups/{group['id']}/statistics").json()
    row = next(item for item in statistics["players"] if item["name"] == "Ann")

    assert row["survey_rating"] is None
    assert row["survey_responses"] == 0


# ---------------------------------------------------------------------------
# Answers that cannot exist
# ---------------------------------------------------------------------------


def test_rating_yourself_is_ignored(group, group_owner):
    """The frontend never offers it; the backend still refuses to store it."""

    own_id = group["members"][0]["id"]
    add_virtual(group_owner, group["id"], "Ann")

    assert rate(group_owner, group["id"], {own_id: 5.0}).status_code == 200

    statistics = group_owner.get(f"/groups/{group['id']}/statistics").json()
    row = next(item for item in statistics["players"] if item["name"] == "Owner")

    assert row["survey_rating"] is None


def test_rating_somebody_from_another_group_is_ignored(group, group_owner, make_user):
    other_owner = make_user("Other owner")
    other_group = other_owner.post("/groups", json={"name": "Other"}).json()
    stranger = add_virtual(other_owner, other_group["id"], "Stranger")

    assert rate(group_owner, group["id"], {stranger["id"]: 5.0}).status_code == 200

    survey = other_owner.get(f"/groups/{other_group['id']}/statistics").json()
    row = next(item for item in survey["players"] if item["name"] == "Stranger")

    assert row["survey_rating"] is None


def test_removing_a_member_removes_their_answers(group, group_owner):
    """Ratings are opinions about a member, not history of a match."""

    ann = add_virtual(group_owner, group["id"], "Ann")
    bob = add_virtual(group_owner, group["id"], "Bob")

    rate(group_owner, group["id"], {ann["id"]: 5.0, bob["id"]: 5.0})

    assert (
        group_owner.delete(f"/groups/{group['id']}/members/{ann['id']}").status_code
        == 200
    )

    statistics = group_owner.get(f"/groups/{group['id']}/statistics").json()

    assert [item["name"] for item in statistics["players"]] == ["Bob", "Owner"]


# ---------------------------------------------------------------------------
# Developer impersonation
# ---------------------------------------------------------------------------


def test_a_request_without_the_header_runs_as_the_caller(group_owner):
    assert group_owner.get("/me").json()["display_name"] == "Owner"


def test_an_admin_can_view_the_app_as_another_member(group, group_owner, make_user):
    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])

    identity = group_owner.get("/me", headers={ACT_AS: membership_id})

    assert identity.status_code == 200, identity.text
    assert identity.json()["display_name"] == "Nadia"
    assert identity.json()["id"] == str(member.id)


def test_the_simulated_member_sees_their_own_survey(group, group_owner, make_user):
    """Proof that the identity really changed, not just the name on /me."""

    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])
    add_virtual(group_owner, group["id"], "Ann")

    simulated = group_owner.get(
        f"/groups/{group['id']}/survey", headers={ACT_AS: membership_id}
    ).json()

    assert set(players_by_name(simulated)) == {"Owner", "Ann"}
    assert simulated["rater_membership_id"] == membership_id


def test_answers_saved_while_simulating_belong_to_the_simulated_member(
    group, group_owner, make_user
):
    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])
    ann = add_virtual(group_owner, group["id"], "Ann")

    assert (
        group_owner.put(
            f"/groups/{group['id']}/survey",
            json={"ratings": [{"membership_id": ann["id"], "rating": 2.0}]},
            headers={ACT_AS: membership_id},
        ).status_code
        == 200
    )

    # The answer is the simulated member's, so the real caller still has none.
    assert players_by_name(group_owner.get(f"/groups/{group['id']}/survey").json())[
        "Ann"
    ]["my_rating"] is None
    assert players_by_name(member.get(f"/groups/{group['id']}/survey").json())["Ann"][
        "my_rating"
    ] == 2.0


def test_simulating_applies_the_simulated_members_permissions(
    group, group_owner, make_user
):
    """Acting as a plain member must lose the admin's powers, not keep them."""

    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])

    refused = group_owner.post(
        f"/groups/{group['id']}/members",
        json={"name": "Ann", "rating": 3, "is_subscriber": False, "is_admin": False},
        headers={ACT_AS: membership_id},
    )

    assert refused.status_code == 403


def test_simulating_does_not_change_the_real_session_or_ownership(
    group, group_owner, make_user, db
):
    """The header affects one request and never writes to identities."""

    from backend.models import Membership

    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])

    group_owner.get("/me", headers={ACT_AS: membership_id})

    assert group_owner.get("/me").json()["display_name"] == "Owner"

    memberships = {
        str(item.user_id): item.is_admin
        for item in db.query(Membership).filter(Membership.group_id == uuid.UUID(group["id"]))
    }

    assert memberships[str(group_owner.id)] is True
    assert memberships[str(member.id)] is False


def test_acting_as_yourself_is_allowed(group, group_owner):
    """The frontend can send the header unconditionally."""

    own_id = group["members"][0]["id"]

    assert group_owner.get("/me", headers={ACT_AS: own_id}).json()["display_name"] == (
        "Owner"
    )


def test_a_plain_member_cannot_simulate_anybody(group, group_owner, make_user):
    member = make_user("Nadia")
    other = make_user("Tom")
    join_group(group_owner, member, group["id"])
    other_id = join_group(group_owner, other, group["id"])

    assert member.get("/me", headers={ACT_AS: other_id}).status_code == 403


def test_an_admin_cannot_simulate_a_member_of_another_group(
    group, group_owner, make_user
):
    other_owner = make_user("Other owner")
    other_group = other_owner.post("/groups", json={"name": "Other"}).json()

    assert (
        group_owner.get(
            "/me", headers={ACT_AS: other_group["members"][0]["id"]}
        ).status_code
        == 403
    )


def test_a_virtual_player_cannot_be_simulated(group, group_owner):
    ann = add_virtual(group_owner, group["id"], "Ann")

    response = group_owner.get("/me", headers={ACT_AS: ann["id"]})

    assert response.status_code == 400
    assert "Virtual" in response.json()["detail"]


def test_a_malformed_or_unknown_header_is_rejected(group_owner):
    assert group_owner.get("/me", headers={ACT_AS: "not-a-uuid"}).status_code == 400
    assert group_owner.get("/me", headers={ACT_AS: str(uuid.uuid4())}).status_code == 404


def test_impersonation_is_refused_when_dev_endpoints_are_off(
    group, group_owner, make_user, monkeypatch
):
    """The switch is a developer tool and must be inert in a deployment."""

    from backend import impersonation

    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])

    class Deployed:
        enable_dev_endpoints = False

    monkeypatch.setattr(impersonation, "get_settings", lambda: Deployed())

    response = group_owner.get("/me", headers={ACT_AS: membership_id})

    assert response.status_code == 403
    assert response.json()["detail"] == "Developer impersonation is not enabled"

    # Without the header the deployment carries on working as normal.
    assert group_owner.get("/me").status_code == 200


def test_simulating_works_on_the_live_game_day(group, group_owner, make_user):
    """The whole point: check a player's view of a day they are playing in."""

    member = make_user("Nadia")
    membership_id = join_group(group_owner, member, group["id"])

    create_open_game(group_owner, group["id"])
    assert (
        group_owner.post(
            f"/groups/{group['id']}/game/register/{membership_id}"
        ).status_code
        == 200
    )

    for index in range(11):
        player = add_virtual(group_owner, group["id"], f"Player {index:02d}")
        assert (
            group_owner.post(
                f"/groups/{group['id']}/game/register/{player['id']}"
            ).status_code
            == 200
        )

    assert group_owner.post(f"/groups/{group['id']}/generate-teams").status_code == 200

    day = start_game_day(group_owner, group["id"])
    squad = [
        player["name"] for team in day["teams"] for player in team["players"]
    ]

    assert "Nadia" in squad

    as_member = group_owner.get(
        f"/groups/{group['id']}/game-day", headers={ACT_AS: membership_id}
    )

    assert as_member.status_code == 200
    assert as_member.json()["status"] == "live"
