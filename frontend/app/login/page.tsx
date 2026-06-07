"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth";

type Mode = "signin" | "signup";

export default function LoginPage() {
  const { signIn, signUp, configured } = useAuth();
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      if (mode === "signin") {
        await signIn(email, password);
        // AppShell redirects to "/" once the session lands.
      } else {
        const { needsConfirmation } = await signUp(email, password);
        if (needsConfirmation) {
          setNotice("Account created. Check your email to confirm, then sign in.");
          setMode("signin");
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <span className="mark">D</span>
          <span className="brand-text">
            Doc<b>Forge</b>
          </span>
        </div>
        <h1 className="auth-title">
          {mode === "signin" ? "Sign in to your account" : "Create your account"}
        </h1>

        {!configured && (
          <div className="banner warn section" role="alert">
            Supabase isn’t configured. Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
            <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in <code>frontend/.env.local</code>.
          </div>
        )}
        {error && (
          <div className="banner warn section" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="banner info section" role="status">
            {notice}
          </div>
        )}

        <label className="field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
          />
        </label>

        <button className="btn btn-primary" type="submit" disabled={busy || !configured}>
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
        </button>

        <p className="auth-switch">
          {mode === "signin" ? (
            <>
              No account?{" "}
              <button type="button" className="linklike" onClick={() => setMode("signup")}>
                Create one
              </button>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <button type="button" className="linklike" onClick={() => setMode("signin")}>
                Sign in
              </button>
            </>
          )}
        </p>
      </form>
    </div>
  );
}
