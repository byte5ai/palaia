#!/usr/bin/env node
// Regenerates the Synology Container Manager walkthrough from
// v3/deploy/docker-compose.yml. Run this after changing that file — the
// drift check (scripts/check-generated.mjs) fails CI if you forget.
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSynologyPages } from "./lib/synology.mjs";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function main() {
  const pages = await buildSynologyPages();
  for (const [relPath, contents] of pages) {
    const fullPath = path.join(PROJECT_ROOT, relPath);
    mkdirSync(path.dirname(fullPath), { recursive: true });
    writeFileSync(fullPath, contents, "utf8");
  }
  console.log(`Wrote ${pages.size} generated page(s) under ${PROJECT_ROOT}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
