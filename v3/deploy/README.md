# palaia v3 — packaging & distribution

SPEC-112. The 5-minute install: one container, one command, then the
browser (MASTERPLAN §9). Everything after `docker run` happens in the
first-run wizard (later SPECs).

## Quick start

```bash
docker run -d --name palaia-hub \
  -p 8420:8420 \
  -v palaia_home:/data \
  --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

The five hardening flags are explained in [`docker-compose.yml`](docker-compose.yml)
and in [Container posture](#container-posture) below; the container runs as a
non-root user either way, and drops the rest.

Then open `http://localhost:8420/` (or the host's IP, from another
machine). Or use compose:

```bash
cd v3/deploy && docker compose up -d
```

Or the convenience script (never required — see `install.sh`):

```bash
curl -fsSL https://raw.githubusercontent.com/byte5ai/palaia/main/v3/deploy/install.sh | bash
```

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

## mDNS (`http://palaia.local`)

The container runs a small announcer (`mdns_announce.py`, python-zeroconf)
that advertises `palaia.local` via mDNS. This is honestly limited by how
container networking works, not by the announcer itself:

- **Docker's default bridge network does not forward multicast traffic to
  the host's LAN.** An mDNS advertisement made from inside a bridge-network
  container is visible to nothing outside that container's own network
  namespace.
- **Fix on Linux:** run the container with `--network host` (or
  `network_mode: host` in compose — see the commented line in
  `docker-compose.yml`). The hub then binds directly to the host's network
  stack and `palaia.local` resolves for other devices on the LAN that
  support mDNS (most desktop OSes and phones do out of the box; some
  routers block mDNS across VLANs).
- **Not available the same way on Docker Desktop** (macOS/Windows): it runs
  containers inside a VM, so `--network host` doesn't put the container on
  your actual LAN. `palaia.local` will not resolve there.
- **Always-available fallback:** the entrypoint prints the reachable
  `http://<ip>:<port>/` URL to stdout/stderr on every start (`docker logs`),
  and the mDNS announcer separately logs whether it managed to determine an
  address to advertise at all. Nothing about first-run depends on mDNS
  working.

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
| `edge` | every push to `main` touching `v3/**` |
| `v3.<version>` and `stable` | a `v3.*` git tag |
| `beta` | a `v3.*-beta*` / `v3.*-rc*` git tag |

Images are `linux/amd64` and `linux/arm64` (Raspberry-class hosts —
verified in CI via QEMU emulation, per the SPEC's acceptance criteria).

Each build also bakes `PALAIA_CHANNEL` (matching the table above) and an
`org.opencontainers.image.version` manifest annotation `/api/update/check`
reads back — see "Updates (SPEC-501)" above. The workflow also accepts a
manual `channel` input (`workflow_dispatch`) to additionally tag an
existing build `stable`/`beta` without cutting a new git tag.

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
| `USER palaia` (in the image) | The hub, nginx and the mDNS announcer all run as an unprivileged system user | Already true before this pass; listed for completeness |
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
