# Database migrations

Before this directory existed the LineApp schema lived only in the hosted
Supabase project. Nothing in version control described it, the SQLAlchemy models
in `backend/models.py` were an incomplete shadow of it (no defaults, no
constraints, no indexes, no policies), and a fresh environment could not be
rebuilt.

These files are the source of truth for the database structure.

## Layout

| File | Purpose |
| --- | --- |
| `20260909120000_baseline_schema.sql` | The structure the application already depended on: tables, foreign keys, the sign-up trigger that populates `public.profiles`. |
| `20260909120100_integrity_constraints_and_indexes.sql` | Value-domain checks, the unique indexes that close the concurrency holes, fair waiting-list ordering, and indexes for the API's real access paths. |
| `20260909120200_rls_lockdown.sql` | Enables row level security and removes the `anon` / `authenticated` grants so the public publishable key cannot read the database through PostgREST. |
| `20260909120300_admin_and_virtual_player_guards.sql` | Virtual players cannot be admins; a group with real members always keeps a real admin. |

Every file is idempotent and safe to re-run. The constraint migrations repair
pre-existing rows that would violate a new rule before installing it, so they
can be applied to the live project without a maintenance window. The repairs
only touch rows that are already invalid.

## Applying to the hosted project

```bash
supabase db push
```

Or paste each file, in filename order, into the SQL editor.

Nothing here drops a column, drops a table or deletes valid data. The only
statements that remove rows are the de-duplication steps in
`20260909120100`, which delete rows that duplicate a row that is kept.

## Rebuilding from scratch locally

`scripts/reset_test_db.sh` creates a database, installs the `auth` stub from
`supabase/testing/local_auth_stub.sql`, and applies every migration in order.
This is what the backend test suite runs against, so the migrations are
exercised on every test run.

## Checking the live project for drift

`supabase/verify_schema.sql` reports anything the migrations expect but the
connected database does not have. Run it against the hosted project after
pushing:

```bash
psql "$DATABASE_URL" -f supabase/verify_schema.sql
```

An empty result means the live schema matches this directory.
