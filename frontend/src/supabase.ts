import { createClient } from "@supabase/supabase-js";
import { parseAuthCallbackHash } from "./authRecovery";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

// Read the hash before the client initializes. Implicit recovery consumes it.
export const authCallback = parseAuthCallbackHash(
  typeof window === "undefined" ? "" : window.location.hash
);

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY"
  );
}

export const supabase = createClient(
  supabaseUrl,
  supabasePublishableKey
);
