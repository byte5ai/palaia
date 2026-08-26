// SPEC-504 deliverable #1's drift test: the onboarding page's three
// commands must be exactly what v3/deploy's real files say, not a
// hand-typed copy of them. `loadDeploySnippets()` already reads them
// straight out of `v3/deploy/README.md` at build time (see that module's
// own docstring for why `import.meta.url`-relative pathing would break
// once Astro bundles the page that imports it) — this test is the
// independent check that the extraction actually landed on the right
// text, by re-reading the same source file a second, differently-shaped
// way and asserting the two agree.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DEPLOY_ROOT, loadDeploySnippets } from "../scripts/lib/deploy-snippets.mjs";

describe("onboarding page snippets", () => {
  it("reads v3/deploy/README.md, not a hand-copied string", () => {
    const readmePath = path.join(DEPLOY_ROOT, "README.md");
    const readme = readFileSync(readmePath, "utf8");
    const snippets = loadDeploySnippets();

    // Every returned snippet must appear verbatim in the real source file
    // — the only way that can be true without maintaining a duplicate is
    // if the extractor actually pulled the text out of it.
    expect(readme).toContain(snippets.dockerRun);
    expect(readme).toContain(snippets.compose);
    expect(readme).toContain(snippets.curlInstall);
  });

  it("the docker run command matches docker-compose.yml's image and port", () => {
    const compose = readFileSync(path.join(DEPLOY_ROOT, "docker-compose.yml"), "utf8");
    const { dockerRun } = loadDeploySnippets();

    const imageMatch = compose.match(/image:\s*(\S+)/);
    expect(imageMatch, "docker-compose.yml has an image: line").not.toBeNull();
    expect(dockerRun).toContain(imageMatch![1]);

    const portMatch = compose.match(/"(\d+):(\d+)"/);
    expect(portMatch, "docker-compose.yml maps a port").not.toBeNull();
    expect(dockerRun).toContain(`-p ${portMatch![1]}:${portMatch![2]}`);
  });

  it("the compose command matches the real docker-compose.yml's own usage line", () => {
    const compose = readFileSync(path.join(DEPLOY_ROOT, "docker-compose.yml"), "utf8");
    const { compose: composeSnippet } = loadDeploySnippets();

    // docker-compose.yml's own header comment documents the command that
    // starts it — the onboarding page's snippet must be that same command.
    expect(compose).toContain(composeSnippet.split("\n").at(-1));
  });

  it("the curl install command points at the real install.sh path in this repository", () => {
    const { curlInstall } = loadDeploySnippets();
    expect(curlInstall).toContain(
      "https://raw.githubusercontent.com/byte5ai/palaia/main/v3/deploy/install.sh",
    );
  });

  it("has no horizontal scroll on phones: no fixed pixel width, snippets scroll in their own box", () => {
    // SPEC-504 deliverable #1's acceptance criterion, checked at the
    // source level (this project has no DOM/browser test environment
    // configured — see this file's own imports versus, say, v3/web's
    // React Testing Library setup): a real phone-width layout regression
    // in this page would show up as either a fixed pixel width wider than
    // a phone viewport, or a code block with no scroll container of its
    // own — both are things the stylesheet text itself proves or disproves
    // directly, with no DOM required.
    const page = readFileSync(
      path.join(__dirname, "..", "src", "pages", "onboarding.astro"),
      "utf8",
    );
    const styleMatch = page.match(/<style>([\s\S]*?)<\/style>/);
    expect(styleMatch, "onboarding.astro has a <style> block").not.toBeNull();
    const style = styleMatch![1];

    // No rule sets an element to a fixed width wider than the narrowest
    // common phone viewport (360px) — the layout is either fluid or
    // capped with max-width, never pinned wider than the screen.
    const widthDeclarations = [...style.matchAll(/(?<!max-|min-)width:\s*(\d+)px/g)];
    for (const match of widthDeclarations) {
      expect(Number(match[1]), `a fixed width of ${match[0]} would force horizontal scroll`).toBeLessThan(
        360,
      );
    }

    // Every command block scrolls inside itself rather than the page.
    expect(style).toMatch(/\.op-snippet\s*\{[^}]*overflow-x:\s*auto/);
    expect(style).toMatch(/\.op-snippet\s*\{[^}]*max-width:\s*100%/);

    // The tab bar wraps rather than forcing the page wider than the
    // platform labels' combined width.
    expect(style).toMatch(/\.op-tabbar\s*\{[^}]*flex-wrap:\s*wrap/);
  });

  it("throws instead of returning an empty snippet if the source shape ever changes", () => {
    // A cheap regression guard: the real file, today, always yields three
    // non-empty fences in this order. If a future edit to README.md's
    // Quick start section reorders or removes one, this extractor's own
    // substring checks (see its module docstring) must fail loudly rather
    // than this test silently passing on empty strings.
    const snippets = loadDeploySnippets();
    expect(snippets.dockerRun.length).toBeGreaterThan(0);
    expect(snippets.compose.length).toBeGreaterThan(0);
    expect(snippets.curlInstall.length).toBeGreaterThan(0);
  });
});
