# palaia v3 — packaging & distribution

SPEC-112. The 5-minute install: one container, one command, then the
browser (MASTERPLAN §9). Everything after `docker run` happens in the
first-run wizard (later SPECs).

## Quick start

On a Linux machine (a home server, a NAS, a Raspberry Pi):

```bash
docker run -d --name palaia-hub \
  --network host -e PALAIA_CLOUD_BIND=127.0.0.1 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

Then open `http://palaia.local:8420/` from any device on the same network
(`http://localhost:8420/` on the machine itself). The container runs on the
machine's own network, so its name announcement reaches your other devices
(see [mDNS](#mdns-httppalaialocal8420) below); `PALAIA_CLOUD_BIND` keeps the
cloud entry on the machine's loopback address, where only a tunnel on the
machine itself reaches it.

With Docker Desktop (macOS, Windows), whose containers run inside a hidden
virtual machine, publish the port instead:

```bash
docker run -d --name palaia-hub \
  -p 8420:8420 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

Then open `http://localhost:8420/`. A name like `palaia.local` cannot reach
your network from inside Docker Desktop's virtual machine.

<!-- rc-channel-note -->
> **Release candidate:** until `3.0.0` is final there is no `stable` image yet. Where a
> command or file on this page says `ghcr.io/byte5ai/palaia-hub:stable`, use
> `ghcr.io/byte5ai/palaia-hub:beta` for now.

The five hardening flags are explained in [`docker-compose.yml`](docker-compose.yml)
and in [Container posture](#container-posture) below; the container runs as a
non-root user either way, and drops the rest. Both commands use the same
five.

Or use compose (host network on Linux; its header says what to change for
Docker Desktop):

```bash
cd v3/deploy && docker compose up -d
```

Or the convenience script (never required — see `install.sh`; it only
wraps the `docker run` above, and picks the right one of the two). Piping a script from `main` into `bash` is
the usual trade-off: to read it first, or to pin what you run, download it
from a release tag instead —
`curl -fsSLo install.sh https://get.palaia.ai/v3.<version>/docker`,
read it, then `bash install.sh` (issue #400):

```bash
curl -fsSL https://get.palaia.ai/docker | bash
```

## Cloud-init (rented servers)

SPEC-601. For a server you rent rather than a machine you already own —
Hetzner Cloud, DigitalOcean, or similar — the vehicle is
[`cloud-init.yaml`](cloud-init.yaml): paste the whole file into the
provider's server-creation user-data field (Hetzner Cloud calls it "Cloud
config"; DigitalOcean calls it "User data"; the file is about 4 KB and
downloads the installer when the server starts), fill in one setup code
first, and the server finishes its own setup with no
terminal session needed: a few minutes after boot, open
`http://<server-address>:8420/`, enter the code and click "Connect with
Tailscale" — a one-time setup page (SPEC-605,
[`setup-page.py`](setup-page.py)) joins the server to your tailnet and
closes itself. Prefer a key? Fill in `TAILSCALE_AUTH_KEY` instead and no
page is shown. The onboarding page's "A rented server" entry shows the same
file with a copy button; this is the file it copies from — never a second,
hand-typed one.

**Already have a server?** cloud-init only ever runs on a machine's *first*
boot, so pasting `cloud-init.yaml` into a box that is already running does
nothing. For that case the universal installer
[`get-palaia.sh`](get-palaia.sh) — served at `get.palaia.ai` — does the same
install over SSH (Docker, Tailscale, the tailnet-only firewall and the hardened
container), ending at the identical hub. The setup file in fact runs this same
installer. On the server:

```bash
curl -fsSL https://get.palaia.ai | sh
```

Plain POSIX `sh`, so `| sh` and `| bash` both work, on a fresh server and on
one that already runs Docker or is already on your tailnet (both are kept).
Without a key it opens the same one-time setup page and prints its address
and code (or uses `PALAIA_SETUP_CODE`). The page then offers **cloud access**:
Tailscale Funnel forwards palaia's *cloud entry* — the AI-connection routes
only, never the dashboard or its API — so ChatGPT and Claude reach the hub over
HTTPS; if your tailnet has not allowed Funnel yet, the page shows Tailscale's
own "allow" link, and "Keep it private" skips the step (`PALAIA_CLOUD=0` skips
it up front). The image channel follows this release (`beta` while it is a
release candidate), so the command above needs nothing added. Other options are
listed in the script header.

A key instead of the page: put the auth key in a file only root can read and
pass `PALAIA_TSKEY_FILE=/path`. Tailscale reads it from there
(`tailscale up --auth-key=file:…`), so the key is never a command-line argument,
and the installer deletes the file afterwards — on success, failure or
cancellation. (`PALAIA_TSKEY` still works but leaves the key in your shell
history.)

What it does, in order: installs Docker and Tailscale if they are missing,
joins your tailnet (unless the server is on one already), sets up cloud access
if you allowed it, then starts the hub with the exact hardening flags
[`install.sh`](install.sh) uses (`--security-opt no-new-privileges:true
--cap-drop ALL --read-only --tmpfs /tmp --tmpfs /run` — never a forked copy of
that list, checked by `server/tests/deploy/test_cloud_init.py`'s drift test).
The dashboard port is published on the tailnet address only, plus two
loopback-only ports for a tunnel on the server itself: `127.0.0.1:8422`, the
cloud entry, and `127.0.0.1:8420`, the whole hub (for the deliberate "open"
mode). An active `ufw` gets a rule for the tailnet; an inactive one is switched
on only with `PALAIA_FIREWALL=on` (the setup file sets it), because on a server
that already runs other services it would cut them off. SSH stays open either
way. The installer counts as done only when the hub's own health check answers
through the container's front door; otherwise it prints the hub's last log lines.
The hub is reachable from your own devices on the tailnet and nowhere else;
with cloud access on, the internet sees the AI connection only.

**Opening it by name** (issues #619, #620). The installer's last line and the
setup page's "Done" screen give palaia's address on the tailnet as a name, not
a number. With MagicDNS on (the default for Tailscale networks created since
October 2022) that is the
machine's tailnet name — `palaia-hub`, or `palaia-hub-1` when the name is
taken — and Tailscale forwards plain HTTP port 80 of that name to the hub's
loopback port (`tailscale serve --bg --http=80 http://127.0.0.1:8420`), so the
address is `http://palaia-hub/`; the full name (`palaia-hub.<tailnet>.ts.net`)
is printed next to it. Tailscale keeps that setting across reboots, and the
forward is answered inside `tailscaled`, so it needs no firewall rule and is
reachable from the tailnet only. When port 80 of that name already serves
something else, it is left alone and the address keeps its port
(`http://palaia-hub:8420/`); with MagicDNS off it is the tailnet IP and port,
and the installer says why. Open that address for the first sign-in: palaia
issues its sign-in for the address it was first set up at.

**Where the data lives.** Same as every other install path: the
`palaia_home` named Docker volume, holding everything under `/data`
(config, vault, index). Nothing about running the hub this way changes
where or how that volume is managed — `docker volume inspect
palaia_home`, `docker exec palaia-hub ls /data`, and ordinary Docker
volume backup tooling all work exactly as they do for the compose or
one-liner install.

**Updating.** The file only runs its install step once, on first boot
(cloud-init's own rule). To update the hub afterward, connect over the
tailnet (SSH, or Tailscale SSH if you enabled it) and use the same two
commands any other install uses — `docker pull` the new image tag, then
recreate the container — or run `palaia-hub update` from the dashboard's
own update banner (see "Updates" above); nothing here needs re-pasting.

**Reboots.** The container is bound to the server's tailnet address, so
after a reboot it can only start once `tailscaled` has that address. The
installer adds a systemd drop-in that starts Docker after `tailscaled`
(issue #400). The address can still arrive later, when Tailscale's control
server is slow to answer at boot; Docker's start then fails ("cannot assign
requested address") and Docker does not try again — `--restart
unless-stopped` restarts a container that exits, not one that never
started. A failed start can also leave the container detached from its
network, so a plain `docker start` would run it without its ports. The
installer therefore also enables
`palaia-start-on-tailnet@palaia-hub.service`: it waits for the address,
attaches the container to its network again if needed and repeats that one
failed start, and leaves a running container, or one you stopped yourself,
alone (issue #614). A minute of "connection refused" right
after a reboot is the server still starting, not a broken install;
`journalctl -u palaia-start-on-tailnet@palaia-hub` shows when the unit
started palaia.

**Backing up.** `docker run --rm -v palaia_home:/data -v
$(pwd):/backup alpine tar czf /backup/palaia-backup.tar.gz -C /data .`
from the server itself (over the tailnet, or a provider console),
run any time.

**The one thing cloud-init cannot prove by itself.** Everything above is
checked in CI at the file level — the config parses
(`cloud-init schema --config-file`), its `docker run` flags never drift
from `install.sh`'s, the one placeholder stays the only one. Whether a
real, freshly created VPS actually finishes this and serves the wizard is
inherently something only booting a real server proves — the same
reasoning as this file's "Manual verification" section above, applied to
a cloud instance instead of a local VM. That is an owner action, not
something CI claims:

- [ ] Create a server on a real provider (Hetzner Cloud, DigitalOcean, or
      similar), pasting `cloud-init.yaml` with a setup code filled in
      into its user-data field; finish the setup page at
      `http://<public-address>:8420/`.
- [ ] Wait for the server to finish booting (a couple of minutes is
      typical for the package installs plus image pull).
- [ ] From a device already on the same tailnet, open the address the
      setup page showed (`http://palaia-hub/` with MagicDNS on) and
      confirm the setup wizard loads.
- [ ] Confirm the same address is *not* reachable from a device that is
      not on the tailnet (e.g. a phone on mobile data).
- [ ] If anything above did not come up, `/var/log/cloud-init-output.log`
      on the server (reachable over the tailnet, or the provider's own
      console) has the full log of what ran.

## What's in the image

Multi-stage build (`Dockerfile`):

1. **web-build** — builds `v3/web` (Vite) into a static `dist/`. Kept
   generic on purpose: the dashboard is still a skeleton (SPEC-109 lands the
   real app); this stage just builds whatever `npm run build` currently
   produces.
2. **hub-build** — installs the `palaia-hub` package from the `v3` uv
   workspace into a venv, `--no-dev`.
3. **runtime** — `python:3.12-slim` + `nginx-light` as the single public
   entry point. nginx serves the built dashboard as static files and
   reverse-proxies `/api/*` and `/mcp/*` to the hub, which binds only to
   `127.0.0.1` inside the container (`PALAIA_HOST`/`PALAIA_PORT`, internal —
   not the port you publish). Runs as a non-root user (`palaia`).

No embedding models are baked into the image — that dependency arrives with
SPEC-104 (index & hybrid search); models download on first use into the
`/data` volume (`PALAIA_HOME`). The startup log line says so.

## mDNS (`http://palaia.local:8420`)

The container runs a small announcer (`mdns_announce.py`, python-zeroconf)
that advertises `palaia.local` via mDNS, so the hub opens at
`http://palaia.local:8420/` from other devices on the same network — the
way Home Assistant's container opens at its host's name and `:8123`. The
port stays: the container runs as a non-root user with every capability
dropped, so it cannot listen on port 80 of the machine's own network
(issue #620 tracks a forwarder outside the container where that is
possible, e.g. the Pi image).

- **On Linux the container runs on the host network** (`--network host` in
  the Quick start command, `network_mode: host` in `docker-compose.yml`).
  Docker's default bridge network does not forward multicast traffic, so an
  announcement made from a bridge-network container reaches nothing outside
  it. On the host network the container sees every interface of the
  machine; the announcer advertises only its local-network addresses
  (never a Docker bridge, a virtual machine bridge or a VPN/tailnet
  address), only on those interfaces, and checks them again every half
  minute, so a network that comes up after the container, or a new DHCP
  address, is picked up without a restart. Most desktop systems and phones
  resolve `.local` names out of the box; some routers block mDNS between
  separate networks (VLANs, guest Wi-Fi).
- **The host network changes nothing about what is reachable:** port 8420
  answers on the machine's addresses exactly as `-p 8420:8420` made it
  answer; the hub's own port (8421) stays on loopback; and
  `PALAIA_CLOUD_BIND=127.0.0.1` keeps the cloud entry (8422) on the
  machine's loopback address, as the installer and compose publish it on
  the bridge network.
- **Not possible on Docker Desktop** (macOS/Windows): it runs containers
  inside a VM, so even `--network host` doesn't put the container on your
  actual network. Use its `-p 8420:8420` command and `http://localhost:8420/`.
- **Always-available fallback:** the entrypoint prints the reachable
  `http://<ip>:<port>/` URL to stdout/stderr on every start (`docker logs`),
  and the mDNS announcer logs which addresses it advertises, or that it
  has none yet. Nothing about first-run depends on mDNS working.

`PALAIA_MDNS_ENABLED=0` disables the announcer entirely (e.g. for a headless
CI smoke test, or a host where mDNS is administratively blocked).

## Updates (SPEC-501)

"Self-update" inside a container is honestly pull-and-recreate — a
container cannot portably do that to itself, and this SPEC does not
pretend otherwise. What it does ship:

- **The check.** `GET /api/update/check` compares this hub's own version
  against its configured channel's latest published version (read from
  the channel tag's own GHCR manifest — see
  `v3/server/src/palaia_hub/update.py`). Three states only:
  `up_to_date`, `update_available`, `cannot_check` — an offline hub, or
  one whose channel tag momentarily 404s, reports `cannot_check`, never
  an error page. The dashboard's "Update available" banner is driven by
  this endpoint and nothing else.
- **`palaia-hub update`** — the compose helper (deliverable #4): edits
  the pinned image tag in a compose file to a different channel
  (`--channel stable|beta`) and prints the two commands to actually
  recreate the container:
  ```bash
  palaia-hub update --channel stable --file docker-compose.yml
  docker compose pull
  docker compose up -d
  ```
  It never runs those two commands itself.
- **Watchtower.** The image carries
  `com.centurylinklabs.watchtower.enable=true`
  ([label docs](https://containrrr.dev/watchtower/container-selection/))
  for operators already running Watchtower with `--label-enable` — palaia
  itself never runs or assumes Watchtower.
- **App stores.** Umbrel/CasaOS/Runtipi/TrueNAS SCALE each have their own
  update button — a store deployment's dashboard banner points at that
  store by name instead of showing the compose helper (see
  `v3/deploy/stores/`).

### Channel and deployment

Two env vars, both baked in rather than hand-edited on a normal install:

- **`PALAIA_CHANNEL`** (`edge`/`beta`/`stable`) — baked into the image at
  build time by the release workflow, matching the GHCR tag(s) that build
  is pushed under (see `.github/workflows/v3-release.yml`'s
  `--build-arg PALAIA_CHANNEL=...`). A local `docker build` with no
  `--build-arg` stays `edge`. This is what `/api/update/check` compares
  against — a `beta`-channel hub checks the `beta` tag, a `stable`-channel
  hub checks `stable`, never the other one.
- **`PALAIA_DEPLOYMENT`** (`compose`/`umbrel`/`casaos`/`runtipi`/
  `truenas`/`home_assistant`/`unknown`) — set by whichever deployment
  package is running (the shipped `docker-compose.yml` sets `compose`;
  each `v3/deploy/stores/*` package sets its own platform's name). Only
  changes which instructions the update banner shows.

Both are surfaced back out: `channel` in `GET /api/info` and the
dashboard's footer (next to the running version), alongside `deployment`
in `GET /api/update/check`.

## Image channels

Published by `.github/workflows/v3-release.yml`:

| Tag | Trigger |
|---|---|
| `edge` | a manual run of the workflow on `main` (`workflow_dispatch`) — not built on every merge |
| `v3.<version>`, `<version>` and `stable` | a `v3.*` git tag (the bare `<version>` tag is what the Home Assistant add-on pulls — issue #394) |
| `beta` | any pre-release git tag — `v3.*-*` with a SemVer suffix (`-rc1`, `-beta2`, `-alpha1`, `-dev1`) |

Images are `linux/amd64` and `linux/arm64` (Raspberry-class hosts —
verified in CI via QEMU emulation, per the SPEC's acceptance criteria).

Each build also bakes `PALAIA_CHANNEL` (matching the table above) and an
`org.opencontainers.image.version` manifest annotation `/api/update/check`
reads back — see "Updates (SPEC-501)" above. The workflow also accepts a
manual `channel` input (`workflow_dispatch`) to additionally tag an
existing *release* `stable`/`beta` — dispatch it on the `v3.*` tag. On a
branch commit the input is refused (issue #393): such a build carries no
release version, so a `stable` pointing at it would make every hub read
"up to date" against `0.0.0` until the next real tag.

## Manual verification (fresh Linux VM)

The acceptance criteria this SPEC names are inherently environment-level
(image size, healthcheck behavior under `restart: unless-stopped`, data
surviving container recreation) rather than something a unit test proves.
Recommended check, on a fresh Linux VM with only Docker installed:

```bash
docker build -f v3/deploy/Dockerfile -t palaia-hub:local .
docker images palaia-hub:local            # check compressed size < 400MB
docker run -d --name palaia-hub -p 8420:8420 -v palaia_home:/data palaia-hub:local
curl -f http://localhost:8420/api/health  # {"status": "ok", ...}
docker inspect --format '{{.State.Health.Status}}' palaia-hub   # "healthy" once past start_period
docker restart palaia-hub                 # recreate-equivalent: container comes back, /data intact
docker exec palaia-hub ls /data           # config.yaml present from before restart
```

## Container posture

SPEC-502's hardening pass. Both the compose file and the `docker run`
one-liner apply the same set, so the two ways of starting palaia give the
same container:

| Flag | What it does | Why it is safe here |
|---|---|---|
| `USER palaia` (in the image) | The hub, nginx and the mDNS announcer all run as an unprivileged system user, pinned to uid/gid `1000:1000` so a bind-mounted `/data` can be chowned to a known number (issue #329) | Already true before this pass; listed for completeness |
| `--security-opt no-new-privileges:true` | No process inside can gain privileges through a setuid binary | Nothing in the image is setuid, and nothing a user installs later should be able to become root |
| `--cap-drop ALL` | Every Linux capability is removed | The hub binds 8421 and nginx binds 8420 — both above 1024, so not even `NET_BIND_SERVICE` is needed |
| `--read-only` plus `--tmpfs /tmp --tmpfs /run` | The image's own filesystem cannot be modified at runtime | Everything written at runtime goes to `/data` (the volume) or `/tmp/nginx` (rendered config, temp paths, pid — see `entrypoint.sh` and `nginx.conf.template`); logs go to stdout/stderr |

If you add something to the image that needs to write outside `/data` and
`/tmp`, give it its own `tmpfs` rather than dropping `--read-only`.

nginx also sets the browser-hardening headers on the static dashboard it
serves, byte-identical to the ones the hub sets on its own responses
(`palaia_hub.security.headers`) — nginx never reaches the hub process for
those files, so without them the one surface a browser actually renders
would be the only one with no policy on it.

**Verify the posture on a real daemon.** This cannot be asserted by the test
suite: the Python CI job has no Docker daemon, and these are properties of
the runtime rather than of the code.

```bash
cd v3/deploy && docker compose up -d
docker inspect palaia-hub --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}'
docker exec palaia-hub id                       # uid/gid of `palaia`, not 0
docker exec palaia-hub touch /opt/palaia/nope   # must fail: read-only file system
curl -si http://localhost:8420/ | grep -i content-security-policy
curl -si http://localhost:8420/oauth/login | head -1   # reaches the hub, not the SPA shell
```
