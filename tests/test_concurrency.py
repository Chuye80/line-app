"""Simultaneous requests.

Every scenario here produced a wrong persisted state before the audit, because
each request read a count, made a decision, and wrote - with nothing stopping a
second request from reading the same count in between.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select

from conftest import add_virtual, create_open_game, join_group
from backend import services
from backend.database import SessionLocal
from backend.models import (
    REGISTRATION_PARTICIPANT,
    REGISTRATION_WAITING,
    JoinRequest,
    Membership,
    Registration,
)
from backend.services import MAX_GAME_PLAYERS


pytestmark = pytest.mark.concurrency


def run_together(calls):
    """Fire every call as close to simultaneously as the runtime allows."""

    barrier = threading.Barrier(len(calls))

    def wrapped(call):
        def run():
            barrier.wait(timeout=30)
            return call()

        return run

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(wrapped(call)) for call in calls]
        return [future.result(timeout=60) for future in futures]


def fill_to_one_slot_remaining(group_owner, group_id):
    for index in range(MAX_GAME_PLAYERS - 1):
        player = add_virtual(group_owner, group_id, f"Filler {index:02d}")
        group_owner.post(f"/groups/{group_id}/game/register/{player['id']}")


def claim_a_slot(group_id, membership_id, *, lock: bool, hold: float = 0.0) -> str:
    """One registration attempt, in its own transaction.

    This is the endpoint's decision procedure with the timing pulled out, so a
    test can force the interleaving that a production race would only hit
    occasionally.
    """

    session = SessionLocal()

    try:
        game = services.get_active_game(session, group_id, lock=lock)
        registrations = services.load_registrations(session, game.id)
        participants, _ = services.split_registrations(registrations)

        status = (
            REGISTRATION_PARTICIPANT
            if len(participants) < MAX_GAME_PLAYERS
            else REGISTRATION_WAITING
        )

        # Stand in for the work a real request does between reading the count
        # and writing its row.
        time.sleep(hold)

        session.add(
            Registration(
                game_id=game.id, membership_id=membership_id, status=status
            )
        )
        session.commit()

        return status
    finally:
        session.close()


def test_the_row_lock_serialises_the_last_slot_decision(
    group, group_owner, make_user, db
):
    """The deterministic proof that the capacity check is now correct.

    Two transactions are forced to overlap: the second reads the participant
    count while the first is still deciding. With the lock the second waits and
    sees the updated count.
    """

    create_open_game(group_owner, group["id"])
    fill_to_one_slot_remaining(group_owner, group["id"])

    first = make_user("Racer One")
    second = make_user("Racer Two")
    first_membership = join_group(group_owner, first, group["id"])
    second_membership = join_group(group_owner, second, group["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(
            claim_a_slot, group["id"], first_membership, lock=True, hold=0.75
        )
        time.sleep(0.2)
        fast = pool.submit(
            claim_a_slot, group["id"], second_membership, lock=True
        )

        outcomes = sorted([slow.result(timeout=30), fast.result(timeout=30)])

    assert outcomes == [REGISTRATION_PARTICIPANT, REGISTRATION_WAITING]

    participants = db.execute(
        select(func.count())
        .select_from(Registration)
        .where(Registration.status == REGISTRATION_PARTICIPANT)
    ).scalar_one()

    assert participants == MAX_GAME_PLAYERS


def test_without_the_lock_the_same_interleaving_oversells_the_game(
    group, group_owner, make_user, db
):
    """Characterises the pre-audit behaviour, so the fix cannot silently regress.

    Identical timing, lock disabled: both transactions read eleven participants
    and both take the twelfth slot, leaving thirteen people in a twelve-player
    game.
    """

    create_open_game(group_owner, group["id"])
    fill_to_one_slot_remaining(group_owner, group["id"])

    first = make_user("Racer One")
    second = make_user("Racer Two")
    first_membership = join_group(group_owner, first, group["id"])
    second_membership = join_group(group_owner, second, group["id"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        slow = pool.submit(
            claim_a_slot, group["id"], first_membership, lock=False, hold=0.75
        )
        time.sleep(0.2)
        fast = pool.submit(
            claim_a_slot, group["id"], second_membership, lock=False
        )

        outcomes = [slow.result(timeout=30), fast.result(timeout=30)]

    assert outcomes == [REGISTRATION_PARTICIPANT, REGISTRATION_PARTICIPANT]

    participants = db.execute(
        select(func.count())
        .select_from(Registration)
        .where(Registration.status == REGISTRATION_PARTICIPANT)
    ).scalar_one()

    assert participants == MAX_GAME_PLAYERS + 1


def test_two_players_racing_for_the_last_slot_do_not_both_get_it(
    group, group_owner, make_user, db
):
    create_open_game(group_owner, group["id"])
    fill_to_one_slot_remaining(group_owner, group["id"])

    first = make_user("Racer One")
    second = make_user("Racer Two")

    first_membership = join_group(group_owner, first, group["id"])
    second_membership = join_group(group_owner, second, group["id"])

    responses = run_together(
        [
            lambda: first.post(
                f"/groups/{group['id']}/game/register/{first_membership}"
            ),
            lambda: second.post(
                f"/groups/{group['id']}/game/register/{second_membership}"
            ),
        ]
    )

    assert [response.status_code for response in responses] == [200, 200]

    state = group_owner.get(f"/groups/{group['id']}").json()["game"]

    assert len(state["participants"]) == MAX_GAME_PLAYERS
    assert len(state["waiting_list"]) == 1

    everyone = {entry["name"] for entry in state["participants"]} | {
        entry["name"] for entry in state["waiting_list"]
    }
    assert {"Racer One", "Racer Two"} <= everyone


def test_the_same_player_registering_twice_at_once_creates_one_registration(
    group, group_owner, db
):
    create_open_game(group_owner, group["id"])
    player = add_virtual(group_owner, group["id"], "Solo")

    responses = run_together(
        [
            lambda: group_owner.post(
                f"/groups/{group['id']}/game/register/{player['id']}"
            )
            for _ in range(4)
        ]
    )

    assert all(response.status_code in (200, 409) for response in responses)

    count = db.execute(
        select(func.count()).select_from(Registration)
    ).scalar_one()

    assert count == 1


def test_two_admins_approving_the_same_request_create_one_membership(
    group, group_owner, make_user, db
):
    second_admin = make_user("Second Admin")
    second_membership = join_group(group_owner, second_admin, group["id"])

    group_owner.put(
        f"/groups/{group['id']}/members/{second_membership}",
        json={"name": "Second Admin", "rating": 3, "is_subscriber": False,
              "is_admin": True},
    )

    applicant = make_user("Applicant")
    applicant.post(f"/groups/{group['id']}/join-request")

    pending = group_owner.get(f"/groups/{group['id']}/join-requests").json()
    request_id = pending[0]["id"]

    responses = run_together(
        [
            lambda: group_owner.post(
                f"/groups/{group['id']}/join-requests/{request_id}/approve"
            ),
            lambda: second_admin.post(
                f"/groups/{group['id']}/join-requests/{request_id}/approve"
            ),
        ]
    )

    statuses = sorted(response.status_code for response in responses)

    # One admin wins; the loser is told the request is no longer pending.
    assert statuses == [200, 404]

    memberships = db.execute(
        select(func.count())
        .select_from(Membership)
        .where(Membership.user_id == applicant.id)
    ).scalar_one()

    assert memberships == 1


def test_approving_and_declining_at_once_leaves_one_decision(
    group, group_owner, make_user, db
):
    second_admin = make_user("Second Admin")
    second_membership = join_group(group_owner, second_admin, group["id"])
    group_owner.put(
        f"/groups/{group['id']}/members/{second_membership}",
        json={"name": "Second Admin", "rating": 3, "is_subscriber": False,
              "is_admin": True},
    )

    applicant = make_user("Applicant")
    applicant.post(f"/groups/{group['id']}/join-request")
    request_id = group_owner.get(f"/groups/{group['id']}/join-requests").json()[0]["id"]

    responses = run_together(
        [
            lambda: group_owner.post(
                f"/groups/{group['id']}/join-requests/{request_id}/approve"
            ),
            lambda: second_admin.post(
                f"/groups/{group['id']}/join-requests/{request_id}/decline"
            ),
        ]
    )

    assert sorted(response.status_code for response in responses) == [200, 404]

    statuses = db.execute(
        select(JoinRequest.status).where(JoinRequest.user_id == applicant.id)
    ).scalars().all()

    assert len(statuses) == 1
    assert statuses[0] in ("approved", "declined")


def test_duplicate_join_requests_sent_at_once_create_one_row(
    group, make_user, db
):
    applicant = make_user("Applicant")

    responses = run_together(
        [
            lambda: applicant.post(f"/groups/{group['id']}/join-request")
            for _ in range(4)
        ]
    )

    assert all(response.status_code == 200 for response in responses)

    count = db.execute(
        select(func.count())
        .select_from(JoinRequest)
        .where(JoinRequest.user_id == applicant.id)
    ).scalar_one()

    assert count == 1


def test_two_admins_leaving_at_once_cannot_strand_the_group(
    group, group_owner, make_user, db
):
    second_admin = make_user("Second Admin")
    second_membership = join_group(group_owner, second_admin, group["id"])

    group_owner.put(
        f"/groups/{group['id']}/members/{second_membership}",
        json={"name": "Second Admin", "rating": 3, "is_subscriber": False,
              "is_admin": True},
    )

    responses = run_together(
        [
            lambda: group_owner.delete(f"/groups/{group['id']}/leave"),
            lambda: second_admin.delete(f"/groups/{group['id']}/leave"),
        ]
    )

    assert sorted(response.status_code for response in responses) == [200, 400]

    remaining_admins = db.execute(
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.group_id == group["id"],
            Membership.is_admin.is_(True),
            Membership.user_id.is_not(None),
        )
    ).scalar_one()

    assert remaining_admins == 1


def test_racing_unregistrations_promote_exactly_one_replacement(
    group, group_owner, db
):
    create_open_game(group_owner, group["id"])

    players = [
        add_virtual(group_owner, group["id"], f"Player {index:02d}")
        for index in range(MAX_GAME_PLAYERS + 1)
    ]

    for player in players:
        group_owner.post(f"/groups/{group['id']}/game/register/{player['id']}")

    responses = run_together(
        [
            lambda: group_owner.post(
                f"/groups/{group['id']}/game/unregister/{players[0]['id']}"
            ),
            lambda: group_owner.post(
                f"/groups/{group['id']}/game/unregister/{players[1]['id']}"
            ),
        ]
    )

    assert all(response.status_code == 200 for response in responses)

    state = group_owner.get(f"/groups/{group['id']}").json()["game"]

    # Two left, one replacement was available.
    assert len(state["participants"]) == MAX_GAME_PLAYERS - 1
    assert state["waiting_list"] == []
