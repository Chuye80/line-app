-- Integrity constraints, uniqueness guarantees and indexes.
--
-- Before this migration every invariant in the product was enforced only by
-- Python code running outside a transaction, so concurrent requests could
-- persist states the application considers impossible (two memberships for the
-- same account, the same player registered twice, ratings outside 1-5, ...).
--
-- Each block repairs any pre-existing data that would violate the new rule
-- before installing it, so the migration is safe to run against the live
-- project. All repairs are narrow and only touch rows that are already invalid.

-- ---------------------------------------------------------------------------
-- Value domains
-- ---------------------------------------------------------------------------

update public.memberships set rating = least(greatest(rating, 1), 5)
where rating < 1 or rating > 5;

alter table public.memberships
    drop constraint if exists memberships_rating_range;
alter table public.memberships
    add constraint memberships_rating_range check (rating between 1 and 5);

-- A membership must identify somebody: either a real account or a named
-- virtual player.
delete from public.memberships
where user_id is null and nullif(trim(coalesce(display_name, '')), '') is null;

alter table public.memberships
    drop constraint if exists memberships_identity_present;
alter table public.memberships
    add constraint memberships_identity_present check (
        user_id is not null
        or nullif(trim(coalesce(display_name, '')), '') is not null
    );

update public.registrations set status = 'waiting'
where status not in ('participant', 'waiting');

alter table public.registrations
    drop constraint if exists registrations_status_valid;
alter table public.registrations
    add constraint registrations_status_valid
    check (status in ('participant', 'waiting'));

update public.join_requests set status = 'pending'
where status not in ('pending', 'approved', 'declined');

alter table public.join_requests
    drop constraint if exists join_requests_status_valid;
alter table public.join_requests
    add constraint join_requests_status_valid
    check (status in ('pending', 'approved', 'declined'));

update public.team_assignments set team_name = 'Team A'
where team_name not in ('Team A', 'Team B', 'Team C');

alter table public.team_assignments
    drop constraint if exists team_assignments_team_name_valid;
alter table public.team_assignments
    add constraint team_assignments_team_name_valid
    check (team_name in ('Team A', 'Team B', 'Team C'));

update public.groups set name = 'Group'
where nullif(trim(name), '') is null;

alter table public.groups
    drop constraint if exists groups_name_not_blank;
alter table public.groups
    add constraint groups_name_not_blank check (nullif(trim(name), '') is not null);

-- The subscriber-priority window must sit before kickoff. A row where it sits
-- after kickoff would make the priority period never end.
update public.games set regular_registration_opens = game_datetime
where regular_registration_opens > game_datetime;

alter table public.games
    drop constraint if exists games_priority_window_valid;
alter table public.games
    add constraint games_priority_window_valid
    check (regular_registration_opens <= game_datetime);

-- ---------------------------------------------------------------------------
-- Uniqueness
--
-- These indexes are what actually close the concurrency holes: two requests
-- racing to create the same row now produce a unique violation instead of
-- silently duplicating state.
-- ---------------------------------------------------------------------------

-- Two admins approving the same join request at the same time previously
-- created two memberships for one account.
delete from public.memberships m
using public.memberships keep
where m.user_id is not null
  and keep.user_id = m.user_id
  and keep.group_id = m.group_id
  and (keep.created_at, keep.id) < (m.created_at, m.id);

create unique index if not exists memberships_group_user_unique
    on public.memberships (group_id, user_id)
    where user_id is not null;

-- A player can hold at most one registration per game.
delete from public.registrations r
using public.registrations keep
where keep.game_id = r.game_id
  and keep.membership_id = r.membership_id
  and (keep.created_at, keep.id) < (r.created_at, r.id);

create unique index if not exists registrations_game_membership_unique
    on public.registrations (game_id, membership_id);

-- A player can be on at most one team per game.
delete from public.team_assignments t
using public.team_assignments keep
where keep.game_id = t.game_id
  and keep.membership_id = t.membership_id
  and keep.id < t.id;

create unique index if not exists team_assignments_game_membership_unique
    on public.team_assignments (game_id, membership_id);

-- At most one outstanding join request per account per group.
delete from public.join_requests j
using public.join_requests keep
where j.status = 'pending'
  and keep.status = 'pending'
  and keep.group_id = j.group_id
  and keep.user_id = j.user_id
  and (keep.created_at, keep.id) < (j.created_at, j.id);

create unique index if not exists join_requests_pending_unique
    on public.join_requests (group_id, user_id)
    where status = 'pending';

-- ---------------------------------------------------------------------------
-- Ordering fairness
--
-- now() returns the transaction timestamp, so every registration written by a
-- single transaction shared one created_at and the waiting list order became
-- arbitrary. clock_timestamp() advances within the transaction.
-- ---------------------------------------------------------------------------

alter table public.registrations
    alter column created_at set default clock_timestamp();

-- ---------------------------------------------------------------------------
-- Indexes for the access paths the API actually uses
-- ---------------------------------------------------------------------------

create index if not exists memberships_group_id_idx
    on public.memberships (group_id);

create index if not exists memberships_user_id_idx
    on public.memberships (user_id)
    where user_id is not null;

create index if not exists games_group_datetime_idx
    on public.games (group_id, game_datetime desc);

create index if not exists registrations_game_status_idx
    on public.registrations (game_id, status, created_at);

create index if not exists registrations_membership_idx
    on public.registrations (membership_id);

create index if not exists team_assignments_game_idx
    on public.team_assignments (game_id);

create index if not exists join_requests_group_status_idx
    on public.join_requests (group_id, status, created_at);

create index if not exists join_requests_user_idx
    on public.join_requests (user_id);

create index if not exists groups_created_at_idx
    on public.groups (created_at desc);
