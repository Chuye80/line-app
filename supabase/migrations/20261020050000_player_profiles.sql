-- Structured registered-user profiles and private player avatars.
-- Existing display_name values remain as the compatibility fallback.

alter table public.profiles
  add column if not exists first_name text,
  add column if not exists last_name text,
  add column if not exists nickname text,
  add column if not exists avatar_path text,
  add column if not exists avatar_version bigint not null default 0;

update public.profiles
set first_name = display_name
where first_name is null;

alter table public.profiles
  drop constraint if exists profiles_first_name_not_blank,
  add constraint profiles_first_name_not_blank
    check (first_name is null or nullif(trim(first_name), '') is not null),
  drop constraint if exists profiles_last_name_not_blank,
  add constraint profiles_last_name_not_blank
    check (last_name is null or nullif(trim(last_name), '') is not null),
  drop constraint if exists profiles_nickname_not_blank,
  add constraint profiles_nickname_not_blank
    check (nickname is null or nullif(trim(nickname), '') is not null),
  drop constraint if exists profiles_avatar_path_owned,
  add constraint profiles_avatar_path_owned
    check (
      avatar_path is null
      or avatar_path like 'users/' || id::text || '/%'
    );

alter table public.memberships
  add column if not exists avatar_path text,
  add column if not exists avatar_version bigint not null default 0;

alter table public.memberships
  drop constraint if exists memberships_avatar_path_owned,
  add constraint memberships_avatar_path_owned
    check (
      avatar_path is null
      or (
        user_id is null
        and avatar_path like
          'groups/' || group_id::text || '/members/' || id::text || '/%'
      )
    );

create or replace function public.lineapp_normal_name(
  p_nickname text,
  p_first_name text,
  p_legacy_display_name text
) returns text
language sql
immutable
as $$
  select coalesce(
    nullif(trim(p_nickname), ''),
    nullif(trim(p_first_name), ''),
    nullif(trim(p_legacy_display_name), ''),
    'Player'
  );
$$;

create or replace function public.lineapp_full_name(
  p_first_name text,
  p_last_name text,
  p_legacy_display_name text
) returns text
language sql
immutable
as $$
  select coalesce(
    nullif(trim(concat_ws(' ', nullif(trim(p_first_name), ''), nullif(trim(p_last_name), ''))), ''),
    nullif(trim(p_legacy_display_name), ''),
    'Player'
  );
$$;

create or replace function private.lineapp_can_read_user_avatar(
  p_target_user_id text
) returns boolean
language sql
stable
security definer
set search_path to 'public', 'pg_temp'
as $$
  select
    p_target_user_id = auth.uid()::text
    or exists (
      select 1
      from public.memberships viewer
      join public.memberships target on target.group_id = viewer.group_id
      where viewer.user_id = auth.uid()
        and target.user_id::text = p_target_user_id
    );
$$;

create or replace function private.lineapp_can_access_member_avatar(
  p_group_id text,
  p_membership_id text,
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
    join public.memberships target on target.group_id = viewer.group_id
    where viewer.user_id = auth.uid()
      and viewer.group_id::text = p_group_id
      and target.id::text = p_membership_id
      and target.user_id is null
      and (not p_require_admin or viewer.is_admin)
  );
$$;

revoke all on function private.lineapp_can_read_user_avatar(text) from public;
revoke all on function private.lineapp_can_access_member_avatar(text, text, boolean) from public;
grant usage on schema private to authenticated;
grant execute on function private.lineapp_can_read_user_avatar(text) to authenticated;
grant execute on function private.lineapp_can_access_member_avatar(text, text, boolean) to authenticated;

-- New Auth users must carry structured names. Existing users are untouched.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  given_name text := nullif(trim(new.raw_user_meta_data ->> 'first_name'), '');
  family_name text := nullif(trim(new.raw_user_meta_data ->> 'last_name'), '');
  preferred_name text := nullif(trim(new.raw_user_meta_data ->> 'nickname'), '');
begin
  if given_name is null or family_name is null then
    raise exception 'first_name and last_name are required';
  end if;

  insert into public.profiles (
    id, first_name, last_name, nickname, display_name
  )
  values (
    new.id,
    given_name,
    family_name,
    preferred_name,
    public.lineapp_normal_name(preferred_name, given_name, given_name)
  )
  on conflict (id) do nothing;

  return new;
end;
$$;

