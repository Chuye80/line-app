from __future__ import annotations

import json
import uuid

import psycopg2
import pytest


def create_user(sql, first_name: str, last_name: str, nickname: str | None = None):
    user_id = uuid.uuid4()
    metadata = {"first_name": first_name, "last_name": last_name}
    if nickname:
        metadata["nickname"] = nickname
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO auth.users (id, email, raw_user_meta_data)
            VALUES (%s, %s, %s)
            """,
            (str(user_id), f"{user_id}@example.test", json.dumps(metadata)),
        )
    return user_id


def call(client, user_id, method: str, path: str, **kwargs):
    return client.request(
        method,
        path,
        headers={"X-Test-User": str(user_id)},
        **kwargs,
    )


def _add_member(sql, group_id, user_id, is_admin=False):
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memberships (
              group_id, user_id, rating, goalkeeper_rating, is_subscriber, is_admin
            )
            VALUES (%s, %s, 3, 3, false, %s)
            """,
            (str(group_id), str(user_id), is_admin),
        )


def test_group_picture_is_admin_write_and_member_read(client, sql):
    admin_id = create_user(sql, "Noa", "Admin")
    member_id = create_user(sql, "Itai", "Member")
    outsider_id = create_user(sql, "Ron", "Outside")
    created = call(client, admin_id, "POST", "/groups", json={"name": "Sunday FC"}).json()
    group_id = created["id"]
    assert created["picture_path"] is None
    assert created["picture_version"] == 0
    _add_member(sql, group_id, member_id)
    other = call(client, outsider_id, "POST", "/groups", json={"name": "Other FC"}).json()

    picture_path = f"groups/{group_id}/picture/{uuid.uuid4()}.webp"
    for user_id, status in ((member_id, 403), (outsider_id, 403)):
        denied = call(
            client,
            user_id,
            "PUT",
            f"/groups/{group_id}/picture",
            json={"picture_path": picture_path},
        )
        assert denied.status_code == status

    for bad_path in (
        f"groups/{other['id']}/picture/{uuid.uuid4()}.webp",
        f"groups/{group_id}/members/{uuid.uuid4()}/{uuid.uuid4()}.webp",
        f"groups/{group_id}/picture/nested/{uuid.uuid4()}.webp",
        f"groups/{group_id}/picture/{uuid.uuid4()}.png",
    ):
        invalid = call(
            client,
            admin_id,
            "PUT",
            f"/groups/{group_id}/picture",
            json={"picture_path": bad_path},
        )
        assert invalid.status_code == 400, bad_path

    saved = call(
        client,
        admin_id,
        "PUT",
        f"/groups/{group_id}/picture",
        json={"picture_path": picture_path},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["picture_path"] == picture_path
    assert saved.json()["picture_version"] == 1

    visible = call(client, member_id, "GET", f"/groups/{group_id}")
    assert visible.status_code == 200, visible.text
    assert visible.json()["picture_path"] == picture_path
    assert visible.json()["picture_version"] == 1
    hidden = call(client, outsider_id, "GET", f"/groups/{group_id}")
    assert hidden.status_code == 403

    preview = call(client, outsider_id, "GET", f"/invite/{created['invite_code']}")
    assert preview.status_code == 200, preview.text
    assert "picture_path" not in preview.json()
    assert "picture_version" not in preview.json()

    cleared = call(
        client,
        admin_id,
        "PUT",
        f"/groups/{group_id}/picture",
        json={"picture_path": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["picture_path"] is None
    assert cleared.json()["picture_version"] == 2

    with sql.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(
                "UPDATE groups SET picture_path = %s WHERE id = %s",
                (
                    f"groups/{other['id']}/picture/{uuid.uuid4()}.webp",
                    group_id,
                ),
            )


def test_group_picture_storage_policies_allow_members_to_read_and_admins_to_write(sql):
    admin_id = create_user(sql, "Dana", "Admin")
    member_id = create_user(sql, "Eli", "Member")
    outsider_id = create_user(sql, "Gal", "Outside")
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groups (name, created_by, invite_code)
            VALUES ('Picture FC', %s, 'picture-test') RETURNING id
            """,
            (str(admin_id),),
        )
        group_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO groups (name, created_by, invite_code)
            VALUES ('Other Picture FC', %s, 'picture-other') RETURNING id
            """,
            (str(outsider_id),),
        )
        other_group_id = cur.fetchone()[0]
    _add_member(sql, group_id, admin_id, is_admin=True)
    _add_member(sql, group_id, member_id)
    _add_member(sql, other_group_id, outsider_id, is_admin=True)
    picture = f"groups/{group_id}/picture/{uuid.uuid4()}.webp"

    def as_user(user_id):
        cur.execute("set role authenticated")
        cur.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user_id),))

    with sql.cursor() as cur:
        try:
            as_user(admin_id)
            cur.execute(
                """
                INSERT INTO storage.objects (bucket_id, name)
                VALUES ('player-avatars', %s)
                """,
                (picture,),
            )
            cur.execute("reset role")

            as_user(member_id)
            cur.execute(
                "SELECT count(*) FROM storage.objects WHERE name = %s",
                (picture,),
            )
            assert cur.fetchone()[0] == 1
            try:
                cur.execute(
                    """
                    INSERT INTO storage.objects (bucket_id, name)
                    VALUES ('player-avatars', %s)
                    """,
                    (f"groups/{group_id}/picture/{uuid.uuid4()}.webp",),
                )
            except psycopg2.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("a member wrote the group picture")
            cur.execute("DELETE FROM storage.objects WHERE name = %s", (picture,))
            assert cur.rowcount == 0
            cur.execute("reset role")
            cur.execute(
                "SELECT count(*) FROM storage.objects WHERE name = %s",
                (picture,),
            )
            assert cur.fetchone()[0] == 1

            as_user(outsider_id)
            cur.execute(
                "SELECT count(*) FROM storage.objects WHERE name = %s",
                (picture,),
            )
            assert cur.fetchone()[0] == 0
            try:
                cur.execute(
                    """
                    INSERT INTO storage.objects (bucket_id, name)
                    VALUES ('player-avatars', %s)
                    """,
                    (f"groups/{group_id}/picture/{uuid.uuid4()}.webp",),
                )
            except psycopg2.errors.InsufficientPrivilege:
                pass
            else:
                raise AssertionError("an outsider wrote another group's picture")
            cur.execute("reset role")

            as_user(admin_id)
            cur.execute("DELETE FROM storage.objects WHERE name = %s", (picture,))
            assert cur.rowcount == 1
        finally:
            cur.execute("reset role")
