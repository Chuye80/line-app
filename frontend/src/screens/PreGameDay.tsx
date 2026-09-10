import { useMemo, useState } from "react";
import { Countdown } from "../components/Countdown";
import type { Group, Member } from "../types";

const TEAM_NAMES = ["Team A", "Team B", "Team C"];
const REQUIRED_PLAYERS = 12;

/**
 * Everything that happens before the football starts: who is playing, which
 * team they are on, and the button that begins the day.
 *
 * This is the only place registration is administered. Once the day is live the
 * app moves to the live screen and this one is out of the navigation, which is
 * why nothing here has to reason about a game in progress.
 */
export function PreGameDay({
  group,
  isAdmin,
  ownMembershipId,
  busy,
  onSchedule,
  onDeleteGame,
  onRegister,
  onUnregister,
  onGenerateTeams,
  onSaveTeams,
  onStartDay,
}: {
  group: Group;
  isAdmin: boolean;
  ownMembershipId: string | null;
  busy: boolean;
  onSchedule: (kickoff: string, priorityHours: number) => void;
  onDeleteGame: () => void;
  onRegister: (membershipId: string) => void;
  onUnregister: (membershipId: string) => void;
  onGenerateTeams: () => void;
  onSaveTeams: (
    assignments: Array<{ membership_id: string; team_name: string }>
  ) => Promise<void>;
  onStartDay: () => void;
}) {
  const game = group.game;

  const registeredIds = useMemo(
    () => new Set(game?.participants.map((player) => player.id) ?? []),
    [game]
  );
  const waitingIds = useMemo(
    () => new Set(game?.waiting_list.map((player) => player.id) ?? []),
    [game]
  );

  if (!game) {
    return (
      <section className="card">
        <h2>Next Game Day</h2>
        <p className="empty-note">No game day has been scheduled yet.</p>

        {isAdmin ? (
          <ScheduleForm busy={busy} onSchedule={onSchedule} />
        ) : (
          <p className="empty-note">An admin will schedule the next one.</p>
        )}
      </section>
    );
  }

  const teamsReady = group.teams.length === TEAM_NAMES.length;
  const squadFull = game.participants.length === REQUIRED_PLAYERS;

  return (
    <>
      <section className="card">
        <div className="section-header">
          <div>
            <h2>Next Game Day</h2>
            <span>{new Date(game.game_datetime).toLocaleString()}</span>
          </div>

          {isAdmin && (
            <button className="text-danger-button" onClick={onDeleteGame}>
              Delete
            </button>
          )}
        </div>

        <Countdown opensAt={game.regular_registration_opens} />

        <div className="progress-row">
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{
                width: `${Math.min(
                  100,
                  (game.participants.length / REQUIRED_PLAYERS) * 100
                )}%`,
              }}
            />
          </div>
          <span>
            <strong>{game.participants.length}</strong>/{REQUIRED_PLAYERS}{" "}
            registered
            {game.waiting_list.length > 0 &&
              ` · ${game.waiting_list.length} waiting`}
          </span>
        </div>

        {ownMembershipId && (
          <MyRegistration
            membershipId={ownMembershipId}
            registered={registeredIds.has(ownMembershipId)}
            waiting={waitingIds.has(ownMembershipId)}
            busy={busy}
            onRegister={onRegister}
            onUnregister={onUnregister}
          />
        )}
      </section>

      <section className="card">
        <h2>Registration</h2>

        <div className="registration-columns">
          <div>
            <h3>Playing ({game.participants.length})</h3>
            {game.participants.length === 0 && (
              <p className="empty-note">Nobody yet.</p>
            )}
            {game.participants.map((player, index) => (
              <RegistrationRow
                key={player.id}
                index={index}
                player={player}
                canControl={isAdmin || player.id === ownMembershipId}
                busy={busy}
                action="remove"
                onAction={onUnregister}
              />
            ))}
          </div>

          <div>
            <h3>Waiting list ({game.waiting_list.length})</h3>
            {game.waiting_list.length === 0 && (
              <p className="empty-note">Nobody waiting.</p>
            )}
            {game.waiting_list.map((player, index) => (
              <RegistrationRow
                key={player.id}
                index={index}
                player={player}
                canControl={isAdmin || player.id === ownMembershipId}
                busy={busy}
                action="remove"
                onAction={onUnregister}
              />
            ))}
          </div>
        </div>

        {isAdmin && (
          <details className="add-players">
            <summary>Register somebody else</summary>

            <div className="member-chips">
              {group.members
                .filter(
                  (member) =>
                    !registeredIds.has(member.id) && !waitingIds.has(member.id)
                )
                .map((member) => (
                  <button
                    key={member.id}
                    className="choice-chip"
                    disabled={busy}
                    onClick={() => onRegister(member.id)}
                  >
                    + {member.name}
                  </button>
                ))}
            </div>
          </details>
        )}
      </section>

      <TeamsSection
        group={group}
        isAdmin={isAdmin}
        busy={busy}
        squadFull={squadFull}
        teamsReady={teamsReady}
        onGenerateTeams={onGenerateTeams}
        onSaveTeams={onSaveTeams}
        onStartDay={onStartDay}
      />
    </>
  );
}

