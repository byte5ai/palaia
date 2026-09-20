# palaia v3 — changelog

This is the v3 track's changelog (the `v2-maintenance` line keeps its own
history at the repo root). Versions follow `v3/VERSION`.

Curated from the merged-PR record — every PR merged into the v3 line before a
version's tag — grouped by what a user actually gets, not by internal SPEC
number, and hand-written in plain language. Internal-only PRs (scaffolding,
ADRs, phase-gate records, SPEC index docs, CI and release plumbing) are left
out on purpose; they moved the project forward but nothing in them is a
capability a user would notice.

## 3.0.0-rc1 — 2026-09-01 (release candidate)

The first v3 release. Everything below is new relative to v2, since this is
v3's first release candidate rather than a diff against an earlier v3 version.

### Memory

- A local-first memory vault: plain Markdown notes in a folder you own, with
  file locking, atomic writes, a live file watcher, and automatic git commits
  — every change is a real commit you can read with `git log`.
- Full-text and hybrid (text + vector) search over your notes, with an
  optional local embeddings model; search degrades cleanly to text-only if
  you skip the embeddings extra.
- A knowledge-graph layer (wikilinks, backlinks, tags) with a conformance
  test suite pinning the vault file format.
- `recall` and `write` tools any connected AI tool can call, plus graph
  traversal and assembled context for a query.
- An inbox for quick capture, and a curator that turns loose inbox notes into
  organized memory (two-tier: auto-file the obvious, ask about the rest).
- Skills that teach a connected AI tool to save and look things up on its own
  — you stop having to ask for it every time.
- Importers for existing palaia v2 vaults and basic-memory notes, so
  switching over doesn't mean starting from zero.

### Connecting your AI tools

- One MCP endpoint your AI tools connect to — Claude Code, Claude Desktop,
  Codex, Gemini/Antigravity CLI, LM Studio, claude.ai, ChatGPT, Grok, and any
  MCP-compatible tool, each with its own connect instructions.
- Sign-in with GitHub, Google, or any OIDC provider, plus a full OAuth 2.1
  authorization server (dynamic client registration, PKCE, token rotation) —
  and per-client tokens for tools that don't do OAuth.
- Three operating modes (Locked, Cloud, Open) with a setup wizard, so how far
  your memory reaches is a deliberate choice, not a default you didn't make.
- Per-client tool profiles: give your phone's AI a narrower set of tools than
  your desktop's, from one hub, no client-side config.
- A one-click Claude Desktop bundle (MCPB) — download, click, connected, no
  typing an address or pasting a token.
- A validated client integration matrix, with real bugs found and fixed along
  the way (an OAuth loopback-redirect mismatch, a scope ceiling that silently
  capped what a token could be granted).
- A scope picker when issuing a client token, so a token can be limited to
  exactly the vaults and actions that client needs, and pre-declared OAuth
  vault scopes in the hub's config so a signing-in client is offered only
  those.
- Clients that connect through sign-in now show up as connected on the
  connect page the same way token clients do.

### Marketplace & add-ons

- A one-click marketplace inside the dashboard — install a tool once, and
  every connected AI tool has it, with no per-client reconfiguration. For
  3.0.0 it browses the official MCP registry, anything you add by hand, and
  the add-ons bundled with this release; palaia publishes no curated index of
  its own yet, and the marketplace page says so rather than implying a list
  that isn't there. An operator who publishes their own signed index can
  point a hub at it (`v3/tools/README.md`).
- Support for external MCP servers and an encrypted secret store for their
  credentials.
- An SDK for third-party add-on authors, with local testing and a submission
  flow.
- An automations editor for hooking events (a new note, a recall, a message)
  to actions.

### Team: session directory & messenger

- A session directory so one AI session can discover another one already
  working on something related — by what it's doing, never a hardcoded name.
- Structured messaging between sessions, including a `handoff` message type
  that carries a reference into memory instead of duplicating the text.
- Skills that make an AI tool check its inbox and hand off work on its own,
  plus push adapters and a team observability screen showing who's doing
  what.
- Dashboard sign-in, so the admin surface itself is no longer wide open by
  default.

### Dashboard

- A setup wizard (sign-in, exposure mode, first vault), a memory explorer, a
  connect page per client, a profile editor, and three in-chat MCP Apps (hub
  status, recall explorer, review queue) so some of this never needs the
  dashboard tab open at all.

### Install & distribution

- A single Docker image (compose file, one-line `docker run`, and a
  convenience install script), advertised on the local network as
  `palaia.local`.
- Ready-to-submit packages for Umbrel, CasaOS, Runtipi, TrueNAS SCALE, and a
  Home Assistant add-on evaluation.
- A Synology walkthrough that never needs a terminal, a cloud-init file for a
  VPS install with Tailscale in front, and a Raspberry Pi appliance image
  (`.img.xz` plus checksum, built reproducibly) attached to every release.
- One-click backup from the dashboard — an archive of your vaults and
  settings — with a documented restore path.
- Release channels (`stable`/`beta`/`edge`) and an in-dashboard "update
  available" check.
- A hardening pass (non-root container, dropped capabilities, read-only
  filesystem) and an external security review brief.
- A documentation site with an onboarding page, a "your first shared memory"
  walkthrough, and a per-client connect guide, served at
  `palaia.byte5.ai/docs`.
- A migration guide and sunset timeline for palaia v2.

### Known gaps in this release candidate

See `v3/docs/client-matrix-results.md` for exactly what has and hasn't been
exercised with a real vendor account/binary — most notably: no phone/claude.ai
account, no `codex` binary, and no public tunnel in the environment these
gates were run from. None of these are protocol gaps; they're sandbox
limits, and `v3/RELEASING.md` names the owner actions that close them before
a final tag.
