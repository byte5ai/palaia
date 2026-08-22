---
id: SPEC-005
title: "UX north star: design system + key screens"
phase: 0
depends_on: []
model: opus-5
effort: high
status: ready
---

# SPEC-005: UX north star — design system + key screens

## Goal
Fix the product's look and interaction language before any UI code exists, so
SPEC-109/110 implement instead of invent. MASTERPLAN §4 (UX doctrine) and P7
(dashboard pillar) are the brief.

## Deliverables
1. `v3/docs/design/system.md` — design tokens (color light/dark, type scale,
   spacing, radii), component inventory (buttons, cards, nav, tables, empty
   states, health badges), tone of voice for UI copy.
2. Key screens as high-fidelity HTML mockups (static, no backend) under
   `v3/docs/design/mockups/`:
   - Home ("is everything healthy, what happened?") — the one-glance screen
   - Onboarding wizard (mode choice Locked/Cloud/Open, first vault, first client)
   - Connect-a-client page (per-client guided flows, copy buttons, QR)
   - Memory explorer (list + note view + graph drill-down)
   - Review queue (curator proposals — also the MCP App's visual reference)
3. `v3/docs/design/principles.md` — the §4 doctrine translated into concrete
   do/don't examples per screen.

## Acceptance criteria
- [ ] all five screens exist in light AND dark, responsive at 360px/768px/1280px
- [ ] every screen answers its primary question without scrolling at 1280px
- [ ] empty states designed (first-run!) — not just filled states
- [ ] no config-file editing anywhere in any flow
- [ ] owner sign-off (this defines "palaia looks like palaia")

## Non-goals
No React implementation, no real data, no MCP App runtime.

## Model note
**Opus 5 / effort high** — design taste and coherence; Fable 5 reviews at the
phase gate.
