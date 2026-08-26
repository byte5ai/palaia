---
id: SPEC-112
title: Packaging & distribution (Docker, compose, mDNS, installer, GHCR)
phase: 1
depends_on: [SPEC-101]
model: sonnet-5
effort: medium
status: draft
---

# SPEC-112: Packaging & distribution

## Goal
The 5-minute install: one container, one command, then the browser
(MASTERPLAN §9). Everything after `docker run` happens in the wizard.

## Deliverables
1. Multi-stage `v3/deploy/Dockerfile` (web build → uv-installed hub → slim
   runtime, non-root, healthcheck); image entry serves hub + built dashboard.
2. `v3/deploy/docker-compose.yml` (volume for PALAIA_HOME, sane defaults) and
   the documented one-liner `docker run` variant.
3. **mDNS**: hub advertises `palaia.local` (zeroconf lib, containerized caveats
   documented honestly — host networking note for Linux, fallback: printed URL
   on startup and in `docker logs`).
4. GHCR publishing workflow (`v3-release.yml`): builds/pushes on `v3.*` tags,
   `edge` on main; multi-arch (amd64/arm64).
5. `v3/deploy/install.sh`: the optional convenience script (checks Docker,
   pulls, runs, prints the URL) — never *required* by any doc.
6. Update path v0: dashboard shows current vs latest (GHCR tag check), update
   instructions; one-click self-update is Phase 2+.

## Acceptance criteria
- [ ] fresh Linux VM: `docker run` one-liner → wizard reachable, data survives
      container recreation (volume test)
- [ ] image < 400MB compressed (embeddings models download at first use, not
      baked in — startup message says so)
- [ ] arm64 image runs (Raspberry-class check via QEMU in CI)
- [ ] healthcheck reflects /api/health; container restarts cleanly under
      compose `restart: unless-stopped`
- [ ] no secrets or tokens baked into the image (scan in CI)

## Non-goals
App-store listings (Phase 5), appliance images, tunnel add-ons (Phase 2),
supervisor/add-on containers (Phase 3).
