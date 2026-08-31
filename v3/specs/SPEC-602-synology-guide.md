---
id: SPEC-602
title: Synology guide — Container Manager walkthrough, no terminal
phase: 6
depends_on: [SPEC-503, SPEC-504]
model: sonnet-5
effort: low
status: ready
---

# SPEC-602: Synology guide

## Goal
Synology NAS owners can run palaia today via Container Manager, but no
page walks them through it — and the walkthrough must never require the
NAS's terminal. Owner has a Synology device for verification.

## Deliverables
1. Docs-site page `connect`-style walkthrough (`/install-synology/` or
   under the install section — match the site's own structure): open
   Container Manager → create a "Project" → paste the compose file →
   choose the data folder → start → open the hub address. Written
   step-by-step against Container Manager's real UI labels; screenshots
   are the owner's follow-up (leave clearly marked figure slots, do not
   fake them).
2. Onboarding page: the Synology entry links this page.
3. The compose file it pastes is the real `v3/deploy/docker-compose.yml`
   (drift-tested reference or generated include — never a copy that can
   rot).

## Acceptance criteria
- [ ] site builds, links resolve, jargon lint green
- [ ] the pasted compose content is drift-tested against v3/deploy
- [ ] an explicit owner checklist at the bottom: verify each step once on
      the real device, replace figure slots with screenshots

## Non-goals
A native Synology Package Center package (separate decision once the
guide has proven itself); DSM versions older than Container Manager.
