/**
 * Issue 322: the dashboard's docs links once pointed at a placeholder
 * domain long after the docs site had a real one. `DOCS_BASE_URL` is now
 * pinned to the astro config itself — the same file the site is built
 * from, read here as text (Vite's `?raw`, the way skills.ts reads the
 * shipped SKILL.md files) rather than a second copy of its values.
 */
import { describe, expect, it } from "vitest";

import astroConfig from "../../../site/docs/astro.config.mjs?raw";
import { DOCS_BASE_URL, docsUrl } from "./docs";

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

describe("DOCS_BASE_URL", () => {
  it("equals astro.config.mjs's `site` + `base`, so the two cannot drift", () => {
    const site = /^\s*site:\s*"([^"]+)"/m.exec(astroConfig)?.[1];
    const baseName = /^\s*base:\s*([A-Za-z_$][\w$]*|"[^"]*")\s*,?\s*$/m.exec(astroConfig)?.[1];
    expect(site, "astro.config.mjs no longer declares `site:`").toBeTruthy();
    expect(baseName, "astro.config.mjs no longer declares `base:`").toBeTruthy();
    if (!site || !baseName) throw new Error("unreachable");

    // `base` is either a string literal or a `const NAME = "..."` declared
    // earlier in the same file (today: `const BASE = "/docs"`).
    const base = baseName.startsWith('"')
      ? baseName.slice(1, -1)
      : new RegExp(`^const ${baseName}\\s*=\\s*"([^"]*)";`, "m").exec(astroConfig)?.[1];
    expect(base, `could not resolve astro.config.mjs's base (${baseName})`).toBeDefined();

    const expected = stripTrailingSlash(`${stripTrailingSlash(site)}/${(base ?? "").replace(/^\/+/, "")}`);
    expect(DOCS_BASE_URL).toBe(expected);
  });

  it("has no trailing slash, so docsUrl's leading-slash paths join cleanly", () => {
    expect(DOCS_BASE_URL).not.toMatch(/\/$/);
    expect(docsUrl("/first-shared-memory/")).toBe("https://palaia.byte5.ai/docs/first-shared-memory/");
  });
});
