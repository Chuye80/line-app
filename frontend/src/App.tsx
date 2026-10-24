import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { Session } from "@supabase/supabase-js";
import "./App.css";
import { supabase, authCallback } from "./supabase";
import { recoveryFailureKey, passwordUpdateError } from "./authRecovery";
import { translations, type Language } from "./i18n";
import { championLabel, teamDisplayNames, teamLabel } from "./teamNames";
import { GroupPicture } from "./GroupPicture";
import { PlayerAvatar, ReigningTitlesProvider } from "./PlayerAvatar";
import { reigningTitles } from "./reigningTitles";
import { removeAvatar, uploadAvatar } from "./avatarStorage";
import { matchesMemberSearch } from "./profileUtils";
import {
  gameDayGuide,
  registrationGenerateCta,
  guideActionLabel,
  guideBarLabel,
  guideDetailLabel,
  guideStageLabel,
  mvpCandidates,
  shouldRemindMvpVote,
  viewerCanVoteForMvp,
} from "./gameDayFlow";

const API_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";
const DEV_TOOLS_ENABLED =
  import.meta.env.VITE_ENABLE_DEV_TOOLS === "true";
const LANG_KEY = "lineapp.lang";
const SELECTED_GROUP_KEY = "lineapp.selectedGroup";

function selectedGroupKey(userId: string) {
  return `${SELECTED_GROUP_KEY}.${userId}`;
}

function updateGroupUrl(groupId: string | null) {
  const url = new URL(window.location.href);
  if (groupId) {
    url.searchParams.set("group", groupId);
  } else {
    url.searchParams.delete("group");
  }
  window.history.replaceState(window.history.state, "", url);
}

type Member = {
  id: string;
  user_id: string | null;
  name: string;
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  nickname?: string | null;
  avatar_path?: string | null;
  avatar_version?: number;
  rating: number;
  goalkeeper_rating: number;
  is_subscriber: boolean;
  is_admin: boolean;
  is_virtual: boolean;
  is_guest: boolean;
  team_name?: string;
};

type Team = {
  /** Internal identifier ("Team A"); display via teamLabel. */
  name: string;
  captain_id?: string | null;
  players: Member[];
  total_rating: number;
  average_rating: number;
};

type MatchGoal = {
  id: string;
  team_name: string;
  scorer: Member | null;
  assist: Member | null;
};

type GoalDraft = {
  team: string;
  scorer: string;
  assist: string;
};

type LineupDraftItem = {
  membership_id: string;
  team_name: string;
};

function scoreFromGoalDrafts(
  goals: GoalDraft[],
  homeTeam: string,
  awayTeam: string
): { home: number; away: number } {
  let home = 0;
  let away = 0;
  for (const goal of goals) {
    if (goal.team === homeTeam) home += 1;
    else if (goal.team === awayTeam) away += 1;
  }
  return { home, away };
}

function goalDraftsFromMatch(goals: MatchGoal[]): GoalDraft[] {
  return goals.map((goal) => ({
    team: goal.team_name,
    scorer: goal.scorer?.id ?? "",
    assist: goal.assist?.id ?? "",
  }));
}

function buildCompleteGoalsPayload(goals: GoalDraft[]) {
  return goals
    .filter((goal) => goal.team)
    .map((goal) => ({
      team_name: goal.team,
      scorer_membership_id: goal.scorer || null,
      assist_membership_id: goal.assist || null,
    }));
}

function lineupDraftFromPlayers(players: Member[]): LineupDraftItem[] {
  return players.map((player) => ({
    membership_id: player.id,
    team_name: player.team_name ?? "",
  }));
}

function buildLineupPayload(draft: LineupDraftItem[]) {
  return draft
    .filter((item) => item.team_name)
    .map((item) => ({
      membership_id: item.membership_id,
      team_name: item.team_name,
    }));
}

function permanentTeamByMember(gameDay: GameDay): Record<string, string | null> {
  const map: Record<string, string | null> = {};
  for (const team of gameDay.teams) {
    for (const player of team.players) {
      map[player.id] = team.name;
    }
  }
  for (const player of gameDay.unassigned) {
    map[player.id] = null;
  }
  for (const player of gameDay.participants) {
    if (!(player.id in map)) {
      map[player.id] = null;
    }
  }
  return map;
}

function lineupPlayersForGoals(
  draft: LineupDraftItem[] | undefined,
  savedPlayers: Member[],
  participants: Member[]
): Member[] {
  if (draft) {
    const byId = new Map(participants.map((member) => [member.id, member]));
    return draft
      .filter((item) => item.team_name)
      .flatMap((item) => {
        const member = byId.get(item.membership_id);
        if (!member) return [];
        return [{ ...member, team_name: item.team_name }];
      });
  }
  return savedPlayers;
}

function lineupDraftIsDirty(
  draft: LineupDraftItem[] | undefined,
  savedPlayers: Member[]
): boolean {
  if (!draft) return false;
  const serialize = (items: LineupDraftItem[]) =>
    items
      .filter((item) => item.team_name)
      .map((item) => `${item.membership_id}:${item.team_name}`)
      .sort()
      .join("|");
  return serialize(draft) !== serialize(lineupDraftFromPlayers(savedPlayers));
}

function clearGoalDraftPlayerReferences(
  goals: GoalDraft[],
  membershipId: string,
  fromSide?: string
): GoalDraft[] {
  return goals.map((goal) => {
    if (fromSide && goal.team !== fromSide) return goal;
    return {
      ...goal,
      scorer: goal.scorer === membershipId ? "" : goal.scorer,
      assist: goal.assist === membershipId ? "" : goal.assist,
    };
  });
}

type MatchInfo = {
  id: string;
  home_team_name: string;
  away_team_name: string;
  home_score: number | null;
  away_score: number | null;
  status: string;
  players: Member[];
  goals: MatchGoal[];
};

type Standing = {
  name: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  points: number;
};

type GameDay = {
  id: string;
  game_datetime: string;
  regular_registration_opens: string;
  status: "upcoming" | "live" | "finished";
  participant_count: number;
  players_per_team: number;
  is_rotating: boolean;
  champion_team_name: string | null;
  /** Internal team name -> captain name (frozen once the day is finished). */
  team_captain_names?: Record<string, string>;
  mvp_open: boolean;
  mvp_announced: boolean;
  votes_cast: number;
  eligible_voters: number;
  my_vote: string | null;
  participants: Member[];
  waiting_list: Member[];
  teams: Team[];
  unassigned: Member[];
  complete_teams: number;
  leftover_players: number;
  matches: MatchInfo[];
  standings: Standing[];
  awards: { champions: Member[]; mvps: Member[] };
  warning?: string | null;
};

type Survey = {
  id: string;
  status: "open" | "closed";
  my_ratings: Record<string, SurveyRating>;
};

type SurveyRating = {
  rating: number;
  goalkeeper_rating: number;
};

type Group = {
  id: string;
  name: string;
  last_participant_count: number;
  last_players_per_team: number;
  members: Member[];
  game_day: GameDay | null;
  /** The last finished day, present only while no new day has been created. */
  finished_game_day: GameDay | null;
  history: {
    id: string;
    game_datetime: string;
    status: string;
    is_rotating: boolean;
    champion_team_name: string | null;
    awards: { champions: Member[]; mvps: Member[] };
  }[];
  survey: Survey | null;
  invite_code?: string;
  invite_link?: string;
  join_requests?: JoinRequest[];
  picture_path?: string | null;
  picture_version?: number;
};

type MyGroup = {
  id: string;
  name: string;
  membership_id: string;
  is_admin: boolean;
};

type MembershipStatus = {
  state: "none" | "pending" | "approved" | "declined" | "member";
  membership_id: string | null;
  is_admin: boolean;
};

type JoinRequest = {
  id: string;
  user_id: string;
  user_name: string;
  user_full_name?: string | null;
  avatar_path?: string | null;
  avatar_version?: number;
  status: string;
};

type GroupMessage = {
  id: string;
  sender_user_id: string;
  sender_name: string;
  sender_avatar_path?: string | null;
  sender_avatar_version?: number;
  message: string;
  created_at: string;
};

type UserProfile = {
  id: string;
  email: string | null;
  display_name: string;
  first_name: string | null;
  last_name: string | null;
  nickname: string | null;
  full_name: string;
  avatar_path: string | null;
  avatar_version: number;
  is_complete: boolean;
};

type StatRow = Member & {
  game_days_played: number;
  matches_played: number;
  championships: number;
  goals: number;
  assists: number;
  mvp_titles: number;
};

type StatisticsTableRow = {
  id: string;
  name: string;
  full_name?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  avatar_path?: string | null;
  avatar_version?: number;
  rating: number;
  goalkeeperRating: number;
  gameDays: number;
  matches: number;
  championships: number;
  goals: number;
  assists: number;
  mvps: number;
};

type StatisticsTableColumn = {
  key: string;
  label: string;
  value: (row: StatisticsTableRow) => string | number;
  display?: (row: StatisticsTableRow) => string | number;
};

const RATING_STEPS = [1, 2, 3, 4, 5];

