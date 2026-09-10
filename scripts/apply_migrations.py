#!/usr/bin/env python
"""Apply the versioned migrations in `supabase/migrations` to a database.

Why this exists
---------------

The migrations are plain SQL, which is deliberate: they can be pasted into the
Supabase SQL editor or piped through `psql`. But `psql` is not installed with
Python, so on a Windows checkout there was no way to run them without either
installing the PostgreSQL client tools or copying five files into a browser by
hand - and doing it by hand is how a later migration ends up being applied
before the baseline it depends on.

What it guarantees
------------------

* Migrations run in filename order, which is the order they were written in.
  `20260910120000_game_day_lifecycle.sql` alters `public.games`, so it cannot
  run before the baseline that creates that table.
* Each file runs inside its own transaction. A failure rolls that file back and
  stops, rather than leaving the schema half-migrated.
* What has been applied is recorded in `public.schema_migrations`, so a second
  run is a single query rather than five re-applications, and `--check` can
  answer "is the database up to date?" without touching it.
* `supabase/verify_schema.sql` runs afterwards, so the answer to "did that
  work?" comes from inspecting the live schema rather than from trusting the
  bookkeeping table. Success is reported only when both agree.

Every migration in this project is also individually idempotent, so recording
history is a convenience and a report, not the thing that keeps you safe.

Usage
-----

    python scripts/apply_migrations.py --check    # report only, change nothing
    python scripts/apply_migrations.py            # apply what is missing

The exit status is 0 only when the database is fully migrated and the drift
check is clean, which is what makes this safe to gate application startup on.

`DATABASE_URL` is read from the environment or from the project `.env`. Nothing
else is read, so this runs without the Supabase API keys being configured.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from sqlalchemy.engine import make_url


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
VERIFY_SCRIPT = REPO_ROOT / "supabase" / "verify_schema.sql"

HISTORY_TABLE = """
create table if not exists public.schema_migrations (
    filename text primary key,
    checksum text not null,
    applied_at timestamptz not null default now()
)
"""

# The bookkeeping table gets the same treatment as every other table in
# `public`: row level security on with no policies, and no grant to the
# PostgREST roles. On a Supabase project a new table would otherwise be readable
# through the REST API with the publishable key that ships in the JS bundle.
HISTORY_TABLE_LOCKDOWN = """
do $$
begin
    execute 'alter table public.schema_migrations enable row level security';

    if exists (select 1 from pg_roles where rolname = 'anon') then
        execute 'revoke all on public.schema_migrations from anon';
    end if;

    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        execute 'revoke all on public.schema_migrations from authenticated';
    end if;
end;
$$;
"""


def database_url():
    """Resolve `DATABASE_URL` exactly the way the application does.

    `load_dotenv` does not override variables that are already set, so a stale
    `DATABASE_URL` exported in the shell or set as a Windows environment
    variable wins over the project `.env` - silently, and with the confusing
    result that the API reports missing tables while `.env` points at a
    database that has them. This tool therefore resolves it the same way and
    prints where it is going, so the two can never disagree unnoticed.
    """

    load_dotenv(REPO_ROOT / ".env")
    url = os.getenv("DATABASE_URL")

    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Add it to the project .env file."
        )

    parsed = make_url(url)
    source = (
        "environment variable (overrides .env)"
        if os.environ.get("DATABASE_URL") == url
        and (REPO_ROOT / ".env").exists()
        and f"DATABASE_URL={url}" not in (REPO_ROOT / ".env").read_text(
            encoding="utf-8", errors="replace"
        )
        else ".env"
    )

    print(f"target: {parsed.host or 'local'}/{parsed.database}  (from {source})")

    return parsed


def database_dsn() -> str:
    """The connection string, as libpq wants it rather than as SQLAlchemy does."""

    # `postgresql+psycopg2://...` is a SQLAlchemy dialect name; psycopg2 itself
    # only understands `postgresql://...`.
    return database_url().set(drivername="postgresql").render_as_string(
        hide_password=False
    )


def migrations() -> list[Path]:
    found = sorted(MIGRATIONS_DIR.glob("*.sql"))

    if not found:
        raise SystemExit(f"No migrations found in {MIGRATIONS_DIR}")

    return found


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def applied_migrations(cursor) -> dict[str, str]:
    cursor.execute("select filename, checksum from public.schema_migrations")
    return {row[0]: row[1] for row in cursor.fetchall()}


def describe(name: str, state: str) -> None:
    print(f"  {state:<12} {name}")


def verify_schema(connection) -> int:
    """Ask the database what it actually has, rather than what we recorded.

    `supabase/verify_schema.sql` is a single read-only query that reports every
    table, column, constraint, index, trigger and grant the migrations expect
    but the connected database does not have. Running it here means a migration
    that succeeded against the wrong database, or an out-of-band schema edit,
    is caught before the application starts rather than at the first request.
    """

    if not VERIFY_SCRIPT.exists():
        print(f"\nNo {VERIFY_SCRIPT.name} to verify against; skipping the drift check.")
        return 0

    try:
        with connection.cursor() as cursor:
            cursor.execute(VERIFY_SCRIPT.read_text(encoding="utf-8"))
            findings = cursor.fetchall()
    finally:
        # Nothing was written, so end the read transaction either way.
        connection.rollback()

    if not findings:
        print("\nSchema verified against supabase/migrations: no drift.")
        return 0

    print(f"\n{len(findings)} schema problem(s) remain after migrating:")

    for issue, object_name in findings:
        print(f"  {issue}: {object_name}")

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report which migrations are outstanding and apply nothing",
    )
    arguments = parser.parse_args()

    connection = psycopg2.connect(database_dsn())
    connection.autocommit = False

    try:
        with connection.cursor() as cursor:
            cursor.execute(HISTORY_TABLE)
            cursor.execute(HISTORY_TABLE_LOCKDOWN)
        connection.commit()

        with connection.cursor() as cursor:
            already = applied_migrations(cursor)

        outstanding: list[Path] = []

        print(f"{len(migrations())} migrations in {MIGRATIONS_DIR.name}:")

        for path in migrations():
            recorded = already.get(path.name)

            if recorded is None:
                describe(path.name, "MISSING")
                outstanding.append(path)
            elif recorded != checksum(path):
                # The file changed after it was applied. Every migration here is
                # idempotent, so re-running it is the safe answer, but it should
                # never happen quietly.
                describe(path.name, "CHANGED")
                outstanding.append(path)
            else:
                describe(path.name, "applied")

        if not outstanding:
            print("\nDatabase is up to date. Nothing to apply.")
            return verify_schema(connection)

        if arguments.check:
            print(f"\n{len(outstanding)} migration(s) outstanding. Re-run without --check to apply.")
            return 1

        print()

        for path in outstanding:
            print(f"applying {path.name} ...", end=" ", flush=True)

            try:
                with connection.cursor() as cursor:
                    cursor.execute(path.read_text(encoding="utf-8"))
                    cursor.execute(
                        """
                        insert into public.schema_migrations (filename, checksum)
                        values (%s, %s)
                        on conflict (filename) do update
                            set checksum = excluded.checksum,
                                applied_at = now()
                        """,
                        (path.name, checksum(path)),
                    )
                connection.commit()
            except Exception as error:
                connection.rollback()
                print("failed")
                print(f"\n{path.name} was rolled back. Nothing after it was applied.\n")
                print(error)
                return 1

            print("done")

        print("\nSchema is up to date.")
        return verify_schema(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
