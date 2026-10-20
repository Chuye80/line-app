export type GamePane = "registration" | "teams" | "matches";

export type FlowActionId =
  | "createGameDay"
  | "register"
  | "openRegistration"
  | "generateTeams"
  | "reviewTeams"
  | "startGameDay"
  | "openMatches"
  | "finishGameDay"
  | "voteMvp"
  | "viewResults";

export type FlowBar = "preparing" | "teamsReady" | "live" | "finished";

export type FlowStage =
  | "schedule"
  | "register"
  | "generateTeams"
  | "reviewTeams"
  | "matches"
  | "mvpVoting"
  | "results";

export type FlowDetail =
  | "create"
  | "waitSchedule"
  | "needPlayers"
  | "tooManyPlayers"
  | "waitGenerate"
  | "generate"
  | "review"
  | "start"
  | "waitStart"
  | "openMatches"
  | "liveMatches"
  | "registrationClosed"
  | "needTeams"
  | "vote"
  | "voted"
  | "notEligible"
  | "viewResults";

export type GameDayGuide = {
  bar: FlowBar;
  stage: FlowStage;
  detail: FlowDetail;
  spotsRemaining: number;
  actions: FlowActionId[];
};

export type GameDayGuideInput = {
  status: "upcoming" | "live" | "finished" | null;
  participantCount: number;
  registeredCount: number;
  teamCount: number;
  mvpOpen: boolean;
  viewerCanVote: boolean;
  hasVoted: boolean;
  isAdmin: boolean;
  selfNeedsRegistration: boolean;
  pane: GamePane;
};

export const guideActionLabel: Record<FlowActionId, string> = {
  createGameDay: "createGameDay",
  register: "register",
  openRegistration: "goToRegistration",
  generateTeams: "generateTeams",
  reviewTeams: "reviewTeamsAction",
  startGameDay: "startGameDay",
  openMatches: "openMatchesAction",
  finishGameDay: "finishGameDay",
  voteMvp: "voteMvp",
  viewResults: "viewResultsAction",
};

const barLabel: Record<FlowBar, string> = {
  preparing: "flowPreparing",
  teamsReady: "flowTeamsReady",
  live: "flowLive",
  finished: "flowFinished",
};

const stageLabel: Record<FlowStage, string> = {
  schedule: "flowStageSchedule",
  register: "flowStageRegister",
  generateTeams: "flowStageGenerate",
  reviewTeams: "flowStageReview",
  matches: "flowStageMatches",
  mvpVoting: "flowStageVote",
  results: "flowStageResults",
};

const detailLabel: Record<FlowDetail, string> = {
  create: "flowDetailCreate",
  waitSchedule: "flowDetailWaitSchedule",
  needPlayers: "flowDetailNeedPlayers",
  tooManyPlayers: "flowDetailTooManyPlayers",
  waitGenerate: "flowDetailWaitGenerate",
  generate: "flowDetailGenerate",
  review: "flowDetailReview",
  start: "flowDetailStart",
  waitStart: "flowDetailWaitStart",
  openMatches: "flowDetailOpenMatches",
  liveMatches: "flowDetailLiveMatches",
  registrationClosed: "flowDetailRegistrationClosed",
  needTeams: "flowDetailNeedTeams",
  vote: "flowDetailVote",
  voted: "flowDetailVoted",
  notEligible: "flowDetailNotEligible",
  viewResults: "flowDetailViewResults",
};

export function guideBarLabel(bar: FlowBar) {
  return barLabel[bar];
}

export function guideStageLabel(stage: FlowStage) {
  return stageLabel[stage];
}

export function guideDetailLabel(detail: FlowDetail) {
  return detailLabel[detail];
}

export function shouldRemindMvpVote(input: {
  mvpOpen: boolean;
  viewerCanVote: boolean;
  hasVoted: boolean;
}) {
  return input.mvpOpen && input.viewerCanVote && !input.hasVoted;
}

export function mvpCandidates<
  T extends { id: string; is_virtual: boolean; is_guest: boolean },
>(participants: T[], selfId: string | null) {
  return participants.filter(
    (player) => !player.is_virtual && !player.is_guest && player.id !== selfId
  );
}

export function viewerCanVoteForMvp(input: {
  mvpOpen: boolean;
  viewerIsVirtual: boolean;
  viewerIsParticipant: boolean;
}) {
  return input.mvpOpen && !input.viewerIsVirtual && input.viewerIsParticipant;
}

function guide(
  bar: FlowBar,
  stage: FlowStage,
  detail: FlowDetail,
  spotsRemaining: number,
  actions: FlowActionId[]
): GameDayGuide {
  return { bar, stage, detail, spotsRemaining, actions };
}

export function gameDayGuide(input: GameDayGuideInput): GameDayGuide {
  const spotsRemaining = Math.max(0, input.participantCount - input.registeredCount);
  const registrationReady =
    input.participantCount > 0 &&
    input.registeredCount === input.participantCount;
  const teamsReady = input.teamCount > 0;

  if (input.status === "finished") {
    if (input.mvpOpen && input.viewerCanVote) {
      return guide(
        "finished",
        "mvpVoting",
        input.hasVoted ? "voted" : "vote",
        0,
        ["voteMvp"]
      );
    }
    if (input.mvpOpen) {
      return guide("finished", "mvpVoting", "notEligible", 0, []);
    }
    return guide("finished", "results", "viewResults", 0, ["viewResults"]);
  }

  if (input.status === null) {
    return guide(
      "preparing",
      "schedule",
      input.isAdmin ? "create" : "waitSchedule",
      0,
      input.isAdmin && input.pane !== "registration" ? ["createGameDay"] : []
    );
  }

  if (input.status === "live") {
    const finish: FlowActionId[] = input.isAdmin ? ["finishGameDay"] : [];
    if (!registrationReady) {
      return guide(
        "live",
        "matches",
        "registrationClosed",
        spotsRemaining,
        finish
      );
    }
    if (!teamsReady) {
      const next: FlowActionId[] = [];
      if (input.isAdmin && input.pane !== "teams") next.push("generateTeams");
      return guide(
        "live",
        "matches",
        input.isAdmin ? "needTeams" : "waitGenerate",
        0,
        [...next, ...finish]
      );
    }
    if (input.pane !== "matches") {
      return guide("live", "matches", "openMatches", 0, [
        "openMatches",
        ...finish,
      ]);
    }
    return guide("live", "matches", "liveMatches", 0, finish);
  }

  if (!registrationReady) {
    const actions: FlowActionId[] = [];
    if (input.pane !== "registration") {
      actions.push(
        input.selfNeedsRegistration && spotsRemaining > 0
          ? "register"
          : "openRegistration"
      );
    }
    return guide(
      "preparing",
      "register",
      input.registeredCount > input.participantCount
        ? "tooManyPlayers"
        : "needPlayers",
      input.registeredCount > input.participantCount
        ? input.registeredCount - input.participantCount
        : spotsRemaining,
      actions
    );
  }

  if (!teamsReady) {
    return guide(
      "preparing",
      "generateTeams",
      input.isAdmin ? "generate" : "waitGenerate",
      0,
      input.isAdmin && input.pane !== "teams" ? ["generateTeams"] : []
    );
  }

  const start: FlowActionId[] = input.isAdmin ? ["startGameDay"] : [];
  if (input.pane !== "teams") {
    return guide("teamsReady", "reviewTeams", "review", 0, [
      "reviewTeams",
      ...start,
    ]);
  }
  return guide(
    "teamsReady",
    "reviewTeams",
    input.isAdmin ? "start" : "waitStart",
    0,
    start
  );
}
