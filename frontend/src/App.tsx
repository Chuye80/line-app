import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import "./App.css";
import { configurationError, supabase } from "./supabase";
import { DEV_TOOLS_ENABLED, configureApi, del, get, post, put } from "./api";
import { IdentityProvider } from "./IdentityProvider";
import { useIdentity } from "./identity";
import { AuthScreen } from "./screens/AuthScreen";
import { DeveloperTools } from "./screens/DeveloperTools";
import { FinishedGameDay } from "./screens/FinishedGameDay";
import { GroupScreen } from "./screens/GroupScreen";
import type { MemberDraft } from "./screens/GroupScreen";
import { HistoryScreen } from "./screens/HistoryScreen";
import { LiveGameDay } from "./screens/LiveGameDay";
import type { GoalInput } from "./screens/LiveGameDay";
import { PreGameDay } from "./screens/PreGameDay";
import { StatisticsScreen } from "./screens/StatisticsScreen";
import { SurveyScreen } from "./screens/SurveyScreen";
import type {
  GameDay,
  Group,
  GroupSummary,
  HistoryEntry,
  JoinRequest,
  Member,
  MembershipStatus,
  MyGroup,
  OverallStatistics,
  Survey,
} from "./types";

// How often the open group is re-read while the tab is in the foreground.
// This used to be every second, which meant one full request per second per
// open tab for the entire time the app was on screen.
const REFRESH_INTERVAL_MS = 8000;

/**
 * Which experience the group is in.
 *
 * This comes from the game day's stored status, never from comparing the
 * kickoff time to the clock. That distinction is the whole reason a finished
 * game day used to come back to life on a refresh.
 */
type Phase = "before" | "live" | "finished";

type View =
  | "home"
  | "group"
  | "gameday"
  | "statistics"
  | "history"
  | "survey"
  | "dev";

type NavItem = { id: View; label: string };

/** A response, remembered together with what it was a response for. */
type Cached<T> = { key: string; data: T } | null;

function cachedFor<T>(cache: Cached<T>, key: string): T | null {
  return cache && cache.key === key ? cache.data : null;
}

function navItemsFor(phase: Phase): NavItem[] {
  const common: NavItem[] = [
    { id: "statistics", label: "Statistics" },
    { id: "history", label: "History" },
    { id: "survey", label: "Rating Survey" },
  ];

  if (phase === "live") {
    // Nothing about group setup or registration: the day has started, and the
    // squad is already fixed.
    return [{ id: "gameday", label: "Game Day" }, ...common];
  }

  if (phase === "finished") {
    return [
      { id: "gameday", label: "Champions" },
      { id: "home", label: "Home" },
      { id: "group", label: "Group" },
      ...common,
    ];
  }

  return [
    { id: "home", label: "Home" },
    { id: "group", label: "Group" },
    ...common,
  ];
}

