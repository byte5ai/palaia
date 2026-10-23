// The docs site's Starlight colours and fonts are generated from the same
// v3/design/tokens.json as the dashboard's tokens.css. This fails when
// src/styles/palaia-tokens.css was edited by hand or tokens.json changed
// without running the generator.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const GENERATOR = path.resolve(HERE, "../../../design/gen-tokens.mjs");

describe("palaia-tokens.css", () => {
  it("matches v3/design/tokens.json", () => {
    let problem = "";
    try {
      execFileSync(process.execPath, [GENERATOR, "--check"], { encoding: "utf8", stdio: "pipe" });
    } catch (error) {
      problem = String((error as { stderr?: string }).stderr || error);
    }
    expect(problem).toBe("");
  });
});
