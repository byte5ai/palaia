# ADR-007: A managed browser — the human logs in once, agents work in that session

- **Status:** Proposed
- **Date:** 2026-09-27
- **Deciders:** owner (open); drafted by Claude for issue #493

## Context

Issue #493 (owner, verbatim): „Headless browser -> Login auf beliebige Website
durch User über VNC -> Automation durch einen Agent, der von palaia gespawnt
und gemanaged wird (Claude, Codex...)".

Much useful automation sits behind a login an agent cannot complete itself:
2FA, captchas, SSO, "confirm in your banking app". The pattern that works is
that the **human logs in once and the agent works inside that session**.

What the repository offers today, checked against the code on 2026-09-27:

1. **Container add-ons are short-lived stdio processes.**
   `market/docker_runtime.py` starts every container add-on as
   `docker run --rm -i <image>`, the child process of a `stdio` upstream. A
   browser the human logs into must keep running between agent calls and
   serve a screen stream, which is not what that model provides.
2. **The default deployment cannot start containers at all.** Neither
   `deploy/install.sh` nor `deploy/docker-compose.yml` gives the hub a docker
   socket, so hub-started container add-ons only work on a host where the
   hub runs outside docker or the operator mounts the socket.
3. **Upstream MCP servers are first-class.** An upstream (`gateway.upstreams`,
   `docs/external-servers.md`) can be `stdio` or `http`, is gated per MCP
   profile, and keeps its credentials in the encrypted secret store.
4. **An off-the-shelf browser MCP server exists.** Playwright MCP
   (Microsoft, Apache-2.0) exposes `browser_navigate`, `browser_snapshot`,
   `browser_click`, `browser_type`, `browser_fill_form`,
   `browser_take_screenshot` and more. It can attach to a running browser
   with `--cdp-endpoint`, keep a persistent profile with `--user-data-dir`,
   and serve MCP over HTTP with `--port`.
5. **MASTERPLAN §2 non-goals:** palaia is "not an LLM host" and "not an agent
   framework (it doesn't orchestrate reasoning)".

## Decision (proposed)

Build it in two parts. Part A ships; part B stays out.

### A. A managed browser, as an optional companion service

- **One extra container next to the hub** (`palaia-browser`), switched on by
  the operator: Chromium running headed on a virtual display, a persistent
  profile on its own volume, noVNC (websockify) for the screen, and
  Playwright MCP attached to that same browser over CDP. It is a service in
  `docker-compose.yml` and an opt-in line in the one-liner, not a container
  the hub spawns. That avoids the docker socket (context 2) and fits a
  long-running process (context 1).
- **Login through the dashboard.** A new "Browser" screen shows the noVNC
  view. The hub proxies the websocket behind the admin session; the VNC port
  is never published to the network. The owner logs in to any site, then
  closes the view. Cookies and storage persist in the profile volume.
- **Agents get it as an upstream.** The hub registers the companion's
  Playwright MCP endpoint as an `http` upstream. Its tools are off in every
  MCP profile until the owner grants them to a profile (default-deny, like
  the Telegram send grants).
- **Sessions per site.** One browser, one profile. A per-profile allowlist
  of sites limits where an agent may navigate; anything else is refused
  before the call reaches the browser.
- **"Please log in again."** When a page the agent opens lands on a login
  form for an allowlisted site, the hub raises an event and a dashboard
  notification, so the human is pulled back in rather than the agent
  failing silently.

### B. palaia does not spawn or supervise agents

The browser is a tool that **external** agents use: Claude Code, Codex or
any MCP client connected to the hub. They are already visible in the
session directory (SPEC-402) and reachable through the messenger (SPEC-403),
and automations (SPEC-307) can message a registered session to start work.
Spawning and supervising Claude or Codex processes would cross the non-goals
in MASTERPLAN §2. If that is wanted, it belongs to the same decision as #495
(coding harnesses as add-ons) and needs its own ADR that amends §2.

## Security

- **A logged-in profile is a credential**, often stronger than an API token.
  It belongs in the threat model as its own asset, next to the secret
  store. The profile volume is part of the full backup archive, and so
  inherits its "store this like a password" warning.
- **VNC only behind dashboard sign-in.** No raw VNC port. The websocket is
  proxied by the hub, and only for a signed-in owner. On a hub without
  sign-in, the Browser screen refuses, like the backup routes.
- **Page content is untrusted input aimed at a model** (the ADR-006
  argument). Tool results say where the text came from, and nothing on a
  page can change the allowlist or the grants.
- **Egress:** the companion has network access by design. It should not
  reach the hub's internal ports other than its own MCP endpoint.

## Alternatives considered

- **A container add-on spawned by the hub** — needs the docker socket in the
  hub container (a large privilege) and a long-running add-on kind that does
  not exist yet. Worth revisiting once #512 defines how palaia's own add-ons
  are built and run.
- **Build our own browser MCP server** — more code to maintain than
  attaching Playwright MCP to a browser we control. Only worth it if its tools
  turn out not to fit.
- **browser-use** as the automation layer — it bundles its own agent loop,
  which is the part MASTERPLAN §2 keeps out of palaia.
- **Remote browsers (cloud providers)** — contradict local-first, and the
  profile would live outside the owner's hardware.

## Consequences

- **Effort (estimate):**
  - Companion image (Chromium, virtual display, noVNC, Playwright MCP):
    2–3 days.
  - Hub (websocket proxy behind the admin session, upstream registration,
    site allowlist, login-needed event): 3–4 days.
  - Dashboard screen: 2 days.
  - Threat model, docs, tests: 2 days.
  - Total: about two weeks.
- **Resources:** Chromium plus a virtual display needs a few hundred MB of
  RAM. That is fine on a server and on a 4 GB Raspberry Pi, and tight on
  2 GB. Measure it on the appliance before offering it there (#280).
- **Publishing:** the companion image has to be built and published like
  the hub image, which is the release question #512 raises for add-ons.
- **Decisions needed from the owner:**
  1. Part A as described: yes or no?
  2. Keep part B out (external agents drive the browser), or open the
     non-goals question together with #495?
  3. Is one browser profile per hub enough, or is one per MCP profile needed
     from the start?
