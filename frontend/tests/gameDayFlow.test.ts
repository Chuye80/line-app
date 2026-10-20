import assert from "node:assert/strict";
import test from "node:test";

import {
  gameDayGuide,
  guideActionLabel,
  guideBarLabel,
  guideDetailLabel,
  guideStageLabel,
  mvpCandidates,
  shouldRemindMvpVote,
  viewerCanVoteForMvp,
  type FlowBar,
  type FlowDetail,
  type FlowStage,
  type GameDayGuideInput,
} from "../src/gameDayFlow.ts";
import { translations } from "../src/i18n.ts";

function input(overrides: Partial<GameDayGuideInput> = {}): GameDayGuideInput {
  return {
    status: "upcoming",
    participantCount: 10,
    registeredCount: 4,
    teamCount: 0,
    mvpOpen: false,
    viewerCanVote: false,
    hasVoted: false,
    isAdmin: false,
    selfNeedsRegistration: true,
    pane: "registration",
    ...overrides,
  };
}

test("registration stage explains the missing players and does not offer generate or start", () => {
  const member = gameDayGuide(input());
  assert.equal(member.bar, "preparing");
  assert.equal(member.stage, "register");
  assert.equal(member.detail, "needPlayers");
  assert.equal(member.spotsRemaining, 6);
  assert.deepEqual(member.actions, []);

  const memberOnTeams = gameDayGuide(input({ pane: "teams" }));
  assert.deepEqual(memberOnTeams.actions, ["register"]);

  const admin = gameDayGuide(
    input({ isAdmin: true, selfNeedsRegistration: false, pane: "matches" })
  );
  assert.deepEqual(admin.actions, ["openRegistration"]);
  assert.equal(admin.actions.includes("generateTeams"), false);
  assert.equal(admin.actions.includes("startGameDay"), false);
});

test("teams can be generated only when registration matches the configured count", () => {
  const admin = gameDayGuide(
    input({
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      pane: "registration",
    })
  );
  assert.equal(admin.stage, "generateTeams");
  assert.equal(admin.detail, "generate");
  assert.deepEqual(admin.actions, ["generateTeams"]);

  const alreadyThere = gameDayGuide(
    input({
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      pane: "teams",
    })
  );
  assert.deepEqual(alreadyThere.actions, []);

  const member = gameDayGuide(
    input({ registeredCount: 10, selfNeedsRegistration: false })
  );
  assert.equal(member.detail, "waitGenerate");
  assert.deepEqual(member.actions, []);
});

test("teams ready offers review, and only admins can start", () => {
  const admin = gameDayGuide(
    input({
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      teamCount: 2,
      pane: "registration",
    })
  );
  assert.equal(admin.bar, "teamsReady");
  assert.equal(admin.stage, "reviewTeams");
  assert.deepEqual(admin.actions, ["reviewTeams", "startGameDay"]);

  const adminOnTeams = gameDayGuide(
    input({
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      teamCount: 2,
      pane: "teams",
    })
  );
  assert.deepEqual(adminOnTeams.actions, ["startGameDay"]);

  const member = gameDayGuide(
    input({
      selfNeedsRegistration: false,
      registeredCount: 10,
      teamCount: 2,
      pane: "teams",
    })
  );
  assert.equal(member.detail, "waitStart");
  assert.deepEqual(member.actions, []);
});

test("live status keeps end available to admins on every tab and opens matches", () => {
  const admin = gameDayGuide(
    input({
      status: "live",
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      teamCount: 2,
      pane: "registration",
    })
  );
  assert.equal(admin.bar, "live");
  assert.deepEqual(admin.actions, ["openMatches", "finishGameDay"]);

  const adminOnMatches = gameDayGuide(
    input({
      status: "live",
      isAdmin: true,
      selfNeedsRegistration: false,
      registeredCount: 10,
      teamCount: 2,
      pane: "matches",
    })
  );
  assert.deepEqual(adminOnMatches.actions, ["finishGameDay"]);

  const member = gameDayGuide(
    input({
      status: "live",
      registeredCount: 10,
      teamCount: 2,
      pane: "teams",
    })
  );
  assert.deepEqual(member.actions, ["openMatches"]);
  assert.equal(member.actions.includes("finishGameDay"), false);
});

test("finishing does not wait for MVP votes, and voting stays closed until the day is finished", () => {
  const live = gameDayGuide(
    input({
      status: "live",
      isAdmin: true,
      registeredCount: 10,
      teamCount: 2,
      pane: "matches",
      viewerCanVote: true,
      mvpOpen: false,
    })
  );
  assert.deepEqual(live.actions, ["finishGameDay"]);
  assert.equal(live.actions.includes("voteMvp"), false);

  const upcoming = gameDayGuide(
    input({
      isAdmin: true,
      registeredCount: 10,
      teamCount: 2,
      viewerCanVote: true,
      mvpOpen: true,
    })
  );
  assert.equal(upcoming.actions.includes("voteMvp"), false);
});

