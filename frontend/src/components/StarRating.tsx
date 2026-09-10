const STARS = [1, 2, 3, 4, 5];

/**
 * A 1.0 to 5.0 rating in half-star steps.
 *
 * Each star is two hit areas, so the nine values on the scale are all reachable
 * in one tap, and the chosen number is always spelled out next to the stars
 * because "four and a half stars" is hard to read off a row of glyphs.
 */
export function StarRating({
  value,
  onChange,
  label,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  label: string;
}) {
  return (
    <div className="star-rating">
      <div className="stars" role="group" aria-label={`Rating for ${label}`}>
        {STARS.map((star) => {
          const fill = Math.max(0, Math.min(1, (value ?? 0) - (star - 1)));

          return (
            <span className="star" key={star}>
              <span className="star-glyph" aria-hidden="true">
                <span className="star-empty">★</span>
                <span className="star-fill" style={{ width: `${fill * 100}%` }}>
                  ★
                </span>
              </span>

              <button
                type="button"
                className="star-half left"
                aria-label={`Rate ${label} ${star - 0.5} out of 5`}
                aria-pressed={value === star - 0.5}
                onClick={() => onChange(star - 0.5)}
              />
              <button
                type="button"
                className="star-half right"
                aria-label={`Rate ${label} ${star} out of 5`}
                aria-pressed={value === star}
                onClick={() => onChange(star)}
              />
            </span>
          );
        })}
      </div>

      <span className={value === null ? "star-value muted" : "star-value"}>
        {value === null ? "Not rated" : value.toFixed(1)}
      </span>

      {value !== null && (
        <button
          type="button"
          className="text-button"
          onClick={() => onChange(null)}
        >
          Clear
        </button>
      )}
    </div>
  );
}
