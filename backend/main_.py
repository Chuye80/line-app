from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import (
    Game,
    Group,
    JoinRequest,
    Membership,
    Profile,
    Registration,
    TeamAssignment,
)
from backend.team_generator import generate_balanced_teams


MAX_GAME_PLAYERS = 12

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")

if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be set in .env"
    )


app = FastAPI(title="LineApp API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CurrentUser(BaseModel):
    id: UUID
    email: str | None = None


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1)


class CreateGameRequest(BaseModel):
    game_datetime: datetime
    priority_hours: int = Field(ge=0, le=168)


class CreateMemberRequest(BaseModel):
    name: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False


class UpdateMemberRequest(BaseModel):
    name: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False


class TeamAssignmentRequest(BaseModel):
    membership_id: UUID
    team_name: str


class UpdateTeamsRequest(BaseModel):
    assignments: list[TeamAssignmentRequest]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_current_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.split(" ", 1)[1].strip()

    request = Request(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {token}",
            "apikey": SUPABASE_PUBLISHABLE_KEY,
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to verify Supabase session") from exc

    return CurrentUser(
        id=UUID(data["id"]),
        email=data.get("email"),
    )


def get_group_or_404(
    db: Session,
    group_id: UUID,
) -> Group:
    group = db.get(Group, group_id)

    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    return group


def profile_name(
    db: Session,
    user_id: UUID,
) -> str:
    profile = db.get(Profile, user_id)
    return profile.display_name if profile else "Player"


def membership_name(
    db: Session,
    membership: Membership,
) -> str:
    if membership.user_id is not None:
        return profile_name(db, membership.user_id)

    return membership.display_name or "Virtual Player"


def membership_for_user(
    db: Session,
    group_id: UUID,
    user_id: UUID,
) -> Membership | None:
    return (
        db.query(Membership)
        .filter(
            Membership.group_id == group_id,
            Membership.user_id == user_id,
        )
        .first()
    )


def require_membership(
    db: Session,
    group: Group,
    user: CurrentUser,
) -> Membership:
    membership = membership_for_user(db, group.id, user.id)

    if membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group")

    return membership


def require_admin(
    db: Session,
    group: Group,
    user: CurrentUser,
) -> Membership:
    membership = require_membership(db, group, user)

    if not membership.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    return membership


def get_active_game(
    db: Session,
    group: Group,
) -> Game | None:
    game = (
        db.query(Game)
        .filter(Game.group_id == group.id)
        .order_by(Game.game_datetime.desc())
        .first()
    )

    if game is None:
        return None

    if now_utc() >= game.game_datetime:
        db.delete(game)
        db.commit()
        return None

    return game


def participant_registrations(game: Game) -> list[Registration]:
    return sorted(
        [
            item
            for item in game.registrations
            if item.status == "participant"
        ],
        key=lambda item: item.created_at,
    )


def waiting_registrations(game: Game) -> list[Registration]:
    return sorted(
        [
            item
            for item in game.registrations
            if item.status == "waiting"
        ],
        key=lambda item: item.created_at,
    )


def is_priority_period(game: Game) -> bool:
    return now_utc() < game.regular_registration_opens


def can_take_game_spot(
    game: Game,
    membership: Membership,
) -> bool:
    if is_priority_period(game):
        return membership.is_subscriber

    return True


def clear_teams(
    db: Session,
    game: Game,
) -> None:
    for assignment in list(game.team_assignments):
        db.delete(assignment)


def promote_waiting_players(
    db: Session,
    game: Game,
) -> None:
    changed = False

    while len(participant_registrations(game)) < MAX_GAME_PLAYERS:
        waiting = waiting_registrations(game)

        if not waiting:
            break

        promoted = next(
            (
                item
                for item in waiting
                if can_take_game_spot(game, item.membership)
            ),
            None,
        )

        if promoted is None:
            break

        promoted.status = "participant"
        changed = True

    if changed:
        clear_teams(db, game)
        db.commit()


def membership_to_dict(
    db: Session,
    membership: Membership,
) -> dict:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id) if membership.user_id else None,
        "name": membership_name(db, membership),
        "rating": membership.rating,
        "is_subscriber": membership.is_subscriber,
        "is_admin": membership.is_admin,
        "is_virtual": membership.user_id is None,
    }


def game_to_dict(
    db: Session,
    game: Game,
) -> dict:
    return {
        "game_datetime": game.game_datetime,
        "regular_registration_opens": game.regular_registration_opens,
        "participants": [
            membership_to_dict(db, item.membership)
            for item in participant_registrations(game)
        ],
        "waiting_list": [
            membership_to_dict(db, item.membership)
            for item in waiting_registrations(game)
        ],
    }


