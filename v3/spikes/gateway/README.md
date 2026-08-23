# Spike: FastMCP gateway proof (SPEC-002)

Throwaway code, not production quality (see the SPEC's Non-goals) — **the
deliverable is [FINDINGS.md](FINDINGS.md)**. Excluded from the v3 CI quality
gates. Self-contained: its own `pyproject.toml`/`uv.lock`, `--no-workspace`,
no dependency on `v3/pyproject.toml` (owned by SPEC-001) or any v2 file.

## Layout

- `servers/local_memory.py` — an in-process FastMCP server (`local_search`,
  `memory_write`) standing in for a first-party palaia component.
- `servers/remote_upstream.py` — a standalone FastMCP server (`echo`,
  `weather`) run as a separate process on `:8811`, standing in for a
  third-party MCP connector the gateway reaches over the network.
- `gateway.py` — the gateway itself: mounts both servers behind two
  bearer-auth profiles (`/mcp/full`, `/mcp/memory-only`) on one Starlette app
  (`:8900`), with a tool rename applied to the remote mount.
- `scripts/mcp_client.py` — a scripted MCP client (official `mcp` python-sdk,
  streamable HTTP) used to interrogate the gateway for Q1-Q4.
- `scripts/run_all.sh` — starts both servers, runs every scripted check, saves
  transcripts to `transcripts/`, tears the servers down.
- `transcripts/` — captured evidence: tool listings, tool calls, rejected
  auth, and two **real Claude Code CLI** end-to-end runs (Q5).

## Running it

```bash
cd v3/spikes/gateway
uv sync                 # installs fastmcp 3.x + mcp python-sdk into .venv
bash scripts/run_all.sh # Q1-Q4, writes transcripts/*.log
```

Q5's real-client run is manual (see FINDINGS.md, Q5) because it drives the
actual `claude` CLI as a separate process and mutates the *global* user
config for the duration of the test (cleaned up after). It is not part of
`run_all.sh` on purpose.

## Findings

See [FINDINGS.md](FINDINGS.md).
