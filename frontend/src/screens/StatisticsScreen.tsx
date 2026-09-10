import { PlayerStatsTable } from "../components/PlayerStatsTable";
import type { OverallStatistics } from "../types";

/**
 * Accumulated statistics across every finished game day.
 *
 * Deliberately a separate screen from the day's own statistics, and it says so
 * at the top: mixing "today" with "all time" in one table is how a statistics
 * page stops being trustworthy. Both are computed from the same stored matches
 * and goals, so they can never disagree.
 */
export function StatisticsScreen({
  statistics,
  ownMembershipId,
}: {
  statistics: OverallStatistics | null;
  ownMembershipId: string | null;
}) {
  if (!statistics) {
    return (
      <section className="card">
        <h2>Statistics</h2>
        <p className="empty-note">Loading…</p>
      </section>
    );
  }

  return (
    <section className="card">
      <div className="section-header">
        <div>
          <h2>Overall Statistics</h2>
          <span>
            {statistics.game_days === 0
              ? "No game day has finished yet."
              : `Across ${statistics.game_days} finished game ${
                  statistics.game_days === 1 ? "day" : "days"
                }. A day in progress is not counted until it is finished.`}
          </span>
        </div>
      </div>

      <PlayerStatsTable
        rows={statistics.players}
        variant="accumulated"
        highlight={ownMembershipId}
      />

      <p className="empty-note">
        Rating is the average of the group's survey answers. Individual answers
        are never shown.
      </p>
    </section>
  );
}
