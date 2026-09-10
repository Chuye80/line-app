from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy import func, text

from backend.database import get_db, read_engine
from backend.models import (
    Developer,
    GameDay,
    GameDayAward,
    Group,
    JoinRequest,
    Match,
    MatchGoal,
    MatchPlayer,
    Membership,
    MvpVote,
    Profile,
    RatingSurvey,
    RatingSurveyResponse,
    Registration,
    TeamAssignment,
)
from backend.team_generator import generate_balanced_teams


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")
LOCAL_FRONTEND_URL = "http://127.0.0.1:5173"
HOSTED_FRONTEND_URL = "https://line-app-cyan.vercel.app"
default_frontend_url = (
    HOSTED_FRONTEND_URL if os.getenv("RAILWAY_PUBLIC_DOMAIN") else LOCAL_FRONTEND_URL
)
FRONTEND_URL = os.getenv("FRONTEND_URL", default_frontend_url).rstrip("/")
ENABLE_DEV_ENDPOINTS = os.getenv("ENABLE_DEV_ENDPOINTS", "").lower() in {
    "1",
    "true",
    "yes",
}

if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
    raise RuntimeError(
        "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY must be set in .env"
    )


app = FastAPI(title="LineApp API")

cors_origins = [
    "http://localhost:5173",
    LOCAL_FRONTEND_URL,
    HOSTED_FRONTEND_URL,
]
if FRONTEND_URL not in cors_origins:
    cors_origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CurrentUser(BaseModel):
    id: UUID
    email: str | None = None


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1)


class CreateGameDayRequest(BaseModel):
    game_datetime: datetime
    priority_hours: int = Field(ge=0, le=168)
    participant_count: int = Field(ge=2, le=40)
    players_per_team: int = Field(ge=2, le=11)


class CreateMemberRequest(BaseModel):
    name: str = Field(min_length=1)
    rating: float = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False


class UpdateMemberRequest(BaseModel):
    name: str = Field(min_length=1)
    rating: float = Field(ge=1, le=5)
    is_subscriber: bool = False
    is_admin: bool = False


class TransferAdminAndLeaveRequest(BaseModel):
    target_membership_id: UUID


class JoinWithInviteRequest(BaseModel):
    invite_code: str = Field(min_length=1)


class TeamAssignmentItem(BaseModel):
    membership_id: UUID
    team_name: str | None = None


class UpdateTeamsRequest(BaseModel):
    assignments: list[TeamAssignmentItem]


class CreateMatchRequest(BaseModel):
    home_team_name: str
    away_team_name: str


class CompleteMatchRequest(BaseModel):
    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    goals: list["GoalItem"] = []


class GoalItem(BaseModel):
    scorer_membership_id: UUID
    assist_membership_id: UUID | None = None


class MvpVoteRequest(BaseModel):
    nominee_membership_id: UUID


class SurveyRatingsRequest(BaseModel):
    ratings: dict[str, float]


_AUTH_CACHE: dict[str, tuple[float, CurrentUser]] = {}
_AUTH_CACHE_TTL_SECONDS = 45.0
_AUTH_LOCKS: dict[str, threading.Lock] = {}
_AUTH_LOCKS_GUARD = threading.Lock()


def _token_lock(token: str) -> threading.Lock:
    with _AUTH_LOCKS_GUARD:
        lock = _AUTH_LOCKS.get(token)
        if lock is None:
            lock = threading.Lock()
            _AUTH_LOCKS[token] = lock
        return lock


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_invite_code() -> str:
    return secrets.token_hex(6)


def is_real(membership: Membership) -> bool:
    return membership.user_id is not None


def get_authenticated_user(
    authorization: str | None = Header(default=None),
) -> CurrentUser:
    """The account that actually signed in. Never affected by simulation."""

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.split(" ", 1)[1].strip()
    with _token_lock(token):
        now = time.monotonic()
        cached = _AUTH_CACHE.get(token)
        if cached and cached[0] > now:
            return cached[1]

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
            _AUTH_CACHE.pop(token, None)
            raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Unable to verify Supabase session") from exc

        user = CurrentUser(id=UUID(data["id"]), email=data.get("email"))
        _AUTH_CACHE[token] = (now + _AUTH_CACHE_TTL_SECONDS, user)
        if len(_AUTH_CACHE) > 256:
            expired = [key for key, value in _AUTH_CACHE.items() if value[0] <= now]
            for key in expired:
                _AUTH_CACHE.pop(key, None)
        return user


