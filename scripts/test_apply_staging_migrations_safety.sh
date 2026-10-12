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

# Never let real credentials from the environment reach this suite.
unset LINEAPP_STAGING_DATABASE_URL LINEAPP_STAGING_PROJECT_REF LINEAPP_FORBIDDEN_PROJECT_REF LINEAPP_ALLOW_STAGING_MIGRATE

# shellcheck source=/dev/null
source "$TARGET"

STG='stagingref0123456789'
PRD='prodref0123456789abc'
OTHER='otherref0123456789ab'
POOLER_HOST='aws-0-ap-northeast-1.pooler.supabase.com'
DIRECT_URL="postgresql://postgres:pw@db.$STG.supabase.co:5432/postgres"
POOLER_URL="postgresql://postgres.$STG:pw@$POOLER_HOST:5432/postgres"

# --- extract_project_ref: accepted forms ---
expect_ref() {
  local name="$1" url="$2" want="$3" got
  if got="$(extract_project_ref "$url" 2>/dev/null)" && [[ "$got" == "$want" ]]; then
    pass "$name"
  else
    fail_test "$name (got: '${got:-<rejected>}')"
  fi
}

expect_reject() {
  local name="$1" url="$2" got
  if got="$(extract_project_ref "$url" 2>/dev/null)"; then
    fail_test "$name (expected rejection, got ref '$got')"
  else
    pass "$name"
  fi
}

expect_ref "direct db.<ref>.supabase.co:5432" "$DIRECT_URL" "$STG"
expect_ref "postgres:// scheme accepted" "postgres://postgres:pw@db.$STG.supabase.co:5432/postgres" "$STG"
expect_ref "session pooler postgres.<ref>@...:5432" "$POOLER_URL" "$STG"
expect_ref "pooler ref parsed from username, not password" \
  "postgresql://postgres.$STG:postgres.$PRD@$POOLER_HOST:5432/postgres" "$STG"
expect_ref "pooler user without password" "postgresql://postgres.$STG@$POOLER_HOST:5432/postgres" "$STG"
expect_ref "percent-encoded '@' in password" "postgresql://postgres.$STG:p%40ss@$POOLER_HOST:5432/postgres" "$STG"
expect_ref "allowed sslmode param" "$POOLER_URL?sslmode=require" "$STG"
expect_ref "other pooler region/shard" "postgresql://postgres.$STG:pw@aws-1-eu-central-1.pooler.supabase.com:5432/postgres" "$STG"

# --- extract_project_ref: port rules ---
expect_reject "pooler Transaction mode port 6543 rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST:6543/postgres"
expect_reject "pooler without explicit port rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST/postgres"
expect_reject "direct port 6543 rejected" "postgresql://postgres:pw@db.$STG.supabase.co:6543/postgres"
expect_reject "direct without explicit port rejected" "postgresql://postgres:pw@db.$STG.supabase.co/postgres"
expect_reject "non-numeric port rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST:5432x/postgres"

# --- extract_project_ref: username rules ---
expect_reject "pooler with bare 'postgres' user rejected" "postgresql://postgres:pw@$POOLER_HOST:5432/postgres"
expect_reject "pooler with non-postgres user rejected" "postgresql://admin.$STG:pw@$POOLER_HOST:5432/postgres"
expect_reject "pooler ref too short rejected" "postgresql://postgres.abc123:pw@$POOLER_HOST:5432/postgres"
expect_reject "pooler uppercase ref rejected" "postgresql://postgres.STAGINGREF0123456789:pw@$POOLER_HOST:5432/postgres"
expect_reject "direct with postgres.<ref> user rejected" "postgresql://postgres.$OTHER:pw@db.$STG.supabase.co:5432/postgres"

# --- extract_project_ref: host rules ---
expect_reject "localhost rejected" "postgresql://postgres:pw@127.0.0.1:5432/postgres"
expect_reject "direct lookalike suffix rejected" "postgresql://postgres:pw@db.$STG.supabase.co.evil.com:5432/postgres"
expect_reject "pooler lookalike suffix rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST.evil.io:5432/postgres"
expect_reject "arbitrary *supabase.com host rejected" "postgresql://postgres.$STG:pw@evilsupabase.com:5432/postgres"
expect_reject "non-pooler supabase.com subdomain rejected" "postgresql://postgres.$STG:pw@api.supabase.com:5432/postgres"
expect_reject "multi-host list rejected" "postgresql://postgres:pw@db.$STG.supabase.co:5432,db.$PRD.supabase.co:5432/postgres"
expect_reject "direct ref wrong length rejected" "postgresql://postgres:pw@db.abcdefghijklmnop.supabase.co:5432/postgres"

