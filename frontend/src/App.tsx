import { FormEvent, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import "./App.css";
import { supabase } from "./supabase";

const API_URL = "http://127.0.0.1:8000";

type Member = {
  id: string;
  user_id: string | null;
  name: string;
  rating: number;
  is_subscriber: boolean;
  is_admin: boolean;
  is_virtual: boolean;
};

type Game = {
  game_datetime: string;
  regular_registration_opens: string;
  participants: Member[];
  waiting_list: Member[];
};

type Team = {
  name: string;
  players: Member[];
  total_rating: number;
  average_rating: number;
};

type Group = {
  id: string;
  name: string;
  members: Member[];
  game: Game | null;
  teams: Team[];
};

type GroupSummary = {
  id: string;
  name: string;
};

type MyGroup = {
  id: string;
  name: string;
  membership_id: string;
  is_admin: boolean;
  is_subscriber: boolean;
  rating: number;
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

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authReady, setAuthReady] = useState(false);

  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [allGroups, setAllGroups] = useState<GroupSummary[]>([]);
  const [myGroups, setMyGroups] = useState<MyGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [group, setGroup] = useState<Group | null>(null);
  const [membership, setMembership] = useState<MembershipStatus | null>(null);
  const [joinRequests, setJoinRequests] = useState<JoinRequest[]>([]);

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

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [now, setNow] = useState(new Date());

  const isMember = membership?.state === "member";
  const isAdmin = Boolean(isMember && membership?.is_admin);

  const currentMembership = useMemo(
    () =>
      group?.members.find(
        (member) => member.id === membership?.membership_id
      ) ?? null,
    [group, membership?.membership_id]
  );

  async function apiFetch(
    path: string,
    options: RequestInit = {}
  ): Promise<Response> {
    const token = session?.access_token;

    if (!token) {
      throw new Error("No active session");
    }

    const headers = new Headers(options.headers);
    headers.set("Authorization", `Bearer ${token}`);

    return fetch(`${API_URL}${path}`, {
      ...options,
      headers,
    });
  }

  async function parseError(response: Response) {
    try {
      const data = await response.json();
      return data.detail ?? data.message ?? "Action failed";
    } catch {
      return "Action failed";
    }
  }

  async function runAction(
    action: () => Promise<Response>,
    refresh = true
  ) {
    setLoading(true);
    setError("");

    try {
      const response = await action();

      if (!response.ok) {
        throw new Error(await parseError(response));
      }

      if (refresh) {
        await refreshData();
      }

      return response;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      throw err;
    } finally {
      setLoading(false);
    }
  }

  async function loadGroups() {
    const response = await apiFetch("/groups");

    if (!response.ok) {
      throw new Error(await parseError(response));
    }

    const data: GroupSummary[] = await response.json();
    setAllGroups(data);
    return data;
  }

  async function loadMyGroups() {
    const response = await apiFetch("/my-groups");

    if (!response.ok) {
      throw new Error(await parseError(response));
    }

    const data: MyGroup[] = await response.json();
    setMyGroups(data);
    return data;
  }

  async function loadGroup(groupId: string) {
    const response = await apiFetch(`/groups/${groupId}`);

    if (!response.ok) {
      throw new Error(await parseError(response));
    }

    const data: Group = await response.json();
    setGroup(data);
    return data;
  }

  async function loadMembership(groupId: string) {
    const response = await apiFetch(
      `/groups/${groupId}/membership-status`
    );

    if (!response.ok) {
      throw new Error(await parseError(response));
    }

    const data: MembershipStatus = await response.json();
    setMembership(data);

    if (data.state === "member" && data.is_admin) {
      const pending = await apiFetch(
        `/groups/${groupId}/join-requests`
      );

      if (pending.ok) {
        setJoinRequests(await pending.json());
      }
    } else {
      setJoinRequests([]);
    }
  }

  async function refreshData() {
    if (!session) {
      return;
    }

    const [groups, mine] = await Promise.all([
      loadGroups(),
      loadMyGroups(),
    ]);

    let target = selectedGroupId;

    if (
      !target ||
      !groups.some((item) => item.id === target)
    ) {
      target = mine[0]?.id ?? groups[0]?.id ?? null;
      setSelectedGroupId(target);
    }

    if (target) {
      await Promise.all([
        loadGroup(target),
        loadMembership(target),
      ]);
    } else {
      setGroup(null);
      setMembership(null);
      setJoinRequests([]);
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
      setAllGroups([]);
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
    if (!session || !selectedGroupId) {
      return;
    }

    Promise.all([
      loadGroup(selectedGroupId),
      loadMembership(selectedGroupId),
    ]).catch((err) =>
      setError(err instanceof Error ? err.message : "Failed to load group")
    );
  }, [selectedGroupId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(new Date());

      if (session && selectedGroupId) {
        loadGroup(selectedGroupId).catch(() => {});
      }
    }, 1000);

    return () => window.clearInterval(timer);
  }, [session, selectedGroupId]);

  useEffect(() => {
    if (!group?.teams.length) {
      setTeamDraft({});
      setEditingTeams(false);
      return;
    }

    const draft: Record<string, string> = {};

    group.teams.forEach((team) => {
      team.players.forEach((player) => {
        draft[player.id] = team.name;
      });
    });

    setTeamDraft(draft);
  }, [group?.teams]);

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

        if (signUpError) {
          throw signUpError;
        }

        setError(
          "Account created. If email confirmation is enabled, confirm your email and then log in."
        );
        setAuthMode("login");
      } else {
        const { error: loginError } =
          await supabase.auth.signInWithPassword({
            email,
            password,
          });

        if (loginError) {
          throw loginError;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setLoading(false);
    }
  }

  async function createGroup() {
    if (!newGroupName.trim()) {
      return;
    }

    const response = await runAction(() =>
      apiFetch("/groups", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: newGroupName.trim(),
        }),
      })
    );

    if (response) {
      const created: Group = await response.clone().json().catch(() => null);
      setNewGroupName("");
      if (created?.id) {
        setSelectedGroupId(created.id);
      }
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

    if (!group || !memberName.trim()) {
      return;
    }

    const body = JSON.stringify({
      name: memberName.trim(),
      rating: memberRating,
      is_subscriber: memberSubscriber,
      is_admin: memberAdmin,
    });

    if (editingMember) {
      await runAction(() =>
        apiFetch(
          `/groups/${group.id}/members/${editingMember.id}`,
          {
            method: "PUT",
            headers: {
              "Content-Type": "application/json",
            },
            body,
          }
        )
      );
    } else {
      await runAction(() =>
        apiFetch(`/groups/${group.id}/members`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body,
        })
      );
    }

    resetMemberForm();
  }

  function isParticipant(member: Member) {
    return Boolean(
      group?.game?.participants.some(
        (player) => player.id === member.id
      )
    );
  }

  function isWaiting(member: Member) {
    return Boolean(
      group?.game?.waiting_list.some(
        (player) => player.id === member.id
      )
    );
  }

  function countdownText() {
    if (!group?.game) {
      return "";
    }

    const deadline = new Date(
      group.game.regular_registration_opens
    );
    const diff = deadline.getTime() - now.getTime();

    if (diff <= 0) {
      return "Registration open to all members";
    }

    const totalSeconds = Math.floor(diff / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    return (
      `Subscribers only: ` +
      `${hours.toString().padStart(2, "0")}:` +
      `${minutes.toString().padStart(2, "0")}:` +
      `${seconds.toString().padStart(2, "0")}`
    );
  }

  function teamCount(teamName: string) {
    return Object.values(teamDraft).filter(
      (value) => value === teamName
    ).length;
  }

  async function saveTeamAdjustments() {
    if (!group) return;

    if (
      ["Team A", "Team B", "Team C"].some(
        (name) => teamCount(name) !== 4
      )
    ) {
      setError("Each team must contain exactly 4 players.");
      return;
    }

    await runAction(() =>
      apiFetch(`/groups/${group.id}/teams`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          assignments: Object.entries(teamDraft).map(
            ([membershipId, teamName]) => ({
              membership_id: membershipId,
              team_name: teamName,
            })
          ),
        }),
      })
    );

    setEditingTeams(false);
  }

  if (!authReady) {
    return <div className="auth-shell">Loading…</div>;
  }

  if (!session) {
    return (
      <div className="auth-shell">
        <form className="auth-card" onSubmit={handleAuth}>
          <h1>⚽ LineApp</h1>
          <p>
            {authMode === "login"
              ? "Sign in to your football groups"
              : "Create your LineApp account"}
          </p>

          {authMode === "signup" && (
            <label>
              Name
              <input
                value={displayName}
                onChange={(event) =>
                  setDisplayName(event.target.value)
                }
                required
              />
            </label>
          )}

          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(event) =>
                setEmail(event.target.value)
              }
              required
            />
          </label>

          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) =>
                setPassword(event.target.value)
              }
              minLength={6}
              required
            />
          </label>

          {error && <div className="error-box">{error}</div>}

          <button
            className="primary-button"
            type="submit"
            disabled={loading}
          >
            {authMode === "login" ? "Log In" : "Sign Up"}
          </button>

          <button
            className="secondary-button"
            type="button"
            onClick={() => {
              setError("");
              setAuthMode(
                authMode === "login" ? "signup" : "login"
              );
            }}
          >
            {authMode === "login"
              ? "Create account"
              : "Back to login"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>⚽ LineApp</h1>
          <p>{session.user.email}</p>
        </div>

        <button
          className="secondary-button"
          onClick={() => supabase.auth.signOut()}
        >
          Log Out
        </button>
      </header>

      <div className="page-layout">
        <aside className="developer-panel">
          <h3>Developer Tools</h3>

          <button
            disabled={!group || !isAdmin}
            onClick={() =>
              group &&
              runAction(() =>
                apiFetch(
                  `/dev/groups/${group.id}/add-test-members?count=12`,
                  { method: "POST" }
                )
              )
            }
          >
            Fill to 12 Members
          </button>

          <button
            disabled={!group || !isAdmin}
            onClick={() =>
              group &&
              runAction(() =>
                apiFetch(
                  `/dev/groups/${group.id}/add-test-members?count=16`,
                  { method: "POST" }
                )
              )
            }
          >
            Fill to 16 Members
          </button>

          <button
            disabled={!group || !isAdmin}
            onClick={() =>
              group &&
              runAction(() =>
                apiFetch(
                  `/dev/groups/${group.id}/create-game`,
                  { method: "POST" }
                )
              )
            }
          >
            Create Test Game
          </button>

          <button
            disabled={!group?.game || !isAdmin}
            onClick={() =>
              group &&
              runAction(() =>
                apiFetch(
                  `/dev/groups/${group.id}/register-all`,
                  { method: "POST" }
                )
              )
            }
          >
            Register All
          </button>

          <button
            disabled={!group?.game || !isAdmin}
            onClick={() =>
              group &&
              runAction(() =>
                apiFetch(
                  `/dev/groups/${group.id}/expire-priority`,
                  { method: "POST" }
                )
              )
            }
          >
            Expire Priority
          </button>
        </aside>

        <main className="container">
          {error && <div className="error-box">{error}</div>}

          <section className="card">
            <div className="section-header">
              <div>
                <h2>My Groups</h2>
                <span>{myGroups.length} memberships</span>
              </div>
            </div>

            <div className="group-switcher">
              {myGroups.map((item) => (
                <button
                  key={item.id}
                  className={
                    selectedGroupId === item.id
                      ? "group-chip active"
                      : "group-chip"
                  }
                  onClick={() =>
                    setSelectedGroupId(item.id)
                  }
                >
                  <strong>{item.name}</strong>
                  <span>
                    {item.is_admin ? "Admin" : "Member"}
                  </span>
                </button>
              ))}
            </div>

            <div className="create-group-row">
              <input
                placeholder="New group name"
                value={newGroupName}
                onChange={(event) =>
                  setNewGroupName(event.target.value)
                }
              />
              <button
                className="primary-button"
                disabled={!newGroupName.trim()}
                onClick={createGroup}
              >
                Create Group
              </button>
            </div>

            {allGroups.length > 0 && (
              <div className="browse-groups">
                <label>
                  Browse / open another group
                  <select
                    value={selectedGroupId ?? ""}
                    onChange={(event) =>
                      setSelectedGroupId(event.target.value)
                    }
                  >
                    {allGroups.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            )}
          </section>

          {group && (
            <section className="card group-title-card">
              <div className="group-title-row">
                <h2>{group.name}</h2>

                {isMember && (
                  <button
                    className="text-danger-button"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Leave ${group.name}?`
                        )
                      ) {
                        runAction(() =>
                          apiFetch(
                            `/groups/${group.id}/leave`,
                            { method: "DELETE" }
                          )
                        ).then(() =>
                          setSelectedGroupId(null)
                        );
                      }
                    }}
                  >
                    Leave Group
                  </button>
                )}
              </div>
            </section>
          )}

          {group && !isMember && (
            <section className="card join-card">
              <h2>Join this group</h2>

              {membership?.state === "pending" ? (
                <div className="status-box pending">
                  Your request is waiting for admin approval.
                </div>
              ) : (
                <button
                  className="primary-button"
                  onClick={() =>
                    runAction(() =>
                      apiFetch(
                        `/groups/${group.id}/join-request`,
                        { method: "POST" }
                      )
                    )
                  }
                >
                  Request to Join
                </button>
              )}
            </section>
          )}

          {group && isAdmin && joinRequests.length > 0 && (
            <section className="card">
              <h2>Pending Join Requests</h2>

              {joinRequests.map((request) => (
                <div className="request-row" key={request.id}>
                  <strong>{request.user_name}</strong>

                  <div className="request-actions">
                    <button
                      className="primary-button"
                      onClick={() =>
                        runAction(() =>
                          apiFetch(
                            `/groups/${group.id}/join-requests/${request.id}/approve`,
                            { method: "POST" }
                          )
                        )
                      }
                    >
                      Approve
                    </button>

                    <button
                      className="secondary-button"
                      onClick={() =>
                        runAction(() =>
                          apiFetch(
                            `/groups/${group.id}/join-requests/${request.id}/decline`,
                            { method: "POST" }
                          )
                        )
                      }
                    >
                      Decline
                    </button>
                  </div>
                </div>
              ))}
            </section>
          )}

          {group && isMember && (
            <>
              <section className="card">
                <h2>Next Game</h2>

                {!group.game ? (
                  <>
                    <p>No game has been scheduled yet.</p>

                    {isAdmin && (
                      <div className="form-panel">
                        <div className="form-row">
                          <label>
                            Game date
                            <input
                              type="date"
                              value={gameDate}
                              onChange={(event) =>
                                setGameDate(event.target.value)
                              }
                            />
                          </label>

                          <label>
                            Kickoff time
                            <input
                              type="time"
                              value={gameTime}
                              onChange={(event) =>
                                setGameTime(event.target.value)
                              }
                            />
                          </label>
                        </div>

                        <label>
                          Subscriber priority
                          <select
                            value={priorityHours}
                            onChange={(event) =>
                              setPriorityHours(
                                Number(event.target.value)
                              )
                            }
                          >
                            <option value={6}>6 hours</option>
                            <option value={12}>12 hours</option>
                            <option value={24}>24 hours</option>
                            <option value={48}>48 hours</option>
                            <option value={72}>3 days</option>
                          </select>
                        </label>

                        <button
                          className="primary-button"
                          disabled={!gameDate || !gameTime}
                          onClick={() =>
                            runAction(() =>
                              apiFetch(
                                `/groups/${group.id}/game`,
                                {
                                  method: "POST",
                                  headers: {
                                    "Content-Type":
                                      "application/json",
                                  },
                                  body: JSON.stringify({
                                    game_datetime:
                                      `${gameDate}T${gameTime}`,
                                    priority_hours:
                                      priorityHours,
                                  }),
                                }
                              )
                            )
                          }
                        >
                          Create Game
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <p>
                      <strong>Kickoff:</strong>{" "}
                      {new Date(
                        group.game.game_datetime
                      ).toLocaleString()}
                    </p>

                    <div className="countdown">
                      {countdownText()}
                    </div>

                    <div className="game-stats">
                      <span>
                        <strong>
                          {group.game.participants.length}
                        </strong>
                        /12 registered
                      </span>
                      <span>
                        <strong>
                          {group.game.waiting_list.length}
                        </strong>{" "}
                        waiting
                      </span>
                    </div>

                    {isAdmin && (
                      <button
                        className="danger-button"
                        onClick={() =>
                          runAction(() =>
                            apiFetch(
                              `/groups/${group.id}/game`,
                              { method: "DELETE" }
                            )
                          )
                        }
                      >
                        Delete Game
                      </button>
                    )}
                  </>
                )}
              </section>

              <section className="card">
                <div className="section-header">
                  <div>
                    <h2>Group Members</h2>
                    <span>{group.members.length} members</span>
                  </div>

                  {isAdmin && (
                    <button
                      className="primary-button"
                      onClick={() => {
                        resetMemberForm();
                        setShowMemberForm(true);
                      }}
                    >
                      + Add Virtual Member
                    </button>
                  )}
                </div>

                {showMemberForm && isAdmin && (
                  <form
                    className="member-form"
                    onSubmit={saveMember}
                  >
                    <h3>
                      {editingMember
                        ? `Edit ${editingMember.name}`
                        : "Add Virtual Member"}
                    </h3>

                    <div className="form-row">
                      <label>
                        Name
                        <input
                          value={memberName}
                          onChange={(event) =>
                            setMemberName(event.target.value)
                          }
                          disabled={
                            Boolean(
                              editingMember?.user_id
                            )
                          }
                          required
                        />
                      </label>

                      <label>
                        Rating
                        <select
                          value={memberRating}
                          onChange={(event) =>
                            setMemberRating(
                              Number(event.target.value)
                            )
                          }
                        >
                          {[1, 2, 3, 4, 5].map((rating) => (
                            <option
                              key={rating}
                              value={rating}
                            >
                              {rating}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>

                    <div className="checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          checked={memberSubscriber}
                          onChange={(event) =>
                            setMemberSubscriber(
                              event.target.checked
                            )
                          }
                        />
                        Subscriber
                      </label>

                      <label>
                        <input
                          type="checkbox"
                          checked={memberAdmin}
                          onChange={(event) =>
                            setMemberAdmin(
                              event.target.checked
                            )
                          }
                        />
                        Admin
                      </label>
                    </div>

                    <div className="form-actions">
                      <button
                        className="primary-button"
                        type="submit"
                      >
                        Save
                      </button>
                      <button
                        className="secondary-button"
                        type="button"
                        onClick={resetMemberForm}
                      >
                        Cancel
                      </button>
                    </div>
                  </form>
                )}

                <div className="member-list">
                  {group.members.map((member) => {
                    const participant =
                      isParticipant(member);
                    const waiting = isWaiting(member);
                    const canControl =
                      isAdmin ||
                      currentMembership?.id === member.id;

                    return (
                      <div
                        className="member-row"
                        key={member.id}
                      >
                        <div className="member-main">
                          <strong>{member.name}</strong>
                          <div className="member-details">
                            Rating {member.rating}
                            {member.is_subscriber &&
                              " · Subscriber"}
                            {member.is_admin && " · Admin"}
                            {member.is_virtual && " · Virtual"}
                            {participant && " · Registered"}
                            {waiting && " · Waiting"}
                          </div>
                        </div>

                        <div className="member-actions">
                          {group.game &&
                            canControl &&
                            (participant || waiting ? (
                              <button
                                className="secondary-button"
                                onClick={() =>
                                  runAction(() =>
                                    apiFetch(
                                      `/groups/${group.id}/game/unregister/${member.id}`,
                                      { method: "POST" }
                                    )
                                  )
                                }
                              >
                                Leave Game
                              </button>
                            ) : (
                              <button
                                className="secondary-button"
                                onClick={() =>
                                  runAction(() =>
                                    apiFetch(
                                      `/groups/${group.id}/game/register/${member.id}`,
                                      { method: "POST" }
                                    )
                                  )
                                }
                              >
                                Register
                              </button>
                            ))}

                          {isAdmin && (
                            <>
                              <button
                                className="secondary-button"
                                onClick={() =>
                                  startEditMember(member)
                                }
                              >
                                Edit
                              </button>

                              <button
                                className="text-danger-button"
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      `Delete ${member.name}?`
                                    )
                                  ) {
                                    runAction(() =>
                                      apiFetch(
                                        `/groups/${group.id}/members/${member.id}`,
                                        { method: "DELETE" }
                                      )
                                    );
                                  }
                                }}
                              >
                                Delete
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>

              {group.game && (
                <section className="card">
                  <h2>Game Registration</h2>

                  <div className="registration-columns">
                    <div>
                      <h3>Registered Players</h3>
                      {group.game.participants.map(
                        (player, index) => (
                          <p key={player.id}>
                            {index + 1}. {player.name}
                          </p>
                        )
                      )}
                    </div>

                    <div>
                      <h3>Waiting List</h3>
                      {group.game.waiting_list.map(
                        (player, index) => (
                          <p key={player.id}>
                            {index + 1}. {player.name}
                          </p>
                        )
                      )}
                    </div>
                  </div>
                </section>
              )}

              <section className="card">
                <h2>Generate Teams</h2>

                {isAdmin && (
                  <button
                    className="primary-button"
                    disabled={
                      !group.game ||
                      group.game.participants.length !== 12
                    }
                    onClick={() =>
                      runAction(() =>
                        apiFetch(
                          `/groups/${group.id}/generate-teams`,
                          { method: "POST" }
                        )
                      )
                    }
                  >
                    Generate Teams
                  </button>
                )}

                {group.teams.length > 0 && (
                  <>
                    {isAdmin && (
                      <div className="team-edit-toolbar">
                        {!editingTeams ? (
                          <button
                            className="secondary-button"
                            onClick={() =>
                              setEditingTeams(true)
                            }
                          >
                            Adjust Teams
                          </button>
                        ) : (
                          <>
                            <span className="team-count-summary">
                              A: {teamCount("Team A")}/4 · B:{" "}
                              {teamCount("Team B")}/4 · C:{" "}
                              {teamCount("Team C")}/4
                            </span>

                            <button
                              className="primary-button"
                              onClick={saveTeamAdjustments}
                            >
                              Save Adjustments
                            </button>

                            <button
                              className="secondary-button"
                              onClick={() =>
                                setEditingTeams(false)
                              }
                            >
                              Cancel
                            </button>
                          </>
                        )}
                      </div>
                    )}

                    <div className="teams-grid">
                      {group.teams.map((team) => (
                        <div
                          className="team-box"
                          key={team.name}
                        >
                          <div className="team-header">
                            <h3>{team.name}</h3>
                            <span>
                              {editingTeams
                                ? `${teamCount(
                                    team.name
                                  )}/4 players`
                                : `Total ${team.total_rating}`}
                            </span>
                          </div>

                          {(editingTeams
                            ? group.teams
                                .flatMap(
                                  (item) => item.players
                                )
                                .filter(
                                  (player) =>
                                    teamDraft[player.id] ===
                                    team.name
                                )
                            : team.players
                          ).map((player) =>
                            editingTeams ? (
                              <div
                                className="team-player-edit-row"
                                key={player.id}
                              >
                                <span>
                                  {player.name} (
                                  {player.rating})
                                </span>

                                <select
                                  value={
                                    teamDraft[player.id]
                                  }
                                  onChange={(event) =>
                                    setTeamDraft(
                                      (previous) => ({
                                        ...previous,
                                        [player.id]:
                                          event.target.value,
                                      })
                                    )
                                  }
                                >
                                  <option value="Team A">
                                    Team A
                                  </option>
                                  <option value="Team B">
                                    Team B
                                  </option>
                                  <option value="Team C">
                                    Team C
                                  </option>
                                </select>
                              </div>
                            ) : (
                              <p key={player.id}>
                                {player.name} (
                                {player.rating})
                              </p>
                            )
                          )}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