test("finished days offer MVP voting only to eligible players, then results", () => {
  const eligible = gameDayGuide(
    input({
      status: "finished",
      mvpOpen: true,
      viewerCanVote: true,
      pane: "matches",
    })
  );
  assert.equal(eligible.bar, "finished");
  assert.equal(eligible.stage, "mvpVoting");
  assert.equal(eligible.detail, "vote");
  assert.deepEqual(eligible.actions, ["voteMvp"]);

  const voted = gameDayGuide(
    input({
      status: "finished",
      mvpOpen: true,
      viewerCanVote: true,
      hasVoted: true,
    })
  );
  assert.equal(voted.detail, "voted");
  assert.deepEqual(voted.actions, ["voteMvp"]);

  const spectator = gameDayGuide(
    input({ status: "finished", mvpOpen: true, viewerCanVote: false })
  );
  assert.equal(spectator.detail, "notEligible");
  assert.deepEqual(spectator.actions, []);

  const announced = gameDayGuide(
    input({ status: "finished", mvpOpen: false, viewerCanVote: true })
  );
  assert.equal(announced.stage, "results");
  assert.deepEqual(announced.actions, ["viewResults"]);
});

test("home reminder is only for eligible players who have not voted while voting is open", () => {
  assert.equal(
    shouldRemindMvpVote({ mvpOpen: true, viewerCanVote: true, hasVoted: false }),
    true
  );
  assert.equal(
    shouldRemindMvpVote({ mvpOpen: true, viewerCanVote: true, hasVoted: true }),
    false
  );
  assert.equal(
    shouldRemindMvpVote({ mvpOpen: true, viewerCanVote: false, hasVoted: false }),
    false
  );
  assert.equal(
    shouldRemindMvpVote({ mvpOpen: false, viewerCanVote: true, hasVoted: false }),
    false
  );
});

test("MVP candidates exclude the voter, guests, and virtual players", () => {
  const players = [
    { id: "me", is_virtual: false, is_guest: false },
    { id: "real", is_virtual: false, is_guest: false },
    { id: "guest", is_virtual: false, is_guest: true },
    { id: "virtual", is_virtual: true, is_guest: false },
  ];
  assert.deepEqual(
    mvpCandidates(players, "me").map((player) => player.id),
    ["real"]
  );
  assert.equal(
    viewerCanVoteForMvp({
      mvpOpen: true,
      viewerIsVirtual: false,
      viewerIsParticipant: true,
    }),
    true
  );
  assert.equal(
    viewerCanVoteForMvp({
      mvpOpen: false,
      viewerIsVirtual: false,
      viewerIsParticipant: true,
    }),
    false
  );
  assert.equal(
    viewerCanVoteForMvp({
      mvpOpen: true,
      viewerIsVirtual: true,
      viewerIsParticipant: true,
    }),
    false
  );
});

test("guide copy exists in English and Hebrew", () => {
  const bars: FlowBar[] = ["preparing", "teamsReady", "live", "finished"];
  const stages: FlowStage[] = [
    "schedule",
    "register",
    "generateTeams",
    "reviewTeams",
    "matches",
    "mvpVoting",
    "results",
  ];
  const details: FlowDetail[] = [
    "create",
    "waitSchedule",
    "needPlayers",
    "tooManyPlayers",
    "waitGenerate",
    "generate",
    "review",
    "start",
    "waitStart",
    "openMatches",
    "liveMatches",
    "registrationClosed",
    "needTeams",
    "vote",
    "voted",
    "notEligible",
    "viewResults",
  ];
  const keys = [
    ...bars.map((bar) => guideBarLabel(bar)),
    ...stages.map((stage) => guideStageLabel(stage)),
    ...details.map((detail) => guideDetailLabel(detail)),
    ...Object.values(guideActionLabel),
    "finishGameDayConfirm",
    "mvpReminder",
    "noMvpCandidates",
    "updateVote",
  ];
  for (const key of keys) {
    assert.equal(typeof translations.en[key], "string", key);
    assert.equal(typeof translations.he[key], "string", key);
  }
});

test("a live day with incomplete registration does not pretend registration is still open", () => {
  const guide = gameDayGuide(
    input({
      status: "live",
      isAdmin: true,
      registeredCount: 4,
      pane: "registration",
    })
  );
  assert.equal(guide.detail, "registrationClosed");
  assert.deepEqual(guide.actions, ["finishGameDay"]);
});