# --- extract_project_ref: structure rules ---
expect_reject "wrong scheme rejected" "mysql://postgres:pw@db.$STG.supabase.co:5432/postgres"
expect_reject "two '@' rejected" "postgresql://postgres.$STG:p@ss@$POOLER_HOST:5432/postgres"
expect_reject "'/' in password rejected" "postgresql://postgres.$STG:p/ss@$POOLER_HOST:5432/postgres"
expect_reject "database other than postgres rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST:5432/other"
expect_reject "missing database rejected" "postgresql://postgres.$STG:pw@$POOLER_HOST:5432"
expect_reject "host= query override rejected" "$POOLER_URL?host=db.$PRD.supabase.co"
expect_reject "hostaddr= query override rejected" "$POOLER_URL?sslmode=require&hostaddr=10.0.0.1"
expect_reject "user= query override rejected" "$POOLER_URL?user=postgres.$PRD"

if err="$(extract_project_ref "postgresql://postgres.$STG:s3cretpw@$POOLER_HOST:6543/postgres" 2>&1 >/dev/null)"; then
  fail_test "rejection message test (unexpected success)"
elif [[ "$err" == *s3cretpw* ]]; then
  fail_test "rejection message leaks password"
elif [[ "$err" == *"Session Pooler"* ]]; then
  pass "6543 rejection explains Session Pooler requirement without leaking password"
else
  fail_test "6543 rejection message unclear: $err"
fi

# --- verify_staging_identity (no psql) ---
export LINEAPP_ALLOW_STAGING_MIGRATE=yes
export LINEAPP_STAGING_PROJECT_REF="$STG"
export LINEAPP_FORBIDDEN_PROJECT_REF="$PRD"
export LINEAPP_STAGING_DATABASE_URL="$DIRECT_URL"

if ( verify_staging_identity >/dev/null 2>&1 ); then
  pass "identity OK for matching direct staging URI"
else
  fail_test "identity matching direct staging URI"
fi

export LINEAPP_STAGING_DATABASE_URL="$POOLER_URL"
if ( verify_staging_identity >/dev/null 2>&1 ); then
  pass "identity OK for matching Session Pooler staging URI"
else
  fail_test "identity matching Session Pooler staging URI"
fi

export LINEAPP_STAGING_DATABASE_URL="postgresql://postgres.$STG:pw@$POOLER_HOST:6543/postgres"
run_expect_fail "identity rejects Transaction Pooler URI" verify_staging_identity
export LINEAPP_STAGING_DATABASE_URL="$POOLER_URL"

export LINEAPP_STAGING_PROJECT_REF="$OTHER"
run_expect_fail "identity rejects URI/ref mismatch" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF="$STG "
run_expect_fail "identity rejects staging ref with trailing space" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF="https://supabase.com/dashboard/project/$STG"
run_expect_fail "identity rejects pasted dashboard URL as ref" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF="$STG"
export LINEAPP_FORBIDDEN_PROJECT_REF=" $PRD"
run_expect_fail "identity rejects malformed forbidden ref" verify_staging_identity
export LINEAPP_FORBIDDEN_PROJECT_REF="$PRD"

export LINEAPP_STAGING_DATABASE_URL="postgresql://postgres.$PRD:pw@$POOLER_HOST:5432/postgres"
run_expect_fail "identity rejects production pooler URI" verify_staging_identity

export LINEAPP_STAGING_DATABASE_URL="postgresql://postgres:pw@db.$PRD.supabase.co:5432/postgres"
run_expect_fail "identity rejects production direct URI" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF="$PRD"
run_expect_fail "identity rejects staging ref set to production ref" verify_staging_identity

export LINEAPP_STAGING_PROJECT_REF="$STG"
export LINEAPP_STAGING_DATABASE_URL='postgresql://postgres:pw@127.0.0.1:5432/postgres'
run_expect_fail "identity rejects unparseable URI" verify_staging_identity

export LINEAPP_STAGING_DATABASE_URL="$POOLER_URL"
unset LINEAPP_ALLOW_STAGING_MIGRATE
run_expect_fail "identity requires LINEAPP_ALLOW_STAGING_MIGRATE=yes to migrate" verify_staging_identity
if ( verify_staging_identity preflight >/dev/null 2>&1 ); then
  pass "preflight identity does not require migrate approval"
