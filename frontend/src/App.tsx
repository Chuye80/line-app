import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { Session } from "@supabase/supabase-js";
import "./App.css";
import { supabase } from "./supabase";
import { translations, type Language } from "./i18n";

const API_URL = "http://127.0.0.1:8000";
const LANG_KEY = "lineapp.lang";

type Member = {
  id: string;
  user_id: string | null;
  name: string;
  rating: number;
  is_subscriber: boolean;
  is_admin: boolean;
  is_virtual: boolean;
  team_name?: string;
};

type Team = {
  name: string;
  players: Member[];
  total_rating: number;
  average_rating: number;
};

type MatchGoal = {
  id: string;
  scorer: Member;
  assist: Member | null;
};

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
  my_ratings: Record<string, number>;
};

type Group = {
  id: string;
  name: string;
  last_participant_count: number;
  last_players_per_team: number;
  members: Member[];
  game_day: GameDay | null;
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
  status: string;
};

type StatRow = Member & {
  game_days_played: number;
  matches_played: number;
  championships: number;
  goals: number;
  assists: number;
  mvp_titles: number;
};

function loadLang(): Language {
  const saved = localStorage.getItem(LANG_KEY);
  return saved === "he" ? "he" : "en";
}

function toLocalIso(date: string, time: string) {
  return new Date(`${date}T${time}`).toISOString();
}

