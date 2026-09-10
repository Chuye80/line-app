/**
 * "View the app as somebody else", for development only.
 *
 * The simulated identity lives here and nowhere else. Screens ask who the
 * current user is and get an answer; none of them know or care whether that
 * answer came from the session or from the developer switch. That is what keeps
 * the feature out of the rest of the codebase - there is no `if (simulating)`
 * anywhere else.
 *
 * The real session is never touched. Nothing is written to Supabase, no
 * credential changes and no ownership moves: the choice is a membership id in
 * this browser's local storage, sent as a request header that the backend only
 * honours when developer endpoints are switched on and the caller administers
 * the group in question.
 */

import { createContext, useContext } from "react";
import { DEV_TOOLS_ENABLED } from "./api";

// Deliberately named as developer state so it can never be mistaken for a
// stored credential.
export const STORAGE_KEY = "lineapp.dev.viewAsMembershipId";

export type StoredIdentity = { id: string | null; name: string | null };

export type SimulatedIdentity = {
  /** The membership being simulated, or null when viewing as yourself. */
  membershipId: string | null;
  /** Shown in the banner. Resolved by the caller from the member list. */
  name: string | null;
  viewAs: (membershipId: string | null, name: string | null) => void;
  returnToMyself: () => void;
};

export const IdentityContext = createContext<SimulatedIdentity>({
  membershipId: null,
  name: null,
  viewAs: () => {},
  returnToMyself: () => {},
});

export function readStoredIdentity(): StoredIdentity {
  if (!DEV_TOOLS_ENABLED) {
    return { id: null, name: null };
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : { id: null, name: null };
  } catch {
    return { id: null, name: null };
  }
}

export function useIdentity() {
  return useContext(IdentityContext);
}
