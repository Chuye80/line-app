-- Baseline schema for LineApp.
--
-- This file reconstructs the structure the application code already depends on.
-- Every statement is idempotent so it can be applied to the existing hosted
-- project (where it should be a no-op) and to a brand new environment (where it
-- creates everything from scratch).
--
-- Hardening that the application did not previously have lives in the later
-- migrations in this directory, so that this file stays a faithful description
-- of the pre-audit database.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Reconcile tables left over from an earlier shape of the app
--
-- `create table if not exists` skips a table that already exists whatever
-- shape it is in, so a project carried over from an older version can satisfy
-- everything below and still be missing columns the later migrations depend
-- on. The symptom is obscure: the baseline reports success and the *next*
-- migration fails on something like `column keep.game_id does not exist`.
--
-- An empty leftover table holds nothing worth keeping, so it is dropped here
-- and recreated correctly by the statements that follow. A table with rows in
-- it is a different matter - which column of an unknown shape corresponds to
-- which is not something to guess at when there is data behind the answer - so
-- that stops the migration with a message naming the table and the columns.
-- ---------------------------------------------------------------------------

do $$
declare
    required jsonb := '{
        "profiles":         ["id", "display_name", "created_at"],
        "groups":           ["id", "name", "created_by", "created_at"],
        "memberships":      ["id", "group_id", "user_id", "display_name",
                             "rating", "is_subscriber", "is_admin", "created_at"],
        "join_requests":    ["id", "group_id", "user_id", "status", "created_at"],
        "games":            ["id", "group_id", "game_datetime",
                             "regular_registration_opens", "created_at"],
        "registrations":    ["id", "game_id", "membership_id", "status", "created_at"],
        "team_assignments": ["id", "game_id", "membership_id", "team_name"]
    }'::jsonb;
    tbl text;
    absent text[];
    rows_present bigint;
begin
    for tbl in select jsonb_object_keys(required) loop
        if to_regclass('public.' || quote_ident(tbl)) is null then
            continue;
        end if;

        select array_agg(expected.name order by expected.name)
        into absent
        from jsonb_array_elements_text(required -> tbl) as expected (name)
        where not exists (
            select 1
            from information_schema.columns c
            where c.table_schema = 'public'
              and c.table_name = tbl
              and c.column_name = expected.name
        );

        if absent is null then
            continue;
        end if;

        execute format('select count(*) from public.%I', tbl) into rows_present;

        if rows_present > 0 then
            raise exception
                'public.% has % row(s) but is missing the column(s) %. It predates '
                'this schema and cannot be reconciled automatically without deciding '
                'where that data belongs. Inspect it with scripts/inspect_schema.py.',
                tbl, rows_present, array_to_string(absent, ', ');
        end if;

        raise notice
            'public.% is empty and missing %; recreating it to match the migrations.',
            tbl, array_to_string(absent, ', ');

        execute format('drop table public.%I cascade', tbl);
    end loop;
end;
$$;

-- ---------------------------------------------------------------------------
-- profiles
-- ---------------------------------------------------------------------------

create table if not exists public.profiles (
    id uuid primary key references auth.users (id) on delete cascade,
    display_name text not null,
    created_at timestamptz not null default now()
);

-- Supabase sign-up sends the chosen name as user metadata. Without this trigger
-- no profile row is ever written and the API falls back to the literal string
-- "Player" for every account.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    insert into public.profiles (id, display_name)
    values (
        new.id,
        coalesce(
            nullif(trim(new.raw_user_meta_data ->> 'display_name'), ''),
            nullif(trim(new.raw_user_meta_data ->> 'full_name'), ''),
            split_part(coalesce(new.email, 'player'), '@', 1)
        )
    )
    on conflict (id) do nothing;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_user();

-- ---------------------------------------------------------------------------
-- groups
-- ---------------------------------------------------------------------------

create table if not exists public.groups (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_by uuid not null references auth.users (id) on delete restrict,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- memberships
--
-- A membership is either a real account (user_id set, display_name null) or a
-- virtual player created by an admin (display_name set, user_id null).
-- ---------------------------------------------------------------------------

create table if not exists public.memberships (
    id uuid primary key default gen_random_uuid(),
    group_id uuid not null references public.groups (id) on delete cascade,
    user_id uuid references auth.users (id) on delete cascade,
    display_name text,
    rating smallint not null default 3,
    is_subscriber boolean not null default false,
    is_admin boolean not null default false,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- join_requests
-- ---------------------------------------------------------------------------

create table if not exists public.join_requests (
    id uuid primary key default gen_random_uuid(),
    group_id uuid not null references public.groups (id) on delete cascade,
    user_id uuid not null references auth.users (id) on delete cascade,
    status text not null default 'pending',
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- games
-- ---------------------------------------------------------------------------

create table if not exists public.games (
    id uuid primary key default gen_random_uuid(),
    group_id uuid not null references public.groups (id) on delete cascade,
    game_datetime timestamptz not null,
    regular_registration_opens timestamptz not null,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- registrations
-- ---------------------------------------------------------------------------

create table if not exists public.registrations (
    id uuid primary key default gen_random_uuid(),
    game_id uuid not null references public.games (id) on delete cascade,
    membership_id uuid not null references public.memberships (id) on delete cascade,
    status text not null,
    created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- team_assignments
-- ---------------------------------------------------------------------------

create table if not exists public.team_assignments (
    id uuid primary key default gen_random_uuid(),
    game_id uuid not null references public.games (id) on delete cascade,
    membership_id uuid not null references public.memberships (id) on delete cascade,
    team_name text not null
);
