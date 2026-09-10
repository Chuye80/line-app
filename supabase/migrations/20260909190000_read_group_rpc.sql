CREATE OR REPLACE FUNCTION public.lineapp_member_json(
  p_id uuid,
  p_user_id uuid,
  p_display_name text,
  p_rating numeric,
  p_is_subscriber boolean,
  p_is_admin boolean,
  p_profile_name text
) RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $$
  SELECT jsonb_build_object(
    'id', p_id::text,
    'user_id', CASE WHEN p_user_id IS NULL THEN NULL ELSE p_user_id::text END,
    'name', CASE
      WHEN p_user_id IS NULL THEN COALESCE(p_display_name, 'Virtual Player')
      ELSE COALESCE(p_profile_name, 'Player')
    END,
    'rating', p_rating::float8,
    'is_subscriber', p_is_subscriber,
    'is_admin', p_is_admin,
    'is_virtual', p_user_id IS NULL
  );
$$;


CREATE OR REPLACE FUNCTION public.lineapp_promote_waiting(p_game_day_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_free integer;
  v_priority boolean;
  v_promoted integer;
BEGIN
  SELECT
    gd.participant_count - (
      SELECT count(*)::int
      FROM registrations r
      WHERE r.game_day_id = gd.id AND r.status = 'participant'
    ),
    now() < gd.regular_registration_opens
  INTO v_free, v_priority
  FROM game_days gd
  WHERE gd.id = p_game_day_id;

  IF v_free IS NULL OR v_free <= 0 THEN
    RETURN;
  END IF;

  WITH ranked AS (
    SELECT r.id,
           row_number() OVER (ORDER BY r.created_at) AS rn
    FROM registrations r
    JOIN memberships m ON m.id = r.membership_id
    WHERE r.game_day_id = p_game_day_id
      AND r.status = 'waiting'
      AND (NOT v_priority OR m.is_subscriber)
  )
  UPDATE registrations
  SET status = 'participant'
  WHERE id IN (SELECT ranked.id FROM ranked WHERE ranked.rn <= v_free);

  GET DIAGNOSTICS v_promoted = ROW_COUNT;
  IF v_promoted > 0 THEN
    DELETE FROM team_assignments WHERE game_day_id = p_game_day_id;
  END IF;
END;
$$;


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
              'scorer', ns.obj,
              'assist', na.obj
            )
            ORDER BY g.created_at
          )
          FROM match_goals g
          JOIN named ns ON ns.id = g.scorer_membership_id
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


CREATE OR REPLACE FUNCTION public.lineapp_read_group(
  p_group_id uuid,
  p_user_id uuid
) RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
  g public.groups%ROWTYPE;
  viewer public.memberships%ROWTYPE;
  current_id uuid;
  payload jsonb;
BEGIN
  SELECT * INTO g FROM public.groups WHERE id = p_group_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', 'not_found');
  END IF;

  SELECT * INTO viewer
  FROM public.memberships
  WHERE group_id = p_group_id AND user_id = p_user_id;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('error', 'forbidden');
  END IF;

  UPDATE public.game_days
  SET status = 'live'
  WHERE group_id = p_group_id
    AND status = 'upcoming'
    AND game_datetime <= now();

  SELECT gd.id INTO current_id
  FROM public.game_days gd
  WHERE gd.group_id = p_group_id
    AND gd.status IN ('upcoming', 'live')
  ORDER BY gd.game_datetime DESC
  LIMIT 1;

  IF current_id IS NOT NULL THEN
    PERFORM public.lineapp_promote_waiting(current_id);
  END IF;

  payload := jsonb_build_object(
    'id', g.id::text,
    'name', g.name,
    'last_participant_count', g.last_participant_count,
    'last_players_per_team', g.last_players_per_team,
    'members', coalesce((
      SELECT jsonb_agg(
        public.lineapp_member_json(
          m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
        )
        ORDER BY m.created_at
      )
      FROM memberships m
      LEFT JOIN profiles p ON p.id = m.user_id
      WHERE m.group_id = g.id
    ), '[]'::jsonb),
    'game_day', CASE
      WHEN current_id IS NULL THEN NULL
      ELSE public.lineapp_game_day_json(current_id, viewer.id)
    END,
    'history', coalesce((
      SELECT jsonb_agg(item.obj ORDER BY item.game_datetime DESC)
      FROM (
        SELECT
          gd.game_datetime,
          jsonb_build_object(
            'id', gd.id::text,
            'game_datetime', gd.game_datetime,
            'status', gd.status,
            'is_rotating', gd.is_rotating,
            'champion_team_name', gd.champion_team_name,
            'awards', jsonb_build_object(
              'champions', coalesce((
                SELECT jsonb_agg(public.lineapp_member_json(
                  m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
                ))
                FROM game_day_awards a
                JOIN memberships m ON m.id = a.membership_id
                LEFT JOIN profiles p ON p.id = m.user_id
                WHERE a.game_day_id = gd.id AND a.award_type = 'champion'
              ), '[]'::jsonb),
              'mvps', coalesce((
                SELECT jsonb_agg(public.lineapp_member_json(
                  m.id, m.user_id, m.display_name, m.rating, m.is_subscriber, m.is_admin, p.display_name
                ))
                FROM game_day_awards a
                JOIN memberships m ON m.id = a.membership_id
                LEFT JOIN profiles p ON p.id = m.user_id
                WHERE a.game_day_id = gd.id AND a.award_type = 'mvp'
              ), '[]'::jsonb)
            )
          ) AS obj
        FROM game_days gd
        WHERE gd.group_id = g.id AND gd.status = 'finished'
      ) item
    ), '[]'::jsonb),
    'survey', (
      SELECT jsonb_build_object(
        'id', s.id::text,
        'status', s.status,
        'created_at', s.created_at,
        'closed_at', s.closed_at,
        'my_ratings', coalesce((
          SELECT jsonb_object_agg(r.rated_membership_id::text, r.rating)
          FROM rating_survey_responses r
          WHERE r.survey_id = s.id AND r.rater_membership_id = viewer.id
        ), '{}'::jsonb)
      )
      FROM rating_surveys s
      WHERE s.group_id = g.id
      ORDER BY s.created_at DESC
      LIMIT 1
    )
  );

  IF viewer.is_admin THEN
    payload := payload || jsonb_build_object(
      'invite_code', g.invite_code,
      'invite_link', 'http://127.0.0.1:5173/?invite=' || g.invite_code,
      'join_requests', coalesce((
        SELECT jsonb_agg(
          jsonb_build_object(
            'id', jr.id::text,
            'user_id', jr.user_id::text,
            'user_name', coalesce(p.display_name, 'Player'),
            'status', jr.status
          )
          ORDER BY jr.created_at
        )
        FROM join_requests jr
        LEFT JOIN profiles p ON p.id = jr.user_id
        WHERE jr.group_id = g.id AND jr.status = 'pending'
      ), '[]'::jsonb)
    );
  END IF;

  RETURN payload;
END;
$$;
