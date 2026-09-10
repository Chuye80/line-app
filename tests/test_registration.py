"""Registration, subscriber priority and the waiting list."""

from __future__ import annotations

import pytest

from conftest import add_virtual, create_game, create_open_game, join_group
from backend.services import MAX_GAME_PLAYERS


def register(actor, group_id, membership_id):
    return actor.post(f"/groups/{group_id}/game/register/{membership_id}")


def unregister(actor, group_id, membership_id):
    return actor.post(f"/groups/{group_id}/game/unregister/{membership_id}")


def game_state(actor, group_id):
    return actor.get(f"/groups/{group_id}").json()["game"]


def names(entries):
    return [entry["name"] for entry in entries]


def test_owner_is_the_first_member_and_an_admin(group, group_owner):
    detail = group_owner.get(f"/groups/{group['id']}").json()

    assert len(detail["members"]) == 1
    assert detail["members"][0]["is_admin"] is True
    assert detail["members"][0]["is_virtual"] is False


def test_registration_fills_slots_then_overflows_to_the_waiting_list(
    group, group_owner
):
    create_open_game(group_owner, group["id"])

    players = [
        add_virtual(group_owner, group["id"], f"Player {index}")
        for index in range(MAX_GAME_PLAYERS + 3)
    ]

    for player in players:
        assert register(group_owner, group["id"], player["id"]).status_code == 200

    state = game_state(group_owner, group["id"])

    assert len(state["participants"]) == MAX_GAME_PLAYERS
    assert len(state["waiting_list"]) == 3
    assert names(state["waiting_list"]) == [
        "Player 12",
        "Player 13",
        "Player 14",
    ]


def test_waiting_list_keeps_registration_order(group, group_owner):
    create_open_game(group_owner, group["id"])

    players = [
        add_virtual(group_owner, group["id"], f"Player {index:02d}")
        for index in range(MAX_GAME_PLAYERS + 4)
    ]

    for player in players:
        register(group_owner, group["id"], player["id"])

    state = game_state(group_owner, group["id"])

    assert names(state["participants"]) == [
        f"Player {index:02d}" for index in range(MAX_GAME_PLAYERS)
    ]
    assert names(state["waiting_list"]) == [
        f"Player {index:02d}" for index in range(MAX_GAME_PLAYERS, MAX_GAME_PLAYERS + 4)
    ]


def test_non_subscribers_wait_during_the_priority_window(group, group_owner):
    create_game(group_owner, group["id"], hours_ahead=48, priority_hours=24)

    subscriber = add_virtual(group_owner, group["id"], "Sub", subscriber=True)
    regular = add_virtual(group_owner, group["id"], "Reg", subscriber=False)

    register(group_owner, group["id"], regular["id"])
    register(group_owner, group["id"], subscriber["id"])

    state = game_state(group_owner, group["id"])

    # The non-subscriber registered first but the window belongs to subscribers.
    assert names(state["participants"]) == ["Sub"]
    assert names(state["waiting_list"]) == ["Reg"]


def test_subscriber_priority_does_not_apply_once_the_window_closes(
    group, group_owner
):
    create_open_game(group_owner, group["id"])

    regular = add_virtual(group_owner, group["id"], "Reg", subscriber=False)
    register(group_owner, group["id"], regular["id"])

    state = game_state(group_owner, group["id"])

    assert names(state["participants"]) == ["Reg"]
    assert state["waiting_list"] == []


def test_waiting_non_subscribers_are_promoted_when_priority_expires(
    group, group_owner
):
    create_game(group_owner, group["id"], hours_ahead=48, priority_hours=24)

    first = add_virtual(group_owner, group["id"], "First", subscriber=False)
    second = add_virtual(group_owner, group["id"], "Second", subscriber=False)

    register(group_owner, group["id"], first["id"])
    register(group_owner, group["id"], second["id"])

    assert game_state(group_owner, group["id"])["participants"] == []

    assert (
        group_owner.post(f"/dev/groups/{group['id']}/expire-priority").status_code
        == 200
    )

    state = game_state(group_owner, group["id"])

    assert names(state["participants"]) == ["First", "Second"]
    assert state["waiting_list"] == []


