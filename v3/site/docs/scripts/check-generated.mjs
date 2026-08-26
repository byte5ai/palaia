#!/usr/bin/env node
// The drift test SPEC-503's acceptance criteria demand: regenerate every
// "Connect your AI" page in memory and diff it against what is checked
// in. A red exit here means clients.ts or skills.ts changed and someone
// forgot `npm run gen:connect` — never means "the source of truth
// disagrees with itself", because both sides of this comparison come
// from the exact same render call (scripts/lib/pages.mjs).
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildGeneratedPages } from "./lib/pages.mjs";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function main() {
  const expected = await buildGeneratedPages();
  const problems = [];

  for (const [relPath, contents] of expected) {
    const fullPath = path.join(PROJECT_ROOT, relPath);
    if (!existsSync(fullPath)) {
      problems.push(`missing: ${relPath} (run \`npm run gen:connect\`)`);
      continue;
    }
    const onDisk = readFileSync(fullPath, "utf8");
    if (onDisk !== contents) {
      problems.push(`stale: ${relPath} does not match clients.ts/skills.ts — regenerate it`);
    }
  }

  if (problems.length > 0) {
    console.error("Generated connect pages are out of date:\n");
    for (const problem of problems) console.error(`  - ${problem}`);
    console.error("\nRun `npm run gen:connect` from v3/site/docs and commit the result.");
    process.exitCode = 1;
    return;
  }
  console.log(`Generated connect pages are up to date (${expected.size} page(s)).`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
