"""Authentication, authorisation and privacy between groups."""

from __future__ import annotations

import uuid

import pytest

from conftest import add_virtual, create_open_game, join_group


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


ENDPOINTS = [
    ("GET", "/me"),
    ("GET", "/groups"),
    ("GET", "/my-groups"),
    ("POST", "/groups"),
]


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_every_endpoint_requires_a_session(client, method, path):
    assert client.request(method, path).status_code == 401


def test_group_endpoints_require_a_session(client, group):
    group_id = group["id"]

    for method, path in [
        ("GET", f"/groups/{group_id}"),
        ("GET", f"/groups/{group_id}/membership-status"),
        ("GET", f"/groups/{group_id}/join-requests"),
        ("POST", f"/groups/{group_id}/join-request"),
        ("DELETE", f"/groups/{group_id}/leave"),
        ("POST", f"/groups/{group_id}/generate-teams"),
    ]:
        assert client.request(method, path).status_code == 401, path


# ---------------------------------------------------------------------------
# Private group data
# ---------------------------------------------------------------------------


def test_a_non_member_cannot_read_a_groups_roster_or_fixtures(
    group, group_owner, make_user
):
    """The central privacy rule.

    Before the audit `GET /groups/{id}` returned the complete roster - names,
    ratings, subscriber flags, admin flags - plus the fixture and the generated
    teams to any signed-in account that knew the group id.
    """

    create_open_game(group_owner, group["id"])
    add_virtual(group_owner, group["id"], "Secret Player", rating=5, subscriber=True)

    outsider = make_user("Outsider")
    body = outsider.get(f"/groups/{group['id']}").json()

    assert body["id"] == group["id"]
    assert body["name"] == group["name"]
    assert body["members"] == []
    assert body["game"] is None
    assert body["teams"] == []

    serialised = str(body)
    assert "Secret Player" not in serialised
    assert "Owner" not in serialised


def test_a_member_sees_the_full_group(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])
    add_virtual(group_owner, group["id"], "Secret Player")

    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    body = member.get(f"/groups/{group['id']}").json()

    assert {entry["name"] for entry in body["members"]} == {
        "Owner",
        "Secret Player",
        "Member",
    }
    assert body["game"] is not None


def test_a_non_member_cannot_list_pending_join_requests(group, make_user):
    outsider = make_user("Outsider")

    assert outsider.get(f"/groups/{group['id']}/join-requests").status_code == 403


def test_a_plain_member_cannot_list_pending_join_requests(
    group, group_owner, make_user
):
    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    assert member.get(f"/groups/{group['id']}/join-requests").status_code == 403


def test_a_non_member_cannot_modify_a_group(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])
    victim = add_virtual(group_owner, group["id"], "Victim")

    outsider = make_user("Outsider")
    group_id = group["id"]

    attempts = [
        outsider.post(
            f"/groups/{group_id}/members",
            json={"name": "Sneak", "rating": 5, "is_subscriber": True,
                  "is_admin": False},
        ),
        outsider.put(
            f"/groups/{group_id}/members/{victim['id']}",
            json={"name": "Hacked", "rating": 1, "is_subscriber": False,
                  "is_admin": False},
        ),
        outsider.delete(f"/groups/{group_id}/members/{victim['id']}"),
        outsider.delete(f"/groups/{group_id}/game"),
        outsider.post(f"/groups/{group_id}/generate-teams"),
        outsider.post(f"/groups/{group_id}/game/register/{victim['id']}"),
        outsider.delete(f"/groups/{group_id}/leave"),
    ]

    assert [response.status_code for response in attempts] == [403] * len(attempts)

    # Nothing changed.
    detail = group_owner.get(f"/groups/{group_id}").json()
    assert {entry["name"] for entry in detail["members"]} == {"Owner", "Victim"}


def test_a_plain_member_cannot_perform_admin_actions(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])
    victim = add_virtual(group_owner, group["id"], "Victim")

    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    group_id = group["id"]

    attempts = [
        member.post(
            f"/groups/{group_id}/members",
            json={"name": "Sneak", "rating": 5, "is_subscriber": False,
                  "is_admin": False},
        ),
        member.put(
            f"/groups/{group_id}/members/{victim['id']}",
            json={"name": "Hacked", "rating": 1, "is_subscriber": False,
                  "is_admin": False},
        ),
        member.delete(f"/groups/{group_id}/members/{victim['id']}"),
        member.delete(f"/groups/{group_id}/game"),
        member.post(f"/groups/{group_id}/generate-teams"),
    ]

    assert [response.status_code for response in attempts] == [403] * len(attempts)


def test_an_admin_cannot_reach_into_another_group(group, group_owner, make_user):
    other_owner = make_user("Other Owner")
    other = other_owner.post("/groups", json={"name": "Private"}).json()
    other_member = add_virtual(other_owner, other["id"], "Their Player")

    # Being an admin somewhere confers nothing anywhere else.
    assert group_owner.get(f"/groups/{other['id']}").json()["members"] == []
    assert (
        group_owner.delete(
            f"/groups/{other['id']}/members/{other_member['id']}"
        ).status_code
        == 403
    )


def test_membership_status_does_not_leak_group_contents(group, make_user):
    outsider = make_user("Outsider")

    body = outsider.get(f"/groups/{group['id']}/membership-status").json()

    assert body == {"state": "none", "membership_id": None, "is_admin": False}


