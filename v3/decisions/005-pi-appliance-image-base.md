# ADR-005: Pi appliance image — customize a pinned base image, not pi-gen

- **Status:** Accepted
- **Date:** 2026-08-31
- **Deciders:** Claude (SPEC-603 implementation), for owner review

## Context

SPEC-603 asks for "a `pi-gen`-based (or equivalently standard, justified in
an ADR note) image build" of a Raspberry Pi appliance: Raspberry Pi OS Lite
arm64 + Docker + the palaia-hub container, auto-started, mDNS on, SSH off,
built and verified inside a `workflow_dispatch`/release-tag GitHub Actions
job that "may be slow" but must reproduce, and that must let CI actually
loop-mount and inspect the result. The constraint doing the most work here
is that this has to run, unattended and honestly, inside a shared GitHub
Actions runner — no privileged access beyond what `ubuntu-latest` (a real
VM, not a nested container) already grants: loop devices and `--privileged`
Docker both work there, but wall-clock and disk are both bounded, and a
build that only sometimes reproduces is worse than one that's honest about
a narrower scope it can actually prove.

## Decision

Build the image by **customizing a pinned, checksum-verified, pre-built
Raspberry Pi OS Lite (arm64) release** — loop-mount it, `chroot` in under
arm64 emulation (`binfmt_misc`/`qemu-user-static`), `apt-get install
docker.io`, drop in one systemd unit, done — rather than driving `pi-gen`.
Full reasoning and what this does and doesn't prove for reproducibility:
`v3/deploy/pi-image/README.md`'s "Reproducibility" section; this ADR
records why, not the mechanics (those are the scripts themselves).

## Alternatives considered

- **`pi-gen` (the SPEC's named default)** — `pi-gen` builds Raspberry Pi OS
  itself from source, via `debootstrap` against a *live* Raspbian apt
  mirror, through several sequential stages (stage0-stage2 for Lite alone).
  Two costs made it a worse fit here than the SPEC's own escape hatch
  anticipated:
  1. **Reproducibility gets strictly harder, not easier.** `debootstrap`ping
     the whole OS from a rolling mirror means *every* package in the image
     — not just the one this pipeline actually adds (Docker) — is subject
     to day-to-day version drift, and `pi-gen` has no built-in apt-snapshot
     pinning to close that gap. Starting from a Raspberry Pi Foundation
     release that's already pinned by URL + sha256 confines the
     live-mirror problem to exactly one package.
  2. **CI cost, for the same deliverable.** A full stage0-2 `debootstrap`
     build is meaningfully slower and heavier (more network, more disk,
     more failure surface — package-index outages, mirror flakiness,
     `pi-gen`'s own stage/export bookkeeping) than installing one package
     into an already-built OS. The SPEC explicitly permits "slow"; it does
     not require paying for a full OS rebuild when the actual deliverable
     is "Raspberry Pi OS Lite plus Docker plus one unit file."
  Vendoring `pi-gen` as a pinned dependency (a fixed commit SHA) would
  still leave both costs in place — it isn't a middle ground here.
- **`rpi-image-gen` / other third-party image builders** — newer, less
  battle-tested than `pi-gen`, and share `pi-gen`'s core reproducibility
  property (build-from-source against a live mirror); no clear win over
  either option above.
- **A cloud-init-driven first-boot install (SPEC-601's pattern, adapted)**
  — install Docker + palaia on first boot instead of baking them into the
  image. Rejected because it reintroduces exactly the "one thing to paste
  in a terminal" gap #280 exists to close for the Home-Assistant-comparison
  audience — SPEC-601's server already covers that audience; SPEC-603 is
  the *offline-flash* answer, and needs everything present before first
  boot.

## Consequences

- **Easier**: the CI job is fast enough to actually run to completion and
  be watched (no full-OS `debootstrap`); the reproducibility check the
  SPEC asks for is meaningful and cheap to compute (diff a rootfs manifest
  between two runs of the one thing this pipeline actually controls);
  re-pinning the base OS (`pin-base-image.sh`) is a single, auditable,
  explicit step rather than an implicit "whatever the mirror serves today."
- **Harder**: the base OS's own package versions are frozen at whatever
  the pinned Raspberry Pi OS build shipped, until someone re-pins — this
  appliance does not get base-OS security patches for free between
  re-pins (documented in `README.md`; unattended-upgrades vs. reflash
  guidance is the open question #280 itself flags, not resolved here).
- **Follow-up created**: `README.md` documents the one real gap against
  "flash, boot, done" fully offline — `palaia.service`'s `docker run`
  still pulls the hub image from GHCR on first start, since this pipeline
  does not bake the container image's own layers into the `.img.xz`.
  Pre-baking that is a reasonable next step but adds real size to the
  image; left as a deliberate, stated gap rather than silently expanded
  scope. `BOOT-TEST.md` asks the owner to record how visible this was on
  a real network.
