/**
 * The hub's *running* access mode, shared across the shell (issue 343).
 *
 * The sidebar's footer used to be hard-coded to "Your network only" — an
 * operator who switched the hub to Open on the Access page kept reading
 * that on every screen. One tiny module-level store rather than a context
 * provider: `GET /api/info` is asked once per shell mount, and the Access
 * page calls `notifyModeChanged` with what the hub reports after a change,
 * so every subscriber re-renders without a second round trip.
 */
import { useEffect, useState } from "react";

import { api } from "./api/client";

export type HubMode = "locked" | "cloud" | "open";

const MODES: readonly HubMode[] = ["locked", "cloud", "open"];

/** The footer's wording per mode — the same words the Access page uses. */
export const MODE_LABEL: Record<HubMode, string> = {
  locked: "Your network only",
  cloud: "Cloud",
  open: "Open",
};

export function isHubMode(value: unknown): value is HubMode {
  return typeof value === "string" && (MODES as readonly string[]).includes(value);
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
