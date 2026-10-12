# Apply Staging migrations 2–14 (simple guide)

This is for the **LineApp Staging** Supabase project only. **Never use production.**

Migration **1 is already done** on Staging (you applied it in the SQL Editor). This process runs migrations **2 through 14** in order, then checks the database.

---

## What you need from Supabase (Staging only)

1. **Project reference (ID)**  
   - Open **LineApp Staging** in the Supabase dashboard.  
   - Look at the browser URL: `https://supabase.com/dashboard/project/XXXXXXXX`  
   - Copy the **`XXXXXXXX`** part — that is your **staging project ref**.

2. **Database connection string (password stays private)**  
   - In Staging: **Project Settings** → **Database** → **Connection string** → **URI**.  
   - Choose **Direct connection** (port **5432**) if available — best for migrations — or the **Session Pooler** (also port **5432**). The **Transaction Pooler (port 6543) is refused** by the script.  
   - Copy the URI. It contains your database password. **Do not paste it into chat, email, or git.**

3. **(Recommended) Production project ref for safety**  
   - Copy the same `XXXXXXXX` from your **production** LineApp project URL.  
   - You will set this as a “forbidden” ref so the script refuses to run against production by mistake.

---

## What to approve

Before anything runs, you (or an operator) confirm:

- [ ] Supabase dashboard shows **LineApp Staging**, not production.  
- [ ] Migration **1** is done (seven tables exist, including `games` — not yet renamed to `game_days`).  
- [ ] You are okay applying migrations **2–14** to **Staging only**.  
- [ ] You will provide the two staging values and production ref via **secrets**, not in the repository.

---

## How automation runs (two options)

### Option A — Cursor Cloud Agent (easiest if you are not a developer)

1. In Cursor, open the **`cursor/staging-db-migrations-7a4d`** branch (or wherever this script lives).  
2. Add **environment secrets** (Cursor cloud / project settings — not committed to git):

   | Secret name | Value |
   |-------------|--------|
   | `LINEAPP_ALLOW_STAGING_MIGRATE` | `yes` |
   | `LINEAPP_STAGING_PROJECT_REF` | Staging `XXXXXXXX` from dashboard URL |
   | `LINEAPP_STAGING_DATABASE_URL` | Staging database URI |
   | `LINEAPP_FORBIDDEN_PROJECT_REF` | Production `XXXXXXXX` (**required**) |

3. Ask the agent: **“Run `scripts/apply_staging_migrations_2_14.sh` on Staging.”**  
4. The agent runs the script once, stops on any error, and reports **`verify_schema.sql`** pass or fail.

### Option B — On your computer (needs PostgreSQL client)

1. Install **PostgreSQL client** (`psql`) if you do not have it.  
2. In a terminal, from the project folder, set the same variables as in the table above (export in the shell — do not save the password in a file).  
3. Run:

   ```bash
   chmod +x scripts/apply_staging_migrations_2_14.sh
   ./scripts/apply_staging_migrations_2_14.sh
   ```

---

## What the script does (safety)

1. **Refuses to run** unless `LINEAPP_ALLOW_STAGING_MIGRATE=yes`.  
2. **Accepts only** these URI shapes (anything else is refused, and the password is never printed):
   - Direct: `postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres`
   - Session Pooler: `postgresql://postgres.<ref>:<pw>@aws-<n>-<region>.pooler.supabase.com:5432/postgres`
   - Port must be **5432**; `<ref>` is 20 lowercase letters/digits; special characters in the password must be percent-encoded; only `sslmode`, `sslrootcert`, `connect_timeout`, `application_name` query parameters are allowed.
3. **Compares** the project ref in the URL with `LINEAPP_STAGING_PROJECT_REF`.  
4. **Blocks** if the ref matches `LINEAPP_FORBIDDEN_PROJECT_REF` (production guard).  
5. **Ignores** ambient `PG*` connection variables and `~/.psqlrc`, so only the verified URI is used.  
6. **Checks** migration 1: all seven baseline tables exist; `games` exists before rename.  
7. **Checks** `public.memberships` has **0 rows**; otherwise stops before any migration.  
8. **Skips migration 2** automatically if it detects migration 2 already applied.  
9. **Runs migrations 2–14** one file at a time; **stops immediately** on the first error.  
10. **Runs** `supabase/verify_schema.sql` — success means **no output rows** (empty result = pass).

### Read-only dry run

`./scripts/apply_staging_migrations_2_14.sh --preflight-only` runs steps 2–8 with every database session forced read-only, prints which migrations would run, and applies nothing. It does not need `LINEAPP_ALLOW_STAGING_MIGRATE`.

### Safety tests (no database needed)

`bash scripts/test_apply_staging_migrations_safety.sh` — uses a mock `psql`; must report `0 failed`.

---

## After success

- Configure Staging **Auth** URLs for your frontend.  
- Point Staging backend `DATABASE_URL` / frontend Supabase keys at **LineApp Staging** only.  
- Optional: add a developer row in SQL Editor after you create a Staging login (see comment in migration 6 file).

---

## If something fails

- **Do not** run the same migration blindly again on production.  
- Note **which filename** failed.  
- Staging may be **half-updated** — fix with Supabase support or reset the Staging database and re-run migration 1, then this script.  
- Production was **not** touched if you used Staging refs and secrets correctly.
