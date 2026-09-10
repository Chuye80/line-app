"""Measure the cost of the read path that the frontend polls.

Run from a checkout's root so that `backend` resolves to that checkout:

    .venv/bin/python scripts/measure_read_path.py --label new

Reports, for `GET /groups/{id}`:

* SQL statements issued per request
* calls to Supabase Auth per request
* wall-clock time per request

The scenario is seeded with plain SQL so that both the pre-audit and the
post-audit code measure exactly the same data.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid


def seed(database_url: str) -> tuple[str, str]:
    """A realistic group: 16 members, a full game and generated teams."""

    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    group_id = uuid.uuid4()
    owner_id = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(
            text(
                "truncate team_assignments, registrations, games, join_requests, "
                "memberships, groups, profiles, auth.users restart identity cascade"
            )
        )

        connection.execute(
            text(
                "insert into auth.users (id, email, raw_user_meta_data) values "
                "(:id, 'owner@test.dev', jsonb_build_object('display_name', 'Owner'))"
            ),
            {"id": str(owner_id)},
        )

        connection.execute(
            text(
                "insert into groups (id, name, created_by) "
                "values (:id, 'Perf Group', :owner)"
            ),
            {"id": str(group_id), "owner": str(owner_id)},
        )

        connection.execute(
            text(
                "insert into memberships (group_id, user_id, rating, is_admin) "
                "values (:group_id, :user_id, 3, true)"
            ),
            {"group_id": str(group_id), "user_id": str(owner_id)},
        )

        # Fifteen further real accounts, so every row needs a profile lookup.
        for index in range(15):
            member_id = uuid.uuid4()
            connection.execute(
                text(
                    "insert into auth.users (id, email, raw_user_meta_data) values "
                    "(:id, :email, jsonb_build_object('display_name', :name))"
                ),
                {
                    "id": str(member_id),
                    "email": f"player{index}@test.dev",
                    "name": f"Player {index:02d}",
                },
            )
            connection.execute(
                text(
                    "insert into memberships (group_id, user_id, rating) "
                    "values (:group_id, :user_id, :rating)"
                ),
                {
                    "group_id": str(group_id),
                    "user_id": str(member_id),
                    "rating": (index % 5) + 1,
                },
            )

        game_id = uuid.uuid4()
        connection.execute(
            text(
                "insert into games "
                "(id, group_id, game_datetime, regular_registration_opens) values "
                "(:id, :group_id, now() + interval '48 hours', "
                " now() - interval '1 hour')"
            ),
            {"id": str(game_id), "group_id": str(group_id)},
        )

        membership_ids = [
            row[0]
            for row in connection.execute(
                text(
                    "select id from memberships where group_id = :group_id "
                    "order by created_at"
                ),
                {"group_id": str(group_id)},
            )
        ]

        for position, membership_id in enumerate(membership_ids):
            connection.execute(
                text(
                    "insert into registrations (game_id, membership_id, status) "
                    "values (:game_id, :membership_id, :status)"
                ),
                {
                    "game_id": str(game_id),
                    "membership_id": str(membership_id),
                    "status": "participant" if position < 12 else "waiting",
                },
            )

        for position, membership_id in enumerate(membership_ids[:12]):
            connection.execute(
                text(
                    "insert into team_assignments (game_id, membership_id, team_name) "
                    "values (:game_id, :membership_id, :team_name)"
                ),
                {
                    "game_id": str(game_id),
                    "membership_id": str(membership_id),
                    "team_name": ["Team A", "Team B", "Team C"][position // 4],
                },
            )

    engine.dispose()
    return str(group_id), str(owner_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument(
        "--scenario",
        choices=("read", "register"),
        default="read",
        help="read: GET /groups/{id}. register: POST a registration.",
    )
    parser.add_argument(
        "--auth-latency-ms",
        type=float,
        default=0.0,
        help=(
            "Simulated round-trip to Supabase Auth. The default of 0 measures "
            "only the application's own work."
        ),
    )
    args = parser.parse_args()

    database_url = os.environ["DATABASE_URL"]
    group_id, owner_id = seed(database_url)

    auth_calls = {"count": 0}

    # Stand in for Supabase Auth so the two checkouts are compared on their own
    # behaviour rather than on network weather. Each call is counted.
    class FakeResponse:
        status = 200
        status_code = 200

        def read(self):
            return json.dumps({"id": owner_id, "email": "owner@test.dev"}).encode()

        def json(self):
            return {"id": owner_id, "email": "owner@test.dev"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    import urllib.request

    def record_auth_call():
        auth_calls["count"] += 1

        if args.auth_latency_ms:
            time.sleep(args.auth_latency_ms / 1000)

    def fake_urlopen(*a, **kw):
        record_auth_call()
        return FakeResponse()

    urllib.request.urlopen = fake_urlopen

    import requests

    original_session_get = requests.Session.get

    def fake_session_get(self, *a, **kw):
        record_auth_call()
        return FakeResponse()

    requests.Session.get = fake_session_get

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    import backend.main as backend_main

    # The pre-audit build verifies the token inside the dependency itself; the
    # post-audit build delegates to backend.auth. Both are reachable from here.
    engine = backend_main.__dict__.get("engine")

    if engine is None:
        from backend.database import engine

    statements = {"count": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def count(conn, cursor, statement, parameters, context, executemany):
        statements["count"] += 1

    client = TestClient(backend_main.app)
    headers = {"Authorization": "Bearer test-token"}

    from sqlalchemy import create_engine, text as sql_text

    admin_engine = create_engine(database_url)

    if args.scenario == "read":
        path = f"/groups/{group_id}"

        def call():
            return client.get(path, headers=headers)

        def reset():
            return None

    else:
        with admin_engine.begin() as connection:
            spare = connection.execute(
                sql_text(
                    "insert into memberships (group_id, display_name, rating) "
                    "values (:group_id, 'Spare', 3) returning id"
                ),
                {"group_id": group_id},
            ).scalar_one()

        path = f"/groups/{group_id}/game/register/{spare}"

        def call():
            return client.post(path, headers=headers)

        def reset():
            with admin_engine.begin() as connection:
                connection.execute(
                    sql_text(
                        "delete from registrations where membership_id = :id"
                    ),
                    {"id": str(spare)},
                )

    # Warm up the connection pool and any caches.
    reset()
    warmup = call()
    assert warmup.status_code == 200, warmup.text

    durations = []
    statements["count"] = 0
    auth_calls["count"] = 0

    for _ in range(args.requests):
        reset()

        # The reset runs on its own engine, so it does not pollute the counters.
        before_statements = statements["count"]
        before_auth = auth_calls["count"]

        started = time.perf_counter()
        response = call()
        elapsed = (time.perf_counter() - started) * 1000

        assert response.status_code == 200, response.text
        durations.append(elapsed)

        statements["count"] = before_statements + (
            statements["count"] - before_statements
        )
        auth_calls["count"] = before_auth + (auth_calls["count"] - before_auth)

    requests.Session.get = original_session_get
    admin_engine.dispose()

    print(
        json.dumps(
            {
                "label": args.label,
                "scenario": args.scenario,
                "requests": args.requests,
                "sql_per_request": statements["count"] / args.requests,
                "auth_calls_per_request": auth_calls["count"] / args.requests,
                "median_ms": round(statistics.median(durations), 3),
                "p95_ms": round(
                    sorted(durations)[int(len(durations) * 0.95) - 1], 3
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
