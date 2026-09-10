-- Drift check: reports everything the migrations in supabase/migrations expect
-- but the connected database does not have.
--
--   psql "$DATABASE_URL" -f supabase/verify_schema.sql
--
-- An empty result set means the live schema matches version control.

with expected_tables (name) as (
    values
        ('profiles'), ('groups'), ('memberships'), ('join_requests'),
        ('games'), ('registrations'), ('team_assignments'),
        ('matches'), ('match_goals'), ('player_ratings')
),
expected_columns (table_name, column_name) as (
    values
        ('profiles', 'id'), ('profiles', 'display_name'), ('profiles', 'created_at'),
        ('groups', 'id'), ('groups', 'name'), ('groups', 'created_by'), ('groups', 'created_at'),
        ('memberships', 'id'), ('memberships', 'group_id'), ('memberships', 'user_id'),
        ('memberships', 'display_name'), ('memberships', 'rating'),
        ('memberships', 'is_subscriber'), ('memberships', 'is_admin'), ('memberships', 'created_at'),
        ('join_requests', 'id'), ('join_requests', 'group_id'), ('join_requests', 'user_id'),
        ('join_requests', 'status'), ('join_requests', 'created_at'),
        ('games', 'id'), ('games', 'group_id'), ('games', 'game_datetime'),
        ('games', 'regular_registration_opens'), ('games', 'created_at'),
        ('games', 'status'), ('games', 'started_at'), ('games', 'finished_at'),
        ('registrations', 'id'), ('registrations', 'game_id'), ('registrations', 'membership_id'),
        ('registrations', 'status'), ('registrations', 'created_at'),
        ('team_assignments', 'id'), ('team_assignments', 'game_id'),
        ('team_assignments', 'membership_id'), ('team_assignments', 'team_name'),
        ('matches', 'id'), ('matches', 'game_id'), ('matches', 'match_order'),
        ('matches', 'home_team'), ('matches', 'away_team'), ('matches', 'status'),
        ('matches', 'started_at'), ('matches', 'completed_at'),
        ('matches', 'created_at'),
        ('match_goals', 'id'), ('match_goals', 'match_id'),
        ('match_goals', 'team_name'), ('match_goals', 'scorer_membership_id'),
        ('match_goals', 'assist_membership_id'), ('match_goals', 'created_at'),
        ('player_ratings', 'id'), ('player_ratings', 'group_id'),
        ('player_ratings', 'rater_membership_id'),
        ('player_ratings', 'subject_membership_id'),
        ('player_ratings', 'rating'), ('player_ratings', 'created_at'),
        ('player_ratings', 'updated_at')
),
expected_constraints (table_name, constraint_name) as (
    values
        ('memberships', 'memberships_rating_range'),
        ('memberships', 'memberships_identity_present'),
        ('memberships', 'memberships_virtual_players_not_admin'),
        ('registrations', 'registrations_status_valid'),
        ('join_requests', 'join_requests_status_valid'),
        ('team_assignments', 'team_assignments_team_name_valid'),
        ('groups', 'groups_name_not_blank'),
        ('games', 'games_priority_window_valid'),
        ('games', 'games_status_valid'),
        ('games', 'games_lifecycle_timestamps_valid'),
        ('matches', 'matches_teams_known'),
        ('matches', 'matches_teams_distinct'),
        ('matches', 'matches_status_valid'),
        ('matches', 'matches_lifecycle_timestamps_valid'),
        ('match_goals', 'match_goals_team_known'),
        ('match_goals', 'match_goals_assist_is_not_scorer'),
        ('player_ratings', 'player_ratings_value_valid'),
        ('player_ratings', 'player_ratings_no_self_rating')
),
expected_indexes (index_name) as (
    values
        ('memberships_group_user_unique'),
        ('registrations_game_membership_unique'),
        ('team_assignments_game_membership_unique'),
        ('join_requests_pending_unique'),
        ('memberships_group_id_idx'),
        ('memberships_user_id_idx'),
        ('games_group_datetime_idx'),
        ('registrations_game_status_idx'),
        ('registrations_membership_idx'),
        ('team_assignments_game_idx'),
        ('join_requests_group_status_idx'),
        ('join_requests_user_idx'),
        ('groups_created_at_idx'),
        ('games_one_live_per_group'),
        ('games_group_status_idx'),
        ('matches_game_order_unique'),
        ('matches_one_live_per_game'),
        ('matches_game_idx'),
        ('match_goals_match_idx'),
        ('player_ratings_rater_subject_unique'),
        ('player_ratings_subject_idx')
),
expected_triggers (table_schema, table_name, trigger_name) as (
    values
        ('auth', 'users', 'on_auth_user_created'),
        ('public', 'memberships', 'memberships_require_admin')
),
findings as (
    select 'missing table' as issue, name as object_name
    from expected_tables
    where to_regclass('public.' || quote_ident(name)) is null

    union all
    select 'missing column', table_name || '.' || column_name
    from expected_columns e
    where to_regclass('public.' || quote_ident(e.table_name)) is not null
      and not exists (
          select 1 from information_schema.columns c
          where c.table_schema = 'public'
            and c.table_name = e.table_name
            and c.column_name = e.column_name
      )

    union all
    select 'missing constraint', table_name || '.' || constraint_name
    from expected_constraints e
    where to_regclass('public.' || quote_ident(e.table_name)) is not null
      and not exists (
          select 1 from pg_constraint pc
          join pg_class rel on rel.oid = pc.conrelid
          join pg_namespace ns on ns.oid = rel.relnamespace
          where ns.nspname = 'public'
            and rel.relname = e.table_name
            and pc.conname = e.constraint_name
      )

    union all
    select 'missing index', index_name
    from expected_indexes e
    where not exists (
        select 1 from pg_indexes i
        where i.schemaname = 'public' and i.indexname = e.index_name
    )

    union all
    select 'missing trigger', table_schema || '.' || table_name || '.' || trigger_name
    from expected_triggers e
    where not exists (
        select 1 from pg_trigger t
        join pg_class rel on rel.oid = t.tgrelid
        join pg_namespace ns on ns.oid = rel.relnamespace
        where ns.nspname = e.table_schema
          and rel.relname = e.table_name
          and t.tgname = e.trigger_name
          and not t.tgisinternal
    )

    union all
    select 'row level security disabled', t.name
    from expected_tables t
    join pg_class rel on rel.oid = to_regclass('public.' || quote_ident(t.name))
    where not rel.relrowsecurity

    union all
    select 'table still granted to ' || g.grantee, t.name
    from expected_tables t
    join lateral (
        select distinct grantee
        from information_schema.role_table_grants
        where table_schema = 'public'
          and table_name = t.name
          and grantee in ('anon', 'authenticated')
    ) g on true

    union all
    select 'unexpected default on registrations.created_at', column_default
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'registrations'
      and column_name = 'created_at'
      and coalesce(column_default, '') not like 'clock_timestamp%'

    union all
    select 'missing function', 'public.' || name
    from (values ('handle_new_user'), ('assert_group_has_admin')) as f (name)
    where not exists (
        select 1 from pg_proc p
        join pg_namespace ns on ns.oid = p.pronamespace
        where ns.nspname = 'public' and p.proname = f.name
    )
)
select issue, object_name
from findings
order by issue, object_name;
