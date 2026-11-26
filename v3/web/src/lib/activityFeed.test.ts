import { describe, expect, it } from "vitest";

import { buildFeed, titleFromPermalink } from "./activityFeed";
import type { VaultChangeEntry } from "./events";

const LIVE: VaultChangeEntry = {
  ts: 2_000,
  event: "memory.entry.created",
  vault: "work",
  permalink: "projects/website/release-process",
  data: { path: "projects/website/release-process.md" },
};

describe("buildFeed", () => {
  it("puts live events first, names the note, and skips loaded notes they already cover", () => {
    const feed = buildFeed(
      [LIVE],
      [
        {
          vault: "work",
          permalink: "projects/website/release-process",
          title: "Release process",
          modified: "2026-09-28T10:00:00Z",
        },
        { vault: "work", permalink: "howto/setup", title: "Setup guide", modified: "2026-09-28T09:00:00Z" },
      ] as never,
    );
    expect(feed.map((item) => [item.verb, item.title, item.vault])).toEqual([
      ["Created", "Release process", "work"],
      ["Saved", "Setup guide", "work"],
    ]);
    expect(feed[1].at).toBe(Date.parse("2026-09-28T09:00:00Z"));
  });

  it("says who made a change: the app, You for an edit outside palaia, nobody for palaia itself", () => {
    const live = (data: VaultChangeEntry["data"]): VaultChangeEntry => ({ ...LIVE, data });
    const feed = buildFeed(
      [live({ actor: "Claude Code CLI" }), live({ external: true }), live({})],
      [
        { vault: "work", permalink: "a", title: "A", modified: "", actor: "Codex" },
        { vault: "work", permalink: "b", title: "B", modified: "", actor: "human" },
        { vault: "work", permalink: "c", title: "C", modified: "", actor: "" },
        // An older hub sends no actor at all.
        { vault: "work", permalink: "d", title: "D", modified: "" },
      ],
    );
    expect(feed.map((item) => item.actor)).toEqual(["Claude Code CLI", "You", null, "Codex", "You", null, null]);
  });

  it("never shows a raw path: a name without a title becomes words", () => {
    expect(titleFromPermalink("inbox/invoice-numbering")).toBe("Invoice numbering");
    expect(titleFromPermalink("decisions/design_review.md")).toBe("Design review");
  });

  it("leaves the time out when a note carries none", () => {
    const [item] = buildFeed([], [{ vault: "work", permalink: "a", title: "A", modified: "" }] as never);
    expect(item.at).toBeNull();
  });

  it("caps the feed", () => {
    const loaded = Array.from({ length: 30 }, (_, i) => ({
      vault: "work",
      permalink: `n${i}`,
      title: `N${i}`,
      modified: "",
    }));
    expect(buildFeed([], loaded as never, 20)).toHaveLength(20);
  });
});
