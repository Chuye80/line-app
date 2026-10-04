-- Goal events become the source of truth: each row records the scoring team,
-- with optional scorer and assist.

alter table public.match_goals
  add column if not exists team_name text;

update public.match_goals g
set team_name = mp.team_name
from public.match_players mp
where g.team_name is null
  and mp.match_id = g.match_id
  and mp.membership_id = g.scorer_membership_id;

update public.match_goals
set team_name = 'Unknown'
where team_name is null;

alter table public.match_goals
  alter column team_name set not null;

alter table public.match_goals
  alter column scorer_membership_id drop not null;

-- Baseline: public.lineapp_game_day_json as defined in
-- 20260909190000_read_group_rpc.sql. Beta.8 adds
-- 20261002093700_goalkeeper_ratings.sql, which updates lineapp_member_json
-- only; game-day members still call that helper and pick up goalkeeper_rating
-- automatically. Only the match goal JSON subquery is changed here.
CREATE OR REPLACE FUNCTION public.lineapp_game_day_json(
  p_game_day_id uuid,
  p_viewer_membership_id uuid
) RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
  WITH gd AS (
    SELECT *
    FROM game_days
    WHERE id = p_game_day_id
  ),
  named AS (
    SELECT
      m.id,
      public.lineapp_member_json(
        m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
      ) AS obj
    FROM memberships m
    LEFT JOIN profiles p ON p.id = m.user_id
  ),
  participants AS (
    SELECT coalesce(
      jsonb_agg(n.obj ORDER BY r.created_at),
      '[]'::jsonb
    ) AS arr
    FROM registrations r
    JOIN named n ON n.id = r.membership_id
    WHERE r.game_day_id = p_game_day_id AND r.status = 'participant'
  ),
  waiting AS (
    SELECT coalesce(
      jsonb_agg(n.obj ORDER BY r.created_at),
      '[]'::jsonb
    ) AS arr
    FROM registrations r
    JOIN named n ON n.id = r.membership_id
    WHERE r.game_day_id = p_game_day_id AND r.status = 'waiting'
  ),
  teams AS (
    SELECT coalesce(
      jsonb_agg(
        jsonb_build_object(
          'name', bucket.team_name,
          'players', bucket.players,
          'total_rating', bucket.total_rating,
          'average_rating', bucket.average_rating
        )
        ORDER BY bucket.team_name
      ),
      '[]'::jsonb
    ) AS arr
    FROM (
      SELECT
        ta.team_name,
        jsonb_agg(n.obj ORDER BY ta.id) AS players,
        round(sum(m.rating)::numeric, 1)::float8 AS total_rating,
        round(avg(m.rating)::numeric, 2)::float8 AS average_rating
      FROM team_assignments ta
      JOIN memberships m ON m.id = ta.membership_id
      JOIN named n ON n.id = m.id
      WHERE ta.game_day_id = p_game_day_id AND ta.team_name IS NOT NULL
      GROUP BY ta.team_name
    ) bucket
  ),
  unassigned AS (
    SELECT coalesce(jsonb_agg(n.obj ORDER BY ta.id), '[]'::jsonb) AS arr
    FROM team_assignments ta
    JOIN named n ON n.id = ta.membership_id
    WHERE ta.game_day_id = p_game_day_id AND ta.team_name IS NULL
  ),
  match_rows AS (
    SELECT
      mt.id,
      mt.created_at,
      jsonb_build_object(
        'id', mt.id::text,
        'home_team_name', mt.home_team_name,
        'away_team_name', mt.away_team_name,
        'home_score', mt.home_score,
        'away_score', mt.away_score,
        'status', mt.status,
        'players', coalesce((
          SELECT jsonb_agg(
            n.obj || jsonb_build_object('team_name', mp.team_name)
            ORDER BY mp.id
          )
          FROM match_players mp
          JOIN named n ON n.id = mp.membership_id
          WHERE mp.match_id = mt.id
        ), '[]'::jsonb),
        'goals', coalesce((
          SELECT jsonb_agg(
            jsonb_build_object(
              'id', g.id::text,
              'team_name', g.team_name,
              'scorer', ns.obj,
              'assist', na.obj
            )
            ORDER BY g.created_at
          )
          FROM match_goals g
          LEFT JOIN named ns ON ns.id = g.scorer_membership_id
          LEFT JOIN named na ON na.id = g.assist_membership_id
          WHERE g.match_id = mt.id
        ), '[]'::jsonb)
      ) AS obj
    FROM matches mt
    WHERE mt.game_day_id = p_game_day_id
  ),
  awards AS (
    SELECT jsonb_build_object(
      'champions', coalesce(jsonb_agg(n.obj) FILTER (WHERE a.award_type = 'champion'), '[]'::jsonb),
      'mvps', coalesce(jsonb_agg(n.obj) FILTER (WHERE a.award_type = 'mvp'), '[]'::jsonb)
    ) AS obj
    FROM game_day_awards a
    JOIN named n ON n.id = a.membership_id
    WHERE a.game_day_id = p_game_day_id
  ),
  votes AS (
    SELECT
      count(*)::int AS votes_cast,
      max(CASE WHEN v.voter_membership_id = p_viewer_membership_id
        THEN v.nominee_membership_id::text END) AS my_vote
    FROM mvp_votes v
    WHERE v.game_day_id = p_game_day_id
  )
  SELECT jsonb_build_object(
    'id', gd.id::text,
    'game_datetime', gd.game_datetime,
    'regular_registration_opens', gd.regular_registration_opens,
    'status', gd.status,
    'participant_count', gd.participant_count,
    'players_per_team', gd.players_per_team,
    'is_rotating', gd.is_rotating,
    'champion_team_name', gd.champion_team_name,
    'mvp_open', gd.status = 'finished' AND gd.mvp_closed_at IS NULL,
    'mvp_announced', gd.mvp_closed_at IS NOT NULL,
    'votes_cast', coalesce((SELECT votes_cast FROM votes), 0),
    'eligible_voters', (
      SELECT count(*)::int
      FROM registrations r
      JOIN memberships m ON m.id = r.membership_id
      WHERE r.game_day_id = gd.id
        AND r.status = 'participant'
        AND m.user_id IS NOT NULL
    ),
    'my_vote', (SELECT my_vote FROM votes),
    'participants', (SELECT arr FROM participants),
    'waiting_list', (SELECT arr FROM waiting),
    'teams', (SELECT arr FROM teams),
    'unassigned', (SELECT arr FROM unassigned),
    'complete_teams', gd.participant_count / gd.players_per_team,
    'leftover_players', gd.participant_count % gd.players_per_team,
    'matches', coalesce((SELECT jsonb_agg(obj ORDER BY created_at) FROM match_rows), '[]'::jsonb),
    'standings', '[]'::jsonb,
    'awards', coalesce((SELECT obj FROM awards), '{"champions":[],"mvps":[]}'::jsonb)
  )
  FROM gd;
$$;
