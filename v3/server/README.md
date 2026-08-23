# palaia_hub

Python core of the palaia v3 hub daemon.

## What's here (SPEC-101)

- `palaia_hub.app.create_app()` — FastAPI app factory serving `/api/health`
  and `/api/info`. No MCP serving, auth, or persistence yet — those land in
  SPEC-105, SPEC-108, SPEC-102 respectively.
- `palaia_hub.config` — single `config.yaml` in a platform data dir
  (override with `PALAIA_HOME`), pydantic-validated, with `PALAIA_*` env
  overrides. Precedence: defaults < file < env. Zero-config first run
  creates a commented default file. Invalid config fails startup with a
  message naming the file, the key, and a fix.
- `palaia_hub.logging` — structured logging (human default, JSON via
  `log_format: json`), per-component levels, and a mandatory redaction
  filter that masks tokens/keys/secrets/passwords before they reach output.
- `palaia_hub.cli` — the `palaia-hub` console script; `palaia-hub serve`
  runs the app under uvicorn with graceful shutdown (in-flight requests
  finish before the process exits on SIGTERM/SIGINT).
- `palaia_hub.__version__` is the single source of version truth;
  `pyproject.toml` reads it back dynamically via `[tool.hatch.version]`
  rather than restating it.

## Dashboard shell support (SPEC-109)

- `palaia_hub.events` — `/api/events`, a Server-Sent Events stream:
  periodic `health` snapshots plus `vault_changed` events from a
  filesystem watcher (opt-in via `PALAIA_WATCH_DIR`; unset means health
  events only — no error). Self-contained: it defines its own tiny
  in-process event bus rather than depending on SPEC-102's vault engine
  bus, since the two SPECs run in parallel on this package.
- `palaia_hub.static` — serves the dashboard's `npm run build` output
  (`v3/web/dist` by default, overridable via `PALAIA_WEB_DIST`) with SPA
  fallback, mounted last so `/api/*` always wins. Serving is optional: a
  checkout without a frontend build still starts with zero config.

## Running it

```bash
cd v3
uv run palaia-hub serve
```

Then `curl http://127.0.0.1:8420/api/health`.
