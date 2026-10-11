#!/usr/bin/env bash
# Apply LineApp Staging migrations 2–14 only (never migration 1).
# Requires: psql, LINEAPP_STAGING_DATABASE_URL, LINEAPP_STAGING_PROJECT_REF
#
# Usage (after you approve and set secrets in the environment):
#   export LINEAPP_STAGING_PROJECT_REF='your-staging-ref'
#   export LINEAPP_STAGING_DATABASE_URL='postgresql://...'   # Staging only
#   ./scripts/apply_staging_migrations_2_14.sh
#
# Optional: export LINEAPP_FORBIDDEN_PROJECT_REF='production-ref'  # extra safety

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MIG_DIR="$ROOT/supabase/migrations"
VERIFY_SQL="$ROOT/supabase/verify_schema.sql"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { printf '%s\n' "$*"; }
fail() { printf "${RED}ERROR:%s${NC}\n" " $*" >&2; exit 1; }
warn() { printf "${YELLOW}WARNING:%s${NC}\n" " $*" >&2; }

if [[ "${LINEAPP_ALLOW_STAGING_MIGRATE:-}" != "yes" ]]; then
  fail "Set LINEAPP_ALLOW_STAGING_MIGRATE=yes to confirm you intend to modify Staging only."
fi

[[ -n "${LINEAPP_STAGING_DATABASE_URL:-}" ]] || fail "LINEAPP_STAGING_DATABASE_URL is not set (Staging Postgres URI only)."
[[ -n "${LINEAPP_STAGING_PROJECT_REF:-}" ]] || fail "LINEAPP_STAGING_PROJECT_REF is not set (from Staging dashboard URL)."

if [[ -n "${LINEAPP_FORBIDDEN_PROJECT_REF:-}" ]] \
   && [[ "$LINEAPP_STAGING_PROJECT_REF" == "$LINEAPP_FORBIDDEN_PROJECT_REF" ]]; then
  fail "Staging project ref matches LINEAPP_FORBIDDEN_PROJECT_REF (production guard)."
fi

command -v psql >/dev/null 2>&1 || fail "psql is not installed. Install PostgreSQL client tools or run via Cursor Cloud Agent."

extract_project_ref() {
  local url="$1"
  local host
  host="$(printf '%s' "$url" | sed -E 's|^[^@]+@([^:/]+).*$|\1|')"
  if [[ "$host" =~ ^db\.([a-z0-9]+)\.supabase\.co$ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
    return 0
  fi
  if [[ "$host" =~ pooler\.supabase\.com$ ]] || [[ "$host" =~ \.supabase\.com$ ]]; then
    if [[ "$url" =~ postgres\.([a-z0-9]+) ]]; then
      printf '%s' "${BASH_REMATCH[1]}"
      return 0
    fi
  fi
  return 1
}

URL_REF="$(extract_project_ref "$LINEAPP_STAGING_DATABASE_URL" || true)"
if [[ -z "$URL_REF" ]]; then
  warn "Could not parse project ref from DATABASE URL host; relying on LINEAPP_STAGING_PROJECT_REF only."
elif [[ "$URL_REF" != "$LINEAPP_STAGING_PROJECT_REF" ]]; then
  fail "URL project ref ($URL_REF) does not match LINEAPP_STAGING_PROJECT_REF ($LINEAPP_STAGING_PROJECT_REF)."
fi

if [[ -n "${LINEAPP_FORBIDDEN_PROJECT_REF:-}" ]] && [[ "$URL_REF" == "$LINEAPP_FORBIDDEN_PROJECT_REF" ]]; then
  fail "Database URL points at forbidden production project ref."
fi

PSQL=(psql "$LINEAPP_STAGING_DATABASE_URL" -v ON_ERROR_STOP=1 -q)

log "=== Pre-flight: Staging identity & migration 1 state ==="

PREFLIGHT_OUT="$("${PSQL[@]}" -t -A -F'|' <<'SQL'
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
)"

[[ -n "$PREFLIGHT_OUT" ]] || fail "Pre-flight query returned no data (connection failed?)."

missing_baseline=()
IFS=',' read -ra PARTS <<< "$PREFLIGHT_OUT"
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

GAME_DAYS_EXISTS="$("${PSQL[@]}" -t -A -c "select to_regclass('public.game_days') is not null;")"
GAMES_EXISTS="$("${PSQL[@]}" -t -A -c "select to_regclass('public.games') is not null;")"
HAS_M2="$("${PSQL[@]}" -t -A -c "select exists (select 1 from pg_constraint where conname = 'memberships_rating_range');")"
PRIVATE_SCHEMA="$("${PSQL[@]}" -t -A -c "select to_regnamespace('private') is not null;")"
HAS_READ_GROUP="$("${PSQL[@]}" -t -A -c "select exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = 'lineapp_read_group');")"

if [[ "$HAS_READ_GROUP" == "t" && "$GAME_DAYS_EXISTS" == "t" ]]; then
  fail "Staging already has game_days and lineapp_read_group — migrations 2–14 look complete. Run verify_schema.sql only."
fi

if [[ "$GAME_DAYS_EXISTS" == "t" && "$GAMES_EXISTS" == "t" ]]; then
  fail "Both public.games and public.game_days exist — inconsistent state. Stop and fix Staging before continuing."
fi

[[ "$GAMES_EXISTS" == "t" ]] || [[ "$GAME_DAYS_EXISTS" == "t" ]] \
  || fail "Neither games nor game_days found — run migration 1 first."

if [[ "$GAMES_EXISTS" == "t" ]]; then
  : "Expected path: migration 1 done, migration 6 not yet applied."
elif [[ "$GAME_DAYS_EXISTS" == "t" && "$PRIVATE_SCHEMA" != "t" ]]; then
  fail "game_days exists but private schema missing — partial migration. Reset Staging or get help; do not guess."
fi

START=2
if [[ "$HAS_M2" == "t" && "$GAMES_EXISTS" == "t" ]]; then
  warn "Migration 2 appears already applied (memberships_rating_range). Starting from migration 3."
  START=3
fi

MIGRATIONS=(
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

log "Staging project ref: $LINEAPP_STAGING_PROJECT_REF"
log "Will apply migrations from index $START through 14 (${#MIGRATIONS[@]} files in chain)."
log ""

for i in "${!MIGRATIONS[@]}"; do
  idx=$((i + 2))
  file="${MIGRATIONS[$i]}"
  if (( idx < START )); then
    continue
  fi
  path="$MIG_DIR/$file"
  [[ -f "$path" ]] || fail "Missing file: $path"
  log "=== Running migration $idx/14: $file ==="
  if ! "${PSQL[@]}" -f "$path"; then
    fail "Migration failed: $file — stopped. Staging may be partially migrated; do not run production. Fix or reset Staging before retrying."
  fi
  log "${GREEN}OK${NC} $file"
done

log ""
log "=== Running verify_schema.sql ==="
VERIFY_ROWS="$("${PSQL[@]}" -t -A -f "$VERIFY_SQL" | sed '/^$/d' || true)"
if [[ -z "$VERIFY_ROWS" ]]; then
  log "${GREEN}verify_schema.sql: PASS (no issues reported)${NC}"
else
  log "${RED}verify_schema.sql: FAIL — issues found:${NC}"
  printf '%s\n' "$VERIFY_ROWS"
  exit 1
fi

log ""
log "${GREEN}All requested migrations and verification completed successfully.${NC}"
