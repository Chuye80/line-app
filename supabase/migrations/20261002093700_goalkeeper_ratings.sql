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
-- receive the additional value without duplicating identity or member data.
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

-- Return both submitted values when the group payload is loaded.
create or replace function public.lineapp_read_group(
  p_group_id uuid,
  p_user_id uuid
) returns jsonb
language plpgsql
as $$
declare
  g public.groups%rowtype;
  viewer public.memberships%rowtype;
  current_id uuid;
  finished_id uuid;
  payload jsonb;
begin
  select * into g from public.groups where id = p_group_id;
  if not found then
    return jsonb_build_object('error', 'not_found');
  end if;

  select * into viewer
  from public.memberships
  where group_id = p_group_id and user_id = p_user_id;
  if not found then
    return jsonb_build_object('error', 'forbidden');
  end if;

  update public.game_days
  set status = 'live'
  where group_id = p_group_id
    and status = 'upcoming'
    and game_datetime <= now();

  select gd.id into current_id
  from public.game_days gd
  where gd.group_id = p_group_id
    and gd.status in ('upcoming', 'live')
  order by gd.game_datetime desc
  limit 1;

  if current_id is not null then
    perform public.lineapp_promote_waiting(current_id);
  else
    select gd.id into finished_id
    from public.game_days gd
    where gd.group_id = p_group_id
      and gd.status = 'finished'
    order by gd.finished_at desc nulls last, gd.game_datetime desc
    limit 1;
  end if;

  payload := jsonb_build_object(
    'id', g.id::text,
    'name', g.name,
    'last_participant_count', g.last_participant_count,
    'last_players_per_team', g.last_players_per_team,
    'members', coalesce((
      select jsonb_agg(
        public.lineapp_member_json(
          m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
        )
        order by m.created_at
      )
      from memberships m
      left join profiles p on p.id = m.user_id
      where m.group_id = g.id
    ), '[]'::jsonb),
    'game_day', case
      when current_id is null then null
      else public.lineapp_game_day_json(current_id, viewer.id)
    end,
    'finished_game_day', case
      when finished_id is null then null
      else public.lineapp_game_day_json(finished_id, viewer.id)
    end,
    'history', coalesce((
      select jsonb_agg(item.obj order by item.game_datetime desc)
      from (
        select
          gd.game_datetime,
          jsonb_build_object(
            'id', gd.id::text,
            'game_datetime', gd.game_datetime,
            'status', gd.status,
            'is_rotating', gd.is_rotating,
            'champion_team_name', gd.champion_team_name,
            'awards', jsonb_build_object(
              'champions', coalesce((
                select jsonb_agg(public.lineapp_member_json(
                  m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
                ))
                from game_day_awards a
                join memberships m on m.id = a.membership_id
                left join profiles p on p.id = m.user_id
                where a.game_day_id = gd.id and a.award_type = 'champion'
              ), '[]'::jsonb),
              'mvps', coalesce((
                select jsonb_agg(public.lineapp_member_json(
                  m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
                ))
                from game_day_awards a
                join memberships m on m.id = a.membership_id
                left join profiles p on p.id = m.user_id
                where a.game_day_id = gd.id and a.award_type = 'mvp'
              ), '[]'::jsonb)
            )
          ) as obj
        from game_days gd
        where gd.group_id = g.id and gd.status = 'finished'
      ) item
    ), '[]'::jsonb),
    'survey', (
      select jsonb_build_object(
        'id', s.id::text,
        'status', s.status,
        'created_at', s.created_at,
        'closed_at', s.closed_at,
        'my_ratings', coalesce((
          select jsonb_object_agg(
            r.rated_membership_id::text,
            jsonb_build_object(
              'rating', r.rating,
              'goalkeeper_rating', r.goalkeeper_rating
            )
          )
          from rating_survey_responses r
          where r.survey_id = s.id and r.rater_membership_id = viewer.id
        ), '{}'::jsonb)
      )
      from rating_surveys s
      where s.group_id = g.id
      order by s.created_at desc
      limit 1
    )
  );

  if viewer.is_admin then
    payload := payload || jsonb_build_object(
      'invite_code', g.invite_code,
      'invite_link', 'http://127.0.0.1:5173/?invite=' || g.invite_code,
      'join_requests', coalesce((
        select jsonb_agg(
          jsonb_build_object(
            'id', jr.id::text,
            'user_id', jr.user_id::text,
            'user_name', coalesce(p.display_name, 'Player'),
            'status', jr.status
          )
          order by jr.created_at
        )
        from join_requests jr
        left join profiles p on p.id = jr.user_id
        where jr.group_id = g.id and jr.status = 'pending'
      ), '[]'::jsonb)
    );
  end if;

  return payload;
end;
$$;
