-- Promotion runs from group reads, on a different connection from registration.
-- Lock the game day before counting free spots so a read cannot promote a
-- waiter into a spot an in-flight registration is also taking.
-- The lock is its own statement: once it returns, the count sees every
-- participant row committed before the lock was acquired.

CREATE OR REPLACE FUNCTION public.lineapp_promote_waiting(p_game_day_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  v_free integer;
  v_priority boolean;
  v_promoted integer;
BEGIN
  PERFORM 1
  FROM public.game_days
  WHERE id = p_game_day_id
  FOR UPDATE;

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
