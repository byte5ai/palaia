# palaia v3 — changelog

This is the v3 track's changelog (the `v2-maintenance` line keeps its own
history at the repo root). Versions follow `v3/VERSION`.

Curated from the merged-PR record — every PR merged into the v3 line before a
version's tag — grouped by what a user actually gets, not by internal SPEC
number, and hand-written in plain language. Internal-only PRs (scaffolding,
ADRs, phase-gate records, SPEC index docs, CI and release plumbing) are left
out on purpose; they moved the project forward but nothing in them is a
capability a user would notice.

## 3.0.0-rc5 — 2026-10-23 (release candidate)

The fixes from the first supervised installation test of `rc4`: a browser-first
install that works with the published command, cloud access for ChatGPT and
Claude with the dashboard kept private, a first-run setup that resumes and ends
at a working AI connection, and a new, simpler look. Still a pre-release — the
`:beta` channel.

### Install

- **`curl -fsSL https://get.palaia.ai | sh` works on Ubuntu again.** The
  installer is plain `sh`; under Ubuntu's `dash` it used to stop at its first
  line.
- **Join your private network in the browser.** Without a key, the installer
  starts a one-time setup page you open in your browser (protected by a
  code) and log in to Tailscale there. The page closes itself and the port
  with it.
- **Cloud access during install.** The same page offers to let ChatGPT and
  Claude reach palaia over HTTPS through Tailscale Funnel — only palaia's AI
  connection, never the dashboard. Keep it private if you prefer.
- **Keys stay out of command lines.** A Tailscale key goes in as a root-only
  file (`PALAIA_TSKEY_FILE`) that Tailscale reads itself; the installer deletes
  it afterwards.
- **"Done" means ready.** The installer and the container report success only
  when the hub's own health check answers, not when the page loads.
- Works on a server that already runs Docker or is already on your tailnet,
  and keeps an existing firewall as it is.
- The server-creation file runs the same installer.

### Cloud access

- **A separate door for the internet.** Tunnels point at palaia's cloud entry,
  which answers only the AI connection and its sign-in; the dashboard and its
  API stay on your private network. The hub keeps that door shut until you
  turn cloud access on.
- **An honest self-test.** palaia checks its own public address the way ChatGPT
  and Claude do and reports each result; a wrong tunnel, an unrelated page or
  an open dashboard fails with the fix named.
- **Sign-in from an empty hub works.** Turning on sign-in before your first
  memory is refused with a reason instead of stopping the hub; signing in to
  the private dashboard in Cloud mode no longer loops.
- **Restart from the browser** where palaia runs in its container.

### First-run setup

- Opens by itself until it is finished, resumes where it stands after a reload
  or restart, and ticks only what palaia really has.
- One forward order: how you'll use palaia, your first memory, your account,
  cloud access, your first AI app — no trip back to an earlier step.
- Required and optional fields are marked, with what an empty value does; the
  example text no longer names a company.
- The Claude app, claude.ai and ChatGPT are offered as cloud connectors next to
  Claude Desktop and the command-line tools.

### Look and words

- **A new, calmer design** across the dashboard, the first-run setup, the
  installer's setup page, the sign-in pages, the docs site and the panels
  palaia shows inside Claude and ChatGPT: one set of colours and type for
  light and dark, larger click targets, a visible focus ring, and status
  always as a word, never colour alone.
- **Five places in the menu.** Overview, Memories, AI apps, Add-ons
  and Automations, with everything about the server under Settings. Old
  addresses and bookmarks still lead to the right page.
- **Plain words everywhere.** Memory instead of vault, AI app instead of
  client, access key instead of token, Private / Cloud / Public with what
  each one means. Long explanations moved behind "What's included?" and
  "Advanced"; every page has one obvious next step.
- **AI apps** shows each app's status ("Connected — last request 2 min
  ago" also after a restart), lets you revoke or replace an app's access
  key, and walks you through connecting one.
- **Access & sign-in** splits the old switch in two: "Require sign-in for
  this dashboard" and "AI apps need an access key".
- **Backups** has one Download button, says plainly what the file
  contains, and shows the setting that unblocks it.

### Fixes

- **A restored backup starts again.** The databases in a backup were
  stored as owned by root; restored the documented way, palaia could not
  open them and never became ready. New backups keep the right owner, and
  the restore steps fix the owner for older ones.
- Opening the Telegram settings by their address works again: only
  `/telegram/webhook` goes to the hub, not every `/telegram` page.

### Documentation

- The setup guide for AI assistants follows the new install and setup,
  including a key handoff that never touches the chat, and the save-and-find
  check before calling setup done.
- The install page lists the first-run steps in their real order; restoring
  a backup on a server set up with `get.palaia.ai` re-runs the installer
  instead of a hand-written `docker run`.

## 3.0.0-rc4 — 2026-10-03 (release candidate)

A small release candidate on top of `rc3`: one new hint for AI tools, and
documentation that matches decisions made since. Still a pre-release — the
`:beta` channel.

### Memory & search

- **A heads-up when a note has a known problem.** The hub checks your
  memory once each time it starts. When an AI tool then reads a note that
  links to a renamed note by its old name, shares its address with another
  note, or cannot be edited because of its text encoding, the answer says so
  and names the next step. The hint is checked against the memory as it is
  now before it is shown.

### Documentation

- palaia v2 is described as retired everywhere: no new features, only
  critical fixes, v3 replaces it.
