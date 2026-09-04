# Website handoff — for the session owning palaia's public website

This document is the engineering side's handoff to whoever runs the public
website. It states what exists in this repository, what decisions are open,
and where the seams are. The website session has authority over everything
public-facing; nothing here prescribes design.

## What exists (all in this repo, CI-verified on every PR)

- **The documentation site**: `v3/site/docs` — Astro Starlight, 23 pages.
  Build: `npm ci && npm run build` (from that directory). CI job
  `docs-site` builds and link-checks every PR; `npm run check:generated`
  guards the 11 generated pages (per-client connect pages, Synology guide)
  against drift from their sources.
- **The onboarding page**: `/onboarding` within that site — platform
  picker (Docker / Compose / app stores / "Looking for your machine?"),
  every command drift-tested against `v3/deploy`'s real files. This is the
  functional successor to palaia.byte5.ai's job.
- **Content rules the site enforces**: a jargon lint (plain language,
  server-side test `server/tests/docs_site/`), screenshot slots as HTML
  comments (`SHOTLIST.md` lists them), one canonical copy per fact
  (generated, never hand-copied).

## What is deliberately NOT decided here (yours)

1. **Domain + DNS** — decided: `astro.config.mjs` has `site:
   "https://palaia.byte5.ai"` and `base: "/docs"` (the docs are a subpath
   of the homepage). The dashboard's `web/src/lib/docs.ts` is pinned to
   that value by `web/src/lib/docs.test.ts` (issue #322), so changing it
   means changing both — the test says so.
2. **Hosting + deploy** — CI builds the site but deploys nowhere;
   `https://palaia.byte5.ai/docs/` still answers 404. Any static host
   works on `dist/` served under `/docs`; a deploy workflow does not exist
   yet.
3. **Marketing** — every page is functional, none is promotional. Whether
   a marketing landing page fronts the docs site (or lives elsewhere) is
   a website-session decision. The root README's pitch (being rewritten,
   see PR "docs: root README — palaia v3 first") is the closest existing
   marketing copy and free to reuse.
4. **Graphics** — slots are marked in pages and `SHOTLIST.md`; issue #298
   tracks the README's graphic orders, same convention.

## Seams to respect

- Command snippets must keep coming from the drift mechanism
  (`scripts/lib/deploy-snippets.mjs`) — never paste a command literal.
- The jargon lint applies to all `.md` content — plain words, no protocol
  names in user-facing text.
- `palaia.local` is the hub's real mDNS name (works only on the user's
  home network) — not a placeholder, do not "fix" it into a domain.

## Contact seam

Engineering-side changes to the site go through PRs in this repo as
usual; this document is updated when the seams change.
