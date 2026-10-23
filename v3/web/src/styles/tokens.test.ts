/// <reference types="node" />
// tokens.css is generated from v3/design/tokens.json by
// v3/design/gen-tokens.mjs (the docs site's palaia-tokens.css comes from the
// same file). This fails when either generated file was edited by hand, or
// tokens.json changed without running `npm run gen:tokens`.
//
// The generator runs as a child process rather than being imported: the
// dashboard's Docker build type-checks src/ with only v3/web copied in, so
// nothing under src/ may import a module from outside v3/web.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// vitest runs from v3/web (and jsdom gives import.meta.url an http scheme).
const GENERATOR = resolve(process.cwd(), "../design/gen-tokens.mjs");
const tokensCss = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

describe("design tokens", () => {
  it("the generated token files match tokens.json", () => {
    let problem = "";
    try {
      execFileSync(process.execPath, [GENERATOR, "--check"], { encoding: "utf8", stdio: "pipe" });
    } catch (error) {
      problem = String((error as { stderr?: string }).stderr || error);
    }
    expect(problem).toBe("");
  });

  it("switches to dark under the system preference unless pinned light, and under data-theme", () => {
    expect(tokensCss).toContain("@media (prefers-color-scheme: dark)");
    expect(tokensCss).toContain(':root:not([data-theme="light"])');
    expect(tokensCss).toContain(':root[data-theme="dark"]');
  });
});
