# SPEC-002 Findings: FastMCP gateway proof

Spike code: [`v3/spikes/gateway/`](.). Versions used (pinned in
[`pyproject.toml`](pyproject.toml)/[`uv.lock`](uv.lock), installed via `uv`):
**FastMCP 3.4.7**, **MCP python-sdk (`mcp`) 1.29.0**, Starlette 1.6.0,
uvicorn 0.52.4, Python 3.12.3. Real-client verification used the `claude` CLI
already present in the execution sandbox, version **2.1.239 (Claude Code)**.

Context read first, per the SPEC's execution notes: MASTERPLAN §5.2
(Gateway), research/mcp-landscape-2026.md §1 (MCP spec) and §5 (FastMCP).

---

## Q1 — Can FastMCP 3.x mount a local in-process server and a remote server
(via a proxy) behind ONE streamable-HTTP endpoint with namespaced tools?

**Answer: yes.**

`gateway.py` builds one `FastMCP` app (`build_full_profile`) that:

```python
gw.mount(local_server, namespace="local")                 # in-process
remote_proxy = FastMCP.as_proxy(REMOTE_UPSTREAM_URL)       # remote, over HTTP
gw.mount(remote_proxy, namespace="remote", tool_names={"echo": "say"})
```

`local_server` (`servers/local_memory.py`) is imported and mounted directly —
no network hop. `servers/remote_upstream.py` is a **separate OS process**
listening on `127.0.0.1:8811`; `FastMCP.as_proxy(url)` returns a
`FastMCPProxy` (`fastmcp.server.providers.proxy.ProxyProvider` under the
hood) that forwards every call over its own streamable-HTTP client
connection. Both mounts are served from the same `/mcp/full/` endpoint with
namespaced tool names:

```
tool surface for profile 'full' (4): ['local_memory_search', 'local_memory_write', 'remote_say', 'remote_weather']
```
(`transcripts/q1_q2_full_tool_list.log`)

A call to the in-process tool and a call to the proxied remote tool both
round-trip correctly through the one endpoint:

```
--- calling local_memory_search({'query': 'onboarding'})
--- result: local-memory: 2 hits for 'onboarding' (fixture data, spike only)
```
(`transcripts/q1_call_local_tool_via_full.log`)

```
--- calling remote_say({'text': 'hello from the spike'})
--- result: remote-upstream echo: hello from the spike
```
(`transcripts/q1_call_remote_tool_via_full.log` — `remote-upstream echo:` is
the literal string returned by the *separate process* on `:8811`, proving the
call actually left the gateway process.)

`FastMCP.as_proxy()` logs a deprecation warning in 3.4.7
(`transcripts/q5_gateway_server.log:1`): *"Use `create_proxy()` from
`fastmcp.server` instead"*. It still works correctly; SPEC-105 should call
`create_proxy()` directly rather than `as_proxy()`.

---

## Q2 — Do per-path profiles work (`/mcp/full` vs `/mcp/memory-only` exposing
different tool subsets of the same mounts)?

**Answer: yes, but not via FastMCP's own per-session `Visibility` transform —
via two separate `FastMCP` instances mounted at two Starlette routes.**

FastMCP 3.4.7 ships a `Visibility` transform
(`fastmcp/server/transforms/visibility.py`) that marks components
enabled/disabled, plus `enable_components`/`disable_components` helpers —
but those are keyed to **the current MCP session**, not to the HTTP path a
request arrived on. There is no built-in "serve different tool subsets at
different URL paths from one FastMCP instance" primitive. The pattern that
actually delivers the addressable-profile requirement from MASTERPLAN §5.2
(and the one implied by the MCPHub group-endpoints precedent it cites) is:
build one `FastMCP()` instance **per profile**, mount whatever that profile
should expose, turn each into its own ASGI app via `.http_app()`, and combine
them under one Starlette parent:

```python
app = Starlette(routes=[
    Mount("/mcp/full", app=full_profile.http_app(path="/")),
    Mount("/mcp/memory-only", app=memory_only_profile.http_app(path="/")),
], lifespan=combine_lifespans(_full_asgi.lifespan, _memory_only_asgi.lifespan))
```

Evidence — the two paths expose different tool counts from the same running
process:

