import { useState } from "react";
import { StandingsTable } from "../components/StandingsTable";
import type { HistoryEntry } from "../types";

export function HistoryScreen({ entries }: { entries: HistoryEntry[] | null }) {
  const [open, setOpen] = useState<string | null>(null);

  if (!entries) {
    return (
      <section className="card">
        <h2>History</h2>
        <p className="empty-note">Loading…</p>
      </section>
    );
  }

  if (entries.length === 0) {
    return (
      <section className="card">
        <h2>History</h2>
        <p className="empty-note">
          Finished game days appear here with their champions and final table.
        </p>
      </section>
    );
  }

  return (
    <section className="card">
      <h2>History</h2>

      <div className="history-list">
        {entries.map((entry) => (
          <div className="history-entry" key={entry.id}>
            <button
              className="history-summary"
              onClick={() => setOpen(open === entry.id ? null : entry.id)}
            >
              <span className="history-date">
                {new Date(entry.game_datetime).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })}
              </span>

              <span className="history-champion">
                🏆 {entry.champions.join(" & ") || "No champion"}
              </span>

              <span className="history-meta">
                {entry.matches_played} matches · {entry.goals} goals
              </span>
            </button>

            {open === entry.id && (
              <StandingsTable
                rows={entry.standings}
                champions={entry.champions}
              />
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
