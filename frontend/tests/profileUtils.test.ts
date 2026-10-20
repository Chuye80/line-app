import assert from "node:assert/strict";
import test from "node:test";

import { avatarInitials, matchesMemberSearch } from "../src/profileUtils.ts";

test("registered avatar initials prefer first and last name", () => {
  assert.equal(
    avatarInitials({
      name: "Shushu",
      first_name: "Shai",
      last_name: "Cohen",
    }),
    "SC"
  );
});

test("legacy and virtual names produce stable fallback initials", () => {
  assert.equal(avatarInitials({ name: "Daniel" }), "D");
  assert.equal(avatarInitials({ name: "Noa Levi" }), "NL");
  assert.equal(avatarInitials({ name: "" }), "?");
});

test("member search matches first name, last name, nickname, and display name", () => {
  const player = {
    name: "Shushu",
    full_name: "Shai Cohen",
    first_name: "Shai",
    last_name: "Cohen",
    nickname: "Shushu",
  };
  for (const query of ["shai", "COHEN", "shush", ""]) {
    assert.equal(matchesMemberSearch(player, query), true);
  }
  assert.equal(matchesMemberSearch(player, "Daniel"), false);
});