```
tool surface for profile 'full' (4): ['local_memory_search', 'local_memory_write', 'remote_say', 'remote_weather']
tool surface for profile 'memory-only' (2): ['local_memory_search', 'local_memory_write']
```
(`transcripts/q1_q2_full_tool_list.log`, `transcripts/q1_q2_memory_only_tool_list.log`)

**Surprise / sharp edge:** a plain `Starlette(routes=[Mount(...), Mount(...)])`
does **not** propagate the ASGI `lifespan` scope into mounted sub-apps. Each
FastMCP `.http_app()` owns a lifespan that starts its streamable-HTTP session
manager task group; without combining lifespans explicitly (`combine_lifespans`
from `fastmcp.utilities.lifespan`, built for exactly this — see its own
FastAPI-mounting example), the first request against a profile hangs. This
cost real debugging time in the spike and will cost it again in SPEC-105 if
not called out up front.

---

## Q3 — Does static bearer-token auth per profile work, and what does
FastMCP's auth layer need for the later OAuth upgrade (CIMD support present)?

**Answer: yes to both.**

Each profile got its own `FastMCP(auth=StaticTokenVerifier(tokens={...},
required_scopes=[...]))` (`fastmcp.server.auth.providers.jwt.StaticTokenVerifier`)
with disjoint token sets. Correct token → success (see Q1/Q2 transcripts,
all authenticated with `full-profile-secret-token` or
`memory-only-profile-secret-token`). Wrong token and **cross-profile** token
(the `full` token presented at `/mcp/memory-only`) are both rejected with a
real 401 from the ASGI layer, before any MCP-level handshake happens:

```
--- connecting to http://127.0.0.1:8900/mcp/memory-only/
--- AUTH/HTTP REJECTED as expected? status=401 (Client error '401 Unauthorized' ...)
```
(`transcripts/q3_cross_profile_token_rejected.log`; `q3_wrong_token_rejected.log`
is the same shape for a token that matches no profile at all.)

CIMD (OAuth 2.1 Client ID Metadata Documents — the client-registration path
MASTERPLAN §5.5/research §1 flag as the post-DCR-deprecation direction) has
first-class, if beta, support in this FastMCP version:
`fastmcp/server/auth/cimd.py` ships `CIMDDocument`, `CIMDFetcher` (with SSRF
protection — `ssrf_safe_fetch_response`), `CIMDAssertionValidator`, and
`CIMDClientManager`, explicitly labeled *"Beta Feature: CIMD support is
currently in beta. The API may change in future releases."* This matches
the research dossier's claim (§5: "OAuth providers … per-component
auth/scopes, CIMD support") with file-level evidence, and tells SPEC-108
the building blocks exist but should be treated as pre-1.0 API surface, not
load-bearing yet.

---

## Q4 — Do tool renames/aliases survive the mount (rename a mounted tool,
verify a client sees only the new name)?

**Answer: yes — and the rename fully replaces the namespaced name, it does
not add an alias alongside it.**

`gw.mount(remote_proxy, namespace="remote", tool_names={"echo": "say"})`
produces the tool `remote_say`. The **un-renamed** namespaced form,
`remote_echo`, is not merely hidden — it does not exist as a callable tool
at all:

```
--- calling remote_echo({'text': 'should not exist'})
--- result: Unknown tool: 'remote_echo'
--- call reported isError=True
```
(`transcripts/q4_original_remote_name_absent.log`)

**Surprise, with a fix:** `tool_names` renames are applied *before* the
namespace prefix, not after — `fastmcp/server/server.py`'s own comment on
`mount()` states it plainly: *"Apply tool renames first (scoped to this
provider), then namespace. So foo → bar with namespace='baz' becomes
baz_bar."* The first version of this spike passed `tool_names={"echo":
"remote_say"}` expecting the literal final name `remote_say`, and got
`remote_remote_say` instead (double-prefixed) — calls to `remote_say` then
failed as `Unknown tool`. The fix was to pass the *pre-namespace* value
(`"say"`); the namespace step then produces `remote_say`. This is a real
foot-gun for SPEC-105's rename UI (MASTERPLAN §5.2: "the user can rename
**all of them** in the dashboard") — the dashboard must either hide the
namespace from the rename input entirely (store/display only the
already-composed final name and diff it back to a pre-namespace value) or
document the composition rule prominently, or renames will silently produce
double-prefixed tool names the first time someone tries it.

---

## Q5 — Does Claude Code (`claude mcp add --transport http`) connect and
call tools through the gateway end-to-end? Handshake/version quirks?

**Answer: yes — verified with the real `claude` CLI, not a substitute.** The
CLI turned out to be present in this sandbox, so the SPEC's fallback path
(scripted python-sdk client + documented manual steps) was not needed for
the connect-and-call part; it was still built and used for Q1-Q4 above,
and the manual steps are documented below for a human running this outside
a sandbox that happens to have the CLI.

Real end-to-end run, `local` scope (private config, not `.mcp.json` — no
repo file written):

```
$ claude mcp add --transport http gw-spike-full "http://127.0.0.1:8900/mcp/full/" \
    --header "Authorization: Bearer full-profile-secret-token" --scope local
