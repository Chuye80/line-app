-- Row level security lockdown for the PostgREST surface.
--
-- LineApp's data API is the FastAPI service, which connects with the project's
-- privileged Postgres role. The browser only ever uses Supabase for Auth
-- (getSession / onAuthStateChange / signUp / signInWithPassword / signOut) and
-- never issues a PostgREST query.
--
-- The publishable ("anon") key is shipped inside the JavaScript bundle and is
-- therefore public. With RLS disabled, anybody holding that key could read and
-- write every table directly through https://<project>.supabase.co/rest/v1/...,
-- completely bypassing the API's permission checks: full member rosters,
-- ratings, subscriber flags and admin flags of every private group.
--
-- Enabling RLS with no permissive policies denies the PostgREST roles while
-- leaving the backend untouched, because the owning/privileged role bypasses
-- row level security.

do $$
declare
    target text;
begin
    foreach target in array array[
        'profiles',
        'groups',
        'memberships',
        'join_requests',
        'games',
        'registrations',
        'team_assignments'
    ]
    loop
        execute format(
            'alter table public.%I enable row level security',
            target
        );

        -- Remove any table-level grant that would otherwise let PostgREST see
        -- the relation at all. Roles are only present on a real Supabase
        -- project, so skip them when running against a plain Postgres.
        if exists (select 1 from pg_roles where rolname = 'anon') then
            execute format('revoke all on public.%I from anon', target);
        end if;

        if exists (select 1 from pg_roles where rolname = 'authenticated') then
            execute format('revoke all on public.%I from authenticated', target);
        end if;
    end loop;
end;
$$;

-- The sign-up trigger is invoked by Auth internals, never by a client.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        revoke execute on function public.handle_new_user() from anon;
    end if;

    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        revoke execute on function public.handle_new_user() from authenticated;
    end if;
end;
$$;

-- Stop future tables in `public` from being world readable by default.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'anon') then
        alter default privileges in schema public revoke all on tables from anon;
        alter default privileges in schema public revoke all on sequences from anon;
    end if;

    if exists (select 1 from pg_roles where rolname = 'authenticated') then
        alter default privileges in schema public revoke all on tables from authenticated;
        alter default privileges in schema public revoke all on sequences from authenticated;
    end if;
end;
$$;
