/**
 * Issue 384: the two screens that poll (a connect panel waiting for a
 * client's first call, Home waiting for the first memory) asked every 3 s
 * for as long as the tab stayed open — on a hub that never records a
 * first memory, forever. They now back off: quick while the answer is
 * likely imminent, then rarer, capped so a forgotten tab costs one request
 * every half minute instead of twenty.
 */

export const POLL_INITIAL_MS = 3_000;
export const POLL_MAX_MS = 30_000;
const POLL_GROWTH = 1.5;

/** The delay to wait after a poll that was itself waited for `previousMs`. */
export function nextPollDelay(previousMs: number): number {
  return Math.min(Math.round(previousMs * POLL_GROWTH), POLL_MAX_MS);
}