Added HTTP MCP server gw-spike-full ... File modified: /root/.claude.json [project: .../v3/spikes/gateway]

$ claude mcp list
gw-spike-full: http://127.0.0.1:8900/mcp/full/ (HTTP) - Connected

$ claude mcp get gw-spike-full
Status: Connected
```

Then a real one-shot model turn calling the **in-process** tool:

```
$ claude -p "Call the mcp__gw-spike-full__local_memory_search tool with query='spike-e2e-check' and then reply with ONLY the exact raw text the tool returned, nothing else." \
    --allowedTools "mcp__gw-spike-full__local_memory_search" --output-format json
{"is_error": false, "subtype": "success", "num_turns": 3,
 "result": "local-memory: 2 hits for 'spike-e2e-check' (fixture data, spike only)"}
```
(full JSON, trimmed to the load-bearing fields: `transcripts/q5_real_claude_code_e2e.log`)

and the **remote, renamed** tool, in the same profile:

```
$ claude -p "Call the mcp__gw-spike-full__remote_say tool with text='real-claude-code-e2e' ..." \
    --allowedTools "mcp__gw-spike-full__remote_say" --output-format json
{"is_error": false, "subtype": "success", "num_turns": 3,
 "result": "remote-upstream echo: real-claude-code-e2e"}
```
(full JSON, trimmed to the load-bearing fields: `transcripts/q5_real_claude_code_e2e_remote.log`)

Both results are the literal strings the two backend tools produce —
confirming the full path Claude Code → gateway (`/mcp/full`) → namespaced
mount (local, then remote-via-proxy) → response, for both a local and a
network-proxied, **renamed** tool. The MCP server entry was removed again
after the test (`claude mcp remove gw-spike-full -s local`); nothing was left
in the global config.

**Handshake/version quirk observed:** every new client connection to the
gateway logs one `400 Bad Request` immediately before the successful
`200 OK` / `202 Accepted` / `200 OK` (GET stream) / `200 OK` (list/call)
sequence (`transcripts/q5_gateway_server.log`, repeats once per connection —
`claude mcp add`'s health check, `claude mcp list`, `claude mcp get`, and
each of the two `claude -p` runs). The scripted python-sdk client does not
trigger it; only the real Claude Code client does. It is not fatal — the
client retries and every subsequent step succeeds — but SPEC-105 should
capture gateway-side request logs during its own Claude Code connectivity
test to identify exactly which initial request Claude Code sends that
FastMCP 3.4.7 rejects (most likely a `POST` before the client has settled on
the `Accept: application/json, text/event-stream` header FastMCP's
streamable-HTTP transport requires).

**Protocol version:** the scripted client's `initialize` response reports
`protocolVersion=2025-11-25` for this FastMCP 3.4.7 gateway
(`transcripts/q1_q2_full_tool_list.log`), **not** `2026-07-28`. This matches
research/mcp-landscape-2026.md §5's note that native 2026-07-28 (stateless)
support lands in **FastMCP 4.0 (currently beta, 4.0.0b3)**, while 3.x — the
version this spike installed and MASTERPLAN §8/IMPLEMENTATION.md §0
currently recommend for the stack — still speaks the older, stateful
revision. See "Assumptions that did NOT hold" below; this is the single
biggest input this spike has for SPEC-105/108.

Manual steps for a human re-running Q5 outside a sandbox with the `claude`
CLI (i.e., a normal workstation):
1. `cd v3/spikes/gateway && uv sync`
2. Start both servers: `uv run python servers/remote_upstream.py &` then
   `uv run python gateway.py &`
3. `claude mcp add --transport http gw-spike-full http://127.0.0.1:8900/mcp/full/ --header "Authorization: Bearer full-profile-secret-token" --scope local`
4. `claude mcp list` / `claude mcp get gw-spike-full` to confirm the
   connection and health check.
