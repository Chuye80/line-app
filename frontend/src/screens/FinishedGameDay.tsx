import { useState } from "react";
import { Confetti } from "../components/Confetti";
import { PlayerStatsTable } from "../components/PlayerStatsTable";
import { StandingsTable } from "../components/StandingsTable";
import type { GameDay } from "../types";

type View = "champions" | "table" | "statistics";

/**
 * The completion screen.
 *
 * A finished day is a stored fact, so this screen survives a refresh: coming
 * back to the app shows the champions again rather than dropping the user into
 * a day that has apparently restarted.
 */
export function FinishedGameDay({
  day,
  ownMembershipId,
  onReturnHome,
}: {
  day: GameDay;
  ownMembershipId: string | null;
  onReturnHome: () => void;
}) {
  const [view, setView] = useState<View>("champions");

  const championTeams = day.teams.filter((team) =>
    day.champions.includes(team.name)
  );

  const played = new Date(day.finished_at ?? day.game_datetime);

  return (
    <>
      <section className="card trophy-card">
        {view === "champions" && <Confetti />}

        <div className="trophy-content">
          <span className="trophy-icon">🏆</span>
          <h2>Game Day Champions</h2>

          <p className="champion-name">
            {day.champions.length > 0
              ? day.champions.join(" & ")
              : "No champion"}
          </p>

          {day.champions.length > 1 && (
            <p className="champion-note">
              Level on points, goal difference and goals scored.
            </p>
          )}

          <div className="champion-squads">
            {championTeams.map((team) => (
              <div className="champion-squad" key={team.name}>
                {championTeams.length > 1 && <h3>{team.name}</h3>}

                <ul>
                  {team.players.map((player) => (
                    <li
                      key={player.id}
                      className={
                        player.id === ownMembershipId ? "own-player" : undefined
                      }
                    >
                      {player.name}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <p className="champion-meta">
            {played.toLocaleDateString(undefined, {
              weekday: "long",
              day: "numeric",
              month: "long",
            })}{" "}
            · {day.matches.length} matches ·{" "}
            {day.matches.reduce(
              (total, match) => total + match.home_score + match.away_score,
              0
            )}{" "}
            goals
          </p>
        </div>
      </section>

      <div className="completion-actions">
        <button
          className={view === "statistics" ? "primary-button" : "secondary-button"}
          onClick={() => setView("statistics")}
        >
          View Day Statistics
        </button>

        <button
          className={view === "table" ? "primary-button" : "secondary-button"}
          onClick={() => setView("table")}
        >
          View Final Table
        </button>

        <button className="secondary-button" onClick={onReturnHome}>
          Return Home
        </button>
      </div>

      {view === "table" && (
        <section className="card">
          <h2>Final Table</h2>
          <StandingsTable rows={day.standings} champions={day.champions} />

          <h3>Results</h3>
          <div className="match-list">
            {day.matches.map((match) => (
              <div className="match-row completed" key={match.id}>
                <span className="match-order">{match.match_order}</span>
                <span className="match-teams">
                  {match.home_team} <span className="muted">vs</span>{" "}
                  {match.away_team}
                </span>
                <span className="match-score">
                  {match.home_score} – {match.away_score}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {view === "statistics" && (
        <section className="card">
          <div className="section-header">
            <div>
              <h2>Game Day Statistics</h2>
              <span>This day only.</span>
            </div>
          </div>

          <PlayerStatsTable
            rows={day.statistics}
            variant="day"
            highlight={ownMembershipId}
          />
        </section>
      )}
    </>
  );
}
