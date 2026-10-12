# Database migrations

These files are the source of truth for the LineApp PostgreSQL schema on the
`beta-game-days-local` product line (game days, matches, surveys, group chat).

The FastAPI backend connects with the project's privileged Postgres role and
bypasses row level security. The browser uses Supabase for Auth only; RLS and
the `private.*` helpers protect the PostgREST surface exposed by the publishable
key.

## Apply order

Run every file in `migrations/` in **filename order** (timestamp prefix). Do
**not** apply `20260910120000_game_day_lifecycle.sql` from the abandoned audit
branch — it defines an incompatible schema (`games` lifecycle, `player_ratings`
instead of rating surveys).

| Migration | Purpose |
| --- | --- |
| `20260909120000_baseline_schema.sql` | Core tables, `pgcrypto`, sign-up trigger → `profiles` |
| `20260909120100_integrity_constraints_and_indexes.sql` | Domain checks, uniqueness indexes, fair waiting-list timestamps |
| `20260909120200_rls_lockdown.sql` | RLS on core tables; revoke `anon` / `authenticated` table grants |
| `20260909120300_admin_and_virtual_player_guards.sql` | Virtual players cannot be admins; deferred last-admin trigger |
| `20260909170000_private_group_access_helpers.sql` | `private.is_group_member` / `is_group_admin` for RLS policies |
| `20260909180000_beta_game_days.sql` | Game days, matches, surveys, developers table, RLS policies |
| `20260909190000_read_group_rpc.sql` | `lineapp_*` read payload functions |
| `20260910130000_finished_game_day_payload.sql` | `finished_game_day` in `lineapp_read_group` |
| `20260910140000_half_step_survey_ratings.sql` | Half-step survey ratings |
| `20260910150000_virtual_members_never_admin.sql` | Extra virtual-not-admin check |
| `20260916200000_game_day_guests.sql` | Game-day guest memberships |
| `20260923064000_group_messages.sql` | Group chat table and RLS |
| `20261002093700_goalkeeper_ratings.sql` | Separate goalkeeper ratings |
| `20261004103000_match_goal_events.sql` | Goal events as score source of truth |
| `20261012170000_team_captains.sql` | Team captains (`team_assignments.is_captain`), finish-time captain-name snapshot (`game_days.team_captain_names`) |

## Fresh staging / new Supabase project

1. Create the project and configure Auth (Site URL, redirect URLs, email policy).
2. Apply migrations in order (SQL Editor paste per file, or `supabase db push` after linking).
3. Grant developer access manually once a staging user exists (see comment in
   `20260909180000_beta_game_days.sql`).
4. Point backend `DATABASE_URL` at the project; set `SUPABASE_URL` and
   `SUPABASE_PUBLISHABLE_KEY` for Auth verification.

## Drift check

After applying migrations:

```bash
psql "$DATABASE_URL" -f supabase/verify_schema.sql
```

An empty result set means the schema matches this directory.

## Local tests

`supabase/testing/local_auth_stub.sql` is for plain Postgres test harnesses only
( minimal `auth.users` / `auth.uid()` stub ). Never apply it to a hosted Supabase project.

Backend integration tests build a throwaway database from the stub plus every
migration on a **local** PostgreSQL server (non-local hosts are refused):

```bash
pip install -r requirements-dev.txt
LINEAPP_TEST_PG_ADMIN_URL='postgresql://postgres@/postgres?host=/tmp&port=54329' \
  python -m pytest backend/tests
```
