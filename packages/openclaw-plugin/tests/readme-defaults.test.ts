/**
 * Issue #419: the README documented `memoryInject` as defaulting to `false`
 * while DEFAULT_CONFIG has had it `true`. Anyone reading the README believed
 * injection was opt-in when it is on out of the box.
 *
 * This pins the README's options block to DEFAULT_CONFIG so the two cannot
 * drift apart again silently.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DEFAULT_CONFIG, type PalaiaPluginConfig } from "../src/config";

const README = readFileSync(join(__dirname, "..", "README.md"), "utf8");

/** Keys the README's options block states a default for. */
const DOCUMENTED: (keyof PalaiaPluginConfig)[] = [
  "tier",
  "maxResults",
  "timeoutMs",
  "memoryInject",
  "maxInjectedChars",
];

describe("README option defaults", () => {
  it.each(DOCUMENTED)("documents the real default for %s", (key) => {
    const actual = DEFAULT_CONFIG[key];
    const expected = typeof actual === "string" ? `"${actual}"` : String(actual);
    const line = README.split("\n").find((l) => l.trimStart().startsWith(`${key}:`));
    expect(line, `README has no options line for ${key}`).toBeDefined();
    expect(line).toContain(`default: ${expected}`);
  });

  it("does not still call memory injection opt-in", () => {
    expect(DEFAULT_CONFIG.memoryInject).toBe(true);
    const feature = README.split("\n").find((l) => l.includes("HOT memory injection"));
    expect(feature).toBeDefined();
    expect(feature!.toLowerCase()).not.toContain("opt-in");
  });
});
