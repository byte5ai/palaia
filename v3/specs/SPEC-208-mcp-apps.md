---
id: SPEC-208
title: "MCP Apps: hub status, recall explorer, review queue"
phase: 2
depends_on: [SPEC-110, SPEC-206]
model: sonnet-5
effort: high
status: ready
---

# SPEC-208: MCP Apps

## Goal
palaia panels inside the chat clients (MASTERPLAN §5.7): the three Phase-2
apps, as progressive enhancement over the plain-text tool results.

## Deliverables
1. **App shell**: one shared HTML/JS base using the Lume tokens (same values
   as the dashboard — visual identity everywhere), self-contained per the
   MCP Apps extension (`io.modelcontextprotocol/ui`), served as `ui://`
   resources from the gateway; fonts bundled (iframe CSP blocks CDNs).
   Verify fastmcp 3.4.7's MCP Apps support first; if it needs a newer 3.x
   minor, bump within stable 3.x only (never 4.x beta) and document.
2. **Hub status app** (attached to a `hub_status` tool): health, vaults,
   index/embed backlog, connected clients — the first-tool-call orientation
   panel.
3. **Recall explorer app** (attached to `search`/`recall` results): browsable
   result list with drill-down; **selective context** — only what the user
   picks is pushed into the model's context (the §5.7 token-discipline lever).
4. **Review queue app** (attached to a `review_queue` tool): proposal cards
   with diff view, approve/reject flipping the format-§8 status via the
   REST API under the caller's auth — mirrors the dashboard/mockup design.
5. Hosts without the extension get well-formatted text results (tests).

## Acceptance criteria
- [ ] apps render in an MCP-Apps-capable harness (automated via the extension
      SDK's test host or a scripted iframe harness — document the approach)
- [ ] selective context proven: picking one of N results injects only that
      one (assert on the context-update payload)
- [ ] approve-from-app flips proposal status exactly like the dashboard path
- [ ] zero external network requests from any app (CSP test)
- [ ] plain-text fallback asserted for a non-supporting client
- [ ] golden tools snapshot regenerated (new tools)
