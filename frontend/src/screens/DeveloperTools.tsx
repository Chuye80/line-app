import { useIdentity } from "../identity";
import type { Group } from "../types";

/**
 * Developer tools, including "view the app as another member".
 *
 * The switcher only offers members with a real account, because a virtual
 * player has no identity to borrow. Choosing somebody changes what the app
 * asks the server for and nothing else: the signed-in session, its credentials
 * and every ownership record are left exactly as they were.
 */
export function DeveloperTools({
  group,
  isAdmin,
  busy,
  onSeedMembers,
  onCreateGame,
  onRegisterAll,
  onExpirePriority,
}: {
  group: Group | null;
  isAdmin: boolean;
  busy: boolean;
  onSeedMembers: (count: number) => void;
  onCreateGame: () => void;
  onRegisterAll: () => void;
  onExpirePriority: () => void;
}) {
  const identity = useIdentity();
  const accounts = group?.members.filter((member) => !member.is_virtual) ?? [];

  return (
    <>
      <section className="card">
        <h2>View app as</h2>
        <p className="empty-note">
          Simulates another member so you can check their registration, survey
          and game day screens. Your own login is untouched.
        </p>

        <div className="view-as-row">
          <label>
            View app as
            <select
              value={identity.membershipId ?? ""}
              onChange={(event) => {
                const membershipId = event.target.value;
                const member = accounts.find(
                  (item) => item.id === membershipId
                );

                identity.viewAs(membershipId || null, member?.name ?? null);
              }}
            >
              <option value="">Myself</option>
              {accounts.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                  {member.is_admin ? " (admin)" : ""}
                </option>
              ))}
            </select>
          </label>

          {identity.membershipId && (
            <button
              className="secondary-button"
              onClick={identity.returnToMyself}
            >
              Return to myself
            </button>
          )}
        </div>

        {accounts.length <= 1 && (
          <p className="empty-note">
            Only members with an account can be simulated. Virtual players have
            no login to borrow.
          </p>
        )}
      </section>

      <section className="card">
        <h2>Test data</h2>
        <p className="developer-warning">
          These actions delete and rewrite data in {group?.name ?? "this group"}.
        </p>

        <div className="dev-actions">
          <button
            disabled={!group || !isAdmin || busy}
            onClick={() => onSeedMembers(12)}
          >
            Fill to 12 members
          </button>

          <button
            disabled={!group || !isAdmin || busy}
            onClick={() => onSeedMembers(16)}
          >
            Fill to 16 members
          </button>

          <button
            disabled={!group || !isAdmin || busy}
            onClick={onCreateGame}
          >
            Create test game day
          </button>

          <button
            disabled={!group?.game || !isAdmin || busy}
            onClick={onRegisterAll}
          >
            Register everybody
          </button>

          <button
            disabled={!group?.game || !isAdmin || busy}
            onClick={onExpirePriority}
          >
            Expire subscriber priority
          </button>
        </div>
      </section>
    </>
  );
}
