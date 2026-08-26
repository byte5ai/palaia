"""Gateway spike: one process, two profile endpoints, mixed local + remote mounts.

Answers SPEC-002 questions 1-4 with running code:

  Q1  Two servers (one local in-process, one remote via a proxy) mounted
      behind ONE streamable-HTTP app, with namespaced tool names.
  Q2  Per-path profiles: /mcp/full exposes both mounts, /mcp/memory-only
      exposes only the local one — same running process, different tool
      surfaces, selected purely by the URL the client connects to.
  Q3  Static bearer-token auth, independent per profile.
  Q4  A tool rename survives the mount: the remote server's `echo` tool is
      exposed under a custom name (`remote_say`) and the original namespaced
      name (`remote_echo`) does NOT appear in the profile that renamed it.

Prerequisite: `servers/remote_upstream.py` must already be running on
REMOTE_UPSTREAM_PORT (default 8811) — see README.md / scripts/run_all.sh.

Run: `uv run python gateway.py`
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from fastmcp.utilities.lifespan import combine_lifespans
from servers.local_memory import local_server
from starlette.applications import Starlette
from starlette.routing import Mount

REMOTE_UPSTREAM_URL = os.environ.get(
    "REMOTE_UPSTREAM_URL", "http://127.0.0.1:8811/mcp"
)
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8900"))

# --- Q3: static bearer-token auth, independent per profile -----------------
# Two disjoint token sets: a client with the "full" token cannot use the
# "memory-only" path's token and vice versa (each profile is its own
# StaticTokenVerifier / its own FastMCP(auth=...) instance).
FULL_TOKEN = "full-profile-secret-token"
MEMORY_ONLY_TOKEN = "memory-only-profile-secret-token"

full_auth = StaticTokenVerifier(
    tokens={
        FULL_TOKEN: {
            "client_id": "spike-full-client",
            "scopes": ["mcp:full"],
        }
    },
    required_scopes=["mcp:full"],
)
memory_only_auth = StaticTokenVerifier(
    tokens={
        MEMORY_ONLY_TOKEN: {
            "client_id": "spike-memory-only-client",
            "scopes": ["mcp:memory"],
        }
    },
    required_scopes=["mcp:memory"],
)


def build_full_profile() -> FastMCP:
    """The /mcp/full profile: local memory + remote upstream, both mounted."""
    gw = FastMCP(name="palaia-gateway-full", auth=full_auth)

    # Q1a: local, in-process mount — no network hop.
    gw.mount(local_server, namespace="local")

    # Q1b: remote mount via a proxy over streamable HTTP.
    remote_proxy = FastMCP.as_proxy(REMOTE_UPSTREAM_URL)
    # Q4: rename `echo` -> `remote_say` on the way in. tool_names renames are
    # applied BEFORE the namespace prefix (per fastmcp/server/server.py's own
    # comment: "foo -> bar with namespace='baz' becomes baz_bar"), so the
    # rename value here is "say", not "remote_say" — namespacing still adds
    # the "remote_" prefix on top. Without tool_names, namespacing alone
    # would have exposed it as `remote_echo`; with it, only `remote_say`
    # is visible and `remote_echo` disappears entirely.
    gw.mount(remote_proxy, namespace="remote", tool_names={"echo": "say"})

    return gw


def build_memory_only_profile() -> FastMCP:
    """The /mcp/memory-only profile: local memory only, remote NOT mounted."""
    gw = FastMCP(name="palaia-gateway-memory-only", auth=memory_only_auth)
    gw.mount(local_server, namespace="local")
    return gw


full_profile = build_full_profile()
memory_only_profile = build_memory_only_profile()

# Q2: per-path profiles as separate ASGI apps under one Starlette parent,
# each addressable by its own URL — the pattern MASTERPLAN §5.2 calls out
# (proven by MCPHub's group endpoints). No client-side filtering: the URL
# a client connects to already selects the tool surface.
_full_asgi = full_profile.http_app(path="/")
_memory_only_asgi = memory_only_profile.http_app(path="/")

# Each mounted FastMCP ASGI app owns a lifespan that starts its streamable-HTTP
# session manager task group. A plain Starlette parent does NOT propagate
# lifespan into mounted sub-apps, so both must be combined into the parent's
# own lifespan or the session managers never start (first request hangs).
app = Starlette(
    routes=[
        Mount("/mcp/full", app=_full_asgi),
        Mount("/mcp/memory-only", app=_memory_only_asgi),
    ],
    lifespan=combine_lifespans(_full_asgi.lifespan, _memory_only_asgi.lifespan),
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=GATEWAY_PORT, log_level="info")
