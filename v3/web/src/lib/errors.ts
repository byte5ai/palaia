/**
 * SPEC-504 first-run funnel audit finding: every network-failure fallback
 * in the wizard/connect flow used to read "Could not reach the hub." or
 * "Could not create the vault — check the hub's own logs." — true, but
 * neither one names a fix a first-timer can actually act on ("logs" is
 * jargon a non-developer does not know how to find). One shared helper so
 * the fix wording lives in one place: a server-sent `detail` string (every
 * server-side error on the funnel path already names its own fix — see
 * `palaia_hub.vault.errors.VaultConfigError`'s call sites) is trusted
 * as-is; a network failure (no response at all — the hub is down, or the
 * browser is pointed at the wrong address) gets a concrete next step
 * instead of a dead end.
 */
import { ApiError } from "./api/client";

const UNREACHABLE_HINT =
  "Could not reach the hub — check that its container is still running and that " +
  "this browser is on the address it printed at startup, then try again.";

/** A user-facing message for `err`, always ending in something to try next. */
export function describeApiError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string } | undefined;
    if (body?.detail) return body.detail;
    return `The hub answered with an unexpected error (status ${err.status}). ` +
      "Try again — if it keeps happening, restart the hub container.";
  }
  return UNREACHABLE_HINT;
}