function AppShell() {
  const identity = useIdentity();

  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);

  const [allGroups, setAllGroups] = useState<GroupSummary[]>([]);
  const [myGroups, setMyGroups] = useState<MyGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [group, setGroup] = useState<Group | null>(null);
  const [membership, setMembership] = useState<MembershipStatus | null>(null);
  const [joinRequests, setJoinRequests] = useState<JoinRequest[]>([]);
  const [gameDay, setGameDay] = useState<GameDay | null>(null);

  // The accumulated views are tagged with the group and identity they were
  // read for, so switching either shows a spinner rather than the previous
  // member's numbers.
  const [statistics, setStatistics] = useState<Cached<OverallStatistics>>(null);
  const [history, setHistory] = useState<Cached<HistoryEntry[]>>(null);
  const [survey, setSurvey] = useState<Cached<Survey>>(null);

  const [requestedView, setRequestedView] = useState<View>("home");
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Declared before every other effect so that the loaders below always run
  // against the current token and simulated member.
  useEffect(() => {
    configureApi({
      token: () => session?.access_token,
      actAs: () => identity.membershipId,
    });
  }, [session, identity.membershipId]);

  // Loading keys off the account rather than the session object, which is
  // replaced every time Supabase rotates the access token.
  const userId = session?.user.id ?? null;

  const isMember = membership?.state === "member";
  const isAdmin = Boolean(isMember && membership?.is_admin);
  const ownMembershipId = membership?.membership_id ?? null;

  const dataKey = `${selectedGroupId ?? ""}:${identity.membershipId ?? "self"}`;

  const phase: Phase =
    gameDay?.status === "live"
      ? "live"
      : gameDay?.status === "finished"
        ? "finished"
        : "before";

  const navItems = useMemo(() => navItemsFor(phase), [phase]);

  // Derived rather than corrected in an effect: when the day starts, "Home"
  // stops being a valid destination and the live screen takes over on the very
  // same render.
  const view: View = navItems.some((item) => item.id === requestedView)
    ? requestedView
    : requestedView === "dev" && DEV_TOOLS_ENABLED
      ? "dev"
      : navItems[0].id;

  // ---------------------------------------------------------------------
  // Loading
  // ---------------------------------------------------------------------

  /**
   * Read the group lists and settle on something to show.
   *
   * Selecting a group is what triggers the effect that loads it, so this must
   * not load it as well - doing both is what made every sign-in fetch the same
   * group twice.
   */
  const loadGroupLists = useCallback(async (preferred: string | null) => {
    const [groups, mine] = await Promise.all([
      get<GroupSummary[]>("/groups"),
      get<MyGroup[]>("/my-groups"),
    ]);

    setAllGroups(groups);
    setMyGroups(mine);

    const target =
      preferred && groups.some((item) => item.id === preferred)
        ? preferred
        : mine[0]?.id ?? groups[0]?.id ?? null;

    setSelectedGroupId(target);

    if (!target) {
      setGroup(null);
      setMembership(null);
      setJoinRequests([]);
      setGameDay(null);
    }

    return target;
  }, []);

  const loadGroup = useCallback(async (groupId: string) => {
    const [detail, status] = await Promise.all([
      get<Group>(`/groups/${groupId}`),
      get<MembershipStatus>(`/groups/${groupId}/membership-status`),
    ]);

    setGroup(detail);
    setMembership(status);

    if (status.state !== "member") {
      setJoinRequests([]);
      setGameDay(null);
      return;
    }

    const [day, requests] = await Promise.all([
      get<GameDay | null>(`/groups/${groupId}/game-day`),
      status.is_admin
        ? get<JoinRequest[]>(`/groups/${groupId}/join-requests`)
        : Promise.resolve([]),
    ]);

    setGameDay(day);
    setJoinRequests(requests);
  }, []);

  /** Re-read the open group. */
  const refresh = useCallback(async () => {
    if (!selectedGroupId) {
      return;
    }

    await loadGroup(selectedGroupId);
  }, [loadGroup, selectedGroupId]);

  async function run(action: () => Promise<unknown>, message?: string) {
    setBusy(true);
    setError("");
    setNotice("");

    try {
      await action();
      await refresh();

      if (message) {
        setNotice(message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
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

      if (!newSession) {
        // Clear on sign-out so the next account on this device never sees the
        // previous one's groups while its own data loads.
        setAllGroups([]);
        setMyGroups([]);
        setGroup(null);
        setMembership(null);
        setJoinRequests([]);
        setGameDay(null);
        setSelectedGroupId(null);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // Which group to stay on when the lists are re-read. Kept in a ref so that
  // re-reading them is not itself triggered by changing the selection.
  const preferredGroupRef = useRef<string | null>(null);

  useEffect(() => {
    preferredGroupRef.current = selectedGroupId;
  }, [selectedGroupId]);

  useEffect(() => {
    if (!userId) {
      return;
    }

    loadGroupLists(preferredGroupRef.current).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load app")
    );
    // Changing the simulated member changes every answer the server gives, so
    // the whole app is re-read rather than patched.
  }, [userId, identity.membershipId, loadGroupLists]);

  useEffect(() => {
    if (!userId || !selectedGroupId) {
      return;
    }

    // Fetching the selected group is synchronising with the server, not
    // deriving one piece of state from another: the state updates happen when
    // the request resolves, which the rule cannot see through.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadGroup(selectedGroupId).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load group")
    );
  }, [userId, selectedGroupId, identity.membershipId, loadGroup]);

  // The accumulated views are read when they are opened rather than kept in
  // step on every poll: they only change when a game day finishes or a survey
  // is saved.
  useEffect(() => {
    if (!userId || !selectedGroupId || !isMember) {
      return;
    }

    const groupId = selectedGroupId;
    const key = dataKey;

    const load = async () => {
      if (view === "statistics") {
        const data = await get<OverallStatistics>(
          `/groups/${groupId}/statistics`
        );
        setStatistics({ key, data });
      } else if (view === "history") {
        const data = await get<HistoryEntry[]>(`/groups/${groupId}/history`);
        setHistory({ key, data });
      } else if (view === "survey") {
        const data = await get<Survey>(`/groups/${groupId}/survey`);
        setSurvey({ key, data });
      }
    };

    load().catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load")
    );
  }, [
    userId,
    selectedGroupId,
    isMember,
    view,
    dataKey,
    gameDay?.status,
  ]);

  useEffect(() => {
    if (!userId || !selectedGroupId) {
      return;
    }

    const tick = () => {
      if (document.hidden) {
        return;
      }

      refresh().catch(() => {});
    };

    const timer = window.setInterval(tick, REFRESH_INTERVAL_MS);

    // Catch up immediately on returning to the tab rather than waiting out the
    // rest of the interval.
    document.addEventListener("visibilitychange", tick);

    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [userId, selectedGroupId, refresh]);

  // ---------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------

  if (configurationError) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <h1>⚽ LineApp</h1>
          <div className="error-box">{configurationError}</div>
        </div>
      </div>
    );
  }

  if (!authReady) {
    return <div className="auth-shell">Loading…</div>;
  }

  if (!session) {
    return <AuthScreen />;
  }

  const groupId = group?.id ?? "";

  return (
    <div className="app">
      <header className="header">
        <div className="header-main">
          <h1>⚽ LineApp</h1>

          <button
            className="group-pill"
            onClick={() => setSwitcherOpen(true)}
            title="Switch group"
          >
            {group?.name ?? "Choose a group"} <span aria-hidden="true">▾</span>
          </button>
        </div>

        <div className="header-actions">
          {DEV_TOOLS_ENABLED && (
            <button
              className={view === "dev" ? "tab active" : "tab"}
              onClick={() => setRequestedView("dev")}
            >
              Developer Tools
            </button>
          )}

          <button
            className="secondary-button"
            onClick={() => supabase.auth.signOut()}
          >
            Log Out
          </button>
        </div>
      </header>

      {identity.membershipId && (
        <div className="dev-banner">
          <span>
            Developer mode: viewing as{" "}
            <strong>{identity.name ?? "another member"}</strong>
          </span>
          <button className="text-button" onClick={identity.returnToMyself}>
            Return to myself
          </button>
        </div>
      )}

      {isMember && (
        <nav className="main-nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              className={item.id === view ? "nav-item active" : "nav-item"}
              onClick={() => setRequestedView(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      )}

      <main className="container">
        {error && <div className="error-box">{error}</div>}
        {notice && <div className="status-box in">{notice}</div>}

        {!group && (
          <section className="card">
            <h2>No group yet</h2>
            <p className="empty-note">
              Create a group for your football crowd, or ask for an invitation
              to an existing one.
            </p>
            <button
              className="primary-button"
              onClick={() => setSwitcherOpen(true)}
            >
              Find or create a group
            </button>
          </section>
        )}

        {group && !isMember && (
          <section className="card join-card">
            <h2>{group.name}</h2>

            {membership?.state === "pending" ? (
              <div className="status-box pending">
                Your request is waiting for admin approval.
              </div>
            ) : (
              <>
                <p className="empty-note">
                  You are not a member of this group yet.
                </p>
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() =>
                    run(() => post(`/groups/${groupId}/join-request`))
                  }
                >
                  Request to Join
                </button>
              </>
            )}
          </section>
        )}

        {group && isMember && view === "home" && (
          <PreGameDay
            group={group}
            isAdmin={isAdmin}
            ownMembershipId={ownMembershipId}
            busy={busy}
            onSchedule={(kickoff, priorityHours) =>
              run(() =>
                post(`/groups/${groupId}/game`, {
                  game_datetime: kickoff,
                  priority_hours: priorityHours,
                })
              )
            }
            onDeleteGame={() => {
              if (
                window.confirm(
                  "Delete this game day? Registrations and teams will be lost."
                )
              ) {
                run(() => del(`/groups/${groupId}/game`));
              }
            }}
            onRegister={(membershipId) =>
              run(() => post(`/groups/${groupId}/game/register/${membershipId}`))
            }
            onUnregister={(membershipId) =>
              run(() =>
                post(`/groups/${groupId}/game/unregister/${membershipId}`)
              )
            }
            onGenerateTeams={() =>
              run(() => post(`/groups/${groupId}/generate-teams`))
            }
            onSaveTeams={(assignments) =>
              run(() => put(`/groups/${groupId}/teams`, { assignments }))
            }
            onStartDay={() =>
              run(async () => {
                await post(`/groups/${groupId}/game/start`);
                setRequestedView("gameday");
              })
            }
          />
        )}

        {group && isMember && view === "group" && (
          <GroupScreen
            group={group}
            isAdmin={isAdmin}
            ownMembershipId={ownMembershipId}
            joinRequests={joinRequests}
            busy={busy}
            onSaveMember={(draft: MemberDraft, existing: Member | null) =>
              run(() =>
                existing
                  ? put(`/groups/${groupId}/members/${existing.id}`, draft)
                  : post(`/groups/${groupId}/members`, draft)
              )
            }
            onDeleteMember={(member) => {
              if (window.confirm(`Delete ${member.name}?`)) {
                run(() => del(`/groups/${groupId}/members/${member.id}`));
              }
            }}
            onApproveRequest={(requestId) =>
              run(() =>
                post(`/groups/${groupId}/join-requests/${requestId}/approve`)
              )
            }
            onDeclineRequest={(requestId) =>
              run(() =>
                post(`/groups/${groupId}/join-requests/${requestId}/decline`)
              )
            }
            onLeaveGroup={() => {
              if (!window.confirm(`Leave ${group.name}?`)) {
                return;
              }

              run(async () => {
                await del(`/groups/${groupId}/leave`);

                // Drop the selection first so the reload lands on a group the
                // user is still a member of instead of an empty page.
                setGroup(null);
                setMembership(null);
                setGameDay(null);
                await loadGroupLists(null);
              });
            }}
          />
        )}

        {group && isMember && view === "gameday" && gameDay?.status === "live" && (
          <LiveGameDay
            day={gameDay}
            isAdmin={isAdmin}
            busy={busy}
            ownMembershipId={ownMembershipId}
            onStartMatch={(matchId) =>
              run(() => post(`/groups/${groupId}/matches/${matchId}/start`))
            }
            onCompleteMatch={(matchId) =>
              run(() => post(`/groups/${groupId}/matches/${matchId}/complete`))
            }
            onAddGoal={(matchId, goal: GoalInput) =>
              run(() =>
                post(`/groups/${groupId}/matches/${matchId}/goals`, goal)
              )
            }
            onRemoveGoal={(matchId, goalId) =>
              run(() =>
                del(`/groups/${groupId}/matches/${matchId}/goals/${goalId}`)
              )
            }
            onFinishDay={() => run(() => post(`/groups/${groupId}/game/finish`))}
          />
        )}

        {group &&
          isMember &&
          view === "gameday" &&
          gameDay?.status === "finished" && (
            <FinishedGameDay
              day={gameDay}
              ownMembershipId={ownMembershipId}
              onReturnHome={() => setRequestedView("home")}
            />
          )}

        {group && isMember && view === "statistics" && (
          <StatisticsScreen
            statistics={cachedFor(statistics, dataKey)}
            ownMembershipId={ownMembershipId}
          />
        )}

        {group && isMember && view === "history" && (
          <HistoryScreen entries={cachedFor(history, dataKey)} />
        )}

        {group && isMember && view === "survey" && (
          <SurveyScreen
            key={dataKey}
            survey={cachedFor(survey, dataKey)}
            busy={busy}
            onSave={(ratings) =>
              run(async () => {
                const data = await put<Survey>(`/groups/${groupId}/survey`, {
                  ratings,
                });

                if (data) {
                  setSurvey({ key: dataKey, data });
                }
              }, "Ratings saved")
            }
          />
        )}

        {view === "dev" && DEV_TOOLS_ENABLED && (
          <DeveloperTools
            group={group}
            isAdmin={isAdmin}
            busy={busy}
            onSeedMembers={(count) =>
              run(() =>
                post(`/dev/groups/${groupId}/add-test-members?count=${count}`)
              )
            }
            onCreateGame={() =>
              run(() => post(`/dev/groups/${groupId}/create-game`))
            }
            onRegisterAll={() =>
              run(() => post(`/dev/groups/${groupId}/register-all`))
            }
            onExpirePriority={() =>
              run(() => post(`/dev/groups/${groupId}/expire-priority`))
            }
          />
        )}
      </main>

      {switcherOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <div className="modal">
            <h3>Groups</h3>

            <div className="group-switcher">
              {myGroups.map((item) => (
                <button
                  key={item.id}
                  className={
                    selectedGroupId === item.id
                      ? "group-chip active"
                      : "group-chip"
                  }
                  onClick={() => {
                    setSelectedGroupId(item.id);
                    setRequestedView("home");
                    setSwitcherOpen(false);
                  }}
                >
                  <strong>{item.name}</strong>
                  <span>{item.is_admin ? "Admin" : "Member"}</span>
                </button>
              ))}

              {myGroups.length === 0 && (
                <p className="empty-note">You have no memberships yet.</p>
              )}
            </div>

            <label>
              Browse every group
              <select
                value={selectedGroupId ?? ""}
                onChange={(event) => {
                  setSelectedGroupId(event.target.value);
                  setRequestedView("home");
                  setSwitcherOpen(false);
                }}
              >
                <option value="">Select…</option>
                {allGroups.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Create a group
              <div className="create-group-row">
                <input
                  placeholder="Group name"
                  value={newGroupName}
                  onChange={(event) => setNewGroupName(event.target.value)}
                />
                <button
                  className="primary-button"
                  disabled={busy || !newGroupName.trim()}
                  onClick={async () => {
                    setBusy(true);
                    setError("");

                    try {
                      const created = await post<Group>("/groups", {
                        name: newGroupName.trim(),
                      });

                      setNewGroupName("");
                      await loadGroupLists(created?.id ?? null);
                      setRequestedView("home");
                      setSwitcherOpen(false);
                    } catch (err) {
                      setError(
                        err instanceof Error ? err.message : "Action failed"
                      );
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Create
                </button>
              </div>
            </label>

            <div className="form-actions">
              <button
                className="secondary-button"
                onClick={() => setSwitcherOpen(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <IdentityProvider>
      <AppShell />
    </IdentityProvider>
  );
}
