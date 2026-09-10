"""Guards against the N+1 patterns coming back.

The frontend polls `GET /groups/{id}`, so its cost is multiplied by every open
tab. Before the audit it issued 49 statements for a sixteen-member group -
roughly four `profiles` lookups per player - and one call to Supabase Auth. The
assertions below pin the shape of the query plan: a constant number of
statements, independent of how many members, registrations or teams exist.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from conftest import add_virtual, create_open_game, join_group
from backend.database import engine


@contextmanager
def counted_statements():
    counter = {"count": 0, "statements": []}

    def before(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1
        counter["statements"].append(statement.split("\n")[0][:90])

    event.listen(engine, "before_cursor_execute", before)

    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", before)


def build_group(group_owner, group_id, member_count):
    create_open_game(group_owner, group_id)

    for index in range(member_count):
        player = add_virtual(group_owner, group_id, f"Player {index:02d}")
        group_owner.post(f"/groups/{group_id}/game/register/{player['id']}")

    group_owner.post(f"/groups/{group_id}/generate-teams")


def test_reading_a_group_costs_a_fixed_number_of_statements(group, group_owner):
    build_group(group_owner, group["id"], 15)

    with counted_statements() as counter:
        response = group_owner.get(f"/groups/{group['id']}")

    assert response.status_code == 200
    assert len(response.json()["members"]) == 16
    assert len(response.json()["teams"]) == 3

    assert counter["count"] <= 8, counter["statements"]


@pytest.mark.parametrize("member_count", [1, 8, 20])
def test_the_cost_of_reading_a_group_does_not_grow_with_its_size(
    group, group_owner, member_count
):
    create_open_game(group_owner, group["id"])

    for index in range(member_count):
        player = add_virtual(group_owner, group["id"], f"Player {index:02d}")
        group_owner.post(f"/groups/{group['id']}/game/register/{player['id']}")

    with counted_statements() as counter:
        group_owner.get(f"/groups/{group['id']}")

    assert counter["count"] <= 8, counter["statements"]


def test_a_steady_state_poll_performs_no_writes(group, group_owner):
    """A read must not mutate. The old code deleted games and promoted players."""

    build_group(group_owner, group["id"], 15)

    with counted_statements() as counter:
        group_owner.get(f"/groups/{group['id']}")

    written = [
        statement
        for statement in counter["statements"]
        if statement.lower().startswith(("insert", "update", "delete"))
    ]

    assert written == []


def test_reading_a_group_as_a_non_member_is_cheap(group, group_owner, make_user):
    build_group(group_owner, group["id"], 15)
    outsider = make_user("Outsider")

    with counted_statements() as counter:
        body = outsider.get(f"/groups/{group['id']}").json()

    assert body["members"] == []
    assert counter["count"] <= 3, counter["statements"]


def test_listing_my_groups_is_a_single_query(group, group_owner, make_user):
    for index in range(5):
        group_owner.post("/groups", json={"name": f"Group {index}"})

    with counted_statements() as counter:
        response = group_owner.get("/my-groups")

    assert len(response.json()) == 6
    assert counter["count"] == 1, counter["statements"]


def test_listing_pending_requests_does_not_query_per_applicant(
    group, group_owner, make_user
):
    for index in range(6):
        applicant = make_user(f"Applicant {index}")
        applicant.post(f"/groups/{group['id']}/join-request")

    with counted_statements() as counter:
        response = group_owner.get(f"/groups/{group['id']}/join-requests")

    assert len(response.json()) == 6
    assert all(entry["user_name"].startswith("Applicant") for entry in response.json())
    assert counter["count"] <= 4, counter["statements"]


def test_registering_does_not_reload_the_world(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])

    member = make_user("Member")
    membership_id = join_group(group_owner, member, group["id"])

    for index in range(10):
        player = add_virtual(group_owner, group["id"], f"Player {index:02d}")
        group_owner.post(f"/groups/{group['id']}/game/register/{player['id']}")

    with counted_statements() as counter:
        response = member.post(
            f"/groups/{group['id']}/game/register/{membership_id}"
        )

    assert response.status_code == 200
    assert counter["count"] <= 10, counter["statements"]
