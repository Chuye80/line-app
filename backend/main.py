from __future__ import annotations

import logging
from datetime import timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import game_day, services
from backend.auth import CurrentUser
from backend.config import get_settings
from backend.database import get_db
from backend.impersonation import acting_user
from backend.models import (
    GAME_FINISHED,
    GAME_LIVE,
    GAME_SCHEDULED,
    JOIN_REQUEST_APPROVED,
    JOIN_REQUEST_DECLINED,
    JOIN_REQUEST_PENDING,
    MATCH_COMPLETED,
    MATCH_LIVE,
    MATCH_SCHEDULED,
    REGISTRATION_PARTICIPANT,
    REGISTRATION_WAITING,
    Game,
    Group,
    JoinRequest,
    Match,
    MatchGoal,
    Membership,
    Registration,
    TeamAssignment,
)
from backend.schemas import (
    AddGoalRequest,
    CreateGameRequest,
    CreateGroupRequest,
    MemberRequest,
    SaveSurveyRequest,
    UpdateTeamsRequest,
)
from backend.models import TEAM_NAMES
from backend.services import MAX_GAME_PLAYERS
from backend.team_generator import REQUIRED_PLAYERS, generate_balanced_teams


logger = logging.getLogger("lineapp")

settings = get_settings()

app = FastAPI(title="LineApp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Database-level guards that correspond to a user-facing rule. When a race
# slips past the application check, the constraint still fires, and the caller
# should see the same message they would have seen from the check.
_CONSTRAINT_MESSAGES = {
    "memberships_group_user_unique": "You are already a member of this group",
    "registrations_game_membership_unique": "Already registered for this game",
    "join_requests_pending_unique": "Request already pending",
    "team_assignments_game_membership_unique": (
        "A player can only be assigned to one team"
    ),
    "memberships_virtual_players_not_admin": (
        "Virtual players cannot be administrators"
    ),
    "memberships_rating_range": "Rating must be between 1 and 5",
    "would be left without an administrator": (
        "Promote another member to admin first"
    ),
    "games_one_live_per_group": "Another Game Day is already in progress",
    "matches_one_live_per_game": "Another match is already in progress",
    "matches_game_order_unique": "That match already exists",
    "match_goals_assist_is_not_scorer": (
        "A player cannot assist their own goal"
    ),
    "player_ratings_value_valid": (
        "Rating must be between 1.0 and 5.0 in half points"
    ),
    "player_ratings_no_self_rating": "You cannot rate yourself",
    "player_ratings_rater_subject_unique": "You have already rated this player",
}


def _constraint_message(error: IntegrityError) -> str | None:
    text = str(getattr(error, "orig", error))

    for marker, message in _CONSTRAINT_MESSAGES.items():
        if marker in text:
            return message

    return None


@app.exception_handler(IntegrityError)
def handle_integrity_error(request: Request, exc: IntegrityError) -> JSONResponse:
    message = _constraint_message(exc)

    if message is not None:
        return JSONResponse(status_code=409, content={"detail": message})

    logger.exception("Unhandled database constraint violation")

    return JSONResponse(
        status_code=409,
        content={"detail": "The request conflicts with the current state"},
    )


def commit(db: Session) -> None:
    """Commit, translating a constraint violation into a useful error."""

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()

        message = _constraint_message(exc)

        if message is not None:
            raise HTTPException(status_code=409, detail=message) from exc

        raise


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def get_group_or_404(db: Session, group_id: UUID) -> Group:
    group = services.get_group(db, group_id)

    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    return group


def lock_group_or_404(db: Session, group_id: UUID) -> Group:
    group = services.lock_group(db, group_id)

    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    return group


def require_membership(db: Session, group_id: UUID, user: CurrentUser) -> Membership:
    membership = services.membership_for_user(db, group_id, user.id)

    if membership is None:
        raise HTTPException(
            status_code=403, detail="You are not a member of this group"
        )

    return membership


def require_admin(db: Session, group_id: UUID, user: CurrentUser) -> Membership:
    membership = require_membership(db, group_id, user)

    if not membership.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    return membership


def require_active_game(db: Session, group_id: UUID, *, lock: bool = False) -> Game:
    game = services.get_active_game(db, group_id, lock=lock)

    if game is None:
        raise HTTPException(status_code=400, detail="No active game")

    return game


def require_scheduled_game(
    db: Session,
    group_id: UUID,
    *,
    lock: bool = False,
) -> Game:
    """Registration and team building belong to the phase before kickoff.

    Once the day is live the squad and the teams are what the matches are being
    played with, so they are fixed. The registration rows are kept - they are
    the record of who turned up - the UI simply stops offering to change them.
    """

    game = require_active_game(db, group_id, lock=lock)

    if game.status != GAME_SCHEDULED:
        raise HTTPException(
            status_code=409,
            detail="The Game Day has already started",
        )

    return game


def require_live_game(db: Session, group_id: UUID, *, lock: bool = False) -> Game:
    game = require_active_game(db, group_id, lock=lock)

    if game.status != GAME_LIVE:
        raise HTTPException(status_code=409, detail="No Game Day in progress")

    return game


def target_membership_or_404(
    db: Session,
    group_id: UUID,
    membership_id: UUID,
) -> Membership:
    membership = db.get(Membership, membership_id)

    if membership is None or membership.group_id != group_id:
        raise HTTPException(status_code=404, detail="Member not found")

    return membership


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
def root():
    return {"message": "LineApp backend is running on Supabase/PostgreSQL"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


@app.get("/me")
def me(
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    names = services.load_display_names(db, [user.id])

    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": names.get(user.id) or services.FALLBACK_PLAYER_NAME,
    }


@app.get("/groups")
def get_groups(
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Discovery list. Deliberately limited to what the join screen needs."""

    rows = db.execute(
        select(Group.id, Group.name).order_by(Group.created_at.desc())
    ).all()

    return [{"id": str(row[0]), "name": row[1]} for row in rows]


@app.get("/my-groups")
def get_my_groups(
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(
            Group.id,
            Group.name,
            Membership.id,
            Membership.is_admin,
            Membership.is_subscriber,
            Membership.rating,
        )
        .join(Group, Group.id == Membership.group_id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).all()

    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "membership_id": str(row[2]),
            "is_admin": row[3],
            "is_subscriber": row[4],
            "rating": row[5],
        }
        for row in rows
    ]


@app.post("/groups")
def create_group(
    request: CreateGroupRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = Group(name=request.name, created_by=user.id)
    db.add(group)
    db.flush()

    db.add(
        Membership(
            group_id=group.id,
            user_id=user.id,
            rating=3,
            is_subscriber=False,
            is_admin=True,
        )
    )

    commit(db)

    return services.group_detail(db, group)


@app.get("/groups/{group_id}")
def get_group(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Group state.

    Members receive the full roster, schedule and teams. Everybody else sees
    only the name, which is what the join screen renders. Before this check any
    signed-in account could read every private group's members, their ratings,
    their subscriber status and their fixture list simply by knowing the id.
    """

    group = get_group_or_404(db, group_id)

    if services.membership_for_user(db, group_id, user.id) is None:
        return services.public_group_view(group)

    return services.group_detail(db, group)


@app.get("/groups/{group_id}/membership-status")
def get_membership_status(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)

    membership = services.membership_for_user(db, group_id, user.id)

    if membership is not None:
        return {
            "state": "member",
            "membership_id": str(membership.id),
            "is_admin": membership.is_admin,
        }

    request = db.execute(
        select(JoinRequest)
        .where(JoinRequest.group_id == group_id, JoinRequest.user_id == user.id)
        .order_by(JoinRequest.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "state": request.status if request else "none",
        "membership_id": None,
        "is_admin": False,
    }


@app.post("/groups/{group_id}/join-request")
def request_to_join(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)

    if services.membership_for_user(db, group_id, user.id) is not None:
        raise HTTPException(status_code=400, detail="You are already a member")

    db.add(
        JoinRequest(group_id=group_id, user_id=user.id, status=JOIN_REQUEST_PENDING)
    )

    try:
        db.commit()
    except IntegrityError:
        # The partial unique index makes a duplicate request impossible; a
        # second click is simply a no-op rather than an error.
        db.rollback()
        return {"message": "Request already pending"}

    return {"message": "Join request submitted"}


@app.get("/groups/{group_id}/join-requests")
def pending_join_requests(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    requests = list(
        db.execute(
            select(JoinRequest)
            .where(
                JoinRequest.group_id == group_id,
                JoinRequest.status == JOIN_REQUEST_PENDING,
            )
            .order_by(JoinRequest.created_at)
        ).scalars()
    )

    display_names = services.load_display_names(
        db, [item.user_id for item in requests]
    )

    return [
        {
            "id": str(item.id),
            "user_id": str(item.user_id),
            "user_name": display_names.get(item.user_id)
            or services.FALLBACK_PLAYER_NAME,
            "status": item.status,
        }
        for item in requests
    ]


def _locked_pending_request(
    db: Session,
    group_id: UUID,
    request_id: UUID,
) -> JoinRequest:
    """Claim a pending request so two admins cannot both act on it."""

    request = db.execute(
        select(JoinRequest).where(JoinRequest.id == request_id).with_for_update()
    ).scalar_one_or_none()

    if (
        request is None
        or request.group_id != group_id
        or request.status != JOIN_REQUEST_PENDING
    ):
        raise HTTPException(status_code=404, detail="Pending request not found")

    return request


@app.post("/groups/{group_id}/join-requests/{request_id}/approve")
def approve_join_request(
    group_id: UUID,
    request_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    request = _locked_pending_request(db, group_id, request_id)

    if services.membership_for_user(db, group_id, request.user_id) is None:
        db.add(
            Membership(
                group_id=group_id,
                user_id=request.user_id,
                rating=3,
                is_subscriber=False,
                is_admin=False,
            )
        )

    request.status = JOIN_REQUEST_APPROVED
    commit(db)

    return {"message": "Join request approved"}


@app.post("/groups/{group_id}/join-requests/{request_id}/decline")
def decline_join_request(
    group_id: UUID,
    request_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    request = _locked_pending_request(db, group_id, request_id)
    request.status = JOIN_REQUEST_DECLINED
    commit(db)

    return {"message": "Join request declined"}


def _detach_from_active_game(
    db: Session,
    group_id: UUID,
    membership_id: UUID,
    game: Game | None = None,
) -> None:
    """Remove a departing member from the upcoming game and backfill the slot.

    Pass `game` when the caller already holds its lock.
    """

    if game is None:
        game = services.get_active_game(db, group_id, lock=True)

    if game is None:
        return

    # A day that is already being played keeps its squad: those rows are the
    # record of who took part, and the matches were built from them.
    if game.status != GAME_SCHEDULED:
        return

    registration = db.execute(
        select(Registration).where(
            Registration.game_id == game.id,
            Registration.membership_id == membership_id,
        )
    ).scalar_one_or_none()

    if registration is None:
        return

    was_participant = registration.status == REGISTRATION_PARTICIPANT

    db.delete(registration)
    db.flush()

    if was_participant:
        services.clear_teams(db, game.id)
        services.promote_waiting_players(db, game)


@app.delete("/groups/{group_id}/leave")
def leave_group(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    lock_group_or_404(db, group_id)

    membership = require_membership(db, group_id, user)
    memberships = services.load_memberships(db, group_id)

    if services.is_last_real_admin(memberships, membership):
        raise HTTPException(
            status_code=400,
            detail="Promote another member to admin before leaving",
        )

    _detach_from_active_game(db, group_id, membership.id)

    db.delete(membership)
    commit(db)

    return {"message": "Left group successfully"}


@app.post("/groups/{group_id}/members")
def add_virtual_member(
    group_id: UUID,
    request: MemberRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    if request.is_admin:
        # A virtual player has no account, so nobody can sign in as them. An
        # admin flag here only inflates the administrator count that the "last
        # admin" rule depends on.
        raise HTTPException(
            status_code=400,
            detail="Virtual players cannot be administrators",
        )

    membership = Membership(
        group_id=group_id,
        user_id=None,
        display_name=request.name,
        rating=request.rating,
        is_subscriber=request.is_subscriber,
        is_admin=False,
    )

    db.add(membership)
    commit(db)

    return services.serialize_member(membership, {})


@app.put("/groups/{group_id}/members/{membership_id}")
def update_member(
    group_id: UUID,
    membership_id: UUID,
    request: MemberRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    membership = target_membership_or_404(db, group_id, membership_id)
    memberships = services.load_memberships(db, group_id)

    if membership.user_id is None and request.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Virtual players cannot be administrators",
        )

    if (
        not request.is_admin
        and membership.is_admin
        and services.is_last_real_admin(memberships, membership)
    ):
        raise HTTPException(
            status_code=400,
            detail="Promote another member to admin before removing this one",
        )

    rating_changed = membership.rating != request.rating

    if membership.user_id is None:
        membership.display_name = request.name

    membership.rating = request.rating
    membership.is_subscriber = request.is_subscriber
    membership.is_admin = request.is_admin

    # Generated teams are balanced on ratings, so only a rating change to
    # somebody who is actually playing invalidates them.
    if rating_changed:
        game = services.get_active_game(db, group_id, lock=True)

        if game is not None and _is_participant(db, game.id, membership.id):
            services.clear_teams(db, game.id)

    commit(db)

    display_names = services.load_display_names(
        db, [membership.user_id] if membership.user_id else []
    )

    return services.serialize_member(membership, display_names)


def _is_participant(db: Session, game_id: UUID, membership_id: UUID) -> bool:
    return (
        db.execute(
            select(func.count())
            .select_from(Registration)
            .where(
                Registration.game_id == game_id,
                Registration.membership_id == membership_id,
                Registration.status == REGISTRATION_PARTICIPANT,
            )
        ).scalar_one()
        > 0
    )


@app.delete("/groups/{group_id}/members/{membership_id}")
def delete_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    membership = target_membership_or_404(db, group_id, membership_id)
    memberships = services.load_memberships(db, group_id)

    if services.is_last_real_admin(memberships, membership):
        raise HTTPException(
            status_code=400,
            detail="Promote another member to admin before removing this one",
        )

    _detach_from_active_game(db, group_id, membership.id)

    db.delete(membership)
    commit(db)

    return {"message": "Member deleted"}


@app.post("/groups/{group_id}/game")
def create_game(
    group_id: UUID,
    request: CreateGameRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game_datetime = request.game_datetime

    if game_datetime.tzinfo is None:
        game_datetime = game_datetime.replace(tzinfo=timezone.utc)

    if game_datetime <= services.now_utc():
        raise HTTPException(status_code=400, detail="Game must be in the future")

    # `get_open_game` rather than `get_active_game`: a scheduled day whose
    # kickoff has passed is no longer "active" but its row is still there, and
    # leaving it behind would mean the group had two open game days.
    existing = services.get_open_game(db, group_id, lock=True)

    if existing is not None:
        if existing.status == GAME_LIVE:
            raise HTTPException(
                status_code=409,
                detail="Finish the current Game Day before scheduling another",
            )

        db.delete(existing)
        db.flush()

    db.add(
        Game(
            group_id=group_id,
            game_datetime=game_datetime,
            regular_registration_opens=game_datetime
            - timedelta(hours=request.priority_hours),
        )
    )

    commit(db)

    return services.game_detail(db, group_id)


@app.delete("/groups/{group_id}/game")
def delete_game(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    lock_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = services.get_active_game(db, group_id, lock=True)

    if game is not None:
        db.delete(game)
        commit(db)

    return {"message": "Game deleted"}


@app.post("/groups/{group_id}/game/register/{membership_id}")
def register_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller = require_membership(db, group_id, user)

    target = target_membership_or_404(db, group_id, membership_id)

    if target.id != caller.id and not caller.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    # The lock is what makes the capacity check correct: without it two
    # requests both see eleven participants and both claim the twelfth slot.
    game = require_scheduled_game(db, group_id, lock=True)

    registrations = services.load_registrations(db, game.id)

    if any(item.membership_id == target.id for item in registrations):
        return services.game_detail(db, group_id)

    participants, _ = services.split_registrations(registrations)

    status = (
        REGISTRATION_PARTICIPANT
        if (
            len(participants) < MAX_GAME_PLAYERS
            and services.can_take_game_spot(game, target)
        )
        else REGISTRATION_WAITING
    )

    db.add(
        Registration(game_id=game.id, membership_id=target.id, status=status)
    )

    # Joining the waiting list does not change who is playing, so it must not
    # discard a line-up the admin has already generated.
    if status == REGISTRATION_PARTICIPANT:
        services.clear_teams(db, game.id)

    commit(db)

    return services.game_detail(db, group_id)


@app.post("/groups/{group_id}/game/unregister/{membership_id}")
def unregister_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller = require_membership(db, group_id, user)

    if membership_id != caller.id and not caller.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    game = require_scheduled_game(db, group_id, lock=True)

    _detach_from_active_game(db, group_id, membership_id, game)
    commit(db)

    return services.game_detail(db, group_id)


@app.post("/groups/{group_id}/generate-teams")
def generate_teams(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_scheduled_game(db, group_id, lock=True)

    registrations = services.load_registrations(db, game.id)
    participants, _ = services.split_registrations(registrations)

    if len(participants) != REQUIRED_PLAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Exactly {REQUIRED_PLAYERS} registered players are required",
        )

    memberships = {
        item.id: item for item in services.load_memberships(db, group_id)
    }

    players = [memberships[item.membership_id] for item in participants]

    services.clear_teams(db, game.id)
    db.flush()

    for team in generate_balanced_teams(players):
        for player in team.players:
            db.add(
                TeamAssignment(
                    game_id=game.id,
                    membership_id=player.id,
                    team_name=team.name,
                )
            )

    commit(db)

    display_names = services.load_display_names(
        db, [item.user_id for item in memberships.values() if item.user_id]
    )

    return services.serialize_teams(
        services.load_team_assignments(db, game.id), memberships, display_names
    )


@app.put("/groups/{group_id}/teams")
def update_teams(
    group_id: UUID,
    request: UpdateTeamsRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_scheduled_game(db, group_id, lock=True)

    registrations = services.load_registrations(db, game.id)
    participants, _ = services.split_registrations(registrations)

    if len(participants) != REQUIRED_PLAYERS:
        raise HTTPException(
            status_code=400,
            detail=f"Exactly {REQUIRED_PLAYERS} registered players are required",
        )

    expected = {item.membership_id for item in participants}
    requested = [item.membership_id for item in request.assignments]

    if len(requested) != len(expected) or set(requested) != expected:
        raise HTTPException(
            status_code=400,
            detail="Assignments must contain each registered player exactly once",
        )

    counts: dict[str, int] = {}

    for item in request.assignments:
        counts[item.team_name] = counts.get(item.team_name, 0) + 1

    team_size = REQUIRED_PLAYERS // 3

    if len(counts) != 3 or any(count != team_size for count in counts.values()):
        raise HTTPException(
            status_code=400,
            detail=f"Each team must contain exactly {team_size} players",
        )

    services.clear_teams(db, game.id)
    db.flush()

    for item in request.assignments:
        db.add(
            TeamAssignment(
                game_id=game.id,
                membership_id=item.membership_id,
                team_name=item.team_name,
            )
        )

    commit(db)

    memberships = {
        item.id: item for item in services.load_memberships(db, group_id)
    }
    display_names = services.load_display_names(
        db, [item.user_id for item in memberships.values() if item.user_id]
    )

    return services.serialize_teams(
        services.load_team_assignments(db, game.id), memberships, display_names
    )


# ---------------------------------------------------------------------------
# Game day: starting, playing and finishing
# ---------------------------------------------------------------------------


def _match_in_game(
    db: Session,
    game: Game,
    match_id: UUID,
    *,
    lock: bool = False,
) -> Match:
    match = (
        game_day.lock_match(db, match_id) if lock else db.get(Match, match_id)
    )

    if match is None or match.game_id != game.id:
        raise HTTPException(status_code=404, detail="Match not found")

    return match


@app.get("/groups/{group_id}/game-day")
def read_game_day(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """The current game day, or the one that just finished.

    Returns null only when the group has never played, so the frontend can
    decide between the registration screens, the live experience and the
    completion screen from a single request.
    """

    get_group_or_404(db, group_id)
    require_membership(db, group_id, user)

    game = services.get_latest_game_day(db, group_id)

    if game is None:
        return None

    return game_day.game_day_view(db, game, group_id)


@app.post("/groups/{group_id}/game/start")
def start_game_day(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Close registration and lay out the day's matches."""

    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_scheduled_game(db, group_id, lock=True)

    assignments = services.load_team_assignments(db, game.id)

    if len(assignments) != REQUIRED_PLAYERS:
        raise HTTPException(
            status_code=400,
            detail="Generate the teams before starting the Game Day",
        )

    teams = [
        name
        for name in TEAM_NAMES
        if any(item.team_name == name for item in assignments)
    ]

    game.status = GAME_LIVE
    game.started_at = services.now_utc()

    game_day.create_fixtures(db, game.id, teams)

    commit(db)

    return game_day.game_day_view(db, game, group_id)


@app.post("/groups/{group_id}/game/finish")
def finish_game_day(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Close the day, which fixes the standings and decides the champion.

    Finishing twice is not possible: a finished day is no longer the active one,
    so the second attempt reports that there is nothing in progress.
    """

    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_live_game(db, group_id, lock=True)

    matches = game_day.load_matches(db, game.id)
    outstanding = [item for item in matches if item.status != MATCH_COMPLETED]

    if outstanding:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(outstanding)} of {len(matches)} matches still need to "
                "be played"
            ),
        )

    game.status = GAME_FINISHED
    game.finished_at = services.now_utc()

    commit(db)

    return game_day.game_day_view(db, game, group_id)


@app.post("/groups/{group_id}/matches/{match_id}/start")
def start_match(
    group_id: UUID,
    match_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_live_game(db, group_id, lock=True)
    match = _match_in_game(db, game, match_id, lock=True)

    # Pressing kick-off twice is harmless rather than an error.
    if match.status == MATCH_LIVE:
        return game_day.game_day_view(db, game, group_id)

    if match.status == MATCH_COMPLETED:
        raise HTTPException(
            status_code=409, detail="That match has already been played"
        )

    if any(
        item.status == MATCH_LIVE
        for item in game_day.load_matches(db, game.id)
    ):
        raise HTTPException(
            status_code=409, detail="Finish the match in progress first"
        )

    match.status = MATCH_LIVE
    match.started_at = services.now_utc()

    commit(db)

    return game_day.game_day_view(db, game, group_id)


@app.post("/groups/{group_id}/matches/{match_id}/complete")
def complete_match(
    group_id: UUID,
    match_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_live_game(db, group_id, lock=True)
    match = _match_in_game(db, game, match_id, lock=True)

    if match.status == MATCH_COMPLETED:
        return game_day.game_day_view(db, game, group_id)

    if match.status != MATCH_LIVE:
        raise HTTPException(
            status_code=409, detail="That match has not kicked off yet"
        )

    match.status = MATCH_COMPLETED
    match.completed_at = services.now_utc()

    commit(db)

    return game_day.game_day_view(db, game, group_id)


@app.post("/groups/{group_id}/matches/{match_id}/goals")
def add_goal(
    group_id: UUID,
    match_id: UUID,
    request: AddGoalRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Record a goal for one of the two teams playing this match.

    The scorer and the assisting player must both be in the scoring team's
    line-up for this game day, which is what stops the goal dialog from
    crediting somebody who is not on the pitch.
    """

    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_live_game(db, group_id, lock=True)
    match = _match_in_game(db, game, match_id, lock=True)

    if match.status != MATCH_LIVE:
        raise HTTPException(
            status_code=409,
            detail="Goals can only be recorded while the match is in progress",
        )

    if request.team_name not in (match.home_team, match.away_team):
        raise HTTPException(
            status_code=400, detail="That team is not playing in this match"
        )

    team_of = {
        item.membership_id: item.team_name
        for item in services.load_team_assignments(db, game.id)
    }

    if team_of.get(request.scorer_membership_id) != request.team_name:
        raise HTTPException(
            status_code=400,
            detail="The scorer is not playing for that team",
        )

    if (
        request.assist_membership_id is not None
        and team_of.get(request.assist_membership_id) != request.team_name
    ):
        raise HTTPException(
            status_code=400,
            detail="The assisting player is not playing for that team",
        )

    db.add(
        MatchGoal(
            match_id=match.id,
            team_name=request.team_name,
            scorer_membership_id=request.scorer_membership_id,
            assist_membership_id=request.assist_membership_id,
        )
    )

    commit(db)

    return game_day.game_day_view(db, game, group_id)


@app.delete("/groups/{group_id}/matches/{match_id}/goals/{goal_id}")
def remove_goal(
    group_id: UUID,
    match_id: UUID,
    goal_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Undo a mistyped goal while the match is still being played."""

    get_group_or_404(db, group_id)
    require_admin(db, group_id, user)

    game = require_live_game(db, group_id, lock=True)
    match = _match_in_game(db, game, match_id, lock=True)

    if match.status != MATCH_LIVE:
        raise HTTPException(
            status_code=409,
            detail="A completed match can no longer be edited",
        )

    goal = db.get(MatchGoal, goal_id)

    if goal is None or goal.match_id != match.id:
        raise HTTPException(status_code=404, detail="Goal not found")

    db.delete(goal)
    commit(db)

    return game_day.game_day_view(db, game, group_id)


# ---------------------------------------------------------------------------
# Statistics, history and the rating survey
# ---------------------------------------------------------------------------


@app.get("/groups/{group_id}/statistics")
def read_statistics(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Accumulated statistics across every finished game day.

    Deliberately separate from the game day's own statistics so that today's
    numbers are never mixed into the running totals.
    """

    get_group_or_404(db, group_id)
    require_membership(db, group_id, user)

    return game_day.overall_statistics(db, group_id)


@app.get("/groups/{group_id}/history")
def read_history(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    require_membership(db, group_id, user)

    return game_day.history(db, group_id)


@app.get("/groups/{group_id}/survey")
def read_survey(
    group_id: UUID,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    """Every other member, plus whatever the caller rated them last time.

    Only the caller's own answers are returned. Nobody can read who rated whom;
    the aggregate average is all that is ever published, in the statistics.
    """

    get_group_or_404(db, group_id)
    membership = require_membership(db, group_id, user)

    return game_day.survey_view(db, group_id, membership)


@app.put("/groups/{group_id}/survey")
def submit_survey(
    group_id: UUID,
    request: SaveSurveyRequest,
    user: CurrentUser = Depends(acting_user),
    db: Session = Depends(get_db),
):
    get_group_or_404(db, group_id)
    membership = require_membership(db, group_id, user)

    game_day.save_survey(
        db,
        group_id,
        membership,
        {item.membership_id: item.rating for item in request.ratings},
    )

    commit(db)

    return game_day.survey_view(db, group_id, membership)


if settings.enable_dev_endpoints:
    from backend.dev_routes import router as dev_router

    logger.warning(
        "Development endpoints are enabled. Never do this in a deployed "
        "environment: they delete registrations, virtual members and games."
    )
    app.include_router(dev_router)
