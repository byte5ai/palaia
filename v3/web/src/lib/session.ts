/**
 * Who is signed in, for the shell (SPEC-401 deliverable #6).
 *
 * One small hook rather than a context: exactly one place in the app renders
 * this (the topbar's sign-out control), and everything else finds out about
 * an expired session the moment a real call comes back 401 — the API client
 * turns that into a single redirect to the hub's sign-in page, so there is
 * no session state to keep in sync across screens.
 */
import { useCallback, useEffect, useState } from "react";

import type { SessionState } from "./api/client";
import { api } from "./api/client";

export interface SessionView {
  /** `null` until the first answer arrives, or when the hub has no sign-in
   * server at all (nothing to show, nothing to sign out of). */
  session: SessionState | null;
  signOut: () => Promise<void>;
}

/** Initials for the avatar: "Ada Lovelace" -> "AL", "owner" -> "OW". */
export function initialsFor(username: string | null): string {
  const name = (username ?? "").trim();
  if (!name) return "PA";
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

export function useSession(): SessionView {
  const [session, setSession] = useState<SessionState | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .session()
      .then((state) => {
        if (!cancelled) setSession(state);
      })
      .catch(() => {
        // A hub with no sign-in server at all 404s this; a hub whose gate is
        // closed answers 401, and the API client has already started the one
        // redirect to its sign-in page. Either way there is no sign-out
        // control to show, which is what leaving this null does.
        if (!cancelled) setSession(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    const target = session?.sign_in_url ?? "/";
    try {
      await api.signOut();
    } finally {
      // Reload through the sign-in door either way: if the request failed,
      // the session may still be live, and the honest thing is to let the
      // hub decide rather than to render a signed-out shell over it.
      window.location.assign(target);
    }
  }, [session]);

  return { session, signOut };
}