def get_current_user(
    real_user: CurrentUser = Depends(get_authenticated_user),
    x_dev_act_as: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """The account the request should be answered as.

    Developers can ask to see the app through another member's eyes by sending
    that member's id in `X-Dev-Act-As`. Nothing about the real session changes:
    the token, its cache entry and the developer's own account are untouched,
    and the substitution lasts exactly one request. Because every endpoint
    already depends on this function, the simulation applies everywhere at once
    instead of each endpoint having to know about it.
    """

    if not x_dev_act_as:
        return real_user
    if not is_developer(db, real_user.id):
        raise HTTPException(status_code=403, detail="Developer access required")
    try:
        membership_id = UUID(x_dev_act_as)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="X-Dev-Act-As must be a membership id"
        ) from exc
    membership = db.get(Membership, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    if membership.user_id is None:
        raise HTTPException(
            status_code=400,
            detail="A virtual player has no account to view the app as",
        )
    return CurrentUser(id=membership.user_id, email=None)


def is_developer(db: Session, user_id: UUID) -> bool:
    return db.get(Developer, user_id) is not None


def require_developer(db: Session, user: CurrentUser) -> None:
    if not ENABLE_DEV_ENDPOINTS:
        # Do not advertise remotely disabled test helpers through a 403.
        raise HTTPException(status_code=404, detail="Not found")
    if not is_developer(db, user.id):
        raise HTTPException(status_code=403, detail="Developer access required")


def get_group_or_404(db: Session, group_id: UUID) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


def profile_names(db: Session, user_ids: list[UUID]) -> dict[UUID, str]:
    if not user_ids:
        return {}
    rows = db.query(Profile).filter(Profile.id.in_(user_ids)).all()
    return {row.id: row.display_name for row in rows}


def profile_name(
    db: Session,
    user_id: UUID,
    cache: dict[UUID, str] | None = None,
) -> str:
    if cache is not None and user_id in cache:
        return cache[user_id]
    profile = db.get(Profile, user_id)
    return profile.display_name if profile else "Player"


def membership_name(
    db: Session,
    membership: Membership,
    cache: dict[UUID, str] | None = None,
) -> str:
    if membership.user_id is not None:
        return profile_name(db, membership.user_id, cache)
    return membership.display_name or "Virtual Player"


def membership_for_user(db: Session, group_id: UUID, user_id: UUID) -> Membership | None:
    return (
        db.query(Membership)
        .filter(Membership.group_id == group_id, Membership.user_id == user_id)
        .first()
    )


def require_membership(db: Session, group: Group, user: CurrentUser) -> Membership:
    membership = membership_for_user(db, group.id, user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this group")
    return membership


def require_admin(db: Session, group: Group, user: CurrentUser) -> Membership:
    membership = require_membership(db, group, user)
    if not membership.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")
    return membership


def admin_count(db: Session, group_id: UUID) -> int:
    return (
        db.query(Membership)
        .filter(
            Membership.group_id == group_id,
            Membership.is_admin.is_(True),
            Membership.user_id.is_not(None),
        )
        .count()
    )


def ensure_not_last_admin(db: Session, membership: Membership) -> None:
    if membership.is_admin and is_real(membership) and admin_count(db, membership.group_id) <= 1:
        raise HTTPException(
            status_code=400,
            detail="A group must keep at least one admin",
        )


def participant_registrations(game_day: GameDay) -> list[Registration]:
    return sorted(
        [item for item in game_day.registrations if item.status == "participant"],
        key=lambda item: item.created_at,
    )


def waiting_registrations(game_day: GameDay) -> list[Registration]:
    return sorted(
        [item for item in game_day.registrations if item.status == "waiting"],
        key=lambda item: item.created_at,
    )


def participant_count_db(db: Session, game_day_id: UUID) -> int:
    return (
        db.query(Registration)
        .filter(
            Registration.game_day_id == game_day_id,
            Registration.status == "participant",
        )
        .count()
    )


def is_priority_period(game_day: GameDay) -> bool:
    return now_utc() < as_utc(game_day.regular_registration_opens)


def can_take_game_spot(game_day: GameDay, membership: Membership) -> bool:
    if is_priority_period(game_day):
        return bool(membership.is_subscriber)
    return True


def registration_status_for(
    db: Session,
    game_day: GameDay,
    membership: Membership,
) -> str:
    if is_priority_period(game_day) and not bool(membership.is_subscriber):
        return "waiting"
    occupied = (
        len(participant_registrations(game_day))
        if "registrations" in game_day.__dict__
        else participant_count_db(db, game_day.id)
    )
    if occupied < game_day.participant_count:
        return "participant"
    return "waiting"


def clear_teams(db: Session, game_day: GameDay) -> None:
    for assignment in list(game_day.team_assignments):
        db.delete(assignment)


def promote_waiting_players(db: Session, game_day: GameDay) -> None:
    changed = False

    while len(participant_registrations(game_day)) < game_day.participant_count:
        waiting = waiting_registrations(game_day)
        if not waiting:
            break

        promoted = next(
            (
                item
                for item in waiting
                if can_take_game_spot(game_day, item.membership)
            ),
            None,
        )
        if promoted is None:
            break

        promoted.status = "participant"
        changed = True

    if changed:
        clear_teams(db, game_day)
        db.commit()


def sync_game_day_status(db: Session, game_day: GameDay) -> GameDay:
    if game_day.status == "upcoming" and now_utc() >= as_utc(game_day.game_datetime):
        game_day.status = "live"
        db.commit()
    return game_day


def current_game_day(db: Session, group: Group) -> GameDay | None:
    insp = group.__dict__
    if "game_days" in insp:
        candidates = [
            item
            for item in group.game_days
            if item.status in ("upcoming", "live")
        ]
        candidates.sort(key=lambda item: item.game_datetime, reverse=True)
        game_day = candidates[0] if candidates else None
    else:
        game_day = (
            db.query(GameDay)
            .filter(
                GameDay.group_id == group.id,
                GameDay.status.in_(("upcoming", "live")),
            )
            .order_by(GameDay.game_datetime.desc())
            .first()
        )
    if game_day is None:
        return None
    return sync_game_day_status(db, game_day)


def load_group_view(db: Session, group_id: UUID) -> Group | None:
    return (
        db.query(Group)
        .options(
            selectinload(Group.memberships),
            selectinload(Group.game_days),
        )
        .filter(Group.id == group_id)
        .first()
    )


def membership_to_dict(
    db: Session,
    membership: Membership,
    cache: dict[UUID, str] | None = None,
) -> dict:
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id) if membership.user_id else None,
        "name": membership_name(db, membership, cache),
        "rating": float(membership.rating),
        "is_subscriber": bool(membership.is_subscriber),
        "is_admin": membership.is_admin,
        "is_virtual": membership.user_id is None,
    }


def team_totals(game_day: GameDay) -> dict[str, list[Membership]]:
    buckets: dict[str, list[Membership]] = defaultdict(list)
    unassigned: list[Membership] = []
    for item in game_day.team_assignments:
        if item.team_name:
            buckets[item.team_name].append(item.membership)
        else:
            unassigned.append(item.membership)
    buckets["_unassigned"] = unassigned
    return buckets


def teams_to_dict(
    db: Session,
    game_day: GameDay,
    cache: dict[UUID, str] | None = None,
) -> dict:
    buckets = team_totals(game_day)
    unassigned = buckets.pop("_unassigned", [])
    named = []
    for name in sorted(buckets.keys()):
        memberships = buckets[name]
        total = sum(float(item.rating) for item in memberships)
        named.append(
            {
                "name": name,
                "players": [membership_to_dict(db, item, cache) for item in memberships],
                "total_rating": round(total, 1),
                "average_rating": round(total / len(memberships), 2) if memberships else 0,
            }
        )
    complete_teams = game_day.participant_count // game_day.players_per_team
    leftover = game_day.participant_count % game_day.players_per_team
    return {
        "teams": named,
        "unassigned": [membership_to_dict(db, item, cache) for item in unassigned],
        "complete_teams": complete_teams,
        "leftover_players": leftover,
        "is_rotating": game_day.is_rotating,
    }


def standings_for(game_day: GameDay) -> list[dict]:
    team_names = sorted(
        {
            item.team_name
            for item in game_day.team_assignments
            if item.team_name
        }
    )
    table = {
        name: {
            "name": name,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        }
        for name in team_names
    }
    completed = [item for item in game_day.matches if item.status == "completed"]
    head_to_head: dict[tuple[str, str], int] = defaultdict(int)

    for match in completed:
        home = table.get(match.home_team_name)
        away = table.get(match.away_team_name)
        if home is None or away is None:
            continue
        home_score = match.home_score or 0
        away_score = match.away_score or 0
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_score
        home["goals_against"] += away_score
        away["goals_for"] += away_score
        away["goals_against"] += home_score
        if home_score > away_score:
            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1
            head_to_head[(match.home_team_name, match.away_team_name)] += 3
        elif away_score > home_score:
            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1
            head_to_head[(match.away_team_name, match.home_team_name)] += 3
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1
            head_to_head[(match.home_team_name, match.away_team_name)] += 1
            head_to_head[(match.away_team_name, match.home_team_name)] += 1

    rows = []
    for row in table.values():
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
        rows.append(row)

    def sort_key(row: dict) -> tuple:
        others = [item["name"] for item in rows if item is not row]
        h2h = sum(head_to_head[(row["name"], other)] for other in others)
        return (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            -h2h,
            row["name"],
        )

    rows.sort(key=sort_key)
    return rows


