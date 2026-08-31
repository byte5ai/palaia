---
id: SPEC-603
title: Raspberry Pi appliance image — flash, boot, done (buildable half of #280)
phase: 6
depends_on: [SPEC-501]
model: sonnet-5
effort: high
status: ready
---

# SPEC-603: Pi appliance image pipeline

## Goal
The project's founding bar (owner, 2026-08-31): take a Pi, flash one
image, boot, open the browser — Home Assistant's install experience.
This SPEC builds everything a CI runner can build and verify; booting on
real hardware stays an owner action with a written protocol (issue #280
carries the context and the resource-measurement requirement).

## Deliverables
1. `v3/deploy/pi-image/`: a `pi-gen`-based (or equivalently standard,
   justified in an ADR note) image build: Raspberry Pi OS Lite arm64 +
   Docker + the hub container from the `:stable` channel, auto-start on
   boot, the mDNS announcer active so `http://palaia.local` works on
   first boot, and the same self-update channel the container already
   has. No SSH enabled by default; document how an owner enables it.
2. CI: a workflow (manual `workflow_dispatch` + on release tags) that
   builds the `.img.xz` and attaches it with a checksum file as a release
   asset. It may be slow; it must not run on every PR.
3. What CI *can* verify, verified: the image builds reproducibly, the
   rootfs contains the expected units/files (loop-mount inspection
   asserts: Docker enabled, palaia unit enabled, mDNS on, SSH off), size
   budget stated and checked.
4. `v3/deploy/pi-image/BOOT-TEST.md`: the owner's one-page hardware
   protocol — flash with Raspberry Pi Imager, boot, expected timeline,
   what to record (time to `palaia.local`, RSS/CPU idle and under the
   funnel walk, on which Pi model/RAM) — feeding the #280 measurement
   requirement and the HA-add-on decision gate.

## Acceptance criteria
- [ ] image build green in the dispatch workflow (run it once for real;
      link the run in the PR)
- [ ] rootfs inspection assertions green in that workflow
- [ ] no change to the hub product itself (packaging only); full suite
      still green
- [ ] BOOT-TEST.md steps reference only things the image actually does

## Non-goals
The hardware boot test itself (owner); Raspberry Pi Imager catalog
listing (later, needs the boot test first); 32-bit Pis.