function MyRegistration({
  membershipId,
  registered,
  waiting,
  busy,
  onRegister,
  onUnregister,
}: {
  membershipId: string;
  registered: boolean;
  waiting: boolean;
  busy: boolean;
  onRegister: (membershipId: string) => void;
  onUnregister: (membershipId: string) => void;
}) {
  if (registered || waiting) {
    return (
      <div className="my-registration">
        <span className={waiting ? "status-box pending" : "status-box in"}>
          {waiting ? "You are on the waiting list" : "You are playing"}
        </span>

        <button
          className="secondary-button"
          disabled={busy}
          onClick={() => onUnregister(membershipId)}
        >
          Drop out
        </button>
      </div>
    );
  }

  return (
    <div className="my-registration">
      <button
        className="primary-button"
        disabled={busy}
        onClick={() => onRegister(membershipId)}
      >
        Register me
      </button>
    </div>
  );
}

function RegistrationRow({
  index,
  player,
  canControl,
  busy,
  onAction,
}: {
  index: number;
  player: Member;
  canControl: boolean;
  busy: boolean;
  action: "remove";
  onAction: (membershipId: string) => void;
}) {
  return (
    <div className="registration-row">
      <span className="registration-index">{index + 1}</span>
      <span className="registration-name">
        {player.name}
        {player.is_subscriber && <span className="tag">sub</span>}
      </span>

      {canControl && (
        <button
          className="text-danger-button"
          disabled={busy}
          onClick={() => onAction(player.id)}
        >
          Remove
        </button>
      )}
    </div>
  );
}

