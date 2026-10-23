/**
 * The Overview's activity feed: live memory events, plus — on first load —
 * the notes that changed before the page was opened
 * (`GET /api/vaults/recent-activity`). Each line reads "Created **Release
 * process** · work · 2 min ago": what happened, to which note, in which
 * memory, when — never a raw path.
 */
import type { RecentChange } from "./api/client";
import type { VaultChangeEntry } from "./events";

const CHANGE_VERB: Record<string, string> = {
  "memory.entry.created": "Created",
  "memory.entry.updated": "Updated",
  "memory.entry.deleted": "Deleted",
  "memory.entry.moved": "Moved",
};

export interface FeedItem {
  key: string;
  /** "Created", "Updated", "Deleted", "Moved". */
  verb: string;
  /** The note's title, or a readable form of its name. */
  title: string;
  /** The memory it belongs to. */
  vault: string | null;
  /** When it happened, in ms since the epoch; `null` when unknown. */
  at: number | null;
}

/** "projects/website/release-process" → "Release process". */
export function titleFromPermalink(permalink: string): string {
  const last = permalink.split("/").filter(Boolean).pop() ?? permalink;
  const words = last.replace(/\.md$/i, "").replace(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : permalink;
}

/** Live events first, then the recently changed notes the page loaded with,
 * minus any a live event already covers; at most `limit` lines. */
export function buildFeed(live: VaultChangeEntry[], loaded: RecentChange[], limit = 20): FeedItem[] {
  const items: FeedItem[] = live.map((entry, index) => ({
    key: `live-${entry.ts}-${index}`,
    verb: CHANGE_VERB[entry.event] ?? "Updated",
    title: titleFromPermalink(entry.permalink ?? entry.data.path ?? "a note"),
    vault: entry.vault,
    at: entry.ts,
  }));
  const seen = new Set(live.map((entry) => `${entry.vault}/${entry.permalink}`));
  for (const change of loaded) {
    if (seen.has(`${change.vault}/${change.permalink}`)) continue;
    const at = change.modified ? Date.parse(change.modified) : NaN;
    items.push({
      key: `loaded-${change.vault}-${change.permalink}`,
      // The listing doesn't say whether a note is new or changed.
      verb: "Saved",
      title: change.title || titleFromPermalink(change.permalink),
      vault: change.vault,
      at: Number.isNaN(at) ? null : at,
    });
  }
  return items.slice(0, limit);
}
