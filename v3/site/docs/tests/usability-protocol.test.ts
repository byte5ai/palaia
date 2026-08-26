// SPEC-506 deliverable #3's own acceptance criterion: "usability protocol
// steps verified against the onboarding page (every step it asks of the
// tester exists)." `v3/docs/usability-test-protocol.md` is not part of
// this Astro project's own content collection (it's a plain repo doc, so
// an owner can hand it to a tester without a build step) — this test reads
// it as text and checks two things a future edit could silently break:
//
// 1. every internal link the protocol sends a tester to
//    (`/install/`, `/connect/clients/claude-code-cli/`, ...) resolves to a
//    real page in this site's content collection — never a step that
//    points at UI that doesn't exist;
// 2. every wizard step name the protocol's own "observer-only notes"
//    section quotes (`Onboarding.tsx`'s `STEP_NAMES`) still matches the
//    real component, so a future step rename doesn't leave the protocol
//    quoting stale labels.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const PROJECT_ROOT = path.resolve(__dirname, "..");
const V3_ROOT = path.resolve(PROJECT_ROOT, "..", "..");
const PROTOCOL_PATH = path.join(V3_ROOT, "docs", "usability-test-protocol.md");
const CONTENT_DOCS = path.join(PROJECT_ROOT, "src", "content", "docs");
const ONBOARDING_TSX = path.join(
  V3_ROOT,
  "web",
  "src",
  "routes",
  "onboarding",
  "Onboarding.tsx",
);

function protocolText(): string {
  return readFileSync(PROTOCOL_PATH, "utf8");
}

/** Every `/foo/` or `/foo/bar/`-shaped markdown link target in the protocol. */
function linkedRoutes(text: string): string[] {
  const routes = new Set<string>();
  const linkPattern = /\]\((\/[a-z0-9\-/]*\/)\)/g;
  for (const match of text.matchAll(linkPattern)) {
    routes.add(match[1]);
  }
  return [...routes];
}

/** A root-relative route (e.g. `/connect/clients/claude-code-cli/`) to the
 * content-collection file it should resolve to, Astro/Starlight's own
 * convention: `/foo/` -> `foo.md` or `foo/index.md`, `/` -> `index.md`. */
function routeToContentFile(route: string): string {
  const trimmed = route.replace(/^\/|\/$/g, "");
  if (trimmed === "") return path.join(CONTENT_DOCS, "index.md");
  return path.join(CONTENT_DOCS, trimmed + ".md");
}

function routeExists(route: string): boolean {
  const direct = routeToContentFile(route);
  if (existsSync(direct)) return true;
  const trimmed = route.replace(/^\/|\/$/g, "");
  const asIndex = path.join(CONTENT_DOCS, trimmed, "index.md");
  return existsSync(asIndex);
}

describe("usability test protocol", () => {
  it("exists as a hand-to-a-tester page in v3/docs", () => {
    expect(existsSync(PROTOCOL_PATH)).toBe(true);
  });

  it("every linked route resolves to a real page in the docs site", () => {
    const routes = linkedRoutes(protocolText());
    expect(routes.length).toBeGreaterThan(0);
    for (const route of routes) {
      expect(routeExists(route), `${route} has no matching page under src/content/docs`).toBe(
        true,
      );
    }
  });

  it("references the four tasks the onboarding page can actually complete", () => {
    const text = protocolText();
    // The four tasks map onto the exact real, wired surfaces
    // test_s7_spec504_first_run_funnel.py / test_spec506_phase5_gate.py
    // already prove work end to end: install, connect a client, save +
    // recall, connect a second client.
    expect(text).toMatch(/Task 1 — Install it/);
    expect(text).toMatch(/Task 2 — Connect your AI/);
    expect(text).toMatch(/Task 3 — Save and retrieve one memory/);
    expect(text).toMatch(/Task 4 — Connect a second AI/);
  });

  it("defines 'unaided' explicitly, not by implication", () => {
    const text = protocolText();
    expect(text).toMatch(/## 4\. What counts as "unaided"/);
    // Markdown line-wraps the phrase across source lines; normalize
    // whitespace before checking rather than requiring one physical line.
    const normalized = text.toLowerCase().replace(/\s+/g, " ");
    expect(normalized).toContain("no palaia-specific help from a person");
  });

  it("names where findings get filed", () => {
    const text = protocolText();
    expect(text).toMatch(/## 5\. Where findings get filed/);
    expect(text).toContain("byte5ai/palaia");
    expect(text).toContain("client-matrix-results.md");
  });

  it("quotes the real wizard step names from Onboarding.tsx, not stale ones", () => {
    const component = readFileSync(ONBOARDING_TSX, "utf8");
    const stepNamesMatch = component.match(/STEP_NAMES = \[([\s\S]*?)\n\];/);
    expect(stepNamesMatch, "Onboarding.tsx's STEP_NAMES block has changed shape").not.toBeNull();
    const stepNames = [...stepNamesMatch![1].matchAll(/name:\s*"([^"]+)"/g)].map((m) => m[1]);
    expect(stepNames).toEqual(["Owner account", "Access mode", "First vault", "First client"]);

    const protocol = protocolText();
    for (const name of stepNames) {
      expect(protocol, `protocol's observer notes should quote "${name}"`).toContain(name);
    }
  });

  it("the observer-only note about steps 1-2 being cosmetic still matches Onboarding.tsx's own admission", () => {
    const component = readFileSync(ONBOARDING_TSX, "utf8");
    // If Onboarding.tsx ever wires step 1/2 for real, its own docstring
    // (this exact phrase) is what would change first — this test fails
    // loudly rather than leaving the protocol's observer note stale.
    expect(component).toContain("are NOT wired to anything");
  });
});
