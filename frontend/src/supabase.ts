import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

/**
 * Missing configuration is reported through the UI rather than by throwing
 * during module evaluation, which rendered a blank white page with the reason
 * visible only in the developer console.
 */
export const configurationError =
  !supabaseUrl || !supabasePublishableKey
    ? "Missing VITE_SUPABASE_URL or VITE_SUPABASE_PUBLISHABLE_KEY. Copy frontend/.env.example to frontend/.env and fill it in."
    : null;

export const supabase = createClient(
  supabaseUrl ?? "http://localhost",
  supabasePublishableKey ?? "missing-key"
);
