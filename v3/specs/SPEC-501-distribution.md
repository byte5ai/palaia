---
id: SPEC-501
title: Distribution — app-store listings, channels, self-update
phase: 5
depends_on: [SPEC-112]
model: sonnet-5
effort: high
status: ready
---

# SPEC-501: Distribution

## Goal
MASTERPLAN §9.2: palaia installable where self-hosters already shop —
Umbrel, CasaOS, Runtipi, TrueNAS SCALE — plus release channels and the
one-click self-update §9.1 promises. Submission mechanics per platform are
in `v3/research/mcp-landscape-2026.md`; where that dossier is silent,
research the platform's CURRENT submission docs and cite them.

## Deliverables
1. `v3/deploy/stores/`: one ready-to-submit package per platform —
   Umbrel app manifest, CasaOS app spec, Runtipi app config, TrueNAS SCALE
   app (their current format) — each validated against the platform's own
   schema/linter where one exists, each pinning the GHCR image by channel
   tag, each with the platform-appropriate description (jargon-free) and
   icon reference. Submission itself (opening PRs against third-party store
   repos) is an owner action: ship the packages + a per-platform
   `SUBMIT.md` with the exact steps.
2. Home-Assistant add-on: an evaluation document (`v3/deploy/stores/
   home-assistant/EVALUATION.md`) with a working add-on config IF the
   evaluation lands positive — HA add-ons are containerized with a defined
   config schema; state honestly what works and what doesn't (mDNS, host
   networking).
3. Release channels: GHCR `stable` and `beta` tags wired into the release
   workflow (SPEC-112's CI grows a channel input); `/api/update/check`
   compares the running version against the channel's latest GHCR digest
   (size/time-capped fetch, offline-safe: "could not check" is a state,
   never an error page).
4. One-click self-update from the dashboard, honest about its mechanics:
   inside a container, "self-update" = pull-and-recreate, which the
   container cannot do to itself portably. Fixed design: a
   `palaia-hub update` helper for compose users (writes the new tag,
   prints the two commands), a documented watchtower-compatible label on
   the image, and — where the hosting store has an update mechanism
   (Umbrel/CasaOS/Runtipi/TrueNAS all do) — the dashboard points at it by
   name instead of pretending. The dashboard "Update available" banner +
   per-environment instructions is the deliverable; silent in-place
   binary swaps are explicitly NOT built.
5. Version/channel surfaced in `/api/info` and the dashboard footer.

## Acceptance criteria
- [ ] every store package passes its platform's validator/linter (or, where
      none exists, a schema check written here from the platform's docs,
      cited)
- [ ] update check: mocked GHCR answers drive "up to date", "update
      available", "cannot check" states end-to-end into the dashboard banner
- [ ] channel plumbed: a beta-channel hub checks beta, stable checks stable
- [ ] compose helper prints correct commands for the shipped compose file
- [ ] jargon lint on all new user-facing copy

## Non-goals
Actually submitting to the stores (owner action, SUBMIT.md each); auto-
applied updates; delta updates; signing beyond what GHCR/cosign already
provides in SPEC-112's pipeline.
