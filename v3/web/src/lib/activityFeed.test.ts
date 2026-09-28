import { describe, expect, it } from "vitest";

import { buildFeed } from "./activityFeed";
import type { VaultChangeEntry } from "./events";

const LIVE: VaultChangeEntry = {
  ts: 2_000,
  event: "memory.entry.updated",
  vault: "work",
  permalink: "projects/billing",
  data: { path: "projects/billing.md" },
};

describe("buildFeed", () => {
  it("puts live events first and skips loaded notes they already cover", () => {
    const feed = buildFeed(
      [LIVE],
      [
        { vault: "work", permalink: "projects/billing", title: "Billing", modified: "2026-09-28T10:00:00Z" },
        { vault: "work", permalink: "howto/setup", title: "Setup", modified: "2026-09-28T09:00:00Z" },
      ],
    );
    expect(feed.map((item) => item.text)).toEqual([
      "Updated projects/billing in work",
      "Changed howto/setup in work",
    ]);
    expect(feed[0].path).toBe("projects/billing.md");
    expect(feed[1].at).toBe(Date.parse("2026-09-28T09:00:00Z"));
  });

  it("leaves the time out when a note carries none", () => {
    const [item] = buildFeed([], [{ vault: "work", permalink: "a", title: "A", modified: "" }]);
    expect(item.at).toBeNull();
  });

  it("caps the feed", () => {
    const loaded = Array.from({ length: 30 }, (_, i) => ({
      vault: "work",
      permalink: `n${i}`,
      title: `N${i}`,
      modified: "",
    }));
    expect(buildFeed([], loaded, 20)).toHaveLength(20);
  });
});