def standings_from_payload(game_day: dict) -> list[dict]:
    team_names = sorted(team["name"] for team in game_day.get("teams") or [])
    table = {
        name: {
            "name": name,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        }
        for name in team_names
    }
    head_to_head: dict[tuple[str, str], int] = defaultdict(int)
    for match in game_day.get("matches") or []:
        if match.get("status") != "completed":
            continue
        home = table.get(match["home_team_name"])
        away = table.get(match["away_team_name"])
        if home is None or away is None:
            continue
        home_score = match.get("home_score") or 0
        away_score = match.get("away_score") or 0
        home["played"] += 1
        away["played"] += 1
        home["goals_for"] += home_score
        home["goals_against"] += away_score
        away["goals_for"] += away_score
        away["goals_against"] += home_score
        if home_score > away_score:
            home["wins"] += 1
            home["points"] += 3
            away["losses"] += 1
            head_to_head[(match["home_team_name"], match["away_team_name"])] += 3
        elif away_score > home_score:
            away["wins"] += 1
            away["points"] += 3
            home["losses"] += 1
            head_to_head[(match["away_team_name"], match["home_team_name"])] += 3
        else:
            home["draws"] += 1
            away["draws"] += 1
            home["points"] += 1
            away["points"] += 1
            head_to_head[(match["home_team_name"], match["away_team_name"])] += 1
            head_to_head[(match["away_team_name"], match["home_team_name"])] += 1

    rows = []
    for row in table.values():
        row["goal_difference"] = row["goals_for"] - row["goals_against"]
        rows.append(row)

    def sort_key(row: dict) -> tuple:
        others = [item["name"] for item in rows if item is not row]
        h2h = sum(head_to_head[(row["name"], other)] for other in others)
        return (
            -row["points"],
            -row["goal_difference"],
            -row["goals_for"],
            -h2h,
            row["name"],
        )

    rows.sort(key=sort_key)
    return rows


def attach_standings(game_day: dict | None) -> dict | None:
    if game_day is None:
        return None
    if game_day.get("is_rotating"):
        game_day["standings"] = []
    else:
        game_day["standings"] = standings_from_payload(game_day)
    return game_day


