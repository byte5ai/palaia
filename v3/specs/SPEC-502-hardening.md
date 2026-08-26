---
id: SPEC-502
title: Hardening pass + external-review package
phase: 5
depends_on: [SPEC-401, SPEC-302, SPEC-203]
model: opus-5
effort: high
status: ready
---

# SPEC-502: Hardening

## Goal
MASTERPLAN §10 before 3.0: an internal security pass over the whole attack
surface, every finding fixed or filed, and a complete package for the
external review (which the owner procures — this SPEC makes that review
cheap and effective, it does not replace it).

## Deliverables
1. `v3/docs/security/threat-model.md`: assets (vault contents, credentials,
   tokens/keys), trust boundaries (modes table, MCP vs admin vs OAuth
   surfaces, upstreams, curator, marketplace installs, messenger), attacker
   profiles, and per-boundary mitigations AS BUILT — every claim linked to
   the enforcing code/test, no aspirational statements.
2. Systematic pass, each area yielding "verified", a fix in this PR (small),
   or a filed issue (larger):
   - HTTP hardening: security headers on dashboard + OAuth pages (CSP for
     the SPA and the login page, X-Content-Type-Options, Referrer-Policy,
     HSTS note for the tunnel docs), cookie flags re-audited;
   - auth surfaces: rate-limit coverage (SPEC-205's middleware vs the
     admin gate's 401s — close the counted-attempts gap noted in SPEC-401),
     session fixation/logout completeness, CSRF coverage of every
     state-changing surface incl. `/oauth/logout`;
   - stores on disk: file-mode audit across every store (oauth, secrets,
     stash, directory, messenger, market cache), WAL siblings included;
   - injection surfaces: vault-format parser fuzz (hypothesis-based, seeded
     from the conformance corpus, bounded runtime), markdown rendering in
     the dashboard (XSS), tool-argument reflection in MCP error messages;
   - dependency audit: `uv` lockfile + npm audit, pinning review, a
     documented policy for security updates;
   - container posture: non-root user, read-only rootfs where possible,
     dropped capabilities in compose + store packages (coordinate with
     SPEC-501's files — shared files, keep additive).
3. Log/telemetry audit: one pass proving no credential class reaches logs
   (extend the SPEC-203 redaction tests to the new packages: secrets,
   messenger bodies, directory session secrets).
4. `v3/docs/security/external-review-brief.md`: scope, architecture
   summary with diagrams-as-text, entry points, the threat model link,
   how to run everything locally, known accepted risks (each with its
   rationale) — the document a hired reviewer starts from.
5. `SECURITY.md` (v3-scoped, linked from README): supported versions,
   how to report, response expectations.

## Acceptance criteria
- [ ] threat model covers every mounted surface (checklist against the
      live route table + tool families, asserted by a test that fails when
      a new router ships unmentioned — a doc that can rot is a doc that
      will)
- [ ] security headers present on dashboard + OAuth responses (tests)
- [ ] admin-gate 401/403s feed the auth rate limiter in cloud/open (closes
      the SPEC-401 note; test)
- [ ] parser fuzz runs green in CI within its time budget, corpus-seeded
- [ ] every store file 0600/0700-audited by one parametrized test
- [ ] no-credential-in-logs test extended to secrets/messenger/directory
- [ ] found issues: fixed here if small, else filed with "v3:" prefix —
      none silently dropped (list them in the PR body)

## Non-goals
The external review itself (owner procures; brief is the deliverable);
SBOM/compliance paperwork; penetration testing infrastructure.
