/**
 * Deep links from the dashboard into the SPEC-503 docs site (SPEC-504
 * deliverable #4: the wizard's final step names its exact next actions,
 * one of which is "read the docs").
 *
 * `DOCS_BASE_URL` mirrors the same placeholder
 * `v3/site/docs/astro.config.mjs` itself uses (that file's own comment:
 * "hosting/DNS for this site is out of this SPEC's scope... set this to
 * the real domain once one is chosen") — one placeholder, not two that
 * could drift out of sync once a real domain is picked.
 */
export const DOCS_BASE_URL = "https://docs.palaia.example";

/** A docs-site path (e.g. `"/connect/"`) as an absolute URL. */
export function docsUrl(path: string): string {
  return `${DOCS_BASE_URL}${path}`;
}