else
  fail_test "preflight identity should not require migrate approval"
fi
export LINEAPP_ALLOW_STAGING_MIGRATE=yes

unset LINEAPP_FORBIDDEN_PROJECT_REF
run_expect_fail "identity requires forbidden ref" verify_staging_identity
export LINEAPP_FORBIDDEN_PROJECT_REF="$PRD"

# --- mock psql ---
MOCK_DIR="$(mktemp -d)"
trap 'rm -rf "$MOCK_DIR"' EXIT
export MOCK_LOG="$MOCK_DIR/calls.log"
cat >"$MOCK_DIR/psql" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
sql=""
file=""
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    -c) sql="${args[$((i + 1))]}" ;;
    -f) file="${args[$((i + 1))]}" ;;
  esac
done
if [[ -z "$sql" && -z "$file" ]]; then
  sql="$(cat)"
fi
flat_args="$*"
printf 'CALL args=[%s] PGOPTIONS=[%s] PGHOSTADDR=[%s]\n' "${flat_args//$'\n'/ }" "${PGOPTIONS:-}" "${PGHOSTADDR:-}" >>"$MOCK_LOG"

if [[ "${MOCK_PSQL_FAIL:-}" == "1" ]]; then
  exit 2
fi

if [[ -n "$file" ]]; then
  if [[ "$file" == *verify_schema.sql ]]; then
    printf 'VERIFY\n' >>"$MOCK_LOG"
    if [[ "${MOCK_VERIFY_ISSUES:-}" == "1" ]]; then
      echo "missing table|profiles"
    fi
    exit 0
  fi
  name="$(basename "$file")"
  printf 'MIGRATION %s\n' "$name" >>"$MOCK_LOG"
  if [[ -n "${MOCK_MIGRATION_FAIL:-}" && "$name" == "$MOCK_MIGRATION_FAIL" ]]; then
    exit 3
  fi
  exit 0
fi

case "$sql" in
  *string_agg*)
    echo "${MOCK_BASELINE:-games:t,groups:t,join_requests:t,memberships:t,profiles:t,registrations:t,team_assignments:t}" ;;
  *memberships_rating_range*)
    echo "${MOCK_M2:-0}" ;;
  *"count(*) from public.memberships"*)
    [[ "${MOCK_MEMBERSHIPS_FAIL:-}" == "1" ]] && exit 2
    echo "${MOCK_MEMBERSHIPS:-0}" ;;
  *"to_regclass('public.game_days')"*)
    echo "${MOCK_GAME_DAYS:-f}" ;;
  *"to_regclass('public.games')"*)
    echo "${MOCK_GAMES:-t}" ;;
  *"to_regnamespace('private')"*)
    echo "${MOCK_PRIVATE:-f}" ;;
  *lineapp_read_group*)
    echo "${MOCK_READ_GROUP:-f}" ;;
  *)
    echo "mock psql: unexpected SQL: $sql" >&2
    exit 9 ;;
esac
MOCK
chmod +x "$MOCK_DIR/psql"

export PATH="$MOCK_DIR:$PATH"
# Guard: these tests must never reach a real database.
[[ "$(command -v psql)" == "$MOCK_DIR/psql" ]] || { echo "mock psql not first on PATH; aborting" >&2; exit 1; }
# shellcheck disable=SC2034 # read by the sourced runner functions
PSQL=(psql "$LINEAPP_STAGING_DATABASE_URL" -X -v ON_ERROR_STOP=1 -q)

# --- run_verify_schema ---
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

if ( run_verify_schema >/dev/null 2>&1 ); then
  pass "verify PASS on empty output"
else
  fail_test "verify should PASS on empty output"
fi

# --- resolve_migration2_start: stdout must be exactly the start value ---
expect_start() {
  local name="$1" m2="$2" want="$3" out err
  err="$MOCK_DIR/stderr.txt"
  if out="$(MOCK_M2="$m2" resolve_migration2_start 2>"$err")" && [[ "$out" == "$want" ]]; then
    if grep -q "Migration 2:" "$err"; then
      pass "$name"
    else
      fail_test "$name (log line missing from stderr)"
    fi
  else
    fail_test "$name (stdout: '$out')"
  fi
}
expect_start "migration 2 not applied -> captured start is exactly '2'" 0 2
expect_start "migration 2 applied -> captured start is exactly '3'" 12 3

