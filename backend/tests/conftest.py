"""Integration-test harness: a throwaway local PostgreSQL database built from
supabase/testing/local_auth_stub.sql plus every file in supabase/migrations.

Set LINEAPP_TEST_PG_ADMIN_URL to a *local* server's maintenance database, e.g.
    postgresql://postgres@/postgres?host=/tmp&port=54329
The suite refuses any non-local host so it can never touch Staging/Production.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
AUTH_STUB = ROOT / "supabase" / "testing" / "local_auth_stub.sql"
TEST_DB = "lineapp_pytest"


def _local_admin_url() -> str:
    url = os.getenv("LINEAPP_TEST_PG_ADMIN_URL")
    if not url:
        pytest.skip("LINEAPP_TEST_PG_ADMIN_URL is not set (local PostgreSQL required)")
    parsed = urlparse(url)
    hosts = [parsed.hostname or ""] + parse_qs(parsed.query).get("host", [])
    hosts = [h for h in hosts if h]
    if not hosts or not all(h.startswith("/") or h in ("localhost", "127.0.0.1", "::1") for h in hosts):
        pytest.exit("LINEAPP_TEST_PG_ADMIN_URL must point at a local PostgreSQL server", returncode=2)
    return url


def _with_database(url: str, name: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(path=f"/{name}").geturl()


def _build_database(admin_url: str) -> str:
    admin = psycopg2.connect(admin_url)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{TEST_DB}"')
    admin.close()

    url = _with_database(admin_url, TEST_DB)
    conn = psycopg2.connect(url)
    for path in [AUTH_STUB, *MIGRATIONS]:
        with conn, conn.cursor() as cur:
            cur.execute(path.read_text(encoding="utf-8"))
    conn.close()
    return url


_ADMIN_URL = os.getenv("LINEAPP_TEST_PG_ADMIN_URL")
if _ADMIN_URL:
    _DATABASE_URL = _build_database(_local_admin_url())
    os.environ["DATABASE_URL"] = _DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
    os.environ.setdefault("SUPABASE_URL", "http://supabase.invalid")
    os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "test-key")
    os.environ.pop("ENABLE_DEV_ENDPOINTS", None)


@pytest.fixture(scope="session")
def database_url() -> str:
    _local_admin_url()
    return _DATABASE_URL


@pytest.fixture(scope="session")
def client(database_url):
    from fastapi import Header
    from fastapi.testclient import TestClient

    from backend import main

    def fake_authenticated_user(x_test_user: str | None = Header(default=None)):
        if not x_test_user:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Authentication required")
        return main.CurrentUser(id=uuid.UUID(x_test_user))

    main.app.dependency_overrides[main.get_authenticated_user] = fake_authenticated_user
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


@pytest.fixture
def sql(database_url):
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    yield conn
    conn.close()
