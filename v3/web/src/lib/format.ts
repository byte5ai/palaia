/** Human-scale formatting helpers shared by screens (issue 399 moved
 * `formatAge` here from `ConnectPanel.tsx`, which exports a component). */

export function formatAge(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

/** "3 h ago" / "in 5 h" for a time in epoch seconds — relative to now,
 * rounded to a human unit (issue 438's backup screen: last and next run). */
export function formatRelative(epochSeconds: number, nowMs = Date.now()): string {
  const delta = epochSeconds - nowMs / 1000;
  const seconds = Math.abs(delta);
  let amount: string;
  if (seconds < 60) amount = "less than a minute";
  else if (seconds < 3600) amount = `${Math.round(seconds / 60)} min`;
  else if (seconds < 86400) amount = `${Math.round(seconds / 3600)} h`;
  else amount = `${Math.round(seconds / 86400)} d`;
  return delta >= 0 ? `in ${amount}` : `${amount} ago`;
}
