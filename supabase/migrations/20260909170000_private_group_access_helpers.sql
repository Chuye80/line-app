-- Private helpers for PostgREST RLS policies (verified against production).
--
-- These run as SECURITY DEFINER with a fixed search_path so policy checks
-- cannot be tricked via search_path manipulation. They intentionally do not
-- filter on memberships.game_day_id: guest rows use user_id IS NULL and never
-- match auth.uid().

create schema if not exists private;

create or replace function private.is_group_member(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select exists (
    select 1
    from public.memberships m
    where m.group_id = target_group_id
      and m.user_id = auth.uid()
  );
$$;

create or replace function private.is_group_admin(target_group_id uuid)
returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select exists (
    select 1
    from public.memberships m
    where m.group_id = target_group_id
      and m.user_id = auth.uid()
      and m.is_admin = true
  );
$$;

revoke all on function private.is_group_member(uuid) from public;
revoke all on function private.is_group_admin(uuid) from public;

grant execute on function private.is_group_member(uuid) to authenticated;
grant execute on function private.is_group_admin(uuid) to authenticated;
