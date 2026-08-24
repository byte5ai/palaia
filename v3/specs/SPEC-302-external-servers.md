---
id: SPEC-302
title: External MCP server aggregation + encrypted credential store
phase: 3
depends_on: [SPEC-301]
model: opus-5
effort: medium
status: ready
---

# SPEC-302: External MCP servers behind the gateway

## Goal
MASTERPLAN §5.2 "one endpoint, many tools": the user connects an external
MCP server (remote HTTP, or a local command/container) once, in palaia, and
it appears — namespaced, renamable, health-checked — on whichever profiles
mount it. Credentials live in palaia's encrypted store, never in a client
config file again.

## Deliverables
1. `palaia_hub.upstream` package: an upstream-server registry
   (config-backed via SPEC-301's `gateway:` section — `upstreams:` list with
   kind `http` | `stdio`, endpoint/command, namespace, display name, enabled
   flag) and a per-upstream FastMCP client/mount. Consult
   `v3/spikes/gateway/FINDINGS.md` for the proven mounting mechanics on
   fastmcp 3.4.7 (`as_proxy` is deprecated — use the current
   client-backed-server mount; namespacing/`tool_names` apply pre-namespace).
2. **Encrypted secret store** (fixed design, security-critical): secrets
   (upstream API keys, OAuth client secrets, bearer tokens) live in
   `<home>/secrets.sqlite3`, values encrypted with Fernet
   (`cryptography`, already a dependency) under a key in
   `<home>/secrets.key` created `0600` in the `0700` home via
   `O_CREAT|O_EXCL` (SPEC-203's `keys.py` shows the exact pattern —
   reuse its `enforce_private_mode`). API: `put/get/delete/list-names`;
   **values are never returned by any REST endpoint or logged** — write-only
   from the dashboard, names-only listing. Upstream configs reference
   secrets by name.
3. Upstream auth wiring: static bearer/header from the secret store for
   `http` upstreams; env-var injection for `stdio` upstreams. (Full OAuth
   *client* flows against third-party ASes are a non-goal — manual token
   paste into the secret store is the v1 path, stated honestly in the UI.)
4. Health: per-upstream reachability probe (initialize + tools/list) with
   status surfaced via REST (`/api/gateway/upstreams`) and a
   `gateway.upstream.up/down` event; a down upstream degrades to absent
   tools + a clear one-line status, never a hung profile (bounded connect
   timeouts; the mount must not block hub startup).
5. Namespacing & renames: upstream tools appear as `<namespace>_<tool>`,
   renamable per SPEC-105's mechanism; conflicts refused loudly at config
   time, not silently last-write-wins.
6. Security fences: an upstream is NEVER mounted on the curator profile
   (SPEC-206's middleware map is fail-closed — assert a test); upstream
   tool descriptions pass through but the profile's IDENTITY line marks
   provenance ("via <display name>, connected by you").

## Acceptance criteria
- [ ] e2e: a real second FastMCP server (test fixture) connected as an
      upstream is callable through a profile by a real `fastmcp.Client`,
      namespaced, and its rename works
- [ ] secret store: key/db files 0600; a stored value never appears in any
      REST response, log line (redaction test), or error message; hub
      restarts read it back
- [ ] a down upstream: profile still initializes, its other tools work,
      status endpoint says which upstream is down and why
- [ ] stdio upstream: command spawned, env-var secret injected, tools
      callable e2e, process reaped on hub shutdown
- [ ] curator profile provably cannot see or call upstream tools

## Non-goals
OAuth client flows to third-party authorization servers; container lifecycle
management (SPEC-304 owns the add-on/container story); registry browsing
(SPEC-303).
