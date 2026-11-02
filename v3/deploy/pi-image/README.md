# palaia Raspberry Pi appliance image

SPEC-603 (`v3/specs/SPEC-603-pi-appliance-image.md`), the buildable half of
[#280](https://github.com/byte5ai/palaia/issues/280): take a Pi, flash one
image, boot, open the browser. No terminal.

This is packaging only — nothing here changes the hub product itself. It
takes the exact container image [`v3/deploy/`](../) already ships
(`ghcr.io/byte5ai/palaia-hub:stable`) and preinstalls it, Docker, the
`palaia.service` unit and a port-80 forwarder onto Raspberry Pi OS Lite.

## What the image ships

- **Raspberry Pi OS Lite (arm64)**, unmodified except for what's below —
  see [Base image](#base-image) for exactly which build and why.
- **Docker** (`docker.io` from the base image's own apt archive), enabled
  at boot.
- **`palaia.service`** ([`systemd/palaia.service`](systemd/palaia.service)),
  enabled at boot: runs `ghcr.io/byte5ai/palaia-hub:stable` with
  `--network host` and the exact same [SPEC-502 hardening
  flags](../install.sh) `install.sh` and `docker-compose.yml` use
  (`--security-opt no-new-privileges:true --cap-drop ALL --read-only
  --tmpfs /tmp --tmpfs /run`) — one posture, never a forked copy (checked
  by `server/tests/deploy/test_pi_image.py`, the same drift-test pattern
  `test_cloud_init.py` already applies to `cloud-init.yaml`).
- **mDNS**: the container's own announcer
  ([`mdns_announce.py`](../mdns_announce.py)) reaches the LAN because
  `palaia.service` runs the container on the host network stack — a Pi
  appliance is always a dedicated Linux host, so this has none of the
  desktop-Docker caveats `docker-compose.yml`'s own `network_mode: host`
  comment documents for a shared machine. First boot: open
  `http://palaia.local/` (or `http://palaia.local:8420/`).
- **Port 80 → 8420** (issue #620): `palaia-http.socket` binds port 80 on
  the Pi and `palaia-http.service` forwards each connection to the hub's
  own port 8420 (`systemd-socket-proxyd`, part of the base image's
  systemd), so `http://palaia.local/` works without a port. It lives on
  the box, outside the container: the container still runs non-root with
  every capability dropped and cannot bind a port below 1024 itself — the
  same split OctoPi uses (OctoPrint on 5000, port 80 in front of it). The
  forwarder holds no privilege either (systemd binds the port and hands it
  over; the proxy runs as a throwaway user in a tight sandbox). The
  socket starts after the rest of the boot, so a web server you install
  on the Pi yourself keeps port 80; the forwarder then just doesn't start
  and the hub stays on `:8420`. Neither unit depends on the other. One
  side effect: connections through port 80 reach the hub from the Pi's own
  loopback, so the hub's failed-sign-in limit counts all of them as one
  caller (`palaia_hub.security.client_ip`); `:8420` still sees each
  device's own address.
- **The same `:stable` release channel** the container has always had
  (SPEC-501) — `PALAIA_CHANNEL` is baked into the image at
  `v3-release.yml`'s build time, read back by `GET /api/update/check`.
  Updating this appliance today is `ssh` in and `docker pull … &&
  systemctl restart palaia` — the dashboard's "Update available" banner
  currently shows the generic manual-recreate message
  (`deployment: unknown`) rather than a Pi-specific one, since teaching it
  a `pi-image` deployment value is a product change (SPEC-501's territory,
  not this packaging-only SPEC) and is filed as follow-up, not silently
  done here.
- **SSH off by default** — the base image's own default, left untouched
  and asserted by CI (see [Verification](#verification)). To enable it:
  flash the image, then before first boot, use Raspberry Pi Imager's own
  "Edit settings" (gear icon) → Services → Enable SSH, or manually create
  an empty file named `ssh` in the image's boot partition. Same mechanism
  Raspberry Pi OS always uses; nothing palaia-specific.

## Base image

Raspberry Pi OS Lite (arm64), pinned by URL + sha256 in
[`base-image.env`](base-image.env) — currently the
`2026-06-18-raspios-trixie-arm64-lite` build, Raspberry Pi Foundation's own
release. `build.sh` refuses to run against anything that doesn't match
that checksum. Re-pin with [`pin-base-image.sh`](pin-base-image.sh) when a
refresh is wanted (e.g. a base-OS security update); this never happens
automatically.

## Reproducibility

What `build.sh` actually proves, and what it doesn't:

- **Proven, and checked by CI on every run**: the *customization step*
  (installing Docker, dropping in `palaia.service` and the port-80
  forwarder, enabling/disabling units) is deterministic. `build.sh` runs that step twice, against two
  independent copies of the same checksum-verified base image, and diffs
  a sha256 manifest of the resulting rootfs (every file's path and
  content hash, excluding the handful of paths that are legitimately
  per-run noise — apt's own cache/lists timing metadata, `/var/log`,
  `/tmp`, `/etc/machine-id` and its dbus equivalent, none of which this
  image ever ships anyway). A mismatch fails the build.
- **Not claimed**: bit-for-bit identical `.img.xz` output *across
  different days or weeks*. `apt-get install docker.io` resolves against
  whatever the live Debian/Raspbian archive is currently serving — the
  same real-world tradeoff every `apt-get install` in every Dockerfile in
  this repo already has (see `v3/deploy/Dockerfile`'s own `apt-get
  update && apt-get install`). The base OS itself doesn't have this
  problem (pinned, checksummed), only the one package this pipeline adds
  to it.

This scope is why `v3/decisions/005-pi-appliance-image-base.md` picked
"customize a pinned, pre-built base image" over `pi-gen`: `pi-gen`
`debootstrap`s the entire OS from a live mirror on every run, which would
put *all* of Raspberry Pi OS inside the same non-reproducible-over-time
category this pipeline keeps to one package.

## Size budget

Budget: **900MB compressed** (`.img.xz`), checked by `build.sh` after
compression — the same "budget stated and checked" pattern
`v3-release.yml`'s container-image size check already uses. Rough
accounting behind that number: the unmodified base `.img.xz` is already
~500MB; `docker.io` and its dependencies (containerd, runc, iptables,
supporting libraries) add on the order of 150-220MB of real (non-zero,
so it compresses less well than the padding around it) content; the
700MB of growth `build.sh` appends to make room for that install is
mostly zero-filled and compresses to nearly nothing. 900MB leaves
meaningful headroom above that estimate; `build.sh`'s own check is the
actual gate, not this paragraph.

## Building locally

Needs root (loop devices, `chroot`), `qemu-user-static`/binfmt registered
for arm64 (`docker run --privileged --rm tonistiigi/binfmt --install
arm64`, or `docker/setup-qemu-action` in CI), and the usual disk image
toolchain (`parted`, `e2fsprogs`, `xz-utils`, `util-linux`).

```bash
sudo ./build.sh
sudo ./inspect.sh /tmp/pi-image-build/run-1/palaia-appliance.img
```

Output: `/tmp/pi-image-build/out/palaia-appliance-v<VERSION>.img.xz` (+
`.sha256`). Override `PI_IMAGE_WORK_DIR`/`PI_IMAGE_OUTPUT_DIR` to change
where.

## Verification

What CI can verify, and does, on every `workflow_dispatch`/release-tag
run of `.github/workflows/v3-pi-image.yml` (never on a PR — this is slow):

1. **Reproducibility** — `build.sh`'s own double-build-and-diff, above.
2. **Rootfs inspection** (`inspect.sh`, loop-mounted read-only) — Docker
   enabled, `palaia.service` enabled and running the `:stable` image with
   host networking, `palaia-http.socket` enabled on port 80 and forwarding
   to `127.0.0.1:8420`, SSH not enabled and no `/boot` ssh marker file.
3. **Size budget** — the compressed image against the number above.

What CI *cannot* verify — the image never actually boots in CI, on real
hardware, with a real network — is the owner's job, protocol in
[`BOOT-TEST.md`](BOOT-TEST.md).

## Data

Same volume convention as every other palaia install path: `palaia_home`,
a named Docker volume holding everything under `/data` (config, vault,
index). `docker volume inspect palaia_home` / `docker exec palaia-hub ls
/data` and ordinary Docker volume backup tooling all work identically to
the compose or one-liner install — nothing about running from this image
changes where or how that volume is managed.
