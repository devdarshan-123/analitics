import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, post } from "../lib/api";
import type { AuthStatus } from "../types";

export function Login() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const status = await post<AuthStatus>("/auth/login", { password });
      qc.setQueryData(["auth"], status);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-surface p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
            <rect width="32" height="32" rx="7" fill="var(--accent)" />
            <path d="M8 22l5-6 4 3 7-9" stroke="white" strokeWidth="2.6" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <h1 className="text-lg font-semibold text-ink">Analytics Dashboard</h1>
        </div>
        <label htmlFor="password" className="text-sm font-medium text-ink-2">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoFocus
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-1.5 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink focus:border-accent focus:outline-none"
        />
        {error && (
          <p role="alert" className="mt-2 text-sm text-bad">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !password} className="mt-4 w-full rounded-lg bg-accent py-2 text-sm font-medium text-accent-ink disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="mt-4 text-xs text-muted">Uses DASHBOARD_PASSWORD from the server's .env.</p>
      </form>
    </main>
  );
}
