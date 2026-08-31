# Boot test protocol (owner action)

SPEC-603 deliverable #4. CI proves the image builds, is reproducible, and
contains what it should ([`README.md`](README.md#verification)) — it
cannot boot real hardware. This is the one-page protocol for the part
that only a physical Pi can prove, and the measurements
[#280](https://github.com/byte5ai/palaia/issues/280) needs before the
Home Assistant add-on question can be decided.

Everything below references only what `build.sh`/`systemd/palaia.service`
actually do — if a step here describes something the image doesn't do,
that's a bug in this file, not a step to perform anyway.

## What you need

- A Raspberry Pi 4 or 5 (record which — #280 wants the number by model).
  2GB, 4GB, and 8GB RAM variants each get their own run if you have them;
  the RAM number is exactly what #280's measurement request is for.
- A microSD card or USB SSD, [Raspberry Pi
  Imager](https://www.raspberrypi.com/software/), and the `.img.xz`
  released from a green `v3-pi-image.yml` run (GitHub release assets, or
  a local `sudo ./build.sh` output).
- A network the Pi and your other device share (mDNS needs to be on the
  same LAN segment/VLAN — it doesn't cross routed subnets).
- A second device to test from (phone or laptop, browser only — the
  point of this whole SPEC is that you never need a terminal for this
  part).

## Flash

1. Raspberry Pi Imager → "Choose OS" → "Use custom" → the downloaded
   `.img.xz` (Imager decompresses it itself, no manual `xz -d` needed).
2. **Do not** open "Edit settings" unless you specifically want to enable
   SSH for this test run (see `README.md`'s "SSH off by default"
   section) — the point of this protocol is testing the image's own
   defaults, not a customized one.
3. Write, wait for verification, eject, insert into the Pi, power on.

## Timeline to record

Start a stopwatch at power-on.

| Milestone | What to watch for | Typical (record actual) |
|---|---|---|
| First boot begins | Pi's activity LED starts flickering | seconds |
| Filesystem expansion / first-boot services | LED activity continues, can take longer on a slower card | ~30-90s |
| `palaia.service` starts, pulls the image | Nothing visible on the Pi itself — see the network-dependency note below | varies with your network |
| `http://palaia.local:8420/` answers | Load it from your second device | record the wall-clock time from power-on |

**Note on first-run network dependency**: `palaia.service`'s `docker run`
pulls `ghcr.io/byte5ai/palaia-hub:stable` from GHCR the first time it
runs (the appliance image itself does not bundle that image's layers —
this is the one honest gap against "flash, boot, done" fully offline; a
follow-up could pre-bake the image into the `.img.xz` and is out of this
SPEC's scope). Record whether your test network's speed made this
noticeable, and roughly how long the pull itself took, separate from the
OS boot time above.

If `http://palaia.local:8420/` never answers: check `README.md`'s mDNS
caveat (same-LAN-segment requirement) before assuming something is
broken — try the Pi's IP address directly (visible on your router's
client list, or a monitor plugged into the Pi) as a fallback.

## Resource measurements (feeds #280 + the HA add-on decision)

Record all of these, from an SSH session you enable *after* the timeline
above (or a monitor+keyboard) — enabling SSH for measurement purposes is
expected; just don't conflate "I turned SSH on to measure this" with
"the image ships with SSH on" (it doesn't — that's what
`inspect.sh` checks).

1. **Idle**: `docker stats --no-stream palaia-hub` and `free -h`, at
   least 5 minutes after `http://palaia.local` first answered, with no
   browser tab open against it.
2. **Under the funnel walk**: the same two commands, immediately after
   walking through the onboarding funnel a real first-time user would —
   the same "install → first memory" sequence
   `server/src/palaia_hub/funnel.py` instruments hub-side: open the
   wizard, connect or create a vault, let it index, write or capture one
   memory, run one query against it. Capture RSS/CPU at the point right
   after that query returns (worst-case, not the cool-down after).
3. Repeat both for every Pi model/RAM combination you have available.

Report format (paste into the #280 thread or a comment on this SPEC's
PR): Pi model, RAM, storage type (SD card class / USB SSD), idle RSS,
idle CPU%, funnel-walk-peak RSS, funnel-walk-peak CPU%, time-to-`palaia.
local` from the timeline above.

## Pass/fail

- Pass: `http://palaia.local:8420/` answers from a second device without
  any terminal use, the wizard loads, and the measurements above are
  recorded for at least one Pi model.
- Fail (file an issue, don't just note it here): image doesn't boot,
  service doesn't start, mDNS doesn't resolve within ~5 minutes of the
  dashboard itself being reachable by IP (ruling out "not booted yet" as
  the cause), or SSH is somehow already enabled on a fresh flash with no
  "Edit settings" used.
