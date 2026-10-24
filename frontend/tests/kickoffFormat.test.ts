import assert from "node:assert/strict";
import test from "node:test";
import { formatKickoff } from "../src/kickoffFormat.ts";

test("kickoff times are concise in English and Hebrew", () => {
  const iso = "2026-10-21T17:30:00";
  const en = formatKickoff(iso, "en");
  const he = formatKickoff(iso, "he");

  assert.equal(en.date.length > 0, true);
  assert.equal(en.time.length > 0, true);
  assert.equal(he.date.length > 0, true);
  assert.equal(he.time.length > 0, true);
  assert.notEqual(he.date, en.date);
  assert.doesNotMatch(en.date, /\d{4}/);
  assert.doesNotMatch(en.date, /\d{1,2}\/\d{1,2}\/\d{2,4}/);
  assert.doesNotMatch(en.time, /\d:\d{2}:\d{2}/);
  assert.doesNotMatch(he.time, /\d:\d{2}:\d{2}/);
});

test("a kickoff in another calendar year includes that year", () => {
  const year = new Date().getFullYear() + 1;
  const en = formatKickoff(`${year}-03-15T18:00:00`, "en");
  assert.match(en.date, new RegExp(String(year)));
  assert.doesNotMatch(en.time, /\d:\d{2}:\d{2}/);
});
