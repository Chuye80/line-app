import { useMemo, useState } from "react";
import type { Match, Team } from "../types";

/**
 * Record a goal in the match being played.
 *
 * The player lists come from the two teams on the pitch, taken from the game
 * day's own line-ups. That is the fix for the original bug: the dropdowns used
 * to be built from the signed-in user's registration state, so they contained
 * exactly one name.
 *
 * Once the scoring team is chosen, both the scorer and the assist are limited
 * to that team, and a player cannot assist their own goal.
 */
export function GoalDialog({
  match,
  teams,
  busy,
  onCancel,
  onSubmit,
}: {
  match: Match;
  teams: Team[];
  busy: boolean;
  onCancel: () => void;
  onSubmit: (goal: {
    team_name: string;
    scorer_membership_id: string;
    assist_membership_id: string | null;
  }) => void;
}) {
  const [teamName, setTeamName] = useState(match.home_team);
  const [scorerId, setScorerId] = useState("");
  const [assistId, setAssistId] = useState("");

  const lineups = useMemo(() => {
    const byName = new Map(teams.map((team) => [team.name, team.players]));

    return {
      [match.home_team]: byName.get(match.home_team) ?? [],
      [match.away_team]: byName.get(match.away_team) ?? [],
    };
  }, [teams, match.home_team, match.away_team]);

  const squad = lineups[teamName] ?? [];
  const assistOptions = squad.filter((player) => player.id !== scorerId);

  function chooseTeam(next: string) {
    setTeamName(next);
    // The previous choices belonged to the other team's line-up.
    setScorerId("");
    setAssistId("");
  }

  function chooseScorer(next: string) {
    setScorerId(next);

    if (next === assistId) {
      setAssistId("");
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <h3>Add goal</h3>
        <p className="modal-subtitle">
          {match.home_team} {match.home_score} – {match.away_score}{" "}
          {match.away_team}
        </p>

        <label>
          Scoring team
          <div className="team-choice">
            {[match.home_team, match.away_team].map((name) => (
              <button
                key={name}
                type="button"
                className={
                  name === teamName ? "choice-chip active" : "choice-chip"
                }
                onClick={() => chooseTeam(name)}
              >
                {name}
              </button>
            ))}
          </div>
        </label>

        <label>
          Scorer
          <select
            value={scorerId}
            onChange={(event) => chooseScorer(event.target.value)}
          >
            <option value="">Select a player…</option>
            {squad.map((player) => (
              <option key={player.id} value={player.id}>
                {player.name}
              </option>
            ))}
          </select>
        </label>

        <label>
          Assist <span className="label-hint">optional</span>
          <select
            value={assistId}
            onChange={(event) => setAssistId(event.target.value)}
            disabled={!scorerId}
          >
            <option value="">No assist</option>
            {assistOptions.map((player) => (
              <option key={player.id} value={player.id}>
                {player.name}
              </option>
            ))}
          </select>
        </label>

        <div className="form-actions">
          <button
            className="primary-button"
            disabled={!scorerId || busy}
            onClick={() =>
              onSubmit({
                team_name: teamName,
                scorer_membership_id: scorerId,
                assist_membership_id: assistId || null,
              })
            }
          >
            Add goal
          </button>

          <button className="secondary-button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
