from __future__ import annotations

import json
import uuid

import psycopg2


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


def test_migration_backfills_legacy_first_name_without_inventing_last_name(sql):
    with sql.cursor() as cur:
        cur.execute(
            """
            SELECT display_name, first_name, last_name, nickname
            FROM profiles
            WHERE id = '369a716c-95ae-4a4a-ba4e-c916d9c54484'
            """
        )
        assert cur.fetchone() == ("Developer", "Developer", None, None)


def test_private_avatar_bucket_and_storage_policies_are_installed(sql):
    with sql.cursor() as cur:
        cur.execute(
            """
            SELECT public, file_size_limit, allowed_mime_types
            FROM storage.buckets WHERE id = 'player-avatars'
            """
        )
        assert cur.fetchone() == (False, 2097152, ["image/webp"])
        cur.execute(
            """
            SELECT policyname
            FROM pg_policies
            WHERE schemaname = 'storage' AND tablename = 'objects'
            ORDER BY policyname
            """
        )
        assert {row[0] for row in cur.fetchall()} == {
            "group admins delete player avatars",
            "group admins insert player avatars",
            "group admins update player avatars",
            "player avatars read",
            "registered users write own avatar",
        }


def test_avatar_authorization_helpers_scope_reads_and_admin_writes(sql):
    admin_id = create_user(sql, "Ari", "Admin")
    member_id = create_user(sql, "Mia", "Member")
    outsider_id = create_user(sql, "Oren", "Outside")
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO groups (name, created_by, invite_code)
            VALUES ('Avatar FC', %s, 'avatar-test') RETURNING id
            """,
            (str(admin_id),),
        )
        group_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO memberships (
              group_id, user_id, display_name, rating, goalkeeper_rating,
              is_subscriber, is_admin
            )
            VALUES
              (%s, %s, null, 3, 3, false, true),
              (%s, %s, null, 3, 3, false, false),
              (%s, null, 'Virtual', 3, 3, false, false)
            RETURNING id
            """,
            (str(group_id), str(admin_id), str(group_id), str(member_id), str(group_id)),
        )
        rows = cur.fetchall()
        virtual_id = rows[2][0]
        cur.execute("set role authenticated")
        cur.execute(
            "select set_config('request.jwt.claim.sub', %s, false)",
            (str(admin_id),),
        )
        cur.execute(
            "select private.lineapp_can_read_user_avatar(%s)",
            (str(member_id),),
        )
        assert cur.fetchone()[0] is True
        cur.execute(
            "select private.lineapp_can_read_user_avatar(%s)",
            (str(outsider_id),),
        )
        assert cur.fetchone()[0] is False
        cur.execute(
            "select private.lineapp_can_access_member_avatar(%s, %s, true)",
            (str(group_id), str(virtual_id)),
        )
        assert cur.fetchone()[0] is True
        cur.execute(
            """
            INSERT INTO storage.objects (bucket_id, name)
            VALUES ('player-avatars', %s)
            """,
            (f"users/{admin_id}/own.webp",),
        )
        cur.execute(
            """
            INSERT INTO storage.objects (bucket_id, name)
            VALUES ('player-avatars', %s)
            """,
            (f"groups/{group_id}/members/{virtual_id}/virtual.webp",),
        )
        try:
            cur.execute(
                """
                INSERT INTO storage.objects (bucket_id, name)
                VALUES ('player-avatars', %s)
                """,
                (f"users/{outsider_id}/stolen.webp",),
            )
        except psycopg2.errors.InsufficientPrivilege:
            pass
        else:
            raise AssertionError("authenticated user wrote another user's avatar")
        cur.execute("reset role")