def decode_jsonb(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def fetch_json(sql: str, params: dict):
    with read_engine.connect() as connection:
        return decode_jsonb(connection.execute(text(sql), params).scalar())


def read_group_payload(group_id: UUID, user_id: UUID) -> dict:
    payload = fetch_json(
        "SELECT public.lineapp_read_group(CAST(:gid AS uuid), CAST(:uid AS uuid))",
        {"gid": str(group_id), "uid": str(user_id)},
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Group not found")
    error = payload.get("error")
    if error == "not_found":
        raise HTTPException(status_code=404, detail="Group not found")
    if error == "forbidden":
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this group",
        )
    attach_standings(payload.get("game_day"))
    # The finished day carries the final table, so it needs standings too.
    attach_standings(payload.get("finished_game_day"))
    return payload


def champion_teams(rows: list[dict]) -> list[str]:
    if not rows:
        return []
    top = rows[0]
    winners = [top["name"]]
    for row in rows[1:]:
        if (
            row["points"] == top["points"]
            and row["goal_difference"] == top["goal_difference"]
            and row["goals_for"] == top["goals_for"]
        ):
            winners.append(row["name"])
        else:
            break
    if len(winners) > 1:
        # Head-to-head already applied in sort; remaining ties are co-champions.
        return winners
    return winners


def real_participants(game_day: GameDay) -> list[Membership]:
    return [
        item.membership
        for item in participant_registrations(game_day)
        if is_real(item.membership)
    ]


def maybe_announce_mvp(db: Session, game_day: GameDay) -> None:
    if game_day.status != "finished" or game_day.mvp_closed_at is not None:
        return
    eligible = real_participants(game_day)
    if not eligible:
        return
    if "mvp_votes" in game_day.__dict__:
        votes = list(game_day.mvp_votes)
    else:
        votes = (
            db.query(MvpVote)
            .filter(MvpVote.game_day_id == game_day.id)
            .all()
        )
    if len(votes) < len(eligible):
        return
    announce_mvp(db, game_day, votes)


def announce_mvp(db: Session, game_day: GameDay, votes: list[MvpVote] | None = None) -> None:
    if game_day.mvp_closed_at is not None:
        return
    if votes is None:
        votes = (
            db.query(MvpVote)
            .filter(MvpVote.game_day_id == game_day.id)
            .all()
        )
    counts: dict[UUID, int] = defaultdict(int)
    for vote in votes:
        counts[vote.nominee_membership_id] += 1
    if counts:
        best = max(counts.values())
        for membership_id, total in counts.items():
            membership = db.get(Membership, membership_id)
            if total == best and membership and is_real(membership):
                db.add(
                    GameDayAward(
                        game_day_id=game_day.id,
                        membership_id=membership_id,
                        award_type="mvp",
                    )
                )
    game_day.mvp_closed_at = now_utc()
    db.commit()


def match_to_dict(db: Session, match: Match) -> dict:
    return {
        "id": str(match.id),
        "home_team_name": match.home_team_name,
        "away_team_name": match.away_team_name,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "status": match.status,
        "players": [
            {
                **membership_to_dict(db, item.membership),
                "team_name": item.team_name,
            }
            for item in match.players
        ],
        "goals": [
            {
                "id": str(goal.id),
                "scorer": membership_to_dict(db, goal.scorer),
                "assist": membership_to_dict(db, goal.assister) if goal.assister else None,
            }
            for goal in match.goals
        ],
    }


def awards_to_dict(
    db: Session,
    game_day: GameDay,
    cache: dict[UUID, str] | None = None,
) -> dict:
    if "awards" in game_day.__dict__:
        awards = list(game_day.awards)
    else:
        awards = (
            db.query(GameDayAward)
            .options(joinedload(GameDayAward.membership))
            .filter(GameDayAward.game_day_id == game_day.id)
            .all()
        )
    champions = [
        membership_to_dict(db, item.membership, cache)
        for item in awards
        if item.award_type == "champion"
    ]
    mvps = [
        membership_to_dict(db, item.membership, cache)
        for item in awards
        if item.award_type == "mvp"
    ]
    return {"champions": champions, "mvps": mvps}


def game_day_to_dict(
    db: Session,
    game_day: GameDay,
    viewer: Membership | None,
    cache: dict[UUID, str] | None = None,
) -> dict:
    game_day = sync_game_day_status(db, game_day)
    promote_waiting_players(db, game_day)
    if game_day.status == "finished" and game_day.mvp_closed_at is None:
        maybe_announce_mvp(db, game_day)

    names = cache or profile_names(
        db,
        [
            item.membership.user_id
            for item in game_day.registrations
            if item.membership.user_id
        ],
    )
    teams = teams_to_dict(db, game_day, names)
    eligible = real_participants(game_day)
    if "mvp_votes" in game_day.__dict__:
        votes = list(game_day.mvp_votes)
    else:
        votes = (
            db.query(MvpVote)
            .filter(MvpVote.game_day_id == game_day.id)
            .all()
        )
    my_vote = None
    if viewer:
        found = next((item for item in votes if item.voter_membership_id == viewer.id), None)
        if found:
            my_vote = str(found.nominee_membership_id)

    payload = {
        "id": str(game_day.id),
        "game_datetime": game_day.game_datetime,
        "regular_registration_opens": game_day.regular_registration_opens,
        "status": game_day.status,
        "participant_count": game_day.participant_count,
        "players_per_team": game_day.players_per_team,
        "is_rotating": game_day.is_rotating,
        "champion_team_name": game_day.champion_team_name,
        "mvp_open": game_day.status == "finished" and game_day.mvp_closed_at is None,
        "mvp_announced": game_day.mvp_closed_at is not None,
        "votes_cast": len(votes),
        "eligible_voters": len(eligible),
        "my_vote": my_vote,
        "participants": [
            membership_to_dict(db, item.membership, names)
            for item in participant_registrations(game_day)
        ],
        "waiting_list": [
            membership_to_dict(db, item.membership, names)
            for item in waiting_registrations(game_day)
        ],
        "matches": [
            match_to_dict(db, item)
            for item in sorted(game_day.matches, key=lambda match: match.created_at)
        ],
        "standings": [] if game_day.is_rotating else standings_for(game_day),
        "awards": awards_to_dict(db, game_day, names),
    }
    payload.update(teams)
    return payload


def reload_game_day(db: Session, game_day_id: UUID) -> GameDay | None:
    return (
        db.query(GameDay)
        .options(
            selectinload(GameDay.registrations).joinedload(Registration.membership),
            selectinload(GameDay.team_assignments).joinedload(TeamAssignment.membership),
            selectinload(GameDay.matches)
            .selectinload(Match.players)
            .joinedload(MatchPlayer.membership),
            selectinload(GameDay.matches).selectinload(Match.goals),
            selectinload(GameDay.awards).joinedload(GameDayAward.membership),
            selectinload(GameDay.mvp_votes),
        )
        .filter(GameDay.id == game_day_id)
        .first()
    )


def slim_game_day_dict(
    db: Session,
    game_day: GameDay,
    viewer: Membership | None,
    include_matches: bool = False,
) -> dict:
    return serialize_game_day(db, game_day, viewer)


def serialize_game_day(
    db: Session,
    game_day: GameDay,
    viewer: Membership | None,
    cache: dict[UUID, str] | None = None,
) -> dict:
    row = fetch_json(
        "SELECT public.lineapp_game_day_json(CAST(:gid AS uuid), CAST(:vid AS uuid))",
        {
            "gid": str(game_day.id),
            "vid": str(viewer.id) if viewer else None,
        },
    )
    payload = row or {}
    attach_standings(payload)
    return payload


def group_to_dict(
    db: Session,
    group: Group,
    user: CurrentUser,
    include_invite: bool,
) -> dict:
    membership = None
    if "memberships" in group.__dict__:
        membership = next(
            (
                item
                for item in group.memberships
                if item.user_id == user.id
            ),
            None,
        )
    if membership is None:
        membership = membership_for_user(db, group.id, user.id)
    names = profile_names(
        db,
        [item.user_id for item in group.memberships if item.user_id],
    )
    current = current_game_day(db, group)
    if "game_days" in group.__dict__:
        history = sorted(
            [item for item in group.game_days if item.status == "finished"],
            key=lambda item: item.game_datetime,
            reverse=True,
        )
    else:
        history = (
            db.query(GameDay)
            .filter(GameDay.group_id == group.id, GameDay.status == "finished")
            .order_by(GameDay.game_datetime.desc())
            .all()
        )
    survey = (
        db.query(RatingSurvey)
        .options(selectinload(RatingSurvey.responses))
        .filter(RatingSurvey.group_id == group.id)
        .order_by(RatingSurvey.created_at.desc())
        .first()
    )
    result = {
        "id": str(group.id),
        "name": group.name,
        "last_participant_count": group.last_participant_count,
        "last_players_per_team": group.last_players_per_team,
        "members": [membership_to_dict(db, item, names) for item in group.memberships],
        "game_day": (
            None
            if current is None
            else slim_game_day_dict(db, current, membership, include_matches=True)
            if current.status == "upcoming"
            else serialize_game_day(db, current, membership, names)
        ),
        "history": [
            {
                "id": str(item.id),
                "game_datetime": item.game_datetime,
                "status": item.status,
                "is_rotating": item.is_rotating,
                "champion_team_name": item.champion_team_name,
                "awards": awards_to_dict(db, item, names),
            }
            for item in history
        ],
        "survey": survey_to_dict(db, survey, membership) if survey else None,
    }
    if include_invite:
        result["invite_code"] = group.invite_code
        result["invite_link"] = f"{FRONTEND_URL}/?invite={group.invite_code}"
    return result


def survey_to_dict(
    db: Session,
    survey: RatingSurvey,
    viewer: Membership | None,
) -> dict:
    my_ratings = {}
    if viewer:
        for response in survey.responses:
            if response.rater_membership_id == viewer.id:
                my_ratings[str(response.rated_membership_id)] = response.rating
    return {
        "id": str(survey.id),
        "status": survey.status,
        "created_at": survey.created_at,
        "closed_at": survey.closed_at,
        "my_ratings": my_ratings,
    }


def parse_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise HTTPException(
            status_code=400,
            detail="Game Day time must include a timezone offset",
        )
    return value.astimezone(timezone.utc)


@app.get("/")
def root():
    return {"message": "LineApp backend is running on Supabase/PostgreSQL"}


@app.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return fetch_json(
        """
        SELECT jsonb_build_object(
          'id', CAST(:uid AS text),
          'email', CAST(:email AS text),
          'display_name', coalesce(
            (SELECT display_name FROM profiles WHERE id = CAST(:uid AS uuid)),
            'Player'
          ),
          'is_developer', exists(
            SELECT 1 FROM developers WHERE user_id = CAST(:uid AS uuid)
          )
        )
        """,
        {"uid": str(user.id), "email": user.email},
    )


@app.get("/bootstrap")
def bootstrap(
    user: CurrentUser = Depends(get_current_user),
    real_user: CurrentUser = Depends(get_authenticated_user),
):
    # Developer status is read from the account that signed in, not the one
    # being simulated, so stepping into a normal member's shoes never locks the
    # developer out of the control that steps back again.
    return fetch_json(
        """
        SELECT jsonb_build_object(
          'id', CAST(:uid AS text),
          'email', CAST(:email AS text),
          'display_name', coalesce(
            (SELECT display_name FROM profiles WHERE id = CAST(:uid AS uuid)),
            'Player'
          ),
          'is_developer', exists(
            SELECT 1 FROM developers WHERE user_id = CAST(:real_uid AS uuid)
          ),
          'is_simulated', CAST(:uid AS uuid) <> CAST(:real_uid AS uuid),
          'groups', coalesce((
            SELECT jsonb_agg(
              jsonb_build_object(
                'id', g.id::text,
                'name', g.name,
                'membership_id', m.id::text,
                'is_admin', m.is_admin,
                'is_subscriber', m.is_subscriber,
                'rating', m.rating::float8
              )
              ORDER BY m.created_at
            )
            FROM memberships m
            JOIN groups g ON g.id = m.group_id
            WHERE m.user_id = CAST(:uid AS uuid)
          ), '[]'::jsonb)
        )
        """,
        {"uid": str(user.id), "email": user.email, "real_uid": str(real_user.id)},
    )


@app.get("/my-groups")
def get_my_groups(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    memberships = (
        db.query(Membership)
        .options(joinedload(Membership.group))
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
            "rating": float(item.rating),
        }
        for item in memberships
    ]


@app.get("/invite/{invite_code}")
def preview_invite(
    invite_code: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = db.query(Group).filter(Group.invite_code == invite_code).first()
    if group is None:
        raise HTTPException(status_code=404, detail="Invitation is not valid")
    membership = membership_for_user(db, group.id, user.id)
    request = (
        db.query(JoinRequest)
        .filter(JoinRequest.group_id == group.id, JoinRequest.user_id == user.id)
        .order_by(JoinRequest.created_at.desc())
        .first()
    )
    return {
        "id": str(group.id),
        "name": group.name,
        "state": (
            "member"
            if membership
            else (request.status if request else "none")
        ),
    }


@app.post("/groups")
def create_group(
    request: CreateGroupRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = Group(
        name=request.name.strip(),
        created_by=user.id,
        invite_code=new_invite_code(),
        last_participant_count=12,
        last_players_per_team=4,
    )
    db.add(group)
    db.flush()
    db.add(
        Membership(
            group_id=group.id,
            user_id=user.id,
            rating=Decimal("3.0"),
            is_subscriber=False,
            is_admin=True,
        )
    )
    db.commit()
    db.refresh(group)
    return read_group_payload(group.id, user.id)


@app.get("/groups/{group_id}")
def get_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    return read_group_payload(group_id, user.id)


@app.get("/groups/{group_id}/membership-status")
def get_membership_status(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    row = fetch_json(
        """
        SELECT jsonb_build_object(
          'state', CASE
            WHEN m.id IS NOT NULL THEN 'member'
            ELSE coalesce(jr.status, 'none')
          END,
          'membership_id', m.id::text,
          'is_admin', coalesce(m.is_admin, false)
        )
        FROM groups g
        LEFT JOIN memberships m
          ON m.group_id = g.id AND m.user_id = CAST(:uid AS uuid)
        LEFT JOIN LATERAL (
          SELECT status
          FROM join_requests
          WHERE group_id = g.id AND user_id = CAST(:uid AS uuid)
          ORDER BY created_at DESC
          LIMIT 1
        ) jr ON true
        WHERE g.id = CAST(:gid AS uuid)
        """,
        {"gid": str(group_id), "uid": str(user.id)},
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return row


@app.post("/groups/{group_id}/join-request")
def request_to_join(
    group_id: UUID,
    body: JoinWithInviteRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    if group.invite_code != body.invite_code.strip():
        raise HTTPException(status_code=403, detail="Invitation is not valid")
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
    db.add(JoinRequest(group_id=group.id, user_id=user.id, status="pending"))
    db.commit()
    return {"message": "Join request submitted"}


@app.post("/groups/{group_id}/invite/regenerate")
def regenerate_invite(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    group.invite_code = new_invite_code()
    db.commit()
    return {
        "invite_code": group.invite_code,
        "invite_link": f"{FRONTEND_URL}/?invite={group.invite_code}",
    }


@app.get("/groups/{group_id}/join-requests")
def pending_join_requests(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    row = fetch_json(
        """
        SELECT CASE
          WHEN NOT EXISTS (
            SELECT 1 FROM groups WHERE id = CAST(:gid AS uuid)
          ) THEN jsonb_build_object('error', 'not_found')
          WHEN NOT EXISTS (
            SELECT 1 FROM memberships
            WHERE group_id = CAST(:gid AS uuid)
              AND user_id = CAST(:uid AS uuid)
              AND is_admin
          ) THEN jsonb_build_object('error', 'forbidden')
          ELSE coalesce((
            SELECT jsonb_agg(
              jsonb_build_object(
                'id', jr.id::text,
                'user_id', jr.user_id::text,
                'user_name', coalesce(p.display_name, 'Player'),
                'status', jr.status
              )
              ORDER BY jr.created_at
            )
            FROM join_requests jr
            LEFT JOIN profiles p ON p.id = jr.user_id
            WHERE jr.group_id = CAST(:gid AS uuid) AND jr.status = 'pending'
          ), '[]'::jsonb)
        END
        """,
        {"gid": str(group_id), "uid": str(user.id)},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Group not found")
    if isinstance(row, dict) and row.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Group not found")
    if isinstance(row, dict) and row.get("error") == "forbidden":
        raise HTTPException(status_code=403, detail="Admin permission required")
    return row


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
    if request is None or request.group_id != group.id or request.status != "pending":
        raise HTTPException(status_code=404, detail="Pending request not found")
    if membership_for_user(db, group.id, request.user_id) is None:
        db.add(
            Membership(
                group_id=group.id,
                user_id=request.user_id,
                rating=Decimal("3.0"),
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
    if request is None or request.group_id != group.id or request.status != "pending":
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
    ensure_not_last_admin(db, membership)
    game_day = current_game_day(db, group)
    if game_day:
        registration = (
            db.query(Registration)
            .filter(
                Registration.game_day_id == game_day.id,
                Registration.membership_id == membership.id,
            )
            .first()
        )
        if registration:
            db.delete(registration)
        clear_teams(db, game_day)
    db.delete(membership)
    db.commit()
    if game_day:
        promote_waiting_players(db, game_day)
    return {"message": "Left group successfully"}


@app.post("/groups/{group_id}/transfer-admin-and-leave")
def transfer_admin_and_leave(
    group_id: UUID,
    request: TransferAdminAndLeaveRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    membership = require_admin(db, group, user)
    target = db.get(Membership, request.target_membership_id)
    if target is None or target.group_id != group.id:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.id == membership.id:
        raise HTTPException(
            status_code=400,
            detail="Choose another real member to receive the admin role",
        )
    if not is_real(target):
        raise HTTPException(
            status_code=400,
            detail="Virtual members cannot be admins",
        )

    # Promotion and departure share one transaction. A failed delete can never
    # leave the group with a surprising partial role change.
    target.is_admin = True
    game_day = current_game_day(db, group)
    if game_day:
        registration = (
            db.query(Registration)
            .filter(
                Registration.game_day_id == game_day.id,
                Registration.membership_id == membership.id,
            )
            .first()
        )
        if registration:
            db.delete(registration)
        clear_teams(db, game_day)
    db.delete(membership)
    db.commit()
    if game_day:
        promote_waiting_players(db, game_day)
    return {"message": "Admin role transferred and group left successfully"}


@app.delete("/groups/{group_id}")
def delete_group(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)

    # The live schema's complete group-owned FK graph is ON DELETE CASCADE.
    # Execute one database-level delete so join requests, game days, matches,
    # goals, MVP data and surveys are handled by those constraints atomically.
    db.execute(text("DELETE FROM groups WHERE id = :group_id"), {"group_id": group.id})
    db.commit()
    return {"message": "Group permanently deleted"}


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
        rating=Decimal(str(request.rating)),
        is_subscriber=request.is_subscriber,
        is_admin=False,
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
    if not is_real(membership) and request.is_admin:
        raise HTTPException(
            status_code=400,
            detail="Virtual members cannot be admins",
        )
    if membership.is_admin and is_real(membership) and not request.is_admin:
        ensure_not_last_admin(db, membership)
    if membership.user_id is None:
        membership.display_name = request.name.strip()
        membership.is_admin = False
    else:
        membership.is_admin = request.is_admin
    membership.rating = Decimal(str(round(request.rating, 1)))
    membership.is_subscriber = request.is_subscriber
    game_day = current_game_day(db, group)
    if game_day:
        clear_teams(db, game_day)
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
    ensure_not_last_admin(db, membership)
    game_day = current_game_day(db, group)
    if game_day:
        registration = (
            db.query(Registration)
            .filter(
                Registration.game_day_id == game_day.id,
                Registration.membership_id == membership.id,
            )
            .first()
        )
        if registration:
            db.delete(registration)
        clear_teams(db, game_day)
    db.delete(membership)
    db.commit()
    if game_day:
        promote_waiting_players(db, game_day)
    return {"message": "Member deleted"}


@app.post("/groups/{group_id}/game-days")
def create_game_day(
    group_id: UUID,
    request: CreateGameDayRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    kickoff = parse_aware(request.game_datetime)
    if kickoff <= now_utc():
        raise HTTPException(status_code=400, detail="Game Day must be in the future")
    if request.participant_count < request.players_per_team:
        raise HTTPException(
            status_code=400,
            detail="Need enough players for at least one complete team",
        )
    if current_game_day(db, group):
        raise HTTPException(
            status_code=400,
            detail="Finish or wait for the current Game Day before creating another",
        )
    leftover = request.participant_count % request.players_per_team
    game_day = GameDay(
        group_id=group.id,
        game_datetime=kickoff,
        regular_registration_opens=kickoff - timedelta(hours=request.priority_hours),
        status="upcoming",
        participant_count=request.participant_count,
        players_per_team=request.players_per_team,
        is_rotating=leftover > 0,
    )
    group.last_participant_count = request.participant_count
    group.last_players_per_team = request.players_per_team
    db.add(game_day)
    db.commit()
    membership = membership_for_user(db, group.id, user.id)
    payload = slim_game_day_dict(db, game_day, membership, include_matches=True)
    payload["warning"] = (
        f"{leftover} player(s) will not fit into a complete team. "
        "This Game Day will use rotating teams and will not have a champion."
        if leftover
        else None
    )
    return payload


@app.delete("/groups/{group_id}/game-days/{game_day_id}")
def delete_game_day(
    group_id: UUID,
    game_day_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if game_day.status == "finished":
        raise HTTPException(status_code=400, detail="Finished Game Days cannot be deleted")
    db.delete(game_day)
    db.commit()
    return {"message": "Game Day deleted"}


@app.post("/groups/{group_id}/game-days/{game_day_id}/register/{membership_id}")
def register_member(
    group_id: UUID,
    game_day_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller = require_membership(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if game_day.status == "finished":
        raise HTTPException(status_code=400, detail="This Game Day is finished")
    target = db.get(Membership, membership_id)
    if target is None or target.group_id != group.id:
        raise HTTPException(status_code=404, detail="Member not found")
    if target.id != caller.id and not caller.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")
    existing = (
        db.query(Registration)
        .filter(
            Registration.game_day_id == game_day.id,
            Registration.membership_id == target.id,
        )
        .first()
    )
    if existing:
        return slim_game_day_dict(db, game_day, caller)
    status = registration_status_for(db, game_day, target)
    db.add(Registration(game_day_id=game_day.id, membership_id=target.id, status=status))
    clear_teams(db, game_day)
    db.commit()
    return slim_game_day_dict(db, game_day, caller)


@app.post("/groups/{group_id}/game-days/{game_day_id}/unregister/{membership_id}")
def unregister_member(
    group_id: UUID,
    game_day_id: UUID,
    membership_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    caller = require_membership(db, group, user)
    if membership_id != caller.id and not caller.is_admin:
        raise HTTPException(status_code=403, detail="Admin permission required")
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    registration = (
        db.query(Registration)
        .filter(
            Registration.game_day_id == game_day.id,
            Registration.membership_id == membership_id,
        )
        .first()
    )
    if registration:
        db.delete(registration)
        clear_teams(db, game_day)
        db.commit()
        promote_waiting_players(db, game_day)
    return slim_game_day_dict(db, game_day, caller)


@app.post("/groups/{group_id}/game-days/{game_day_id}/generate-teams")
def generate_teams(
    group_id: UUID,
    game_day_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    registrations = participant_registrations(game_day)
    if len(registrations) != game_day.participant_count:
        raise HTTPException(
            status_code=400,
            detail="Register the configured number of participating players first",
        )
    memberships = [item.membership for item in registrations]
    generated, unassigned = generate_balanced_teams(
        memberships,
        game_day.players_per_team,
    )
    clear_teams(db, game_day)
    for team in generated:
        for membership in team.players:
            db.add(
                TeamAssignment(
                    game_day_id=game_day.id,
                    membership_id=membership.id,
                    team_name=team.name,
                )
            )
    for membership in unassigned:
        db.add(
            TeamAssignment(
                game_day_id=game_day.id,
                membership_id=membership.id,
                team_name=None,
            )
        )
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, caller)


@app.put("/groups/{group_id}/game-days/{game_day_id}/teams")
def update_teams(
    group_id: UUID,
    game_day_id: UUID,
    request: UpdateTeamsRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if not game_day.is_rotating and game_day.status == "live":
        raise HTTPException(
            status_code=400,
            detail="Fixed teams cannot be changed during a Live Game Day",
        )
    valid_ids = {item.membership_id for item in participant_registrations(game_day)}
    requested_ids = [item.membership_id for item in request.assignments]
    if set(requested_ids) != valid_ids:
        raise HTTPException(status_code=400, detail="Assignments must include every participating player")
    clear_teams(db, game_day)
    for item in request.assignments:
        db.add(
            TeamAssignment(
                game_day_id=game_day.id,
                membership_id=item.membership_id,
                team_name=item.team_name,
            )
        )
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, caller)


@app.post("/groups/{group_id}/game-days/{game_day_id}/matches")
def create_match(
    group_id: UUID,
    game_day_id: UUID,
    request: CreateMatchRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    game_day = sync_game_day_status(db, game_day)
    if game_day.status != "live":
        raise HTTPException(status_code=400, detail="Matches can only be created during a Live Game Day")
    if request.home_team_name == request.away_team_name:
        raise HTTPException(status_code=400, detail="Select two different teams")
    buckets = team_totals(game_day)
    home = buckets.get(request.home_team_name, [])
    away = buckets.get(request.away_team_name, [])
    if len(home) != game_day.players_per_team or len(away) != game_day.players_per_team:
        raise HTTPException(
            status_code=400,
            detail="Each selected team must have a complete lineup",
        )
    match = Match(
        game_day_id=game_day.id,
        home_team_name=request.home_team_name,
        away_team_name=request.away_team_name,
        status="open",
    )
    db.add(match)
    db.flush()
    for membership in home:
        db.add(MatchPlayer(match_id=match.id, membership_id=membership.id, team_name=request.home_team_name))
    for membership in away:
        db.add(MatchPlayer(match_id=match.id, membership_id=membership.id, team_name=request.away_team_name))
    db.commit()
    db.refresh(match)
    caller = membership_for_user(db, group.id, user.id)
    return serialize_game_day(db, game_day, caller)


@app.post("/groups/{group_id}/matches/{match_id}/complete")
def complete_match(
    group_id: UUID,
    match_id: UUID,
    request: CompleteMatchRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    match = db.get(Match, match_id)
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    game_day = db.get(GameDay, match.game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Match not found")
    if match.status == "completed":
        for goal in list(match.goals):
            db.delete(goal)
    playing_ids = {item.membership_id for item in match.players}
    for goal in request.goals:
        if goal.scorer_membership_id not in playing_ids:
            raise HTTPException(status_code=400, detail="Scorer must be playing in this match")
        if goal.assist_membership_id and goal.assist_membership_id not in playing_ids:
            raise HTTPException(status_code=400, detail="Assist must come from a player in this match")
        if goal.assist_membership_id == goal.scorer_membership_id:
            raise HTTPException(status_code=400, detail="A player cannot assist their own goal")
        db.add(
            MatchGoal(
                match_id=match.id,
                scorer_membership_id=goal.scorer_membership_id,
                assist_membership_id=goal.assist_membership_id,
            )
        )
    match.home_score = request.home_score
    match.away_score = request.away_score
    match.status = "completed"
    match.completed_at = now_utc()
    db.commit()
    db.refresh(match)
    caller = membership_for_user(db, group.id, user.id)
    return serialize_game_day(db, game_day, caller)


@app.post("/groups/{group_id}/game-days/{game_day_id}/finish")
def finish_game_day(
    group_id: UUID,
    game_day_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if game_day.status == "finished":
        raise HTTPException(status_code=400, detail="Game Day is already finished")
    game_day.status = "finished"
    game_day.finished_at = now_utc()
    if not game_day.is_rotating:
        completed = [item for item in game_day.matches if item.status == "completed"]
        if completed:
            rows = standings_for(game_day)
            winners = champion_teams(rows)
            game_day.champion_team_name = " / ".join(winners) if winners else None
            for assignment in game_day.team_assignments:
                if assignment.team_name in winners and is_real(assignment.membership):
                    db.add(
                        GameDayAward(
                            game_day_id=game_day.id,
                            membership_id=assignment.membership_id,
                            award_type="champion",
                        )
                    )
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return serialize_game_day(db, game_day, caller)


@app.post("/groups/{group_id}/game-days/{game_day_id}/mvp")
def vote_mvp(
    group_id: UUID,
    game_day_id: UUID,
    request: MvpVoteRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if game_day.status != "finished" or game_day.mvp_closed_at is not None:
        raise HTTPException(status_code=400, detail="MVP voting is not open")
    eligible_ids = {item.id for item in real_participants(game_day)}
    if membership.id not in eligible_ids:
        raise HTTPException(status_code=403, detail="Only participating players can vote")
    if request.nominee_membership_id not in eligible_ids:
        raise HTTPException(status_code=400, detail="MVP must be a participating player with an account")
    if request.nominee_membership_id == membership.id:
        raise HTTPException(status_code=400, detail="You cannot vote for yourself")
    existing = (
        db.query(MvpVote)
        .filter(
            MvpVote.game_day_id == game_day.id,
            MvpVote.voter_membership_id == membership.id,
        )
        .first()
    )
    if existing:
        existing.nominee_membership_id = request.nominee_membership_id
    else:
        db.add(
            MvpVote(
                game_day_id=game_day.id,
                voter_membership_id=membership.id,
                nominee_membership_id=request.nominee_membership_id,
            )
        )
    db.commit()
    maybe_announce_mvp(db, game_day)
    return serialize_game_day(db, game_day, membership)


@app.post("/groups/{group_id}/game-days/{game_day_id}/mvp/close")
def close_mvp(
    group_id: UUID,
    game_day_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    game_day = db.get(GameDay, game_day_id)
    if game_day is None or game_day.group_id != group.id:
        raise HTTPException(status_code=404, detail="Game Day not found")
    if game_day.status != "finished":
        raise HTTPException(status_code=400, detail="Finish the Game Day first")
    announce_mvp(db, game_day)
    caller = membership_for_user(db, group.id, user.id)
    return serialize_game_day(db, game_day, caller)


@app.get("/groups/{group_id}/statistics")
def statistics(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
):
    payload = fetch_json(
                """
                SELECT CASE
                  WHEN NOT EXISTS (
                    SELECT 1 FROM groups WHERE id = CAST(:gid AS uuid)
                  ) THEN jsonb_build_object('error', 'not_found')
                  WHEN NOT EXISTS (
                    SELECT 1 FROM memberships
                    WHERE group_id = CAST(:gid AS uuid)
                      AND user_id = CAST(:uid AS uuid)
                  ) THEN jsonb_build_object('error', 'forbidden')
                  ELSE coalesce((
                    SELECT jsonb_agg(item.obj ORDER BY lower(item.obj->>'name'))
                    FROM (
                      SELECT public.lineapp_member_json(
                        m.id, m.user_id, m.display_name, m.rating,
                        m.is_subscriber, m.is_admin, p.display_name
                      ) || jsonb_build_object(
                        'game_days_played', (
                          SELECT count(*) FROM registrations r
                          JOIN game_days gd ON gd.id = r.game_day_id
                          WHERE r.membership_id = m.id
                            AND r.status = 'participant'
                            AND gd.status = 'finished'
                        ),
                        'matches_played', (
                          SELECT count(*) FROM match_players mp
                          JOIN matches mt ON mt.id = mp.match_id
                          JOIN game_days gd ON gd.id = mt.game_day_id
                          WHERE mp.membership_id = m.id
                            AND mt.status = 'completed'
                            AND gd.group_id = CAST(:gid AS uuid)
                        ),
                        'championships', (
                          SELECT count(*) FROM game_day_awards a
                          WHERE a.membership_id = m.id AND a.award_type = 'champion'
                        ),
                        'goals', (
                          SELECT count(*) FROM match_goals g
                          WHERE g.scorer_membership_id = m.id
                        ),
                        'assists', (
                          SELECT count(*) FROM match_goals g
                          WHERE g.assist_membership_id = m.id
                        ),
                        'mvp_titles', (
                          SELECT count(*) FROM game_day_awards a
                          WHERE a.membership_id = m.id AND a.award_type = 'mvp'
                        )
                      ) AS obj
                      FROM memberships m
                      LEFT JOIN profiles p ON p.id = m.user_id
                      WHERE m.group_id = CAST(:gid AS uuid) AND m.user_id IS NOT NULL
                    ) item
                  ), '[]'::jsonb)
                END
                """,
        {"gid": str(group_id), "uid": str(user.id)},
    )
    if not payload:
        raise HTTPException(status_code=404, detail="Group not found")
    if isinstance(payload, dict) and payload.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="Group not found")
    if isinstance(payload, dict) and payload.get("error") == "forbidden":
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this group",
        )
    return payload


@app.post("/groups/{group_id}/surveys")
def start_survey(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    open_survey = (
        db.query(RatingSurvey)
        .filter(RatingSurvey.group_id == group.id, RatingSurvey.status == "open")
        .first()
    )
    if open_survey:
        raise HTTPException(status_code=400, detail="A rating survey is already open")
    survey = RatingSurvey(group_id=group.id, status="open")
    db.add(survey)
    db.commit()
    membership = membership_for_user(db, group.id, user.id)
    return survey_to_dict(db, survey, membership)


@app.post("/groups/{group_id}/surveys/{survey_id}/ratings")
def submit_survey_ratings(
    group_id: UUID,
    survey_id: UUID,
    request: SurveyRatingsRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    membership = require_membership(db, group, user)
    survey = db.get(RatingSurvey, survey_id)
    if survey is None or survey.group_id != group.id:
        raise HTTPException(status_code=404, detail="Survey not found")
    if survey.status != "open":
        raise HTTPException(status_code=400, detail="This survey is closed")
    for key, value in request.ratings.items():
        try:
            rated_id = UUID(key)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Each rating target must be a valid membership id",
            ) from exc
        if rated_id == membership.id:
            raise HTTPException(
                status_code=400,
                detail="You cannot rate yourself",
            )
        rated = db.get(Membership, rated_id)
        if rated is None or rated.group_id != group.id:
            raise HTTPException(
                status_code=400,
                detail="Only current members of this group can be rated",
            )
        if not is_real(rated):
            raise HTTPException(
                status_code=400,
                detail="Virtual members cannot be rated",
            )
        if value < 1 or value > 5:
            raise HTTPException(status_code=400, detail="Ratings must be between 1 and 5")
        # Half stars only: doubling a permitted value lands on a whole number.
        if (value * 2) % 1 != 0:
            raise HTTPException(
                status_code=400,
                detail="Ratings must be given in steps of 0.5",
            )
        existing = (
            db.query(RatingSurveyResponse)
            .filter(
                RatingSurveyResponse.survey_id == survey.id,
                RatingSurveyResponse.rater_membership_id == membership.id,
                RatingSurveyResponse.rated_membership_id == rated_id,
            )
            .first()
        )
        if existing:
            existing.rating = value
        else:
            db.add(
                RatingSurveyResponse(
                    survey_id=survey.id,
                    rater_membership_id=membership.id,
                    rated_membership_id=rated_id,
                    rating=value,
                )
            )
    db.commit()
    db.refresh(survey)
    return survey_to_dict(db, survey, membership)


@app.post("/groups/{group_id}/surveys/{survey_id}/close")
def close_survey(
    group_id: UUID,
    survey_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    group = get_group_or_404(db, group_id)
    require_admin(db, group, user)
    survey = db.get(RatingSurvey, survey_id)
    if survey is None or survey.group_id != group.id:
        raise HTTPException(status_code=404, detail="Survey not found")
    if survey.status != "open":
        raise HTTPException(status_code=400, detail="Survey already closed")
    totals: dict[UUID, list[Decimal]] = defaultdict(list)
    for response in survey.responses:
        totals[response.rated_membership_id].append(response.rating)
    for membership_id, values in totals.items():
        membership = db.get(Membership, membership_id)
        if membership is None or not is_real(membership):
            continue
        average = sum(values) / len(values)
        rounded = Decimal(str(average)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        membership.rating = rounded
    survey.status = "closed"
    survey.closed_at = now_utc()
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return survey_to_dict(db, survey, caller)


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
    ("Sam", 4, False),
    ("Leo", 3, False),
]


@app.post("/dev/groups/{group_id}/add-test-members")
def dev_add_test_members(
    group_id: UUID,
    count: int = 16,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_developer(db, user)
    group = get_group_or_404(db, group_id)
    existing_virtual = [item for item in group.memberships if item.user_id is None]
    for item in existing_virtual:
        db.delete(item)
    db.commit()
    real_count = (
        db.query(Membership)
        .filter(Membership.group_id == group.id, Membership.user_id.is_not(None))
        .count()
    )
    needed = max(0, count - real_count)
    for name, rating, subscriber in TEST_MEMBERS[:needed]:
        db.add(
            Membership(
                group_id=group.id,
                display_name=name,
                rating=Decimal(str(rating)),
                is_subscriber=subscriber,
                is_admin=False,
            )
        )
    db.commit()
    return read_group_payload(group.id, user.id)


@app.post("/dev/groups/{group_id}/create-game")
def dev_create_game(
    group_id: UUID,
    participant_count: int = 12,
    players_per_team: int = 4,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_developer(db, user)
    group = get_group_or_404(db, group_id)
    old = current_game_day(db, group)
    if old:
        db.delete(old)
        db.commit()
    leftover = participant_count % players_per_team
    game_day = GameDay(
        group_id=group.id,
        game_datetime=now_utc() + timedelta(hours=2),
        regular_registration_opens=now_utc() + timedelta(minutes=30),
        status="upcoming",
        participant_count=participant_count,
        players_per_team=players_per_team,
        is_rotating=leftover > 0,
    )
    group.last_participant_count = participant_count
    group.last_players_per_team = players_per_team
    db.add(game_day)
    db.commit()
    membership = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, membership, include_matches=True)


@app.post("/dev/groups/{group_id}/register-all")
def dev_register_all(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_developer(db, user)
    group = get_group_or_404(db, group_id)
    game_day = current_game_day(db, group)
    if game_day is None:
        raise HTTPException(status_code=400, detail="Create a Game Day first")
    for item in list(game_day.registrations):
        db.delete(item)
    db.commit()
    db.refresh(game_day)
    for membership in group.memberships:
        status = registration_status_for(db, game_day, membership)
        db.add(
            Registration(
                game_day_id=game_day.id,
                membership_id=membership.id,
                status=status,
            )
        )
        db.flush()
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, caller)


@app.post("/dev/groups/{group_id}/expire-priority")
def dev_expire_priority(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_developer(db, user)
    group = get_group_or_404(db, group_id)
    game_day = current_game_day(db, group)
    if game_day is None:
        raise HTTPException(status_code=400, detail="Create a Game Day first")
    game_day.regular_registration_opens = now_utc() - timedelta(seconds=1)
    db.commit()
    promote_waiting_players(db, game_day)
    caller = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, caller)


@app.post("/dev/groups/{group_id}/start-live")
def dev_start_live(
    group_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_developer(db, user)
    group = get_group_or_404(db, group_id)
    game_day = current_game_day(db, group)
    if game_day is None:
        raise HTTPException(status_code=400, detail="Create a Game Day first")
    game_day.game_datetime = now_utc() - timedelta(seconds=1)
    game_day.status = "live"
    db.commit()
    caller = membership_for_user(db, group.id, user.id)
    return slim_game_day_dict(db, game_day, caller)
