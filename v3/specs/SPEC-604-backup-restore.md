---
id: SPEC-604
title: Backup & restore — one button out, one documented path back
phase: 6
depends_on: [SPEC-401, SPEC-501]
model: sonnet-5
effort: high
status: ready
---

# SPEC-604: Backup & restore

## Goal
"Operation maximally easy" (owner, 2026-08-31) currently fails at the
first question every self-hoster asks: how do I back this up? Nothing in
the product or docs answers it. Target: a signed-in owner downloads one
file from the dashboard; restoring it onto a fresh install brings
everything back.

## Fixed design points (do not weaken)
- The backup archive contains the whole hub home (vaults, config,
  SQLite state, the secret-store file AND its key) — a backup that can't
  restore secrets is not a backup. Because of that, the download exists
  ONLY behind the admin session gate (SPEC-401), is never written to a
  world-readable location server-side, and the docs say plainly: this
  file can impersonate your hub — store it like a password.
- Restore is explicitly offline-first: stop hub → unpack into the volume
  → start. A dashboard *upload*-restore is out of scope (too much risk
  surface for this pass); the wizard's empty-state may link the restore
  doc.
- Rebuildable state (search indexes) may be excluded to keep archives
  small — only if restore provably rebuilds it on first start.

## Deliverables
1. `GET /api/backup` (admin-gated): streams a tar.gz of the hub home,
   consistent (quiesce writes or snapshot per-store the way each store
   already supports; document the consistency claim honestly).
2. Dashboard: a "Back up" action on the hub-status screen with a
   plain-language explanation and the security warning.
3. `v3/docs/backup-restore.md` + docs-site page: the button, the restore
   path (compose and one-liner variants), and what is/isn't inside the
   archive. Jargon-free on the site.
4. Threat model + external-review brief updated (new endpoint — the
   coverage test will force this anyway).

## Acceptance criteria
- [ ] e2e: fresh hub → write memory → download backup → NEW fresh home →
      restore per the documented steps → the memory is back and a client
      can read it
- [ ] the endpoint 401s without an admin session in every mode that
      gates (same matrix as other admin routes)
- [ ] archive excludes nothing that restore needs (test proves secrets
      round-trip); if indexes are excluded, test proves rebuild
- [ ] docs pages build, jargon lint green; full suite green

## Non-goals
Scheduled/automatic backups, remote backup targets, dashboard
upload-restore — all future work once this floor exists.