- The release checklist no longer lists an external security review or a
  recruited usability session before 3.0.0; neither was ever planned.
  Private vulnerability reporting, the channel `SECURITY.md` names, is now
  switched on.
- The Telegram connector has its own page on the docs site, and the feature
  overview covers what `rc3` added.

## 3.0.0-rc3 — 2026-09-28 (release candidate)

The third release candidate, and the first meant for a live test end to
end. Everything below is new relative to `rc2`. Still a pre-release — the
`:beta` channel, same caveats as before.

### Memory & search

- **Temporary memories for one task**: create a memory for a trip, a report
  or a migration from the Explorer, copy the notes worth keeping into an
  everyday memory when you are done, then close it. Closing archives its
  folder; nothing is deleted. The health check lists one that is overdue.
- **`memory_status`** on every connection: an AI tool can check which
  memories it may read and write, how many notes they hold and whether
  search is hybrid or full-text only, instead of guessing that its memory
  is unavailable.
- **Is your AI tool actually using it?** The Clients page shows, per tool,
  how often it looked something up and saved something over the last
  seven days, and how many of its sessions saved before looking anything
  up. Only counts are kept, and they survive a restart.
- Saving a note that closely resembles an existing one now names that note,
  so a tool can update it instead of keeping two versions.
- Notes that get recalled often rank a little higher, and that boost fades
  again when they stop being asked for.
- Every memory tool now says what it returns and how it fails.
- Home's activity list shows what changed before you opened the page, not
  only what happens afterwards.

### Backups

- **Back up on a schedule**: set `interval_hours`, and the hub writes its
  backup into every configured folder by itself. The new **Backups** screen
  lists the folders, how each last backup went, and a "Back up now" button.
- **Push a memory to a git repository** you own, for example a private
  GitHub repository: set it up on the Backups screen with an access token,
  which is stored encrypted. Only the notes go there, never keys, and the
  hub never overwrites commits it did not make.

### Telegram

- The Telegram connector now runs in the hub, and a **Telegram** screen shows
  each bot's status, where its messages go, and recent messages. Bots,
  routing rules and send permissions are set up and changed from that
  screen; changes apply without a restart.

### Installing

- A one-command installer for an existing server (`get-palaia.sh`), and a
  guided setup an AI assistant can walk you through, grounded in what this
  release actually ships.
- The unattended cloud setup file pins the `:beta` image during the release
  candidates, so pasting it no longer fails on a missing image.

### Marketplace

- Add-ons that could not be installed are no longer offered: the two
  bundled entries pointed at images that were never published.
- Servers from the official MCP registry are listed once, not once per
  published version.

### Fixes

- The hub image now contains `git`. Creating a memory failed in the
  published image without it.
- The hub image now ships the embedding backend, so search in the image
  combines keywords and meaning instead of keywords only.
- Embeddings kept working when the default model's files changed upstream
  on 2026-09-27; the vectors are unchanged.
- The running hub picks up tokens created or revoked with `palaia-hub token`
  on the command line; a revoked token used to keep working until a restart.
- Behind the image's web server, redirects and the Claude Desktop bundle's
  address keep the published port (8420).
- A token id never starts with a dash, which broke `palaia-hub token revoke`.

### Under the hood

- The web toolchain moved to Node 26, Python formatting is enforced in CI,
  and the checks `main` requires now always report.

## 3.0.0-rc2 — 2026-09-20 (release candidate)

The second release candidate. Everything below is new relative to `rc1`;
nothing already listed under `rc1` is repeated. Still a pre-release for
testing — the `:beta` channel, same caveats as `rc1`.

### Memory & search

- Search now tells you *how* it found each hit: every result carries its
  provenance (full-text / vector, or both) and a per-result `degraded` signal
  when semantic search was unavailable and the query fell back to text-only —
  so an agent can weigh the hits instead of trusting them blindly.
- Smart Nudges: short, deterministic, rule-based guidance is attached to the
  output of a successful memory tool (no extra model call) — for example, a
  note when a search ran degraded. Error results stay untouched.

### Operations

- `palaia doctor`: a whole-hub diagnose command — a check framework with real
  checks across the hub, run from the CLI, reporting problems in one place.
- Backup targets: a backup-destination abstraction with a built-in
  secret-safety invariant (a destination that isn't secret-safe is refused
  before a byte is written), plus a local-directory target end-to-end — CLI
  (`palaia-hub backup`), REST (`/api/backup/targets`), and
  `backup.target.succeeded` / `backup.target.failed` events. External and
  per-vault git-remote targets, scheduling and a dashboard panel are tracked
  as follow-ups (#438).

### Fixes

- `claude mcp get` / `claude mcp list` no longer reports "Failed to connect"
  against a working OAuth profile: the protected-resource metadata now
  advertises the gateway mount URL as its RFC 9728 `resource`, which is what
  MCP clients validate against (the `aud` audience is unchanged).
- Docs corrected: the nonexistent "recall" hook-event claim in how-it-works,
  and the plugin README's `memoryInject` default and search description.

### Under the hood

- Supply chain: v3 workflow actions pinned by commit SHA, base images pinned
  by digest, and Dependabot added to keep both current; store manifests
  (TrueNAS template library, Umbrel gallery shape) corrected.
- A preview **Telegram connector** landed in the codebase (inbound routing per
  bot/chat, outbound send tools, message-text redaction). It is **not yet
  wired into the running hub** — daemon wiring and a dashboard panel are the
  remaining work (#439) — so it does nothing in this image yet; it ships early
  so its shape can be reviewed.

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
