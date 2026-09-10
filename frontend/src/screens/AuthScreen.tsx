import { useState } from "react";
import type { FormEvent } from "react";
import { supabase } from "../supabase";

export function AuthScreen() {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");

    try {
      if (mode === "signup") {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: {
            data: { display_name: displayName.trim() || email.split("@")[0] },
          },
        });

        if (signUpError) {
          throw signUpError;
        }

        setNotice(
          "Account created. If email confirmation is enabled, confirm your email and then log in."
        );
        setMode("login");
      } else {
        const { error: loginError } = await supabase.auth.signInWithPassword({
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
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card" onSubmit={submit}>
        <h1>⚽ LineApp</h1>
        <p>
          {mode === "login"
            ? "Sign in to your football groups"
            : "Create your LineApp account"}
        </p>

        {mode === "signup" && (
          <label>
            Name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              required
            />
          </label>
        )}

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={6}
            required
          />
        </label>

        {error && <div className="error-box">{error}</div>}
        {notice && <div className="status-box pending">{notice}</div>}

        <button className="primary-button" type="submit" disabled={busy}>
          {mode === "login" ? "Log In" : "Sign Up"}
        </button>

        <button
          className="secondary-button"
          type="button"
          onClick={() => {
            setError("");
            setMode(mode === "login" ? "signup" : "login");
          }}
        >
          {mode === "login" ? "Create account" : "Back to login"}
        </button>
      </form>
    </div>
  );
}
