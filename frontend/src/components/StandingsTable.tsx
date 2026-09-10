import type { StandingsRow } from "../types";

/**
 * The league table.
 *
 * Full column names would not fit a phone, so the head is abbreviated the way
 * a printed table is, with the long name in a tooltip.
 */
const COLUMNS: Array<{ key: keyof StandingsRow; short: string; long: string }> = [
  { key: "played", short: "P", long: "Played" },
  { key: "wins", short: "W", long: "Wins" },
  { key: "draws", short: "D", long: "Draws" },
  { key: "losses", short: "L", long: "Losses" },
  { key: "goals_for", short: "GF", long: "Goals for" },
  { key: "goals_against", short: "GA", long: "Goals against" },
  { key: "goal_difference", short: "GD", long: "Goal difference" },
  { key: "points", short: "Pts", long: "Points" },
];

export function StandingsTable({
  rows,
  champions = [],
}: {
  rows: StandingsRow[];
  champions?: string[];
}) {
  if (rows.length === 0) {
    return <p className="empty-note">The table fills in as matches finish.</p>;
  }

  return (
    <div className="table-scroll">
      <table className="data-table standings-table">
        <thead>
          <tr>
            <th className="numeric">#</th>
            <th>Team</th>
            {COLUMNS.map((column) => (
              <th className="numeric" key={column.key} title={column.long}>
                {column.short}
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {rows.map((row) => (
            <tr
              key={row.team}
              className={champions.includes(row.team) ? "champion-row" : undefined}
            >
              <td className="numeric">{row.position}</td>
              <td className="team-cell">
                {row.team}
                {champions.includes(row.team) && (
                  <span className="champion-mark" title="Champions">
                    🏆
                  </span>
                )}
              </td>
              {COLUMNS.map((column) => (
                <td
                  className={
                    column.key === "points" ? "numeric strong" : "numeric"
                  }
                  key={column.key}
                >
                  {column.key === "goal_difference" && row.goal_difference > 0
                    ? `+${row.goal_difference}`
                    : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
