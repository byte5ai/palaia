---
id: SPEC-306
title: MCPB bundle + one-click client bundles
phase: 3
depends_on: [SPEC-203, SPEC-205]
model: sonnet-5
effort: high
status: ready
---

# SPEC-306: One-click client bundles

## Goal
The §6 matrix's Claude Desktop row: a signed MCPB bundle containing a thin
stdio→hub proxy, downloaded from the connect page — double-click installs,
Claude renders the config UI from the manifest. Plus the same "hand the
user one artifact" treatment for the other config-file clients.

## Deliverables
1. `palaia-proxy`: a minimal stdio MCP server that forwards to the hub's
   streamable-HTTP endpoint (URL + token/OAuth from its config), written as
   a **self-contained Node script** (Claude Desktop ships a Node runtime for
   MCPB; facts and constraints in `v3/research/mcp-landscape-2026.md` §MCPB
   — read it first). Reconnect/backoff, clear stderr diagnostics, version
   pinned to the hub release.
2. MCPB packaging: `manifest.json` per the MCPB spec (user_config fields
   for hub URL + credential, rendered by Claude Desktop as a form), icon,
   the proxy, packed via the official `mcpb` tooling in CI
   (`v3/tools/build-mcpb/`); **signed** (the spec's signing story; document
   what signature Claude Desktop enforces today vs. what we attach, from
   the dossier — no hand-waving).
3. Connect page: the Claude Desktop entry becomes "Download bundle"
   (generated for the chosen profile, hub URL pre-filled; token minted on
   click via SPEC-108, or OAuth if enabled). Codex/Gemini/LM Studio entries
   gain "download config file" one-clicks (their real file formats — the
   SPEC-209-corrected snippets are the source of truth).
4. Hub serves its own bundle: `/api/connect/mcpb` streams the packaged
   bundle with the profile baked in; dashboard build embeds nothing —
   the artifact is assembled server-side from the packaged template.
5. e2e: the proxy speaks real stdio MCP — a `fastmcp.Client` (stdio
   transport) through the proxy against a live hub round-trips
   initialize/tools/call (this is the same proof shape SPEC-002 used).

## Acceptance criteria
- [ ] stdio e2e through the real proxy against a real hub: tools listed and
      a memory tool called successfully
- [ ] packed bundle validates against the MCPB manifest schema; CI job
      builds it reproducibly
- [ ] download endpoint bakes the chosen profile URL in; token variant
      mints a scoped token, OAuth variant contains no secret at all
- [ ] proxy survives hub restart (reconnect test) and reports a clear error
      on wrong credentials (no stack trace vomit)
- [ ] connect-page copy stays jargon-free (lint)

## Non-goals
Marketplace distribution of third-party MCPBs (listed via SPEC-303/304,
delivery is the vendor's); Windows/macOS installer signing beyond what MCPB
itself defines.