def test_unknown_group_returns_not_found(make_user):
    outsider = make_user("Outsider")

    assert outsider.get(f"/groups/{uuid.uuid4()}").status_code == 404


def test_my_groups_only_lists_the_callers_memberships(group, group_owner, make_user):
    other = make_user("Other")
    other.post("/groups", json={"name": "Theirs"})

    mine = group_owner.get("/my-groups").json()

    assert [entry["name"] for entry in mine] == ["Sunday League"]


# ---------------------------------------------------------------------------
# Virtual players
# ---------------------------------------------------------------------------


def test_a_virtual_player_cannot_be_created_as_an_admin(group, group_owner):
    response = group_owner.post(
        f"/groups/{group['id']}/members",
        json={"name": "Ghost", "rating": 3, "is_subscriber": False,
              "is_admin": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Virtual players cannot be administrators"


def test_a_virtual_player_cannot_be_promoted_to_admin(group, group_owner):
    ghost = add_virtual(group_owner, group["id"], "Ghost")

    response = group_owner.put(
        f"/groups/{group['id']}/members/{ghost['id']}",
        json={"name": "Ghost", "rating": 3, "is_subscriber": False,
              "is_admin": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Virtual players cannot be administrators"


def test_the_database_refuses_a_virtual_admin_even_if_the_api_is_bypassed(db, group):
    """The application check is backed by a constraint, not trusted alone."""

    from sqlalchemy.exc import IntegrityError
    from sqlalchemy import text

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "insert into memberships (group_id, display_name, is_admin) "
                "values (:group_id, 'Ghost', true)"
            ),
            {"group_id": group["id"]},
        )
        db.flush()


# ---------------------------------------------------------------------------
# Last administrator
# ---------------------------------------------------------------------------


def test_the_only_admin_cannot_leave(group, group_owner):
    response = group_owner.delete(f"/groups/{group['id']}/leave")

    assert response.status_code == 400
    assert "admin" in response.json()["detail"].lower()

    assert len(group_owner.get("/my-groups").json()) == 1


def test_the_only_admin_cannot_demote_themselves(group, group_owner):
    membership_id = group_owner.get("/my-groups").json()[0]["membership_id"]

    response = group_owner.put(
        f"/groups/{group['id']}/members/{membership_id}",
        json={"name": "Owner", "rating": 3, "is_subscriber": False,
              "is_admin": False},
    )

    assert response.status_code == 400
    assert group_owner.get(f"/groups/{group['id']}/membership-status").json()[
        "is_admin"
    ]


def test_the_only_admin_cannot_delete_their_own_membership(group, group_owner):
    membership_id = group_owner.get("/my-groups").json()[0]["membership_id"]

    response = group_owner.delete(
        f"/groups/{group['id']}/members/{membership_id}"
    )

    assert response.status_code == 400


def test_moving_the_only_admin_cannot_strand_the_old_group(
    db, group, group_owner, make_user
):
    """The database guard covers direct writes outside the supported API."""

    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    membership_id = group_owner.get("/my-groups").json()[0]["membership_id"]
    remaining_member = make_user("Remaining Member")
    join_group(group_owner, remaining_member, group["id"])
    other_owner = make_user("Other Owner")
    other_group = other_owner.post("/groups", json={"name": "Other"}).json()

    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "update memberships set group_id = :new_group "
                "where id = :membership_id"
            ),
            {
                "new_group": other_group["id"],
                "membership_id": membership_id,
            },
        )
        db.commit()


def test_virtual_admins_do_not_count_towards_the_last_admin_rule(group, group_owner):
    """A virtual player can never sign in, so it cannot be the surviving admin."""

    add_virtual(group_owner, group["id"], "Ghost")

    assert group_owner.delete(f"/groups/{group['id']}/leave").status_code == 400


def test_an_admin_can_leave_once_another_admin_exists(group, group_owner, make_user):
    member = make_user("Member")
    membership_id = join_group(group_owner, member, group["id"])

    assert (
        group_owner.put(
            f"/groups/{group['id']}/members/{membership_id}",
            json={"name": "Member", "rating": 3, "is_subscriber": False,
                  "is_admin": True},
        ).status_code
        == 200
    )

    assert group_owner.delete(f"/groups/{group['id']}/leave").status_code == 200

    assert member.get(f"/groups/{group['id']}").json()["members"][0]["name"] == (
        "Member"
    )


def test_a_plain_member_can_always_leave(group, group_owner, make_user):
    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    assert member.delete(f"/groups/{group['id']}/leave").status_code == 200
    assert member.get("/my-groups").json() == []


def test_leaving_removes_the_member_from_the_upcoming_game(
    group, group_owner, make_user
):
    create_open_game(group_owner, group["id"])

    member = make_user("Member")
    membership_id = join_group(group_owner, member, group["id"])

    member.post(f"/groups/{group['id']}/game/register/{membership_id}")
    assert (
        len(group_owner.get(f"/groups/{group['id']}").json()["game"]["participants"])
        == 1
    )

    member.delete(f"/groups/{group['id']}/leave")

    assert group_owner.get(f"/groups/{group['id']}").json()["game"][
        "participants"
    ] == []
