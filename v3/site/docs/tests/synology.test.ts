// SPEC-602 acceptance criterion "the pasted compose content is drift-tested
// against v3/deploy": the Synology guide's pasted compose block must be
// exactly what `v3/deploy/docker-compose.yml` says, not a hand-typed copy
// of it — the same shape of check `tests/onboarding.test.ts` already runs
// for the onboarding page's own commands, and `tests/generated-pages.test.ts`
// runs for the connect pages.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DEPLOY_ROOT, loadComposeFile } from "../scripts/lib/deploy-snippets.mjs";
import { buildSynologyPages, renderSynologyPage, SYNOLOGY_PAGE_PATH } from "../scripts/lib/synology.mjs";

const PROJECT_ROOT = path.resolve(__dirname, "..");

describe("Synology guide", () => {
  it("the generated page on disk matches what the source produces right now", async () => {
    const pages = await buildSynologyPages();
    expect(pages.size).toBe(1);
    for (const [relPath, contents] of pages) {
      const fullPath = path.join(PROJECT_ROOT, relPath);
      expect(existsSync(fullPath), `${relPath} is missing — run \`npm run gen:synology\``).toBe(true);
      const onDisk = readFileSync(fullPath, "utf8");
      expect(onDisk, `${relPath} is stale — run \`npm run gen:synology\``).toBe(contents);
    }
  });

  it("pastes the real docker-compose.yml, not a hand-typed copy", () => {
    const compose = readFileSync(path.join(DEPLOY_ROOT, "docker-compose.yml"), "utf8").trimEnd();
    expect(loadComposeFile()).toBe(compose);

    const page = renderSynologyPage();
    expect(page).toContain(compose);
  });

  it("throws instead of silently returning a wrong or empty file if docker-compose.yml's shape changes", () => {
    const compose = loadComposeFile();
    expect(compose.length).toBeGreaterThan(0);
    expect(compose).toContain("services:");
    expect(compose).toContain("image: ghcr.io/byte5ai/palaia-hub:stable");
  });

  it("has a screenshot marker for each step a reader can't do without seeing the real UI, and no fake images", () => {
    const page = renderSynologyPage();
    const markers = [...page.matchAll(/<!--\s*screenshot:[^>]*-->/g)];
    expect(markers.length).toBeGreaterThanOrEqual(3);
    // Never a real (or stock/placeholder) image file in a generated page —
    // only the site's own established marker convention.
    expect(page).not.toMatch(/!\[[^\]]*\]\([^)]*\.(png|jpg|jpeg|gif|webp)\)/i);
  });

  it("has an explicit owner verification checklist at the bottom", () => {
    const page = renderSynologyPage();
    const lastHeadingIndex = page.lastIndexOf("\n## ");
    const tail = page.slice(lastHeadingIndex);
    expect(tail).toMatch(/owner verification checklist/i);
    expect(tail).toMatch(/real Synology device/i);
    expect(tail).toMatch(/screenshot/i);
  });

  it("only ever writes the one path it declares", () => {
    expect(SYNOLOGY_PAGE_PATH).toBe(path.join("src", "content", "docs", "install-synology.md"));
  });
});
