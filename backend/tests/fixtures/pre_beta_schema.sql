-- Minimal pre-beta schema used only by the local Captains integration tests.
-- It provides the starting point expected by the committed migrations without
-- adding historical migration files to the production migration directory.

create extension if not exists "pgcrypto";

create table public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  display_name text not null,
  created_at timestamptz not null default now()
);

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

create trigger on_auth_user_created
after insert on auth.users
for each row execute function public.handle_new_user();

create table public.groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by uuid not null references auth.users (id) on delete restrict,
  created_at timestamptz not null default now()
);

create table public.memberships (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  user_id uuid references auth.users (id) on delete cascade,
  display_name text,
  rating smallint not null default 3,
  is_subscriber boolean not null default false,
  is_admin boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.join_requests (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  status text not null default 'pending',
  created_at timestamptz not null default now()
);

create table public.games (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  game_datetime timestamptz not null,
  regular_registration_opens timestamptz not null,
  created_at timestamptz not null default now()
);

create table public.registrations (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games (id) on delete cascade,
  membership_id uuid not null references public.memberships (id) on delete cascade,
  status text not null,
  created_at timestamptz not null default clock_timestamp()
);

create table public.team_assignments (
  id uuid primary key default gen_random_uuid(),
  game_id uuid not null references public.games (id) on delete cascade,
  membership_id uuid not null references public.memberships (id) on delete cascade,
  team_name text not null
);

create schema private;

create function private.is_group_member(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select exists (
    select 1 from public.memberships
    where group_id = target_group_id and user_id = auth.uid()
  );
$$;

create function private.is_group_admin(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select exists (
    select 1 from public.memberships
    where group_id = target_group_id and user_id = auth.uid() and is_admin
  );
$$;

-- The beta migration seeds this developer only when its referenced Auth user
-- exists in Production. Supply that user in the isolated test database.
insert into auth.users (id, email, raw_user_meta_data)
values (
  '369a716c-95ae-4a4a-ba4e-c916d9c54484',
  'developer@example.test',
  '{"display_name":"Developer"}'::jsonb
);
