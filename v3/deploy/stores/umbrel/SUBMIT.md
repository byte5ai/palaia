# Submitting palaia to the Umbrel App Store

Source: `getumbrel/umbrel-apps` — PR-based listing, or a self-maintained
Community App Store added by URL (v3/research/mcp-landscape-2026.md §8).
This package targets the PR route (the store 90%+ of Umbrel users already
browse); the Community App Store route needs no submission at all — see
"Faster alternative" below.

`umbrel-app.yml` here was written against a real, currently-listed app's
manifest (`syncthing/umbrel-app.yml` in that repo) field-for-field, since
Umbrel does not publish a standalone schema document — the shipped apps
*are* the schema. `docker-compose.yml` follows the same app's
`app_proxy` + volume-under-`${APP_DATA_DIR}` convention.

## Steps

1. Fork `getumbrel/umbrel-apps`.
2. Create a `palaia/` directory at the repo root containing this
   directory's `umbrel-app.yml` and `docker-compose.yml` verbatim.
3. Read that repo's own `AGENTS.md` and `.claude/skills/` — its README
   points contributors there for the current packaging/verification
   checklist, which is more current than anything this repo can pin.
   Confirm in particular:
   - `category: ai` is still a value their app list actually accepts
     (unverified here — pick the closest current category if not).
   - Where the icon goes. Umbrel apps are commonly illustrated via a
     separate assets pipeline (a CDN-backed icon set) rather than a file
     living next to `umbrel-app.yml`; `icon.png` in this directory is
     palaia's placeholder mark (`v3/tools/build-mcpb/generate_icon.py`) —
     follow their current asset instructions for where it actually needs
     to live, rather than assuming this file's location.
4. Run their local validation script (their README/`AGENTS.md` names it)
   against your `palaia/` directory before opening the PR.
5. Open the PR. Fill in `submission:` in `umbrel-app.yml` with its URL
   once opened (a manifest field their tooling reads back).

## Faster alternative: a Community App Store

Umbrel also supports third-party app stores added by URL, no PR or review
needed (v3/research/mcp-landscape-2026.md §8). Publishing this same
`palaia/` directory (this `umbrel-app.yml` + `docker-compose.yml`) at the
root of a small public git repo, then following Umbrel's own "Community
App Stores" instructions to register that repo's URL, gets palaia
installable today — worth doing in parallel with the PR above, which can
take a while to review.

## What to update before every release

`version` in `umbrel-app.yml` and the image tag in `docker-compose.yml`
should track the `stable` channel — bump `version` on each release; the
`:stable` tag itself always points at the current release already (no
edit needed there unless you want to pin an exact `v3.<version>` tag
instead of the moving `stable` alias).
