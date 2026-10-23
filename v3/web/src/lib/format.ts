/**
 * Times and counts the way people say them (system.md §3): "2 min ago",
 * "Updated 23 Oct, 15:35", "1 of 9 connected". The exact value goes into a
 * tooltip (`exactTime`), never into the text.
 */

function toMs(value: string | number | Date): number {
  if (value instanceof Date) return value.getTime();
  if (typeof value === "number") return value;
  return new Date(value).getTime();
}

/** "just now", "2 min ago", "3 h ago", "2 d ago" for a past moment (an ISO
 * string, a Date, or milliseconds since the epoch). */
export function timeAgo(value: string | number | Date, nowMs = Date.now()): string {
  const seconds = Math.max(0, (nowMs - toMs(value)) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

/** The earlier name of `timeAgo`, for an ISO timestamp. */
export function formatAge(iso: string): string {
  return timeAgo(iso);
}

/** "3 h ago" / "in 5 h" for a time in epoch seconds — past or future. */
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

/** "23 Oct, 15:35" in the reader's own locale; the year only when it is
 * not this year. */
export function shortDateTime(value: string | number | Date, nowMs = Date.now()): string {
  const date = new Date(toMs(value));
  if (Number.isNaN(date.getTime())) return "";
  const sameYear = date.getFullYear() === new Date(nowMs).getFullYear();
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "23 Oct 2026" — a date without a time. */
export function shortDate(value: string | number | Date): string {
  const date = new Date(toMs(value));
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/** The full, exact moment — for a `title` tooltip. */
export function exactTime(value: string | number | Date): string {
  const date = new Date(toMs(value));
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
}

/** "1 memory", "3 memories". */
export function count(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "10m16s" (the hub's compact form) → "10 min 16 s". */
export function spokenDuration(compact: string): string {
  const parts: string[] = [];
  for (const [, amount, unit] of compact.matchAll(/(\d+)\s*([dhms])/g)) {
    parts.push(`${amount} ${unit === "m" ? "min" : unit}`);
  }
  return parts.length > 0 ? parts.join(" ") : compact;
}
