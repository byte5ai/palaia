# Releasing palaia v3

The ordered path from "the Phase-5 gate is held" to a tagged, published,
submitted `3.0.0`. Steps marked **[OWNER]** are not automatable from this
repository's own tooling — a person, a decision, or an external party has
to act. Everything else is a command this repository already has, checked
in `server/tests/`.

This file describes going from `3.0.0-rc1` (SPEC-506) to the final
`3.0.0`. It is not itself the gate decision: `v3/IMPLEMENTATION.md` §6's
Gate-P5 paragraph records the architect's verdict (held 2026-08-26,
conditional on the two owner actions in §1 below). The Phase-4 paragraph
above it still carries its "this paragraph is a draft" marker — that is
the historical record of what SPEC-407 ran, not an open gate, and it does
not block the cut (issue #388).

## 0. Prerequisite: the gate is held

- [ ] **[OWNER]** Confirm `v3/IMPLEMENTATION.md` §6's Gate-P5 verdict
      still stands — it is conditional on §1's two owner actions, so this
      is a re-read, not a new decision.
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

- [ ] **[OWNER]** `v3/docs/migrate-from-v2.md`'s "Support timeline" says
      "not decided yet" in three places (feature-parity target date,
      earliest v2-hotfix-stops date, advance-notice policy — issue #390).
      Replace each with the real date/policy before this becomes the
      message v2 users see; the page is already linked from the root
      README and the release notes, so it is public now.
- [ ] **[OWNER]** Decide whether `3.0.0` ships alongside, or after,
      those v2-sunset dates going live on the docs site.

## 3. Cut the release

- [ ] Bump `v3/VERSION` from `3.0.0-rc1` to `3.0.0` (the only file to
      edit — `server/tests/test_version_drift.py` fails loudly if any
      other artifact disagrees; fix forward until it's green again).
- [ ] Remove every `rc-channel-note` (the "until 3.0.0 is final, use `:beta`"
      notes in the install docs, `deploy/README.md`, `deploy/docker-compose.yml`,
      `deploy/cloud-init.yaml`, the root README and the generated Synology page
      — regenerate it with `npm run gen:synology`).
      `server/tests/test_version_drift.py` requires the notes while `VERSION`
      is a pre-release and refuses them once it is not, so a forgotten one
      fails CI rather than shipping.
- [ ] Flip the *unattended* install path from the `beta` channel to `stable`:
      `deploy/cloud-init.yaml`'s `IMAGE=` line. Unlike the `docker run`/compose
      commands a reader types (and can adjust after reading the note next to
      them), it boots without anyone watching, so during the RC it pins
      `:beta` — a tag that exists — rather than a `:stable` alias that would
      404 mid-boot. On the final tag `:stable` exists, and it must point at it.
      `test_version_drift.py`'s
      `test_unattended_install_paths_pin_the_channel_matching_version` fails
      until it says `:stable`. (`deploy/get-palaia.sh` keeps its `stable`
      default — it fails loudly with a re-run hint during an RC, so it needs no
      flip.)
- [ ] Add a `## 3.0.0` section to `v3/CHANGELOG.md`. The header line must
      start with `## 3.0.0` followed by a space or the end of the line
      (`## 3.0.0 — 2026-09-15` or a bare `## 3.0.0`); both the cut
      workflow's guard and `tools/release-dry-run.sh` test exactly
      `^## <version>( |$)`, so the existing `## 3.0.0-rc1` header never
      counts for `3.0.0`. If nothing user-visible changed since `rc1`
      beyond the version bump itself, say so in one line rather than
      duplicating the `rc1` section.
- [ ] Write `v3/docs/release-notes/3.0.0.md`, saying plainly that the
      marketplace shows the add-ons bundled with the release unless an
      operator configures a published index (`market.index_url` +
      `market.public_key`) — palaia publishes none for 3.0.0 (issue #409;
      the owner steps to change that are in `v3/tools/README.md`). Its first line is
      `# <release title>`; the cut workflow publishes the rest as the
      GitHub release body (§3 below), and fails without the file.
      `server/tests/test_version_drift.py` fails first, on the checkout,
      while the notes for `VERSION` are missing.
- [ ] Retire the release-candidate wording: `v3/README.md`'s status
      paragraph ("release candidate", "Not yet tagged `3.0.0`") and
      `v3/SECURITY.md`'s supported-versions row ("there is no released v3
      yet"). `test_version_drift.py` refuses those phrases once `VERSION`
      has no suffix. (The root README's `:beta` command and its "use
      `:stable` once final" line are the `rc-channel-note` the step above
      already covers.)
- [ ] Run `v3/tools/release-dry-run.sh` once more against the bumped
      version — it re-runs the drift test, prints what the release
      workflow would tag/push, confirms the `CHANGELOG.md` section exists,
      and does a real `npm run build`/pack/sign of the mcpb bundle when
      network access allows (skips honestly otherwise, naming the
      structural fallback check).
- [ ] Commit the version bump + changelog entry, PR it through the normal
      process (this file's own repository is still `CONTRIBUTING.md`-governed —
      a feature branch, a PR, conventional commits).
- [ ] Tag + release: dispatch `.github/workflows/v3-cut-release.yml` on
      the merge commit with `expected_version: 3.0.0`. It creates the
      `v3.3.0.0` tag (yes — the leading `3.` is the `v3` track's own fixed
      tag prefix, not a repeated major version; `v3-release.yml`'s
      tag-parsing strips exactly `refs/tags/v3.` and keeps the rest, so
      the tag really is `v3.` + `v3/VERSION`'s content), publishes the
      GitHub release from `v3/docs/release-notes/<version>.md` (which must
      exist — write it first), and dispatches both image builds on the tag:
      `v3-release.yml` (the hub container image) and `v3-pi-image.yml` (the
      Raspberry Pi appliance image, attached to the release as
      `.img.xz` + `.sha256`). Neither would run on its own — a tag created
      by the workflow's token does not fire their `push: tags:` triggers.
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
- [ ] Watch `v3-pi-image.yml`'s run too (it takes longer — a real OS image
      is built twice for the reproducibility check): when it is green, the
      release carries `palaia-appliance-*.img.xz` and its `.sha256`, which
      is what `deploy/pi-image/README.md` and `BOOT-TEST.md` tell people to
      flash. A release without that asset is not finished.

## 4. After the tag: what becomes reachable

- [ ] `docker pull ghcr.io/byte5ai/palaia-hub:stable` now serves `3.0.0`
      — the one-liner, `deploy/install.sh`, and `deploy/docker-compose.yml`
      need no edits; they already pin the `stable` channel tag on
      purpose (`deploy/README.md`/`deploy/stores/README.md` — never a
      literal version). The Pi image (`deploy/pi-image/`: systemd unit,
      README, `BOOT-TEST.md`) and the generated Synology page also pin
      `:stable`. The unattended path (`deploy/cloud-init.yaml`) was flipped
      from `:beta` to `:stable` in §3 — it pins a real channel tag rather than
      the moving alias, so a paste-and-boot never 404s mid-setup. The Pi
      appliance `.img.xz` itself is attached to the release by
      `v3-pi-image.yml` (§3).
- [ ] Check the GitHub release the cut workflow created: title from the
      notes' first line, body from the rest, no pre-release badge for a
      final version. Nothing to publish by hand — §3's dispatch did it.
- [ ] **[OWNER]** Bump the *store package* version fields — these are the
      one place a literal version string does live, separate from the
      image tag: `truenas/community/palaia/app.yaml`'s `app_version`/
      `human_version`, `runtipi/apps/palaia/config.json`'s `version`,
      `umbrel/umbrel-app.yml`'s `version`, `casaos/docker-compose.yml`'s
      `version` label. The Home Assistant `config.yaml`'s `version` is
      *not* on this list: it is the image tag HA pulls, so
      `server/tests/test_version_drift.py` pins it to `v3/VERSION` and §3's
      bump carries it along (issue #394). Each package's own
      `SUBMIT.md`/`EVALUATION.md` names exactly what to update and how — see
      `v3/deploy/stores/README.md`. This is deliberately *not* done as
      part of `rc1` (SPEC-506's own non-goal): bumping these to claim
      `3.0.0` while the `stable` channel still served a pre-release image
      would have been dishonest; now that `stable` really does serve
      `3.0.0`, bump them and submit.
- [ ] **[OWNER]** Submit (or re-submit) the store packages per each
      `SUBMIT.md`. None was submitted as part of any SPEC in this
      repository — SPEC-501's own non-goal, carried through SPEC-506's.
- [ ] **[OWNER]** Re-publish the docs site after the release. The site is
      live at `https://palaia.byte5.ai/docs` (`astro.config.mjs`: `site:
      "https://palaia.byte5.ai"`, `base: "/docs"`; served by the
      palaia-homepage repo per its `DOCS-HOSTING.md`), and the dashboard's
      docs links (`web/src/lib/docs.ts`, pinned to `site` + `base` by
      `web/src/lib/docs.test.ts` — issue #322) resolve there. Nothing in
      *this* repository deploys it: `v3-ci.yml`'s `docs-site` job only
      builds and link-checks `dist/`, so the content changes a release
      carries (connect pages, install guide, changelog links) reach the
      live site only when the homepage repo picks up the new build.
      (`palaia.local` is unrelated and needs no change here — that is the
      hub's own real mDNS self-advertisement, `deploy/README.md` §"Finding
      it on your network", not a placeholder.)
- [ ] **[OWNER]** Turn on whatever v2-sunset messaging
      `docs/migrate-from-v2.md`'s §2 dates call for, now that they are
      real dates rather than placeholders.

## 5. What this file deliberately does not cover

Reverting a bad release (this repository's standing `git`/hotfix norms in
`CONTRIBUTING.md` apply — a `v2-maintenance`-style hotfix branch for v3 is a
judgment call for whoever holds the gate, not something pre-decided
here), and any `3.0.x` patch release after this one (a lighter version of
§3 above — bump `VERSION`, changelog, tag, no need to re-run §0–§2).
