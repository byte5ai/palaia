---
id: SPEC-605
title: Setup page — join the tailnet in the browser, no key, no chat
phase: 6
depends_on: [SPEC-601]
model: opus-5
effort: high
status: in-progress
---

# SPEC-605: Setup page for the private network

## Goal
Owner decision 2026-10-08, from the live onboarding test: getting the
Tailscale auth key onto the server must be friendly for a non-technical
person and must never pass through the AI chat. Consoles and terminals are
off-putting. Instead, like Home Assistant's first-run page: palaia briefly
shows a setup page in the browser, protected by a one-time code; the person
clicks "Connect with Tailscale", logs in to their Tailscale account, and the
server joins their private network. No key to create, copy or paste.

## Hard constraints
- **Host-side, not in the hub.** Tailscale runs on the host
  (`get-palaia.sh`, `cloud-init.yaml`); the hub container stays
  `--cap-drop ALL --read-only` with no access to `tailscaled`. The setup
  page is a small helper the installer / cloud-init starts on the host and
  stops again. No image change, so the path is testable from `main`
  (get.palaia.ai serves `main`) without a release.
- **Short, guarded exposure.** The public port is open only while the
  helper runs, with a hard timeout (30 minutes). Every request needs the
  one-time code; a wrong code gets nothing (no login link, no hint). After
  the server has joined the tailnet, or on timeout, the helper exits and the
  public port is closed; the installer then continues exactly as today
  (hub bound to the tailnet address, ufw tailnet-only).
- **The key path stays.** `PALAIA_TSKEY` (installer) and the
  `TAILSCALE_AUTH_KEY` line (cloud-init) keep working for technical users.
  The setup page is the default only when no key is given.
- Keep the machine name `palaia-hub` so "find palaia-hub in your Tailscale
  machine list" (install skill, Step 5) still holds.

## Deliverables
1. `v3/deploy/setup-page.py` (or inlined into both scripts from one source
   of truth, same drift-test pattern as the docker-run flags): runs
   `tailscale up --hostname=palaia-hub` without an auth key in the
   background, captures the login URL it prints, serves one plain page on
   `0.0.0.0:8420`: code field → on the right code, a "Connect with
   Tailscale" button to that login URL, then "Waiting for you to log in…"
   until `tailscale ip -4` answers, then "Done — open http://<tailnet-ip>:8420/
   from a device on your Tailscale network". Python 3 standard library only.
2. One-time code, per path:
   - installer run by an AI with a shell: the AI passes
     `PALAIA_SETUP_CODE`; otherwise the installer generates one and prints
     it prominently;
   - console paste: printed by the installer;
   - cloud-init: the file carries a `PALAIA_SETUP_CODE="..."` line the AI
     (or the onboarding page) fills with a fresh random code — this replaces
     the `tskey-REPLACE_ME` edit as the default.
   Code format readable aloud and typeable on a phone (e.g. 3×4 characters
   without look-alikes).
3. `get-palaia.sh`: no key and no TTY → setup page instead of `die`.
   `cloud-init.yaml`: no key filled in → setup page instead of stopping.
   Both stay safe to re-run.
4. Install skill (`palaia-install`): Steps 2a / 3 / 4 / 5 rewritten around
   the setup page; Step 4 (create a key) becomes the power path only.
   Drift tests for the old key edit are replaced, not allow-listed.
5. Onboarding page + `v3/deploy/README.md`: same flow, same wording.

## Open points
- Runtime: settled — cloud-init itself is written in Python, so every image
  that runs it has `python3`; the installer installs it with apt if missing.
- Plain HTTP: the code and the login link travel unencrypted during the
  setup window. Accepted for the 30-minute, code-gated window (a browser
  warning for a self-signed certificate would scare the very people this is
  for); revisit if the page ever stays up longer.
- Remaining terminal touch: an *existing* server that the AI cannot reach
  still needs one console paste (a fixed line, no secret, no editing). The
  skill should offer, for an empty existing server, recreating it with the
  setup file instead (no console at all).

## Acceptance criteria
- [ ] Fresh Ubuntu VPS, cloud-init without a key: browser page at
      `http://<public-ip>:8420/`, code, Tailscale login, hub reachable on
      the tailnet; `:8420` no longer answers on the public address.
- [ ] Same via `curl -fsSL https://get.palaia.ai | sh` without a key.
- [ ] Wrong code: no login link is ever served; timeout closes the port.
- [ ] Re-running the installer on a joined server skips the setup page.
- [ ] Live onboarding test (naive user + install skill) reaches a green hub
      on the owner's test VPS without the key passing through the chat.
