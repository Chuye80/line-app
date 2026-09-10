import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  IdentityContext,
  STORAGE_KEY,
  readStoredIdentity,
} from "./identity";
import type { SimulatedIdentity } from "./identity";

/** Holds the developer's "view as" choice. See ./identity.ts for the rules. */
export function IdentityProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState(readStoredIdentity);

  const viewAs = useCallback(
    (membershipId: string | null, name: string | null) => {
      const next = { id: membershipId, name };
      setStored(next);

      try {
        if (membershipId) {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
        } else {
          window.localStorage.removeItem(STORAGE_KEY);
        }
      } catch {
        // A browser refusing local storage only costs persistence across a
        // refresh, which is a convenience rather than a requirement.
      }
    },
    []
  );

  const value = useMemo<SimulatedIdentity>(
    () => ({
      membershipId: stored.id,
      name: stored.name,
      viewAs,
      returnToMyself: () => viewAs(null, null),
    }),
    [stored, viewAs]
  );

  return (
    <IdentityContext.Provider value={value}>
      {children}
    </IdentityContext.Provider>
  );
}
