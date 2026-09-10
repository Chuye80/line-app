"""Development-only endpoints.

These destroy data: they delete every virtual member in a group, wipe the
registration list and rewrite the schedule. They used to be mounted
unconditionally, which meant a single admin misclick in the beta could clear a
real group's game. They are now only registered when `ENABLE_DEV_ENDPOINTS` is
switched on, and the frontend hides the panel unless it is told to show it.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete
from sqlalchemy.orm import Session

from backend import services
from backend.auth import CurrentUser
from backend.database import get_db
from backend.impersonation import acting_user
from backend.main import get_group_or_404, lock_group_or_404, require_admin
from backend.models import (
    GAME_SCHEDULED,
    REGISTRATION_PARTICIPANT,
    REGISTRATION_WAITING,
    Game,
    Membership,
    Registration,
)
from backend.services import MAX_GAME_PLAYERS


router = APIRouter(prefix="/dev", tags=["development"])


def _scheduled_game_or_400(db: Session, group_id: UUID) -> Game:
    """The open game day, which must still be taking registrations."""

    game = services.get_active_game(db, group_id, lock=True)

    if game is None:
        raise HTTPException(status_code=400, detail="Create a game first")

    if game.status != GAME_SCHEDULED:
        raise HTTPException(
            status_code=409,
            detail="The Game Day has already started",
        )

    return game


TEST_MEMBERS: list[tuple[str, int, bool]] = [
    ("Avi", 5, True),
    ("Dan", 4, True),
    ("Ron", 4, True),
    ("Gil", 4, True),
    ("Tom", 4, True),
    ("Yoni", 3, True),
    ("Nir", 3, True),
    ("Omer", 3, False),
    ("Itay", 3, False),
    ("Lior", 2, False),
    ("Ben", 2, False),
    ("Eli", 4, False),
    ("Noam", 3, False),
    ("Adam", 2, False),
    ("Guy", 3, False),
    ("Alex", 3, False),
]


@router.post("/groups/{group_id}/add-test-members")
def dev_add_test_members(
    group_id: UUID,
    count: int = Query(default=16),
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    if count not in (12, 16):
        raise HTTPException(status_code=400, detail="count must be 12 or 16")

    db.execute(
        delete(Membership).where(
            Membership.group_id == group_id,
            Membership.user_id.is_(None),
        )
    )

    memberships = services.load_memberships(db, group_id)
    real_count = sum(1 for item in memberships if item.user_id is not None)

    for name, rating, subscriber in TEST_MEMBERS[: max(0, count - real_count)]:
        db.add(
            Membership(
                group_id=group_id,
                display_name=name,
                rating=rating,
                is_subscriber=subscriber,
                is_admin=False,
            )
        )

    db.commit()

    return services.group_detail(db, group)


@router.post("/groups/{group_id}/create-game")
def dev_create_game(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    # Resetting is the whole point of this endpoint, so it replaces whatever
    # game day is open, including one that is already being played.
    existing = services.get_open_game(db, group_id, lock=True)

    if existing is not None:
        db.delete(existing)
        db.flush()

    now = services.now_utc()

    db.add(
        Game(
            group_id=group_id,
            game_datetime=now + timedelta(hours=2),
            regular_registration_opens=now + timedelta(minutes=1),
        )
    )

    db.commit()

    return services.game_detail(db, group_id)


@router.post("/groups/{group_id}/register-all")
def dev_register_all(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = _scheduled_game_or_400(db, group_id)

    db.execute(delete(Registration).where(Registration.game_id == game.id))
    services.clear_teams(db, game.id)
    db.flush()

    participants = 0

    for membership in services.load_memberships(db, group_id):
        takes_slot = (
            participants < MAX_GAME_PLAYERS
            and services.can_take_game_spot(game, membership)
        )

        db.add(
            Registration(
                game_id=game.id,
                membership_id=membership.id,
                status=(
                    REGISTRATION_PARTICIPANT if takes_slot else REGISTRATION_WAITING
                ),
            )
        )

        # Each row must land with a distinct clock_timestamp() so the waiting
        # list keeps a stable, fair order.
        db.flush()

        if takes_slot:
            participants += 1

    db.commit()

    return services.game_detail(db, group_id)


@router.post("/groups/{group_id}/expire-priority")
def dev_expire_priority(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = _scheduled_game_or_400(db, group_id)

    game.regular_registration_opens = services.now_utc() - timedelta(seconds=1)
    db.flush()

    services.promote_waiting_players(db, game)
    db.commit()

    return services.game_detail(db, group_id)


__all__ = ["router", "TEST_MEMBERS"]
