# Publishing palaia as a Runtipi app store

Runtipi's own official app repository is closed to new submissions — the
only current path is publishing your **own** custom app store that
Runtipi users add by URL
(https://runtipi.io/docs/guides/create-your-own-app-store,
v3/research/mcp-landscape-2026.md §8). This directory is that store's one
app.

**Status, in one sentence (issue #395):** written to Runtipi's classic app
format from its custom-app-store guide — `config.json` with
`dynamic_config: false`, a plain `docker-compose.yml` with `${APP_PORT}`,
`${APP_DATA_DIR}` and `tipi_main_network` — and **not yet loaded into a
real Runtipi instance** (none exists in this repository's environment).
Step 5 below is where it is validated; until someone has done that, this
is a well-grounded draft, not a published-and-working store. `exposable`
is `false` on purpose: the app is reached on its Runtipi port on the LAN,
and palaia's own Access page handles remote access (Tailscale,
cloudflared), so no reverse-proxy labels are needed here.

## Steps

1. Create a small public git repository (this is the "app store" itself —
   Runtipi's guide expects one app-store repo, which can hold any number
   of apps; palaia can be its only app for now).
2. Copy this directory's `apps/palaia/` folder to that repo's `apps/`
   directory, unchanged.
3. `metadata/logo.png` here is palaia's placeholder mark
   (`v3/tools/build-mcpb/generate_icon.py`) — the guide's own example
   names this file `logo.jpg`; rename/re-encode if your Runtipi version's
   loader is strict about the extension matching the actual format (this
   file is a PNG, not a JPEG, despite either name working in most image
   loaders — confirm before publishing).
4. Follow the guide's own steps for making the repo installable
   (an `apps.json`/store index at the repo root, per Runtipi's current
   instructions — the exact file the guide asks for was not duplicated
   here since it names the *store*, not this one app).
5. In a real Runtipi instance: Settings → App Stores → add your repo's
   URL. palaia should appear in the app list.
6. Fill in `created_at`/`updated_at` in `config.json` with the real
   publish time (Unix milliseconds) — JSON has no comment syntax to flag
   this inline, so it is flagged here instead; the placeholder values are
   simply "2025-08-24", not a lie about permanence.

## Data directory ownership

The container runs as uid/gid `1000:1000` (pinned in `v3/deploy/Dockerfile`,
issue #329), and `docker-compose.yml` says so with `user: "1000:1000"`.
`${APP_DATA_DIR}/data` is a bind mount, so it keeps the host's ownership —
Runtipi's own app data is commonly `1000:1000` (inferred from its app-store
convention; not verified on a live Runtipi here). If the first boot logs a
`PermissionError` under `/data`, fix the ownership once on the host:

```bash
sudo chown -R 1000:1000 "${APP_DATA_DIR}/data"
```

## What to update before every release

`version` in `config.json` and the image tag in `docker-compose.yml`
should track the `stable` channel — bump `version` on each release; the
`:stable` tag itself always points at the current release already.
