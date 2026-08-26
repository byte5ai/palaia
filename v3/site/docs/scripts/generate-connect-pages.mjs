#!/usr/bin/env node
// Regenerates every "Connect your AI" page from v3/web/src/lib/clients.ts
// and skills.ts. Run this after changing either source file — the drift
// test (scripts/check-generated.mjs) fails CI if you forget.
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildGeneratedPages } from "./lib/pages.mjs";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function main() {
  const pages = await buildGeneratedPages();
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
