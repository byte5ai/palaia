#!/usr/bin/env node
// The drift test SPEC-503's acceptance criteria demand: regenerate every
// "Connect your AI" page (and the Synology guide, SPEC-602) in memory and
// diff each against what is checked in. A red exit here means one of the
// sources changed (clients.ts, skills.ts, or docker-compose.yml) and
// someone forgot to regenerate — never means "the source of truth
// disagrees with itself", because both sides of every comparison come
// from the exact same render calls (scripts/lib/pages.mjs,
// scripts/lib/synology.mjs).
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildGeneratedPages } from "./lib/pages.mjs";
import { buildSynologyPages } from "./lib/synology.mjs";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function main() {
  // Each entry owns the pages one generator built, plus the one command
  // that regenerates just those — so a stale page always points at the
  // right fix, not a generic "regenerate something" shrug.
  const generators = [
    { pages: await buildGeneratedPages(), command: "npm run gen:connect", label: "connect" },
    { pages: await buildSynologyPages(), command: "npm run gen:synology", label: "synology" },
  ];

  const problems = [];
  let total = 0;

  for (const { pages, command, label } of generators) {
    total += pages.size;
    for (const [relPath, contents] of pages) {
      const fullPath = path.join(PROJECT_ROOT, relPath);
      if (!existsSync(fullPath)) {
        problems.push(`missing: ${relPath} (run \`${command}\`)`);
        continue;
      }
      const onDisk = readFileSync(fullPath, "utf8");
      if (onDisk !== contents) {
        problems.push(`stale: ${relPath} does not match its source (run \`${command}\`) [${label}]`);
      }
    }
  }

  if (problems.length > 0) {
    console.error("Generated pages are out of date:\n");
    for (const problem of problems) console.error(`  - ${problem}`);
    console.error("\nRegenerate with the command each line above names and commit the result.");
    process.exitCode = 1;
    return;
  }
  console.log(`Generated pages are up to date (${total} page(s)).`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
