-- Reuse membership-backed player references for Game Day-only guests while
-- keeping them out of the group's member list.

alter table public.memberships
  add column if not exists game_day_id uuid
    references public.game_days (id) on delete cascade;

create or replace function public.lineapp_member_json(
  p_id uuid,
  p_user_id uuid,
  p_display_name text,
  p_rating numeric,
  p_is_subscriber boolean,
  p_is_admin boolean,
  p_profile_name text
) returns jsonb
language sql
stable
as $$
  with player as (
    select coalesce(m.game_day_id is not null, false) as is_guest
    from public.memberships m
    where m.id = p_id
  )
  select jsonb_build_object(
    'id', p_id::text,
    'user_id', case when p_user_id is null then null else p_user_id::text end,
    'name', case
      when p_user_id is null then coalesce(p_display_name, 'Virtual Player')
      else coalesce(p_profile_name, 'Player')
    end,
    'rating', p_rating::float8,
    'is_subscriber', p_is_subscriber,
    'is_admin', p_is_admin,
    'is_virtual', p_user_id is null and not coalesce((select is_guest from player), false),
    'is_guest', coalesce((select is_guest from player), false)
  );
$$;
