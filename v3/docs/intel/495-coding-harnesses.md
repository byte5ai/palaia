# Coding harnesses (OpenRig and others) as palaia plugins or add-ons

Issue [#495](https://github.com/byte5ai/palaia/issues/495) · intel research · written
2026-09-26 against `3.0.0-rc2` (commit `bec551f`).

This is research, not a feature. The issue asks whether multi-agent coding harnesses
should be offered through palaia, and in which of three shapes:

1. **Harness as a palaia client**: it registers its agents in the session directory
   and uses shared memory and messenger envelopes.
2. **Harness as a store add-on**: it gets a SPEC-304 manifest and palaia hosts the
   harness container, while the harness runs the agents.
3. **palaia spawns and supervises agents itself.** This crosses the MASTERPLAN
   non-goal, and it is the same decision as [#493](https://github.com/byte5ai/palaia/issues/493).

The dossier does not write an ADR and does not edit the MASTERPLAN. §6 says what an ADR
would have to decide.

## Evidence base

Everything about **palaia** is read off this repository at `bec551f` and cited by file
and line.

Everything about **external harnesses** was fetched on **2026-09-26**, from two kinds of
source:

- **Repository metadata** (licence, stars, creation date, last push, releases,
  contributor count) comes from the GitHub REST API (`/repos/{owner}/{repo}`,
  `/releases`, `/contributors?anon=1`). Contributor counts are read off the pagination
  header, so treat them as approximate. Star counts are a snapshot and move daily.
- **Behaviour** (how a harness spawns and addresses agents) comes from each project's
  README or source at `HEAD`, or from the vendor's documentation, fetched live that
  day. The URL is given at each claim and again in §8.

Anything that was not read directly from one of those sources is marked
**UNVERIFIED**. Nothing here was installed or run. Every behavioural statement is what
the project documents or what its code says, not what this session observed.

## 1. Verdict

**Shape 1 fits every candidate, it is cheap, and it is the only shape palaia can ship
without an ADR.** palaia already has the pieces a harness needs: a session directory
with an open `platform` field, a messenger with typed envelopes and vault references,
and an MCP endpoint every harness in this survey can consume. What is missing is small
and client-side: registration recipes per harness, a convention for mapping a harness
"seat" onto a directory row, and a hook-driven heartbeat (§5.1).

**Shape 2 does not fit palaia's actual container runtime.** A store add-on is a
`docker run --rm -i` child process spawned as a stdio MCP upstream. It is capped at
1 GiB and 512 processes, and it is respawned by the health probe when it dies
(`v3/server/src/palaia_hub/market/docker_runtime.py:1-40,55-70`). A harness is a
long-lived daemon with tmux sessions, provider logins, repository mounts and, for some,
Docker itself. Hosting one needs a new entry kind, a new permission vocabulary and the
docker-socket ADR that MASTERPLAN open decision #4 already names
(`v3/MASTERPLAN.md:642`). Even then palaia would only be a launcher for software that
brings its own UI (§5.2).

**Shape 3 should not move the non-goal now.** The category is occupied. OpenHands Agent
Canvas, OpenClaw's ACP runtime, Claude Code's agent teams, Codex subagents and OpenRig
all spawn and supervise Claude Code or Codex today. Each of them would be a shape-1
client of palaia. Crossing the line would put palaia into a crowded field and weaken
the thing no candidate offers: one self-hosted memory and message broker across
providers (§5.3).

**The finding that matters most is not a harness.** Claude Code now ships its own
session discovery and messaging (`ListAgents` / `SendMessage`, agent teams with
per-agent mailboxes, cross-machine delivery through Anthropic's servers). For a user
who runs only Claude, that covers much of MASTERPLAN pillar P4. palaia's defensible
delta is being cross-provider, self-hosted, structured and observable (§4).

## 2. The palaia side: boundary and seams

### 2.1 The boundary

- **Non-goal**: palaia is "not an LLM host (it doesn't run models), not an agent
  framework (it doesn't orchestrate reasoning)" (`v3/MASTERPLAN.md:56-59`). The
  non-goals sit under §2 "Target Users". The wording is about *reasoning*, not
  *processes*. Starting a `claude` process does not orchestrate its reasoning, while a
  planner that splits tasks across agents does. Any ADR has to sharpen this either way
  (§6).
- **Add-ons**: containerized local MCP servers with a declarative manifest, declared
  permissions and sandboxing (`v3/MASTERPLAN.md:329-349`). Container add-ons were
  planned "in phase 3 (needs docker-socket ADR)" (`v3/MASTERPLAN.md:642`, status
  *Proposed*).
- **Messenger and directory**: sessions register "via skill/hook/SDK". Delivery is pull
  over MCP as the baseline, with push adapters "where platforms allow them", and
  Claude Code's `claude/channel` is named as the precedent (`v3/MASTERPLAN.md:351-374`).
  Open decision #6 keeps the messenger a built-in pillar, not an add-on
  (`v3/MASTERPLAN.md:644`).
- **OpenClaw**: "not a v3 launch target — v2 serves it", with a v3 adapter later
  (`v3/MASTERPLAN.md:499`). Open v2-plugin bugs #482/#483 are client-side fixes, and
  they confirm the existing pattern: the harness is the client, palaia is the memory.

### 2.2 Session directory (SPEC-402), as built

- A row has a server-minted `handle`, free-text `scope`, `host`, `platform`,
  `agent_kind`, a self-reported `model`, `status`, free-text `capabilities`, and TTL
  fields (`v3/server/src/palaia_hub/directory/models.py:28-43`). The spec's platform
  list is `claude-code | claude-desktop | claude-ai | codex | gemini | other`, an
  open enum stored verbatim (`v3/specs/SPEC-402-session-directory.md:22-23`). So
  `openrig`, `openclaw` or `openhands` need no schema change.
- `register` returns a **session secret**, and only its holder can heartbeat, update or
  deregister (`SPEC-402:28-32`). The default TTL is 300 s
  (`v3/server/src/palaia_hub/directory/store.py:69`). A row turns `stale` past its TTL
  and is pruned at 5×TTL.
- `session.registered|updated|idle|stale|deregistered` are on the event bus
  (`v3/server/src/palaia_hub/events/schema.py:111-115`).
- **There is no parent/child relation.** A harness with a lead and ten workers is ten
  unrelated rows. The only place to express "this row is seat X of rig Y" is a
  `capabilities` tag or the `scope` text.

### 2.3 Messenger (SPEC-403), as built

- The envelope types are `request | inform | question | handoff | broadcast`
  (`v3/server/src/palaia_hub/messenger/models.py:45`). The body is capped at 4096 UTF-8
  bytes (`:64`), and long content goes into the vault and travels as a `memory://`
  reference. Broadcast is capped at 20 recipients (`:78`).
- Delivery is **pull only**: `messenger_check` requires the recipient's session secret
  (`v3/specs/SPEC-403-messenger.md:35-43`). Push exists as a webhook recipe on
  `message.received`. Claude Code's `claude/channel` is explicitly **not** implemented,
  because the pinned `fastmcp` cannot declare the capability
  (`v3/docs/messenger.md:194-208`).

### 2.4 Store add-ons (SPEC-304), as built

- The entry kinds are `remote | container | mcpb | skill | plugin`
  (`v3/server/src/palaia_hub/market/models.py:32`).
- A `container` entry "pulls and runs the declared image … then connects it as a
  SPEC-302 upstream", with restart-on-crash (`v3/specs/SPEC-304-marketplace.md:23-26`).
  The implementation is precise about what that means. Every container is a plain
  `docker run --rm -i <image>`, spawned as the child process of a `stdio` upstream,
  "not a second thing palaia supervises". A crash is healed by the next once-a-minute
  health probe respawning the child (`docker_runtime.py:1-21`).
- Hardening applies to every add-on: all capabilities dropped, `no-new-privileges`,
  `--memory 1g`, `--pids-limit 512` (`docker_runtime.py:55-70`). Without the `network`
  permission a container gets `--network none`. Without `filesystem` its root is
  read-only (`docker_runtime.py:148-152`).
- The permission vocabulary is exactly four values: `network`, `filesystem`,
  `memory-scope:read`, `memory-scope:write`
  (`v3/sdk/src/palaia_addon_sdk/models.py:43-44`).

### 2.5 Automations (SPEC-307), as built

The action kinds are `memory_write`, `stash_set` and `notification`
(`v3/server/src/palaia_hub/automations/models.py:47-73`), plus webhooks from SPEC-201.
**No action reaches a session.** "Tool invocation as an action" was deferred to
Phase 4 "with the messenger" (`v3/specs/SPEC-307-automations.md:57-59`). An automation
therefore cannot today say "when X happens, send a `request` to the session registered
for repo Y". §6 argues this is the smallest real step toward #493 and #495.

## 3. The candidates

### 3.1 Maturity at a glance

All figures fetched from the GitHub API on 2026-09-26.

| Project | Licence | Stars | Latest release | Contributors (≈) | Created | Note |
|---|---|---|---|---|---|---|
| [OpenRig](https://github.com/mvschwarz/openrig) | Apache-2.0 | 515 | v0.5.16, 2026-09-26 | 12 | 2026-04-01 | Pre-1.0, releases every few days |
| [OpenClaw](https://github.com/openclaw/openclaw) | MIT (LICENSE file, "© 2026 OpenClaw Foundation", plus third-party notices). The GitHub API reports `NOASSERTION` | 390,563 | v2026.9.6, 2026-09-23 | 3,432 | 2025-11-24 | Calendar versioning |
| [Claude Code](https://github.com/anthropics/claude-code) | Proprietary: "© Anthropic PBC. All rights reserved", Commercial Terms | 148,177 | — (repo carries no release objects) | — | 2025-02-22 | |
| [Claude Agent SDK (Python)](https://github.com/anthropics/claude-agent-sdk-python) | MIT per GitHub, but SDK use is governed by the Commercial Terms (§3.4) | 8,170 | v0.2.160, 2026-09-25 | 72 | 2025-06-11 | |
| [Claude Agent SDK (TypeScript)](https://github.com/anthropics/claude-agent-sdk-typescript) | Proprietary: "© Anthropic PBC", Commercial Terms | 1,773 | v0.3.283, 2026-09-25 | 7 | 2025-09-27 | |
| [Codex CLI](https://github.com/openai/codex) | Apache-2.0 | 126,579 | stable `rust-v0.157.1`, 2026-09-26; alpha pre-releases the same day | 631 | 2025-04-13 | |
| [OpenHands](https://github.com/OpenHands/OpenHands) | MIT | 89,216 | v1.24.0, 2026-09-25 | 565 | 2024-03-13 | README badge: "status: beta" (Agent Canvas) |
| [Ruflo](https://github.com/ruvnet/ruflo) (formerly claude-flow) | MIT | 73,317 | v3.45.0, 2026-09-24 | 44 | 2025-06-02 | |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Apache-2.0 | 28,197 | v0.1.45 (pre-release), 2026-09-19 | 66 | 2025-06-14 | **Sunsetting**: company shut down 2026-04-10, "community maintained" |
| [Claude Squad](https://github.com/smtg-ai/claude-squad) | AGPL-3.0 | 8,536 | v1.0.20, 2026-08-20 | 20 | 2025-03-09 | |

Codex cloud tasks are a hosted service with no repository, so they are not in the table.

### 3.2 OpenRig

**What it is.** In its own words, "a multi-agent harness that runs Claude Code and Codex
together as one system". It is a local daemon, a CLI, a TUI and an MCP server built on
tmux: "Hono HTTP daemon → domain services → SQLite + tmux + runtime adapters". Topologies
are declared in YAML ("RigSpec": pods, members, edges, continuity policies) and booted
with `rig up`. Source: [README](https://github.com/mvschwarz/openrig/blob/main/README.md).

**How it spawns agents.** Each member is a native `claude` or `codex` process in its own
tmux session. OpenRig also runs "terminal nodes, and a Pi adapter". A managed Claude
launch uses `--permission-mode acceptEdits`, and a Codex launch uses
`-s workspace-write`. The `--dangerously-skip-permissions` / `danger-full-access` mode
("YOLO") is off by default. OpenRig writes provider hooks and workspace trust into
`~/.claude.json`, `.claude/settings.local.json` and `~/.codex/config.toml`
([README, "What OpenRig changes on your machine"](https://github.com/mvschwarz/openrig/blob/main/README.md#what-openrig-changes-on-your-machine)).
It can also *adopt* existing tmux sessions (`rig discover`, `rig adopt`). Service-backed
rigs need Docker.

**How it addresses agents.** A **seat** is "a stable role and address in a rig, such as
`dev-owner@first-project`. The conversation occupying it can change while its identity
and authored context remain." Messages go through `rig send`, `rig broadcast` and
`rig chatroom`, and the stdio MCP server (`rig mcp serve`) exposes the same tools as
`rig_up`, `rig_ps`, `rig_send`, `rig_chatroom_send` and others. That server dials the
daemon at `http://127.0.0.1:<port>`
([`packages/cli/src/commands/mcp.ts`](https://github.com/mvschwarz/openrig/blob/main/packages/cli/src/commands/mcp.ts),
[`packages/cli/src/mcp-server.ts`](https://github.com/mvschwarz/openrig/blob/main/packages/cli/src/mcp-server.ts)).
Harness hooks relay lifecycle events (type, seat, runtime, timestamps; no prompt text)
to the daemon's `/api/activity/hooks` endpoint.

**Overlap with palaia.** Seats ≈ directory rows, and `rig send` ≈ `messenger_send`.
OpenRig also has its own knowledge store: "lore" is Markdown under
`rigs/<rig>/seats/<seat>/lore/`, addressed as `seat:lore/<slug>.md`
([`docs/reference/lore-routing.md`](https://github.com/mvschwarz/openrig/blob/main/docs/reference/lore-routing.md)).
That overlaps palaia's vault. This dossier notes the overlap and does not resolve it.

**Fit.**
- **Shape 1: good, and cheap.** An AgentSpec can carry runtime resources of type
  `claude_mcp_fragment` (merged into the seat's `.mcp.json`) and `codex_config_fragment`
  (upserted into `~/.codex/config.toml`)
  ([`docs/reference/agent-spec.md`](https://github.com/mvschwarz/openrig/blob/main/docs/reference/agent-spec.md)).
  One fragment gives every seat palaia's MCP endpoint. A startup file or skill makes
  each seat call `directory_register` with `platform: "openrig"` (the enum is open,
  §2.2) and the seat address as a capability tag. The palaia-messenger skill already
  exists (`v3/clients/skills/palaia-messenger/`).
- **Upstream variant.** `rig mcp serve` is a stdio MCP server, so the palaia gateway
  could add it as a SPEC-302 `stdio` upstream and expose `rig_*` tools to *every*
  client (a phone could `rig_send` to a seat). The limit is that it dials `127.0.0.1`.
  It works only when the hub and the OpenRig daemon share a host. The daemon can bind
  elsewhere only with a bearer token (`OPENRIG_HOST` + `OPENRIG_AUTH_BEARER_TOKEN`,
  per
  [`docker/testbed/runbooks/L3-daemon-in-container.md`](https://github.com/mvschwarz/openrig/blob/main/docker/testbed/runbooks/L3-daemon-in-container.md)),
  and the MCP wrapper does not pass one through (**UNVERIFIED** beyond the file cited).
- **Shape 2: poor** (§5.2). It needs tmux, provider logins, repository mounts and,
  optionally, Docker.

**What palaia would add:** a recipe (docs plus an example AgentSpec fragment), the
seat-to-row convention (§5.1), and optionally a documented `stdio` upstream entry.

### 3.3 Claude Code: sub-agents, agent teams, cross-session messaging

**Sub-agents.** Each "runs in its own context window with a custom system prompt,
specific tool access, and independent permissions". They are defined as Markdown with
frontmatter in `.claude/agents/`, `~/.claude/agents/`, a plugin's `agents/`, managed
settings, or the `--agents` JSON flag. Priority runs from managed settings down to
plugins ([docs: sub-agents](https://code.claude.com/docs/en/sub-agents)).

**Agent teams** are experimental and off by default
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). Each teammate is "a full, independent Claude
Code session", running in-process or in tmux/iTerm2 split panes. Coordination uses a
shared task list with file-locked claiming, plus a mailbox. "Each agent's mailbox is a
JSON file at `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`". The team config at
`~/.claude/teams/{team-name}/config.json` lists members, and "teammates can read this
file to discover other team members". It is removed when the session ends
([docs: agent teams](https://code.claude.com/docs/en/agent-teams)).

**Cross-session messaging** is on by default from v2.1.224 (macOS/Linux) and v2.1.234
(Windows) ([docs](https://code.claude.com/docs/en/cross-session-messaging)):
- Two tools: `ListAgents` discovers reachable agents and `SendMessage` delivers by name.
  The same tool reaches sub-agents and teammates.
- Same-machine delivery is "over a per-session socket … never through Anthropic
  servers". Other machines and cloud sessions are reached "through Anthropic servers"
  over Remote Control, which "needs a claude.ai sign-in". A container cannot reach the
  host's sessions ("a container has its own filesystem").
- Messages are "plain text only". A message "can't approve anything", "can't change
  configuration", and the receiver's permission prompts still fire. Inbound handling is
  `accept | hold | refuse` via `crossSessionInbound`. Loops are throttled, and the
  inbox queue holds at most 50 accepted messages.
- **Each session's inbox socket is exported to hooks and Bash as
  `CLAUDE_CODE_MESSAGING_SOCKET`**, along with a per-session token, so "a script or hook
  [can] post into a session". A message that Claude Code cannot verify as coming from
  the session's own child process gets the default inbound treatment. A session that
  bypasses permission prompts *holds* such a message for approval.

**Fit.** Shape 1, natively. Claude Code already consumes palaia over MCP, and sub-agents
and teammates inherit it through `.mcp.json` or a plugin. §4 covers what the messaging
features mean for palaia.

**What palaia would add:** a push path into a Claude Code session through the inbox
socket. A small local relay would turn palaia `message.received` events into a line on
the recipient's socket. This is documented upstream, not exercised here, and belongs
with #494 / SPEC-404. The relay must run on the same machine, outside any container,
and it is subject to the receiver's inbound controls.

### 3.4 Claude Agent SDK

"A library that runs the Claude Code binary", in Python and TypeScript, with built-in
tools, hooks, sub-agents, MCP and sessions (resume/fork)
([docs: Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)).
Two statements on that page bear directly on shape 3:

> "Unless previously approved, Anthropic does not allow third party developers to offer
> claude.ai login or rate limits for their products, including agents built on the
> Claude Agent SDK."

> "Use of the Claude Agent SDK is governed by Anthropic's Commercial Terms of Service …
> except to the extent a specific component or dependency is covered by a different
> license as indicated in that component's LICENSE file."

The TypeScript SDK's `LICENSE.md` is "© Anthropic PBC. All rights reserved. Use is
subject to Anthropic's Commercial Terms of Service", and so is Claude Code's. GitHub
reports MIT for the Python SDK repository.

**Fit.** The SDK is the obvious engine for shape 3: palaia would embed it and run agents.
Doing so raises a question this dossier does not answer. Does a self-hosted, personal
hub that starts the user's own `claude` under the user's own subscription fall under
"offer claude.ai login … for their products"? OpenRig starts native `claude` processes
under the user's login. Whether that is sanctioned is **UNVERIFIED**. An ADR for shape 3
has to settle the auth model (API-key billing or subscription) before anything is built.

### 3.5 Codex: CLI subagents, app server, cloud tasks

**Subagents.** "Current Codex releases enable subagent workflows by default", in the CLI,
the IDE extension and the desktop app. Codex spawns subagents on a direct request or
when AGENTS.md or skill instructions ask for it. `/agent` switches between agent
threads. Custom agents are TOML files in `~/.codex/agents/` or `.codex/agents/` with
`name`, `description` and `developer_instructions`. Settings such as `sandbox_mode`,
**`mcp_servers`** and `skills.config` "inherit from the parent when the custom agent file
omits them". `[agents] max_concurrent_threads_per_session` caps concurrency
([docs: subagents](https://developers.openai.com/codex/agent-configuration/subagents)).
Subagents report back to the main thread. The page documents no peer-to-peer channel
between them.

**App server, not MCP.** "The `codex mcp-server` command and the standalone
`codex-mcp-server` binary have been removed." The replacement, the Codex app server,
"uses its own JSON-RPC protocol … It isn't an MCP server", and "is experimental and
isn't supported for production workloads". Codex continues to *consume* external MCP
servers ([docs: MCP server removal](https://developers.openai.com/codex/mcp-server)).
So a supervisor that wants to drive Codex programmatically now faces an experimental
JSON-RPC surface. The earlier MCP-wrapping route is gone.

**Cloud tasks** run "in isolated cloud environments", in parallel, started "from the web,
GitHub, GitLab, Linear, or Slack", and return a summary and diff or a pull request
([docs: Codex cloud](https://developers.openai.com/codex/cloud)). "By default, Codex
blocks internet access during the agent phase", and it can be enabled per environment
([docs: internet access](https://developers.openai.com/codex/cloud/internet-access)).
Whether a cloud task can reach a remote HTTP MCP server such as a palaia hub is
**UNVERIFIED** in this pass. #202 records it as not reachable, which makes Codex cloud
out of scope for the remote server. That claim predates this dossier and was not
re-checked.

**Fit.** Shape 1, for the CLI and IDE. One project-scoped `[mcp_servers.palaia]` entry
reaches the main thread and, by inheritance, every subagent. Cloud tasks are out of
scope until the reachability question is re-verified.

**What palaia would add:** nothing structural. A connect-page note that subagents
inherit the palaia entry, and a directory convention for registering a subagent thread
(§5.1), if anyone wants subagents visible at all.

### 3.6 OpenClaw

OpenClaw runs external coding harnesses through **ACP** (Agent Client Protocol): "Claude
Code, Cursor, Copilot, Droid, OpenClaw ACP, OpenCode, Gemini CLI, and other supported
acpx harnesses", via the `@openclaw/acpx` runtime plugin. "Each spawn is tracked as a
background task." The spawn tool is `sessions_spawn({ runtime: "acp" })` or
`/acp spawn`. Native sub-agents use `sessions_spawn` with the default runtime. Session
keys are `agent:<agentId>:acp:<uuid>` and `agent:<agentId>:subagent:<uuid>`. Codex also
has a native app-server path (`/codex bind`)
([docs: ACP agents](https://docs.openclaw.ai/tools/acp-agents)). OpenClaw can also act
*as* an ACP server for an editor (`openclaw acp`, [docs](https://docs.openclaw.ai/cli/acp)).

**Fit.** OpenClaw is already a shape-1 client of palaia v2 (#202), and it is itself a
shape-3 supervisor of Claude Code and Codex. The v3 adapter stays deferred
(`v3/MASTERPLAN.md:499`). Any harness work for OpenClaw belongs in that adapter, as #194's
dossier already concluded (`v3/docs/intel/194-active-memory-plugin.md` §5–6).

**What palaia would add:** nothing new for #495. The session keys map naturally onto
directory rows (`platform: "openclaw"`, key as a capability tag) once the v3 adapter
exists.

### 3.7 OpenHands Agent Canvas

"The self-hosted developer control center for coding agents and automations. Run
OpenHands, Claude Code, Codex, Gemini, or any ACP-compatible agent across local, remote,
and cloud backends." It runs an agent server locally, in Docker, on VMs or on OpenHands
Cloud. Automations run "on a schedule or in response to webhook events", with Slack,
GitHub and Linear integrations. The README carries a "status: beta" badge and warns
that the no-sandbox install gives the agent "full access to your filesystem"
([README](https://github.com/OpenHands/OpenHands/blob/main/README.md)).

**Fit.** This is **shape 3 already built, open source (MIT) and well staffed** (565
contributors). It is the strongest single argument against palaia crossing the
non-goal: the self-hosted "control center that spawns Claude Code and Codex and triggers
them from events" exists. Whether OpenHands' agents can register as MCP clients of an
external hub was not checked (**UNVERIFIED**). If they can, the fit is shape 1, like
everything else.

### 3.8 Claude Squad

"A terminal app that manages multiple Claude Code, Codex, Gemini … in separate
workspaces." It uses tmux for isolated sessions and git worktrees so each session works
on its own branch. Background runs with auto-accept are experimental (`--autoyes`)
([README](https://github.com/smtg-ai/claude-squad/blob/main/README.md)). AGPL-3.0.

**Fit.** Shape 1 only, and only indirectly. Claude Squad launches unmodified CLIs, so
palaia reaches its agents through each CLI's own MCP config. Nothing is harness-specific.
AGPL-3.0 is the licence ADR-002 kept out of palaia's codebase in the basic-memory case
(`v3/decisions/002-clean-room-licensing.md`), so embedding or vendoring Claude Squad is
off the table. A separate, unmodified program that a user runs is a different matter
and is not assessed here.

### 3.9 Vibe Kanban

A kanban board that runs "10+ coding agents" (Claude Code, Codex, Gemini CLI, Copilot,
Amp, Cursor, OpenCode, …) in per-issue workspaces with a branch, terminal and dev
server ([README](https://github.com/BloopAI/vibe-kanban/blob/main/README.md)). Its
README headline is now **"Vibe Kanban is sunsetting."** The company behind it shut down
on 2026-04-10, and the project "will live on as open source and community maintained"
([announcement](https://www.vibekanban.com/blog/shutdown)).

**Fit.** Shape 1 at most. The more useful point is the **churn data point**: a harness
with 28k stars lost its company inside a year. Harnesses come and go faster than a
user's accumulated memory. That argues for palaia being the durable layer underneath
whichever harness is in fashion, and against coupling palaia's roadmap to any one of
them.

### 3.10 Ruflo (formerly claude-flow)

"Ruflo is the harness — the execution layer around Claude Code and Codex that adds 100+
specialized agents, coordinated swarms, self-learning memory, federated comms across
machines". It is installed as a Claude Code plugin set or through `npx ruflo init`,
which writes `.claude/`, `.claude-flow/`, `CLAUDE.md`, hooks and an MCP server into the
workspace ([README](https://github.com/ruvnet/ruflo/blob/main/README.md)). The counts in
its README ("314 MCP tools", "98 agents") are the project's claims and are
**UNVERIFIED**.

**Fit.** Ruflo is a shape-1 client in principle, but it bundles its **own memory
layer**, so it is as much a competitor to P1 as a harness. Integration would mean
choosing whose memory wins in a workspace. That is a product decision, not a plugin.

## 4. Claude Code already ships P4 for Claude-only users

palaia's P4 pitch is "Sessions become visible … a cross-host, cross-provider messenger
with *structured* messages" (`v3/MASTERPLAN.md:83-88`). Three comparable systems now
exist:

| Dimension | palaia directory + messenger | Claude Code cross-session messaging | Claude Code agent teams | OpenRig |
|---|---|---|---|---|
| Providers | Any MCP client; `platform` is an open enum | Claude Code only | Claude Code only | Claude Code + Codex (+ terminal, Pi) |
| Discovery | `directory_list` / `directory_query` by scope, capability, platform | `ListAgents` / `/list-agents` | Team `config.json` members | `rig ps`, topology graph |
| Addressing | Server-minted handle | Session name (`/rename`, `--name`) | Teammate name | Seat `role@rig` |
| Message shape | Typed envelope, subject, urgency, `expects_reply`, `memory://` refs | Plain text | Plain text + structured team protocol messages | `rig send` text, chatroom |
| Size discipline | 4096-byte body cap, "write it to memory" | ~1M characters | — | not checked |
| Cross-host | Yes: the hub is the broker, self-hosted | Via Anthropic servers + Remote Control (claude.ai sign-in) | Same machine | Multi-host is a documented testbed target; not checked beyond that |
| Delivery | Pull (`messenger_check`) + webhook push | Pushed into the running turn, or starts a turn when idle | Per-agent mailbox file | `rig send` into the seat (mechanism not checked) |
| Auth between peers | Session secret per row; per-tool scopes | OS-user socket permissions + inbound `accept/hold/refuse` | Same user | Daemon bearer token off loopback |
| Human observability | Dashboard flows (SPEC-405) | Per-session transcript lines | Agent panel / panes | TUI graph and feed |

**What this means.** For a Claude-only user on one machine, palaia's messenger is now
the *second* way to do something the client does natively, and the native way pushes
while palaia polls. palaia's defensible delta is exactly the columns Claude Code cannot
fill:

1. **Cross-provider.** One directory for Claude Code, Codex, Gemini, OpenClaw and harness
   seats. No vendor will build this for a competitor's agents.
2. **Self-hosted broker.** Cross-machine delivery does not go through a vendor cloud and
   does not need a vendor sign-in.
3. **Structure and memory.** Envelopes point into the shared vault instead of pasting
   context. That is palaia's token-discipline argument, and none of the three
   alternatives has it.
4. **Observability and policy.** Flows are on a dashboard, subject to scopes, and visible
   to automations as events.

**Consequence for this issue.** The case for palaia in the harness space is shape 1
done well: be the directory and memory that *spans* harnesses and vendors. Racing
harnesses on spawning (shape 3) is not that case. The push gap is the concrete weakness
this comparison exposes, and it is already tracked as #494 and SPEC-404. The inbox
socket in §3.3 is a newly documented path for it.

## 5. Shape by shape

### 5.1 Shape 1: harness as a client (recommended)

Every candidate can already consume palaia over MCP. The work is on palaia's side of
the contract, and all of it is small:

1. **Registration recipes, per harness** (docs, no server code): OpenRig
   `claude_mcp_fragment` / `codex_config_fragment`; Codex `.codex/config.toml` with
   subagent inheritance; Claude Code `.mcp.json` or plugin, reaching sub-agents and
   teammates; OpenClaw deferred to the v3 adapter.
2. **A seat-to-row convention** so harness agents are legible in the directory without
   a schema change: `platform` = harness or client (`openrig`, `codex`, …),
   `agent_kind` = the role, capabilities such as `harness:openrig`,
   `seat:dev-owner@first-project`, `parent:<handle>`. If a real hierarchy view is
   wanted later, an optional additive `parent_handle` field on SPEC-402 is the smallest
   schema change. It is not needed now.
3. **Hook-driven presence instead of habit.** Harness seats restart often, and the
   default TTL is 300 s. Relying on the skill to register and heartbeat is fragile.
   Both Claude Code and Codex have lifecycle hooks (OpenRig relays exactly these to its
   own daemon), so a thin client-side hook script (register on start, heartbeat on
   activity, deregister on stop) would make presence automatic. It would live beside
   `v3/clients/skills/` and need no server change.
4. **Push, where the client allows it**: the Claude Code inbox-socket relay (§3.3),
   tracked with #494 and SPEC-404. Webhook push already exists.

**Not recommended now:** bridging palaia's messenger into a harness's own messaging
(`rig send`, teammate mailboxes). Two brokers relaying into each other invite loops and
duplicate delivery. Claude Code's own docs describe loop throttling as a necessity.
Revisit only if users ask for it.

### 5.2 Shape 2: harness as a store add-on (not on the current runtime)

What a harness needs, set against what a palaia container add-on gets (§2.4):

| Harness need | palaia container add-on today |
|---|---|
| A long-lived daemon plus many interactive agent processes | A single `stdio` child, `--rm`, respawned by the health probe on crash. A respawn would kill every running agent |
| tmux, a TUI, attachable terminals | No TTY or UI surface. The add-on speaks MCP over stdio |
| Provider logins (`~/.claude.json`, `CODEX_HOME`) and trust files written into the user's home | No home-directory mounts beyond declared paths. Credentials would sit inside an add-on container, a new class of secret |
| Repository working trees, read-write | `filesystem` + declared mounts; possible, but broad |
| Docker (OpenRig service-backed rigs) | Would need the docker socket inside the add-on: MASTERPLAN open decision #4's unwritten ADR |
| Several GB of RAM and hundreds of processes for several agents | `--memory 1g`, `--pids-limit 512` |
| Permissions such as "spawns processes", "holds model credentials", "spends money" | Four permissions: `network`, `filesystem`, `memory-scope:read/write` |

Making shape 2 real would take a new entry kind (a *service*, not a stdio MCP
upstream), a lifecycle supervisor, a new permission vocabulary, the docker-socket ADR,
and an answer for the Raspberry Pi appliance's resources. That is shape 3's machinery
under a different name, and the user would still drive the harness through the
harness's own TUI.

A cheap, honest variant exists if the store should *list* harnesses: hand-off entries
that point at the harness's own install path. SPEC-304 already treats `skill` and
`mcpb` entries this way: "the marketplace lists them, it does not reinvent their
delivery" (`SPEC-304:28-30`). A harness listing would need the same treatment for a
`plugin` or `manual` entry. That is discovery, not hosting, and it needs no ADR.
Whether curating third-party harnesses fits the store's trust model ("curation is the
product", `v3/MASTERPLAN.md:337-338`) is an owner call. Several harnesses write hooks
and trust settings into the user's home, and OpenRig says so plainly.

### 5.3 Shape 3: palaia spawns and supervises

What it would mean concretely: palaia starts `claude` or `codex` processes (directly,
through the Agent SDK, or through the Codex app server), gives them a task, watches them,
restarts or stops them, and accounts for their cost. This is what OpenHands Agent Canvas,
OpenClaw ACP, OpenRig, Claude Code agent teams and Codex subagents each already do.

Arguments against crossing the non-goal now:

- **The category is occupied**, by projects with far more contributors (§3.1) and by
  the vendors themselves.
- **Every one of them is a shape-1 client of palaia.** Staying the layer underneath
  serves all of them. Becoming one of them competes with all of them.
- **Harness churn** (§3.9): the durable asset is memory, not the spawner.
- **Terms and auth are unresolved** (§3.4): the Agent SDK's claude.ai-login statement,
  and the Codex app server being "experimental … not supported for production".
- **The appliance target**: supervising several coding agents on a Raspberry Pi hub
  (SPEC-603) is a resource problem in its own right.

The argument for crossing it is #493's case: a managed browser that an agent drives,
triggered by palaia. §6 shows a way to serve that case without spawning.

## 6. Recommendation

1. **Adopt shape 1 as the answer to #495.** Ship the harness recipes, the seat-to-row
   convention and the hook-driven presence script (§5.1). All of it is client-side or
   docs, with no ADR and no server change.
2. **Do not build shape 2 on the current container runtime.** If the store should
   surface harnesses, list them as hand-off entries that point at the harness's own
   install, subject to an owner call on curation (§5.2).
3. **Do not move the non-goal now.** Close the gap it leaves with the smallest step
   that stays inside it: the deferred SPEC-307 "tool invocation as an action",
   narrowed to a **`messenger_send` action**. An automation could then send a
   `request` envelope to a *registered* session ("when the browser session expires,
   ask the session working on repo X to re-check"). palaia would trigger work without
   running it. This is exactly #493's stated alternative ("messaging a registered
   session instead of spawning one"), and it gets stronger with the push work in #494.
4. **Decide #493 and #495 together**, in one ADR, if and when the owner wants to
   revisit the non-goal. That ADR would have to decide:
   - **Scope of the boundary.** Is "orchestrate reasoning" (planning, task
     decomposition) still out while "run a process on request" is in? The current
     sentence does not say, and it should either way.
   - **The supervisor contract.** Process lifecycle, crash policy, timeouts, stop and
     kill from the dashboard, and where the processes run (hub host, a separate
     runner, never inside the appliance).
   - **The provider auth model.** API keys held by palaia, or the user's subscription
     login, checked against the Agent SDK statement in §3.4 and OpenAI's terms for
     the app server.
   - **Cost and quota accounting.** Who sees spend, and whether an automation can spend
     without a human.
   - **The security model.** A spawned agent with repository write access and a
     logged-in browser (#493) is the strongest credential palaia would ever hold. That
     needs ADR-006-style framing of untrusted input and an update to the threat model.
   - **Build, embed or delegate.** If spawning is wanted, is it palaia code, the Agent
     SDK, or a delegation to an existing supervisor (OpenHands, OpenRig) that palaia
     triggers over its API? The last option might keep the non-goal intact.
5. **Record the P4 competitive shift** (§4) wherever the owner tracks positioning. It
   changes how the messenger should be pitched: cross-provider and self-hosted first,
   "agents can message each other" second.

## 7. To verify before building on this

1. Whether Codex cloud tasks can reach a remote HTTP MCP server (#202's claim, not
   re-checked here).
2. Whether posting into `CLAUDE_CODE_MESSAGING_SOCKET` from a non-child relay is
   delivered under the default inbound rules on Linux, in a real session, and what the
   line format is beyond the documented auth line.
3. Whether OpenRig's MCP wrapper can reach a non-loopback daemon with a bearer token
   (only the daemon side is documented in the runbook cited).
4. Whether OpenHands Agent Canvas agents can take an external MCP server, and so
   register in palaia's directory.
5. How Anthropic applies the Agent SDK login statement to self-hosted, single-user
   tools that start the user's own `claude` CLI.
6. Codex subagents' behaviour around MCP: inheritance is documented, but whether
   each subagent opens its own MCP session (and so could register its own directory
   row) is not.

## 8. Sources

External sources were accessed on 2026-09-26.

| Claim | Location |
|---|---|
| Non-goals ("not an agent framework") | `v3/MASTERPLAN.md:56-59` |
| P4 pitch | `v3/MASTERPLAN.md:83-88` |
| Add-ons, curation, permissions | `v3/MASTERPLAN.md:329-349` |
| Directory, envelopes, push adapters, `claude/channel` precedent | `v3/MASTERPLAN.md:351-374` |
| OpenClaw not a v3 launch target | `v3/MASTERPLAN.md:499` |
| Open decisions #4 (docker-socket ADR), #6 (messenger built-in) | `v3/MASTERPLAN.md:642,644` |
| Directory row shape | `v3/server/src/palaia_hub/directory/models.py:28-43`; `v3/specs/SPEC-402-session-directory.md:17-27` |
| Session secret, TTL, prune | `v3/specs/SPEC-402-session-directory.md:28-32`; `v3/server/src/palaia_hub/directory/store.py:69` |
| `session.*` / `message.*` events | `v3/server/src/palaia_hub/events/schema.py:111-115,126-128` |
| Envelope types, body cap, broadcast cap | `v3/server/src/palaia_hub/messenger/models.py:45,64,78` |
| Pull-only check with session secret | `v3/specs/SPEC-403-messenger.md:35-47` |
| `claude/channel` not implemented | `v3/docs/messenger.md:194-208` |
| Entry kinds | `v3/server/src/palaia_hub/market/models.py:32` |
| Container install flow, restart-on-crash | `v3/specs/SPEC-304-marketplace.md:23-26` |
| Skill/MCPB entries hand off | `v3/specs/SPEC-304-marketplace.md:28-30` |
| Container = stdio child, respawned by probe | `v3/server/src/palaia_hub/market/docker_runtime.py:1-21` |
| Hardening and resource ceilings | `v3/server/src/palaia_hub/market/docker_runtime.py:55-70,148-152` |
| Permission vocabulary | `v3/sdk/src/palaia_addon_sdk/models.py:43-44` |
| Automation action kinds | `v3/server/src/palaia_hub/automations/models.py:47-73` |
| Tool invocation as an action deferred | `v3/specs/SPEC-307-automations.md:57-59` |
| Repo metadata (licence, stars, releases, contributors) | GitHub REST API, `/repos/{o}/{r}`, `/releases`, `/contributors?anon=1` |
| OpenRig architecture, seats, launch flags, provider writes | <https://github.com/mvschwarz/openrig/blob/main/README.md> |
| OpenRig runtime resources (`claude_mcp_fragment`, …) | <https://github.com/mvschwarz/openrig/blob/main/docs/reference/agent-spec.md> |
| OpenRig lore store | <https://github.com/mvschwarz/openrig/blob/main/docs/reference/lore-routing.md> |
| OpenRig MCP server (stdio, `rig_*` tools, loopback daemon) | <https://github.com/mvschwarz/openrig/blob/main/packages/cli/src/commands/mcp.ts>, <https://github.com/mvschwarz/openrig/blob/main/packages/cli/src/mcp-server.ts> |
| OpenRig daemon bind and bearer rule | <https://github.com/mvschwarz/openrig/blob/main/docker/testbed/runbooks/L3-daemon-in-container.md> |
| OpenClaw licence | <https://github.com/openclaw/openclaw/blob/main/LICENSE> |
| Claude Code sub-agents | <https://code.claude.com/docs/en/sub-agents> |
| Claude Code agent teams | <https://code.claude.com/docs/en/agent-teams> |
| Claude Code cross-session messaging, inbox socket | <https://code.claude.com/docs/en/cross-session-messaging> |
| Agent SDK capabilities, login statement, Commercial Terms | <https://code.claude.com/docs/en/agent-sdk/overview> |
| Agent SDK (TS) and Claude Code licence text | `LICENSE.md` in <https://github.com/anthropics/claude-agent-sdk-typescript> and <https://github.com/anthropics/claude-code> |
| Codex subagents, custom agents, MCP inheritance | <https://developers.openai.com/codex/agent-configuration/subagents> |
| `codex mcp-server` removed; app server experimental | <https://developers.openai.com/codex/mcp-server> |
| Codex cloud tasks | <https://developers.openai.com/codex/cloud> |
| Codex cloud agent internet off by default | <https://developers.openai.com/codex/cloud/internet-access> |
| OpenClaw ACP agents, `sessions_spawn`, session keys | <https://docs.openclaw.ai/tools/acp-agents> |
| OpenClaw as ACP server | <https://docs.openclaw.ai/cli/acp> |
| OpenHands Agent Canvas | <https://github.com/OpenHands/OpenHands/blob/main/README.md> |
| Claude Squad | <https://github.com/smtg-ai/claude-squad/blob/main/README.md> |
| Vibe Kanban, sunset | <https://github.com/BloopAI/vibe-kanban/blob/main/README.md>, <https://www.vibekanban.com/blog/shutdown> |
| Ruflo | <https://github.com/ruvnet/ruflo/blob/main/README.md> |
