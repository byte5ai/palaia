---
id: SPEC-404
title: Structured-messaging skills + push adapters
phase: 4
depends_on: [SPEC-403, SPEC-207]
model: sonnet-5
effort: high
status: ready
---

# SPEC-404: Messaging skills + push

## Goal
The habit half of §5.4 ("nothing prompts them") and the delivery half
beyond polling: skills that make agents register, check and reply as part
of their normal workflow — measured, not assumed, with SPEC-207's
effectiveness discipline — plus push where a platform allows it.

## Deliverables
1. `v3/clients/skills/palaia-messenger/SKILL.md`: register-on-start (scope
   from the task at hand), check-on-milestone, the reply discipline
   (`expects_reply` means answer or explicitly decline), the token rule
   (long content → memory, send the ref), deregister/idle on wrap-up.
   Wired into the existing plugin manifest so it installs with the
   SPEC-207 pack; connect-page skill panel lists it (same capability
   table).
2. SPEC-207's format lint extended over the new skill (same jargon rules);
   `## Per-model notes` variant markers where behavior differs.
3. **Effectiveness harness extension** (env-gated like SPEC-207's): two
   real `claude` CLI sessions against a real hub — session A gets a task
   and the skill; does it register, and does it send a `handoff` with a
   vault ref instead of pasting content? Session B: does it check its
   inbox unprompted at task start? Same honesty rules: every run printed,
   the rate is the finding, misses analyzed and prose iterated at least
   once.
4. Push adapters, hook-based (SPEC-201/307 machinery, no new delivery
   system): a `message.received` automation recipe that fires an outbound
   webhook ("notify my other tooling"), and — if the research dossier's
   `claude/channel` facts support it in this sandbox — a documented,
   env-gated proof that a Claude Code session can be poked to check its
   inbox; if the capability cannot be exercised honestly here, document
   the integration path and mark it "not verified" rather than shipping
   dead code.
5. `docs/messenger.md`: the agent-facing contract (envelope shape, the
   body cap and why, the check/reply discipline) — written for skill
   authors and SDK users, jargon-free where user-facing.

## Acceptance criteria
- [ ] skills pass the format lint; plugin manifest installs both packs
- [ ] effectiveness runs documented: register + handoff-with-ref and
      check-on-start rates reported honestly, at least one prose iteration
- [ ] the webhook recipe delivers on a real `message.received` (e2e over
      the SPEC-201 outbox)
- [ ] connect page lists the messenger skill per client capability table

## Non-goals
New delivery transports; vendor-cloud push (no honest way to test);
changing the envelope protocol (SPEC-403 owns it).
