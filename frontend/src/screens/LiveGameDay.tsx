import { useState } from "react";
import { GoalDialog } from "../components/GoalDialog";
import { PlayerStatsTable } from "../components/PlayerStatsTable";
import { StandingsTable } from "../components/StandingsTable";
import type { GameDay, Match } from "../types";

type Tab = "matches" | "standings" | "statistics" | "teams";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "matches", label: "Matches" },
  { id: "standings", label: "Standings" },
  { id: "statistics", label: "Day Statistics" },
  { id: "teams", label: "Teams" },
];

export type GoalInput = {
  team_name: string;
  scorer_membership_id: string;
  assist_membership_id: string | null;
};

/**
 * The live experience.
 *
 * Everything on this screen is about the football being played: the match on
 * the pitch, the results so far, the table and the day's statistics. Group
 * administration and the registration list are deliberately absent - once the
 * day has started there is nothing left to register for, and the registration
 * data is kept on the server for the record rather than shown here.
 */
export function LiveGameDay({
  day,
  isAdmin,
  busy,
  ownMembershipId,
  onStartMatch,
  onCompleteMatch,
  onAddGoal,
  onRemoveGoal,
  onFinishDay,
}: {
  day: GameDay;
  isAdmin: boolean;
  busy: boolean;
  ownMembershipId: string | null;
  onStartMatch: (matchId: string) => void;
  onCompleteMatch: (matchId: string) => void;
  onAddGoal: (matchId: string, goal: GoalInput) => void;
  onRemoveGoal: (matchId: string, goalId: string) => void;
  onFinishDay: () => void;
}) {
  const [tab, setTab] = useState<Tab>("matches");
  const [scoringMatch, setScoringMatch] = useState<Match | null>(null);

  const current = day.matches.find((item) => item.id === day.current_match_id);
  const next = day.matches.find((item) => item.id === day.next_match_id);
  const played = day.matches.filter((item) => item.status === "completed");
  const allPlayed = day.matches.length > 0 && played.length === day.matches.length;

  return (
    <>
      <section className="card live-header">
        <div>
          <span className="live-pill">
            <span className="live-dot" /> Game Day in progress
          </span>
          <h2>
            {played.length} of {day.matches.length} matches played
          </h2>
        </div>

        {isAdmin && (
          <button
            className={allPlayed ? "primary-button finish-button" : "secondary-button"}
            disabled={!allPlayed || busy}
            title={
              allPlayed
                ? "Close the day and crown the champions"
                : "Every match has to be played first"
            }
            onClick={onFinishDay}
          >
            Finish Game Day
          </button>
        )}
      </section>

      <MatchPitch
        current={current}
        next={next}
        allPlayed={allPlayed}
        isAdmin={isAdmin}
        busy={busy}
        onStartMatch={onStartMatch}
        onCompleteMatch={onCompleteMatch}
        onAddGoal={() => setScoringMatch(current ?? null)}
        onRemoveGoal={onRemoveGoal}
      />

      <nav className="tab-bar">
        {TABS.map((item) => (
          <button
            key={item.id}
            className={item.id === tab ? "tab active" : "tab"}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {tab === "matches" && (
        <section className="card">
          <h2>Results</h2>
          <div className="match-list">
            {day.matches.map((match) => (
              <MatchRow key={match.id} match={match} />
            ))}
          </div>
        </section>
      )}

      {tab === "standings" && (
        <section className="card">
          <h2>Standings</h2>
          <StandingsTable rows={day.standings} />
          <p className="empty-note">
            Won 3 points, drawn 1. Level teams are separated by goal difference,
            then by goals scored.
          </p>
        </section>
      )}

      {tab === "statistics" && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Game Day Statistics</h2>
              <span>Today only. Career totals live under Statistics.</span>
            </div>
          </div>

          <PlayerStatsTable
            rows={day.statistics}
            variant="day"
            highlight={ownMembershipId}
          />
        </section>
      )}

      {tab === "teams" && (
        <section className="card">
          <h2>Teams</h2>
          <div className="teams-grid">
            {day.teams.map((team) => (
              <div className="team-box" key={team.name}>
                <div className="team-header">
                  <h3>{team.name}</h3>
                  <span>Avg {team.average_rating.toFixed(1)}</span>
                </div>

                {team.players.map((player) => (
                  <p
                    key={player.id}
                    className={
                      player.id === ownMembershipId ? "own-player" : undefined
                    }
                  >
                    {player.name}
                  </p>
                ))}
              </div>
            ))}
          </div>
        </section>
      )}

      {scoringMatch && (
        <GoalDialog
          match={scoringMatch}
          teams={day.teams}
          busy={busy}
          onCancel={() => setScoringMatch(null)}
          onSubmit={(goal) => {
            onAddGoal(scoringMatch.id, goal);
            setScoringMatch(null);
          }}
        />
      )}
    </>
  );
}

function MatchPitch({
  current,
  next,
  allPlayed,
  isAdmin,
  busy,
  onStartMatch,
  onCompleteMatch,
  onAddGoal,
  onRemoveGoal,
}: {
  current?: Match;
  next?: Match;
  allPlayed: boolean;
  isAdmin: boolean;
  busy: boolean;
  onStartMatch: (matchId: string) => void;
  onCompleteMatch: (matchId: string) => void;
  onAddGoal: () => void;
  onRemoveGoal: (matchId: string, goalId: string) => void;
}) {
  if (current) {
    return (
      <section className="card pitch-card">
        <span className="pitch-label">On the pitch</span>

        <div className="scoreline">
          <span className="scoreline-team">{current.home_team}</span>
          <span className="scoreline-score">
            {current.home_score} – {current.away_score}
          </span>
          <span className="scoreline-team">{current.away_team}</span>
        </div>

        {isAdmin && (
          <div className="pitch-actions">
            <button className="primary-button" disabled={busy} onClick={onAddGoal}>
              ⚽ Add Goal
            </button>

            <button
              className="secondary-button"
              disabled={busy}
              onClick={() => onCompleteMatch(current.id)}
            >
              Finish Match
            </button>
          </div>
        )}

        {current.goals.length > 0 && (
          <ul className="goal-feed">
            {current.goals.map((goal) => (
              <li key={goal.id}>
                <span className="goal-team">{goal.team_name}</span>
                <span>
                  {goal.scorer_name}
                  {goal.assist_name && (
                    <span className="assist"> (assist {goal.assist_name})</span>
                  )}
                </span>

                {isAdmin && (
                  <button
                    className="text-danger-button"
                    disabled={busy}
                    onClick={() => onRemoveGoal(current.id, goal.id)}
                  >
                    Remove
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }

  if (allPlayed) {
    return (
      <section className="card pitch-card">
        <span className="pitch-label">All matches played</span>
        <p className="pitch-message">
          The football is done. Finish the Game Day to crown the champions.
        </p>
      </section>
    );
  }

  return (
    <section className="card pitch-card">
      <span className="pitch-label">Up next</span>

      {next ? (
        <>
          <div className="scoreline">
            <span className="scoreline-team">{next.home_team}</span>
            <span className="scoreline-score muted">vs</span>
            <span className="scoreline-team">{next.away_team}</span>
          </div>

          {isAdmin && (
            <div className="pitch-actions">
              <button
                className="primary-button"
                disabled={busy}
                onClick={() => onStartMatch(next.id)}
              >
                Kick Off
              </button>
            </div>
          )}
        </>
      ) : (
        <p className="pitch-message">No matches left to play.</p>
      )}
    </section>
  );
}

function MatchRow({ match }: { match: Match }) {
  const label =
    match.status === "completed"
      ? "Full time"
      : match.status === "live"
        ? "Playing"
        : "Scheduled";

  return (
    <div className={`match-row ${match.status}`}>
      <span className="match-order">{match.match_order}</span>

      <span className="match-teams">
        {match.home_team} <span className="muted">vs</span> {match.away_team}
      </span>

      <span className="match-score">
        {match.status === "scheduled"
          ? "–"
          : `${match.home_score} – ${match.away_score}`}
      </span>

      <span className={`match-status ${match.status}`}>{label}</span>
    </div>
  );
}