def test_new_auth_users_require_structured_names_and_use_nickname(sql):
    with sql.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO auth.users (id, email, raw_user_meta_data)
                VALUES (%s, %s, %s)
                """,
                (str(uuid.uuid4()), f"{uuid.uuid4()}@example.test", json.dumps({"display_name": "Old"})),
            )
        except psycopg2.errors.RaiseException:
            pass
        else:
            raise AssertionError("new Auth user without first/last name was accepted")

    user_id = create_user(sql, "Shai", "Cohen", "Shushu")
    with sql.cursor() as cur:
        cur.execute(
            """
            SELECT display_name, first_name, last_name, nickname
            FROM profiles WHERE id = %s
            """,
            (str(user_id),),
        )
        assert cur.fetchone() == ("Shushu", "Shai", "Cohen", "Shushu")


def test_user_updates_only_their_global_profile(client, sql):
    user_id = create_user(sql, "Noa", "Levi")
    response = call(
        client,
        user_id,
        "PUT",
        "/profile",
        json={"first_name": "Noa", "last_name": "Levi", "nickname": "Nuni"},
    )
    assert response.status_code == 200, response.text
    expected = {
        "display_name": "Nuni",
        "full_name": "Noa Levi",
        "first_name": "Noa",
        "last_name": "Levi",
        "nickname": "Nuni",
        "is_complete": True,
    }
    assert {key: response.json()[key] for key in expected} == expected

    avatar_path = f"users/{user_id}/{uuid.uuid4()}.webp"
    response = call(
        client,
        user_id,
        "PUT",
        "/profile/avatar",
        json={"avatar_path": avatar_path},
    )
    assert response.status_code == 200, response.text
    assert response.json()["avatar_path"] == avatar_path
    assert response.json()["avatar_version"] == 1

    bad = call(
        client,
        user_id,
        "PUT",
        "/profile/avatar",
        json={"avatar_path": f"users/{uuid.uuid4()}/stolen.webp"},
    )
    assert bad.status_code == 400


def test_group_admin_controls_only_virtual_and_guest_avatars(client, sql):
    admin_id = create_user(sql, "Admin", "Owner")
    member_id = create_user(sql, "Real", "Member")
    group = call(client, admin_id, "POST", "/groups", json={"name": "Profiles FC"}).json()
    group_id = group["id"]
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memberships (
              group_id, user_id, rating, goalkeeper_rating, is_subscriber, is_admin
            )
            VALUES (%s, %s, 3, 3, false, false)
            RETURNING id
            """,
            (group_id, str(member_id)),
        )
        real_membership_id = str(cur.fetchone()[0])

    virtual = call(
        client,
        admin_id,
        "POST",
        f"/groups/{group_id}/members",
        json={
            "name": "Virtual V",
            "rating": 3,
            "goalkeeper_rating": 3,
            "is_subscriber": False,
            "is_admin": False,
        },
    ).json()
    avatar_path = (
        f"groups/{group_id}/members/{virtual['id']}/{uuid.uuid4()}.webp"
    )
    response = call(
        client,
        admin_id,
        "PUT",
        f"/groups/{group_id}/members/{virtual['id']}/avatar",
        json={"avatar_path": avatar_path},
    )
    assert response.status_code == 200, response.text
    assert response.json()["avatar_path"] == avatar_path

    forbidden = call(
        client,
        member_id,
        "PUT",
        f"/groups/{group_id}/members/{virtual['id']}/avatar",
        json={"avatar_path": avatar_path},
    )
    assert forbidden.status_code == 403

    registered = call(
        client,
        admin_id,
        "PUT",
        f"/groups/{group_id}/members/{real_membership_id}/avatar",
        json={"avatar_path": None},
    )
    assert registered.status_code == 404


def test_member_payload_uses_name_precedence_and_exposes_current_avatar(client, sql):
    user_id = create_user(sql, "Daniel", "Bar", "Dani")
    group = call(client, user_id, "POST", "/groups", json={"name": "Payload FC"}).json()
    member = next(item for item in group["members"] if item["user_id"] == str(user_id))
    assert member["name"] == "Dani"
    assert member["full_name"] == "Daniel Bar"
    assert member["first_name"] == "Daniel"
    assert member["last_name"] == "Bar"
    assert member["nickname"] == "Dani"
    assert member["avatar_path"] is None


def test_registered_member_search_is_scoped_to_current_group(client, sql):
    admin_id = create_user(sql, "Maya", "Owner")
    teammate_id = create_user(sql, "Jonathan", "Cohen", "Jonny")
    outsider_id = create_user(sql, "Jonathan", "Outside", "Jonny")
    group = call(client, admin_id, "POST", "/groups", json={"name": "Search FC"}).json()
    other_group = call(
        client, outsider_id, "POST", "/groups", json={"name": "Other FC"}
    ).json()
    with sql.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memberships (
              group_id, user_id, rating, goalkeeper_rating, is_subscriber, is_admin
            )
            VALUES (%s, %s, 3, 3, false, false)
            """,
            (group["id"], str(teammate_id)),
        )

    for term in ("Jonathan", "Cohen", "Jonny"):
        response = call(
            client,
            admin_id,
            "GET",
            f"/groups/{group['id']}/members/search",
            params={"q": term},
        )
        assert response.status_code == 200, response.text
        assert [item["user_id"] for item in response.json()] == [str(teammate_id)]

    outsider = call(
        client,
        admin_id,
        "GET",
        f"/groups/{other_group['id']}/members/search",
        params={"q": "Jonny"},
    )
    assert outsider.status_code == 403
