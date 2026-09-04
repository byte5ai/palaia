# Releasing palaia v3

The ordered path from "the Phase-5 gate is held" to a tagged, published,
submitted `3.0.0`. Steps marked **[OWNER]** are not automatable from this
repository's own tooling — a person, a decision, or an external party has
to act. Everything else is a command this repository already has, checked
in `server/tests/`.

This file describes going from `3.0.0-rc1` (SPEC-506) to the final
`3.0.0`. It is not itself the gate decision — `v3/IMPLEMENTATION.md` §6's
Phase-5 paragraph is a **draft**; the architect holds the gate. Do not
start step 1 below until that paragraph is accepted, in writing, by
whoever holds it.

## 0. Prerequisite: the gate is held

- [ ] **[OWNER]** `v3/IMPLEMENTATION.md` §6's Phase-5 paragraph is
      reviewed and its "draft" marker removed (or replaced with the
      architect's actual verdict).
- [ ] `uv run pytest server/tests -q` green, `uv run ruff check server &&
      uv run mypy server/src` clean, `v3/web` and `v3/site/docs`'s own
      lint/typecheck/test/build all green — the state this SPEC's own PR
      already leaves the branch in; re-run once more here as the last
      check before anything below.

## 1. Close the two things this sandbox could not do

- [ ] **[OWNER]** External security review. Send
      `v3/docs/security/external-review-brief.md` to the reviewer;
      address findings per `SECURITY.md`'s own severity/timeline table
      before tagging. `docs/security/threat-model.md` §8's eight named
      trade-offs are not new findings — a reviewer flagging one of those
      still gets a real answer, just not a blocking one by default.
- [ ] **[OWNER]** The real usability test session:
      `v3/docs/usability-test-protocol.md`, run with an actual
      non-developer. Record the result in
      `v3/docs/client-matrix-results.md`'s usability section (the
      protocol's own §5 says where). A "gave up" or "stuck" result on any
      task is not automatically a blocker — judge it the way every other
      gate in this project has: does it undermine the exit criterion, or
      is it a polish item that becomes a filed issue?
- [ ] **[OWNER]** Confirm `SECURITY.md`'s reporting channel (the GitHub
      private-vulnerability-reporting button — the owner confirmed on
      2026-08-26 that no security email address exists, so the button is
      the only channel) actually notifies someone who reads it before a
      wider audience sees this release. Adding a real, monitored security
      email later means one edit to `SECURITY.md`.

## 2. Owner decisions this repository left open on purpose

- [ ] **[OWNER]** `v3/docs/migrate-from-v2.md` has three
      `[DECISION: ...]` placeholders (feature-parity target date, earliest
      v2-hotfix-stops date, advance-notice policy) — fill them in with
      real dates/policy before this becomes the message v2 users see.
- [ ] **[OWNER]** Decide whether `3.0.0` ships alongside, or after,
      those v2-sunset dates going live on the docs site.

## 3. Cut the release

