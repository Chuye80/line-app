"""Test harness.

The database is rebuilt from `supabase/migrations` before the suite runs, so
the tests exercise the real schema - including the partial unique indexes and
the deferred constraint trigger that the concurrency tests rely on. A drift
between the migrations and the application would fail here rather than in
production.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

TEST_DB_NAME = os.environ.get("LINEAPP_TEST_DB", "lineapp_test")
TEST_DB_URL = os.environ.get(
    "LINEAPP_TEST_DATABASE_URL",
    f"postgresql+psycopg2://lineapp:lineapp@127.0.0.1:5432/{TEST_DB_NAME}",
)

# Configuration has to exist before anything under `backend` is imported: the
# settings object is read at module import time.
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("SUPABASE_URL", "https://project.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "test-publishable-key")
os.environ["ENABLE_DEV_ENDPOINTS"] = "true"
os.environ.pop("SUPABASE_JWT_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend.auth import CurrentUser, get_current_user  # noqa: E402
from backend.database import SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402


TABLES = (
    "match_goals",
    "matches",
    "player_ratings",
    "team_assignments",
    "registrations",
    "games",
    "join_requests",
    "memberships",
    "groups",
    "profiles",
)


def _rebuild_database() -> None:
    subprocess.run(
        [str(REPO_ROOT / "scripts" / "reset_test_db.sh"), TEST_DB_NAME],
        check=True,
        capture_output=True,
        cwd=REPO_ROOT,
    )


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    _rebuild_database()
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(database):
    with engine.begin() as connection:
        connection.execute(
            text(f"truncate {', '.join(TABLES)}, auth.users restart identity cascade")
        )

    yield


@pytest.fixture
def db():
    session = SessionLocal()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


class Actor:
    """A signed-in account, plus the client calls made as that account."""

    def __init__(self, client: TestClient, user_id: uuid.UUID, name: str, email: str):
        self.client = client
        self.id = user_id
        self.name = name
        self.email = email

    def _request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Test-User"] = str(self.id)
        return self.client.request(method, path, headers=headers, **kwargs)

    def get(self, path, **kwargs):
        return self._request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self._request("POST", path, **kwargs)

    def put(self, path, **kwargs):
        return self._request("PUT", path, **kwargs)

    def delete(self, path, **kwargs):
        return self._request("DELETE", path, **kwargs)


@pytest.fixture
def client(database):
    """A client whose identity comes from an `X-Test-User` header.

    Overriding the dependency keeps the routes, the database and every
    permission check real; only the network call to Supabase Auth is replaced.
    """

    from fastapi import Header, HTTPException

    def fake_current_user(x_test_user: str | None = Header(default=None)):
        if not x_test_user:
            raise HTTPException(status_code=401, detail="Authentication required")

        return CurrentUser(id=uuid.UUID(x_test_user), email=f"{x_test_user}@test.dev")

    app.dependency_overrides[get_current_user] = fake_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def make_user(client):
    """Create a Supabase-style account and return an Actor for it."""

    def factory(name: str) -> Actor:
        user_id = uuid.uuid4()
        email = f"{name.lower().replace(' ', '.')}.{user_id.hex[:6]}@test.dev"

        with engine.begin() as connection:
            connection.execute(
                text(
                    "insert into auth.users (id, email, raw_user_meta_data) "
                    "values (:id, :email, jsonb_build_object('display_name', :name))"
                ),
                {"id": str(user_id), "email": email, "name": name},
            )

        return Actor(client, user_id, name, email)

    return factory


@pytest.fixture
def group_owner(make_user):
    return make_user("Owner")


@pytest.fixture
def group(group_owner):
    response = group_owner.post("/groups", json={"name": "Sunday League"})
    assert response.status_code == 200, response.text
    return response.json()


def future(hours: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def create_game(
    admin: Actor,
    group_id: str,
    *,
    hours_ahead: float = 48,
    priority_hours: int = 24,
):
    """Schedule a game.

    `priority_hours` counts backwards from kickoff: it is how long before the
    game that registration opens to everybody. Until then only subscribers can
    take a playing slot. A value of 0 therefore means the game stays
    subscribers-only right up to kickoff.
    """

    response = admin.post(
        f"/groups/{group_id}/game",
        json={
            "game_datetime": future(hours_ahead).isoformat(),
            "priority_hours": priority_hours,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def create_open_game(admin: Actor, group_id: str, *, hours_ahead: int = 48):
    """A game whose subscriber-priority window has already closed."""

    return create_game(
        admin, group_id, hours_ahead=hours_ahead, priority_hours=hours_ahead
    )


def add_virtual(
    admin: Actor,
    group_id: str,
    name: str,
    *,
    rating: int = 3,
    subscriber: bool = False,
):
    response = admin.post(
        f"/groups/{group_id}/members",
        json={
            "name": name,
            "rating": rating,
            "is_subscriber": subscriber,
            "is_admin": False,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def build_squad(admin: Actor, group_id: str, *, ratings: list[int] | None = None):
    """Fill a scheduled game day with a full squad and generate the teams."""

    ratings = ratings or [5, 4, 4, 4, 3, 3, 3, 3, 2, 2, 2, 1]

    players = []

    for index, rating in enumerate(ratings):
        player = add_virtual(admin, group_id, f"Player {index:02d}", rating=rating)
        assert (
            admin.post(
                f"/groups/{group_id}/game/register/{player['id']}"
            ).status_code
            == 200
        )
        players.append(player)

    response = admin.post(f"/groups/{group_id}/generate-teams")
    assert response.status_code == 200, response.text

    return players


def start_game_day(admin: Actor, group_id: str) -> dict:
    """Take a group from an empty scheduled day to a live one."""

    response = admin.post(f"/groups/{group_id}/game/start")
    assert response.status_code == 200, response.text
    return response.json()


def team_players(day: dict, team_name: str) -> list[dict]:
    return next(item["players"] for item in day["teams"] if item["name"] == team_name)


def score_goal(
    admin: Actor,
    group_id: str,
    match_id: str,
    team_name: str,
    scorer_id: str,
    assist_id: str | None = None,
) -> dict:
    response = admin.post(
        f"/groups/{group_id}/matches/{match_id}/goals",
        json={
            "team_name": team_name,
            "scorer_membership_id": scorer_id,
            "assist_membership_id": assist_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def play_match(
    admin: Actor,
    group_id: str,
    day: dict,
    match_id: str,
    goals: list[tuple[str, int]],
) -> dict:
    """Kick off a match, score `goals` as (team, count) pairs, and complete it.

    Scorers are picked from the team's line-up so the credited player is always
    somebody actually playing for that team.
    """

    assert (
        admin.post(f"/groups/{group_id}/matches/{match_id}/start").status_code
        == 200
    )

    latest = day

    for team_name, count in goals:
        squad = team_players(day, team_name)

        for index in range(count):
            latest = score_goal(
                admin,
                group_id,
                match_id,
                team_name,
                squad[index % len(squad)]["id"],
            )

    response = admin.post(f"/groups/{group_id}/matches/{match_id}/complete")
    assert response.status_code == 200, response.text

    return response.json()


def join_group(admin: Actor, member: Actor, group_id: str) -> str:
    """Run the full request/approve flow and return the new membership id."""

    assert member.post(f"/groups/{group_id}/join-request").status_code == 200

    pending = admin.get(f"/groups/{group_id}/join-requests").json()
    request_id = next(item["id"] for item in pending if item["user_id"] == str(member.id))

    assert (
        admin.post(
            f"/groups/{group_id}/join-requests/{request_id}/approve"
        ).status_code
        == 200
    )

    status = member.get(f"/groups/{group_id}/membership-status").json()
    assert status["state"] == "member"

    return status["membership_id"]
