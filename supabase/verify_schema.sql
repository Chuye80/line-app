-- Drift check for the beta game-days migration line.
--
--   psql "$DATABASE_URL" -f supabase/verify_schema.sql
--
-- An empty result set means the connected database matches supabase/migrations.

with expected_tables (name) as (
    values
        ('profiles'), ('groups'), ('memberships'), ('join_requests'),
        ('game_days'), ('registrations'), ('team_assignments'),
        ('developers'), ('matches'), ('match_players'), ('match_goals'),
        ('mvp_votes'), ('game_day_awards'), ('rating_surveys'),
        ('rating_survey_responses'), ('group_messages')
),
expected_columns (table_name, column_name) as (
    values
        ('profiles', 'id'), ('profiles', 'display_name'), ('profiles', 'created_at'),
        ('groups', 'id'), ('groups', 'name'), ('groups', 'created_by'), ('groups', 'created_at'),
        ('groups', 'invite_code'), ('groups', 'last_participant_count'), ('groups', 'last_players_per_team'),
        ('memberships', 'id'), ('memberships', 'group_id'), ('memberships', 'user_id'),
        ('memberships', 'display_name'), ('memberships', 'rating'),
        ('memberships', 'goalkeeper_rating'), ('memberships', 'game_day_id'),
        ('memberships', 'is_subscriber'), ('memberships', 'is_admin'), ('memberships', 'created_at'),
        ('join_requests', 'id'), ('join_requests', 'group_id'), ('join_requests', 'user_id'),
        ('join_requests', 'status'), ('join_requests', 'created_at'),
        ('game_days', 'id'), ('game_days', 'group_id'), ('game_days', 'game_datetime'),
        ('game_days', 'regular_registration_opens'), ('game_days', 'created_at'),
        ('game_days', 'status'), ('game_days', 'participant_count'), ('game_days', 'players_per_team'),
        ('game_days', 'is_rotating'), ('game_days', 'champion_team_name'),
        ('game_days', 'mvp_closed_at'), ('game_days', 'finished_at'),
        ('registrations', 'id'), ('registrations', 'game_day_id'), ('registrations', 'membership_id'),
        ('registrations', 'status'), ('registrations', 'created_at'),
        ('team_assignments', 'id'), ('team_assignments', 'game_day_id'),
        ('team_assignments', 'membership_id'), ('team_assignments', 'team_name'),
        ('developers', 'user_id'), ('developers', 'created_at'),
        ('matches', 'id'), ('matches', 'game_day_id'), ('matches', 'home_team_name'),
        ('matches', 'away_team_name'), ('matches', 'home_score'), ('matches', 'away_score'),
        ('matches', 'status'), ('matches', 'created_at'), ('matches', 'completed_at'),
        ('match_players', 'id'), ('match_players', 'match_id'), ('match_players', 'membership_id'),
        ('match_players', 'team_name'),
        ('match_goals', 'id'), ('match_goals', 'match_id'), ('match_goals', 'team_name'),
        ('match_goals', 'scorer_membership_id'), ('match_goals', 'assist_membership_id'),
        ('match_goals', 'created_at'),
        ('mvp_votes', 'id'), ('mvp_votes', 'game_day_id'), ('mvp_votes', 'voter_membership_id'),
        ('mvp_votes', 'nominee_membership_id'), ('mvp_votes', 'created_at'),
        ('game_day_awards', 'id'), ('game_day_awards', 'game_day_id'), ('game_day_awards', 'membership_id'),
        ('game_day_awards', 'award_type'), ('game_day_awards', 'created_at'),
        ('rating_surveys', 'id'), ('rating_surveys', 'group_id'), ('rating_surveys', 'status'),
        ('rating_surveys', 'created_at'), ('rating_surveys', 'closed_at'),
        ('rating_survey_responses', 'id'), ('rating_survey_responses', 'survey_id'),
        ('rating_survey_responses', 'rater_membership_id'), ('rating_survey_responses', 'rated_membership_id'),
        ('rating_survey_responses', 'rating'), ('rating_survey_responses', 'goalkeeper_rating'),
        ('rating_survey_responses', 'created_at'),
        ('group_messages', 'id'), ('group_messages', 'group_id'), ('group_messages', 'sender_user_id'),
        ('group_messages', 'message'), ('group_messages', 'created_at')
),
expected_public_functions (name) as (
    values
        ('handle_new_user'),
        ('assert_group_has_admin'),
        ('preview_group_by_invite'),
        ('lineapp_member_json'),
        ('lineapp_promote_waiting'),
        ('lineapp_game_day_json'),
        ('lineapp_read_group')
),
expected_private_functions (name) as (
    values
        ('is_group_member'),
        ('is_group_admin')
),
expected_triggers (table_schema, table_name, trigger_name) as (
    values
        ('auth', 'users', 'on_auth_user_created'),
        ('public', 'memberships', 'memberships_require_admin')
),
rls_locked_tables (name) as (
    values
        ('profiles'), ('groups'), ('memberships'), ('join_requests'),
        ('game_days'), ('registrations'), ('team_assignments'),
        ('developers'), ('matches'), ('match_players'), ('match_goals'),
        ('mvp_votes'), ('game_day_awards'), ('rating_surveys'),
        ('rating_survey_responses')
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
    select 'row level security disabled', t.name
    from rls_locked_tables t
    join pg_class rel on rel.oid = to_regclass('public.' || quote_ident(t.name))
    where not rel.relrowsecurity

    union all
    select 'table still granted to ' || g.grantee, t.name
    from rls_locked_tables t
    join lateral (
        select distinct grantee
        from information_schema.role_table_grants
        where table_schema = 'public'
          and table_name = t.name
          and grantee in ('anon', 'authenticated')
    ) g on true

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
    select 'missing function', 'public.' || name
    from expected_public_functions f
    where not exists (
        select 1 from pg_proc p
        join pg_namespace ns on ns.oid = p.pronamespace
        where ns.nspname = 'public' and p.proname = f.name
    )

    union all
    select 'missing function', 'private.' || name
    from expected_private_functions f
    where not exists (
        select 1 from pg_proc p
        join pg_namespace ns on ns.oid = p.pronamespace
        where ns.nspname = 'private' and p.proname = f.name
    )

    union all
    select 'private helper missing EXECUTE for authenticated', p.proname
    from pg_proc p
    join pg_namespace ns on ns.oid = p.pronamespace
    where ns.nspname = 'private'
      and p.proname in ('is_group_member', 'is_group_admin')
      and not has_function_privilege('authenticated', p.oid, 'EXECUTE')

    union all
    select 'private helper EXECUTE granted to anon', p.proname
    from pg_proc p
    join pg_namespace ns on ns.oid = p.pronamespace
    where ns.nspname = 'private'
      and p.proname in ('is_group_member', 'is_group_admin')
      and has_function_privilege('anon', p.oid, 'EXECUTE')

    union all
    select 'unexpected default on registrations.created_at', column_default
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'registrations'
      and column_name = 'created_at'
      and coalesce(column_default, '') not like 'clock_timestamp%'

    union all
    select 'legacy table still present', 'public.games'
    where to_regclass('public.games') is not null

    union all
    select 'legacy table still present', 'public.player_ratings'
    where to_regclass('public.player_ratings') is not null
)
select issue, object_name
from findings
order by issue, object_name;
