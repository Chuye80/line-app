import assert from "node:assert/strict";
import test from "node:test";

import {
  playerHasReigningTitle,
  reigningTitles,
  type AwardedGameDay,
} from "../src/reigningTitles.ts";

function day(
  game_datetime: string,
  champions: { id: string; user_id?: string | null }[] = [],
  mvps: { id: string; user_id?: string | null }[] = []
): AwardedGameDay {
  return {
    game_datetime,
    awards: { champions, mvps },
  };
}

const older = "2026-09-01T18:00:00Z";
const newer = "2026-10-01T18:00:00Z";

test("reigning champions are the winners of the latest completed game day", () => {
  const titles = reigningTitles([
    day(older, [{ id: "old-champ", user_id: "user-old" }]),
    day(newer, [
      { id: "new-champ", user_id: "user-new" },
      { id: "co-champ", user_id: "user-co" },
    ]),
  ]);

  assert.equal(titles.championIds.has("new-champ"), true);
  assert.equal(titles.championIds.has("user-new"), true);
  assert.equal(titles.championIds.has("co-champ"), true);
  assert.equal(titles.championIds.has("old-champ"), false);
  assert.equal(titles.championIds.has("user-old"), false);
});

test("a newer completed day with no champion clears the previous champions", () => {
  const titles = reigningTitles([
    day(newer, [], [{ id: "still-mvp", user_id: "user-mvp" }]),
    day(older, [{ id: "old-champ", user_id: "user-old" }], [
      { id: "old-mvp", user_id: "user-old-mvp" },
    ]),
  ]);

  assert.equal(titles.championIds.size, 0);
  assert.equal(titles.mvpIds.has("still-mvp"), true);
  assert.equal(titles.mvpIds.has("old-mvp"), false);
});

test("the previous MVP keeps the crown until a newer winner is finalized", () => {
  const titles = reigningTitles([
    day(newer, [{ id: "new-champ", user_id: "user-champ" }], []),
    day(older, [{ id: "old-champ" }], [{ id: "reigning-mvp", user_id: "user-mvp" }]),
  ]);

  assert.equal(titles.championIds.has("new-champ"), true);
  assert.equal(titles.championIds.has("old-champ"), false);
  assert.equal(titles.mvpIds.has("reigning-mvp"), true);
  assert.equal(titles.mvpIds.has("user-mvp"), true);
  assert.equal(
    playerHasReigningTitle(titles, { id: "new-champ" }, "champion"),
    true
  );
  assert.equal(
    playerHasReigningTitle(titles, { id: "new-champ" }, "mvp"),
    false
  );
  assert.equal(
    playerHasReigningTitle(titles, { user_id: "user-mvp" }, "mvp"),
    true
  );
});

test("one player can be reigning champion and MVP at the same time", () => {
  const titles = reigningTitles([
    day(
      newer,
      [{ id: "ada", user_id: "user-ada" }],
      [{ id: "ada", user_id: "user-ada" }]
    ),
  ]);

  assert.equal(playerHasReigningTitle(titles, { id: "ada" }, "champion"), true);
  assert.equal(playerHasReigningTitle(titles, { id: "ada" }, "mvp"), true);
  assert.equal(
    playerHasReigningTitle(titles, { id: "user-ada" }, "mvp"),
    true
  );
});

test("co-MVPs from the latest finalized day all keep the crown", () => {
  const titles = reigningTitles([
    day(newer, [{ id: "champ" }]),
    day(older, [], [
      { id: "mvp-a", user_id: "user-a" },
      { id: "mvp-b", user_id: "user-b" },
    ]),
  ]);

  assert.equal(titles.mvpIds.has("mvp-a"), true);
  assert.equal(titles.mvpIds.has("mvp-b"), true);
  assert.equal(titles.mvpIds.has("champ"), false);
});

test("an empty history awards nobody", () => {
  const titles = reigningTitles([]);
  assert.equal(titles.championIds.size, 0);
  assert.equal(titles.mvpIds.size, 0);
  assert.equal(playerHasReigningTitle(titles, { id: "ada" }, "champion"), false);
});
