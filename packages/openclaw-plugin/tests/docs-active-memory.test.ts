/**
 * Consistency guard for docs/openclaw-active-memory.md (#198).
 *
 * The chapter tells users which tool names to put into a host config and which
 * defaults apply. Both are facts about this package, so they are pinned here:
 * rename a tool or change a default and this test fails with the doc.
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { registerTools } from "../src/tools.js";
import { DEFAULT_CONFIG } from "../src/config.js";

const PKG_DIR = resolve(__dirname, "..");
const DOC = readFileSync(
  resolve(PKG_DIR, "../../docs/openclaw-active-memory.md"),
  "utf8"
);
const TOOLS_SRC = readFileSync(resolve(PKG_DIR, "src/tools.ts"), "utf8");

/** Collect the tools registerTools() actually registers. */
function registeredTools(): Record<string, { def: any; opts?: any }> {
  const tools: Record<string, { def: any; opts?: any }> = {};
  registerTools(
    {
      registerTool(def: any, opts?: any) {
        tools[def.name] = { def, opts };
      },
    } as any,
    DEFAULT_CONFIG
  );
  return tools;
}

describe("docs/openclaw-active-memory.md", () => {
  it("names every registered tool", () => {
    for (const name of Object.keys(registeredTools())) {
      expect(DOC).toContain(`\`${name}\``);
    }
  });

  it("names no tool that is not registered", () => {
    const registered = new Set(Object.keys(registeredTools()));
    const claimed = new Set(
      [...DOC.matchAll(/`(memory_[a-z_]+)`/g)].map((m) => m[1])
    );
    for (const name of claimed) {
      expect(registered).toContain(name);
    }
  });

  it("documents memory_write as opt-in while it is registered optional", () => {
    expect(registeredTools()["memory_write"].opts).toEqual({ optional: true });
    expect(DOC).toMatch(/memory_write[\s\S]{0,120}opt-in/);
  });

  it("quotes the real defaults in the Setup A snippet", () => {
    const shown = ["tier", "maxResults", "timeoutMs", "memoryInject"] as const;
    for (const key of shown) {
      const value = DEFAULT_CONFIG[key];
      const literal = typeof value === "string" ? `"${value}"` : String(value);
      expect(DOC).toContain(`"${key}": ${literal}`);
    }
  });

  it("quotes the real CLI-fallback timeout", () => {
    const match = TOOLS_SRC.match(/timeoutMs:\s*(\d+)\s*\}\)/);
    expect(match, "memory_search CLI fallback timeout not found").not.toBeNull();
    const seconds = Number(match![1]) / 1000;
    expect(DOC).toContain(`${seconds} s timeout`);
  });
});
