---
id: SPEC-110
title: "Dashboard v0: wizard, explorer, connect-a-client"
phase: 1
depends_on: [SPEC-109]
model: sonnet-5
effort: high
status: draft
---

# SPEC-110: Dashboard v0 — wizard, explorer, connect-a-client

## Goal
The three screens that carry the MVP promise: install → first vault → first
client → first shared memory, all in the browser (UX doctrine: shell is the
escape hatch, 5-minute install / 2-minute connect targets).

## Deliverables
1. **Onboarding wizard** (first run): admin credentials → operating mode
   (Locked/Cloud/Open, with the vendor-cloud reality check from MASTERPLAN
   §5.5 explained inline) → first vault (name + purpose line) → offer template
   vault → land on Home with "connect your first client" callout.
2. **Memory explorer**: vault switcher, folder tree, note view (rendered
   markdown + frontmatter panel + git history from SPEC-102), inbox section
   with uncurated badge (SPEC-107), search bar (hybrid, SPEC-104), relation
   graph drill-down for one note (local graph, not a global hairball).
3. **Connect-a-client page**: per-client guided flows per MASTERPLAN §6 matrix
   (Claude Code one-liner + paste-prompt, Claude Desktop MCPB placeholder-note
   until Phase 3, claude.ai/ChatGPT flows gated on mode with inline
   explanation, Codex config.toml snippet, generic MCP) — each with copy
   buttons, live "seen a connection from this client yet?" check, QR for URLs.
4. **Home v0**: health tiles (hub, vaults, index lag, inbox age), recent
   activity feed (SSE-live), connected-clients list with last-seen.

## Acceptance criteria
- [ ] fresh install → wizard → write a note via Claude Code → note visible in
      explorer: complete flow under 5 minutes, scripted as the SPEC-113
      headline scenario and demonstrated in a screen recording in the PR
- [ ] every §6-matrix client has a connect flow (even if "not yet available in
      this mode/phase" with a truthful explanation)
- [ ] connect page detects and shows a client's first successful tool call
- [ ] no dead-end screens: every empty state teaches the next action
- [ ] owner UX pass recorded in the PR

## Non-goals
Marketplace, automations, session views (later phases); admin settings beyond
mode + tokens (SPEC-108 UIs are minimal forms here).
