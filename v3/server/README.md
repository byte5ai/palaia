# palaia_hub

Python core of the palaia v3 hub daemon.

## What's here (SPEC-101)

- `palaia_hub.app.create_app()` — FastAPI app factory serving `/api/health`
  and `/api/info`, plus (SPEC-105, below) an optional `gateway=` parameter
  that mounts the MCP gateway. Auth and persistence land in SPEC-108,
  SPEC-102 respectively.
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

## MCP gateway (SPEC-105)

`palaia_hub.gateway` builds the streamable-HTTP MCP endpoint: one memory
tool family (`search`/`read`/`write`/`edit`/`move`/`delete`/`list`/
`recent_activity`) per configured vault, mounted into one or more
addressable profiles (`/mcp/<profile>`). It is written against a narrow
`VaultService` protocol, not against SPEC-102's vault engine directly (the
two lanes run in parallel; real wiring is SPEC-113's job) — tests use the
in-memory `FakeVaultService`.

```python
from palaia_hub.app import create_app
from palaia_hub.config import HubConfig
from palaia_hub.gateway import (
    FakeVaultService, GatewayConfig, ProfileConfig, VaultMountConfig, build_gateway,
)

config = GatewayConfig(
    vaults=[VaultMountConfig(key="work", name="work", purpose="Team knowledge.")],
    profiles=[ProfileConfig(path="default", vaults=["work"])],
)
gateway = build_gateway(config, {"work": FakeVaultService()})
app = create_app(HubConfig(), gateway=gateway)  # /mcp/default now live
```

Building blocks: `gateway/vault_protocol.py` (the protocol + result types),
`gateway/memory_tools.py` (one vault's tool family — annotations, alias
absorption, dual text/json output, IDENTITY instructions,
`ai_assistant_guide` resource), `gateway/naming.py` (tool-name
sanitization and the FastMCP `mount()` pre-namespace rename composition
rule — see its module docstring), `gateway/build.py` (assembles
per-profile `FastMCP` instances + combined lifespans per
`v3/spikes/gateway/FINDINGS.md`).

## Running it

```bash
cd v3
uv run palaia-hub serve
```

Then `curl http://127.0.0.1:8420/api/health`.
