import { useMemo, useState } from "react";
import type { PlayerStatsRow } from "../types";

type Column = {
  key: keyof PlayerStatsRow;
  short: string;
  long: string;
};

const PER_DAY_COLUMNS: Column[] = [
  { key: "goals", short: "G", long: "Goals" },
  { key: "assists", short: "A", long: "Assists" },
  { key: "points", short: "G+A", long: "Goals plus assists" },
  { key: "matches", short: "MP", long: "Matches played" },
  { key: "wins", short: "W", long: "Wins" },
  { key: "draws", short: "D", long: "Draws" },
  { key: "losses", short: "L", long: "Losses" },
];

const ACCUMULATED_COLUMNS: Column[] = [
  { key: "game_days", short: "Days", long: "Game days played" },
  ...PER_DAY_COLUMNS,
  { key: "survey_rating", short: "Rating", long: "Average survey rating" },
];

/**
 * One row per player, sortable by any column.
 *
 * The same table serves the day's statistics and the accumulated ones; only
 * the columns differ, which is deliberate - the two views should look like the
 * same table over different periods, not like two different features.
 */
export function PlayerStatsTable({
  rows,
  variant,
  highlight,
}: {
  rows: PlayerStatsRow[];
  variant: "day" | "accumulated";
  highlight?: string | null;
}) {
  const columns = variant === "day" ? PER_DAY_COLUMNS : ACCUMULATED_COLUMNS;
  const [sortKey, setSortKey] = useState<keyof PlayerStatsRow>("goals");
  const [ascending, setAscending] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...rows];

    copy.sort((left, right) => {
      const a = left[sortKey];
      const b = right[sortKey];

      if (typeof a === "string" || typeof b === "string") {
        const compared = String(a).localeCompare(String(b));
        return ascending ? compared : -compared;
      }

      // A player nobody has rated sorts below everyone rather than as a zero.
      const first = a ?? -1;
      const second = b ?? -1;

      if (first === second) {
        return left.name.localeCompare(right.name);
      }

      return ascending
        ? Number(first) - Number(second)
        : Number(second) - Number(first);
    });

    return copy;
  }, [rows, sortKey, ascending]);

  function sortBy(key: keyof PlayerStatsRow) {
    if (key === sortKey) {
      setAscending((previous) => !previous);
      return;
    }

    setSortKey(key);
    setAscending(key === "name");
  }

  if (rows.length === 0) {
    return <p className="empty-note">No statistics recorded yet.</p>;
  }

  const arrow = (key: keyof PlayerStatsRow) =>
    key === sortKey ? (ascending ? " ▲" : " ▼") : "";

  return (
    <div className="table-scroll">
      <table className="data-table stats-table">
        <thead>
          <tr>
            <th>
              <button className="sort-button" onClick={() => sortBy("name")}>
                Player{arrow("name")}
              </button>
            </th>

            {columns.map((column) => (
              <th className="numeric" key={column.key}>
                <button
                  className="sort-button"
                  title={`Sort by ${column.long.toLowerCase()}`}
                  onClick={() => sortBy(column.key)}
                >
                  {column.short}
                  {arrow(column.key)}
                </button>
              </th>
            ))}
          </tr>
        </thead>

        <tbody>
          {sorted.map((row) => (
            <tr
              key={row.membership_id}
              className={
                highlight && row.membership_id === highlight ? "own-row" : undefined
              }
            >
              <td className="player-cell">
                {row.name}
                {row.is_virtual && <span className="tag">virtual</span>}
              </td>

              {columns.map((column) => (
                <td className="numeric" key={column.key}>
                  {column.key === "survey_rating"
                    ? formatRating(row)
                    : row[column.key] ?? 0}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function formatRating(row: PlayerStatsRow) {
  if (row.survey_rating === null || row.survey_rating === undefined) {
    return <span className="muted">–</span>;
  }

  return (
    <span title={`${row.survey_responses ?? 0} responses`}>
      {row.survey_rating.toFixed(1)}
    </span>
  );
}