if ( MOCK_M2=5 resolve_migration2_start >/dev/null 2>&1 ); then
  fail_test "partial migration 2 should fail"
else
  pass "partial migration 2 (5/12 markers) fails"
fi
if ( MOCK_M2=garbage resolve_migration2_start >/dev/null 2>&1 ); then
  fail_test "non-numeric marker count should fail"
else
  pass "non-numeric migration 2 marker count fails"
fi
if ( MOCK_M2=12 MOCK_GAMES=f resolve_migration2_start >/dev/null 2>&1 ); then
  fail_test "migration 2 complete without games should fail"
else
  pass "migration 2 complete but games missing fails"
fi

# --- main (end-to-end against mock psql) ---
ALL_MIGRATIONS=(
  20260909120100_integrity_constraints_and_indexes.sql
  20260909120200_rls_lockdown.sql
  20260909120300_admin_and_virtual_player_guards.sql
  20260909170000_private_group_access_helpers.sql
  20260909180000_beta_game_days.sql
  20260909190000_read_group_rpc.sql
  20260910130000_finished_game_day_payload.sql
  20260910140000_half_step_survey_ratings.sql
  20260910150000_virtual_members_never_admin.sql
  20260916200000_game_day_guests.sql
  20260923064000_group_messages.sql
  20261002093700_goalkeeper_ratings.sql
  20261004103000_match_goal_events.sql
)

run_main() {
  : >"$MOCK_LOG"
  bash "$TARGET" "$@" >"$MOCK_DIR/main.out" 2>&1
}

migrations_run() { sed -n 's/^MIGRATION //p' "$MOCK_LOG"; }
psql_calls() { grep -c '^CALL' "$MOCK_LOG" || true; }

if run_main; then
  expected="$(printf '%s\n' "${ALL_MIGRATIONS[@]}")"
  if [[ "$(migrations_run)" == "$expected" ]] && grep -q '^VERIFY' "$MOCK_LOG"; then
    pass "main: fresh Staging runs migrations 2..14 in order, then verify"
  else
    fail_test "main: fresh Staging migration order wrong: $(migrations_run | tr '\n' ' ')"
  fi
  if grep -q "from step 2 through 14" "$MOCK_DIR/main.out"; then
    pass "main: plan reports start step 2"
  else
    fail_test "main: plan should report start step 2"
  fi
else
  fail_test "main: fresh Staging should succeed ($(tail -1 "$MOCK_DIR/main.out"))"
fi

if MOCK_M2=12 run_main; then
  expected="$(printf '%s\n' "${ALL_MIGRATIONS[@]:1}")"
  if [[ "$(migrations_run)" == "$expected" ]]; then
    pass "main: migration 2 already applied -> runs 3..14 only"
  else
    fail_test "main: skip-2 order wrong: $(migrations_run | tr '\n' ' ')"
  fi
else
  fail_test "main: migration-2-applied Staging should succeed ($(tail -1 "$MOCK_DIR/main.out"))"
fi

if grep '^CALL' "$MOCK_LOG" | grep -qv -- ' -X '; then
  fail_test "main: every psql call must use -X (ignore ~/.psqlrc)"
else
  pass "main: every psql call uses -X"
fi

if PGHOSTADDR=10.9.9.9 PGOPTIONS='-c search_path=evil' run_main; then
  if grep -q 'PGHOSTADDR=\[10.9.9.9\]' "$MOCK_LOG" || grep -q 'search_path=evil' "$MOCK_LOG"; then
    fail_test "main: ambient PG* variables leaked into psql"
  else
    pass "main: ambient PGHOSTADDR/PGOPTIONS are not passed to psql"
  fi
else
  fail_test "main: run with ambient PG* vars should still succeed"
fi

expect_main_fail_no_migrations() {
  local name="$1"
  shift
  if run_main_env "$@"; then
    fail_test "$name (expected failure)"
  elif [[ -n "$(migrations_run)" ]]; then
    fail_test "$name (migrations ran: $(migrations_run | tr '\n' ' '))"
  else
    pass "$name"
  fi
}
run_main_env() { : >"$MOCK_LOG"; env "$@" bash "$TARGET" >"$MOCK_DIR/main.out" 2>&1; }

expect_main_fail_no_migrations "main: memberships with rows blocks before any migration" MOCK_MEMBERSHIPS=3
if grep -q "public.memberships has 3 rows" "$MOCK_DIR/main.out"; then
  pass "main: memberships failure message reports row count"
