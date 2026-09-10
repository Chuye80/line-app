-- Game Day lifecycle: live matches, goals, standings inputs and rating surveys.
--
-- Before this migration a "game day" was only a row in `games` plus a squad and
-- three generated teams, and whether it was happening was inferred from the
-- clock: `game_datetime > now()` meant upcoming, anything else meant gone. That
-- has two consequences this migration removes.
--
-- 1. There was no way to be *in* a game day. The moment kickoff passed the row
--    stopped being active, so the app could never show a live experience.
-- 2. A finished game day could not stay finished. Because the state was derived
--    from a timestamp rather than stored, nothing could record that the day was
--    over and its champion decided.
--
-- `games.status` makes the lifecycle explicit and durable:
--
--     scheduled  registration and team building
--     live       matches are being played
--     finished   standings final, champion decided
--
-- Match scores are deliberately *not* stored. They are derived by counting
-- `match_goals` rows per team, so the goal list and the scoreboard cannot
-- disagree, and there is no counter to drift.

-- ---------------------------------------------------------------------------
-- games: explicit lifecycle
-- ---------------------------------------------------------------------------

alter table public.games
    add column if not exists status text not null default 'scheduled';

alter table public.games
    add column if not exists started_at timestamptz;

alter table public.games
    add column if not exists finished_at timestamptz;

alter table public.games
    drop constraint if exists games_status_valid;
alter table public.games
    add constraint games_status_valid
    check (status in ('scheduled', 'live', 'finished'));

-- A day that never started cannot have a start or finish time, and a day that
-- is over must have one. This is what stops a refresh from resurrecting a
-- finished game day: the state is a stored fact, not a comparison against now().
alter table public.games
    drop constraint if exists games_lifecycle_timestamps_valid;
alter table public.games
    add constraint games_lifecycle_timestamps_valid
    check (
        (status = 'scheduled' and started_at is null and finished_at is null)
        or (status = 'live' and started_at is not null and finished_at is null)
        or (status = 'finished' and started_at is not null and finished_at is not null)
    );

-- A group can only be playing one game day at a time, so the live screen always
-- resolves a single unambiguous game day.
--
-- Deliberately restricted to 'live' rather than covering 'scheduled' too. A
-- group may legitimately still hold older scheduled rows whose kickoff simply
-- passed without the day being started, and this index has to be appliable to
-- the existing hosted project without deleting any of them. `create_game`
-- supersedes a stale scheduled row under the group lock instead.
create unique index if not exists games_one_live_per_group
    on public.games (group_id)
    where status = 'live';

create index if not exists games_group_status_idx
    on public.games (group_id, status, game_datetime desc);

-- ---------------------------------------------------------------------------
-- matches
-- ---------------------------------------------------------------------------

create table if not exists public.matches (
    id uuid primary key default gen_random_uuid(),
    game_id uuid not null references public.games (id) on delete cascade,
    match_order smallint not null,
    home_team text not null,
    away_team text not null,
    status text not null default 'scheduled',
    started_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now()
);

alter table public.matches
    drop constraint if exists matches_teams_known;
alter table public.matches
    add constraint matches_teams_known
    check (
        home_team in ('Team A', 'Team B', 'Team C')
        and away_team in ('Team A', 'Team B', 'Team C')
    );

alter table public.matches
    drop constraint if exists matches_teams_distinct;
alter table public.matches
    add constraint matches_teams_distinct
    check (home_team <> away_team);

alter table public.matches
    drop constraint if exists matches_status_valid;
alter table public.matches
    add constraint matches_status_valid
    check (status in ('scheduled', 'live', 'completed'));

alter table public.matches
    drop constraint if exists matches_lifecycle_timestamps_valid;
alter table public.matches
    add constraint matches_lifecycle_timestamps_valid
    check (
        (status = 'scheduled' and started_at is null and completed_at is null)
        or (status = 'live' and started_at is not null and completed_at is null)
        or (status = 'completed' and started_at is not null
            and completed_at is not null)
    );

create unique index if not exists matches_game_order_unique
    on public.matches (game_id, match_order);

-- Two matches cannot be in progress at once, so the live screen always has a
-- single unambiguous "current match".
create unique index if not exists matches_one_live_per_game
    on public.matches (game_id)
    where status = 'live';

