---
id: SPEC-109
title: Dashboard shell & design system implementation
phase: 1
depends_on: [SPEC-005, SPEC-101]
model: sonnet-5
effort: high
status: draft
---

# SPEC-109: Dashboard shell & design-system implementation

## Goal
Turn the SPEC-005 north star into the running app shell: design tokens,
component library, navigation, live-state plumbing — so SPEC-110 (and every
later screen) composes instead of styles.

## Deliverables
1. `v3/web`: **the Lume design system is normative** — tokens lifted from
   `v3/docs/design/lume/colors_and_type.css` (do not fork values; palaia
   default accent is `atelier`, mode default follows system preference with
   manual override), Geist/Geist Mono/Source Serif 4 self-hosted; Tailwind
   config bound to the Lume tokens; component library (buttons, cards, nav,
   tables, badges, empty states, toasts, form fields) using the Lume material
   recipes (surface gradients, directional borders, glow selection/focus),
   with Storybook or an equivalent living style guide.
2. App shell: sidebar navigation per the north star, health indicator in the
   chrome, responsive per SPEC-005 breakpoints, theme switch (system default).
3. **Live-state layer**: SSE client against `/api/events` (hub side: minimal
   SSE endpoint emitting health + vault change events from SPEC-102's bus
   stub); UI state updates without reload (ravitemer-hub pattern).
4. API client layer: typed client generated from the hub's OpenAPI schema.
5. Static build served by the hub (`palaia-hub serve` = one process, one port).

## Acceptance criteria
- [ ] visual parity with SPEC-005 mockups for shell + components (owner eyeball
      + screenshot diffs checked into the PR)
- [ ] light/dark both flawless; no hardcoded colors outside tokens (lint rule)
- [ ] SSE: vault file touched on disk → explorer badge updates without reload
- [ ] `npm run build` output served by the hub; deep links work (SPA fallback)
- [ ] axe-core a11y scan: no critical violations on the shell

## Non-goals
Feature screens (SPEC-110), MCP Apps shell (Phase 2 — but keep components
importable in isolation for reuse there).