else
  fail_test "main: memberships failure message missing row count"
fi
expect_main_fail_no_migrations "main: memberships count query error blocks" MOCK_MEMBERSHIPS_FAIL=1
expect_main_fail_no_migrations "main: non-numeric memberships count blocks" MOCK_MEMBERSHIPS=abc
expect_main_fail_no_migrations "main: missing baseline table blocks" \
  MOCK_BASELINE='games:t,groups:t,join_requests:t,memberships:f,profiles:t,registrations:t,team_assignments:t'
expect_main_fail_no_migrations "main: legacy 'true' baseline output is not accepted as 't'" \
  MOCK_BASELINE='games:true,groups:true,join_requests:true,memberships:true,profiles:true,registrations:true,team_assignments:true'
expect_main_fail_no_migrations "main: short baseline list blocks" MOCK_BASELINE='games:t'
expect_main_fail_no_migrations "main: game_days present (already migrated) blocks" \
  MOCK_GAME_DAYS=t MOCK_GAMES=f MOCK_PRIVATE=t MOCK_READ_GROUP=t
expect_main_fail_no_migrations "main: games and game_days both present blocks" MOCK_GAME_DAYS=t
expect_main_fail_no_migrations "main: partial migration 2 blocks" MOCK_M2=7
expect_main_fail_no_migrations "main: psql connection failure blocks" MOCK_PSQL_FAIL=1
expect_main_fail_no_migrations "main: Transaction Pooler URI blocks" \
  LINEAPP_STAGING_DATABASE_URL="postgresql://postgres.$STG:pw@$POOLER_HOST:6543/postgres"
if [[ "$(psql_calls)" == "0" ]]; then
  pass "main: rejected URI never reaches psql"
else
  fail_test "main: rejected URI still invoked psql"
fi
expect_main_fail_no_migrations "main: production URI blocks" \
  LINEAPP_STAGING_DATABASE_URL="postgresql://postgres.$PRD:pw@$POOLER_HOST:5432/postgres"
expect_main_fail_no_migrations "main: missing approval flag blocks" LINEAPP_ALLOW_STAGING_MIGRATE=no
if run_main --bogus; then
  fail_test "main: unknown CLI argument should fail"
else
  if [[ -z "$(migrations_run)" ]]; then
    pass "main: unknown CLI argument fails without migrating"
  else
    fail_test "main: unknown CLI argument ran migrations"
  fi
fi

: >"$MOCK_LOG"
if MOCK_MIGRATION_FAIL=20260909180000_beta_game_days.sql bash "$TARGET" >"$MOCK_DIR/main.out" 2>&1; then
  fail_test "main: failing migration should fail the run"
else
  if [[ "$(migrations_run | tail -1)" == "20260909180000_beta_game_days.sql" ]] && ! grep -q '^VERIFY' "$MOCK_LOG"; then
    pass "main: stops at first failing migration (no later files, no verify)"
  else
    fail_test "main: did not stop at failing migration: $(migrations_run | tr '\n' ' ')"
  fi
fi

if MOCK_VERIFY_ISSUES=1 run_main; then
  fail_test "main: verify issues should fail the run"
else
  pass "main: verify_schema issues fail the run"
fi

# --- preflight-only mode ---
if LINEAPP_ALLOW_STAGING_MIGRATE=no run_main --preflight-only; then
  if [[ -z "$(migrations_run)" ]] && ! grep -q '^VERIFY' "$MOCK_LOG"; then
    pass "preflight-only: passes and applies no migrations"
  else
    fail_test "preflight-only: ran migrations or verify"
  fi
  if grep '^CALL' "$MOCK_LOG" | grep -qv 'PGOPTIONS=\[-c default_transaction_read_only=on\]'; then
    fail_test "preflight-only: every psql session must be read-only"
  else
    pass "preflight-only: every psql session is forced read-only"
  fi
else
  fail_test "preflight-only should pass on fresh Staging ($(tail -1 "$MOCK_DIR/main.out"))"
fi

if MOCK_MEMBERSHIPS=1 run_main --preflight-only; then
  fail_test "preflight-only should fail when memberships has rows"
else
  pass "preflight-only: fails when memberships has rows"
fi

# --- migration uses -1 flag (grep script) ---
if grep -q 'PSQL\[@\].*-1 -f' "$TARGET"; then
  pass "migrations use psql single-transaction (-1)"
else
  fail_test "migrations must use psql -1"
fi

printf '\nResults: %s passed, %s failed\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]]
