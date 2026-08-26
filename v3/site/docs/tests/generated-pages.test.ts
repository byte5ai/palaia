// SPEC-503 deliverable #2's drift test: every "Connect your AI" page must
// match what regenerating from v3/web/src/lib/clients.ts and skills.ts
// produces right now. This is the same comparison scripts/check-generated.mjs
// makes, wired into `npm test` (and so into CI) rather than left as a
// script someone has to remember to run by hand.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { buildGeneratedPages } from "../scripts/lib/pages.mjs";

const PROJECT_ROOT = path.resolve(__dirname, "..");

describe("generated connect pages", () => {
  it("match what the source (clients.ts / skills.ts) generates right now", async () => {
    const expected: Map<string, string> = await buildGeneratedPages();
    expect(expected.size).toBeGreaterThan(0);

    for (const [relPath, contents] of expected) {
      const fullPath = path.join(PROJECT_ROOT, relPath);
      expect(existsSync(fullPath), `${relPath} is missing — run \`npm run gen:connect\``).toBe(
        true,
      );
      const onDisk = readFileSync(fullPath, "utf8");
      expect(onDisk, `${relPath} is stale — run \`npm run gen:connect\``).toBe(contents);
    }
  });

  it("covers every client in the catalog, guided/download/notYet alike", async () => {
    const pages = await buildGeneratedPages();
    const clientPageCount = [...pages.keys()].filter((p) =>
      p.includes(path.join("connect", "clients")),
    ).length;
    // clients.ts currently declares 9 entries (SPEC-110's §6-matrix
    // catalog) — this guards against the extractor silently dropping one,
    // not against the catalog growing (raising this number is expected).
    expect(clientPageCount).toBeGreaterThanOrEqual(9);
  });

  it("every generated page has non-empty title and description frontmatter", async () => {
    const pages = await buildGeneratedPages();
    for (const [relPath, contents] of pages) {
      expect(contents, relPath).toMatch(/^---\n/);
      expect(contents, relPath).toMatch(/\ntitle: "[^"]+"\n/);
      expect(contents, relPath).toMatch(/\ndescription: "[^"]+"\n/);
    }
  });
});
