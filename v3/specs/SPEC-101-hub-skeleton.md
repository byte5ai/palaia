---
id: SPEC-101
title: Hub daemon skeleton, config, logging
phase: 1
depends_on: [SPEC-001]
model: sonnet-5
effort: medium
status: draft
---

# SPEC-101: Hub daemon skeleton, config, logging

## Goal
The long-running process everything else plugs into: one FastAPI app hosting
(a) the REST/dashboard API, (b) mount points for the MCP gateway (SPEC-105),
with configuration, logging and health done once, properly.

## Deliverables
1. `palaia_hub.app` — ASGI app factory; uvicorn entry `palaia-hub serve`;
   graceful shutdown (finish in-flight writes).
2. **Config system**: single `config.yaml` in a platform data dir
   (`PALAIA_HOME` override), pydantic-validated, env-var overrides
   (`PALAIA_*`), safe defaults for everything (zero-config first run creates a
   commented default file). Operating mode field (`locked|cloud|open`) exists
   from day one, default `locked`.
3. **Logging**: structured (JSON option), human-readable default, **secret
   redaction filter** (never log tokens/keys), per-component levels.
4. `/api/health` (liveness + component readiness) and `/api/info` (version,
   mode, uptime).
5. Version singleton: ONE source (`palaia_hub.__version__`) — nothing else may
   restate the version (v2's six-file sync pain must not return).

## Acceptance criteria
- [ ] `palaia-hub serve` starts with zero config and serves /api/health green
- [ ] invalid config → startup fails with a message naming file, key, and fix
- [ ] a token passed through logging paths is redacted in output (test proves)
- [ ] SIGTERM during a simulated slow request → request completes, then exit
- [ ] unit tests for config precedence (defaults < file < env)

## Non-goals
No MCP serving (105), no auth (108), no persistence (102), no UI.
