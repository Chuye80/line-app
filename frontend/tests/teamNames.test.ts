import assert from "node:assert/strict";
import { test } from "node:test";

import {
  championLabel,
  teamDisplayNames,
  teamLabel,
  teamLetter,
} from "../src/teamNames.ts";

const EN = "{name}'s Team";
const HE = "הקבוצה של {name}";

test("captain-based names in English and Hebrew", () => {
  const captains = { "Team A": "Shai", "Team B": "Daniel" };
  assert.deepEqual(teamDisplayNames(captains, EN), {
    "Team A": "Shai's Team",
    "Team B": "Daniel's Team",
  });
  assert.deepEqual(teamDisplayNames({ "Team A": "שי", "Team B": "דניאל" }, HE), {
    "Team A": "הקבוצה של שי",
    "Team B": "הקבוצה של דניאל",
  });
});

test("a match reads with both captains' team names", () => {
  const names = teamDisplayNames({ "Team A": "Shai", "Team B": "Daniel" }, EN);
  assert.equal(
    `${teamLabel(names, "Team A")} vs ${teamLabel(names, "Team B")}`,
    "Shai's Team vs Daniel's Team"
  );
});

test("teams without a captain keep the internal fallback", () => {
  const names = teamDisplayNames({ "Team A": "Shai" }, EN);
  assert.equal(teamLabel(names, "Team A"), "Shai's Team");
  assert.equal(teamLabel(names, "Team B"), "Team B");
  assert.equal(teamLabel(teamDisplayNames(undefined, EN), "Team C"), "Team C");
  assert.equal(teamLabel(teamDisplayNames(null, HE), "Team C"), "Team C");
  assert.equal(teamLabel(teamDisplayNames({ "Team A": "  " }, EN), "Team A"), "Team A");
});

test("identical names are disambiguated with the team letter only when needed", () => {
  assert.deepEqual(
    teamDisplayNames(
      { "Team A": "Daniel", "Team B": "Daniel", "Team C": "Noa" },
      EN
    ),
    {
      "Team A": "Daniel's Team (A)",
      "Team B": "Daniel's Team (B)",
      "Team C": "Noa's Team",
    }
  );
  assert.deepEqual(
    teamDisplayNames({ "Team A": "Daniel", "Team B": "daniel " }, HE),
    {
      "Team A": "הקבוצה של Daniel (A)",
      "Team B": "הקבוצה של daniel (B)",
    }
  );
});

test("names are inserted literally, even with replacement patterns", () => {
  const names = teamDisplayNames({ "Team A": "$& $1 Bob" }, EN);
  assert.equal(names["Team A"], "$& $1 Bob's Team");
});

test("co-champions map each internal team", () => {
  const names = teamDisplayNames({ "Team A": "Shai" }, EN);
  assert.equal(championLabel(names, "Team A"), "Shai's Team");
  assert.equal(championLabel(names, "Team A / Team B"), "Shai's Team / Team B");
});

test("team letters come from the internal identifier", () => {
  assert.equal(teamLetter("Team A"), "A");
  assert.equal(teamLetter("Team Z"), "Z");
  assert.equal(teamLetter("Unknown"), "Unknown");
});
