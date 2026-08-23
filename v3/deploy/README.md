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
  ghcr.io/byte5ai/palaia-hub:stable
```

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

## Update path v0

Phase 1 ships **manual** updates only (one-click self-update is Phase 2+,
per the SPEC's non-goals):

- `docker pull ghcr.io/byte5ai/palaia-hub:stable && docker compose up -d`
  (or the equivalent `docker run` after `docker rm`), reusing the same
  named volume — data (vault, index, config under `/data`) survives.
- The dashboard shows the running version (`/api/info`) versus the latest
  published GHCR tag so a user knows an update exists; it links to the
  command above rather than performing it. The GHCR tag check itself lands
  with the dashboard SPECs (109/110) — packaging's job here is only to
  publish `stable`/`beta`/`edge` tags predictably (see the release
  workflow) so that check has something to read.

## Image channels

Published by `.github/workflows/v3-release.yml`:

| Tag | Trigger |
|---|---|
| `edge` | every push to `main` touching `v3/**` |
| `v3.<version>` and `stable` | a `v3.*` git tag |
| `beta` | a `v3.*-beta*` / `v3.*-rc*` git tag |

Images are `linux/amd64` and `linux/arm64` (Raspberry-class hosts —
verified in CI via QEMU emulation, per the SPEC's acceptance criteria).

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
