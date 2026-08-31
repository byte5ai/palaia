---
id: SPEC-601
title: Cloud-init template — VPS install with Tailscale, no terminal
phase: 6
depends_on: [SPEC-501, SPEC-504]
model: sonnet-5
effort: medium
status: ready
---

# SPEC-601: Cloud-init VPS install

## Goal
Owner decision 2026-08-31: every install path reaches "onboarding and
operation maximally easy". For rented cloud servers the vehicle is
cloud-init — paste one file into the provider's user-data field at server
creation (Hetzner Cloud "Cloud config", DigitalOcean, AWS, …), enter one
Tailscale auth key, and the server sets itself up with the hub never
exposed to the public internet.

## Deliverables
1. `v3/deploy/cloud-init.yaml`: installs Docker and Tailscale, joins the
   tailnet with the user's auth key (one clearly marked `REPLACE_ME`
   placeholder, nothing else to edit), starts the hub with the same
   hardened flags as `install.sh` (same source of truth, never a fork of
   the flag list), and firewalls the hub port so it is reachable via the
   tailnet only. Idempotent on re-run; cloud-init's own logging tells the
   user where to look if something failed.
2. Onboarding page: the "rented server" entry gains this as its primary
   path ("paste this file when creating the server"), with the copy
   button pattern already used there; the one-liner stays as the
   alternative for servers that already exist.
3. `v3/deploy/README.md` section: what the file does, where the data
   lives, how to update/back up — same honesty rules as the rest.

## Acceptance criteria
- [ ] cloud-init file passes `cloud-init schema --config-file` validation
      in CI (add to the python or e2e job the cheapest clean way)
- [ ] drift test: the docker-run flags inside cloud-init.yaml are checked
      verbatim against `install.sh`'s flag list (same pattern as the
      onboarding snippets drift test)
- [ ] onboarding page builds, links resolve, jargon lint green
- [ ] the full-VM boot test is explicitly an owner action: a short
      checklist at the end of the deploy README section (create server,
      paste, wait, open) — never claimed as CI-proven

## Non-goals
Provider-specific marketplace listings; the real Hetzner boot test
(owner); non-Tailscale VPN variants (the file's comments may point at the
firewall line to adapt).
