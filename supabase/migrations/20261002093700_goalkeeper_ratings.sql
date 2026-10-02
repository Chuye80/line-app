-- Keep field-player and goalkeeper ability as separate membership ratings.

alter table public.memberships
  add column if not exists goalkeeper_rating numeric(3, 1);

update public.memberships
set goalkeeper_rating = 3.0
where goalkeeper_rating is null;

alter table public.memberships
  alter column goalkeeper_rating set default 3.0,
  alter column goalkeeper_rating set not null;

alter table public.memberships
  drop constraint if exists memberships_goalkeeper_rating_check,
  add constraint memberships_goalkeeper_rating_check
    check (goalkeeper_rating >= 1 and goalkeeper_rating <= 5);

alter table public.rating_survey_responses
  add column if not exists goalkeeper_rating numeric(2, 1);

update public.rating_survey_responses
set goalkeeper_rating = 3.0
where goalkeeper_rating is null;

alter table public.rating_survey_responses
  alter column goalkeeper_rating set not null;

alter table public.rating_survey_responses
  drop constraint if exists rating_survey_responses_goalkeeper_range,
  add constraint rating_survey_responses_goalkeeper_range
    check (
      goalkeeper_rating >= 1
      and goalkeeper_rating <= 5
      and (goalkeeper_rating * 2) = floor(goalkeeper_rating * 2)
    );

-- Keep the existing function signature so all current callers automatically
-- receive the additional value without replacing lineapp_read_group.
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
    select
      coalesce(m.game_day_id is not null, false) as is_guest,
      m.goalkeeper_rating
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
    'goalkeeper_rating', (select goalkeeper_rating::float8 from player),
    'is_subscriber', p_is_subscriber,
    'is_admin', p_is_admin,
    'is_virtual', p_user_id is null and not coalesce((select is_guest from player), false),
    'is_guest', coalesce((select is_guest from player), false)
  );
$$;
