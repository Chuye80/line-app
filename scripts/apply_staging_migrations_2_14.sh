#!/usr/bin/env bash
# Apply LineApp Staging migrations 2–14 only (never migration 1).
# Requires: psql, LINEAPP_STAGING_DATABASE_URL, LINEAPP_STAGING_PROJECT_REF,
#           LINEAPP_FORBIDDEN_PROJECT_REF (production project ref — never run against it)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIG_DIR="$ROOT/supabase/migrations"
VERIFY_SQL="$ROOT/supabase/verify_schema.sql"

# Migration 2 completion markers (20260909120100_integrity_constraints_and_indexes.sql)
M2_MARKER_COUNT=12

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { printf '%s\n' "$*"; }
fail() { printf "${RED}ERROR:%s${NC}\n" " $*" >&2; exit 1; }

extract_project_ref() {
  local url="$1"
  local host userpart ref

  if [[ "$url" =~ postgres(ql)?://([^@]+)@ ]]; then
    userpart="${BASH_REMATCH[2]}"
    if [[ "$userpart" =~ ^postgres\.([a-z0-9]{15,25})$ ]]; then
      printf '%s' "${BASH_REMATCH[1]}"
      return 0
    fi
  fi

  host="$(printf '%s' "$url" | sed -E 's|^[^@]+@([^:/]+).*$|\1|')"
  if [[ "$host" =~ ^db\.([a-z0-9]+)\.supabase\.co$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi

  if [[ "$host" == *pooler.supabase.com* ]] || [[ "$host" == *supabase.com* ]]; then
    if [[ "$url" =~ postgres\.([a-z0-9]+) ]]; then
      printf '%s' "${BASH_REMATCH[1]}"
      return 0
    fi
  fi

  return 1
}

verify_staging_identity() {
  if [[ "${LINEAPP_ALLOW_STAGING_MIGRATE:-}" != "yes" ]]; then
    fail "Set LINEAPP_ALLOW_STAGING_MIGRATE=yes to confirm you intend to modify Staging only."
  fi

  [[ -n "${LINEAPP_STAGING_DATABASE_URL:-}" ]] \
    || fail "LINEAPP_STAGING_DATABASE_URL is not set (Staging Postgres URI only)."
  [[ -n "${LINEAPP_STAGING_PROJECT_REF:-}" ]] \
    || fail "LINEAPP_STAGING_PROJECT_REF is not set (from Staging dashboard URL)."
  [[ -n "${LINEAPP_FORBIDDEN_PROJECT_REF:-}" ]] \
    || fail "LINEAPP_FORBIDDEN_PROJECT_REF is required (production project ref — used as a deny target)."

  if [[ "$LINEAPP_STAGING_PROJECT_REF" == "$LINEAPP_FORBIDDEN_PROJECT_REF" ]]; then
    fail "Staging project ref must not equal production (LINEAPP_FORBIDDEN_PROJECT_REF)."
  fi

  local url_ref
  if ! url_ref="$(extract_project_ref "$LINEAPP_STAGING_DATABASE_URL")"; then
    fail "Could not extract Supabase project ref from LINEAPP_STAGING_DATABASE_URL. Use a standard Supabase URI (db.<ref>.supabase.co or pooler with user postgres.<ref>)."
  fi

  if [[ "$url_ref" != "$LINEAPP_STAGING_PROJECT_REF" ]]; then
    fail "Connection URI project ref ($url_ref) does not match LINEAPP_STAGING_PROJECT_REF ($LINEAPP_STAGING_PROJECT_REF)."
  fi

  if [[ "$url_ref" == "$LINEAPP_FORBIDDEN_PROJECT_REF" ]]; then
    fail "Connection URI points at forbidden production project ref ($url_ref)."
  fi

  log "Verified target project ref: $url_ref (not production ref)."
}

migration2_marker_count_sql() {
  cat <<'SQL'
select (
  (select count(*) from pg_constraint where conname in (
    'memberships_rating_range',
    'memberships_identity_present',
    'registrations_status_valid',
    'join_requests_status_valid',
    'team_assignments_team_name_valid',
    'groups_name_not_blank',
    'games_priority_window_valid'
  ))
  +
  (select count(*) from pg_indexes where schemaname = 'public' and indexname in (
    'memberships_group_user_unique',
    'registrations_game_membership_unique',
    'team_assignments_game_membership_unique',
    'join_requests_pending_unique'
  ))
  +
  (select case
     when coalesce(
       (select column_default from information_schema.columns
        where table_schema = 'public' and table_name = 'registrations'
          and column_name = 'created_at'),
       ''
     ) like '%clock_timestamp%'
     then 1 else 0 end)
)::text;
SQL
}

resolve_migration2_start() {
  local games_exists m2_count

  games_exists="$("${PSQL[@]}" -t -A -c "select to_regclass('public.games') is not null;")"
  m2_count="$("${PSQL[@]}" -t -A -c "$(migration2_marker_count_sql)")"
  m2_count="${m2_count//[[:space:]]/}"

  if [[ ! "$m2_count" =~ ^[0-9]+$ ]]; then
    fail "Could not read migration 2 marker count from database (got: $m2_count)."
  fi

  if (( m2_count == 0 )); then
    log "Migration 2: not applied (0/$M2_MARKER_COUNT markers)."
    printf '%s' "2"
    return 0
  fi

  if (( m2_count == M2_MARKER_COUNT )); then
    if [[ "$games_exists" != "t" ]]; then
      fail "Migration 2 markers complete but public.games is missing — unexpected state; stop and investigate."
    fi
    log "Migration 2: fully applied ($M2_MARKER_COUNT/$M2_MARKER_COUNT markers). Skipping migration 2."
    printf '%s' "3"
    return 0
  fi

  fail "Migration 2 is partially applied ($m2_count/$M2_MARKER_COUNT markers). Stop — reset Staging or repair manually before re-running."
}

run_verify_schema() {
  local verify_tmp verify_rows psql_status

  verify_tmp="$(mktemp)"
  trap 'rm -f "$verify_tmp"' RETURN

  if ! "${PSQL[@]}" -t -A -f "$VERIFY_SQL" >"$verify_tmp"; then
    fail "verify_schema.sql failed to execute (connection error or SQL error)."
  fi

  verify_rows="$(sed '/^[[:space:]]*$/d' "$verify_tmp")"
  if [[ -n "$verify_rows" ]]; then
    log "${RED}verify_schema.sql: FAIL — issues found:${NC}"
    printf '%s\n' "$verify_rows"
    exit 1
  fi

  log "${GREEN}verify_schema.sql: PASS (no issues reported)${NC}"
}

main() {
  verify_staging_identity

  command -v psql >/dev/null 2>&1 \
    || fail "psql is not installed. Install PostgreSQL client tools or run via Cursor Cloud Agent."

  PSQL=(psql "$LINEAPP_STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -q)

  log "=== Pre-flight: migration 1 state & database consistency ==="

  local preflight_out
  preflight_out="$("${PSQL[@]}" -t -A -F'|' <<'SQL'
select coalesce(string_agg(table_name || ':' || exists::text, ',' order by table_name), '')
from (
  select t.table_name,
         to_regclass('public.' || t.table_name) is not null as exists
  from (values
    ('profiles'), ('groups'), ('memberships'), ('join_requests'),
    ('games'), ('registrations'), ('team_assignments')
  ) as t(table_name)
) s;
SQL
  )" || fail "Pre-flight baseline query failed (connection or SQL error)."

  [[ -n "$preflight_out" ]] || fail "Pre-flight query returned no data."

  local missing_baseline=() part name ok
  IFS=',' read -ra PARTS <<< "$preflight_out"
  for part in "${PARTS[@]}"; do
    name="${part%%:*}"
    ok="${part##*:}"
    if [[ "$ok" != "t" ]]; then
      missing_baseline+=("$name")
    fi
  done

  if ((${#missing_baseline[@]} > 0)); then
    fail "Baseline incomplete (migration 1 missing?). Missing tables: ${missing_baseline[*]}"
  fi

  local game_days_exists games_exists private_schema has_read_group
  game_days_exists="$("${PSQL[@]}" -t -A -c "select to_regclass('public.game_days') is not null;")" \
    || fail "Pre-flight game_days check failed."
  games_exists="$("${PSQL[@]}" -t -A -c "select to_regclass('public.games') is not null;")" \
    || fail "Pre-flight games check failed."
  private_schema="$("${PSQL[@]}" -t -A -c "select to_regnamespace('private') is not null;")" \
    || fail "Pre-flight private schema check failed."
  has_read_group="$("${PSQL[@]}" -t -A -c "select exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = 'lineapp_read_group');")" \
    || fail "Pre-flight lineapp_read_group check failed."

  if [[ "$has_read_group" == "t" && "$game_days_exists" == "t" ]]; then
    fail "Staging already has game_days and lineapp_read_group — migrations 2–14 look complete. Run verify_schema.sql only."
  fi

  if [[ "$game_days_exists" == "t" && "$games_exists" == "t" ]]; then
    fail "Both public.games and public.game_days exist — inconsistent state. Stop and fix Staging before continuing."
  fi

  if [[ "$games_exists" != "t" && "$game_days_exists" != "t" ]]; then
    fail "Neither games nor game_days found — run migration 1 first."
  fi

  if [[ "$game_days_exists" == "t" && "$private_schema" != "t" ]]; then
    fail "game_days exists but private schema missing — partial migration. Reset Staging or get help; do not guess."
  fi

  local start
  start="$(resolve_migration2_start)"

  local migrations=(
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

  log "Will apply migrations from step $start through 14 (${#migrations[@]} files in chain)."
  log ""

  local i idx file path
  for i in "${!migrations[@]}"; do
    idx=$((i + 2))
    file="${migrations[$i]}"
    if (( idx < start )); then
      continue
    fi
    path="$MIG_DIR/$file"
    [[ -f "$path" ]] || fail "Missing file: $path"
    log "=== Running migration $idx/14 (single transaction): $file ==="
    if ! "${PSQL[@]}" -1 -f "$path"; then
      fail "Migration failed: $file — stopped (transaction rolled back). Staging may be unchanged for this file; fix before retrying."
    fi
    log "${GREEN}OK${NC} $file"
  done

  log ""
  log "=== Running verify_schema.sql ==="
  run_verify_schema

  log ""
  log "${GREEN}All requested migrations and verification completed successfully.${NC}"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
