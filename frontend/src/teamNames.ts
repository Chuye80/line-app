// User-facing team names. Internal identifiers ("Team A", "Team B", ...) stay
// the keys everywhere; these helpers only decide what is shown for them.

export type TeamCaptainNames = Record<string, string> | null | undefined;

export function teamLetter(teamName: string): string {
  const match = /^Team ([A-Z])$/.exec(teamName);
  return match ? match[1] : teamName;
}

/**
 * Maps internal team names to captain-based display names using a template
 * such as "{name}'s Team". Teams without a captain are omitted, so callers fall
 * back to the internal name. Identical results are disambiguated with the
 * internal team letter, e.g. "Daniel's Team (A)" and "Daniel's Team (B)".
 */
export function teamDisplayNames(
  captainNames: TeamCaptainNames,
  template: string
): Record<string, string> {
  const labels = Object.entries(captainNames ?? {})
    .filter(([, name]) => typeof name === "string" && name.trim() !== "")
    .map(
      ([team, name]) =>
        [team, template.replace("{name}", () => name.trim())] as const
    );
  const counts = new Map<string, number>();
  for (const [, label] of labels) {
    const key = label.toLocaleLowerCase();
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Object.fromEntries(
    labels.map(([team, label]) => [
      team,
      (counts.get(label.toLocaleLowerCase()) ?? 0) > 1
        ? `${label} (${teamLetter(team)})`
        : label,
    ])
  );
}

export function teamLabel(
  displayNames: Record<string, string>,
  teamName: string
): string {
  return displayNames[teamName] ?? teamName;
}

/** Co-champions are stored as "Team A / Team B". */
export function championLabel(
  displayNames: Record<string, string>,
  championTeamName: string
): string {
  return championTeamName
    .split(" / ")
    .map((teamName) => teamLabel(displayNames, teamName))
    .join(" / ");
}
