-- LineApp beta: Game Days, matches, private groups, surveys, stats, developers

drop policy if exists games_delete_admin on public.games;
drop policy if exists games_insert_admin on public.games;
drop policy if exists games_select_group_members on public.games;
drop policy if exists games_update_admin on public.games;
drop policy if exists registrations_delete_self_or_admin on public.registrations;
drop policy if exists registrations_insert_self_or_admin on public.registrations;
drop policy if exists registrations_select_group_members on public.registrations;
drop policy if exists registrations_update_admin on public.registrations;
drop policy if exists team_assignments_delete_admin on public.team_assignments;
drop policy if exists team_assignments_insert_admin on public.team_assignments;
drop policy if exists team_assignments_select_group_members on public.team_assignments;
drop policy if exists team_assignments_update_admin on public.team_assignments;
drop policy if exists groups_select_authenticated on public.groups;

alter table public.games rename to game_days;
alter table public.registrations rename column game_id to game_day_id;
alter table public.team_assignments rename column game_id to game_day_id;

alter table public.game_days
  add column if not exists status text not null default 'upcoming',
  add column if not exists participant_count integer not null default 12,
  add column if not exists players_per_team integer not null default 4,
  add column if not exists is_rotating boolean not null default false,
  add column if not exists champion_team_name text,
  add column if not exists mvp_closed_at timestamptz,
  add column if not exists finished_at timestamptz;

alter table public.game_days
  drop constraint if exists game_days_status_check,
  add constraint game_days_status_check
    check (status = any (array['upcoming'::text, 'live'::text, 'finished'::text]));

alter table public.game_days
  drop constraint if exists game_days_participant_count_check,
  add constraint game_days_participant_count_check
    check (participant_count >= 2 and participant_count <= 40);

alter table public.game_days
  drop constraint if exists game_days_players_per_team_check,
  add constraint game_days_players_per_team_check
    check (players_per_team >= 2 and players_per_team <= 11);

alter table public.groups
  add column if not exists invite_code text,
  add column if not exists last_participant_count integer not null default 12,
  add column if not exists last_players_per_team integer not null default 4;

update public.groups
set invite_code = encode(gen_random_bytes(6), 'hex')
where invite_code is null;

alter table public.groups
  alter column invite_code set not null;

alter table public.groups
  drop constraint if exists groups_invite_code_key,
  add constraint groups_invite_code_key unique (invite_code);

alter table public.groups
  drop constraint if exists groups_last_participant_count_check,
  add constraint groups_last_participant_count_check
    check (last_participant_count >= 2 and last_participant_count <= 40);

alter table public.groups
  drop constraint if exists groups_last_players_per_team_check,
  add constraint groups_last_players_per_team_check
    check (last_players_per_team >= 2 and last_players_per_team <= 11);

alter table public.memberships
  alter column rating type numeric(3, 1)
  using rating::numeric(3, 1);

alter table public.memberships
  drop constraint if exists memberships_rating_check,
  add constraint memberships_rating_check
    check (rating >= 1 and rating <= 5);

alter table public.team_assignments
  drop constraint if exists team_assignments_team_name_check;

alter table public.team_assignments
  alter column team_name drop not null;

alter table public.team_assignments
  add constraint team_assignments_team_name_check
    check (team_name is null or team_name ~ '^Team [A-Z]$');

create table if not exists public.developers (
  user_id uuid primary key references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);

insert into public.developers (user_id)
values ('369a716c-95ae-4a4a-ba4e-c916d9c54484')
on conflict (user_id) do nothing;

create table if not exists public.matches (
  id uuid primary key default gen_random_uuid(),
  game_day_id uuid not null references public.game_days (id) on delete cascade,
  home_team_name text not null,
  away_team_name text not null,
  home_score integer,
  away_score integer,
  status text not null default 'open',
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  constraint matches_status_check check (status = any (array['open'::text, 'completed'::text])),
  constraint matches_teams_distinct check (home_team_name <> away_team_name),
  constraint matches_scores_check check (
    (status = 'open' and home_score is null and away_score is null)
    or (status = 'completed' and home_score is not null and away_score is not null
        and home_score >= 0 and away_score >= 0)
  )
);

create table if not exists public.match_players (
  id uuid primary key default gen_random_uuid(),
  match_id uuid not null references public.matches (id) on delete cascade,
  membership_id uuid not null references public.memberships (id) on delete cascade,
  team_name text not null,
  unique (match_id, membership_id)
);

