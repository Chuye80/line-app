-- Return the most recently finished game day alongside the active one.
--
-- `lineapp_read_group` only ever returned a game day with status 'upcoming' or
-- 'live'. The moment a day was finished it vanished from the payload and
-- survived only as a history line, which made two things unreachable:
--
--   * the champion result, which could not survive a refresh because there was
--     nothing left to render it from, and
--   * MVP voting, which the UI renders inside the finished-day card and which
--     is only open while the day is finished and `mvp_closed_at` is null.
--
-- Rather than widen `game_day` - which the whole UI treats as "the day being
-- organised", registration and teams included - the finished day is returned
-- under its own key. It is populated only while there is no active day, so it
-- describes exactly one situation: the last day is over and the next has not
-- been created yet.

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
  finished_id uuid;
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
  ELSE
    SELECT gd.id INTO finished_id
    FROM public.game_days gd
    WHERE gd.group_id = p_group_id
      AND gd.status = 'finished'
    ORDER BY gd.finished_at DESC NULLS LAST, gd.game_datetime DESC
    LIMIT 1;
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
    'finished_game_day', CASE
      WHEN finished_id IS NULL THEN NULL
      ELSE public.lineapp_game_day_json(finished_id, viewer.id)
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
