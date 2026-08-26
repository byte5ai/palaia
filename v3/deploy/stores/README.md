# App-store packages (SPEC-501)

MASTERPLAN §9.2: palaia installable where self-hosters already shop.
Every subdirectory here is a ready-to-submit package for one store,
pinning the GHCR image (SPEC-112) at the `stable` channel tag and setting
`PALAIA_DEPLOYMENT` to that platform's name — the field
`GET /api/update/check`'s guidance reads to point the dashboard's "Update
available" banner at the right place (`v3/server/src/palaia_hub/update.py`).

| Directory | Platform | Route |
|---|---|---|
| `umbrel/` | Umbrel | PR to `getumbrel/umbrel-apps`, or a self-hosted Community App Store |
| `casaos/` | CasaOS | PR to `IceWhaleTech/CasaOS-AppStore`, or a third-party store by URL |
| `runtipi/` | Runtipi | Publish your own app store (official repo is closed to new apps) |
| `truenas/` | TrueNAS SCALE | PR to `truenas/apps`, `community` train |
| `home-assistant/` | Home Assistant | `EVALUATION.md` + a working add-on `config.yaml` |

Submitting any of these is an owner action — see each directory's own
`SUBMIT.md` (or, for Home Assistant, `EVALUATION.md`) for the exact
steps, what was verified against a real listing versus inferred from
docs, and what to update on every release.

## What's shared across every package

- **Image**: `ghcr.io/byte5ai/palaia-hub:stable` (or, for Home Assistant,
  the equivalent `image`/`version` pair) — never `beta` or `edge`. A
  store listing is what a new user finds first; it should always install
  the same thing `docker compose up -d` against the shipped
  `v3/deploy/docker-compose.yml` would.
- **`PALAIA_DEPLOYMENT`**: set to that platform's own name
  (`umbrel`/`casaos`/`runtipi`/`truenas`/`home_assistant`), so the
  dashboard's update banner says "open $STORE to update" by name instead
  of showing the compose helper a store user has no use for (SPEC-501
  deliverable #4 — see `update_guidance` in
  `v3/server/src/palaia_hub/update.py`).
- **Jargon-free copy**: every description/tagline a store actually shows
  a browsing user avoids palaia's own internal vocabulary (checked
  against `palaia_addon_sdk.jargon`'s shared blocklist in
  `server/tests/deploy/test_store_manifests.py` — the same blocklist the
  add-on SDK and skill lint already use).
- **Icon**: `icon.png` (or `logo.png` for Runtipi) in each package
  directory is palaia's placeholder mark, generated the same
  dependency-free way as the MCPB bundle's own icon
  (`v3/tools/build-mcpb/generate_icon.py` — see that script's docstring
  for why it's hand-built PNG bytes rather than a design asset checked in
  as a binary from elsewhere).

## Validation

`server/tests/deploy/test_store_manifests.py` — one pydantic model per
platform, built from that platform's own docs and (where reachable) a
real currently-listed app's manifest, since none of Umbrel/CasaOS/Runtipi
publish a standalone offline schema document to run a linter against.
Each model's docstring cites its source. Run it with the rest of the
suite: `uv run pytest server/tests -q` from `v3/`.
