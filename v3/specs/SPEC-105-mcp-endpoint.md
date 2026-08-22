---
id: SPEC-105
title: MCP endpoint & memory tool family
phase: 1
depends_on: [SPEC-002, SPEC-101]
model: sonnet-5
effort: high
status: draft
---

# SPEC-105: MCP endpoint & memory tool family

## Goal
palaia's primary interface: a streamable-HTTP MCP endpoint (FastMCP 3.x,
stateless) exposing the memory tool family — with the tool ergonomics and the
naming rules that are product identity (MASTERPLAN §5.1/§5.2).

## Deliverables
1. Gateway skeleton per SPEC-002 findings: FastMCP mounted into the hub app;
   profile paths `/mcp/<profile>` (profiles config-defined for now; dashboard
   editing later); default profile with the core toolset.
2. **Memory tool family per vault** (per format spec + SPEC-102/104 APIs):
   `search`, `read`, `write`, `edit`, `move`, `delete`, `list`,
   `recent_activity` — mounted once per configured vault.
3. **Naming rules** (MASTERPLAN §5.2): default names carry the vault identity
   (`work_memory_search`); every tool/connector name user-renamable via config
   (sanitized to the MCP tool-name charset); every tool description leads with
   the vault's user-editable purpose line.
4. **Tool ergonomics** (research/basic-memory.md §7): behavior annotations
   (`readOnlyHint`/`destructiveHint`) on every tool; alias absorption for
   common LLM parameter misses (`folder/dir/path`, `q/query/text`); dual
   text/json output; server `instructions` with an IDENTITY line per vault; an
   `ai_assistant_guide` MCP resource.
5. MCP protocol target: 2026-07-28 stateless with the compatibility posture
   from SPEC-002 findings.

## Acceptance criteria
- [ ] Claude Code connects via `claude mcp add --transport http` and round-trips
      write→search→read on a test vault (scripted e2e, harness from SPEC-113)
- [ ] two vaults configured → two clearly distinguishable tool families; a
      rename in config changes the exposed name after reload; invalid rename
      chars are sanitized with a warning
- [ ] every tool passes an annotations-lint (test walks tools/list and asserts
      annotations + leading purpose line)
- [ ] alias absorption proven per aliased param (tests call with wrong names)
- [ ] a profile exposing a subset actually hides the rest (tools/list per path)

## Non-goals
Auth (108), inbox tools (107), recall/traversal (106), external upstreams
(Phase 3), MCP Apps (Phase 2).
