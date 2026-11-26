/** What the command palette (`shell/CommandPalette.tsx`) shares with its
 * triggers and its tests. */

/** A note search starts at two characters: one letter matches everything. */
export const NOTE_QUERY_MIN = 2;
/** The best notes across all memories; the Memories page has the full list. */
export const NOTE_RESULT_LIMIT = 8;

/** The path that opens one note in its memory (read by the Memories page). */
export function notePath(memory: string, permalink: string): string {
  return `/memories?memory=${encodeURIComponent(memory)}&note=${encodeURIComponent(permalink)}`;
}

/** Every word of the query appears in the label or the keywords. */
export function matchesQuery(command: { label: string; keywords?: string }, query: string): boolean {
  const haystack = `${command.label} ${command.keywords ?? ""}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

/** The shortcut as this computer's keyboard prints it. */
export function paletteShortcut(): { label: string; aria: string } {
  const apple = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  return apple ? { label: "⌘K", aria: "Meta+K" } : { label: "Ctrl K", aria: "Control+K" };
}
