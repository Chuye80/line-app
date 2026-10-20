export type AwardedPlayer = {
  id: string;
  user_id?: string | null;
};

/** A finished Game Day, as already returned on the group history payload. */
export type AwardedGameDay = {
  game_datetime: string;
  awards?: {
    champions?: AwardedPlayer[];
    mvps?: AwardedPlayer[];
  };
};

export type ReigningTitles = {
  championIds: ReadonlySet<string>;
  mvpIds: ReadonlySet<string>;
};

function completedAt(day: AwardedGameDay): number {
  const value = Date.parse(day.game_datetime);
  return Number.isNaN(value) ? Number.NEGATIVE_INFINITY : value;
}

function remember(target: Set<string>, player: AwardedPlayer) {
  if (player.id) target.add(player.id);
  if (player.user_id) target.add(player.user_id);
}

/**
 * Reigning champions are everyone who won the most recently completed Game Day.
 * A newer completed day replaces them, including a day with no champion.
 *
 * The reigning MVP is the latest finalized winner. MVP awards are written only
 * when voting is finalized, so a newer finished day with an empty MVP list
 * leaves the previous winner in place.
 */
export function reigningTitles(days: readonly AwardedGameDay[]): ReigningTitles {
  const ordered = [...days].sort(
    (left, right) => completedAt(right) - completedAt(left)
  );
  const championIds = new Set<string>();
  const mvpIds = new Set<string>();
  for (const player of ordered[0]?.awards?.champions ?? []) {
    remember(championIds, player);
  }
  const mvpDay = ordered.find((day) => (day.awards?.mvps?.length ?? 0) > 0);
  for (const player of mvpDay?.awards?.mvps ?? []) {
    remember(mvpIds, player);
  }
  return { championIds, mvpIds };
}

export function playerHasReigningTitle(
  titles: ReigningTitles,
  player: { id?: string | null; user_id?: string | null },
  kind: "champion" | "mvp"
): boolean {
  const ids = kind === "champion" ? titles.championIds : titles.mvpIds;
  return (
    (player.id != null && player.id !== "" && ids.has(player.id)) ||
    (player.user_id != null && player.user_id !== "" && ids.has(player.user_id))
  );
}
