"""Capacity stays exact when registrations overlap.

The API pool serves at most 12 sessions at once. Fourteen registrations against
a capacity of 12 only overlap if the pool can hand out that many connections,
so the test raises the overflow for this case and then puts it back.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from backend.tests.test_team_captains import create_user

CAPACITY = 12
TOTAL = 14


def test_overlapping_registrations_stay_within_capacity(client, sql, monkeypatch):
    import backend.main as main
    from backend.database import SessionLocal, engine
    from backend.main import CurrentUser, register_member

    admin = create_user(sql, "Admin")
    group_id = client.post(
        "/groups",
        headers={"X-Test-User": str(admin)},
        json={"name": "Capacity FC"},
    ).json()["id"]
    member_ids: list[str] = []
    for index in range(TOTAL):
        created = client.post(
            f"/groups/{group_id}/members",
            headers={"X-Test-User": str(admin)},
            json={"name": f"Player {index + 1:02d}", "rating": 3},
        )
        assert created.status_code == 200, created.text
        member_ids.append(created.json()["id"])
    kickoff = datetime.now(timezone.utc) + timedelta(days=2)
    created_day = client.post(
        f"/groups/{group_id}/game-days",
        headers={"X-Test-User": str(admin)},
        json={
            "game_datetime": kickoff.isoformat(),
            "priority_hours": 168,
            "participant_count": CAPACITY,
            "players_per_team": 6,
        },
    )
    assert created_day.status_code == 200, created_day.text
    game_day_id = created_day.json()["id"]

    # Regular registration is already open: kickoff is in two days and the
    # priority window is 168 hours, so every player is eligible for a spot.
    inside = {"current": 0, "peak": 0}
    critical = {"current": 0, "peak": 0}
    guard = threading.Lock()
    original_get_group = main.get_group_or_404
    original_clear = main.clear_teams

    def tracking_get_group(db, group_id):
        with guard:
            inside["current"] += 1
            inside["peak"] = max(inside["peak"], inside["current"])
        return original_get_group(db, group_id)

    def slow_clear(db, game_day):
        with guard:
            critical["current"] += 1
            critical["peak"] = max(critical["peak"], critical["current"])
        try:
            original_clear(db, game_day)
            # Hold the row lock long enough that the other requests are
            # waiting inside the endpoint, not still starting up.
            time.sleep(0.05)
        finally:
            with guard:
                critical["current"] -= 1
                inside["current"] -= 1

    monkeypatch.setattr(main, "get_group_or_404", tracking_get_group)
    monkeypatch.setattr(main, "clear_teams", slow_clear)

    pool = engine.pool
    previous_overflow = pool._max_overflow
    pool._max_overflow = TOTAL
    barrier = threading.Barrier(TOTAL)

    def register(member_id: str) -> None:
        db = SessionLocal()
        try:
            barrier.wait(timeout=10)
            register_member(
                uuid.UUID(group_id),
                uuid.UUID(game_day_id),
                uuid.UUID(member_id),
                user=CurrentUser(id=admin),
                db=db,
            )
        finally:
            db.close()

    try:
        with ThreadPoolExecutor(max_workers=TOTAL) as executor:
            futures = [executor.submit(register, member_id) for member_id in member_ids]
            for future in futures:
                future.result(timeout=30)
    finally:
        pool._max_overflow = previous_overflow

    assert critical["peak"] == 1

    with sql.cursor() as cur:
        cur.execute(
            """
            SELECT status, count(*)
            FROM registrations
            WHERE game_day_id = %s
            GROUP BY status
            """,
            (game_day_id,),
        )
        counts = dict(cur.fetchall())
        cur.execute(
            """
            SELECT membership_id::text
            FROM registrations
            WHERE game_day_id = %s
            GROUP BY membership_id
            HAVING count(*) > 1
            """,
            (game_day_id,),
        )
        duplicates = cur.fetchall()
        cur.execute(
            """
            SELECT membership_id::text
            FROM registrations
            WHERE game_day_id = %s AND status = 'waiting'
            ORDER BY created_at, id
            """,
            (game_day_id,),
        )
        waiting_before = {row[0] for row in cur.fetchall()}
        cur.execute(
            """
            SELECT membership_id::text
            FROM registrations
            WHERE game_day_id = %s AND status = 'participant'
            """,
            (game_day_id,),
        )
        participants_before = {row[0] for row in cur.fetchall()}
        remove_id = next(iter(participants_before))

    assert counts == {"participant": CAPACITY, "waiting": TOTAL - CAPACITY}
    assert duplicates == []
    assert inside["peak"] == TOTAL

    removed = client.post(
        f"/groups/{group_id}/game-days/{game_day_id}/unregister/{remove_id}",
        headers={"X-Test-User": str(admin)},
    )
    assert removed.status_code == 200, removed.text
    with sql.cursor() as cur:
        cur.execute(
            """
            SELECT status, membership_id::text
            FROM registrations
            WHERE game_day_id = %s
            """,
            (game_day_id,),
        )
        rows = cur.fetchall()
    participants = {member_id for status, member_id in rows if status == "participant"}
    waiting = {member_id for status, member_id in rows if status == "waiting"}
    promoted = participants - (participants_before - {remove_id})
    # Removing one participant promotes exactly one person who was waiting.
    assert len(participants) == CAPACITY
    assert remove_id not in participants
    assert promoted == waiting_before - waiting
    assert len(promoted) == 1
    assert waiting == waiting_before - promoted