def teams_to_dict(
    db: Session,
    game: Game,
) -> list[dict]:
    result = []

    for team_name in ("Team A", "Team B", "Team C"):
        assignments = [
            item
            for item in game.team_assignments
            if item.team_name == team_name
        ]

        if not assignments:
            continue

        memberships = [item.membership for item in assignments]
        total = sum(item.rating for item in memberships)

        result.append(
            {
                "name": team_name,
                "players": [
                    membership_to_dict(db, membership)
                    for membership in memberships
                ],
                "total_rating": total,
                "average_rating": total / len(memberships),
            }
        )

    return result


def group_to_dict(
    db: Session,
    group: Group,
) -> dict:
    game = get_active_game(db, group)

    if game is not None:
        promote_waiting_players(db, game)

    return {
        "id": str(group.id),
        "name": group.name,
        "members": [
            membership_to_dict(db, membership)
            for membership in group.memberships
        ],
        "game": game_to_dict(db, game) if game else None,
        "teams": teams_to_dict(db, game) if game else [],
    }


@app.get("/")
def root():
    return {"message": "LineApp backend is running on Supabase/PostgreSQL"}


@app.get("/me")
def me(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": profile_name(db, user.id),
    }


@app.get("/groups")
def get_groups(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    groups = db.query(Group).order_by(Group.created_at.desc()).all()
    return [
        {
            "id": str(group.id),
            "name": group.name,
        }
        for group in groups
    ]


@app.get("/my-groups")
def get_my_groups(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == user.id)
        .order_by(Membership.created_at)
        .all()
    )

    return [
        {
            "id": str(item.group.id),
            "name": item.group.name,
            "membership_id": str(item.id),
            "is_admin": item.is_admin,
            "is_subscriber": item.is_subscriber,
            "rating": item.rating,
        }
        for item in memberships
    ]


