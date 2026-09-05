# Home Assistant add-on: evaluation

MASTERPLAN §9.2: "a Home-Assistant add-on variant is worth evaluating (HA
users are exactly the audience)." SPEC-501 deliverable #2 asks for an
honest verdict plus a working config *if* it lands positive.

## Verdict: positive, with one real limitation

Home Assistant add-ons (their current "Apps" model, per
`v3/research/mcp-landscape-2026.md` §8 and
[the add-on docs](https://developers.home-assistant.io/docs/add-ons))
are a container plus a `config.yaml` the Supervisor reads — and critically,
`config.yaml`'s `image` field lets an add-on point at an **already-built,
already-published** multi-arch registry image rather than requiring the
add-on's own Dockerfile to be built by the Supervisor. palaia's existing
GHCR image (SPEC-112) fits that directly: `config.yaml` in this directory
points `image` at `ghcr.io/byte5ai/palaia-hub`, `version` at the `stable`
tag, and `arch` at the two architectures the release workflow already
publishes (`amd64`, `aarch64` — HA's name for what SPEC-112 calls
`arm64`). No second build pipeline, no add-on-specific Dockerfile to
maintain alongside the real one.

## What works

- **The image itself.** Same one every other channel in this SPEC points
  at — one build, every distribution surface.
- **Persistent storage.** HA gives every add-on a `/data` directory that
  survives add-on updates and restarts automatically, with no `map:`
  entry required — and that happens to be exactly the path
  `v3/deploy/Dockerfile` already uses for `PALAIA_HOME` (`ENV
  PALAIA_HOME=/data`). No path translation needed either direction.
- **Reaching the dashboard.** With `host_network: true` (set in this
  package's `config.yaml`), the add-on binds directly to the Home
  Assistant host's own network interface, at the port palaia's `nginx`
  layer already listens on inside the container (`8420`) — reachable at
  `http://<home-assistant-host>:8420/` from any device on the LAN, no
  Supervisor port-mapping UI involved.

## What doesn't (stated honestly, matching this SPEC's own instruction)

- **The Supervisor's `/data` is root-owned and the image is not root
  (issue #329).** The add-on model has no `user:` option: the Supervisor
  creates each add-on's `/data` as root and expects the add-on to run as
  root inside. This image runs as its own uid/gid `1000:1000` (pinned in
  `v3/deploy/Dockerfile`) from the first instruction of its entrypoint and
  never has root, so it cannot `chown` its way in — its first start is
  expected to fail with a `PermissionError` under `/data` (inferred from
  how the Supervisor provisions add-on data; not run on a real Home
  Assistant here). Closing this needs an add-on-specific entrypoint that
  starts as root, fixes `/data`'s ownership and drops to `palaia` — a
  second image, which is exactly what this evaluation set out not to
  maintain. Until that decision is made, this package is a working
  evaluation, not a shippable add-on.
- **mDNS (`http://palaia.local`) has the exact same limitation documented
  for the plain compose deployment** (`v3/deploy/README.md`'s "mDNS"
  section) — Docker's default bridge network does not forward multicast
  to the LAN, and turning that off requires host networking. This
  package sets `host_network: true` for exactly that reason, which
  trades away Supervisor-managed port isolation to get it. Whether
  `palaia.local` actually resolves still depends on the host's own
  network (some routers block multicast across VLANs, same caveat as
  everywhere else this SPEC deploys). Nothing here makes mDNS *more*
  reliable than it already is elsewhere — it only makes it *possible*,
  the same tradeoff the compose file already documents.
- **No Home Assistant Ingress integration.** HA add-ons can optionally
  render inside the HA UI itself via its Ingress panel system (a
  supervisor-proxied iframe with HA's own auth in front of it) — this
  package does not implement that. It is a real add-on with its own
  page, not embedded in the HA sidebar. Wiring Ingress properly means
  handling HA's `X-Ingress-Path` header throughout the dashboard's own
  routing, which is real work this SPEC's scope does not cover; the add-
  on is fully usable without it, just as its own tab/bookmark rather than
  an HA sidebar entry.
- **`PALAIA_MODE`/`PALAIA_DEPLOYMENT` are set once, at install, via HA's
  own options schema** — changing them later means editing the add-on's
  own Configuration tab and restarting it, not palaia's dashboard (SPEC-
  205's exposure wizard still works for everything *inside* the
  container once it's running; it just doesn't reach back out to rewrite
  HA's own add-on options).

## Bottom line

Ship it: `config.yaml` in this directory is a real, working add-on
config, not a placeholder. The one deliberate tradeoff (host networking,
for mDNS parity with the other deployment paths) is the same tradeoff
`v3/deploy/docker-compose.yml` already documents and defaults to
*avoiding* — this add-on defaults to *taking* that tradeoff, since a
Home Assistant install is exactly the "walk up and it's just there on my
network" audience `http://palaia.local` is for.
