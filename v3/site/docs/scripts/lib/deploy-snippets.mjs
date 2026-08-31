// SPEC-504 deliverable #1's drift test, made structurally impossible to
// fail silently: the onboarding page never retypes an install command —
// every snippet it shows is read straight out of v3/deploy's real files at
// build time, the same "extract, don't copy" rule extract.mjs already
// applies to the connect pages' client commands. If v3/deploy/README.md's
// Quick start section ever changes shape, this throws instead of quietly
// handing back the wrong (or an empty) block — `check-generated.mjs`-style
// honesty, applied to code fences instead of whole pages.
import { readFileSync } from "node:fs";
import path from "node:path";

// Resolved from `process.cwd()`, not `import.meta.url`: this module is
// imported by `src/pages/onboarding.astro`, which Vite bundles into a
// chunk under `dist/` at build time — `import.meta.url` there points at
// that *output* location, not this file's real path in the source tree,
// so a path relative to it would silently resolve somewhere under `dist/`
// instead of `v3/deploy`. `astro build`/`astro dev` are always run with
// this project (`v3/site/docs`) as the working directory (see the v3-ci.yml
// docs-site job's own `working-directory`), so `process.cwd()` is the
// stable anchor here — the same one `scripts/check-links.mjs` and
// `scripts/check-generated.mjs` use for `PROJECT_ROOT`, those two just via
// `import.meta.url` instead because they run standalone, never bundled.
// v3/site/docs -> v3/site -> v3 -> v3/deploy
export const DEPLOY_ROOT = path.resolve(process.cwd(), "../../deploy");

const FENCE_RE = /```bash\n([\s\S]*?)```/g;

function bashFences(text) {
  return [...text.matchAll(FENCE_RE)].map((m) => m[1].trimEnd());
}

/**
 * The three "one thing to paste" commands the onboarding page shows,
 * read from `v3/deploy/README.md`'s own "Quick start" section — the exact
 * three ```bash fences that section has always had, in order: the
 * `docker run` one-liner (with the SPEC-502 hardening flags), the
 * `docker compose up -d` pair, and the convenience `curl | bash` script.
 * Each is sanity-checked against a substring only that command could
 * contain, so a reordering (not just a removal) is caught too.
 */
export function loadDeploySnippets() {
  const readmePath = path.join(DEPLOY_ROOT, "README.md");
  const readme = readFileSync(readmePath, "utf8");
  const fences = bashFences(readme);

  const checks = [
    ["docker run", "docker run"],
    ["cd v3/deploy && docker compose up -d", "docker compose up -d"],
    ["curl -fsSL", "curl -fsSL"],
  ];
  checks.forEach(([needle], index) => {
    const fence = fences[index];
    if (!fence || !fence.includes(needle)) {
      throw new Error(
        `deploy-snippets: expected ${readmePath}'s Quick start fence #${index} to contain ` +
          `${JSON.stringify(needle)} — the section's shape changed; update this extractor ` +
          `to match (never hand-copy the command instead).`,
      );
    }
  });

  return {
    dockerRun: fences[0],
    compose: fences[1],
    curlInstall: fences[2],
  };
}

/**
 * The Synology guide pastes `v3/deploy/docker-compose.yml` into Container
 * Manager's project editor verbatim — the whole point being that a reader
 * pastes the same file this repository actually ships, never a hand-typed
 * approximation of it. Sanity-checked against substrings only the real
 * file has, so a shape change (a renamed service, a moved volume) is
 * caught the same way `loadDeploySnippets()`'s own checks are, rather than
 * silently handing back a stale or empty file.
 */
export function loadComposeFile() {
  const composePath = path.join(DEPLOY_ROOT, "docker-compose.yml");
  const compose = readFileSync(composePath, "utf8").trimEnd();

  const checks = ["services:", "hub:", "image: ghcr.io/byte5ai/palaia-hub:stable", "palaia_home:/data", "volumes:"];
  for (const needle of checks) {
    if (!compose.includes(needle)) {
      throw new Error(
        `deploy-snippets: expected ${composePath} to contain ${JSON.stringify(needle)} — ` +
          "the file's shape changed; update this extractor to match (never hand-copy the file instead).",
      );
    }
  }

  return compose;
}
