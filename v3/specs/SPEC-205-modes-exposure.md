---
id: SPEC-205
title: Operating modes & exposure wizard
phase: 2
depends_on: [SPEC-203, SPEC-110]
model: sonnet-5
effort: high
status: ready
---

# SPEC-205: Operating modes & exposure wizard

## Goal
Locked → Cloud → Open becomes a guided, safe journey in the dashboard
(MASTERPLAN §5.5 table is binding; the vendor-cloud reality check is stated
plainly to the user).

## Deliverables
1. Mode-change REST API with precondition validation (cloud/open refuse
   without a working auth setup; actionable errors) + audit log entry + event.
2. **Exposure wizard** (dashboard): explains what each mode means in plain
   language; for Cloud: tunnel guidance with detection — Tailscale
   (serve/funnel) and cloudflared configs generated for the user's setup,
   copy-paste ready, plus "I have my own reverse proxy" path; public-URL
   self-test (hub fetches its own metadata endpoint via the public URL and
   reports reachability honestly — no fake green).
3. Connect-a-client page reacts to mode live (claude.ai/ChatGPT flows unlock
   in Cloud/Open with the public URL filled in).
4. Open-mode hardening checklist (rate limiting on auth endpoints, TLS check,
   dashboard-exposure warning) — checklist items verified where the hub can,
   stated as manual where it cannot.
5. Docs: `v3/docs/exposure.md`.

## Acceptance criteria
- [ ] mode transitions validated (cloud without auth → refused with fix)
- [ ] self-test correctly distinguishes reachable/unreachable public URL
- [ ] generated tunnel configs are syntactically valid (golden files)
- [ ] auth endpoints rate-limited in cloud/open (test)
- [ ] no jargon in wizard copy (lint)