@app.post("/groups")
def create_group(
    request: CreateGroupRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = Group(
        name=request.name.strip(),
        created_by=user.id,
    )

    db.add(group)
    db.flush()

    membership = Membership(
        group_id=group.id,
        user_id=user.id,
        rating=3,
        is_subscriber=False,
        is_admin=True,
    )

    db.add(membership)
    db.commit()
    db.refresh(group)

    return group_to_dict(db, group)


@app.get("/groups/{group_id}")
def get_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    return group_to_dict(db, group)


@app.get("/groups/{group_id}/membership-status")
def get_membership_status(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    membership = membership_for_user(db, group.id, user.id)

    if membership is not None:
        return {
            "state": "member",
            "membership_id": str(membership.id),
            "is_admin": membership.is_admin,
        }

    request = (
        db.query(JoinRequest)
        .filter(
            JoinRequest.group_id == group.id,
            JoinRequest.user_id == user.id,
        )
        .order_by(JoinRequest.created_at.desc())
        .first()
    )

    return {
        "state": request.status if request else "none",
        "membership_id": None,
        "is_admin": False,
    }


@app.post("/groups/{group_id}/join-request")
def request_to_join(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)

    if membership_for_user(db, group.id, user.id):
        raise HTTPException(status_code=400, detail="You are already a member")

    existing = (
        db.query(JoinRequest)
        .filter(
            JoinRequest.group_id == group.id,
            JoinRequest.user_id == user.id,
            JoinRequest.status == "pending",
        )
        .first()
    )

    if existing:
        return {"message": "Request already pending"}

    db.add(
        JoinRequest(
            group_id=group.id,
            user_id=user.id,
            status="pending",
        )
    )
    db.commit()

    return {"message": "Join request submitted"}


@app.get("/groups/{group_id}/join-requests")
def pending_join_requests(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    requests = (
        db.query(JoinRequest)
        .filter(
            JoinRequest.group_id == group.id,
            JoinRequest.status == "pending",
        )
        .order_by(JoinRequest.created_at)
        .all()
    )

    return [
        {
            "id": str(item.id),
            "user_id": str(item.user_id),
            "user_name": profile_name(db, item.user_id),
            "status": item.status,
        }
        for item in requests
    ]


@app.post("/groups/{group_id}/join-requests/{request_id}/approve")
def approve_join_request(
    group_id: UUID,
    request_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    request = db.get(JoinRequest, request_id)

    if (
        request is None
        or request.group_id != group.id
        or request.status != "pending"
    ):
        raise HTTPException(status_code=404, detail="Pending request not found")

    if membership_for_user(db, group.id, request.user_id) is None:
        db.add(
            Membership(
                group_id=group.id,
                user_id=request.user_id,
                rating=3,
                is_subscriber=False,
                is_admin=False,
            )
        )

    request.status = "approved"
    db.commit()

    return {"message": "Join request approved"}


@app.post("/groups/{group_id}/join-requests/{request_id}/decline")
def decline_join_request(
    group_id: UUID,
    request_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    request = db.get(JoinRequest, request_id)

    if (
        request is None
        or request.group_id != group.id
        or request.status != "pending"
    ):
        raise HTTPException(status_code=404, detail="Pending request not found")

    request.status = "declined"
    db.commit()

    return {"message": "Join request declined"}


@app.delete("/groups/{group_id}/leave")
def leave_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(db, group, user)

    if membership.is_admin:
        admin_count = (
            db.query(Membership)
            .filter(
                Membership.group_id == group.id,
                Membership.is_admin.is_(True),
            )
            .count()
        )

        if admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Promote another member to admin before leaving",
            )

    game = get_active_game(db, group)

    if game:
        registration = (
            db.query(Registration)
            .filter(
                Registration.game_id == game.id,
                Registration.membership_id == membership.id,
            )
            .first()
        )

        if registration:
            db.delete(registration)

        clear_teams(db, game)

    db.delete(membership)
    db.commit()

    if game:
        promote_waiting_players(db, game)

    return {"message": "Left group successfully"}


@app.post("/groups/{group_id}/members")
def add_virtual_member(
    group_id: UUID,
    request: CreateMemberRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    membership = Membership(
        group_id=group.id,
        user_id=None,
        display_name=request.name.strip(),
        rating=request.rating,
        is_subscriber=request.is_subscriber,
        is_admin=request.is_admin,
    )

    db.add(membership)
    db.commit()
    db.refresh(membership)

    return membership_to_dict(db, membership)


@app.put("/groups/{group_id}/members/{membership_id}")
def update_member(
    group_id: UUID,
    membership_id: UUID,
    request: UpdateMemberRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    membership = db.get(Membership, membership_id)

    if membership is None or membership.group_id != group.id:
        raise HTTPException(status_code=404, detail="Member not found")

    if membership.user_id is None:
        membership.display_name = request.name.strip()

    membership.rating = request.rating
    membership.is_subscriber = request.is_subscriber
    membership.is_admin = request.is_admin

    game = get_active_game(db, group)
    if game:
        clear_teams(db, game)

    db.commit()

    return membership_to_dict(db, membership)


@app.delete("/groups/{group_id}/members/{membership_id}")
def delete_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    membership = db.get(Membership, membership_id)

    if membership is None or membership.group_id != group.id:
        raise HTTPException(status_code=404, detail="Member not found")

    game = get_active_game(db, group)

    if game:
        registration = (
            db.query(Registration)
            .filter(
                Registration.game_id == game.id,
                Registration.membership_id == membership.id,
            )
            .first()
        )

        if registration:
            db.delete(registration)

        clear_teams(db, game)

    db.delete(membership)
    db.commit()

    if game:
        promote_waiting_players(db, game)

    return {"message": "Member deleted"}


@app.post("/groups/{group_id}/game")
def create_game(
    group_id: UUID,
    request: CreateGameRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game_datetime = request.game_datetime

    if game_datetime.tzinfo is None:
        game_datetime = game_datetime.replace(tzinfo=timezone.utc)

    if game_datetime <= now_utc():
        raise HTTPException(status_code=400, detail="Game must be in the future")

    old_game = get_active_game(db, group)

    if old_game:
        db.delete(old_game)
        db.commit()

    game = Game(
        group_id=group.id,
        game_datetime=game_datetime,
        regular_registration_opens=game_datetime - timedelta(hours=request.priority_hours),
    )

    db.add(game)
    db.commit()
    db.refresh(game)

    return game_to_dict(db, game)


@app.delete("/groups/{group_id}/game")
def delete_game(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game = get_active_game(db, group)

    if game:
        db.delete(game)
        db.commit()

    return {"message": "Game deleted"}


@app.post("/groups/{group_id}/game/register/{membership_id}")
def register_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller_membership = require_membership(db, group, user)

    target = db.get(Membership, membership_id)

    if target is None or target.group_id != group.id:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.id != caller_membership.id and not caller_membership.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="No active game")

    existing = (
        db.query(Registration)
        .filter(
            Registration.game_id == game.id,
            Registration.membership_id == target.id,
        )
        .first()
    )

    if existing:
        return game_to_dict(db, game)

    status = (
        "participant"
        if (
            len(participant_registrations(game)) < MAX_GAME_PLAYERS
            and can_take_game_spot(game, target)
        )
        else "waiting"
    )

    db.add(
        Registration(
            game_id=game.id,
            membership_id=target.id,
            status=status,
        )
    )

    clear_teams(db, game)
    db.commit()

    return game_to_dict(db, game)


@app.post("/groups/{group_id}/game/unregister/{membership_id}")
def unregister_member(
    group_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller_membership = require_membership(db, group, user)

    if membership_id != caller_membership.id and not caller_membership.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="No active game")

    registration = (
        db.query(Registration)
        .filter(
            Registration.game_id == game.id,
            Registration.membership_id == membership_id,
        )
        .first()
    )

    if registration:
        db.delete(registration)
        clear_teams(db, game)
        db.commit()
        promote_waiting_players(db, game)

    return game_to_dict(db, game)


@app.post("/groups/{group_id}/generate-teams")
def generate_teams(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="No active game")

    registrations = participant_registrations(game)

    if len(registrations) != MAX_GAME_PLAYERS:
        raise HTTPException(
            status_code=400,
            detail="Exactly 12 registered players are required",
        )

    memberships = [item.membership for item in registrations]

    generated = generate_balanced_teams(memberships)

    clear_teams(db, game)

    for team in generated:
        for membership in team.players:
            db.add(
                TeamAssignment(
                    game_id=game.id,
                    membership_id=membership.id,
                    team_name=team.name,
                )
            )

    db.commit()

    return teams_to_dict(db, game)


@app.put("/groups/{group_id}/teams")
def update_teams(
    group_id: UUID,
    request: UpdateTeamsRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="No active game")

    registrations = participant_registrations(game)

    if len(registrations) != MAX_GAME_PLAYERS:
        raise HTTPException(status_code=400, detail="Exactly 12 registered players are required")

    valid_ids = {item.membership_id for item in registrations}
    requested_ids = [item.membership_id for item in request.assignments]

    if len(requested_ids) != 12 or set(requested_ids) != valid_ids:
        raise HTTPException(
            status_code=400,
            detail="Assignments must contain each registered player exactly once",
        )

    counts = {"Team A": 0, "Team B": 0, "Team C": 0}

    for item in request.assignments:
        if item.team_name not in counts:
            raise HTTPException(status_code=400, detail="Invalid team name")
        counts[item.team_name] += 1

    if any(count != 4 for count in counts.values()):
        raise HTTPException(status_code=400, detail="Each team must contain exactly 4 players")

    clear_teams(db, game)

    for item in request.assignments:
        db.add(
            TeamAssignment(
                game_id=game.id,
                membership_id=item.membership_id,
                team_name=item.team_name,
            )
        )

    db.commit()

    return teams_to_dict(db, game)


# -------- Development helpers, still authenticated/admin-only --------

TEST_MEMBERS = [
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


@app.post("/dev/groups/{group_id}/add-test-members")
def dev_add_test_members(
    group_id: UUID,
    count: int = 16,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    if count not in (12, 16):
        raise HTTPException(status_code=400, detail="count must be 12 or 16")

    existing_virtual = [
        item
        for item in group.memberships
        if item.user_id is None
    ]

    for item in existing_virtual:
        db.delete(item)

    db.commit()

    real_count = (
        db.query(Membership)
        .filter(
            Membership.group_id == group.id,
            Membership.user_id.is_not(None),
        )
        .count()
    )

    needed = max(0, count - real_count)

    for name, rating, subscriber in TEST_MEMBERS[:needed]:
        db.add(
            Membership(
                group_id=group.id,
                display_name=name,
                rating=rating,
                is_subscriber=subscriber,
                is_admin=False,
            )
        )

    db.commit()

    return group_to_dict(db, group)


@app.post("/dev/groups/{group_id}/create-game")
def dev_create_game(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    old_game = get_active_game(db, group)

    if old_game:
        db.delete(old_game)
        db.commit()

    game = Game(
        group_id=group.id,
        game_datetime=now_utc() + timedelta(hours=2),
        regular_registration_opens=now_utc() + timedelta(minutes=1),
    )

    db.add(game)
    db.commit()
    db.refresh(game)

    return game_to_dict(db, game)


@app.post("/dev/groups/{group_id}/register-all")
def dev_register_all(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="Create a game first")

    for item in list(game.registrations):
        db.delete(item)

    db.commit()

    for membership in group.memberships:
        current_count = (
            db.query(Registration)
            .filter(
                Registration.game_id == game.id,
                Registration.status == "participant",
            )
            .count()
        )

        status = (
            "participant"
            if (
                current_count < MAX_GAME_PLAYERS
                and can_take_game_spot(game, membership)
            )
            else "waiting"
        )

        db.add(
            Registration(
                game_id=game.id,
                membership_id=membership.id,
                status=status,
            )
        )
        db.flush()

    db.commit()

    return game_to_dict(db, game)


@app.post("/dev/groups/{group_id}/expire-priority")
def dev_expire_priority(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    game = get_active_game(db, group)

    if game is None:
        raise HTTPException(status_code=400, detail="Create a game first")

    game.regular_registration_opens = now_utc() - timedelta(seconds=1)
    db.commit()
    promote_waiting_players(db, game)

    return game_to_dict(db, game)