create index if not exists matches_game_idx
    on public.matches (game_id, match_order);

-- ---------------------------------------------------------------------------
-- match_goals
--
-- `team_name` is stored on the goal rather than looked up from the scorer's
-- team assignment. That is what lets a member be removed from the group later
-- without rewriting the history of a match that has already been played: the
-- scorer reference is cleared, the goal (and therefore the score) survives.
-- ---------------------------------------------------------------------------

create table if not exists public.match_goals (
    id uuid primary key default gen_random_uuid(),
    match_id uuid not null references public.matches (id) on delete cascade,
    team_name text not null,
    scorer_membership_id uuid references public.memberships (id) on delete set null,
    assist_membership_id uuid references public.memberships (id) on delete set null,
    created_at timestamptz not null default clock_timestamp()
);

alter table public.match_goals
    drop constraint if exists match_goals_team_known;
alter table public.match_goals
    add constraint match_goals_team_known
    check (team_name in ('Team A', 'Team B', 'Team C'));

-- A player cannot assist his own goal.
alter table public.match_goals
    drop constraint if exists match_goals_assist_is_not_scorer;
alter table public.match_goals
    add constraint match_goals_assist_is_not_scorer
    check (
        assist_membership_id is null
        or scorer_membership_id is null
        or assist_membership_id <> scorer_membership_id
    );

create index if not exists match_goals_match_idx
    on public.match_goals (match_id, created_at);

create index if not exists match_goals_scorer_idx
    on public.match_goals (scorer_membership_id)
    where scorer_membership_id is not null;

create index if not exists match_goals_assist_idx
    on public.match_goals (assist_membership_id)
    where assist_membership_id is not null;

-- ---------------------------------------------------------------------------
-- player_ratings (rating survey)
--
-- One row per (rater, subject) pair, so reopening the survey shows what the
-- rater previously submitted and saving again updates rather than accumulates.
-- ---------------------------------------------------------------------------

create table if not exists public.player_ratings (
    id uuid primary key default gen_random_uuid(),
    group_id uuid not null references public.groups (id) on delete cascade,
    rater_membership_id uuid not null
        references public.memberships (id) on delete cascade,
    subject_membership_id uuid not null
        references public.memberships (id) on delete cascade,
    rating numeric(2, 1) not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- 1.0 to 5.0 in half-point steps, which is what the survey control offers.
alter table public.player_ratings
    drop constraint if exists player_ratings_value_valid;
alter table public.player_ratings
    add constraint player_ratings_value_valid
    check (rating >= 1.0 and rating <= 5.0 and mod(rating * 2, 1) = 0);

-- Nobody rates themselves; the survey never lists the current user.
alter table public.player_ratings
    drop constraint if exists player_ratings_no_self_rating;
alter table public.player_ratings
    add constraint player_ratings_no_self_rating
    check (rater_membership_id <> subject_membership_id);

create unique index if not exists player_ratings_rater_subject_unique
    on public.player_ratings (rater_membership_id, subject_membership_id);

create index if not exists player_ratings_subject_idx
    on public.player_ratings (subject_membership_id);

create index if not exists player_ratings_group_idx
    on public.player_ratings (group_id);

-- ---------------------------------------------------------------------------
-- Row level security for the new tables.
--
-- Same reasoning as 20260909120200_rls_lockdown.sql: the browser never talks to
-- PostgREST, and the publishable key is public, so the tables are denied to the
-- PostgREST roles entirely. Goals and survey answers are exactly the kind of
-- data that must not be readable with a key shipped in a JavaScript bundle.
-- ---------------------------------------------------------------------------

do $$
declare
    target text;
begin
    foreach target in array array['matches', 'match_goals', 'player_ratings']
    loop
        execute format(
            'alter table public.%I enable row level security',
            target
        );

        if exists (select 1 from pg_roles where rolname = 'anon') then
            execute format('revoke all on public.%I from anon', target);
        end if;

        if exists (select 1 from pg_roles where rolname = 'authenticated') then
            execute format('revoke all on public.%I from authenticated', target);
        end if;
    end loop;
end;
$$;
