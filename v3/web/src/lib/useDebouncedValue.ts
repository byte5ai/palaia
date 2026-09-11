/**
 * Issue 384: every search box used to fire a request per keystroke with no
 * cancellation, so a slow answer for "a" could land after the fast one
 * for "abc" and overwrite it. Screens debounce the *value* with this hook
 * and abort the previous request in the effect that reads it.
 */
import { useEffect, useState } from "react";

/** How long a search box waits after the last keystroke before asking the hub. */
export const SEARCH_DEBOUNCE_MS = 250;

/** How long the Agents screen waits after an SSE burst (heartbeats arrive
 * per agent) before refetching once for all of them. */
export const AGENT_REFRESH_COALESCE_MS = 400;

/** `value`, but only once it has held still for `delayMs`. The very first
 * render returns `value` as-is, so a mount-time fetch is not delayed. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), delayMs);
    return () => window.clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}
