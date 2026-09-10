import { useState } from "react";
import type { FormEvent } from "react";
import type { Group, JoinRequest, Member } from "../types";

export type MemberDraft = {
  name: string;
  rating: number;
  is_subscriber: boolean;
  is_admin: boolean;
};

/**
 * Who is in the group.
 *
 * Membership, ratings and join requests belong here rather than beside the
 * football, so this screen leaves the navigation entirely once a game day is
 * in progress.
 */
export function GroupScreen({
  group,
  isAdmin,
  ownMembershipId,
  joinRequests,
  busy,
  onSaveMember,
  onDeleteMember,
  onApproveRequest,
  onDeclineRequest,
  onLeaveGroup,
}: {
  group: Group;
  isAdmin: boolean;
  ownMembershipId: string | null;
  joinRequests: JoinRequest[];
  busy: boolean;
  onSaveMember: (draft: MemberDraft, existing: Member | null) => Promise<void>;
  onDeleteMember: (member: Member) => void;
  onApproveRequest: (requestId: string) => void;
  onDeclineRequest: (requestId: string) => void;
  onLeaveGroup: () => void;
}) {
  const [editing, setEditing] = useState<Member | null>(null);
  const [showForm, setShowForm] = useState(false);

  function startAdd() {
    setEditing(null);
    setShowForm(true);
  }

  function startEdit(member: Member) {
    setEditing(member);
    setShowForm(true);
  }

  return (
    <>
      {isAdmin && joinRequests.length > 0 && (
        <section className="card">
          <h2>Join Requests</h2>

          {joinRequests.map((request) => (
            <div className="request-row" key={request.id}>
              <strong>{request.user_name}</strong>

              <div className="request-actions">
                <button
                  className="primary-button"
                  disabled={busy}
                  onClick={() => onApproveRequest(request.id)}
                >
                  Approve
                </button>

                <button
                  className="secondary-button"
                  disabled={busy}
                  onClick={() => onDeclineRequest(request.id)}
                >
                  Decline
                </button>
              </div>
            </div>
          ))}
        </section>
      )}

      <section className="card">
        <div className="section-header">
          <div>
            <h2>Members</h2>
            <span>{group.members.length} in the group</span>
          </div>

          {isAdmin && (
            <button className="primary-button" onClick={startAdd}>
              + Add Player
            </button>
          )}
        </div>

        {showForm && isAdmin && (
          <MemberForm
            key={editing?.id ?? "new"}
            existing={editing}
            busy={busy}
            onCancel={() => setShowForm(false)}
            onSave={async (draft) => {
              await onSaveMember(draft, editing);
              setShowForm(false);
            }}
          />
        )}

        <div className="member-list">
          {group.members.map((member) => (
            <div className="member-row" key={member.id}>
              <div className="member-main">
                <strong>
                  {member.name}
                  {member.id === ownMembershipId && (
                    <span className="tag">you</span>
                  )}
                </strong>

                <div className="member-details">
                  Rating {member.rating}
                  {member.is_subscriber && " · Subscriber"}
                  {member.is_admin && " · Admin"}
                  {member.is_virtual && " · Virtual"}
                </div>
              </div>

              {isAdmin && (
                <div className="member-actions">
                  <button
                    className="secondary-button"
                    onClick={() => startEdit(member)}
                  >
                    Edit
                  </button>

                  <button
                    className="text-danger-button"
                    disabled={busy}
                    onClick={() => onDeleteMember(member)}
                  >
                    Delete
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Leave {group.name}</h2>
        <p className="empty-note">
          Your goals and results stay in the group's history.
        </p>
        <button className="text-danger-button" onClick={onLeaveGroup}>
          Leave Group
        </button>
      </section>
    </>
  );
}

function MemberForm({
  existing,
  busy,
  onCancel,
  onSave,
}: {
  existing: Member | null;
  busy: boolean;
  onCancel: () => void;
  onSave: (draft: MemberDraft) => Promise<void>;
}) {
  const [name, setName] = useState(existing?.name ?? "");
  const [rating, setRating] = useState(existing?.rating ?? 3);
  const [subscriber, setSubscriber] = useState(existing?.is_subscriber ?? false);
  const [admin, setAdmin] = useState(existing?.is_admin ?? false);

  async function submit(event: FormEvent) {
    event.preventDefault();

    if (!name.trim()) {
      return;
    }

    await onSave({
      name: name.trim(),
      rating,
      is_subscriber: subscriber,
      is_admin: admin,
    });
  }

  return (
    <form className="member-form" onSubmit={submit}>
      <h3>{existing ? `Edit ${existing.name}` : "Add Player"}</h3>

      <div className="form-row">
        <label>
          Name
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={Boolean(existing?.user_id)}
            required
          />
        </label>

        <label>
          Rating
          <select
            value={rating}
            onChange={(event) => setRating(Number(event.target.value))}
          >
            {[1, 2, 3, 4, 5].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="checkbox-row">
        <label>
          <input
            type="checkbox"
            checked={subscriber}
            onChange={(event) => setSubscriber(event.target.checked)}
          />
          Subscriber
        </label>

        {/* A virtual player has no account to sign in with, so it can never act
            as an administrator. */}
        {existing && !existing.is_virtual ? (
          <label>
            <input
              type="checkbox"
              checked={admin}
              onChange={(event) => setAdmin(event.target.checked)}
            />
            Admin
          </label>
        ) : (
          <span className="checkbox-hint">
            Virtual players cannot be administrators
          </span>
        )}
      </div>

      <div className="form-actions">
        <button className="primary-button" type="submit" disabled={busy}>
          Save
        </button>
        <button className="secondary-button" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
