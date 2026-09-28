/**
 * Home's activity feed: live vault events, plus — on first load — the notes
 * that changed before the page was opened (`GET /api/vaults/recent-activity`).
 */
import type { RecentChange } from "./api/client";
import type { VaultChangeEntry } from "./events";

const CHANGE_VERB: Record<string, string> = {
  "memory.entry.created": "Created",
  "memory.entry.updated": "Updated",
  "memory.entry.deleted": "Deleted",
  "memory.entry.moved": "Moved",
};

/** One line of the activity feed: a live event, or — on first load — a
 * recently changed note from `GET /api/vaults/recent-activity`. */
export interface FeedItem {
  key: string;
  text: string;
  path: string | null;
  /** When it happened, in ms since the epoch; `null` when unknown. */
  at: number | null;
}

/** Live events first, then the recently changed notes the page loaded with,
 * minus any a live event already covers; at most `limit` lines. */
export function buildFeed(
  live: VaultChangeEntry[],
  loaded: RecentChange[],
  limit = 20,
): FeedItem[] {
  const items: FeedItem[] = live.map((entry, index) => ({
    key: `live-${entry.ts}-${index}`,
    text: describeChange(entry) + (entry.vault ? ` in ${entry.vault}` : ""),
    path: entry.data.path ?? null,
    at: entry.ts,
  }));
  const seen = new Set(live.map((entry) => `${entry.vault}/${entry.permalink}`));
  for (const change of loaded) {
    if (seen.has(`${change.vault}/${change.permalink}`)) continue;
    const at = change.modified ? Date.parse(change.modified) : NaN;
    items.push({
      key: `loaded-${change.vault}-${change.permalink}`,
      text: `Changed ${change.permalink} in ${change.vault}`,
      path: null,
      at: Number.isNaN(at) ? null : at,
    });
  }
  return items.slice(0, limit);
}

export function describeChange(entry: VaultChangeEntry): string {
  const verb = CHANGE_VERB[entry.event] ?? "Changed";
  const target = entry.permalink ?? entry.data.path ?? "a note";
  return `${verb} ${target}`;
}