create table if not exists public.match_goals (
  id uuid primary key default gen_random_uuid(),
  match_id uuid not null references public.matches (id) on delete cascade,
  scorer_membership_id uuid not null references public.memberships (id) on delete cascade,
  assist_membership_id uuid references public.memberships (id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.mvp_votes (
  id uuid primary key default gen_random_uuid(),
  game_day_id uuid not null references public.game_days (id) on delete cascade,
  voter_membership_id uuid not null references public.memberships (id) on delete cascade,
  nominee_membership_id uuid not null references public.memberships (id) on delete cascade,
  created_at timestamptz not null default now(),
  unique (game_day_id, voter_membership_id),
  constraint mvp_votes_not_self check (voter_membership_id <> nominee_membership_id)
);

create table if not exists public.game_day_awards (
  id uuid primary key default gen_random_uuid(),
  game_day_id uuid not null references public.game_days (id) on delete cascade,
  membership_id uuid not null references public.memberships (id) on delete cascade,
  award_type text not null,
  created_at timestamptz not null default now(),
  unique (game_day_id, membership_id, award_type),
  constraint game_day_awards_type_check check (award_type = any (array['champion'::text, 'mvp'::text]))
);

create table if not exists public.rating_surveys (
  id uuid primary key default gen_random_uuid(),
  group_id uuid not null references public.groups (id) on delete cascade,
  status text not null default 'open',
  created_at timestamptz not null default now(),
  closed_at timestamptz,
  constraint rating_surveys_status_check check (status = any (array['open'::text, 'closed'::text]))
);

create table if not exists public.rating_survey_responses (
  id uuid primary key default gen_random_uuid(),
  survey_id uuid not null references public.rating_surveys (id) on delete cascade,
  rater_membership_id uuid not null references public.memberships (id) on delete cascade,
  rated_membership_id uuid not null references public.memberships (id) on delete cascade,
  rating smallint not null,
  created_at timestamptz not null default now(),
  unique (survey_id, rater_membership_id, rated_membership_id),
  constraint rating_survey_responses_range check (rating >= 1 and rating <= 5),
  constraint rating_survey_responses_not_self check (rater_membership_id <> rated_membership_id)
);

alter table public.developers enable row level security;
alter table public.matches enable row level security;
alter table public.match_players enable row level security;
alter table public.match_goals enable row level security;
alter table public.mvp_votes enable row level security;
alter table public.game_day_awards enable row level security;
alter table public.rating_surveys enable row level security;
alter table public.rating_survey_responses enable row level security;

create or replace function public.preview_group_by_invite(invite text)
returns table (id uuid, name text)
language sql
stable
security definer
set search_path to 'public'
as $$
  select g.id, g.name
  from public.groups g
  where g.invite_code = invite;
$$;

grant execute on function public.preview_group_by_invite(text) to authenticated;

drop policy if exists groups_select_members on public.groups;
create policy groups_select_members
  on public.groups
  for select
  using (private.is_group_member(id));

drop policy if exists groups_update_admin on public.groups;
create policy groups_update_admin
  on public.groups
  for update
  using (private.is_group_admin(id))
  with check (private.is_group_admin(id));

drop policy if exists profiles_select_authenticated on public.profiles;
create policy profiles_select_self_or_group
  on public.profiles
  for select
  using (
    id = auth.uid()
    or exists (
      select 1
      from public.memberships mine
      join public.memberships theirs
        on theirs.group_id = mine.group_id
      where mine.user_id = auth.uid()
        and theirs.user_id = profiles.id
    )
  );

create policy game_days_select_members
  on public.game_days for select
  using (private.is_group_member(group_id));

create policy game_days_insert_admin
  on public.game_days for insert
  with check (private.is_group_admin(group_id));

create policy game_days_update_admin
  on public.game_days for update
  using (private.is_group_admin(group_id))
  with check (private.is_group_admin(group_id));

create policy game_days_delete_admin
  on public.game_days for delete
  using (private.is_group_admin(group_id));

create policy registrations_select_members
  on public.registrations for select
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = registrations.game_day_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy registrations_insert_self_or_admin
  on public.registrations for insert
  with check (
    exists (
      select 1
      from public.game_days gd
      join public.memberships m on m.id = registrations.membership_id
      where gd.id = registrations.game_day_id
        and m.group_id = gd.group_id
        and (m.user_id = auth.uid() or private.is_group_admin(gd.group_id))
    )
  );

create policy registrations_delete_self_or_admin
  on public.registrations for delete
  using (
    exists (
      select 1
      from public.game_days gd
      join public.memberships m on m.id = registrations.membership_id
      where gd.id = registrations.game_day_id
        and m.group_id = gd.group_id
        and (m.user_id = auth.uid() or private.is_group_admin(gd.group_id))
    )
  );

create policy registrations_update_admin
  on public.registrations for update
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = registrations.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1 from public.game_days gd
      where gd.id = registrations.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy team_assignments_select_members
  on public.team_assignments for select
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = team_assignments.game_day_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy team_assignments_admin_insert
  on public.team_assignments for insert
  with check (
    exists (
      select 1 from public.game_days gd
      where gd.id = team_assignments.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy team_assignments_admin_update
  on public.team_assignments for update
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = team_assignments.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1 from public.game_days gd
      where gd.id = team_assignments.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy team_assignments_admin_delete
  on public.team_assignments for delete
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = team_assignments.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy developers_select_self
  on public.developers for select
  using (user_id = auth.uid());

create policy matches_select_members
  on public.matches for select
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = matches.game_day_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy matches_admin_all
  on public.matches for all
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = matches.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1 from public.game_days gd
      where gd.id = matches.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy match_players_select_members
  on public.match_players for select
  using (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_players.match_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy match_players_admin_all
  on public.match_players for all
  using (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_players.match_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_players.match_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy match_goals_select_members
  on public.match_goals for select
  using (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_goals.match_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy match_goals_admin_all
  on public.match_goals for all
  using (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_goals.match_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1
      from public.matches m
      join public.game_days gd on gd.id = m.game_day_id
      where m.id = match_goals.match_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy mvp_votes_select_own
  on public.mvp_votes for select
  using (
    voter_membership_id in (
      select m.id from public.memberships m where m.user_id = auth.uid()
    )
  );

create policy mvp_votes_insert_self
  on public.mvp_votes for insert
  with check (
    exists (
      select 1
      from public.game_days gd
      join public.memberships voter on voter.id = mvp_votes.voter_membership_id
      where gd.id = mvp_votes.game_day_id
        and gd.status = 'finished'
        and gd.mvp_closed_at is null
        and voter.user_id = auth.uid()
        and private.is_group_member(gd.group_id)
    )
  );

create policy awards_select_members
  on public.game_day_awards for select
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = game_day_awards.game_day_id
        and private.is_group_member(gd.group_id)
    )
  );

create policy awards_admin_all
  on public.game_day_awards for all
  using (
    exists (
      select 1 from public.game_days gd
      where gd.id = game_day_awards.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  )
  with check (
    exists (
      select 1 from public.game_days gd
      where gd.id = game_day_awards.game_day_id
        and private.is_group_admin(gd.group_id)
    )
  );

create policy surveys_select_members
  on public.rating_surveys for select
  using (private.is_group_member(group_id));

create policy surveys_admin_all
  on public.rating_surveys for all
  using (private.is_group_admin(group_id))
  with check (private.is_group_admin(group_id));

create policy survey_responses_select_own
  on public.rating_survey_responses for select
  using (
    exists (
      select 1
      from public.memberships rater
      where rater.id = rating_survey_responses.rater_membership_id
        and rater.user_id = auth.uid()
    )
  );

create policy survey_responses_insert_self
  on public.rating_survey_responses for insert
  with check (
    exists (
      select 1
      from public.rating_surveys s
      join public.memberships rater on rater.id = rating_survey_responses.rater_membership_id
      where s.id = rating_survey_responses.survey_id
        and s.status = 'open'
        and rater.user_id = auth.uid()
        and private.is_group_member(s.group_id)
    )
  );

create policy survey_responses_update_self
  on public.rating_survey_responses for update
  using (
    exists (
      select 1
      from public.rating_surveys s
      join public.memberships rater on rater.id = rating_survey_responses.rater_membership_id
      where s.id = rating_survey_responses.survey_id
        and s.status = 'open'
        and rater.user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1
      from public.rating_surveys s
      join public.memberships rater on rater.id = rating_survey_responses.rater_membership_id
      where s.id = rating_survey_responses.survey_id
        and s.status = 'open'
        and rater.user_id = auth.uid()
    )
  );
