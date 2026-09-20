/**
 * Pins docs/prompt-caching.md against the code it describes (Issue #199).
 *
 * The prompt-caching trade-off page quotes plugin defaults and names the exact
 * injection points. If either drifts, the doc becomes wrong — and a wrong doc
 * about cost is worse than none.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { DEFAULT_CONFIG } from "../src/config.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..", "..");
const doc = readFileSync(join(repoRoot, "docs", "prompt-caching.md"), "utf8");
const engineSrc = readFileSync(join(here, "..", "src", "context-engine.ts"), "utf8");
const hooksSrc = readFileSync(join(here, "..", "src", "hooks", "index.ts"), "utf8");

/** Defaults the doc states verbatim, with the text it uses to state them. */
const DOCUMENTED_DEFAULTS: Array<{ key: keyof typeof DEFAULT_CONFIG; value: unknown; text: string }> = [
  { key: "maxInjectedChars", value: 4000, text: "default 4000 characters" },
  { key: "maxResults", value: 10, text: "default 10" },
  { key: "recallRecencyBoost", value: 0.3, text: "`recallRecencyBoost: 0.3`" },
  { key: "manualEntryBoost", value: 1.3, text: "`manualEntryBoost: 1.3`" },
  { key: "recallMode", value: "query", text: '`recallMode: "query"`' },
  { key: "memoryInject", value: true, text: "`memoryInject: true`" },
  { key: "showMemorySources", value: true, text: "default true" },
];

describe("docs/prompt-caching.md", () => {
  for (const { key, value, text } of DOCUMENTED_DEFAULTS) {
    it(`documents ${String(key)} in sync with DEFAULT_CONFIG`, () => {
      expect(DEFAULT_CONFIG[key]).toBe(value);
      expect(doc).toContain(text);
    });
  }

  it("describes the injection points that actually exist", () => {
    // ContextEngine path writes into the system prompt.
    expect(engineSrc).toContain("systemPromptAddition");
    // Legacy hook path prepends to the user message and toggles a system suffix.
    expect(hooksSrc).toContain("prependContext");
    expect(hooksSrc).toContain("appendSystemContext");
    expect(doc).toContain("systemPromptAddition");
    expect(doc).toContain("prependContext");
    expect(doc).toContain("appendSystemContext");
  });

  it("is right that memoryInject also gates session briefing delivery", () => {
    // Both delivery points sit behind config.memoryInject; if that ever changes,
    // the "Option A" section must be rewritten.
    expect(engineSrc).toContain("if (!config.memoryInject) {");
    expect(hooksSrc).toContain("if (config.memoryInject) {");
  });
});
