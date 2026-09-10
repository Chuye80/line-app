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