-- Keep the established seven-argument signature so all existing payload
-- functions receive structured profile and avatar data automatically.
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
      m.goalkeeper_rating,
      m.avatar_path as membership_avatar_path,
      m.avatar_version as membership_avatar_version
    from public.memberships m
    where m.id = p_id
  ),
  registered_profile as (
    select
      p.first_name,
      p.last_name,
      p.nickname,
      p.display_name,
      p.avatar_path,
      p.avatar_version
    from public.profiles p
    where p.id = p_user_id
  )
  select jsonb_build_object(
    'id', p_id::text,
    'user_id', case when p_user_id is null then null else p_user_id::text end,
    'name', case
      when p_user_id is null then coalesce(nullif(trim(p_display_name), ''), 'Virtual Player')
      else public.lineapp_normal_name(
        (select nickname from registered_profile),
        (select first_name from registered_profile),
        coalesce((select display_name from registered_profile), p_profile_name)
      )
    end,
    'full_name', case
      when p_user_id is null then coalesce(nullif(trim(p_display_name), ''), 'Virtual Player')
      else public.lineapp_full_name(
        (select first_name from registered_profile),
        (select last_name from registered_profile),
        coalesce((select display_name from registered_profile), p_profile_name)
      )
    end,
    'first_name', case when p_user_id is null then null else (select first_name from registered_profile) end,
    'last_name', case when p_user_id is null then null else (select last_name from registered_profile) end,
    'nickname', case when p_user_id is null then null else (select nickname from registered_profile) end,
    'avatar_path', case
      when p_user_id is null then (select membership_avatar_path from player)
      else (select avatar_path from registered_profile)
    end,
    'avatar_version', case
      when p_user_id is null then (select membership_avatar_version from player)
      else (select avatar_version from registered_profile)
    end,
    'rating', p_rating::float8,
    'goalkeeper_rating', (select goalkeeper_rating::float8 from player),
    'is_subscriber', p_is_subscriber,
    'is_admin', p_is_admin,
    'is_virtual', p_user_id is null and not coalesce((select is_guest from player), false),
    'is_guest', coalesce((select is_guest from player), false)
  );
$$;

-- Storage is present on hosted Supabase but absent from the plain-Postgres
-- integration-test harness, so install bucket configuration and policies only
-- when that schema exists.
do $$
begin
  if to_regclass('storage.buckets') is null
     or to_regclass('storage.objects') is null then
    return;
  end if;

  insert into storage.buckets (
    id, name, public, file_size_limit, allowed_mime_types
  )
  values (
    'player-avatars',
    'player-avatars',
    false,
    2097152,
    array['image/webp']
  )
  on conflict (id) do nothing;

  execute 'drop policy if exists "player avatars read" on storage.objects';
  execute 'drop policy if exists "registered users write own avatar" on storage.objects';
  execute 'drop policy if exists "group admins insert player avatars" on storage.objects';
  execute 'drop policy if exists "group admins update player avatars" on storage.objects';
  execute 'drop policy if exists "group admins delete player avatars" on storage.objects';

  execute $policy$
    create policy "player avatars read"
    on storage.objects for select to authenticated
    using (
      bucket_id = 'player-avatars'
      and (
        (
          (storage.foldername(name))[1] = 'users'
          and private.lineapp_can_read_user_avatar(
            (storage.foldername(name))[2]
          )
        )
        or (
          (storage.foldername(name))[1] = 'groups'
          and private.lineapp_can_access_member_avatar(
            (storage.foldername(name))[2],
            (storage.foldername(name))[4],
            false
          )
        )
      )
    )
  $policy$;

  execute $policy$
    create policy "registered users write own avatar"
    on storage.objects for all to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'users'
      and (storage.foldername(name))[2] = auth.uid()::text
    )
    with check (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'users'
      and (storage.foldername(name))[2] = auth.uid()::text
    )
  $policy$;

  execute $policy$
    create policy "group admins insert player avatars"
    on storage.objects for insert to authenticated
    with check (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and private.lineapp_can_access_member_avatar(
        (storage.foldername(name))[2],
        (storage.foldername(name))[4],
        true
      )
    )
  $policy$;

  execute $policy$
    create policy "group admins update player avatars"
    on storage.objects for update to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and private.lineapp_can_access_member_avatar(
        (storage.foldername(name))[2],
        (storage.foldername(name))[4],
        true
      )
    )
    with check (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and private.lineapp_can_access_member_avatar(
        (storage.foldername(name))[2],
        (storage.foldername(name))[4],
        true
      )
    )
  $policy$;

  execute $policy$
    create policy "group admins delete player avatars"
    on storage.objects for delete to authenticated
    using (
      bucket_id = 'player-avatars'
      and (storage.foldername(name))[1] = 'groups'
      and private.lineapp_can_access_member_avatar(
        (storage.foldername(name))[2],
        (storage.foldername(name))[4],
        true
      )
    )
  $policy$;
end;
$$;
