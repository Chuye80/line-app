/**
 * The single door to the backend.
 *
 * Every request goes through here, which is what makes "view the app as
 * somebody else" a one-line change rather than a special case in each screen:
 * the simulated identity is attached to the outgoing request, so the whole app
 * behaves as that member without any component knowing about it.
 */

import { supabase } from "./supabase";

const API_URL =
  import.meta.env.VITE_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

// The developer panel deletes virtual members, wipes registrations, rewrites
// the schedule and can borrow another member's identity. It is only built into
// the page when explicitly switched on, and the backend refuses to serve the
// endpoints - and the impersonation header - unless it is too.
export const DEV_TOOLS_ENABLED =
  import.meta.env.VITE_ENABLE_DEV_TOOLS === "true";

const ACT_AS_HEADER = "X-Dev-Act-As";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/**
 * Read through holders rather than captured values so that a long-lived
 * callback or a polling timer never sends a stale token, and never keeps
 * sending requests as a member the developer has already stopped simulating.
 */
type Holders = {
  token: () => string | undefined;
  actAs: () => string | null;
};

let holders: Holders = { token: () => undefined, actAs: () => null };

export function configureApi(next: Holders) {
  holders = next;
}

async function errorFrom(response: Response) {
  try {
    const data = await response.json();
    return new ApiError(
      data.detail ?? data.message ?? "Action failed",
      response.status
    );
  } catch {
    return new ApiError("Action failed", response.status);
  }
}

async function request(path: string, options: RequestInit = {}) {
  const token = holders.token();

  if (!token) {
    throw new ApiError("No active session", 401);
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);

  const actAs = DEV_TOOLS_ENABLED ? holders.actAs() : null;

  if (actAs) {
    headers.set(ACT_AS_HEADER, actAs);
  }

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (response.status === 401) {
    // The session is gone. Ending it here stops every subsequent poll from
    // failing in the background with no way for the user to recover.
    await supabase.auth.signOut();
    throw new ApiError("Your session expired. Please log in again.", 401);
  }

  if (!response.ok) {
    throw await errorFrom(response);
  }

  return response;
}

export async function get<T>(path: string): Promise<T> {
  return (await request(path)).json();
}

export async function send<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown
): Promise<T | null> {
  const response = await request(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  if (response.status === 204) {
    return null;
  }

  return response.json().catch(() => null);
}

export const post = <T>(path: string, body?: unknown) =>
  send<T>("POST", path, body);
export const put = <T>(path: string, body?: unknown) =>
  send<T>("PUT", path, body);
export const del = <T>(path: string) => send<T>("DELETE", path);
