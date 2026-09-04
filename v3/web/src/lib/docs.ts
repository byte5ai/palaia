/**
 * Deep links from the dashboard into the SPEC-503 docs site (SPEC-504
 * deliverable #4: the wizard's final step names its exact next actions,
 * one of which is "read the docs").
 *
 * `DOCS_BASE_URL` must equal `v3/site/docs/astro.config.mjs`'s `site` +
 * `base` (the docs are served as a subpath of the palaia homepage, see
 * that file's own comment) — `docs.test.ts` reads the astro config and
 * fails if the two ever drift apart (issue 322). No trailing slash: the
 * paths handed to `docsUrl` start with one.
 */
export const DOCS_BASE_URL = "https://palaia.byte5.ai/docs";

/** A docs-site path (e.g. `"/connect/"`) as an absolute URL. */
export function docsUrl(path: string): string {
  return `${DOCS_BASE_URL}${path}`;
}