5. In a real interactive session (or `claude -p ... --allowedTools
   mcp__gw-spike-full__<tool>`), ask Claude to call `local_memory_search`,
   `remote_say`, or `remote_weather` and confirm the response matches the
   fixture strings in `servers/local_memory.py` / `servers/remote_upstream.py`.
6. Clean up: `claude mcp remove gw-spike-full -s local`, then stop both
   background servers.

---

## Assumptions that did NOT hold

1. **"Target protocol MCP 2026-07-28 (stateless) from day one" (MASTERPLAN
   §5.2) is not achievable on FastMCP 3.x.** FastMCP 3.4.7 negotiates
   `2025-11-25` and is still session/stream-based (a `GET` stream stays open
   per connection — see the `200 OK` GET lines in
   `transcripts/q5_gateway_server.log`). 2026-07-28 stateless support exists
   only in FastMCP 4.0, which is beta (4.0.0b3) as of this spike. SPEC-105
   and SPEC-006 (stack ADR) need an explicit decision: ship on 3.x now and
   accept 2025-11-25 for Phase 1, or take on 4.0-beta risk to get
   statelessness immediately. This spike does not recommend one over the
   other — it only establishes that "both, from day one" is not on the
   table with 3.x.
2. **`FastMCP.as_proxy()` is deprecated in 3.4.7** in favor of
   `fastmcp.server.create_proxy()`. MASTERPLAN §5.2 and the research dossier
   both describe "ProxyProvider (remote servers)" without flagging this;
   SPEC-105 should use `create_proxy()` directly.
3. **Per-path tool-subset profiles are not a single-instance FastMCP
   feature.** The `Visibility` transform this FastMCP version ships is
   session-scoped, not path-scoped. The addressable-profile design in
   MASTERPLAN §5.2 requires the multi-instance-plus-Starlette-`Mount`
   pattern demonstrated in `gateway.py`, with explicit lifespan combination
   (`combine_lifespans`) — a detail neither document anticipated and one
   that silently hangs the server if missed.
4. **`tool_names` in `mount()` does not take the final tool name** — it
   takes the pre-namespace name, and namespace prefixing is applied on top
   of it. A rename UI that lets users type the *displayed* (already
   namespaced) name and hands that string straight to `tool_names` will
   double the prefix. (Everything else about Q4 held: the rename fully
   replaces the original name, exactly as MASTERPLAN §5.2's "renamed, not
   aliased" requirement wants.)

Everything else assumed in the SPEC's five questions held as stated:
in-process + remote mounts behind one endpoint (Q1), addressable per-path
profiles once built correctly (Q2), static bearer auth plus present-but-beta
CIMD groundwork (Q3), full (non-aliased) tool renames (Q4), and a real,
working Claude Code end-to-end connection (Q5).

## What this changes for SPEC-105 / SPEC-108

- **SPEC-105 (MCP endpoint):** build profiles as one `FastMCP()` instance per
  profile + Starlette `Mount`, not via `Visibility`; always combine lifespans
  with `fastmcp.utilities.lifespan.combine_lifespans`; call
  `fastmcp.server.create_proxy()` instead of the deprecated `as_proxy()`;
  decide and document the protocol-version stance (3.x/2025-11-25 now vs.
  4.0-beta/2026-07-28) before writing the endpoint, since it is a stack-ADR
  -level decision, not an implementation detail; capture gateway-side
  request logs during Claude Code connectivity testing to chase down the
  observed pre-handshake `400`.
- **SPEC-108 (MVP auth):** `StaticTokenVerifier` is sufficient for the MVP
  per-client-token requirement as-is; CIMD primitives exist in this FastMCP
  version but are explicitly beta — treat them as a Phase 2 OAuth-AS
  building block to evaluate, not something to depend on for the Phase 1
  MVP auth.
- **Rename UI (both SPECs, dashboard-facing):** the tool-rename contract
  described in MASTERPLAN §5.2 needs a written composition rule (rename
  happens pre-namespace) surfaced to whoever builds the dashboard's rename
  form, or the first user rename attempt on a mounted (non-default-namespace)
  tool will silently double-prefix.

