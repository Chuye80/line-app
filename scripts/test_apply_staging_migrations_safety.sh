#!/usr/bin/env bash
# Database-free safety tests for apply_staging_migrations_2_14.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/scripts/apply_staging_migrations_2_14.sh"
PASS=0
FAIL=0

pass() { PASS=$((PASS + 1)); printf 'PASS: %s\n' "$1"; }
fail_test() { FAIL=$((FAIL + 1)); printf 'FAIL: %s\n' "$1" >&2; }

run_expect_fail() {
  local name="$1"
  shift
  if ( "$@" >/dev/null 2>&1 ); then
    fail_test "$name (expected failure, got success)"
  else
    pass "$name"
  fi
}

bash -n "$TARGET" && pass "bash -n syntax check"

# shellcheck source=/dev/null
source "$TARGET"

# --- extract_project_ref ---
[[ "$(extract_project_ref 'postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres')" == "abcdefghijklmnop" ]] \
  && pass "extract direct db.<ref>.supabase.co" \
  || fail_test "extract direct host"

[[ "$(extract_project_ref 'postgresql://postgres.abcdefghijklmnop:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres')" == "abcdefghijklmnop" ]] \
  && pass "extract pooler postgres.<ref> user" \
  || fail_test "extract pooler user"

if extract_project_ref 'postgresql://postgres:pw@127.0.0.1:5432/postgres' 2>/dev/null; then
  fail_test "extract localhost should fail"
else
  pass "extract localhost fails closed"
fi

# --- verify_staging_identity (no psql) ---
export LINEAPP_ALLOW_STAGING_MIGRATE=yes
export LINEAPP_STAGING_PROJECT_REF='stagingref1234567'
export LINEAPP_FORBIDDEN_PROJECT_REF='prodref123456789'
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@db.stagingref1234567.supabase.co:5432/postgres'

if ( verify_staging_identity >/dev/null 2>&1 ); then
  pass "identity OK for matching staging URI"
else
  fail_test "identity matching staging URI"
fi

export LINEAPP_STAGING_PROJECT_REF='wrongref123456789'
run_expect_fail "identity rejects URI/ref mismatch" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF='stagingref1234567'
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@db.prodref123456789.supabase.co:5432/postgres'
run_expect_fail "identity rejects production URI" verify_staging_identity

export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@127.0.0.1:5432/postgres'
run_expect_fail "identity rejects unparseable URI" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF='same1234567890123'
export LINEAPP_FORBIDDEN_PROJECT_REF='same1234567890123'
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@db.same1234567890123.supabase.co:5432/postgres'
run_expect_fail "identity rejects staging=forbidden" verify_staging_identity

unset LINEAPP_FORBIDDEN_PROJECT_REF
export LINEAPP_STAGING_PROJECT_REF='stagingref1234567'
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@db.stagingref1234567.supabase.co:5432/postgres'
run_expect_fail "identity requires forbidden ref" verify_staging_identity

# --- mock psql: verify never PASS on error ---
MOCK_DIR="$(mktemp -d)"
trap 'rm -rf "$MOCK_DIR"' EXIT
cat >"$MOCK_DIR/psql" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${MOCK_PSQL_FAIL:-}" == "1" ]]; then
  exit 2
fi
for arg in "$@"; do
  if [[ "$arg" == *verify_schema.sql ]]; then
    if [[ "${MOCK_VERIFY_ISSUES:-}" == "1" ]]; then
      echo "missing table|profiles"
    fi
    exit 0
  fi
done
exit 0
MOCK
chmod +x "$MOCK_DIR/psql"

export PATH="$MOCK_DIR:$PATH"
export LINEAPP_ALLOW_STAGING_MIGRATE=yes
export LINEAPP_STAGING_PROJECT_REF='stagingref1234567'
export LINEAPP_FORBIDDEN_PROJECT_REF='prodref123456789'
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@db.stagingref1234567.supabase.co:5432/postgres'
PSQL=(psql "$LINEAPP_STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -q)

export MOCK_PSQL_FAIL=1
if ( run_verify_schema >/dev/null 2>&1 ); then
  fail_test "verify treats psql failure as PASS"
else
  pass "verify fails on psql exit 2"
fi
unset MOCK_PSQL_FAIL

export MOCK_VERIFY_ISSUES=1
if ( run_verify_schema >/dev/null 2>&1 ); then
  fail_test "verify treats issue rows as PASS"
else
  pass "verify fails when issue rows present"
fi
unset MOCK_VERIFY_ISSUES
unset MOCK_PSQL_FAIL

if ( run_verify_schema >/dev/null 2>&1 ); then
  pass "verify PASS on empty output"
else
  fail_test "verify should PASS on empty output"
fi

# --- migration uses -1 flag (grep script) ---
grep -q 'PSQL\[@\].*-1 -f' "$TARGET" && pass "migrations use psql single-transaction (-1)" \
  || fail_test "migrations must use psql -1"

printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
