# palaia docs site

SPEC-503: the user-facing documentation site — the one a non-developer can
follow, distinct from `v3/docs/` (engineering documentation for people
building palaia itself). Built with [Astro](https://astro.build) +
[Starlight](https://starlight.astro.build): static output, no server to
run, full-text search built in.

Hosting/deployment is explicitly out of this SPEC's scope (its own
non-goals list) — this README covers building and previewing the site;
where it actually gets served (the owner's DNS/CDN) is a separate,
later decision.

## Building it

```bash
npm ci
npm run build
```

Output lands in `dist/` — a fully static site: point any static file host
(nginx, an S3 bucket, GitHub Pages, Cloudflare Pages, the same nginx that
already serves the dashboard in `v3/deploy/`) at that directory and it
works. No environment variables, no server process, no database.

`npm run build` also runs the broken-internal-link check
(`scripts/check-links.mjs`) against its own output — a build that
completes has already been checked for a route nothing links to correctly.

## Previewing locally

```bash
npm run dev        # hot-reloading dev server
npm run preview     # serves the actual `dist/` build, for a closer-to-production check
```

## The "Connect your AI" pages are generated — read this before editing them

Every page under `src/content/docs/connect/` carries a comment at the top
saying so. They are rendered straight from
[`v3/web/src/lib/clients.ts`](../../web/src/lib/clients.ts) and
[`skills.ts`](../../web/src/lib/skills.ts) — the same catalog the
dashboard's own connect-a-client page reads — so there is exactly one
place a client's command, prompt, or skill-support text is ever typed.

- Changed `clients.ts` or `skills.ts`? Run `npm run gen:connect` from
  here and commit the result.
- `npm run check:generated` (part of `npm test` and of CI) fails loudly if
  you forget — it regenerates the pages in memory and diffs them against
  what's checked in.
- Never hand-edit a file under `connect/` — the next regeneration
  overwrites it silently, and the drift check will not catch a hand-edit
  that happens to still match the source's current output (it only catches
  the source having moved *past* what's checked in).

See `scripts/lib/extract.mjs` (the bundler that reads the TypeScript
source without a copy) and `scripts/lib/render.mjs` (turns one catalog
entry into a page) for how this actually works.

## Tests and checks

```bash
npm run lint          # eslint
npm run typecheck    # astro check
npm run check:generated
npm test             # vitest — includes the drift check as an assertion, plus page-shape checks
npm run build         # astro build + the link checker
```

The jargon lint (SPEC-503 deliverable #3: no in-house word in prose outside
a code span) runs from the Python side, over every page in
`src/content/docs/`, at
`v3/server/tests/docs_site/test_docs_jargon_lint.py` — part of
`uv run pytest server/tests` from `v3/`, not part of this project's own
`npm test`. It shares the exact blocklist the skill packages
(`v3/clients/skills/`) are linted against
(`palaia_addon_sdk.jargon.find_jargon`) — one list, not two copies that
can drift apart.

## Screenshots

This sandbox cannot produce real product screenshots. Every page that
wants one carries an HTML comment (`<!-- screenshot: ... -->`, invisible
when rendered) instead of a placeholder image. `SHOTLIST.md` is the
checklist for turning those into real ones.