def test_promotion_after_expiry_respects_the_queue_order(group, group_owner):
    create_game(group_owner, group["id"], hours_ahead=48, priority_hours=24)

    subscribers = [
        add_virtual(group_owner, group["id"], f"Sub {index:02d}", subscriber=True)
        for index in range(MAX_GAME_PLAYERS - 1)
    ]
    waiting = [
        add_virtual(group_owner, group["id"], f"Wait {index:02d}")
        for index in range(3)
    ]

    for player in subscribers + waiting:
        register(group_owner, group["id"], player["id"])

    group_owner.post(f"/dev/groups/{group['id']}/expire-priority")

    state = game_state(group_owner, group["id"])

    # Exactly one free slot, taken by the player who has waited longest.
    assert len(state["participants"]) == MAX_GAME_PLAYERS
    assert "Wait 00" in names(state["participants"])
    assert names(state["waiting_list"]) == ["Wait 01", "Wait 02"]


def test_unregistering_a_participant_promotes_the_first_in_line(group, group_owner):
    create_open_game(group_owner, group["id"])

    players = [
        add_virtual(group_owner, group["id"], f"Player {index:02d}")
        for index in range(MAX_GAME_PLAYERS + 2)
    ]

    for player in players:
        register(group_owner, group["id"], player["id"])

    unregister(group_owner, group["id"], players[0]["id"])

    state = game_state(group_owner, group["id"])

    assert len(state["participants"]) == MAX_GAME_PLAYERS
    assert "Player 12" in names(state["participants"])
    assert names(state["waiting_list"]) == ["Player 13"]


def test_unregistering_from_the_waiting_list_does_not_promote_anyone(
    group, group_owner
):
    create_open_game(group_owner, group["id"])

    players = [
        add_virtual(group_owner, group["id"], f"Player {index:02d}")
        for index in range(MAX_GAME_PLAYERS + 2)
    ]

    for player in players:
        register(group_owner, group["id"], player["id"])

    unregister(group_owner, group["id"], players[-1]["id"])

    state = game_state(group_owner, group["id"])

    assert len(state["participants"]) == MAX_GAME_PLAYERS
    assert names(state["waiting_list"]) == ["Player 12"]


def test_registering_twice_is_a_no_op(group, group_owner):
    create_open_game(group_owner, group["id"])
    player = add_virtual(group_owner, group["id"], "Solo")

    register(group_owner, group["id"], player["id"])
    register(group_owner, group["id"], player["id"])

    state = game_state(group_owner, group["id"])

    assert len(state["participants"]) == 1


def test_registering_requires_an_active_game(group, group_owner):
    player = add_virtual(group_owner, group["id"], "Solo")

    response = register(group_owner, group["id"], player["id"])

    assert response.status_code == 400
    assert response.json()["detail"] == "No active game"


def test_members_cannot_register_somebody_else(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])

    member = make_user("Member")
    join_group(group_owner, member, group["id"])

    victim = add_virtual(group_owner, group["id"], "Victim")

    response = register(member, group["id"], victim["id"])

    assert response.status_code == 403


def test_members_can_register_themselves(group, group_owner, make_user):
    create_open_game(group_owner, group["id"])

    member = make_user("Member")
    membership_id = join_group(group_owner, member, group["id"])

    assert register(member, group["id"], membership_id).status_code == 200
    assert names(game_state(member, group["id"])["participants"]) == ["Member"]


def test_a_registration_cannot_reference_another_groups_member(
    group, group_owner, make_user
):
    create_open_game(group_owner, group["id"])

    other_owner = make_user("Other Owner")
    other = other_owner.post("/groups", json={"name": "Other"}).json()
    outsider = add_virtual(other_owner, other["id"], "Outsider")

    response = register(group_owner, group["id"], outsider["id"])

    assert response.status_code == 404


@pytest.mark.parametrize("priority_hours", [0, 6, 24, 72, 95])
def test_priority_window_is_still_open_before_the_configured_cutoff(
    group, group_owner, priority_hours
):
    """`priority_hours` is measured backwards from kickoff.

    For a game 96 hours away, any cutoff shorter than 96 hours is still in the
    future, so the game is subscribers-only right now.
    """

    create_game(
        group_owner, group["id"], hours_ahead=96, priority_hours=priority_hours
    )

    regular = add_virtual(group_owner, group["id"], "Reg")
    register(group_owner, group["id"], regular["id"])

    assert names(game_state(group_owner, group["id"])["waiting_list"]) == ["Reg"]


@pytest.mark.parametrize("hours_ahead", [6, 24, 96])
def test_registration_is_open_to_everyone_once_the_cutoff_has_passed(
    group, group_owner, hours_ahead
):
    create_open_game(group_owner, group["id"], hours_ahead=hours_ahead)

    regular = add_virtual(group_owner, group["id"], "Reg")
    register(group_owner, group["id"], regular["id"])

    state = game_state(group_owner, group["id"])

    assert names(state["participants"]) == ["Reg"]
    assert state["waiting_list"] == []