function App() {
  const [lang, setLang] = useState<Language>(loadLang);
  const t = (key: string) => translations[lang][key] ?? key;

  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [isDeveloper, setIsDeveloper] = useState(false);

  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

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
  const [tab, setTab] = useState<"group" | "stats">("group");

  const [newGroupName, setNewGroupName] = useState("");
  const [showMemberForm, setShowMemberForm] = useState(false);
  const [editingMember, setEditingMember] = useState<Member | null>(null);
  const [memberName, setMemberName] = useState("");
  const [memberRating, setMemberRating] = useState(3);
  const [memberSubscriber, setMemberSubscriber] = useState(false);
  const [memberAdmin, setMemberAdmin] = useState(false);
  const [teamDraft, setTeamDraft] = useState<Record<string, string>>({});
  const [editingTeams, setEditingTeams] = useState(false);

  const [gameDate, setGameDate] = useState("");
  const [gameTime, setGameTime] = useState("20:00");
  const [priorityHours, setPriorityHours] = useState(24);
  const [participantCount, setParticipantCount] = useState(12);
  const [playersPerTeam, setPlayersPerTeam] = useState(4);

  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [matchScores, setMatchScores] = useState<Record<string, { home: string; away: string }>>({});
  const [goalDrafts, setGoalDrafts] = useState<
    Record<string, { scorer: string; assist: string }[]>
  >({});
  const [mvpChoice, setMvpChoice] = useState("");
  const [surveyDraft, setSurveyDraft] = useState<Record<string, number>>({});
  const [copied, setCopied] = useState(false);
  const membershipStateRef = useRef<string | null>(null);
  const skipNextGroupLoad = useRef(false);
  const isAdminRef = useRef(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
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
    return fetch(`${API_URL}${path}`, { ...options, headers });
  }

  async function parseError(response: Response) {
    try {
      const data = await response.json();
      return data.detail ?? data.message ?? "Action failed";
    } catch {
      return "Action failed";
    }
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
        return {
          ...current,
          game_day: null,
          history: [
            {
              id: data.id,
              game_datetime: data.game_datetime,
              status: data.status,
              is_rotating: data.is_rotating,
              champion_team_name: data.champion_team_name,
              awards: data.awards ?? { champions: [], mvps: [] },
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
        my_ratings?: Record<string, number>;
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
    if (!bootResponse.ok) throw new Error(await parseError(bootResponse));
    const boot = await bootResponse.json();
    setIsDeveloper(Boolean(boot.is_developer));
    const mine: MyGroup[] = boot.groups ?? [];
    setMyGroups(mine);
    if (inviteCode) await loadInvite(inviteCode);
    let target = selectedGroupId;
    if (!target || !mine.some((item) => item.id === target)) {
      target = mine[0]?.id ?? null;
      if (target !== selectedGroupId) {
        skipNextGroupLoad.current = true;
        setSelectedGroupId(target);
      }
    }
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
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setAuthReady(true);
    });
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, newSession) => {
      setSession(newSession);
      setAuthReady(true);
    });
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session) {
      setMyGroups([]);
      setGroup(null);
      setMembership(null);
      setSelectedGroupId(null);
      return;
    }
    refreshData().catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load app")
    );
  }, [session]);

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
    if (tab !== "stats" || !selectedGroupId || membership?.state !== "member") {
      return;
    }
    loadStats(selectedGroupId).catch(() => {});
  }, [tab, selectedGroupId, membership?.state]);

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
  }, [group?.game_day?.teams, group?.game_day?.unassigned]);

  useEffect(() => {
    if (invitePreview?.state === "member") {
      setSelectedGroupId(invitePreview.id);
    }
  }, [invitePreview]);

  async function handleAuth(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (authMode === "signup") {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: {
              display_name: displayName.trim() || email.split("@")[0],
            },
          },
        });
        if (signUpError) throw signUpError;
        setError(t("accountCreated"));
        setAuthMode("login");
      } else {
        const { error: loginError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (loginError) throw loginError;
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
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

  function resetMemberForm() {
    setEditingMember(null);
    setMemberName("");
    setMemberRating(3);
    setMemberSubscriber(false);
    setMemberAdmin(false);
    setShowMemberForm(false);
  }

  function startEditMember(member: Member) {
    setEditingMember(member);
    setMemberName(member.name);
    setMemberRating(member.rating);
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

  async function saveTeamAdjustments() {
    if (!group?.game_day) return;
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

  if (!session) {
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={handleAuth}>
          <h1>⚽ {t("appName")}</h1>
          <p>{authMode === "login" ? t("loginSubtitle") : t("signupSubtitle")}</p>
          {languageToggle}
          {authMode === "signup" && (
            <label>
              {t("name")}
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                required
              />
            </label>
          )}
          <label>
            {t("email")}
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            {t("password")}
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              minLength={6}
              required
            />
          </label>
          {error && <div className="error-box">{error}</div>}
          <button className="primary-button" type="submit" disabled={loading}>
            {authMode === "login" ? t("logIn") : t("signUp")}
          </button>
          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              setError("");
              setAuthMode(authMode === "login" ? "signup" : "login");
            }}
          >
            {authMode === "login" ? t("createAccount") : t("backToLogin")}
          </button>
        </form>
      </div>
    );
  }

  const gameDay = group?.game_day ?? null;
  const teamNames = gameDay?.teams.map((team) => team.name) ?? [];

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>⚽ {t("appName")}</h1>
          <p>{session.user.email}</p>
        </div>
        <div className="header-actions">
          {languageToggle}
          <button className="secondary-button" onClick={() => supabase.auth.signOut()}>
            {t("logOut")}
          </button>
        </div>
      </header>

      <div className="page-layout">
        {isDeveloper && (
          <aside className="developer-panel">
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
          </aside>
        )}

        <main className="container">
          {error && <div className="error-box">{error}</div>}

          {invitePreview && invitePreview.state !== "member" && (
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
                  onClick={() => setSelectedGroupId(item.id)}
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

          {group && isMember && (
            <section className="card group-title-card">
              <div className="group-title-row">
                <h2>{group.name}</h2>
                <div className="header-actions">
                  <button
                    className={tab === "group" ? "primary-button" : "secondary-button"}
                    onClick={() => setTab("group")}
                  >
                    {t("gameDay")}
                  </button>
                  <button
                    className={tab === "stats" ? "primary-button" : "secondary-button"}
                    onClick={() => setTab("stats")}
                  >
                    {t("statistics")}
                  </button>
                  <button
                    className="text-danger-button"
                    onClick={() => {
                      if (window.confirm(t("leaveConfirm"))) {
                        runAction(
                          () =>
                            apiFetch(`/groups/${group.id}/leave`, {
                              method: "DELETE",
                            }),
                          "reload-app"
                        ).then(() => setSelectedGroupId(null));
                      }
                    }}
                  >
                    {t("leaveGroup")}
                  </button>
                </div>
              </div>
            </section>
          )}

          {group && isAdmin && tab === "group" && (
            <section className="card">
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

          {group && isAdmin && joinRequests.length > 0 && (
            <section className="card">
              <h2>{t("pendingJoinRequests")}</h2>
              {joinRequests.map((request) => (
                <div className="request-row" key={request.id}>
                  <strong>{request.user_name}</strong>
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

          {group && isMember && tab === "stats" && (
            <section className="card">
              <h2>{t("statistics")}</h2>
              <div className="stats-table">
                {stats.map((row) => (
                  <div className="member-row" key={row.id}>
                    <div>
                      <strong>{row.name}</strong>
                      <div className="member-details">
                        {t("rating")} {row.rating} · {t("gameDaysPlayed")}{" "}
                        {row.game_days_played} · {t("matchesPlayed")}{" "}
                        {row.matches_played} · {t("championships")}{" "}
                        {row.championships} · {t("goals")} {row.goals} ·{" "}
                        {t("assists")} {row.assists} · {t("mvpTitles")}{" "}
                        {row.mvp_titles}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {group && isMember && tab === "group" && (
            <>
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
                    <div className="countdown">{countdownText(gameDay)}</div>
                    <div className="game-stats">
                      <span>
                        <strong>{gameDay.participants.length}</strong>/
                        {gameDay.participant_count} {t("registered")}
                      </span>
                      <span>
                        <strong>{gameDay.waiting_list.length}</strong> {t("waiting")}
                      </span>
                    </div>
                    {isAdmin && gameDay.status !== "finished" && (
                      <div className="form-actions">
                        {gameDay.status === "live" && (
                          <button
                            className="primary-button"
                            onClick={() =>
                              runAction(() =>
                                apiFetch(
                                  `/groups/${group.id}/game-days/${gameDay.id}/finish`,
                                  { method: "POST" }
                                )
                              )
                            }
                          >
                            {t("finishGameDay")}
                          </button>
                        )}
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

              <section className="card">
                <div className="section-header">
                  <div>
                    <h2>{t("groupMembers")}</h2>
                    <span>
                      {group.members.length} {t("members")}
                    </span>
                  </div>
                  {isAdmin && (
                    <button
                      className="primary-button"
                      onClick={() => {
                        resetMemberForm();
                        setShowMemberForm(true);
                      }}
                    >
                      + {t("addVirtualMember")}
                    </button>
                  )}
                </div>
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
                        {t("rating")}
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
                <div className="member-list">
                  {group.members.map((member) => {
                    const participant = Boolean(
                      gameDay?.participants.some((item) => item.id === member.id)
                    );
                    const waiting = Boolean(
                      gameDay?.waiting_list.some((item) => item.id === member.id)
                    );
                    const canControl =
                      isAdmin || currentMembership?.id === member.id;
                    return (
                      <div className="member-row" key={member.id}>
                        <div className="member-main">
                          <strong>{member.name}</strong>
                          <div className="member-details">
                            {t("rating")} {member.rating}
                            {member.is_subscriber && ` · ${t("subscriber")}`}
                            {member.is_admin && ` · ${t("admin")}`}
                            {member.is_virtual && ` · ${t("virtual")}`}
                            {participant && ` · ${t("registered")}`}
                            {waiting && ` · ${t("waiting")}`}
                          </div>
                        </div>
                        <div className="member-actions">
                          {gameDay &&
                            gameDay.status !== "finished" &&
                            canControl &&
                            (participant || waiting ? (
                              <button
                                className="secondary-button"
                                onClick={() =>
                                  runAction(
                                    () =>
                                      apiFetch(
                                        `/groups/${group.id}/game-days/${gameDay.id}/unregister/${member.id}`,
                                        { method: "POST" }
                                      ),
                                    "silent"
                                  )
                                }
                              >
                                {t("leaveGameDay")}
                              </button>
                            ) : (
                              <button
                                className="secondary-button"
                                onClick={() =>
                                  runAction(
                                    () =>
                                      apiFetch(
                                        `/groups/${group.id}/game-days/${gameDay.id}/register/${member.id}`,
                                        { method: "POST" }
                                      ),
                                    "silent"
                                  )
                                }
                              >
                                {t("register")}
                              </button>
                            ))}
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
                                onClick={() => {
                                  if (window.confirm(t("deleteConfirm"))) {
                                    runAction(
                                      () =>
                                        apiFetch(
                                          `/groups/${group.id}/members/${member.id}`,
                                          { method: "DELETE" }
                                        )
                                    ).then(() =>
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
                                      })
                                    );
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
              </section>

              {gameDay && (
                <section className="card">
                  <h2>{t("gameRegistration")}</h2>
                  <div className="registration-columns">
                    <div>
                      <h3>{t("registeredPlayers")}</h3>
                      {gameDay.participants.map((player, index) => (
                        <p key={player.id}>
                          {index + 1}. {player.name}
                        </p>
                      ))}
                    </div>
                    <div>
                      <h3>{t("waitingList")}</h3>
                      {gameDay.waiting_list.map((player, index) => (
                        <p key={player.id}>
                          {index + 1}. {player.name}
                        </p>
                      ))}
                    </div>
                  </div>
                </section>
              )}

              {gameDay && (
                <section className="card">
                  <h2>{t("generateTeams")}</h2>
                  {isAdmin && (
                    <button
                      className="primary-button"
                      disabled={
                        gameDay.participants.length !== gameDay.participant_count
                      }
                      onClick={() =>
                        runAction(() =>
                          apiFetch(
                            `/groups/${group.id}/game-days/${gameDay.id}/generate-teams`,
                            { method: "POST" }
                          )
                        )
                      }
                    >
                      {t("generateTeams")}
                    </button>
                  )}
                  {gameDay.teams.length > 0 && isAdmin && (
                    <div className="team-edit-toolbar">
                      {!editingTeams ? (
                        <button
                          className="secondary-button"
                          onClick={() => setEditingTeams(true)}
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
                            onClick={() => setEditingTeams(false)}
                          >
                            {t("cancel")}
                          </button>
                        </>
                      )}
                    </div>
                  )}
                  <div className="teams-grid">
                    {gameDay.teams.map((team) => (
                      <div className="team-box" key={team.name}>
                        <div className="team-header">
                          <h3>{team.name}</h3>
                          <span>
                            {team.players.length}/{gameDay.players_per_team}
                          </span>
                        </div>
                        {(editingTeams
                          ? gameDay.participants.filter(
                              (player) => teamDraft[player.id] === team.name
                            )
                          : team.players
                        ).map((player) =>
                          editingTeams ? (
                            <div className="team-player-edit-row" key={player.id}>
                              <span>
                                {player.name} ({player.rating})
                              </span>
                              <select
                                value={teamDraft[player.id] ?? ""}
                                onChange={(event) =>
                                  setTeamDraft((previous) => ({
                                    ...previous,
                                    [player.id]: event.target.value,
                                  }))
                                }
                              >
                                <option value="">{t("unassigned")}</option>
                                {teamNames.map((name) => (
                                  <option key={name} value={name}>
                                    {name}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ) : (
                            <p key={player.id}>
                              {player.name} ({player.rating})
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
                                {player.name} ({player.rating})
                              </span>
                              <select
                                value={teamDraft[player.id] ?? ""}
                                onChange={(event) =>
                                  setTeamDraft((previous) => ({
                                    ...previous,
                                    [player.id]: event.target.value,
                                  }))
                                }
                              >
                                <option value="">{t("unassigned")}</option>
                                {teamNames.map((name) => (
                                  <option key={name} value={name}>
                                    {name}
                                  </option>
                                ))}
                              </select>
                            </div>
                          ) : (
                            <p key={player.id}>
                              {player.name} ({player.rating})
                            </p>
                          )
                        )}
                      </div>
                    )}
                  </div>
                </section>
              )}

              {gameDay && gameDay.status === "live" && (
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
                                {name}
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
                                {name}
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
                  {gameDay.matches.map((match) => {
                    const scores = matchScores[match.id] ?? {
                      home: String(match.home_score ?? 0),
                      away: String(match.away_score ?? 0),
                    };
                    const goals = goalDrafts[match.id] ?? [];
                    return (
                      <div className="team-box" key={match.id}>
                        <h3>
                          {match.home_team_name} vs {match.away_team_name}
                        </h3>
                        {match.status === "completed" ? (
                          <p>
                            {match.home_score} - {match.away_score}
                          </p>
                        ) : (
                          isAdmin && (
                            <>
                              <div className="form-row">
                                <label>
                                  {t("homeScore")}
                                  <input
                                    type="number"
                                    min={0}
                                    value={scores.home}
                                    onChange={(event) =>
                                      setMatchScores((previous) => ({
                                        ...previous,
                                        [match.id]: {
                                          ...scores,
                                          home: event.target.value,
                                        },
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  {t("awayScore")}
                                  <input
                                    type="number"
                                    min={0}
                                    value={scores.away}
                                    onChange={(event) =>
                                      setMatchScores((previous) => ({
                                        ...previous,
                                        [match.id]: {
                                          ...scores,
                                          away: event.target.value,
                                        },
                                      }))
                                    }
                                  />
                                </label>
                              </div>
                              {goals.map((goal, index) => (
                                <div className="form-row" key={index}>
                                  <label>
                                    {t("scorer")}
                                    <select
                                      value={goal.scorer}
                                      onChange={(event) =>
                                        setGoalDrafts((previous) => {
                                          const next = [...(previous[match.id] ?? [])];
                                          next[index] = {
                                            ...goal,
                                            scorer: event.target.value,
                                          };
                                          return { ...previous, [match.id]: next };
                                        })
                                      }
                                    >
                                      <option value="">—</option>
                                      {match.players
                                        .filter((player) => !player.is_virtual)
                                        .map((player) => (
                                          <option key={player.id} value={player.id}>
                                            {player.name}
                                          </option>
                                        ))}
                                    </select>
                                  </label>
                                  <label>
                                    {t("assist")}
                                    <select
                                      value={goal.assist}
                                      onChange={(event) =>
                                        setGoalDrafts((previous) => {
                                          const next = [...(previous[match.id] ?? [])];
                                          next[index] = {
                                            ...goal,
                                            assist: event.target.value,
                                          };
                                          return { ...previous, [match.id]: next };
                                        })
                                      }
                                    >
                                      <option value="">{t("noAssist")}</option>
                                      {match.players
                                        .filter((player) => !player.is_virtual)
                                        .map((player) => (
                                          <option key={player.id} value={player.id}>
                                            {player.name}
                                          </option>
                                        ))}
                                    </select>
                                  </label>
                                </div>
                              ))}
                              <div className="form-actions">
                                <button
                                  className="secondary-button"
                                  type="button"
                                  onClick={() =>
                                    setGoalDrafts((previous) => ({
                                      ...previous,
                                      [match.id]: [
                                        ...(previous[match.id] ?? []),
                                        { scorer: "", assist: "" },
                                      ],
                                    }))
                                  }
                                >
                                  {t("addGoal")}
                                </button>
                                <button
                                  className="primary-button"
                                  onClick={() =>
                                    runAction(() =>
                                      apiFetch(
                                        `/groups/${group.id}/matches/${match.id}/complete`,
                                        {
                                          method: "POST",
                                          headers: {
                                            "Content-Type": "application/json",
                                          },
                                          body: JSON.stringify({
                                            home_score: Number(scores.home),
                                            away_score: Number(scores.away),
                                            goals: goals
                                              .filter((goal) => goal.scorer)
                                              .map((goal) => ({
                                                scorer_membership_id: goal.scorer,
                                                assist_membership_id: goal.assist || null,
                                              })),
                                          }),
                                        }
                                      )
                                    )
                                  }
                                >
                                  {t("completeMatch")}
                                </button>
                              </div>
                            </>
                          )
                        )}
                        {match.goals.map((goal) => (
                          <p key={goal.id}>
                            {goal.scorer.name}
                            {goal.assist ? ` (${goal.assist.name})` : ""}
                          </p>
                        ))}
                      </div>
                    );
                  })}
                </section>
              )}

              {gameDay && !gameDay.is_rotating && gameDay.standings.length > 0 && (
                <section className="card">
                  <h2>{t("standings")}</h2>
                  {gameDay.standings.map((row) => (
                    <p key={row.name}>
                      {row.name}: {row.points} {t("pts")} · {row.wins}
                      {t("wins")} {row.draws}
                      {t("draws")} {row.losses}
                      {t("losses")} · {t("gd")} {row.goal_difference}
                    </p>
                  ))}
                </section>
              )}

              {gameDay && gameDay.status === "finished" && (
                <section className="card">
                  {!gameDay.is_rotating && gameDay.champion_team_name && (
                    <h2>
                      {gameDay.awards.champions.length > 1
                        ? t("coChampions")
                        : t("champion")}
                      : {gameDay.champion_team_name}
                    </h2>
                  )}
                  {gameDay.mvp_announced ? (
                    <p>
                      {gameDay.awards.mvps.length > 1 ? t("coMvps") : t("mvpAnnounced")}
                      : {gameDay.awards.mvps.map((item) => item.name).join(", ")}
                    </p>
                  ) : (
                    <>
                      <h2>{t("mvpVoting")}</h2>
                      <p className="muted-text">{t("waitingForVotes")}</p>
                      <p className="muted-text">
                        {gameDay.votes_cast}/{gameDay.eligible_voters}
                      </p>
                      {gameDay.my_vote && <p>{t("youVoted")}</p>}
                      {currentMembership && !currentMembership.is_virtual && (
                        <div className="form-actions">
                          <select
                            value={mvpChoice}
                            onChange={(event) => setMvpChoice(event.target.value)}
                          >
                            <option value="">—</option>
                            {gameDay.participants
                              .filter(
                                (player) =>
                                  !player.is_virtual &&
                                  player.id !== currentMembership.id
                              )
                              .map((player) => (
                                <option key={player.id} value={player.id}>
                                  {player.name}
                                </option>
                              ))}
                          </select>
                          <button
                            className="primary-button"
                            disabled={!mvpChoice}
                            onClick={() =>
                              runAction(() =>
                                apiFetch(
                                  `/groups/${group.id}/game-days/${gameDay.id}/mvp`,
                                  {
                                    method: "POST",
                                    headers: {
                                      "Content-Type": "application/json",
                                    },
                                    body: JSON.stringify({
                                      nominee_membership_id: mvpChoice,
                                    }),
                                  }
                                )
                              )
                            }
                          >
                            {t("submitVote")}
                          </button>
                        </div>
                      )}
                      {isAdmin && (
                        <button
                          className="secondary-button"
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/game-days/${gameDay.id}/mvp/close`,
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

              <section className="card">
                <h2>{t("ratingSurvey")}</h2>
                {group.survey?.status === "open" ? (
                  <>
                    <p>{t("surveyOpen")}</p>
                    {group.members
                      .filter(
                        (member) =>
                          !member.is_virtual &&
                          member.id !== currentMembership?.id
                      )
                      .map((member) => (
                        <label key={member.id}>
                          {member.name}
                          <select
                            value={surveyDraft[member.id] ?? ""}
                            onChange={(event) =>
                              setSurveyDraft((previous) => ({
                                ...previous,
                                [member.id]: Number(event.target.value),
                              }))
                            }
                          >
                            <option value="">—</option>
                            {[1, 2, 3, 4, 5].map((value) => (
                              <option key={value} value={value}>
                                {value}
                              </option>
                            ))}
                          </select>
                        </label>
                      ))}
                    <div className="form-actions">
                      <button
                        className="primary-button"
                        onClick={() =>
                          runAction(() =>
                            apiFetch(
                              `/groups/${group.id}/surveys/${group.survey!.id}/ratings`,
                              {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ ratings: surveyDraft }),
                              }
                            )
                          )
                        }
                      >
                        {t("submitRatings")}
                      </button>
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

              {group.history.length > 0 && (
                <section className="card">
                  <h2>{t("history")}</h2>
                  {group.history.map((item) => (
                    <p key={item.id}>
                      {new Date(item.game_datetime).toLocaleString()}
                      {item.champion_team_name
                        ? ` · ${t("champion")}: ${item.champion_team_name}`
                        : ""}
                      {item.awards.mvps.length
                        ? ` · ${t("mvpAnnounced")}: ${item.awards.mvps
                            .map((mvp) => mvp.name)
                            .join(", ")}`
                        : ""}
                    </p>
                  ))}
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
