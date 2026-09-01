#!/usr/bin/env node
// Broken-internal-link check for the built site (SPEC-503 deliverable #4:
// "broken internal links fail the build"). Runs as `npm run build`'s own
// postbuild step, over the actual output astro build produced — so a
// route that fails to render, or a link nobody updated after a page moved,
// fails CI rather than shipping as a 404 a reader finds first.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST = path.join(PROJECT_ROOT, "dist");

// The site is served under a base path (astro.config.mjs `base`), so its links
// are `/docs/...` while the build output stays flat under dist/ (Astro does not
// nest the physical files under the base). Read the base from the config —
// rather than duplicating the literal — and strip it before resolving a link
// against dist.
const CONFIG = readFileSync(path.join(PROJECT_ROOT, "astro.config.mjs"), "utf8");
const BASE = (CONFIG.match(/\bBASE\s*=\s*["'`]([^"'`]+)["'`]/)?.[1] ?? "").replace(/\/$/, "");

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full));
    else if (entry.name.endsWith(".html")) out.push(full);
  }
  return out;
}

// Astro's static output is directory-per-route (`/foo/` -> `foo/index.html`);
// a route resolves if either the exact file or its directory-index form
// exists.
function routeExists(routePath) {
  let clean = routePath.split("#")[0].split("?")[0];
  // Links carry the base prefix; the flat dist output does not — strip it.
  if (BASE && (clean === BASE || clean.startsWith(`${BASE}/`))) {
    clean = clean.slice(BASE.length) || "/";
  }
  if (clean === "" || clean === "/") return existsSync(path.join(DIST, "index.html"));
  const relative = clean.replace(/^\//, "");
  const asFile = path.join(DIST, relative);
  const asIndex = path.join(DIST, relative, "index.html");
  const asHtml = asFile.endsWith(".html") ? asFile : `${asFile}.html`;
  return existsSync(asIndex) || existsSync(asHtml) || existsSync(asFile);
}

function internalHrefs(html) {
  const hrefs = [];
  const re = /\shref="([^"]+)"/g;
  let match;
  while ((match = re.exec(html))) {
    const href = match[1];
    if (href.startsWith("/") && !href.startsWith("//")) hrefs.push(href);
  }
  return hrefs;
}

function main() {
  if (!existsSync(DIST) || !statSync(DIST).isDirectory()) {
    console.error(`check-links: no build output at ${DIST} — run \`astro build\` first.`);
    process.exitCode = 1;
    return;
  }

  const pages = walk(DIST);
  if (pages.length === 0) {
    console.error("check-links: build output has no .html files — something is very wrong.");
    process.exitCode = 1;
    return;
  }

  const broken = [];
  for (const pagePath of pages) {
    const html = readFileSync(pagePath, "utf8");
    const pageRoute = "/" + path.relative(DIST, pagePath).replace(/index\.html$/, "").replace(/\\/g, "/");
    for (const href of internalHrefs(html)) {
      if (!routeExists(href)) {
        broken.push({ page: pageRoute, href });
      }
    }
  }

  if (broken.length > 0) {
    console.error(`Broken internal link(s) found (${broken.length}):\n`);
    for (const { page, href } of broken) {
      console.error(`  ${page} -> ${href}`);
    }
    process.exitCode = 1;
    return;
  }
  console.log(`check-links: ${pages.length} page(s) checked, no broken internal links.`);
}

main();
