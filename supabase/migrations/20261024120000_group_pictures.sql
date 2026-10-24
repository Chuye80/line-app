-- One private picture per group.
--
-- The object lives in the existing private player-avatars bucket, under
-- groups/{groupId}/picture/{file}.webp. That folder is separate from
-- groups/{groupId}/members/{membershipId}/, which remains virtual-player and
-- guest avatars only.

alter table public.groups
  add column if not exists picture_path text,
  add column if not exists picture_version bigint not null default 0;

alter table public.groups
  drop constraint if exists groups_picture_path_owned,
  add constraint groups_picture_path_owned
    check (
      picture_path is null
      or picture_path like 'groups/' || id::text || '/picture/%'
    );

create or replace function private.lineapp_can_access_group_picture(
  p_group_id text,
  p_require_admin boolean
) returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select exists (
    select 1
    from public.memberships viewer
    where viewer.user_id = auth.uid()
      and viewer.group_id::text = p_group_id
      and (not p_require_admin or viewer.is_admin)
  );
$$;

revoke all on function private.lineapp_can_access_group_picture(text, boolean) from public;
grant execute on function private.lineapp_can_access_group_picture(text, boolean) to authenticated;

-- Keep the current group payload and expose the picture to members.
create or replace function public.lineapp_read_group(
  p_group_id uuid,
  p_user_id uuid
) returns jsonb
language plpgsql
as $$
declare
  g public.groups%ROWTYPE;
  viewer public.memberships%ROWTYPE;
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
    'picture_path', g.picture_path,
    'picture_version', g.picture_version,
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
          select jsonb_object_agg(r.rated_membership_id::text, r.rating)
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

-- Storage is present on hosted Supabase but absent from a plain-Postgres
-- install, so install picture policies only when that schema exists.
do $$
begin
  if to_regclass('storage.buckets') is null
     or to_regclass('storage.objects') is null then
    return;
  end if;

  execute 'drop policy if exists "group pictures read" on storage.objects';
  execute 'drop policy if exists "group admins insert group pictures" on storage.objects';
  execute 'drop policy if exists "group admins update group pictures" on storage.objects';
  execute 'drop policy if exists "group admins delete group pictures" on storage.objects';

  execute $policy$
    create policy "group pictures read"
    on storage.objects for select to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and (storage.foldername(name))[3] = 'picture'
      and private.lineapp_can_access_group_picture(
        (storage.foldername(name))[2],
        false
      )
    )
  $policy$;

  execute $policy$
    create policy "group admins insert group pictures"
    on storage.objects for insert to authenticated
    with check (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and (storage.foldername(name))[3] = 'picture'
      and private.lineapp_can_access_group_picture(
        (storage.foldername(name))[2],
        true
      )
    )
  $policy$;

  execute $policy$
    create policy "group admins update group pictures"
    on storage.objects for update to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and (storage.foldername(name))[3] = 'picture'
      and private.lineapp_can_access_group_picture(
        (storage.foldername(name))[2],
        true
      )
    )
    with check (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and (storage.foldername(name))[3] = 'picture'
      and private.lineapp_can_access_group_picture(
        (storage.foldername(name))[2],
        true
      )
    )
  $policy$;

  execute $policy$
    create policy "group admins delete group pictures"
    on storage.objects for delete to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and (storage.foldername(name))[3] = 'picture'
      and private.lineapp_can_access_group_picture(
        (storage.foldername(name))[2],
        true
      )
    )
  $policy$;
end;
$$;
