# palaia Raspberry Pi appliance image

SPEC-603 (`v3/specs/SPEC-603-pi-appliance-image.md`), the buildable half of
[#280](https://github.com/byte5ai/palaia/issues/280): take a Pi, flash one
image, boot, open the browser. No terminal.

This is packaging only — nothing here changes the hub product itself. It
takes the exact container image [`v3/deploy/`](../) already ships
(`ghcr.io/byte5ai/palaia-hub:stable`) and preinstalls it, Docker, the
`palaia.service` unit and a port-80 redirect onto Raspberry Pi OS Lite.

## What the image ships

- **Raspberry Pi OS Lite (arm64)**, unmodified except for what's below —
  see [Base image](#base-image) for exactly which build and why.
- **Docker** (`docker.io` from the base image's own apt archive), enabled
  at boot, and **nftables** (the `nft` tool for the port-80 redirect).
- **`palaia.service`** ([`systemd/palaia.service`](systemd/palaia.service)),
  enabled at boot: runs `ghcr.io/byte5ai/palaia-hub:stable` with
  `--network host` and the exact same [SPEC-502 hardening
  flags](../install.sh) `install.sh` and `docker-compose.yml` use
  (`--security-opt no-new-privileges:true --cap-drop ALL --read-only
  --tmpfs /tmp --tmpfs /run`) — one posture, never a forked copy (checked
  by `server/tests/deploy/test_pi_image.py`, the same drift-test pattern
  `test_cloud_init.py` already applies to `cloud-init.yaml`). On the host
  network the container's cloud entry (port 8422, the door a public tunnel
  points at) would listen on every address of the Pi, so the unit sets
  `PALAIA_CLOUD_BIND=127.0.0.1`: a tunnel reaches it on loopback, nothing
  on the LAN does.
- **mDNS**: the container's own announcer
  ([`mdns_announce.py`](../mdns_announce.py)) reaches the LAN because
  `palaia.service` runs the container on the host network stack — a Pi
  appliance is always a dedicated Linux host, so this has none of the
  desktop-Docker caveats `docker-compose.yml`'s own `network_mode: host`
  comment documents for a shared machine. First boot: open
  `http://palaia.local/` (or `http://palaia.local:8420/`).
- **Port 80 → 8420** (issue #620): after the rest of the boot,
  `palaia-http-redirect.service` runs
  [`http-redirect.sh`](http-redirect.sh), which adds a kernel redirect of
  incoming TCP port 80 to the hub's own port 8420, so `http://palaia.local/`
  works without a port. It lives on the box, outside the container: the
  container still runs non-root with every capability dropped and cannot
  bind a port below 1024 itself — the same split OctoPi uses (OctoPrint on
  5000, port 80 in front of it). A redirect rather than a proxy, because the
  hub then still sees each device's own address, which its failed-sign-in
  limit is keyed on (SPEC-502); through a proxy every caller would share
  one limit. The rule sits in an nftables table of its own (`inet
  palaia_http`, IPv4 and IPv6 in one rule, only for traffic addressed to
  the Pi), never touches Docker's rules, and `systemctl stop
  palaia-http-redirect` removes it as a whole. If something already
  listens on port 80 at that point — a web server you installed on the Pi
  yourself — the script leaves port 80 alone and logs one line saying so;
  the hub stays on `:8420`. Neither unit depends on the other.
  `nftables.service` stays disabled (Debian's default): its stock
  `/etc/nftables.conf` flushes the whole ruleset, Docker's rules included.
  IPv6 note: nginx in the container listens on IPv4 only, so a redirected
  IPv6 connection is refused just as it was before; `palaia.local` is
  announced with its IPv4 address only.
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
  (installing Docker and nftables, dropping in `palaia.service` and the
  port-80 redirect, enabling/disabling units) is deterministic. `build.sh` runs that step twice, against two
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
   host networking and its cloud entry on loopback,
   `palaia-http-redirect.service` enabled and redirecting port 80 to 8420
   only when port 80 is free, `nft` present and `nftables.service` off, SSH
   not enabled and no `/boot` ssh marker file.
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
