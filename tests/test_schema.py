"""The database, the migrations and the models must agree.

The test database is built by applying `supabase/migrations` to an empty
PostgreSQL, so anything asserted here is a statement about what a fresh
environment produces.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from backend.database import Base, engine
import backend.models  # noqa: F401  (registers the tables on Base.metadata)


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_sql_file(path: Path) -> list[tuple]:
    with engine.begin() as connection:
        return list(connection.execute(text(path.read_text())))


def test_the_live_schema_matches_the_migrations(database):
    """`verify_schema.sql` is the drift check run against the hosted project."""

    findings = run_sql_file(REPO_ROOT / "supabase" / "verify_schema.sql")

    assert findings == [], f"schema drift: {findings}"


def test_migrations_can_be_applied_twice(database):
    """Re-running a migration must never fail, so a partial push can be retried."""

    for migration in sorted(
        (REPO_ROOT / "supabase" / "migrations").glob("*.sql")
    ):
        with engine.begin() as connection:
            connection.execute(text(migration.read_text()))

    findings = run_sql_file(REPO_ROOT / "supabase" / "verify_schema.sql")
    assert findings == []


def test_every_model_table_exists_in_the_database(database):
    inspector = inspect(engine)
    actual = set(inspector.get_table_names(schema="public"))

    assert set(Base.metadata.tables) <= actual


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_model_columns_match_the_database(database, table_name):
    inspector = inspect(engine)

    actual = {
        column["name"]: column
        for column in inspector.get_columns(table_name, schema="public")
    }
    model = Base.metadata.tables[table_name]

    assert set(model.columns.keys()) == set(actual), table_name

    for column in model.columns:
        assert column.nullable == actual[column.name]["nullable"], (
            f"{table_name}.{column.name} nullability differs"
        )


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_model_indexes_exist_in_the_database(database, table_name):
    inspector = inspect(engine)

    actual = {
        index["name"]
        for index in inspector.get_indexes(table_name, schema="public")
    }
    expected = {index.name for index in Base.metadata.tables[table_name].indexes}

    assert expected <= actual, f"{table_name} is missing {expected - actual}"


@pytest.mark.parametrize("table_name", sorted(Base.metadata.tables))
def test_model_check_constraints_exist_in_the_database(database, table_name):
    from sqlalchemy import CheckConstraint

    expected = {
        constraint.name
        for constraint in Base.metadata.tables[table_name].constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }

    with engine.begin() as connection:
        actual = {
            row[0]
            for row in connection.execute(
                text(
                    "select conname from pg_constraint c "
                    "join pg_class r on r.oid = c.conrelid "
                    "join pg_namespace n on n.oid = r.relnamespace "
                    "where n.nspname = 'public' and r.relname = :table"
                ),
                {"table": table_name},
            )
        }

    assert expected <= actual, f"{table_name} is missing {expected - actual}"


def test_row_level_security_is_enabled_on_every_table(database):
    with engine.begin() as connection:
        disabled = [
            row[0]
            for row in connection.execute(
                text(
                    "select c.relname from pg_class c "
                    "join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = 'public' and c.relkind = 'r' "
                    "and not c.relrowsecurity"
                )
            )
        ]

    assert disabled == []


def test_no_permissive_policy_exposes_a_table_to_postgrest(database):
    """The API is the only data path; PostgREST must stay closed."""

    with engine.begin() as connection:
        policies = [
            (row[0], row[1])
            for row in connection.execute(
                text("select tablename, policyname from pg_policies "
                     "where schemaname = 'public'")
            )
        ]

    assert policies == []


def test_registration_timestamps_are_distinct_within_one_transaction(
    database, db, group, group_owner
):
    """Waiting-list order depends on this.

    `now()` is the transaction timestamp, so rows written by one transaction
    would tie and the queue order would be arbitrary.
    """

    from conftest import add_virtual, create_open_game

    create_open_game(group_owner, group["id"])
    group_id = group["id"]

    for index in range(3):
        player = add_virtual(group_owner, group_id, f"P{index}")
        group_owner.post(f"/groups/{group_id}/game/register/{player['id']}")

    timestamps = [
        row[0]
        for row in db.execute(
            text("select created_at from registrations order by created_at")
        )
    ]

    assert len(set(timestamps)) == len(timestamps)


def test_a_fresh_database_can_be_built_from_the_migrations_alone(tmp_path):
    """The whole point of the migration directory."""

    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "reset_test_db.sh"), "lineapp_rebuild_check"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "rebuilt from migrations" in result.stdout
