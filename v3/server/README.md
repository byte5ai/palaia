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

## Running it

```bash
cd v3
uv run palaia-hub serve
```

Then `curl http://127.0.0.1:8420/api/health`.