- [ ] Bump `v3/VERSION` from `3.0.0-rc1` to `3.0.0` (the only file to
      edit — `server/tests/test_version_drift.py` fails loudly if any
      other artifact disagrees; fix forward until it's green again).
- [ ] Add a `## 3.0.0` section to `v3/CHANGELOG.md` — if nothing
      user-visible changed since `rc1` beyond the version bump itself, say
      so in one line rather than duplicating the `rc1` section.
- [ ] Run `v3/tools/release-dry-run.sh` once more against the bumped
      version — it re-runs the drift test, prints what the release
      workflow would tag/push, confirms the `CHANGELOG.md` section exists,
      and does a real `npm run build`/pack/sign of the mcpb bundle when
      network access allows (skips honestly otherwise, naming the
      structural fallback check).
- [ ] Commit the version bump + changelog entry, PR it through the normal
      process (this file's own repository is still `AGENTS.md`-governed —
      a feature branch, a PR, conventional commits).
- [ ] Tag + release: dispatch `.github/workflows/v3-cut-release.yml` on
      the merge commit with `expected_version: 3.0.0`. It creates the
      `v3.3.0.0` tag (yes — the leading `3.` is the `v3` track's own fixed
      tag prefix, not a repeated major version; `v3-release.yml`'s
      tag-parsing strips exactly `refs/tags/v3.` and keeps the rest, so
      the tag really is `v3.` + `v3/VERSION`'s content), publishes the
      GitHub release from `v3/docs/release-notes/<version>.md` (which must
      exist — write it first), and dispatches the image build on the tag.
      This is the step that actually publishes — nothing before it does.
      (A plain `git tag v3.3.0.0 && git push origin v3.3.0.0` by someone
      with tag-push rights creates the same tag, but then the GitHub
      release and its notes are manual — the workflow exists because
      agent sessions cannot push tags.)
- [ ] Watch `v3-release.yml`'s run: it builds and pushes
      `ghcr.io/byte5ai/palaia-hub:v3.3.0.0` and `:stable` (never `:beta`
      for a non-`rc`/non-`beta` version — the workflow's own branch logic;
      `server/tests/test_version_drift.py`'s
      `test_release_workflow_tag_derived_version_would_round_trip_this_rc`
      pins the same arithmetic and re-checks itself against whatever
      `VERSION` currently is, so it stays meaningful after this bump
      rather than only proving the `rc1` case), runs the arm64 QEMU
      health smoke, checks the 400MB image budget, and scans for
      secrets. **[OWNER]**: if any of these fail, this is not a "release
      anyway" situation — fix and re-tag.

## 4. After the tag: what becomes reachable

- [ ] `docker pull ghcr.io/byte5ai/palaia-hub:stable` now serves `3.0.0`
      — the one-liner, `deploy/install.sh`, and `deploy/docker-compose.yml`
      need no edits; they already pin the `stable` channel tag on
      purpose (`deploy/README.md`/`deploy/stores/README.md` — never a
      literal version).
- [ ] **[OWNER]** Bump the *store package* version fields — these are the
      one place a literal version string does live, separate from the
      image tag: `truenas/community/palaia/app.yaml`'s `app_version`/
      `human_version`, `runtipi/apps/palaia/config.json`'s `version`,
      `umbrel/umbrel-app.yml`'s `version`, `casaos/docker-compose.yml`'s
      `version` label. Each package's own `SUBMIT.md`/`EVALUATION.md`
      names exactly what to update and how — see
      `v3/deploy/stores/README.md`. This is deliberately *not* done as
      part of `rc1` (SPEC-506's own non-goal): bumping these to claim
      `3.0.0` while the `stable` channel still served a pre-release image
      would have been dishonest; now that `stable` really does serve
      `3.0.0`, bump them and submit.
- [ ] **[OWNER]** Submit (or re-submit) the store packages per each
      `SUBMIT.md`. None was submitted as part of any SPEC in this
      repository — SPEC-501's own non-goal, carried through SPEC-506's.
- [ ] **[OWNER]** Deploy `v3/site/docs`'s built output to real hosting —
      `astro.config.mjs` already names the real address (`site:
      "https://palaia.byte5.ai"`, `base: "/docs"`, served by the
      palaia-homepage repo per its `DOCS-HOSTING.md`), but as of this
      writing `https://palaia.byte5.ai/docs/` answers 404: nothing in this
      repository deploys the build anywhere. `v3-ci.yml`'s `docs-site` job
      builds and link-checks the site on every PR; the remaining step is
      publishing that `dist/` under `/docs` on that origin, so the
      dashboard's docs links (`web/src/lib/docs.ts`, pinned to `site` +
      `base` by `web/src/lib/docs.test.ts` — issue #322) resolve for anyone
      outside this repository. (`palaia.local` is unrelated and needs no
      change here — that is the hub's own real mDNS self-advertisement,
      `deploy/README.md` §"Finding it on your network", not a placeholder.)
- [ ] **[OWNER]** Publish the GitHub release notes from
      `v3/CHANGELOG.md`'s new section (`gh release create v3.3.0.0
      --notes-file ...` or the GitHub UI) — this repository has no
      workflow step that does this automatically today.
- [ ] **[OWNER]** Turn on whatever v2-sunset messaging
      `docs/migrate-from-v2.md`'s §2 dates call for, now that they are
      real dates rather than placeholders.

## 5. What this file deliberately does not cover

Reverting a bad release (this repository's standing `git`/hotfix norms in
`AGENTS.md` apply — a `v2-maintenance`-style hotfix branch for v3 is a
judgment call for whoever holds the gate, not something pre-decided
here), and any `3.0.x` patch release after this one (a lighter version of
§3 above — bump `VERSION`, changelog, tag, no need to re-run §0–§2).
