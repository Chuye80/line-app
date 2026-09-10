#!/usr/bin/env bash
#
# Rebuild a local PostgreSQL database from the versioned migrations.
#
# This proves the migrations alone can reproduce the full database structure,
# and gives the backend test suite a real PostgreSQL to run against (the schema
# relies on partial unique indexes, deferred constraint triggers and jsonb, none
# of which SQLite can emulate).
#
# Usage: scripts/reset_test_db.sh [database_name]

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

db_name="${1:-${LINEAPP_TEST_DB:-lineapp_test}}"
db_host="${PGHOST:-127.0.0.1}"
db_port="${PGPORT:-5432}"
db_user="${PGUSER:-lineapp}"
export PGPASSWORD="${PGPASSWORD:-lineapp}"

psql_admin() {
    psql -v ON_ERROR_STOP=1 -q -h "$db_host" -p "$db_port" -U "$db_user" \
        -d postgres "$@"
}

psql_target() {
    psql -v ON_ERROR_STOP=1 -q -h "$db_host" -p "$db_port" -U "$db_user" \
        -d "$db_name" "$@"
}

psql_admin -c "drop database if exists \"$db_name\" with (force)"
psql_admin -c "create database \"$db_name\""

psql_target -f "$repo_root/supabase/testing/local_auth_stub.sql"

for migration in "$repo_root"/supabase/migrations/*.sql; do
    echo "applying $(basename "$migration")"
    psql_target -f "$migration"
done

echo "database $db_name rebuilt from migrations"