function TeamsSection({
  group,
  isAdmin,
  busy,
  squadFull,
  teamsReady,
  onGenerateTeams,
  onSaveTeams,
  onStartDay,
}: {
  group: Group;
  isAdmin: boolean;
  busy: boolean;
  squadFull: boolean;
  teamsReady: boolean;
  onGenerateTeams: () => void;
  onSaveTeams: (
    assignments: Array<{ membership_id: string; team_name: string }>
  ) => Promise<void>;
  onStartDay: () => void;
}) {
  const [editing, setEditing] = useState(false);

  // Unsaved edits, or null while the saved line-up is shown as-is. Deriving the
  // displayed draft instead of mirroring the server response into state is what
  // stops a background refresh from discarding an edit in progress.
  const [draftOverride, setDraftOverride] = useState<Record<
    string,
    string
  > | null>(null);

  const savedDraft = useMemo(() => {
    const draft: Record<string, string> = {};

    group.teams.forEach((team) => {
      team.players.forEach((player) => {
        draft[player.id] = team.name;
      });
    });

    return draft;
  }, [group.teams]);

  const draft = draftOverride ?? savedDraft;
  const count = (teamName: string) =>
    Object.values(draft).filter((value) => value === teamName).length;

  const players = useMemo(
    () => group.teams.flatMap((team) => team.players),
    [group.teams]
  );

  async function save() {
    await onSaveTeams(
      Object.entries(draft).map(([membership_id, team_name]) => ({
        membership_id,
        team_name,
      }))
    );

    setDraftOverride(null);
    setEditing(false);
  }

  return (
    <section className="card">
      <div className="section-header">
        <div>
          <h2>Teams</h2>
          <span>
            {teamsReady
              ? "Balanced by rating. Adjust before kick-off if you need to."
              : "Generated once twelve players have registered."}
          </span>
        </div>

        {isAdmin && !teamsReady && (
          <button
            className="primary-button"
            disabled={busy || !squadFull}
            title={squadFull ? undefined : "Twelve players have to register first"}
            onClick={onGenerateTeams}
          >
            Generate Teams
          </button>
        )}
      </div>

      {!teamsReady ? (
        <p className="empty-note">No teams yet.</p>
      ) : (
        <>
          {isAdmin && (
            <div className="team-edit-toolbar">
              {editing ? (
                <>
                  <span className="team-count-summary">
                    {TEAM_NAMES.map((name) => `${name.slice(-1)}: ${count(name)}/4`).join(
                      " · "
                    )}
                  </span>

                  <button
                    className="primary-button"
                    disabled={
                      busy || TEAM_NAMES.some((name) => count(name) !== 4)
                    }
                    onClick={save}
                  >
                    Save
                  </button>

                  <button
                    className="secondary-button"
                    onClick={() => {
                      setDraftOverride(null);
                      setEditing(false);
                    }}
                  >
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <button
                    className="secondary-button"
                    onClick={() => setEditing(true)}
                  >
                    Adjust Teams
                  </button>

                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={onGenerateTeams}
                  >
                    Regenerate
                  </button>
                </>
              )}
            </div>
          )}

          <div className="teams-grid">
            {group.teams.map((team) => (
              <div className="team-box" key={team.name}>
                <div className="team-header">
                  <h3>{team.name}</h3>
                  <span>
                    {editing
                      ? `${count(team.name)}/4`
                      : `Avg ${team.average_rating.toFixed(1)}`}
                  </span>
                </div>

                {(editing
                  ? players.filter((player) => draft[player.id] === team.name)
                  : team.players
                ).map((player) =>
                  editing ? (
                    <div className="team-player-edit-row" key={player.id}>
                      <span>
                        {player.name} ({player.rating})
                      </span>

                      <select
                        value={draft[player.id]}
                        onChange={(event) =>
                          setDraftOverride({
                            ...draft,
                            [player.id]: event.target.value,
                          })
                        }
                      >
                        {TEAM_NAMES.map((name) => (
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
          </div>

          {isAdmin && (
            <div className="start-day-row">
              <button
                className="primary-button start-button"
                disabled={busy || editing}
                onClick={onStartDay}
              >
                Start Game Day
              </button>
              <span className="empty-note">
                Registration closes and the matches are laid out.
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ScheduleForm({
  busy,
  onSchedule,
}: {
  busy: boolean;
  onSchedule: (kickoff: string, priorityHours: number) => void;
}) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("20:00");
  const [priorityHours, setPriorityHours] = useState(24);

  return (
    <div className="form-panel">
      <div className="form-row">
        <label>
          Date
          <input
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>

        <label>
          Kickoff
          <input
            type="time"
            value={time}
            onChange={(event) => setTime(event.target.value)}
          />
        </label>
      </div>

      <label>
        Subscriber priority
        <select
          value={priorityHours}
          onChange={(event) => setPriorityHours(Number(event.target.value))}
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
        disabled={busy || !date || !time}
        onClick={() =>
          // The picker returns a wall-clock time with no zone. Sending it as-is
          // made the server read it as UTC, so a kickoff chosen as 20:00 in
          // Israel was stored as 23:00.
          onSchedule(new Date(`${date}T${time}`).toISOString(), priorityHours)
        }
      >
        Schedule Game Day
      </button>
    </div>
  );
}
