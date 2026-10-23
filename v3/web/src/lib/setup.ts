/**
 * First-run setup state (issues 559, 561): read from the hub's
 * `/api/setup`, never kept in the browser, so a reload, a restart or a second
 * browser all see the same progress.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api, type SetupStatus } from "./api/client";

export const ONBOARDING_PATH = "/onboarding";

/** Open the setup wizard instead of the app while first-run setup is
 * unfinished. Checked once per page load, so someone who chose to leave the
 * wizard can still use the app until the next visit. */
export function useFirstRunRedirect(): void {
  const navigate = useNavigate();
  const location = useLocation();
  const checked = useRef(false);
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    if (location.pathname === ONBOARDING_PATH) return;
    let cancelled = false;
    api
      .setupStatus()
      .then((status) => {
        if (!cancelled && !status.completed)
          navigate(ONBOARDING_PATH, { replace: true });
      })
      // A hub that cannot answer is the shell's own error to show.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [location.pathname, navigate]);
}

export interface SetupState {
  status: SetupStatus | null;
  error: unknown;
  refresh: () => Promise<SetupStatus | null>;
}

/** The setup status, refreshed on demand and every `pollMs` while set. */
export function useSetupStatus(pollMs?: number): SetupState {
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const refresh = useCallback(async () => {
    try {
      const next = await api.setupStatus();
      setStatus(next);
      setError(null);
      return next;
    } catch (err) {
      setError(err);
      return null;
    }
  }, []);
  useEffect(() => {
    let cancelled = false;
    api
      .setupStatus()
      .then((next) => {
        if (cancelled) return;
        setStatus(next);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (!pollMs) return;
    const id = window.setInterval(() => void refresh(), pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, refresh]);
  return { status, error, refresh };
}

/** After a restart was requested: resolves once the hub went away and
 * answers its health check again, or `false` after `timeoutMs`. */
export async function waitForRestart(timeoutMs = 120_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  let wentDown = false;
  while (Date.now() < deadline) {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      if (response.ok && wentDown) return true;
      if (!response.ok) wentDown = true;
    } catch {
      wentDown = true;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }
  return false;
}