function SortableStatisticsTable({
  rows,
  columns,
  emptyText,
}: {
  rows: StatisticsTableRow[];
  columns: StatisticsTableColumn[];
  emptyText: string;
}) {
  const [sort, setSort] = useState<{
    key: string;
    direction: "asc" | "desc";
  } | null>(null);

  if (rows.length === 0) {
    return <p className="muted-text">{emptyText}</p>;
  }

  const sortedRows = sort
    ? [...rows].sort((left, right) => {
        const column = columns.find((item) => item.key === sort.key);
        if (!column) return 0;
        const leftValue = column.value(left);
        const rightValue = column.value(right);
        const comparison =
          typeof leftValue === "number" && typeof rightValue === "number"
            ? leftValue - rightValue
            : String(leftValue).localeCompare(String(rightValue));
        return sort.direction === "asc" ? comparison : -comparison;
      })
    : rows;

  return (
    <div className="statistics-table-scroll">
      <table className="statistics-table">
        <thead>
          <tr>
            {columns.map((column) => {
              const direction =
                sort?.key === column.key ? sort.direction : null;
              return (
                <th
                  key={column.key}
                  aria-sort={
                    direction
                      ? direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    type="button"
                    onClick={() =>
                      setSort((current) => ({
                        key: column.key,
                        direction:
                          current?.key === column.key &&
                          current.direction === "asc"
                            ? "desc"
                            : "asc",
                      }))
                    }
                  >
                    {column.label}
                    <span className="sort-indicator" aria-hidden="true">
                      {direction ? (direction === "asc" ? "↑" : "↓") : ""}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr key={row.id}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.key === "name" ? (
                    <span className="player-identity">
                      <PlayerAvatar player={row} size="small" />
                      {row.name}
                    </span>
                  ) : column.display ? (
                    column.display(row)
                  ) : (
                    column.value(row)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StarRating({
  value,
  onChange,
  label,
}: {
  value: number;
  onChange: (value: number) => void;
  label: string;
}) {
  return (
    <div className="star-rating" role="group" aria-label={label}>
      {RATING_STEPS.map((star) => {
        const half = star - 0.5;
        const fill = value >= star ? "full" : value >= half ? "half" : "empty";
        return (
          <span className="star" key={star}>
            {star === 1 ? (
              <button
                type="button"
                className="star-hit whole"
                aria-label={`${label}: 1.0`}
                aria-pressed={value === 1}
                onClick={() => onChange(1)}
              />
            ) : (
              <button
                type="button"
                className="star-hit left"
                aria-label={`${label}: ${half.toFixed(1)}`}
                aria-pressed={value === half}
                onClick={() => onChange(half)}
              />
            )}
            {star !== 1 && (
              <button
                type="button"
                className="star-hit right"
                aria-label={`${label}: ${star.toFixed(1)}`}
                aria-pressed={value === star}
                onClick={() => onChange(star)}
              />
            )}
            <span className={`star-glyph ${fill}`} aria-hidden="true">
              ★
            </span>
          </span>
        );
      })}
      <span className="star-value">{value ? value.toFixed(1) : "—"}</span>
    </div>
  );
}

/** Where the simulated identity lives: per tab, and never in the auth session. */
const ACT_AS_KEY = "lineapp.viewAs";

function loadActAs(): string | null {
  return sessionStorage.getItem(ACT_AS_KEY);
}

function loadLang(): Language {
  const saved = localStorage.getItem(LANG_KEY);
  return saved === "he" ? "he" : "en";
}

function toLocalIso(date: string, time: string) {
  return new Date(`${date}T${time}`).toISOString();
}

type MainSection = "home" | "game" | "group" | "stats" | "settings";
type GamePane = "registration" | "teams" | "matches";
type GroupPane = "members" | "ratings" | "manage" | "chat";

function PasswordField({
  value,
  onChange,
  shown,
  onToggle,
  showLabel,
  hideLabel,
  autoComplete,
}: {
  value: string;
  onChange: (value: string) => void;
  shown: boolean;
  onToggle: () => void;
  showLabel: string;
  hideLabel: string;
  autoComplete: string;
}) {
  return (
    <div className="password-field">
      <input
        type={shown ? "text" : "password"}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        minLength={6}
        required
        autoComplete={autoComplete}
      />
      <button
        className="password-toggle"
        type="button"
        aria-label={shown ? hideLabel : showLabel}
        aria-pressed={shown}
        onClick={onToggle}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
          <circle cx="12" cy="12" r="3" />
          {shown && <path d="M4 4 20 20" />}
        </svg>
      </button>
    </div>
  );
}

function App() {
  const [lang, setLang] = useState<Language>(loadLang);
  const t = (key: string) => translations[lang][key] ?? key;

  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [isDeveloper, setIsDeveloper] = useState(false);
  // The whole of "view app as" is these two values plus one request header.
  // Everything downstream just reads the group payload the server sends back.
  const [actAs, setActAs] = useState<string | null>(loadActAs);
  const [simulatedName, setSimulatedName] = useState("");

  const [authMode, setAuthMode] = useState<"login" | "signup" | "forgot">("login");
  const [signupFirstName, setSignupFirstName] = useState("");
  const [signupLastName, setSignupLastName] = useState("");
  const [signupNickname, setSignupNickname] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [recoveryEmailSent, setRecoveryEmailSent] = useState(false);
  const [passwordRecovery, setPasswordRecovery] = useState(
    () => authCallback.recovery && !recoveryFailureKey(authCallback)
  );
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [section, setSection] = useState<MainSection>("home");
  const [gamePane, setGamePane] = useState<GamePane>("registration");
  const [groupPane, setGroupPane] = useState<GroupPane>("members");
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileFirstName, setProfileFirstName] = useState("");
  const [profileLastName, setProfileLastName] = useState("");
  const [profileNickname, setProfileNickname] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [memberSearch, setMemberSearch] = useState("");

  const [myGroups, setMyGroups] = useState<MyGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [group, setGroup] = useState<Group | null>(null);
  const [membership, setMembership] = useState<MembershipStatus | null>(null);
  const [joinRequests, setJoinRequests] = useState<JoinRequest[]>([]);
  const [invitePreview, setInvitePreview] = useState<{
    id: string;
    name: string;
    state: string;
  } | null>(null);
  const [inviteCode] = useState(
    new URLSearchParams(window.location.search).get("invite") ?? ""
  );
  const [stats, setStats] = useState<StatRow[]>([]);
  const [statsScope, setStatsScope] = useState<"day" | "overall">("overall");

  const [newGroupName, setNewGroupName] = useState("");
  const [groupMenuOpen, setGroupMenuOpen] = useState(false);
  const groupMenuRef = useRef<HTMLDivElement | null>(null);
  const [chatExpanded, setChatExpanded] = useState(true);
  const [chatMessages, setChatMessages] = useState<GroupMessage[]>([]);
  const [chatDraft, setChatDraft] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const [membersExpanded, setMembersExpanded] = useState(true);
  const [showMemberForm, setShowMemberForm] = useState(false);
  const [editingMember, setEditingMember] = useState<Member | null>(null);
  const [memberName, setMemberName] = useState("");
  const [memberRating, setMemberRating] = useState(3);
  const [memberGoalkeeperRating, setMemberGoalkeeperRating] = useState(3);
  const [memberSubscriber, setMemberSubscriber] = useState(false);
  const [memberAdmin, setMemberAdmin] = useState(false);
  const [showGuestForm, setShowGuestForm] = useState(false);
  const [editingGuest, setEditingGuest] = useState<Member | null>(null);
  const [guestName, setGuestName] = useState("");
  const [guestRating, setGuestRating] = useState(3);
  const [guestGoalkeeperRating, setGuestGoalkeeperRating] = useState(3);
  const [teamDraft, setTeamDraft] = useState<Record<string, string>>({});
  const [editingTeams, setEditingTeams] = useState(false);
  const [teamAdjustmentError, setTeamAdjustmentError] = useState("");

  const [gameDate, setGameDate] = useState("");
  const [gameTime, setGameTime] = useState("20:00");
  const [priorityHours, setPriorityHours] = useState(24);
  const [participantCount, setParticipantCount] = useState(12);
  const [playersPerTeam, setPlayersPerTeam] = useState(4);

  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [goalDrafts, setGoalDrafts] = useState<Record<string, GoalDraft[]>>({});
  const [lineupDrafts, setLineupDrafts] = useState<Record<string, LineupDraftItem[]>>({});
  const [editingMatches, setEditingMatches] = useState<Set<string>>(() => new Set());
  const [adjustingLineups, setAdjustingLineups] = useState<Set<string>>(() => new Set());
  const [mvpChoice, setMvpChoice] = useState("");
  const [mvpVoteOpen, setMvpVoteOpen] = useState(false);
  const [surveyDraft, setSurveyDraft] = useState<
    Record<string, Partial<SurveyRating>>
  >({});
  const [copied, setCopied] = useState(false);
  const [showGroupActions, setShowGroupActions] = useState(false);
  const [showExitOptions, setShowExitOptions] = useState(false);
  const [transferTarget, setTransferTarget] = useState("");
  const membershipStateRef = useRef<string | null>(null);
  const skipNextGroupLoad = useRef(false);
  const isAdminRef = useRef(false);
  const selectionOwnerRef = useRef<string | null>(null);
  const chatMessagesRef = useRef<HTMLDivElement | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(() => {
    const key = recoveryFailureKey(authCallback);
    return key ? translations[loadLang()][key] : "";
  });
  const [now, setNow] = useState(new Date());

  const isMember = membership?.state === "member";
  const isAdmin = Boolean(isMember && membership?.is_admin);
  isAdminRef.current = isAdmin;
  const leftover = participantCount % playersPerTeam;
  const completeTeams = Math.floor(participantCount / playersPerTeam);

  const currentMembership = useMemo(
    () =>
      group?.members.find((member) => member.id === membership?.membership_id) ??
      null,
    [group, membership?.membership_id]
  );
  const titles = useMemo(
    () => reigningTitles(group?.history ?? []),
    [group?.history]
  );
  const otherRealMembers =
    group?.members.filter(
      (member) =>
        !member.is_virtual && member.id !== currentMembership?.id
    ) ?? [];
  const otherRealAdmins = otherRealMembers.filter((member) => member.is_admin);
  const isSoleRealAdmin = Boolean(isAdmin && otherRealAdmins.length === 0);
  const sortedGroupMembers = useMemo(() => {
    const members = (group?.members ?? []).filter((member) =>
      matchesMemberSearch(member, memberSearch)
    );
    return [
      ...members.filter((member) => member.is_admin),
      ...members.filter(
        (member) =>
          !member.is_admin && !member.is_virtual && member.is_subscriber
      ),
      ...members.filter(
        (member) =>
          !member.is_admin && !member.is_virtual && !member.is_subscriber
      ),
      ...members.filter(
        (member) => !member.is_admin && member.is_virtual
      ),
    ];
  }, [group?.members, memberSearch]);
  const surveyEligibleMembers =
    group?.members.filter(
      (member) =>
        member.user_id !== null && member.id !== currentMembership?.id
    ) ?? [];
  const surveyRatingValue = (
    memberId: string,
    key: keyof SurveyRating
  ): number =>
    surveyDraft[memberId]?.[key] ??
    group?.survey?.my_ratings?.[memberId]?.[key] ??
    0;
  const completedSurveyRatings = Object.fromEntries(
    surveyEligibleMembers.flatMap((member) => {
      const rating = surveyRatingValue(member.id, "rating");
      const goalkeeperRating = surveyRatingValue(
        member.id,
        "goalkeeper_rating"
      );
      return rating && goalkeeperRating
        ? [
            [
              member.id,
              {
                rating,
                goalkeeper_rating: goalkeeperRating,
              },
            ],
          ]
        : [];
    })
  );

  // Statistics for the single day being played or just finished. These are
  // read straight off that day's matches rather than kept alongside the
  // career totals, so the two can never drift apart.
  const dayStats = useMemo(() => {
    const day = group?.game_day ?? group?.finished_game_day ?? null;
    if (!day) return [];
    const rows = new Map<
      string,
      { member: Member; played: number; goals: number; assists: number }
    >();
    const rowFor = (member: Member) => {
      const existing = rows.get(member.id);
      if (existing) return existing;
      const created = { member, played: 0, goals: 0, assists: 0 };
      rows.set(member.id, created);
      return created;
    };
    day.participants.forEach(rowFor);
    day.matches.forEach((match) => {
      if (match.status === "completed") {
        match.players.forEach((player) => {
          rowFor(player).played += 1;
        });
      }
      match.goals.forEach((goal) => {
        if (goal.scorer) rowFor(goal.scorer).goals += 1;
        if (goal.assist) rowFor(goal.assist).assists += 1;
      });
    });
    return [...rows.values()].sort(
      (a, b) =>
        b.goals - a.goals ||
        b.assists - a.assists ||
        b.played - a.played ||
        a.member.name.localeCompare(b.member.name)
    );
  }, [group?.game_day, group?.finished_game_day]);

  useEffect(() => {
    document.documentElement.lang = lang === "he" ? "he" : "en";
    document.documentElement.dir = lang === "he" ? "rtl" : "ltr";
    localStorage.setItem(LANG_KEY, lang);
  }, [lang]);

  async function apiFetch(path: string, options: RequestInit = {}) {
    const token = session?.access_token;
    if (!token) throw new Error("No active session");
    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);
    // The real bearer token always travels as-is; the simulation is a separate
    // hint the server is free to refuse.
    if (actAs) headers.set("X-Dev-Act-As", actAs);
    return fetch(`${API_URL}${path}`, { ...options, headers });
  }

  function viewAs(membershipId: string | null, name = "") {
    if (membershipId) {
      sessionStorage.setItem(ACT_AS_KEY, membershipId);
    } else {
      sessionStorage.removeItem(ACT_AS_KEY);
    }
    setActAs(membershipId);
    setSimulatedName(name);
  }

  function openSection(next: MainSection) {
    setSection(next);
    setEditingProfile(false);
    setProfileError("");
  }

  async function parseError(response: Response) {
    try {
      const data = await response.json();
      return data.detail ?? data.message ?? "Action failed";
    } catch {
      return "Action failed";
    }
  }

  function populateProfileForm(value: UserProfile | null) {
    setProfileFirstName(value?.first_name ?? value?.display_name ?? "");
    setProfileLastName(value?.last_name ?? "");
    setProfileNickname(value?.nickname ?? "");
  }

  async function loadProfile() {
    const response = await apiFetch("/profile");
    if (!response.ok) throw new Error(await parseError(response));
    const data = (await response.json()) as UserProfile;
    setProfile(data);
    populateProfileForm(data);
    return data;
  }

  function isGameDayPayload(data: unknown): data is GameDay {
    if (!data || typeof data !== "object") return false;
    const value = data as GameDay;
    return Array.isArray(value.participants) && Array.isArray(value.waiting_list);
  }

  function isGroupPayload(data: unknown): data is Group {
    if (!data || typeof data !== "object") return false;
    const value = data as Group;
    return Array.isArray(value.members) && "game_day" in value;
  }

  function applyGameDay(data: GameDay) {
    setGroup((current) => {
      if (!current) return current;
      if (data.status === "finished") {
        const awards = data.awards ?? { champions: [], mvps: [] };
        const champions = awards.champions.map((champion) => ({
          ...champion,
          team_name: data.teams.find((team) =>
            team.players.some((player) => player.id === champion.id)
          )?.name,
        }));
        const historyAwards = { ...awards, champions };
        // The day stops being the one being organised, but it is still the one
        // being celebrated and voted on, so it moves across rather than away.
        return {
          ...current,
          game_day: null,
          finished_game_day: data,
          history: [
            {
              id: data.id,
              game_datetime: data.game_datetime,
              status: data.status,
              is_rotating: data.is_rotating,
              champion_team_name: data.champion_team_name,
              awards: historyAwards,
            },
            ...current.history.filter((item) => item.id !== data.id),
          ],
        };
      }
      const previous = current.game_day;
      const merged: GameDay = previous
        ? {
            ...previous,
            ...data,
            matches: data.matches ?? previous.matches,
            standings: data.standings ?? previous.standings,
            awards: data.awards ?? previous.awards,
            my_vote: data.my_vote ?? previous.my_vote,
            votes_cast: data.votes_cast ?? previous.votes_cast,
            eligible_voters: data.eligible_voters ?? previous.eligible_voters,
          }
        : {
            ...data,
            matches: data.matches ?? [],
            standings: data.standings ?? [],
            awards: data.awards ?? { champions: [], mvps: [] },
            my_vote: data.my_vote ?? null,
            votes_cast: data.votes_cast ?? 0,
            eligible_voters: data.eligible_voters ?? 0,
            teams: data.teams ?? [],
            unassigned: data.unassigned ?? [],
          };
      return { ...current, game_day: merged };
    });
  }

  function applyActionPayload(data: unknown) {
    if (isGameDayPayload(data)) {
      applyGameDay(data);
      return;
    }
    if (isGroupPayload(data)) {
      setGroup(data);
      setParticipantCount(data.last_participant_count);
      setPlayersPerTeam(data.last_players_per_team);
      setMyGroups((current) => {
        if (current.some((item) => item.id === data.id)) return current;
        const mine = data.members.find((member) => member.user_id);
        return [
          ...current,
          {
            id: data.id,
            name: data.name,
            membership_id: mine?.id ?? "",
            is_admin: Boolean(mine?.is_admin),
          },
        ];
      });
      return;
    }
    if (data && typeof data === "object") {
      const value = data as {
        invite_code?: string;
        invite_link?: string;
        my_ratings?: Record<string, SurveyRating>;
        status?: string;
        id?: string;
        name?: string;
        is_virtual?: boolean;
      };
      if (value.invite_code && value.invite_link) {
        setGroup((current) =>
          current
            ? {
                ...current,
                invite_code: value.invite_code,
                invite_link: value.invite_link,
              }
            : current
        );
      }
      if (value.my_ratings && value.status && value.id) {
        setGroup((current) =>
          current ? { ...current, survey: value as Survey } : current
        );
      }
      if (
        value.id &&
        value.name &&
        typeof value.is_virtual === "boolean" &&
        !isGameDayPayload(data)
      ) {
        setGroup((current) => {
          if (!current) return current;
          const exists = current.members.some((member) => member.id === value.id);
          const member = value as Member;
          return {
            ...current,
            members: exists
              ? current.members.map((item) =>
                  item.id === member.id ? { ...item, ...member } : item
                )
              : [...current.members, member],
          };
        });
      }
    }
  }

  async function loadJoinRequests(groupId: string) {
    const pending = await apiFetch(`/groups/${groupId}/join-requests`);
    if (pending.ok) {
      setJoinRequests(await pending.json());
    } else {
      setJoinRequests([]);
    }
  }

  async function loadGroup(
    groupId: string,
    options: { joinRequests?: boolean } = {}
  ) {
    const response = await apiFetch(`/groups/${groupId}`);
    if (!response.ok) throw new Error(await parseError(response));
    const data: Group = await response.json();
    setGroup(data);
    if (Array.isArray(data.join_requests)) {
      setJoinRequests(data.join_requests);
    } else if (options.joinRequests) {
      await loadJoinRequests(groupId);
    }
    return data;
  }

  async function loadMembership(groupId: string) {
    const response = await apiFetch(`/groups/${groupId}/membership-status`);
    if (!response.ok) throw new Error(await parseError(response));
    const data: MembershipStatus = await response.json();
    setMembership(data);
    membershipStateRef.current = data.state;
    if (data.state !== "member") {
      setJoinRequests([]);
    }
    return data;
  }

  async function loadStats(groupId: string) {
    const response = await apiFetch(`/groups/${groupId}/statistics`);
    if (response.ok) setStats(await response.json());
  }

  async function loadGroupMessages(groupId: string) {
    const response = await apiFetch(`/groups/${groupId}/messages`);
    if (!response.ok) throw new Error(await parseError(response));
    return (await response.json()) as GroupMessage[];
  }

  async function loadInvite(code: string) {
    const response = await apiFetch(`/invite/${code}`);
    if (!response.ok) {
      setInvitePreview(null);
      return;
    }
    setInvitePreview(await response.json());
  }

  async function refreshData() {
    if (!session) return;
    const bootResponse = await apiFetch("/bootstrap");
    if (!bootResponse.ok) {
      // A simulation the server refuses must never lock us out of our own
      // account, so drop it and let the retry run as the real user.
      if (actAs) {
        sessionStorage.removeItem(ACT_AS_KEY);
        setActAs(null);
      }
      throw new Error(await parseError(bootResponse));
    }
    const boot = await bootResponse.json();
    setIsDeveloper(Boolean(boot.is_developer));
    if (boot.is_simulated) setSimulatedName(boot.display_name ?? "");
    const mine: MyGroup[] = boot.groups ?? [];
    setMyGroups(mine);
    if (inviteCode) await loadInvite(inviteCode);
    const userId = session.user.id;
    const savedGroupId = localStorage.getItem(selectedGroupKey(userId));
    const urlGroupId = new URLSearchParams(window.location.search).get("group");
    let target =
      mine.find((item) => item.id === urlGroupId)?.id ??
      (selectionOwnerRef.current === userId ? selectedGroupId : null);
    if (!target || !mine.some((item) => item.id === target)) {
      target =
        mine.find((item) => item.id === savedGroupId)?.id ??
        mine[0]?.id ??
        null;
    }
    if (target !== selectedGroupId) {
      skipNextGroupLoad.current = true;
      setSelectedGroupId(target);
    }
    selectionOwnerRef.current = userId;
    if (target) {
      localStorage.setItem(selectedGroupKey(userId), target);
    } else {
      localStorage.removeItem(selectedGroupKey(userId));
    }
    updateGroupUrl(target);
    if (target) {
      const known = mine.find((item) => item.id === target);
      if (known) {
        setMembership({
          state: "member",
          membership_id: known.membership_id,
          is_admin: known.is_admin,
        });
        membershipStateRef.current = "member";
        const data = await loadGroup(target, { joinRequests: known.is_admin });
        setParticipantCount(data.last_participant_count);
        setPlayersPerTeam(data.last_players_per_team);
      } else {
        const status = await loadMembership(target);
        if (status.state === "member") {
          const data = await loadGroup(target, {
            joinRequests: status.is_admin,
          });
          setParticipantCount(data.last_participant_count);
          setPlayersPerTeam(data.last_players_per_team);
        } else {
          setGroup(null);
          setStats([]);
        }
      }
    } else {
      setGroup(null);
      setMembership(null);
      setStats([]);
    }
  }

  async function runAction(
    action: () => Promise<Response>,
    mode: "auto" | "reload-group" | "reload-app" | "silent" = "auto"
  ) {
    if (mode !== "silent") setLoading(true);
    setError("");
    try {
      const response = await action();
      if (!response.ok) throw new Error(await parseError(response));
      const data = await response.json().catch(() => null);
      if (mode === "reload-app") {
        await refreshData();
        return data;
      }
      if (mode === "reload-group" && selectedGroupId) {
        await loadGroup(selectedGroupId, { joinRequests: isAdminRef.current });
        return data;
      }
      applyActionPayload(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    } finally {
      if (mode !== "silent") setLoading(false);
    }
  }

  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setAuthReady(true);
      if (authCallback.recovery && !data.session) {
        setPasswordRecovery(false);
        setError((current) => current || translations[loadLang()].recoveryLinkInvalid);
      }
      const hash = window.location.hash;
      if (
        hash.includes("access_token=") ||
        hash.includes("refresh_token=") ||
        hash.includes("error=") ||
        hash.includes("error_code=") ||
        hash.includes("type=recovery")
      ) {
        const url = new URL(window.location.href);
        url.hash = "";
        window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}`);
      }
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, newSession) => {
      if (event === "PASSWORD_RECOVERY") setPasswordRecovery(true);
      if (event === "SIGNED_OUT") setPasswordRecovery(false);
      setSession(newSession);
      setAuthReady(true);
    });
    return () => {
      active = false;
      subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!session) {
      setProfile(null);
      setSection("home");
      setEditingProfile(false);
      populateProfileForm(null);
      setProfileError("");
      return;
    }
    loadProfile().catch((err) =>
      setProfileError(
        err instanceof Error ? err.message : t("profileLoadFailed")
      )
    );
  }, [session?.user.id]);

  useEffect(() => {
    if (!session) {
      setMyGroups([]);
      setGroup(null);
      setMembership(null);
      setSelectedGroupId(null);
      selectionOwnerRef.current = null;
      return;
    }
    refreshData().catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load app")
    );
    // Switching the simulated identity reloads everything, which is why no
    // other component needs to know the simulation exists.
  }, [session, actAs]);

  useEffect(() => {
    if (
      !session ||
      !selectedGroupId ||
      selectionOwnerRef.current !== session.user.id
    ) {
      return;
    }
    localStorage.setItem(selectedGroupKey(session.user.id), selectedGroupId);
    updateGroupUrl(selectedGroupId);
  }, [session?.user.id, selectedGroupId]);

  useEffect(() => {
    setShowGroupActions(false);
    setShowExitOptions(false);
    setTransferTarget("");
  }, [selectedGroupId]);

  useEffect(() => {
    if (!session || !selectedGroupId) return;
    if (skipNextGroupLoad.current) {
      skipNextGroupLoad.current = false;
      return;
    }
    const known = myGroups.find((item) => item.id === selectedGroupId);
    if (known) {
      setMembership({
        state: "member",
        membership_id: known.membership_id,
        is_admin: known.is_admin,
      });
      membershipStateRef.current = "member";
      loadGroup(selectedGroupId, { joinRequests: known.is_admin })
        .then((data) => {
          setParticipantCount(data.last_participant_count);
          setPlayersPerTeam(data.last_players_per_team);
        })
        .catch((err) =>
          setError(err instanceof Error ? err.message : "Failed to load group")
        );
      return;
    }
    loadMembership(selectedGroupId)
      .then((status) => {
        if (status.state === "member") {
          return loadGroup(selectedGroupId, {
            joinRequests: status.is_admin,
          }).then((data) => {
            setParticipantCount(data.last_participant_count);
            setPlayersPerTeam(data.last_players_per_team);
            return data;
          });
        }
        setGroup(null);
        setJoinRequests([]);
        return null;
      })
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load group")
      );
  }, [selectedGroupId]);

  useEffect(() => {
    if (section !== "stats" || !selectedGroupId || membership?.state !== "member") {
      return;
    }
    loadStats(selectedGroupId).catch(() => {});
  }, [section, selectedGroupId, membership?.state]);

  useEffect(() => {
    setChatMessages([]);
    setChatDraft("");
    setChatError("");
    setChatExpanded(true);
    if (!session || !selectedGroupId || membership?.state !== "member") return;

    let cancelled = false;
    const refreshMessages = () => {
      loadGroupMessages(selectedGroupId)
        .then((messages) => {
          if (!cancelled) {
            setChatMessages((current) =>
              current.length === messages.length &&
              current.every(
                (item, index) =>
                  item.id === messages[index]?.id &&
                  item.sender_name === messages[index]?.sender_name
              )
                ? current
                : messages
            );
            setChatError("");
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setChatError(
              err instanceof Error ? err.message : t("chatLoadFailed")
            );
          }
        });
    };

    refreshMessages();
    const timer = window.setInterval(refreshMessages, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [session?.user.id, selectedGroupId, membership?.state, actAs]);

  useEffect(() => {
    if (!chatExpanded) return;
    const messageArea = chatMessagesRef.current;
    if (messageArea) messageArea.scrollTop = messageArea.scrollHeight;
  }, [chatMessages, chatExpanded]);

  useEffect(() => {
    const clock = window.setInterval(() => {
      setNow(new Date());
    }, 1000);
    return () => window.clearInterval(clock);
  }, []);

  useEffect(() => {
    if (!session) {
      return;
    }

    const membershipTimer = window.setInterval(() => {
    if (inviteCode) {
      loadInvite(inviteCode).catch(() => {});
    }
    if (!selectedGroupId || membershipStateRef.current === "member") {
      return;
    }
    loadMembership(selectedGroupId)
        .then((status) => {
          const previous = membershipStateRef.current;
          membershipStateRef.current = status.state;
          if (status.state !== "member") {
            setGroup(null);
            return null;
          }
          if (previous !== "member") {
            return loadGroup(selectedGroupId, {
              joinRequests: status.is_admin,
            });
          }
          return null;
        })
        .catch(() => {});
    }, 15000);

    const groupTimer = window.setInterval(() => {
      if (!selectedGroupId || membershipStateRef.current !== "member") {
        return;
      }
      loadGroup(selectedGroupId, { joinRequests: isAdminRef.current }).catch(
        () => {}
      );
    }, 30000);

    return () => {
      window.clearInterval(membershipTimer);
      window.clearInterval(groupTimer);
    };
  }, [session, selectedGroupId, inviteCode]);

  useEffect(() => {
    if (!group?.game_day) {
      setTeamDraft({});
      setEditingTeams(false);
      return;
    }
    if (editingTeams) return;
    const draft: Record<string, string> = {};
    group.game_day.teams.forEach((team) => {
      team.players.forEach((player) => {
        draft[player.id] = team.name;
      });
    });
    group.game_day.unassigned.forEach((player) => {
      draft[player.id] = "";
    });
    setTeamDraft(draft);
  }, [group?.game_day?.teams, group?.game_day?.unassigned, editingTeams]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [section, gamePane, groupPane]);

  useEffect(() => {
    if (!mvpVoteOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setMvpVoteOpen(false);
    }
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [mvpVoteOpen]);

  useEffect(() => {
    if (!groupMenuOpen) return;
    function closeOnOutsidePointer(event: PointerEvent) {
      if (!groupMenuRef.current?.contains(event.target as Node)) {
        setGroupMenuOpen(false);
      }
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setGroupMenuOpen(false);
    }
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [groupMenuOpen]);

  useEffect(() => {
    if (invitePreview?.state === "member") {
      setSelectedGroupId(invitePreview.id);
    }
  }, [invitePreview]);

  function returnToLogin() {
    setError("");
    setShowPassword(false);
    setRecoveryEmailSent(false);
    setAuthMode("login");
  }

  async function handlePasswordUpdate(event: FormEvent) {
    event.preventDefault();
    const validation = passwordUpdateError(password, confirmPassword);
    if (validation) {
      setError(t(validation));
      return;
    }
    setLoading(true);
    setError("");
    try {
      const { error: updateError } = await supabase.auth.updateUser({ password });
      if (updateError) throw updateError;
      setPassword("");
      setConfirmPassword("");
      setShowPassword(false);
      setPasswordRecovery(false);
    } catch (err) {
      setError(err instanceof Error && err.message ? err.message : t("passwordUpdateFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function handleAuth(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const normalizedEmail = email.trim();
      if (authMode === "forgot") {
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(
          normalizedEmail,
          { redirectTo: window.location.origin }
        );
        if (resetError) throw resetError;
        setRecoveryEmailSent(true);
        return;
      }
      if (authMode === "signup") {
        const firstName = signupFirstName.trim();
        const lastName = signupLastName.trim();
        if (!firstName || !lastName) {
          throw new Error(t("firstAndLastRequired"));
        }
        const { data, error: signUpError } = await supabase.auth.signUp({
          email: normalizedEmail,
          password,
          options: {
            emailRedirectTo: window.location.origin,
            data: {
              first_name: firstName,
              last_name: lastName,
              nickname: signupNickname.trim() || null,
              display_name: signupNickname.trim() || firstName,
            },
          },
        });
        if (signUpError) throw signUpError;
        if (!data.session) {
          if (!data.user || data.user.identities?.length === 0) {
            throw new Error(t("accountNotCreated"));
          }
          setError(t("confirmEmail"));
        }
        setAuthMode("login");
      } else {
        const { error: loginError } = await supabase.auth.signInWithPassword({
          email: normalizedEmail,
          password,
        });
        if (loginError) throw loginError;
      }
    } catch (err) {
      const authCode =
        err && typeof err === "object" && "code" in err
          ? String(err.code)
          : "";
      setError(
        authCode === "over_email_send_rate_limit"
          ? t(authMode === "forgot" ? "recoveryRateLimited" : "signupRateLimited")
          : err instanceof Error
            ? err.message
            : "Authentication failed"
      );
    } finally {
      setLoading(false);
    }
  }

  function selectGroup(groupId: string) {
    if (!session) return;
    localStorage.setItem(selectedGroupKey(session.user.id), groupId);
    updateGroupUrl(groupId);
    setSelectedGroupId(groupId);
    setGroupMenuOpen(false);
  }

  function setGameDayRegistration(memberId: string, join: boolean) {
    if (!group?.game_day) return;
    return runAction(
      () =>
        apiFetch(
          `/groups/${group.id}/game-days/${group.game_day!.id}/${
            join ? "register" : "unregister"
          }/${memberId}`,
          { method: "POST" }
        ),
      "silent"
    );
  }

  async function createGroup() {
    if (!newGroupName.trim()) return;
    const created = (await runAction(() =>
      apiFetch("/groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newGroupName.trim() }),
      })
    )) as Group | null;
    setNewGroupName("");
    if (created?.id) {
      skipNextGroupLoad.current = true;
      setSelectedGroupId(created.id);
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    const firstName = profileFirstName.trim();
    if (!firstName || profileSaving) return;
    setProfileSaving(true);
    setProfileError("");
    try {
      const response = await apiFetch("/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          first_name: firstName,
          last_name: profileLastName.trim() || null,
          nickname: profileNickname.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await parseError(response));
      const updated = (await response.json()) as UserProfile;
      setProfile(updated);
      populateProfileForm(updated);
      setEditingProfile(false);
      setChatMessages((current) =>
        current.map((message) =>
          message.sender_user_id === updated.id
            ? { ...message, sender_name: updated.display_name }
            : message
        )
      );
      refreshData().catch(() => {});
      if (group && section === "stats") loadStats(group.id).catch(() => {});
    } catch (err) {
      setProfileError(
        err instanceof Error ? err.message : t("profileSaveFailed")
      );
    } finally {
      setProfileSaving(false);
    }
  }

  async function saveAvatar(
    file: File,
    owner: UserProfile | Member,
    prefix: string,
    endpoint: string
  ) {
    setLoading(true);
    setError("");
    let newPath: string | null = null;
    try {
      newPath = await uploadAvatar(prefix, file);
      const response = await apiFetch(endpoint, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ avatar_path: newPath }),
      });
      if (!response.ok) throw new Error(await parseError(response));
      const updated = (await response.json()) as UserProfile | Member;
      if ("email" in updated) {
        setProfile(updated as UserProfile);
      } else if (group) {
        await loadGroup(group.id, { joinRequests: isAdminRef.current });
      }
      await removeAvatar(owner.avatar_path);
    } catch (err) {
      if (newPath) await removeAvatar(newPath);
      setError(err instanceof Error ? err.message : t("avatarUploadFailed"));
    } finally {
      setLoading(false);
    }
  }

  async function clearAvatar(
    owner: UserProfile | Member,
    endpoint: string
  ) {
    const response = await apiFetch(endpoint, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ avatar_path: null }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    const updated = (await response.json()) as UserProfile | Member;
    if ("email" in updated) setProfile(updated as UserProfile);
    else if (group) await loadGroup(group.id, { joinRequests: isAdminRef.current });
    await removeAvatar(owner.avatar_path);
  }

  async function persistGroupPicture(path: string | null) {
    if (!group) throw new Error(t("groupPictureUploadFailed"));
    const response = await apiFetch(`/groups/${group.id}/picture`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ picture_path: path }),
    });
    if (!response.ok) throw new Error(await parseError(response));
    const updated = (await response.json()) as Group;
    setGroup(updated);
    return updated;
  }

  async function saveGroupPicture(file: File) {
    if (!group) return;
    setLoading(true);
    setError("");
    let newPath: string | null = null;
    const previous = group.picture_path;
    try {
      newPath = await uploadAvatar(`groups/${group.id}/picture/`, file);
      await persistGroupPicture(newPath);
      await removeAvatar(previous);
    } catch (err) {
      if (newPath) await removeAvatar(newPath);
      setError(
        err instanceof Error ? err.message : t("groupPictureUploadFailed")
      );
    } finally {
      setLoading(false);
    }
  }

  async function clearGroupPicture() {
    if (!group?.picture_path) return;
    const previous = group.picture_path;
    setLoading(true);
    setError("");
    try {
      await persistGroupPicture(null);
      await removeAvatar(previous);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("groupPictureUploadFailed")
      );
      throw err;
    } finally {
      setLoading(false);
    }
  }

  async function sendGroupMessage(event: FormEvent) {
    event.preventDefault();
    const message = chatDraft.trim();
    if (!group || !message || chatSending) return;
    setChatSending(true);
    setChatError("");
    try {
      const response = await apiFetch(`/groups/${group.id}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      });
      if (!response.ok) throw new Error(await parseError(response));
      const created = (await response.json()) as GroupMessage;
      setChatMessages((current) =>
        current.some((item) => item.id === created.id)
          ? current
          : [...current, created]
      );
      setChatDraft("");
    } catch (err) {
      setChatError(
        err instanceof Error ? err.message : t("chatSendFailed")
      );
    } finally {
      setChatSending(false);
    }
  }

  function resetMemberForm() {
    setEditingMember(null);
    setMemberName("");
    setMemberRating(3);
    setMemberGoalkeeperRating(3);
    setMemberSubscriber(false);
    setMemberAdmin(false);
    setShowMemberForm(false);
  }

  function startEditMember(member: Member) {
    setEditingMember(member);
    setMemberName(member.name);
    setMemberRating(member.rating);
    setMemberGoalkeeperRating(member.goalkeeper_rating);
    setMemberSubscriber(member.is_subscriber);
    setMemberAdmin(member.is_admin);
    setShowMemberForm(true);
  }

  async function saveMember(event: FormEvent) {
    event.preventDefault();
    if (!group || !memberName.trim()) return;
    const body = JSON.stringify({
      name: memberName.trim(),
      rating: memberRating,
      goalkeeper_rating: memberGoalkeeperRating,
      is_subscriber: memberSubscriber,
      is_admin: memberAdmin,
    });
    if (editingMember) {
      await runAction(() =>
        apiFetch(`/groups/${group.id}/members/${editingMember.id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body,
        })
      );
    } else {
      await runAction(() =>
        apiFetch(`/groups/${group.id}/members`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        })
      );
    }
    resetMemberForm();
  }

  function resetGuestForm() {
    setEditingGuest(null);
    setGuestName("");
    setGuestRating(3);
    setGuestGoalkeeperRating(3);
    setShowGuestForm(false);
  }

  function startEditGuest(guest: Member) {
    setEditingGuest(guest);
    setGuestName(guest.name);
    setGuestRating(guest.rating);
    setGuestGoalkeeperRating(guest.goalkeeper_rating);
    setShowGuestForm(true);
  }

  async function saveGuest(event: FormEvent) {
    event.preventDefault();
    if (!group?.game_day || !guestName.trim()) return;
    const path = editingGuest
      ? `/groups/${group.id}/game-days/${group.game_day.id}/guests/${editingGuest.id}`
      : `/groups/${group.id}/game-days/${group.game_day.id}/guests`;
    await runAction(() =>
      apiFetch(path, {
        method: editingGuest ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: guestName.trim(),
          rating: guestRating,
          goalkeeper_rating: guestGoalkeeperRating,
        }),
      })
    );
    resetGuestForm();
  }

  async function removeGuest(guest: Member) {
    if (!group?.game_day || !window.confirm(t("removeGuestConfirm"))) return;
    if (guest.avatar_path) {
      await clearAvatar(
        guest,
        `/groups/${group.id}/members/${guest.id}/avatar`
      );
    }
    await runAction(() =>
      apiFetch(
        `/groups/${group.id}/game-days/${group.game_day!.id}/guests/${guest.id}`,
        { method: "DELETE" }
      )
    );
    if (editingGuest?.id === guest.id) resetGuestForm();
  }

  function playerName(player: Member) {
    return player.is_guest ? `${player.name} (${t("guest")})` : player.name;
  }

  function playerRatings(player: Member) {
    return `${t("playerRating")} ${player.rating} · ${t("goalkeeperRating")} ${
      player.goalkeeper_rating
    }`;
  }

  function standingsTable(rows: Standing[], displayNames: Record<string, string>) {
    return (
      <div className="standings-table-scroll">
        <table className="standings-table">
          <thead>
            <tr>
              <th>{t("position")}</th>
              <th>{t("team")}</th>
              <th>{t("played")}</th>
              <th>{t("wins")}</th>
              <th>{t("draws")}</th>
              <th>{t("losses")}</th>
              <th>{t("goalsForAgainst")}</th>
              <th>{t("gd")}</th>
              <th>{t("pts")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.name}>
                <td className="standings-position">{index + 1}</td>
                <td className="standings-team">
                  {teamLabel(displayNames, row.name)}
                </td>
                <td>{row.played}</td>
                <td>{row.wins}</td>
                <td>{row.draws}</td>
                <td>{row.losses}</td>
                <td>
                  {row.goals_for} / {row.goals_against}
                </td>
                <td>{row.goal_difference}</td>
                <td className="standings-points">{row.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  async function leaveGroup() {
    if (!group) return;
    await runAction(
      () =>
        apiFetch(`/groups/${group.id}/leave`, {
          method: "DELETE",
        }),
      "reload-app"
    );
    setShowGroupActions(false);
    setShowExitOptions(false);
    setSelectedGroupId(null);
  }

  async function transferAdminAndLeave() {
    if (!group || !transferTarget) return;
    await runAction(
      () =>
        apiFetch(`/groups/${group.id}/transfer-admin-and-leave`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target_membership_id: transferTarget }),
        }),
      "reload-app"
    );
    setShowGroupActions(false);
    setShowExitOptions(false);
    setTransferTarget("");
    setSelectedGroupId(null);
  }

  async function deleteGroup() {
    if (!group || !window.confirm(t("deleteGroupConfirm"))) return;
    if (group.picture_path) {
      try {
        await clearGroupPicture();
      } catch {
        return;
      }
    }
    await runAction(
      () =>
        apiFetch(`/groups/${group.id}`, {
          method: "DELETE",
        }),
      "reload-app"
    );
    setShowGroupActions(false);
    setShowExitOptions(false);
    setSelectedGroupId(null);
  }

  function countdownText(gameDay: GameDay) {
    const deadline = new Date(gameDay.regular_registration_opens);
    const diff = deadline.getTime() - now.getTime();
    if (diff <= 0) return t("registrationOpen");
    const totalSeconds = Math.floor(diff / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return `${t("subscribersOnly")}: ${hours.toString().padStart(2, "0")}:${minutes
      .toString()
      .padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }

  function statusLabel(status: string) {
    if (status === "live") return t("statusLive");
    if (status === "finished") return t("statusFinished");
    return t("statusUpcoming");
  }

  function draftTeamSize(
    teamName: string,
    draft: Record<string, string> = teamDraft
  ) {
    return Object.values(draft).filter((value) => value === teamName).length;
  }

  function updateTeamDraft(membershipId: string, teamName: string) {
    const updatedDraft = { ...teamDraft, [membershipId]: teamName };
    setTeamDraft(updatedDraft);
    const gameDay = group?.game_day;
    if (
      gameDay &&
      gameDay.teams.every(
        (team) =>
          draftTeamSize(team.name, updatedDraft) === gameDay.players_per_team
      )
    ) {
      setTeamAdjustmentError("");
    }
  }

  async function saveTeamAdjustments() {
    if (!group?.game_day) return;
    const requiredSize = group.game_day.players_per_team;
    const hasInvalidTeam = group.game_day.teams.some(
      (team) => draftTeamSize(team.name) !== requiredSize
    );
    if (hasInvalidTeam) {
      setTeamAdjustmentError(
        `Each team must have exactly ${requiredSize} players.`
      );
      return;
    }
    await runAction(() =>
      apiFetch(`/groups/${group.id}/game-days/${group.game_day!.id}/teams`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          assignments: Object.entries(teamDraft).map(
            ([membershipId, teamName]) => ({
              membership_id: membershipId,
              team_name: teamName || null,
            })
          ),
        }),
      })
    );
    setTeamAdjustmentError("");
    setEditingTeams(false);
  }

  const languageToggle = (
    <label className="language-toggle">
      {t("language")}
      <select
        value={lang}
        onChange={(event) => setLang(event.target.value as Language)}
      >
        <option value="en">{t("english")}</option>
        <option value="he">{t("hebrew")}</option>
      </select>
    </label>
  );

  if (!authReady) {
    return <div className="auth-shell">{t("loading")}</div>;
  }

  if (passwordRecovery && session) {
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={handlePasswordUpdate}>
          <h1>⚽ {t("appName")}</h1>
          <p>{t("chooseNewPassword")}</p>
          {languageToggle}
          <label>
            {t("newPassword")}
            <PasswordField
              value={password}
              onChange={setPassword}
              shown={showPassword}
              onToggle={() => setShowPassword((current) => !current)}
              showLabel={t("showPassword")}
              hideLabel={t("hidePassword")}
              autoComplete="new-password"
            />
          </label>
          <label>
            {t("confirmPassword")}
            <PasswordField
              value={confirmPassword}
              onChange={setConfirmPassword}
              shown={showPassword}
              onToggle={() => setShowPassword((current) => !current)}
              showLabel={t("showPassword")}
              hideLabel={t("hidePassword")}
              autoComplete="new-password"
            />
          </label>
          {error && <div className="error-box">{error}</div>}
          <button className="primary-button" type="submit" disabled={loading}>
            {t("updatePassword")}
          </button>
        </form>
      </div>
    );
  }

  if (!session) {
    const recoverySent = authMode === "forgot" && recoveryEmailSent;
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={handleAuth}>
          <h1>⚽ {t("appName")}</h1>
          <p>
            {authMode === "signup"
              ? t("signupSubtitle")
              : authMode === "forgot"
                ? t("forgotPasswordSubtitle")
                : t("loginSubtitle")}
          </p>
          {languageToggle}
          {authMode === "signup" && (
            <>
              <label>
                {t("firstName")}
                <input
                  value={signupFirstName}
                  onChange={(event) => setSignupFirstName(event.target.value)}
                  required
                />
              </label>
              <label>
                {t("lastName")}
                <input
                  value={signupLastName}
                  onChange={(event) => setSignupLastName(event.target.value)}
                  required
                />
              </label>
              <label>
                {t("nicknameOptional")}
                <input
                  value={signupNickname}
                  onChange={(event) => setSignupNickname(event.target.value)}
                />
              </label>
            </>
          )}
          {!recoverySent && (
            <label>
              {t("email")}
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                autoComplete="email"
              />
            </label>
          )}
          {authMode !== "forgot" && (
            <label>
              {t("password")}
              <PasswordField
                value={password}
                onChange={setPassword}
                shown={showPassword}
                onToggle={() => setShowPassword((current) => !current)}
                showLabel={t("showPassword")}
                hideLabel={t("hidePassword")}
                autoComplete={authMode === "signup" ? "new-password" : "current-password"}
              />
            </label>
          )}
          {authMode === "login" && (
            <button
              className="auth-text-button"
              type="button"
              onClick={() => {
                setError("");
                setShowPassword(false);
                setRecoveryEmailSent(false);
                setAuthMode("forgot");
              }}
            >
              {t("forgotPassword")}
            </button>
          )}
          {recoverySent && <p>{t("recoveryEmailSent")}</p>}
          {error && <div className="error-box">{error}</div>}
          {!recoverySent && (
            <button className="primary-button" type="submit" disabled={loading}>
              {authMode === "forgot"
                ? t("sendRecoveryEmail")
                : authMode === "login"
                  ? t("logIn")
                  : t("signUp")}
            </button>
          )}
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              if (authMode === "login") {
                setError("");
                setShowPassword(false);
                setAuthMode("signup");
                return;
              }
              returnToLogin();
            }}
          >
            {authMode === "login" ? t("createAccount") : t("backToLogin")}
          </button>
        </form>
      </div>
    );
  }

  const gameDay = group?.game_day ?? null;
  const finishedGameDay = group?.finished_game_day ?? null;
  const teamNames = gameDay?.teams.map((team) => team.name) ?? [];
  const currentTeamNames = teamDisplayNames(
    gameDay?.team_captain_names,
    t("captainTeam")
  );
  const finishedTeamNames = teamDisplayNames(
    finishedGameDay?.team_captain_names,
    t("captainTeam")
  );
  const currentTeamLabel = (teamName: string) =>
    teamLabel(currentTeamNames, teamName);
  const isLive = gameDay?.status === "live";
  const registrationState =
    currentMembership && gameDay
      ? gameDay.participants.some((item) => item.id === currentMembership.id)
        ? "registered"
        : gameDay.waiting_list.some((item) => item.id === currentMembership.id)
          ? "waiting"
          : "out"
      : null;
  const focusDay = gameDay ?? finishedGameDay;
  const viewerIsMvpParticipant = Boolean(
    focusDay &&
      currentMembership &&
      !currentMembership.is_virtual &&
      focusDay.participants.some(
        (player) =>
          player.id === currentMembership.id &&
          !player.is_guest &&
          !player.is_virtual
      )
  );
  const mvpVotingOpen = Boolean(focusDay?.mvp_open);
  const viewerCanVote = viewerCanVoteForMvp({
    mvpOpen: mvpVotingOpen,
    viewerIsVirtual: Boolean(currentMembership?.is_virtual),
    viewerIsParticipant: viewerIsMvpParticipant,
  });
  const mvpVoteRecorded = Boolean(focusDay?.my_vote);
  const showMvpReminder = shouldRemindMvpVote({
    mvpOpen: mvpVotingOpen,
    viewerCanVote,
    hasVoted: mvpVoteRecorded,
  });
  const guide = gameDayGuide({
    status: focusDay?.status ?? null,
    participantCount: focusDay?.participant_count ?? 0,
    registeredCount: focusDay?.participants.length ?? 0,
    teamCount: focusDay?.teams.length ?? 0,
    mvpOpen: mvpVotingOpen,
    viewerCanVote,
    hasVoted: mvpVoteRecorded,
    isAdmin,
    selfNeedsRegistration: registrationState === "out",
    pane: gamePane,
  });
  const registrationCta = gameDay
    ? registrationGenerateCta(guide, {
        registered: gameDay.participants.length,
        capacity: gameDay.participant_count,
      })
    : null;
  const registrationReady = Boolean(
    gameDay &&
      gameDay.participant_count > 0 &&
      gameDay.participants.length === gameDay.participant_count
  );
  const mvpBallot = finishedGameDay
    ? mvpCandidates(finishedGameDay.participants, currentMembership?.id ?? null)
    : [];
  function openMvpVote() {
    setMvpChoice(finishedGameDay?.my_vote ?? "");
    setMvpVoteOpen(true);
  }
  async function generateCurrentTeams() {
    if (!group || !gameDay) return;
    await runAction(() =>
      apiFetch(`/groups/${group.id}/game-days/${gameDay.id}/generate-teams`, {
        method: "POST",
      })
    );
    setGamePane("teams");
  }
  async function startCurrentGameDay() {
    if (!group || !gameDay) return;
    await runAction(() =>
      apiFetch(`/groups/${group.id}/game-days/${gameDay.id}/start`, {
        method: "POST",
      })
    );
    setGamePane("matches");
  }
  async function finishCurrentGameDay() {
    if (!group || !gameDay) return;
    if (!window.confirm(t("finishGameDayConfirm"))) return;
    await runAction(() =>
      apiFetch(`/groups/${group.id}/game-days/${gameDay.id}/finish`, {
        method: "POST",
      })
    );
  }
  async function closeMvpVoting() {
    if (!group || !finishedGameDay) return;
    await runAction(() =>
      apiFetch(`/groups/${group.id}/game-days/${finishedGameDay.id}/mvp/close`, {
        method: "POST",
      })
    );
    setMvpVoteOpen(false);
  }
  function runGuideAction(action: (typeof guide.actions)[number]) {
    if (
      action === "createGameDay" ||
      action === "register" ||
      action === "openRegistration"
    ) {
      setGamePane("registration");
      return;
    }
    if (action === "reviewTeams") {
      setGamePane("teams");
      return;
    }
    if (action === "openMatches") {
      setGamePane("matches");
      return;
    }
    if (action === "generateTeams") {
      void generateCurrentTeams();
      return;
    }
    if (action === "startGameDay") {
      void startCurrentGameDay();
      return;
    }
    if (action === "finishGameDay") {
      void finishCurrentGameDay();
      return;
    }
    if (action === "voteMvp") {
      openMvpVote();
      return;
    }
    if (action === "viewResults") {
      openSection("stats");
    }
  }
  const guideActions = (
    <div className="game-day-status-actions">
      {guide.actions.map((action, index) => (
        <button
          key={action}
          type="button"
          className={index === 0 ? "primary-button" : "secondary-button"}
          onClick={() => runGuideAction(action)}
        >
          {t(guideActionLabel[action])}
        </button>
      ))}
      {isAdmin && finishedGameDay?.mvp_open && (
        <button
          className="secondary-button"
          type="button"
          onClick={() => void closeMvpVoting()}
        >
          {t("closeVoting")}
        </button>
      )}
      {isLive && isAdmin && gameDay && group && (
        <button
          className="danger-button"
          type="button"
          onClick={() => {
            const groupId = group.id;
            const gameDayId = gameDay.id;
            void runAction(() =>
              apiFetch(`/groups/${groupId}/game-days/${gameDayId}`, {
                method: "DELETE",
              })
            ).then(() =>
              setGroup((current) =>
                current ? { ...current, game_day: null } : current
              )
            );
          }}
        >
          {t("deleteGameDay")}
        </button>
      )}
    </div>
  );
  const latestMessage = chatMessages[0] ?? null;
  const dayStatisticsRows: StatisticsTableRow[] = dayStats.map((row) => ({
    id: row.member.id,
    name: playerName(row.member),
    full_name: row.member.full_name,
    first_name: row.member.first_name,
    last_name: row.member.last_name,
    avatar_path: row.member.avatar_path,
    avatar_version: row.member.avatar_version,
    rating: row.member.rating,
    goalkeeperRating: row.member.goalkeeper_rating,
    gameDays: 0,
    matches: row.played,
    championships: 0,
    goals: row.goals,
    assists: row.assists,
    mvps: 0,
  }));
  const overallStatisticsRows: StatisticsTableRow[] = stats.map((row) => ({
    id: row.id,
    name: row.name,
    full_name: row.full_name,
    first_name: row.first_name,
    last_name: row.last_name,
    avatar_path: row.avatar_path,
    avatar_version: row.avatar_version,
    rating: row.rating,
    goalkeeperRating: row.goalkeeper_rating,
    gameDays: row.game_days_played,
    matches: row.matches_played,
    championships: row.championships,
    goals: row.goals,
    assists: row.assists,
    mvps: row.mvp_titles,
  }));
  const goalsPerGame = (row: StatisticsTableRow) =>
    row.matches === 0 ? 0 : row.goals / row.matches;
  const assistsPerGame = (row: StatisticsTableRow) =>
    row.matches === 0 ? 0 : row.assists / row.matches;
  const rateColumns: StatisticsTableColumn[] = [
    {
      key: "name",
      label: t("playerColumn"),
      value: (row) => row.name,
    },
    {
      key: "matches",
      label: t("matchesPlayed"),
      value: (row) => row.matches,
    },
    {
      key: "goals",
      label: t("goals"),
      value: (row) => row.goals,
    },
    {
      key: "goalsPerGame",
      label: t("goalsPerGame"),
      value: goalsPerGame,
      display: (row) => goalsPerGame(row).toFixed(2),
    },
    {
      key: "assists",
      label: t("assists"),
      value: (row) => row.assists,
    },
    {
      key: "assistsPerGame",
      label: t("assistsPerGame"),
      value: assistsPerGame,
      display: (row) => assistsPerGame(row).toFixed(2),
    },
  ];
  const ratingColumns: StatisticsTableColumn[] = [
    {
      key: "rating",
      label: t("playerRating"),
      value: (row) => row.rating,
    },
    {
      key: "goalkeeperRating",
      label: t("goalkeeperRating"),
      value: (row) => row.goalkeeperRating,
    },
  ];
  const overallStatisticsColumns: StatisticsTableColumn[] = [
    rateColumns[0]!,
    ...ratingColumns,
    {
      key: "gameDays",
      label: t("gameDaysPlayed"),
      value: (row) => row.gameDays,
    },
    rateColumns[1]!,
    {
      key: "championships",
      label: t("championships"),
      value: (row) => row.championships,
    },
    ...rateColumns.slice(2),
    {
      key: "mvps",
      label: t("mvps"),
      value: (row) => row.mvps,
    },
  ];
  const dayStatsRows = (
    <SortableStatisticsTable
      key="day"
      rows={dayStatisticsRows}
      columns={[rateColumns[0]!, ...ratingColumns, ...rateColumns.slice(1)]}
      emptyText={t("noDayStats")}
    />
  );

  return (
    <ReigningTitlesProvider titles={titles}>
    <div className="app">
      <header className="header app-header">
        <div className="app-header-title" ref={groupMenuRef}>
          <h1>⚽ {t("appName")}</h1>
          <button
            type="button"
            className="group-switch-button"
            aria-expanded={groupMenuOpen}
            aria-haspopup="menu"
            onClick={() => setGroupMenuOpen((current) => !current)}
          >
            <span>{group && isMember ? group.name : t("myGroups")}</span>
            <span className="group-switch-caret" aria-hidden="true">
              ▼
            </span>
          </button>
          {groupMenuOpen && (
            <div className="group-switch-menu" role="menu">
              {myGroups.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={selectedGroupId === item.id}
                  className={
                    selectedGroupId === item.id
                      ? "group-switch-option active"
                      : "group-switch-option"
                  }
                  onClick={() => selectGroup(item.id)}
                >
                  <strong>{item.name}</strong>
                  <span>{item.is_admin ? t("admin") : t("member")}</span>
                </button>
              ))}
              <form
                className="group-switch-create"
                onSubmit={(event) => {
                  event.preventDefault();
                  setGroupMenuOpen(false);
                  createGroup();
                }}
              >
                <input
                  placeholder={t("newGroupName")}
                  aria-label={t("newGroupName")}
                  value={newGroupName}
                  onChange={(event) => setNewGroupName(event.target.value)}
                />
                <button
                  className="primary-button"
                  type="submit"
                  disabled={!newGroupName.trim()}
                >
                  + {t("createGroup")}
                </button>
              </form>
            </div>
          )}
        </div>
        <button
          type="button"
          className="avatar-button"
          aria-label={t("settings")}
          aria-current={section === "settings" ? "page" : undefined}
          onClick={() => {
            populateProfileForm(profile);
            openSection(section === "settings" ? "home" : "settings");
          }}
        >
          <PlayerAvatar
            player={{
              id: profile?.id,
              user_id: profile?.id,
              name: profile?.display_name ?? session.user.email ?? t("myProfile"),
              full_name: profile?.full_name,
              first_name: profile?.first_name,
              last_name: profile?.last_name,
              avatar_path: profile?.avatar_path,
              avatar_version: profile?.avatar_version,
            }}
          />
        </button>
      </header>

      <div className="page-layout">
        <main className="container app-main">
          {section === "settings" && (
            <section className="card profile-card">
              <h2>{t("myProfile")}</h2>
              {profile && (
                <div className="profile-avatar-editor">
                  <PlayerAvatar player={{ ...profile, name: profile.display_name }} size="large" />
                  <div className="form-actions">
                    <label className="secondary-button file-button">
                      {t("choosePicture")}
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) {
                            saveAvatar(
                              file,
                              profile,
                              `users/${profile.id}/`,
                              "/profile/avatar"
                            );
                          }
                          event.currentTarget.value = "";
                        }}
                      />
                    </label>
                    {profile.avatar_path && (
                      <button
                        className="text-danger-button"
                        onClick={() => clearAvatar(profile, "/profile/avatar")}
                      >
                        {t("removePicture")}
                      </button>
                    )}
                  </div>
                </div>
              )}
              {editingProfile ? (
                <form className="form-panel" onSubmit={saveProfile}>
                  <label>
                    {t("firstName")}
                    <input
                      value={profileFirstName}
                      maxLength={80}
                      onChange={(event) => setProfileFirstName(event.target.value)}
                      required
                    />
                  </label>
                  <label>
                    {t("lastName")}
                    <input
                      value={profileLastName}
                      maxLength={80}
                      onChange={(event) => setProfileLastName(event.target.value)}
                    />
                  </label>
                  <label>
                    {t("nicknameOptional")}
                    <input
                      value={profileNickname}
                      maxLength={80}
                      onChange={(event) => setProfileNickname(event.target.value)}
                    />
                  </label>
                  <p className="muted-text">
                    {t("displayedAs")}:{" "}
                    <strong>{profileNickname.trim() || profileFirstName.trim()}</strong>
                  </p>
                  <div className="form-actions">
                    <button
                      className="primary-button"
                      type="submit"
                      disabled={!profileFirstName.trim() || profileSaving}
                    >
                      {t("save")}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      onClick={() => {
                        setEditingProfile(false);
                        populateProfileForm(profile);
                        setProfileError("");
                      }}
                    >
                      {t("cancel")}
                    </button>
                  </div>
                </form>
              ) : (
                <div className="profile-details">
                  <div>
                    <span className="muted-text">{t("fullName")}</span>
                    <strong>{profile?.full_name ?? t("loading")}</strong>
                    <span className="muted-text">
                      {t("displayedAs")}: {profile?.display_name ?? t("loading")}
                    </span>
                    {profile?.email && (
                      <span className="muted-text">{profile.email}</span>
                    )}
                    {profile && !profile.is_complete && (
                      <span className="profile-incomplete">{t("profileIncomplete")}</span>
                    )}
                  </div>
                  <button
                    className="secondary-button"
                    disabled={!profile}
                    onClick={() => setEditingProfile(true)}
                  >
                    {t("edit")}
                  </button>
                </div>
              )}
              {profileError && <p className="chat-error">{profileError}</p>}
            </section>
          )}
          {section === "settings" && (
            <section className="card">
              <h2>{t("settings")}</h2>
              {languageToggle}
              <div className="form-actions">
                <button
                  className="secondary-button"
                  onClick={() => supabase.auth.signOut()}
                >
                  {t("logOut")}
                </button>
              </div>
              <p className="muted-text">Version 1.0.0-beta.11</p>
            </section>
          )}
          {section === "settings" && isDeveloper && DEV_TOOLS_ENABLED && (
            <aside className="developer-panel settings-tools">
              <h3>{t("developerTools")}</h3>
              <button
                disabled={!group}
                onClick={() =>
                  group &&
                  runAction(() =>
                    apiFetch(
                      `/dev/groups/${group.id}/add-test-members?count=${participantCount}`,
                      { method: "POST" }
                    )
                  )
                }
              >
                {t("fillMembers")}
              </button>
              <button
                disabled={!group}
                onClick={() =>
                  group &&
                  runAction(() =>
                    apiFetch(
                      `/dev/groups/${group.id}/create-game?participant_count=${participantCount}&players_per_team=${playersPerTeam}`,
                      { method: "POST" }
                    )
                  )
                }
              >
                {t("createTestGameDay")}
              </button>
              <button
                disabled={!gameDay}
                onClick={() =>
                  group &&
                  runAction(() =>
                    apiFetch(`/dev/groups/${group.id}/register-all`, {
                      method: "POST",
                    })
                  )
                }
              >
                {t("registerAll")}
              </button>
              <button
                disabled={!gameDay}
                onClick={() =>
                  group &&
                  runAction(() =>
                    apiFetch(`/dev/groups/${group.id}/expire-priority`, {
                      method: "POST",
                    })
                  )
                }
              >
                {t("expirePriority")}
              </button>
              <button
                disabled={!gameDay}
                onClick={() =>
                  group &&
                  runAction(() =>
                    apiFetch(`/dev/groups/${group.id}/start-live`, {
                      method: "POST",
                    })
                  )
                }
              >
                {t("startLive")}
              </button>
              <label className="view-as">
                {t("viewAs")}
                <select
                  value={actAs ?? ""}
                  onChange={(event) => {
                    const picked = event.target.value;
                    const member = group?.members.find(
                      (item) => item.id === picked
                    );
                    viewAs(picked || null, member?.name ?? "");
                  }}
                >
                  <option value="">{t("myself")}</option>
                  {(group?.members ?? [])
                    .filter((member) => !member.is_virtual)
                    .map((member) => (
                      <option key={member.id} value={member.id}>
                        {member.name}
                      </option>
                    ))}
                </select>
              </label>
              <p className="muted-text">{t("simulationNote")}</p>
            </aside>
          )}
          {actAs && (
            <div className="simulation-banner">
              <span>
                {t("simulating")} <strong>{simulatedName || "…"}</strong>
              </span>
              <button className="secondary-button" onClick={() => viewAs(null)}>
                {t("stopSimulating")}
              </button>
            </div>
          )}
          {error && <div className="error-box">{error}</div>}

          {(section === "home" || section === "settings") &&
            invitePreview &&
            invitePreview.state !== "member" && (
            <section className="card join-card">
              <h2>
                {t("invitedTo")} {invitePreview.name}
              </h2>
              {invitePreview.state === "pending" ? (
                <div className="status-box pending">{t("joinPending")}</div>
              ) : (
                <button
                  className="primary-button"
                  onClick={() => {
                    runAction(
                      () =>
                        apiFetch(`/groups/${invitePreview.id}/join-request`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({ invite_code: inviteCode }),
                        })
                    ).then(() => loadInvite(inviteCode));
                  }}
                >
                  {t("requestToJoin")}
                </button>
              )}
            </section>
          )}

          {section === "home" && (
            <section className="card home-dashboard">
              {group && isMember ? (
                <div className="home-group-identity">
                  <GroupPicture
                    name={group.name}
                    picturePath={group.picture_path}
                    pictureVersion={group.picture_version}
                  />
                  <h2>{group.name}</h2>
                </div>
              ) : (
                <h2>{t("navHome")}</h2>
              )}
              {!(group && isMember) ? (
                <>
                  <p>{t("chooseGroup")}</p>
                  <button
                    className="primary-button"
                    onClick={() => setGroupMenuOpen(true)}
                  >
                    {t("myGroups")}
                  </button>
                </>
              ) : (
                <>
                  <div className="home-summary">
                    <span className="muted-text">{t("nextGameDay")}</span>
                    {!gameDay ? (
                      finishedGameDay ? (
                        <strong>
                          {t("flowFinished")} ·{" "}
                          {new Date(finishedGameDay.game_datetime).toLocaleString()}
                        </strong>
                      ) : (
                        <strong>{t("noGameDay")}</strong>
                      )
                    ) : (
                      <>
                        <strong>
                          {statusLabel(gameDay.status)} ·{" "}
                          {new Date(gameDay.game_datetime).toLocaleString()}
                        </strong>
                        {gameDay.status === "upcoming" && (
                          <>
                            <span>{countdownText(gameDay)}</span>
                            <span>
                              {gameDay.participants.length}/{gameDay.participant_count}{" "}
                              {t("registered")} · {gameDay.waiting_list.length}{" "}
                              {t("waiting")}
                            </span>
                          </>
                        )}
                        <span>
                          {t("yourStatus")}:{" "}
                          {registrationState === "registered"
                            ? t("registered")
                            : registrationState === "waiting"
                              ? t("waiting")
                              : t("notRegistered")}
                        </span>
                      </>
                    )}
                  </div>
                  {isLive && (
                    <div className="live-banner">
                      <span className="live-dot" aria-hidden="true" />
                      <strong>{t("liveGameDay")}</strong>
                    </div>
                  )}
                  {showMvpReminder && finishedGameDay && (
                    <div className="mvp-reminder">
                      <strong>{t("voteMvp")}</strong>
                      <p>{t("mvpReminder")}</p>
                      <button
                        className="primary-button"
                        type="button"
                        onClick={openMvpVote}
                      >
                        {t("voteMvp")}
                      </button>
                    </div>
                  )}
                  <div className="home-shortcuts">
                    <button
                      className="primary-button"
                      onClick={() => {
                        setGamePane(isLive ? "matches" : "registration");
                        openSection("game");
                      }}
                    >
                      {isLive ? t("enterLiveGameDay") : t("gameDay")}
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => {
                        setGroupPane("members");
                        openSection("group");
                      }}
                    >
                      {t("navGroup")}
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() => {
                        if (isLive || finishedGameDay) setStatsScope("day");
                        openSection("stats");
                      }}
                    >
                      {t("navStats")}
                    </button>
                  </div>
                  <div className="home-updates">
                    <h3>{t("recentUpdates")}</h3>
                    {isAdmin && joinRequests.length > 0 && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setGroupPane("manage");
                          openSection("group");
                        }}
                      >
                        {t("pendingJoinRequests")} ({joinRequests.length})
                      </button>
                    )}
                    {group.survey?.status === "open" && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setGroupPane("ratings");
                          openSection("group");
                        }}
                      >
                        {t("ratingSurvey")}
                      </button>
                    )}
                    {latestMessage && (
                      <button
                        className="text-button"
                        onClick={() => {
                          setGroupPane("chat");
                          openSection("group");
                        }}
                      >
                        <strong>{latestMessage.sender_name}:</strong>{" "}
                        {latestMessage.message}
                      </button>
                    )}
                    {finishedGameDay && (
                      <button
                        className="text-button"
                        onClick={() => openSection("stats")}
                      >
                        {finishedGameDay.champion_team_name
                          ? `${t("champion")}: ${championLabel(
                              finishedTeamNames,
                              finishedGameDay.champion_team_name
                            )}`
                          : t("history")}
                      </button>
                    )}
                    {!latestMessage &&
                      joinRequests.length === 0 &&
                      group.survey?.status !== "open" &&
                      !finishedGameDay && <p className="muted-text">{t("noRecentUpdates")}</p>}
                  </div>
                </>
              )}
            </section>
          )}

          {section === "settings" && (
          <section className="card">
            <div className="section-header">
              <div>
                <h2>{t("myGroups")}</h2>
                <span>
                  {myGroups.length} {t("memberships")}
                </span>
              </div>
            </div>
            <div className="group-switcher">
              {myGroups.map((item) => (
                <button
                  key={item.id}
                  className={
                    selectedGroupId === item.id ? "group-chip active" : "group-chip"
                  }
                  onClick={() => selectGroup(item.id)}
                >
                  <strong>{item.name}</strong>
                  <span>{item.is_admin ? t("admin") : t("member")}</span>
                </button>
              ))}
            </div>
            <div className="create-group-row">
              <input
                placeholder={t("newGroupName")}
                value={newGroupName}
                onChange={(event) => setNewGroupName(event.target.value)}
              />
              <button
                className="primary-button"
                disabled={!newGroupName.trim()}
                onClick={createGroup}
              >
                {t("createGroup")}
              </button>
            </div>
          </section>
          )}

          {section === "group" && group && isMember && (
            <section className="card group-title-card">
              <div className="group-title-row">
                <h2>{group.name}</h2>
                <div className="header-actions">
                  <div className="group-actions-wrapper">
                    <button
                      className="secondary-button"
                      aria-expanded={showGroupActions}
                      onClick={() =>
                        setShowGroupActions((current) => !current)
                      }
                    >
                      {t("groupActions")}
                    </button>
                    {showGroupActions && (
                      <div className="group-actions-menu" role="menu">
                        <button
                          className="text-danger-button"
                          role="menuitem"
                          onClick={() => {
                            setShowGroupActions(false);
                            if (isSoleRealAdmin) {
                              setGroupPane("manage");
                              setShowExitOptions(true);
                            } else if (window.confirm(t("leaveConfirm"))) {
                              leaveGroup();
                            }
                          }}
                        >
                          {t("leaveGroup")}
                        </button>
                        {isAdmin && (
                          <button
                            className="danger-button"
                            role="menuitem"
                            onClick={deleteGroup}
                          >
                            {t("deleteGroup")}
                          </button>
                        )}
                        <button
                          className="secondary-button"
                          role="menuitem"
                          onClick={() => setShowGroupActions(false)}
                        >
                          {t("cancel")}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              <div className="section-tabs" role="tablist">
                {(
                  [
                    ["members", t("members")],
                    ["ratings", t("ratings")],
                    ["manage", t("manage")],
                    ["chat", t("chat")],
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={groupPane === key}
                    className={
                      groupPane === key ? "primary-button" : "secondary-button"
                    }
                    onClick={() => setGroupPane(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </section>
          )}

          {section === "group" && groupPane === "manage" && group && isMember && (
            <section className="card">
              <h2>{t("groupActions")}</h2>
              <div className="form-actions">
                <button
                  className="text-danger-button"
                  onClick={() => {
                    if (isSoleRealAdmin) {
                      setShowExitOptions(true);
                    } else if (window.confirm(t("leaveConfirm"))) {
                      leaveGroup();
                    }
                  }}
                >
                  {t("leaveGroup")}
                </button>
                {isAdmin && (
                  <button className="danger-button" onClick={deleteGroup}>
                    {t("deleteGroup")}
                  </button>
                )}
              </div>
            </section>
          )}

          {section === "group" &&
            groupPane === "manage" &&
            group &&
            isMember &&
            showExitOptions &&
            isSoleRealAdmin && (
            <section className="card exit-options group-page-only" aria-live="polite">
              <h2>{t("soleAdminExitTitle")}</h2>
              <p>{t("soleAdminExitHelp")}</p>
              {otherRealMembers.length > 0 && (
                <div className="form-panel">
                  <label>
                    {t("transferAdminTo")}
                    <select
                      value={transferTarget}
                      onChange={(event) => setTransferTarget(event.target.value)}
                    >
                      <option value="">—</option>
                      {otherRealMembers.map((member) => (
                        <option key={member.id} value={member.id}>
                          {member.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="primary-button"
                    disabled={!transferTarget}
                    onClick={transferAdminAndLeave}
                  >
                    {t("transferAndLeave")}
                  </button>
                </div>
              )}
              {otherRealMembers.length === 0 && (
                <p className="muted-text">{t("noRealMemberForTransfer")}</p>
              )}
              <div className="form-actions">
                <button className="danger-button" onClick={deleteGroup}>
                  {t("deleteGroup")}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setShowExitOptions(false);
                    setTransferTarget("");
                  }}
                >
                  {t("cancel")}
                </button>
              </div>
            </section>
          )}

          {section === "group" && groupPane === "manage" && group && isAdmin && (
            <section className="card group-page-only">
              <h2>{t("groupPicture")}</h2>
              <div className="profile-avatar-editor">
                <GroupPicture
                  name={group.name}
                  picturePath={group.picture_path}
                  pictureVersion={group.picture_version}
                  size="editor"
                />
                <div className="form-actions">
                  <label className="secondary-button file-button">
                    {t("choosePicture")}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) saveGroupPicture(file);
                        event.currentTarget.value = "";
                      }}
                    />
                  </label>
                  {group.picture_path && (
                    <button
                      className="text-danger-button"
                      onClick={() => {
                        clearGroupPicture().catch(() => {});
                      }}
                    >
                      {t("removePicture")}
                    </button>
                  )}
                </div>
              </div>
            </section>
          )}

          {section === "group" && groupPane === "manage" && group && isAdmin && (
            <section className="card group-page-only">
              <h2>{t("invite")}</h2>
              <p>
                {t("inviteCode")}: <strong>{group.invite_code}</strong>
              </p>
              <p className="muted-text">{group.invite_link}</p>
              <div className="form-actions">
                <button
                  className="secondary-button"
                  onClick={() => {
                    if (group.invite_link) {
                      navigator.clipboard.writeText(group.invite_link);
                      setCopied(true);
                      window.setTimeout(() => setCopied(false), 1500);
                    }
                  }}
                >
                  {copied ? t("copied") : t("copy")}
                </button>
                <button
                  className="secondary-button"
                  onClick={() => {
                    if (window.confirm(t("regenerateConfirm"))) {
                      runAction(() =>
                        apiFetch(`/groups/${group.id}/invite/regenerate`, {
                          method: "POST",
                        })
                      );
                    }
                  }}
                >
                  {t("regenerateInvite")}
                </button>
              </div>
            </section>
          )}

          {section === "group" &&
            groupPane === "manage" &&
            group &&
            isAdmin &&
            joinRequests.length > 0 && (
            <section className="card group-page-only">
              <h2>{t("pendingJoinRequests")}</h2>
              {joinRequests.map((request) => (
                <div className="request-row" key={request.id}>
                  <span className="player-identity">
                    <PlayerAvatar
                      player={{
                        name: request.user_name,
                        full_name: request.user_full_name,
                        avatar_path: request.avatar_path,
                        avatar_version: request.avatar_version,
                      }}
                    />
                    <span>
                      <strong>{request.user_name}</strong>
                      {request.user_full_name &&
                        request.user_full_name !== request.user_name && (
                          <span className="member-full-name">
                            {request.user_full_name}
                          </span>
                        )}
                    </span>
                  </span>
                  <div className="request-actions">
                    <button
                      className="primary-button"
                      onClick={() =>
                        runAction(
                          () =>
                            apiFetch(
                              `/groups/${group.id}/join-requests/${request.id}/approve`,
                              { method: "POST" }
                            ),
                          "reload-group"
                        )
                      }
                    >
                      {t("approve")}
                    </button>
                    <button
                      className="secondary-button"
                      onClick={() =>
                        runAction(
                          () =>
                            apiFetch(
                              `/groups/${group.id}/join-requests/${request.id}/decline`,
                              { method: "POST" }
                            )
                        ).then(() =>
                          setJoinRequests((current) =>
                            current.filter((item) => item.id !== request.id)
                          )
                        )
                      }
                    >
                      {t("decline")}
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {section === "stats" && group && isMember && (
            <section className="card group-page-only">
              <div className="section-header">
                <h2>{t("statistics")}</h2>
                <div className="header-actions">
                  <button
                    className={
                      statsScope === "day" ? "primary-button" : "secondary-button"
                    }
                    onClick={() => setStatsScope("day")}
                  >
                    {t("dayStatistics")}
                  </button>
                  <button
                    className={
                      statsScope === "overall"
                        ? "primary-button"
                        : "secondary-button"
                    }
                    onClick={() => setStatsScope("overall")}
                  >
                    {t("overallStatistics")}
                  </button>
                </div>
              </div>
              {statsScope === "day" ? (
                dayStatsRows
              ) : (
                <SortableStatisticsTable
                  key="overall"
                  rows={overallStatisticsRows}
                  columns={overallStatisticsColumns}
                  emptyText={t("noDayStats")}
                />
              )}
            </section>
          )}

          {section !== "home" && section !== "settings" && !(group && isMember) && (
            <section className="card">
              <p>{t("chooseGroup")}</p>
              <button className="primary-button" onClick={() => setGroupMenuOpen(true)}>
                {t("myGroups")}
              </button>
            </section>
          )}

          {group && isMember && section !== "settings" && (
            <>
              {section === "group" && groupPane === "chat" && (
              <section className="card group-chat-card">
                <div
                  className="section-header collapsible-header"
                  role="button"
                  tabIndex={0}
                  aria-expanded={chatExpanded}
                  onClick={() => setChatExpanded((current) => !current)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setChatExpanded((current) => !current);
                    }
                  }}
                >
                  <div className="collapsible-title">
                    <span
                      className={chatExpanded ? "chevron expanded" : "chevron"}
                      aria-hidden="true"
                    >
                      ›
                    </span>
                    <h2>{t("groupChat")}</h2>
                  </div>
                </div>
                {chatExpanded && (
                  <>
                    <div className="chat-messages" ref={chatMessagesRef}>
                      {chatMessages.length === 0 && !chatError && (
                        <p className="muted-text">{t("noChatMessages")}</p>
                      )}
                      {chatMessages.map((message) => (
                        <div className="chat-message" key={message.id}>
                          <div className="chat-message-meta">
                            <span className="player-identity">
                              <PlayerAvatar
                                size="small"
                                player={{
                                  id: message.sender_user_id,
                                  user_id: message.sender_user_id,
                                  name: message.sender_name,
                                  avatar_path: message.sender_avatar_path,
                                  avatar_version: message.sender_avatar_version,
                                }}
                              />
                              <strong>{message.sender_name}</strong>
                            </span>
                            <time dateTime={message.created_at}>
                              {new Date(message.created_at).toLocaleString(
                                lang === "he" ? "he-IL" : "en-US",
                                {
                                  dateStyle: "short",
                                  timeStyle: "short",
                                }
                              )}
                            </time>
                          </div>
                          <p>{message.message}</p>
                        </div>
                      ))}
                    </div>
                    {chatError && <p className="chat-error">{chatError}</p>}
                    <form className="chat-form" onSubmit={sendGroupMessage}>
                      <input
                        value={chatDraft}
                        maxLength={1000}
                        placeholder={t("chatMessagePlaceholder")}
                        aria-label={t("chatMessagePlaceholder")}
                        onChange={(event) => setChatDraft(event.target.value)}
                      />
                      <button
                        className="primary-button"
                        type="submit"
                        disabled={!chatDraft.trim() || chatSending}
                      >
                        {t("send")}
                      </button>
                    </form>
                  </>
                )}
              </section>
              )}

              {section === "game" && (
                <section className="card">
                  <h2>{t("gameDay")}</h2>
                  <div className="section-tabs" role="tablist">
                    {(
                      [
                        ["registration", t("registration")],
                        ["teams", t("teams")],
                        ["matches", t("matches")],
                      ] as const
                    ).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        role="tab"
                        aria-selected={gamePane === key}
                        className={
                          gamePane === key ? "primary-button" : "secondary-button"
                        }
                        onClick={() => setGamePane(key)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  {focusDay && (
                    <div className="game-day-status" role="status">
                      <div className="game-day-status-label">
                        {guide.bar === "live" && (
                          <span className="live-dot" aria-hidden="true" />
                        )}
                        <strong>{t(guideBarLabel(guide.bar))}</strong>
                      </div>
                      <p className="game-day-status-stage">
                        {t(guideStageLabel(guide.stage))}
                      </p>
                      <p className="muted-text">
                        {t(guideDetailLabel(guide.detail)).replace(
                          "{count}",
                          String(guide.spotsRemaining)
                        )}
                      </p>
                      {guideActions}
                    </div>
                  )}
                </section>
              )}

              {section === "game" && gamePane === "registration" && (
              <section className="card">
                <h2>{t("nextGameDay")}</h2>
                {!gameDay ? (
                  <>
                    <p>{t("noGameDay")}</p>
                    {isAdmin && (
                      <div className="form-panel">
                        <div className="form-row">
                          <label>
                            {t("gameDate")}
                            <input
                              type="date"
                              value={gameDate}
                              onChange={(event) => setGameDate(event.target.value)}
                            />
                          </label>
                          <label>
                            {t("kickoffTime")}
                            <input
                              type="time"
                              value={gameTime}
                              onChange={(event) => setGameTime(event.target.value)}
                            />
                          </label>
                        </div>
                        <div className="form-row">
                          <label>
                            {t("participatingPlayers")}
                            <input
                              type="number"
                              min={2}
                              max={40}
                              value={participantCount}
                              onChange={(event) =>
                                setParticipantCount(Number(event.target.value))
                              }
                            />
                          </label>
                          <label>
                            {t("playersPerTeam")}
                            <input
                              type="number"
                              min={2}
                              max={11}
                              value={playersPerTeam}
                              onChange={(event) =>
                                setPlayersPerTeam(Number(event.target.value))
                              }
                            />
                          </label>
                        </div>
                        <p className="muted-text">
                          {t("completeTeams")}: {completeTeams} · {t("leftoverPlayers")}:{" "}
                          {leftover}
                        </p>
                        {leftover > 0 && (
                          <div className="status-box pending">{t("rotatingWarning")}</div>
                        )}
                        <label>
                          {t("subscriberPriority")}
                          <select
                            value={priorityHours}
                            onChange={(event) =>
                              setPriorityHours(Number(event.target.value))
                            }
                          >
                            <option value={6}>{t("hours6")}</option>
                            <option value={12}>{t("hours12")}</option>
                            <option value={24}>{t("hours24")}</option>
                            <option value={48}>{t("hours48")}</option>
                            <option value={72}>{t("days3")}</option>
                          </select>
                        </label>
                        <button
                          className="primary-button"
                          disabled={!gameDate || !gameTime}
                          onClick={() =>
                            runAction(() =>
                              apiFetch(`/groups/${group.id}/game-days`, {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  game_datetime: toLocalIso(gameDate, gameTime),
                                  priority_hours: priorityHours,
                                  participant_count: participantCount,
                                  players_per_team: playersPerTeam,
                                }),
                              })
                            )
                          }
                        >
                          {t("createGameDay")}
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <p>
                      <strong>{statusLabel(gameDay.status)}</strong> · {t("kickoff")}:{" "}
                      {new Date(gameDay.game_datetime).toLocaleString()}
                    </p>
                    <p className="muted-text">
                      {gameDay.participant_count} {t("members")} ·{" "}
                      {gameDay.players_per_team} {t("playersPerTeam")} ·{" "}
                      {gameDay.complete_teams} {t("completeTeams")}
                      {gameDay.is_rotating
                        ? ` · ${gameDay.leftover_players} ${t("leftoverPlayers")}`
                        : ""}
                    </p>
                    {/* Once the day starts, the countdown and the sign-up
                        tallies are answering a question nobody is asking any
                        more. The registrations themselves are untouched. */}
                    {gameDay.status === "upcoming" && (
                      <>
                        <div className="countdown">{countdownText(gameDay)}</div>
                        <div className="game-stats">
                          <span>
                            <strong>{gameDay.participants.length}</strong>/
                            {gameDay.participant_count} {t("registered")}
                          </span>
                          <span>
                            <strong>{gameDay.waiting_list.length}</strong>{" "}
                            {t("waiting")}
                          </span>
                        </div>
                        {isAdmin && (
                          <>
                            <button
                              className="secondary-button"
                              disabled={
                                gameDay.participants.length >= gameDay.participant_count
                              }
                              onClick={() => {
                                resetGuestForm();
                                setShowGuestForm(true);
                              }}
                            >
                              + {t("addGuest")}
                            </button>
                            {showGuestForm && (
                              <form className="member-form" onSubmit={saveGuest}>
                                <div className="form-row">
                                  <label>
                                    {t("guestName")}
                                    <input
                                      value={guestName}
                                      onChange={(event) => setGuestName(event.target.value)}
                                      autoFocus
                                      required
                                    />
                                  </label>
                                  <label>
                                    {t("playerRating")}
                                    <input
                                      type="number"
                                      min={1}
                                      max={5}
                                      step={0.5}
                                      value={guestRating}
                                      onChange={(event) =>
                                        setGuestRating(Number(event.target.value))
                                      }
                                      required
                                    />
                                  </label>
                                  <label>
                                    {t("goalkeeperRating")}
                                    <input
                                      type="number"
                                      min={1}
                                      max={5}
                                      step={0.5}
                                      value={guestGoalkeeperRating}
                                      onChange={(event) =>
                                        setGuestGoalkeeperRating(
                                          Number(event.target.value)
                                        )
                                      }
                                      required
                                    />
                                  </label>
                                </div>
                                <div className="form-actions">
                                  <button className="primary-button" type="submit">
                                    {t("save")}
                                  </button>
                                  <button
                                    className="secondary-button"
                                    type="button"
                                    onClick={resetGuestForm}
                                  >
                                    {t("cancel")}
                                  </button>
                                </div>
                              </form>
                            )}
                          </>
                        )}
                      </>
                    )}
                    {isAdmin && gameDay.status === "upcoming" && (
                      <div className="form-actions">
                        <button
                          className="danger-button"
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/game-days/${gameDay.id}`,
                                { method: "DELETE" }
                              )
                            ).then(() =>
                              setGroup((current) =>
                                current ? { ...current, game_day: null } : current
                              )
                            )
                          }
                        >
                          {t("deleteGameDay")}
                        </button>
                      </div>
                    )}
                  </>
                )}
              </section>
              )}

              {section === "group" && groupPane === "members" && (
              <section className="card">
                <div
                  className="section-header collapsible-header"
                  role="button"
                  tabIndex={0}
                  aria-expanded={membersExpanded}
                  onClick={() => setMembersExpanded((current) => !current)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setMembersExpanded((current) => !current);
                    }
                  }}
                >
                  <div className="collapsible-title">
                    <span
                      className={membersExpanded ? "chevron expanded" : "chevron"}
                      aria-hidden="true"
                    >
                      ›
                    </span>
                    <div>
                      <h2>{t("groupMembers")}</h2>
                      <span>
                        {group.members.length} {t("members")}
                      </span>
                    </div>
                  </div>
                  {isAdmin && (
                    <button
                      className="primary-button"
                      onClick={(event) => {
                        event.stopPropagation();
                        resetMemberForm();
                        setMembersExpanded(true);
                        setShowMemberForm(true);
                      }}
                    >
                      + {t("addVirtualMember")}
                    </button>
                  )}
                </div>
                {membersExpanded && (
                  <>
                    {showMemberForm && isAdmin && (
                      <form className="member-form" onSubmit={saveMember}>
                    <div className="form-row">
                      <label>
                        {t("name")}
                        <input
                          value={memberName}
                          onChange={(event) => setMemberName(event.target.value)}
                          disabled={Boolean(editingMember?.user_id)}
                          required
                        />
                      </label>
                      <label>
                        {t("playerRating")}
                        <input
                          type="number"
                          min={1}
                          max={5}
                          step={0.1}
                          value={memberRating}
                          onChange={(event) =>
                            setMemberRating(Number(event.target.value))
                          }
                        />
                      </label>
                      <label>
                        {t("goalkeeperRating")}
                        <input
                          type="number"
                          min={1}
                          max={5}
                          step={0.1}
                          value={memberGoalkeeperRating}
                          onChange={(event) =>
                            setMemberGoalkeeperRating(Number(event.target.value))
                          }
                        />
                      </label>
                    </div>
                    <div className="checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          checked={memberSubscriber}
                          onChange={(event) =>
                            setMemberSubscriber(event.target.checked)
                          }
                        />
                        {t("subscriber")}
                      </label>
                      {editingMember?.user_id && (
                        <label>
                          <input
                            type="checkbox"
                            checked={memberAdmin}
                            onChange={(event) =>
                              setMemberAdmin(event.target.checked)
                            }
                          />
                          {t("admin")}
                        </label>
                      )}
                    </div>
                    <div className="form-actions">
                      <button className="primary-button" type="submit">
                        {t("save")}
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={resetMemberForm}
                      >
                        {t("cancel")}
                      </button>
                    </div>
                      </form>
                    )}
                    <input
                      className="member-search"
                      type="search"
                      value={memberSearch}
                      placeholder={t("searchMembers")}
                      onChange={(event) => setMemberSearch(event.target.value)}
                    />
                    <div className="member-list">
                  {sortedGroupMembers.map((member) => {
                    return (
                      <div className="member-row" key={member.id}>
                        <div className="member-main">
                          <PlayerAvatar player={member} />
                          <div>
                            <strong>{member.name}</strong>
                            {member.user_id &&
                              member.full_name &&
                              member.full_name !== member.name && (
                                <div className="member-full-name">
                                  {member.full_name}
                                </div>
                              )}
                          <div className="member-details">
                            {t("playerRating")} {member.rating} ·{" "}
                            {t("goalkeeperRating")} {member.goalkeeper_rating}
                            {member.is_subscriber && ` · ${t("subscriber")}`}
                            {member.is_admin && ` · ${t("admin")}`}
                            {member.is_virtual && ` · ${t("virtual")}`}
                          </div>
                          </div>
                        </div>
                        <div className="member-actions">
                          {isAdmin && member.is_virtual && (
                            <>
                              <label className="secondary-button file-button">
                                {t("picture")}
                                <input
                                  type="file"
                                  accept="image/jpeg,image/png,image/webp"
                                  onChange={(event) => {
                                    const file = event.target.files?.[0];
                                    if (file) {
                                      saveAvatar(
                                        file,
                                        member,
                                        `groups/${group.id}/members/${member.id}/`,
                                        `/groups/${group.id}/members/${member.id}/avatar`
                                      );
                                    }
                                    event.currentTarget.value = "";
                                  }}
                                />
                              </label>
                              {member.avatar_path && (
                                <button
                                  className="text-danger-button"
                                  onClick={() =>
                                    clearAvatar(
                                      member,
                                      `/groups/${group.id}/members/${member.id}/avatar`
                                    )
                                  }
                                >
                                  {t("removePicture")}
                                </button>
                              )}
                            </>
                          )}
                          {isAdmin && (
                            <>
                              <button
                                className="secondary-button"
                                onClick={() => startEditMember(member)}
                              >
                                {t("editMember")}
                              </button>
                              <button
                                className="text-danger-button"
                                onClick={async () => {
                                  if (window.confirm(t("deleteConfirm"))) {
                                    if (member.avatar_path) {
                                      await clearAvatar(
                                        member,
                                        `/groups/${group.id}/members/${member.id}/avatar`
                                      );
                                    }
                                    runAction(
                                      () =>
                                        apiFetch(
                                          `/groups/${group.id}/members/${member.id}`,
                                          { method: "DELETE" }
                                        )
                                    ).then(() => {
                                      setGroup((current) => {
                                        if (!current) return current;
                                        return {
                                          ...current,
                                          members: current.members.filter(
                                            (item) => item.id !== member.id
                                          ),
                                          game_day: current.game_day
                                            ? {
                                                ...current.game_day,
                                                participants:
                                                  current.game_day.participants.filter(
                                                    (item) => item.id !== member.id
                                                  ),
                                                waiting_list:
                                                  current.game_day.waiting_list.filter(
                                                    (item) => item.id !== member.id
                                                  ),
                                              }
                                            : null,
                                        };
                                      });
                                    });
                                  }
                                }}
                              >
                                {t("deleteMember")}
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                    </div>
                  </>
                )}
              </section>
              )}

              {section === "game" &&
                gamePane === "registration" &&
                gameDay &&
                gameDay.status === "upcoming" && (
                <section className="card group-page-only">
                  <h2>{t("gameRegistration")}</h2>
                  {currentMembership && (
                    <div className="form-actions">
                      <button
                        className={
                          registrationState === "out"
                            ? "primary-button"
                            : "secondary-button"
                        }
                        onClick={() =>
                          setGameDayRegistration(
                            currentMembership.id,
                            registrationState === "out"
                          )
                        }
                      >
                        {registrationState === "out"
                          ? t("register")
                          : t("leaveGameDay")}
                      </button>
                    </div>
                  )}
                  <div className="registration-columns">
                    <div>
                      <h3>{t("registeredPlayers")}</h3>
                      {gameDay.participants.map((player, index) => (
                        <div className="member-row" key={player.id}>
                          <span className="player-identity">
                            <PlayerAvatar player={player} size="small" />
                            {index + 1}. {playerName(player)}
                          </span>
                          {(isAdmin && player.is_guest) ||
                          (isAdmin && player.id !== currentMembership?.id) ? (
                            <div className="member-actions">
                              {isAdmin && !player.is_guest && (
                                <button
                                  className="secondary-button"
                                  onClick={() =>
                                    setGameDayRegistration(player.id, false)
                                  }
                                >
                                  {t("leaveGameDay")}
                                </button>
                              )}
                              {isAdmin && player.is_guest && (
                                <>
                                  <label className="secondary-button file-button">
                                    {t("picture")}
                                    <input
                                      type="file"
                                      accept="image/jpeg,image/png,image/webp"
                                      onChange={(event) => {
                                        const file = event.target.files?.[0];
                                        if (file) {
                                          saveAvatar(
                                            file,
                                            player,
                                            `groups/${group.id}/members/${player.id}/`,
                                            `/groups/${group.id}/members/${player.id}/avatar`
                                          );
                                        }
                                        event.currentTarget.value = "";
                                      }}
                                    />
                                  </label>
                                  <button
                                    className="secondary-button"
                                    onClick={() => startEditGuest(player)}
                                  >
                                    {t("editMember")}
                                  </button>
                                  <button
                                    className="text-danger-button"
                                    onClick={() => removeGuest(player)}
                                  >
                                    {t("removeGuest")}
                                  </button>
                                </>
                              )}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                    <div>
                      <h3>{t("waitingList")}</h3>
                      {gameDay.waiting_list.map((player, index) => (
                        <div className="member-row" key={player.id}>
                          <span className="player-identity">
                            <PlayerAvatar player={player} size="small" />
                            {index + 1}. {playerName(player)}
                          </span>
                          {isAdmin && player.id !== currentMembership?.id && (
                            <div className="member-actions">
                              {player.is_guest ? (
                                <button
                                  className="text-danger-button"
                                  onClick={() => removeGuest(player)}
                                >
                                  {t("removeGuest")}
                                </button>
                              ) : (
                                <button
                                  className="secondary-button"
                                  onClick={() =>
                                    setGameDayRegistration(player.id, false)
                                  }
                                >
                                  {t("leaveGameDay")}
                                </button>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                  {isAdmin &&
                    group.members.some(
                      (member) =>
                        member.id !== currentMembership?.id &&
                        !gameDay.participants.some(
                          (player) => player.id === member.id
                        ) &&
                        !gameDay.waiting_list.some(
                          (player) => player.id === member.id
                        )
                    ) && (
                    <div className="registration-available">
                      <h3>{t("notRegistered")}</h3>
                      {group.members
                        .filter(
                          (member) =>
                            member.id !== currentMembership?.id &&
                            !gameDay.participants.some(
                              (player) => player.id === member.id
                            ) &&
                            !gameDay.waiting_list.some(
                              (player) => player.id === member.id
                            )
                        )
                        .map((member) => (
                          <div className="member-row" key={member.id}>
                            <span className="player-identity">
                              <PlayerAvatar player={member} size="small" />
                              {member.name}
                            </span>
                            <button
                              className="secondary-button"
                              onClick={() =>
                                setGameDayRegistration(member.id, true)
                              }
                            >
                              {t("register")}
                            </button>
                          </div>
                        ))}
                    </div>
                  )}
                  {registrationCta && (
                    <div className="registration-generate">
                      <p className="registration-ready-note">
                        <bdi>
                          {registrationCta.registered}/{registrationCta.capacity}
                        </bdi>
                        <span>{t("playersReady")}</span>
                        <span aria-hidden="true">✓</span>
                      </p>
                      <button
                        className="primary-button"
                        type="button"
                        onClick={() => void generateCurrentTeams()}
                      >
                        {t("generateTeams")}
                      </button>
                    </div>
                  )}
                </section>
              )}

              {section === "game" && gamePane === "teams" && !gameDay && (
                <section className="card">
                  <h2>{t("teams")}</h2>
                  <p>
                    {t(guideDetailLabel(guide.detail)).replace(
                      "{count}",
                      String(guide.spotsRemaining)
                    )}
                  </p>
                </section>
              )}

              {section === "game" && gamePane === "teams" && gameDay && (
                <section className="card">
                  <h2>{t("generateTeams")}</h2>
                  {isAdmin && registrationReady && (
                    <button
                      className="primary-button"
                      onClick={() => void generateCurrentTeams()}
                    >
                      {t("generateTeams")}
                    </button>
                  )}
                  {isAdmin && !registrationReady && (
                    <div className="status-box pending">
                      <p>
                        {t(guideDetailLabel(guide.detail)).replace(
                          "{count}",
                          String(guide.spotsRemaining)
                        )}
                      </p>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={() => setGamePane("registration")}
                      >
                        {t("goToRegistration")}
                      </button>
                    </div>
                  )}
                  {gameDay.teams.length > 0 && isAdmin && (
                    <div className="team-edit-toolbar">
                      {!editingTeams ? (
                        <button
                          className="secondary-button"
                          onClick={() => {
                            setTeamAdjustmentError("");
                            setEditingTeams(true);
                          }}
                        >
                          {t("adjustTeams")}
                        </button>
                      ) : (
                        <>
                          <button
                            className="primary-button"
                            onClick={saveTeamAdjustments}
                          >
                            {t("saveAdjustments")}
                          </button>
                          <button
                            className="secondary-button"
                            onClick={() => {
                              setTeamAdjustmentError("");
                              setEditingTeams(false);
                            }}
                          >
                            {t("cancel")}
                          </button>
                        </>
                      )}
                      {teamAdjustmentError && (
                        <div className="error-box team-adjustment-error">
                          {teamAdjustmentError}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="teams-grid">
                    {gameDay.teams.map((team) => (
                      <div className="team-box" key={team.name}>
                        <div className="team-header">
                          <h3>{currentTeamLabel(team.name)}</h3>
                          <span
                            className={
                              editingTeams &&
                              draftTeamSize(team.name) !==
                                gameDay.players_per_team
                                ? "invalid-team-count"
                                : undefined
                            }
                          >
                            {editingTeams
                              ? draftTeamSize(team.name)
                              : team.players.length}
                            /{gameDay.players_per_team}
                          </span>
                        </div>
                        {isAdmin && !editingTeams && (
                          <label className="team-captain-select">
                            {t("captain")}
                            <select
                              value={team.captain_id ?? ""}
                              onChange={(event) =>
                                runAction(() =>
                                  apiFetch(
                                    `/groups/${group.id}/game-days/${gameDay.id}/captain`,
                                    {
                                      method: "PUT",
                                      headers: {
                                        "Content-Type": "application/json",
                                      },
                                      body: JSON.stringify({
                                        team_name: team.name,
                                        membership_id: event.target.value || null,
                                      }),
                                    }
                                  )
                                ).catch(() => undefined)
                              }
                            >
                              <option value="">{t("noCaptain")}</option>
                              {team.players.map((player) => (
                                <option key={player.id} value={player.id}>
                                  {playerName(player)}
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        {(editingTeams
                          ? gameDay.participants.filter(
                              (player) => teamDraft[player.id] === team.name
                            )
                          : team.players
                        ).map((player) =>
                          editingTeams ? (
                            <div className="team-player-edit-row" key={player.id}>
                              <span>
                                {playerName(player)} ({playerRatings(player)})
                              </span>
                              <select
                                value={teamDraft[player.id] ?? ""}
                                onChange={(event) =>
                                  updateTeamDraft(player.id, event.target.value)
                                }
                              >
                                <option value="">{t("unassigned")}</option>
                                {teamNames.map((name) => (
                                  <option key={name} value={name}>
                                    {currentTeamLabel(name)}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ) : (
                            <p className="player-identity" key={player.id}>
                              <PlayerAvatar player={player} size="small" />
                              <span>
                                {playerName(player)} ({playerRatings(player)})
                              {player.id === team.captain_id && (
                                <span className="captain-badge">
                                  {t("captain")}
                                </span>
                              )}
                              </span>
                            </p>
                          )
                        )}
                      </div>
                    ))}
                    {(gameDay.unassigned.length > 0 || editingTeams) && (
                      <div className="team-box">
                        <div className="team-header">
                          <h3>{t("unassigned")}</h3>
                        </div>
                        {(editingTeams
                          ? gameDay.participants.filter(
                              (player) => !teamDraft[player.id]
                            )
                          : gameDay.unassigned
                        ).map((player) =>
                          editingTeams ? (
                            <div className="team-player-edit-row" key={player.id}>
                              <span>
                                {playerName(player)} ({playerRatings(player)})
                              </span>
                              <select
                                value={teamDraft[player.id] ?? ""}
                                onChange={(event) =>
                                  updateTeamDraft(player.id, event.target.value)
                                }
                              >
                                <option value="">{t("unassigned")}</option>
                                {teamNames.map((name) => (
                                  <option key={name} value={name}>
                                    {currentTeamLabel(name)}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ) : (
                            <p className="player-identity" key={player.id}>
                              <PlayerAvatar player={player} size="small" />
                              <span>
                                {playerName(player)} ({playerRatings(player)})
                              </span>
                            </p>
                          )
                        )}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {section === "game" && gamePane === "matches" && isLive && gameDay && (
                <section className="card">
                  <h2>{t("matches")}</h2>
                  {isAdmin && teamNames.length >= 2 && (
                    <div className="form-panel">
                      <div className="form-row">
                        <label>
                          {t("homeTeam")}
                          <select
                            value={homeTeam}
                            onChange={(event) => setHomeTeam(event.target.value)}
                          >
                            <option value="">—</option>
                            {teamNames.map((name) => (
                              <option key={name} value={name}>
                                {currentTeamLabel(name)}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          {t("awayTeam")}
                          <select
                            value={awayTeam}
                            onChange={(event) => setAwayTeam(event.target.value)}
                          >
                            <option value="">—</option>
                            {teamNames.map((name) => (
                              <option key={name} value={name}>
                                {currentTeamLabel(name)}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <button
                        className="primary-button"
                        disabled={!homeTeam || !awayTeam || homeTeam === awayTeam}
                        onClick={() =>
                          runAction(() =>
                            apiFetch(
                              `/groups/${group.id}/game-days/${gameDay.id}/matches`,
                              {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                  home_team_name: homeTeam,
                                  away_team_name: awayTeam,
                                }),
                              }
                            )
                          )
                        }
                      >
                        {t("startMatch")}
                      </button>
                    </div>
                  )}
                  {[...gameDay.matches].reverse().map((match) => {
                    const isEditing = editingMatches.has(match.id);
                    const isAdjustingLineup = adjustingLineups.has(match.id);
                    const isEditable =
                      isAdmin &&
                      isLive &&
                      (match.status !== "completed" || isEditing);
                    const showReadOnlyResult =
                      match.status === "completed" && !isEditing;
                    const showLineupEditor =
                      isEditable && (isEditing || isAdjustingLineup);
                    const drafts = isEditable ? (goalDrafts[match.id] ?? []) : [];
                    const permanentTeams = permanentTeamByMember(gameDay);
                    const lineupDraft =
                      lineupDrafts[match.id] ??
                      (showLineupEditor
                        ? lineupDraftFromPlayers(match.players)
                        : undefined);
                    const lineupPlayers = lineupPlayersForGoals(
                      isEditing || isAdjustingLineup ? lineupDraft : undefined,
                      match.players,
                      gameDay.participants
                    );
                    const homeLineup = lineupPlayers.filter(
                      (player) => player.team_name === match.home_team_name
                    );
                    const awayLineup = lineupPlayers.filter(
                      (player) => player.team_name === match.away_team_name
                    );
                    const assignedIds = new Set(lineupPlayers.map((player) => player.id));
                    const availablePlayers = gameDay.participants.filter(
                      (player) => !assignedIds.has(player.id)
                    );
                    const displayScore = showReadOnlyResult
                      ? {
                          home: match.home_score ?? 0,
                          away: match.away_score ?? 0,
                        }
                      : scoreFromGoalDrafts(
                          drafts,
                          match.home_team_name,
                          match.away_team_name
                        );
                    const discardMatchEdits = () => {
                      setGoalDrafts((previous) => {
                        const next = { ...previous };
                        delete next[match.id];
                        return next;
                      });
                      setLineupDrafts((previous) => {
                        const next = { ...previous };
                        delete next[match.id];
                        return next;
                      });
                      setEditingMatches((previous) => {
                        const next = new Set(previous);
                        next.delete(match.id);
                        return next;
                      });
                      setAdjustingLineups((previous) => {
                        const next = new Set(previous);
                        next.delete(match.id);
                        return next;
                      });
                    };
                    const updateLineupDraft = (nextLineup: LineupDraftItem[]) => {
                      setLineupDrafts((previous) => ({
                        ...previous,
                        [match.id]: nextLineup,
                      }));
                    };
                    const addPlayerToSide = (
                      membershipId: string,
                      teamName: string
                    ) => {
                      const current = lineupDraft ?? [];
                      updateLineupDraft([
                        ...current.filter(
                          (item) => item.membership_id !== membershipId
                        ),
                        { membership_id: membershipId, team_name: teamName },
                      ]);
                    };
                    const removePlayerFromLineup = (membershipId: string) => {
                      const current = lineupDraft ?? [];
                      updateLineupDraft(
                        current.filter(
                          (item) => item.membership_id !== membershipId
                        )
                      );
                      setGoalDrafts((previous) => ({
                        ...previous,
                        [match.id]: clearGoalDraftPlayerReferences(
                          previous[match.id] ?? [],
                          membershipId
                        ),
                      }));
                    };
                    const movePlayerToSide = (
                      membershipId: string,
                      teamName: string
                    ) => {
                      const current = lineupDraft ?? [];
                      const previousSide = current.find(
                        (item) => item.membership_id === membershipId
                      )?.team_name;
                      updateLineupDraft(
                        current.map((item) =>
                          item.membership_id === membershipId
                            ? { ...item, team_name: teamName }
                            : item
                        )
                      );
                      if (previousSide && previousSide !== teamName) {
                        setGoalDrafts((previous) => ({
                          ...previous,
                          [match.id]: clearGoalDraftPlayerReferences(
                            previous[match.id] ?? [],
                            membershipId,
                            previousSide
                          ),
                        }));
                      }
                    };
                    const saveLineup = async () => {
                      await runAction(() =>
                        apiFetch(
                          `/groups/${group.id}/matches/${match.id}/lineup`,
                          {
                            method: "PUT",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                              players: buildLineupPayload(lineupDraft ?? []),
                            }),
                          }
                        )
                      );
                      setLineupDrafts((previous) => {
                        const next = { ...previous };
                        delete next[match.id];
                        return next;
                      });
                      setAdjustingLineups((previous) => {
                        const next = new Set(previous);
                        next.delete(match.id);
                        return next;
                      });
                    };
                    const saveMatch = async () => {
                      if (
                        match.status === "open" &&
                        lineupDraftIsDirty(lineupDrafts[match.id], match.players)
                      ) {
                        setError(t("lineupSaveFirst"));
                        return;
                      }
                      const payload: {
                        goals: ReturnType<typeof buildCompleteGoalsPayload>;
                        players?: ReturnType<typeof buildLineupPayload>;
                      } = {
                        goals: buildCompleteGoalsPayload(drafts),
                      };
                      if (isEditing) {
                        payload.players = buildLineupPayload(lineupDraft ?? []);
                      }
                      await runAction(() =>
                        apiFetch(
                          `/groups/${group.id}/matches/${match.id}/complete`,
                          {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify(payload),
                          }
                        )
                      );
                      discardMatchEdits();
                    };
                    const otherTeamName = (side: string) =>
                      side === match.home_team_name
                        ? match.away_team_name
                        : match.home_team_name;
                    const renderLineupPlayer = (
                      player: Member,
                      currentSide: string
                    ) => {
                      const permanentTeam = permanentTeams[player.id];
                      const isBorrowed =
                        Boolean(permanentTeam) && permanentTeam !== currentSide;
                      const destination = otherTeamName(currentSide);
                      return (
                        <div className="match-lineup-row" key={player.id}>
                          <div className="match-lineup-row-main">
                            <PlayerAvatar player={player} size="small" />
                            <span className="match-lineup-name">
                              {playerName(player)}
                            </span>
                            {isBorrowed && permanentTeam && (
                              <span className="match-lineup-borrowed">
                                {t("normally")} {currentTeamLabel(permanentTeam)}
                              </span>
                            )}
                          </div>
                          {showLineupEditor && (
                            <div className="match-lineup-row-actions">
                              <button
                                className="secondary-button match-lineup-move"
                                type="button"
                                onClick={() =>
                                  movePlayerToSide(player.id, destination)
                                }
                              >
                                {t("moveTo")} {currentTeamLabel(destination)}
                              </button>
                              <button
                                className="match-lineup-remove text-danger-button"
                                type="button"
                                onClick={() => removePlayerFromLineup(player.id)}
                              >
                                {t("removePlayer")}
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    };
                    const renderAvailablePlayer = (player: Member) => {
                      const permanentTeam = permanentTeams[player.id];
                      return (
                        <div className="match-lineup-row" key={player.id}>
                          <div className="match-lineup-row-main">
                            <PlayerAvatar player={player} size="small" />
                            <span className="match-lineup-name">
                              {playerName(player)}
                            </span>
                            <span className="match-lineup-badge">
                              {permanentTeam
                                ? currentTeamLabel(permanentTeam)
                                : t("unassigned")}
                            </span>
                          </div>
                          <div className="match-lineup-row-actions">
                            <button
                              className="secondary-button match-lineup-add"
                              type="button"
                              onClick={() =>
                                addPlayerToSide(player.id, match.home_team_name)
                              }
                            >
                              + {currentTeamLabel(match.home_team_name)}
                            </button>
                            <button
                              className="secondary-button match-lineup-add"
                              type="button"
                              onClick={() =>
                                addPlayerToSide(player.id, match.away_team_name)
                              }
                            >
                              + {currentTeamLabel(match.away_team_name)}
                            </button>
                          </div>
                        </div>
                      );
                    };
                    const renderLineupTeams = () => (
                      <div className="match-lineup-columns">
                        <div className="match-lineup-side match-lineup-side-home">
                          <h5 className="match-lineup-side-title">
                            {currentTeamLabel(match.home_team_name)} (
                            {homeLineup.length})
                          </h5>
                          {homeLineup.map((player) =>
                            renderLineupPlayer(player, match.home_team_name)
                          )}
                        </div>
                        <div className="match-lineup-side match-lineup-side-away">
                          <h5 className="match-lineup-side-title">
                            {currentTeamLabel(match.away_team_name)} (
                            {awayLineup.length})
                          </h5>
                          {awayLineup.map((player) =>
                            renderLineupPlayer(player, match.away_team_name)
                          )}
                        </div>
                      </div>
                    );
                    return (
                      <div className="team-box" key={match.id}>
                        <h3>
                          {currentTeamLabel(match.home_team_name)} vs{" "}
                          {currentTeamLabel(match.away_team_name)}
                        </h3>
                        <p className="match-score">
                          {displayScore.home} - {displayScore.away}
                        </p>
                        {showReadOnlyResult && (
                          <>
                            {isAdmin && (
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() => {
                                  setGoalDrafts((previous) => ({
                                    ...previous,
                                    [match.id]: goalDraftsFromMatch(match.goals),
                                  }));
                                  setLineupDrafts((previous) => ({
                                    ...previous,
                                    [match.id]: lineupDraftFromPlayers(
                                      match.players
                                    ),
                                  }));
                                  setEditingMatches(
                                    (previous) => new Set([...previous, match.id])
                                  );
                                }}
                              >
                                {t("editMatch")}
                              </button>
                            )}
                            {match.goals.map((goal) => (
                              <p className="goal-player-line" key={goal.id}>
                                {currentTeamLabel(goal.team_name)}:{" "}
                                {goal.scorer ? (
                                  <span className="player-identity">
                                    <PlayerAvatar player={goal.scorer} size="small" />
                                    {playerName(goal.scorer)}
                                  </span>
                                ) : (
                                  t("unknownScorer")
                                )}
                                {goal.assist
                                  ? ` (${playerName(goal.assist)})`
                                  : ""}
                              </p>
                            ))}
                          </>
                        )}
                        {isEditable && match.status === "open" && !isAdjustingLineup && (
                          <button
                            className="secondary-button"
                            type="button"
                            onClick={() => {
                              setLineupDrafts((previous) => ({
                                ...previous,
                                [match.id]: lineupDraftFromPlayers(match.players),
                              }));
                              setAdjustingLineups(
                                (previous) => new Set([...previous, match.id])
                              );
                            }}
                          >
                            {t("adjustMatchLineups")}
                          </button>
                        )}
                        {showLineupEditor && (
                          <div className="match-lineup-editor">
                            <h4 className="match-lineup-title">
                              {t("matchLineup")}
                            </h4>
                            <p className="muted-text match-lineup-intro">
                              {t("matchLineupHint")}
                            </p>
                            {renderLineupTeams()}
                            <div className="match-lineup-pool">
                              <h5 className="match-lineup-pool-title">
                                {t("availablePlayers")}
                              </h5>
                              {availablePlayers.map((player) =>
                                renderAvailablePlayer(player)
                              )}
                            </div>
                            {match.status === "open" && isAdjustingLineup && (
                              <div className="form-actions match-lineup-actions">
                                <button
                                  className="secondary-button"
                                  type="button"
                                  onClick={() => {
                                    setLineupDrafts((previous) => {
                                      const next = { ...previous };
                                      delete next[match.id];
                                      return next;
                                    });
                                    setAdjustingLineups((previous) => {
                                      const next = new Set(previous);
                                      next.delete(match.id);
                                      return next;
                                    });
                                  }}
                                >
                                  {t("cancelEdit")}
                                </button>
                                <button
                                  className="primary-button"
                                  type="button"
                                  onClick={saveLineup}
                                >
                                  {t("saveLineups")}
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                        {isEditable && (
                          <>
                            {drafts.map((goal, index) => {
                              const teamPlayers = goal.team
                                ? lineupPlayers.filter(
                                    (player) => player.team_name === goal.team
                                  )
                                : [];
                              const assistOptions = teamPlayers.filter(
                                (player) => player.id !== goal.scorer
                              );
                              return (
                                <div className="form-row goal-row" key={index}>
                                  <label>
                                    {t("scoringTeam")}
                                    <select
                                      value={goal.team}
                                      onChange={(event) =>
                                        setGoalDrafts((previous) => {
                                          const next = [
                                            ...(previous[match.id] ?? []),
                                          ];
                                          next[index] = {
                                            team: event.target.value,
                                            scorer: "",
                                            assist: "",
                                          };
                                          return {
                                            ...previous,
                                            [match.id]: next,
                                          };
                                        })
                                      }
                                    >
                                      <option value="">—</option>
                                      <option value={match.home_team_name}>
                                        {currentTeamLabel(match.home_team_name)}
                                      </option>
                                      <option value={match.away_team_name}>
                                        {currentTeamLabel(match.away_team_name)}
                                      </option>
                                    </select>
                                  </label>
                                  <label>
                                    {t("scorer")}
                                    <select
                                      value={goal.scorer}
                                      disabled={!goal.team}
                                      onChange={(event) =>
                                        setGoalDrafts((previous) => {
                                          const next = [
                                            ...(previous[match.id] ?? []),
                                          ];
                                          const picked = event.target.value;
                                          next[index] = {
                                            ...goal,
                                            scorer: picked,
                                            assist:
                                              picked && goal.assist === picked
                                                ? ""
                                                : goal.assist,
                                          };
                                          return {
                                            ...previous,
                                            [match.id]: next,
                                          };
                                        })
                                      }
                                    >
                                      <option value="">{t("noScorer")}</option>
                                      {teamPlayers.map((player) => (
                                        <option key={player.id} value={player.id}>
                                          {playerName(player)}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                  <label>
                                    {t("assist")}
                                    <select
                                      value={goal.assist}
                                      disabled={!goal.team}
                                      onChange={(event) =>
                                        setGoalDrafts((previous) => {
                                          const next = [
                                            ...(previous[match.id] ?? []),
                                          ];
                                          next[index] = {
                                            ...goal,
                                            assist: event.target.value,
                                          };
                                          return {
                                            ...previous,
                                            [match.id]: next,
                                          };
                                        })
                                      }
                                    >
                                      <option value="">{t("noAssist")}</option>
                                      {assistOptions.map((player) => (
                                        <option key={player.id} value={player.id}>
                                          {playerName(player)}
                                        </option>
                                      ))}
                                    </select>
                                  </label>
                                  <button
                                    className="text-danger-button"
                                    type="button"
                                    onClick={() =>
                                      setGoalDrafts((previous) => ({
                                        ...previous,
                                        [match.id]: (
                                          previous[match.id] ?? []
                                        ).filter((_, at) => at !== index),
                                      }))
                                    }
                                  >
                                    {t("removeGoal")}
                                  </button>
                                </div>
                              );
                            })}
                            <div className="form-actions">
                              <button
                                className="secondary-button"
                                type="button"
                                onClick={() =>
                                  setGoalDrafts((previous) => ({
                                    ...previous,
                                    [match.id]: [
                                      ...(previous[match.id] ?? []),
                                      { team: "", scorer: "", assist: "" },
                                    ],
                                  }))
                                }
                              >
                                {t("addGoal")}
                              </button>
                              {isEditing && (
                                <button
                                  className="secondary-button"
                                  type="button"
                                  onClick={discardMatchEdits}
                                >
                                  {t("cancelEdit")}
                                </button>
                              )}
                              <button
                                className="primary-button"
                                type="button"
                                onClick={saveMatch}
                              >
                                {t("completeMatch")}
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    );
                  })}
                </section>
              )}

              {section === "game" && gamePane === "matches" && !isLive && (
                <section className="card">
                  <h2>{t("matches")}</h2>
                  <p>
                    {t(guideDetailLabel(guide.detail)).replace(
                      "{count}",
                      String(guide.spotsRemaining)
                    )}
                  </p>
                </section>
              )}

              {section === "game" &&
                gamePane === "matches" &&
                gameDay &&
                !gameDay.is_rotating &&
                gameDay.standings.length > 0 && (
                <section className="card">
                  <h2>{t("standings")}</h2>
                  {standingsTable(gameDay.standings, currentTeamNames)}
                </section>
              )}

              {section === "stats" && finishedGameDay && (
                <section className="card celebration-card">
                  {!finishedGameDay.is_rotating &&
                    finishedGameDay.champion_team_name && (
                      <>
                        <div className="trophy" aria-hidden="true">
                          🏆
                        </div>
                        <h2>
                          {finishedGameDay.awards.champions.length > 1
                            ? t("coChampions")
                            : t("champion")}
                          :{" "}
                          {championLabel(
                            finishedTeamNames,
                            finishedGameDay.champion_team_name
                          )}
                        </h2>
                        {finishedGameDay.awards.champions.length > 0 && (
                          <div className="champion-squad player-list-inline">
                            {finishedGameDay.awards.champions.map((item) => (
                              <span className="player-identity" key={item.id}>
                                <PlayerAvatar player={item} size="small" />
                                {item.name}
                              </span>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  {finishedGameDay.standings.length > 0 && (
                    standingsTable(finishedGameDay.standings, finishedTeamNames)
                  )}
                  {finishedGameDay.mvp_announced ? (
                    <div className="player-list-inline">
                      {finishedGameDay.awards.mvps.length > 1
                        ? t("coMvps")
                        : t("mvpAnnounced")}
                      :{" "}
                      {finishedGameDay.awards.mvps.map((item) => (
                        <span className="player-identity" key={item.id}>
                          <PlayerAvatar player={item} size="small" />
                          {item.name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <>
                      <h2>{t("mvpVoting")}</h2>
                      <p className="muted-text">{t("waitingForVotes")}</p>
                      <p className="muted-text">
                        {finishedGameDay.votes_cast}/
                        {finishedGameDay.eligible_voters}
                      </p>
                      {finishedGameDay.my_vote && <p>{t("youVoted")}</p>}
                      {viewerCanVote && (
                        <button
                          className="primary-button"
                          type="button"
                          onClick={openMvpVote}
                        >
                          {t("voteMvp")}
                        </button>
                      )}
                      {!viewerCanVote && (
                        <p className="muted-text">{t("flowDetailNotEligible")}</p>
                      )}
                      {isAdmin && (
                        <button
                          className="secondary-button"
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/game-days/${finishedGameDay.id}/mvp/close`,
                                { method: "POST" }
                              )
                            )
                          }
                        >
                          {t("closeVoting")}
                        </button>
                      )}
                    </>
                  )}
                </section>
              )}

              {section === "group" && groupPane === "ratings" && (
              <section className="card">
                <h2>{t("ratingSurvey")}</h2>
                {group.survey?.status === "open" ? (
                  <>
                    <p>{t("surveyOpen")}</p>
                    {surveyEligibleMembers.length === 0 ? (
                      <p className="empty-state">{t("noEligibleSurveyMembers")}</p>
                    ) : (
                      <div className="survey-list">
                        {surveyEligibleMembers.map((member) => (
                          <div className="survey-row" key={member.id}>
                            <span className="survey-name player-identity">
                              <PlayerAvatar player={member} />
                              {member.name}
                            </span>
                            <div className="survey-ratings">
                              <div className="survey-rating-field">
                                <span>{t("playerRating")}</span>
                                <StarRating
                                  label={`${member.name} ${t("playerRating")}`}
                                  // Fall back to what was already submitted, so
                                  // reopening the survey is an edit, not a reset.
                                  value={surveyRatingValue(member.id, "rating")}
                                  onChange={(value) =>
                                    setSurveyDraft((previous) => ({
                                      ...previous,
                                      [member.id]: {
                                        ...previous[member.id],
                                        rating: value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                              <div className="survey-rating-field">
                                <span>{t("goalkeeperRating")}</span>
                                <StarRating
                                  label={`${member.name} ${t("goalkeeperRating")}`}
                                  value={surveyRatingValue(
                                    member.id,
                                    "goalkeeper_rating"
                                  )}
                                  onChange={(value) =>
                                    setSurveyDraft((previous) => ({
                                      ...previous,
                                      [member.id]: {
                                        ...previous[member.id],
                                        goalkeeper_rating: value,
                                      },
                                    }))
                                  }
                                />
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="form-actions">
                      {surveyEligibleMembers.length > 0 && (
                        <button
                          className="primary-button"
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/surveys/${group.survey!.id}/ratings`,
                                {
                                  method: "POST",
                                  headers: { "Content-Type": "application/json" },
                                  body: JSON.stringify({
                                    ratings: completedSurveyRatings,
                                  }),
                                }
                              )
                            )
                          }
                        >
                          {t("submitRatings")}
                        </button>
                      )}
                      {isAdmin && (
                        <button
                          className="secondary-button"
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/surveys/${group.survey!.id}/close`,
                                { method: "POST" }
                              )
                            )
                          }
                        >
                          {t("closeSurvey")}
                        </button>
                      )}
                    </div>
                  </>
                ) : (
                  <>
                    {group.survey?.status === "closed" && (
                      <p>{t("surveyClosed")}</p>
                    )}
                    {isAdmin && (
                      <button
                        className="primary-button"
                        onClick={() =>
                          runAction(() =>
                            apiFetch(`/groups/${group.id}/surveys`, {
                              method: "POST",
                            })
                          )
                        }
                      >
                        {t("startSurvey")}
                      </button>
                    )}
                  </>
                )}
              </section>
              )}

              {section === "stats" && group.history.length > 0 && (
                <section className="card group-page-only">
                  <h2>{t("history")}</h2>
                  {group.history.map((item) => (
                    <div className="history-profile-row" key={item.id}>
                      <p>
                        {new Date(item.game_datetime).toLocaleString()}
                      </p>
                      {item.awards.champions.length > 0 && (
                        <div className="history-award">
                          <p className="history-award-label">
                            🏆 {t("championPlayers")}
                          </p>
                          <div className="history-award-players">
                            {item.awards.champions.map((player) => (
                              <span className="player-identity" key={`champion-${player.id}`}>
                                <PlayerAvatar player={player} size="small" />
                                {player.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {item.awards.mvps.length > 0 && (
                        <div className="history-award">
                          <p className="history-award-label">
                            ⭐ {t("mvpAnnounced")}
                          </p>
                          <div className="history-award-players">
                            {item.awards.mvps.map((player) => (
                              <span className="player-identity" key={`mvp-${player.id}`}>
                                <PlayerAvatar player={player} size="small" />
                                {player.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </section>
              )}
            </>
          )}
        </main>
      </div>
      {mvpVoteOpen && finishedGameDay && group && (
        <div
          className="mvp-modal-backdrop"
          onClick={() => setMvpVoteOpen(false)}
        >
          <div
            className="mvp-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mvp-vote-title"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 id="mvp-vote-title">{t("voteMvp")}</h2>
            {finishedGameDay.my_vote && (
              <p className="status-box approved">{t("youVoted")}</p>
            )}
            <p className="muted-text">
              {finishedGameDay.votes_cast}/{finishedGameDay.eligible_voters}
            </p>
            {mvpBallot.length === 0 ? (
              <p>{t("noMvpCandidates")}</p>
            ) : (
              <div className="mvp-candidates">
                {mvpBallot.map((player) => (
                  <label className="mvp-candidate" key={player.id}>
                    <input
                      type="radio"
                      name="mvp-candidate"
                      value={player.id}
                      checked={mvpChoice === player.id}
                      onChange={() => setMvpChoice(player.id)}
                    />
                    <PlayerAvatar player={player} size="small" />
                    <span>{playerName(player)}</span>
                  </label>
                ))}
              </div>
            )}
            <div className="form-actions">
              <button
                className="primary-button"
                type="button"
                disabled={!mvpChoice || mvpBallot.length === 0}
                onClick={() =>
                  runAction(() =>
                    apiFetch(
                      `/groups/${group.id}/game-days/${finishedGameDay.id}/mvp`,
                      {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          nominee_membership_id: mvpChoice,
                        }),
                      }
                    )
                  )
                }
              >
                {finishedGameDay.my_vote ? t("updateVote") : t("submitVote")}
              </button>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setMvpVoteOpen(false)}
              >
                {t("cancel")}
              </button>
            </div>
          </div>
        </div>
      )}
      <nav className="bottom-nav" aria-label={t("appName")}>
        {(
          [
            ["home", t("navHome")],
            ["game", t("gameDay")],
            ["group", t("navGroup")],
            ["stats", t("navStats")],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={section === key ? "bottom-nav-button active" : "bottom-nav-button"}
            aria-current={section === key ? "page" : undefined}
            onClick={() => openSection(key)}
          >
            {label}
          </button>
        ))}
      </nav>
    </div>
    </ReigningTitlesProvider>
  );
}

export default App;
