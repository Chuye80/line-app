import { useMemo, useState } from "react";
import { StarRating } from "../components/StarRating";
import type { Survey } from "../types";

/**
 * The rating survey.
 *
 * Every other member of the group is listed - the server never includes the
 * person filling it in, so there is no way to rate yourself - and each answer
 * is a value from 1.0 to 5.0 in half steps. Answers are private: only the
 * average ever appears anywhere else in the app.
 */
export function SurveyScreen({
  survey,
  busy,
  onSave,
}: {
  survey: Survey | null;
  busy: boolean;
  onSave: (
    ratings: Array<{ membership_id: string; rating: number | null }>
  ) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Record<string, number | null> | null>(null);

  const saved = useMemo(() => {
    const values: Record<string, number | null> = {};
    survey?.players.forEach((player) => {
      values[player.membership_id] = player.my_rating;
    });
    return values;
  }, [survey]);

  // Show the saved answers until the user changes something, so a background
  // refresh cannot overwrite a survey that is halfway through being filled in.
  const values = draft ?? saved;

  const changed = Object.keys(values).filter(
    (id) => values[id] !== saved[id]
  );

  if (!survey) {
    return (
      <section className="card">
        <h2>Rating Survey</h2>
        <p className="empty-note">Loading…</p>
      </section>
    );
  }

  const answered = Object.values(values).filter(
    (value) => value !== null && value !== undefined
  ).length;

  return (
    <section className="card">
      <div className="section-header">
        <div>
          <h2>Rating Survey</h2>
          <span>
            {answered} of {survey.players.length} rated · answers stay private
          </span>
        </div>

        <button
          className="primary-button"
          disabled={busy || changed.length === 0}
          onClick={async () => {
            await onSave(
              changed.map((membership_id) => ({
                membership_id,
                rating: values[membership_id],
              }))
            );

            setDraft(null);
          }}
        >
          {changed.length === 0 ? "Saved" : `Save ${changed.length}`}
        </button>
      </div>

      {survey.players.length === 0 && (
        <p className="empty-note">
          There is nobody else in the group to rate yet.
        </p>
      )}

      <div className="survey-list">
        {survey.players.map((player) => (
          <div className="survey-row" key={player.membership_id}>
            <span className="survey-name">
              {player.name}
              {player.is_virtual && <span className="tag">virtual</span>}
            </span>

            <StarRating
              label={player.name}
              value={values[player.membership_id] ?? null}
              onChange={(rating) =>
                setDraft({ ...values, [player.membership_id]: rating })
              }
            />
          </div>
        ))}
      </div>
    </section>
  );
}
