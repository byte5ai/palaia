/**
 * The hub's *running* access mode, shared across the shell (issue 343).
 *
 * The sidebar's footer used to be hard-coded to one mode — an operator who
 * switched the hub to Public on the Access page kept reading the old name
 * on every screen. One tiny module-level store rather than a context
 * provider: `GET /api/info` is asked once per shell mount, and the Access
 * page calls `notifyModeChanged` with what the hub reports after a change,
 * so every subscriber re-renders without a second round trip.
 */
import { useEffect, useState } from "react";

import { api, type ModeChangeRequest } from "./api/client";

export type HubMode = "locked" | "cloud" | "open";

const MODES: readonly HubMode[] = ["locked", "cloud", "open"];

/** The name of each mode, everywhere in the dashboard (the config values
 * stay locked/cloud/open). */
export const MODE_LABEL: Record<HubMode, string> = {
  locked: "Private",
  cloud: "Cloud",
  open: "Public",
};

/** What each mode means for the person choosing it, in one line. */
export const MODE_OUTCOME: Record<HubMode, string> = {
  locked: "Only devices on your network or VPN. claude.ai and ChatGPT can't connect.",
  cloud: "AI apps can connect from the internet. The dashboard stays private.",
  open: "The dashboard is on the internet too. Requires sign-in and the security checklist.",
};

export function isHubMode(value: unknown): value is HubMode {
  return typeof value === "string" && (MODES as readonly string[]).includes(value);
}

/**
 * The change that makes palaia Private, sent alike by Settings › Access &
 * sign-in and the first-run setup (issue 588).
 *
 * - `keepDashboardSignIn`: the dashboard asked for the owner's password
 *   before. Private alone stops asking (`admin_session.sign_in_required` is
 *   off in Private unless it is set), so the setting is written explicitly.
 * - `signInServerOn`: palaia's sign-in server stays on. Its address
 *   (`oauth.issuer`) is what AI apps and the Claude Desktop extension sign in
 *   through and where a sign-in provider sends the browser back. In Private
 *   the public address answers nothing (the cloud entry refuses every
 *   request), so the address becomes the one this dashboard is open at, as
 *   the first-run setup sets it for a private hub. The public address stays
 *   saved (`public_url`), so switching back to Cloud offers it again.
 */
export function privateModeChange({
  keepDashboardSignIn,
  signInServerOn,
  origin,
}: {
  keepDashboardSignIn: boolean;
  signInServerOn: boolean;
  origin: string;
}): ModeChangeRequest {
  const body: ModeChangeRequest = { mode: "locked" };
  if (keepDashboardSignIn) body.dashboard_require_sign_in = true;
  if (signInServerOn) body.oauth_issuer = origin;
  return body;
}

const listeners = new Set<(mode: HubMode) => void>();
let known: HubMode | null = null;

/** Tell every mounted `useHubMode` what the hub is running now — the Access
 * page calls this with the `active_mode` the hub answers a change with. */
export function notifyModeChanged(mode: HubMode): void {
  known = mode;
  for (const listener of listeners) listener(mode);
}

/** `null` until the hub has answered once (or when it cannot be reached —
 * the indicator then shows nothing rather than a guess). */
export function useHubMode(): HubMode | null {
  const [mode, setMode] = useState<HubMode | null>(known);

  useEffect(() => {
    listeners.add(setMode);
    let cancelled = false;
    api
      .info()
      .then((info) => {
        if (!cancelled && isHubMode(info.mode)) notifyModeChanged(info.mode);
      })
      .catch(() => {
        // Unreachable hub: keep whatever is known (possibly nothing).
      });
    return () => {
      cancelled = true;
      listeners.delete(setMode);
    };
  }, []);

  return mode;
}

/** Test hook: forget the last known mode between tests. */
export function resetHubModeForTests(): void {
  known = null;
  listeners.clear();
}
