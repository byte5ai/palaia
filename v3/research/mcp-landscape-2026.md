# Research: MCP ecosystem & client landscape (August 2026)

**Purpose:** verified factual basis for v3's protocol, gateway, marketplace and
client-integration design. **Method:** web research against official sources on
2026-08-22; every claim dated and linked. Items only sourceable from third parties
are flagged; a list of unverified details is at the end.

## 1. MCP specification

**Current version: `2026-07-28`** — "the largest revision since launch"
([RC post](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/),
[versioning](https://modelcontextprotocol.io/specification/versioning)). Two revisions
since 2025-06-18:

**2025-11-25** ([changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)):
OIDC Discovery for auth-server discovery; RFC 9728 protected-resource metadata with
`.well-known` fallback; incremental scope consent; **OAuth Client ID Metadata
Documents (CIMD)** as recommended client registration; URL-mode elicitation;
experimental **tasks** (durable requests); icons metadata; JSON Schema 2020-12
default.

**2026-07-28** ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)):

- **Stateless protocol:** `initialize` handshake and `Mcp-Session-Id` removed;
  version + capabilities travel in `_meta` per request → deployable behind plain
  load balancers/serverless. New mandatory **`server/discover`** RPC.
- **MRTR (multi-round-trip requests)** replaces server-initiated
  sampling/elicitation/roots calls: servers return `resultType: "input_required"`,
  clients retry with answers. **No server-initiated JSON-RPC anymore.**
- `subscriptions/listen` (one long-lived POST stream) replaces the GET stream and
  `resources/subscribe`; SSE resumability removed.
- **Extensions are first-class** (reverse-DNS ids, own versioning); **Tasks moved to
  official extension `io.modelcontextprotocol/tasks`**.
- Auth hardening: RFC 9207 `iss` validation; per-issuer credentials; **RFC 7591
  Dynamic Client Registration DEPRECATED in favor of CIMD**.
- Ops: mandatory cache metadata on list results, `Mcp-Method`/`Mcp-Name` headers,
  OpenTelemetry conventions, deterministic tool ordering (prompt-cache friendly).
- **Deprecated** (12-month lifecycle): Roots, Sampling, Logging; **HTTP+SSE
  transport** (migrate to Streamable HTTP).

Governance: MCP was donated to the **Agentic AI Foundation** (Linux Foundation) on
2025-12-09; platinum members incl. AWS, Anthropic, Block, Bloomberg, Cloudflare,
Google, Microsoft, OpenAI
([announcement](https://anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation)).
The [2026 roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
prioritizes transport scalability, tasks, governance, enterprise readiness (audit,
SSO, **gateway behavior**) — the spec itself is trending toward palaia's shape.

## 2. MCP Apps (UI inside the chat clients)

- **Final; the first official MCP extension** `io.modelcontextprotocol/ui`, spec
  2026-01-26 ([SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp),
  [overview](https://modelcontextprotocol.io/extensions/apps/overview)). Tools point
  at a `ui://` HTML resource; hosts render it in a sandboxed iframe; the app speaks
  JSON-RPC over postMessage incl. proxied `tools/call`.
- **Rendering clients** ([matrix](https://modelcontextprotocol.io/extensions/client-matrix)):
  claude.ai, Claude Desktop, VS Code Copilot, Microsoft 365 Copilot, Goose, Postman,
  MCPJam, Archestra. **ChatGPT** renders MCP-Apps-standard UI too (its Apps SDK is
  MCP-based; OpenAI recommends leading with the open standard).
- Implication: **palaia can ship onboarding/config/memory panels directly into the
  chat clients** — a huge UX lever on top of the own dashboard.

## 3. MCPB (MCP Bundles, ex-DXT)

- ZIP of a **local** MCP server + `manifest.json`; donated to the MCP org 2025-11-20
  ([blog](https://blog.modelcontextprotocol.io/posts/2025-11-20-adopting-mcpb/),
  [repo](https://github.com/modelcontextprotocol/mcpb)). Clients: Claude Desktop,
  Claude Code, MCP for Windows.
- **Local-only:** server types `node|python|binary|uv` — **no remote/HTTP type**; an
  MCPB cannot declare a remote URL
  ([MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md)).
  Established workaround (explicitly noted in Anthropic docs): **bundle a thin local
  stdio proxy that talks to your remote endpoint** — exactly palaia's Claude-Desktop
  one-click path.
- `user_config` auto-generates a settings UI in Claude Desktop (`sensitive` values go
  to the OS keychain). Signing: `mcpb sign` (PKCS#7/CMS), `mcpb verify`; whether
  Claude Desktop *enforces* signatures is undocumented (unverified). **SPEC-306
  update:** running the tooling confirms `mcpb verify`/`info` themselves report a
  self-signed bundle as *unsigned* (not "signed but untrusted") — they additionally
  check the signing cert against the OS trust store (`security verify-cert` /
  `X509Chain` / `openssl verify -CApath`), which no self-signed cert ever passes;
  Claude Desktop's own enforcement remains genuinely undocumented. Full accounting:
  `v3/tools/build-mcpb/SIGNING.md`.
- Anthropic now calls MCPB "the secondary distribution path — remote MCP servers are
  recommended" ([guide](https://claude.com/docs/connectors/building/mcpb)).

## 4. Official registry & Anthropic directory

- **registry.modelcontextprotocol.io: preview, but API-frozen** — v0.1 API stable
  since 2025-10-24 ("no breaking changes" for integrators), GA is a future milestone
  ([repo](https://github.com/modelcontextprotocol/registry)). Open REST API
  (`/v0/servers`); **aggregators/subregistries are the intended consumption model** —
  palaia can browse/mirror it today.
- `server.json` schema `2025-12-11`; publishing auth via GitHub OAuth/OIDC or DNS
  verification.
- **Moderation is minimal by design** ("consumers should assume minimal-to-no
  moderation" — [policy](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/moderation-policy.mdx)).
  **Trust/curation is explicitly left to subregistries — that's palaia's marketplace
  opportunity.**
- **Anthropic connectors directory** ([claude.ai/directory](https://claude.ai/directory),
  950+ servers): submission requires a Team/Enterprise org; remote servers only;
  HTTPS + streamable HTTP; tool `title` + behavior annotations mandatory; OAuth 2.0
  for authenticated services (no-auth allowed); privacy policy mandatory
  ([submission docs](https://claude.com/docs/connectors/building/submission)).

## 5. FastMCP

- **Owned by PrefectHQ** now ([repo](https://github.com/PrefectHQ/fastmcp)); still
  the dominant Python framework.
- **FastMCP 3.0 GA 2026-02-18** ([announcement](https://jlowin.dev/blog/fastmcp-3)):
  Components/Providers/Transforms architecture — **ProxyProvider (remote servers)**,
  **FastMCPProvider (composition/mounting)**, OpenAPIProvider, FileSystemProvider,
  **SkillsProvider (serves SKILL.md skills over MCP)**; Namespace prefixing,
  per-session/per-user tool **Visibility** transforms; OAuth providers (GitHub,
  WorkOS, Google, Azure…), per-component auth/scopes, **CIMD support**; component
  versioning, OTel, background tasks. → Aggregation, per-client tool filtering, and
  skills-over-MCP exist **out of the box**; the gateway build is mostly assembly.
- **FastMCP 4.0 in beta** (4.0.0b3, 2026-08-14): native MCP 2026-07-28 (stateless).
  3.x maintained in parallel ([updates](https://gofastmcp.com/updates)).
- **FastMCP Cloud → Prefect Horizon** (Deploy / Registry / Gateway / Agents pillars):
  the commercial hosted competitor shape to palaia — validates the category;
  palaia's differentiators: self-hosted, open, memory-centric
  ([Horizon](https://www.prefect.io/blog/prefect-horizon)).

## 6. Client integration paths (verified)

| Client | Facts (2026-08-22) |
|---|---|
| **claude.ai (web/desktop/mobile/Cowork)** | Custom connectors on **all plans incl. Free (limit 1)**; added in Settings → Connectors; **OAuth optional** (no-auth URLs work); **Anthropic's cloud connects to the server, not the user's device** → endpoint must be publicly reachable even for LAN users ([support](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)). MCP 2026-07-28 rolling out ([blog](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude)) |
| **Claude Desktop** | Local stdio config, **MCPB one-click** (local-only → palaia ships a proxy bundle), in-app directory; renders MCP Apps |
| **Claude Code** | `claude mcp add --transport http <name> <url>` (recommended; **SSE deprecated in docs**); project-scope `.mcp.json`; OAuth via `/mcp`; two runtimes (v1/v2, v2 = MCP 2026-07-28); **ToolSearch** dynamic tool discovery on by default; **channels**: an MCP server declaring `claude/channel` can push external events into sessions ([docs](https://code.claude.com/docs/en/mcp)) — direct precedent for the messenger |
| **Agent Skills** | SKILL.md folders; **open standard [agentskills.io](https://agentskills.io)**, community-governed, **~40+ adopters incl. Claude, ChatGPT & Codex, Gemini CLI, Copilot, Cursor**; distribution via `.claude/skills`, plugins/marketplaces, claude.ai capabilities + skills directory; **Skills API GA on the Claude API (2026-08-20)** |
| **ChatGPT** | Custom MCP via **developer mode** (web; Plus/Pro/Business/Enterprise/Edu); **write-capable custom connectors gated to Business/Enterprise/Edu** — Plus/Pro read/fetch-oriented (partially unverified, official help pages block fetching); July 2026: **"plugins"** = skills + MCP server + optional UI in one directory shared by ChatGPT & Codex ([concepts](https://developers.openai.com/plugins/concepts/plugins)) |
| **Codex (CLI/IDE/desktop)** | `codex mcp add`; `~/.codex/config.toml` `[mcp_servers.*]` — stdio **and streamable HTTP** (`url`, bearer env, headers); **OAuth via `codex mcp login` with CIMD + DCR**; per-server tool enable/disable + approval modes; desktop app, CLI and IDE extension share the config ([docs](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)) |
| **Antigravity / Gemini CLI** | Antigravity 2.0 IDE + `agy` CLI + SDK share `~/.gemini/config/mcp_config.json` (third-party-sourced); Gemini CLI: `mcpServers` in settings.json + extensions bundling MCP servers; supports Agent Skills ([docs](https://geminicli.com/docs/tools/mcp-server/)) |
| **Grok (xAI)** | Connectors for all Grok users incl. **bring-your-own custom MCP servers** (OAuth-based), web/iOS/Android; API-side Remote MCP Tools ([docs](https://docs.x.ai/grok/connectors)) |
| **Local frontends** | LM Studio: native MCP host (mcp.json, Claude-Desktop-compatible); Ollama: no native client — via frontends; **Open WebUI** integrates MCP through its MCPO proxy; llama.cpp web UI merged an MCP client 2026-03 (third-party) |

**Agent Plugins open standard (2026-08-06):** vendor-neutral packaging of Agent
Skills + MCP server configs (`plugin.json`, schema 1.0.0); TSC: Amazon,
Cursor/Anysphere, Microsoft, OpenAI, Vercel ([spec](https://agent-plugins.org/specification)).
Works across ChatGPT, Codex, Cursor, Copilot, Kiro, VS Code. palaia's marketplace
should treat this as a first-class artifact type alongside MCP servers, MCPB and
skills.

## 7. Anthropic news timeline (Dec 2025 – Aug 2026)

- 2025-12-09 — MCP donated to the Agentic AI Foundation (Linux Foundation)
- 2025-12-18 — Agent Skills published as open standard + claude.ai skills directory (third-party-dated)
- Jan 2026 — **Claude Cowork** launched; GA 2026-04-09 (third-party-dated) + Managed Agents beta
- 2026-06-30 — Claude Sonnet 5; 2026-07-24 — Claude Opus 5
- 2026-07-07 — Cowork on mobile & web (remote sessions, scheduled tasks)
- 2026-07-28 — "Bringing MCP 2026-07-28 to Claude" (stateless, extensions, 950+ directory servers)
- Aug 2026 — Claude Code on own compute (08-06); Chrome side panel → Cowork (08-12); **Skills API + Files API GA** (08-20)

## 8. Self-hosted app-store channels

| Channel | Listing model |
|---|---|
| **Umbrel** | PR into [getumbrel/umbrel-apps](https://github.com/getumbrel/umbrel-apps) (`umbrel-app.yml` + compose); or self-maintained Community App Store added by URL |
| **CasaOS** | PR to [CasaOS-AppStore](https://github.com/IceWhaleTech/CasaOS-AppStore) (compose + x-casaos metadata); third-party stores by URL |
| **Runtipi** | Official repo closed for new apps — publish an **own custom app store** users add by URL ([docs](https://runtipi.io/docs/guides/create-your-own-app-store)) |
| **TrueNAS** | Community submissions via [truenas/apps](https://github.com/truenas/apps) (compose-based) |
| **Home Assistant** | Add-on ("Apps" since 2026) model: container + `config.yaml`, community repositories by URL — the best architectural reference for palaia's own store ([docs](https://developers.home-assistant.io/docs/add-ons)) |

## 9. Key implications for palaia v3

1. **Target MCP 2026-07-28, stateless, from day one** — implement `server/discover`,
   MRTR, `_meta` negotiation; keep a 2025-11-25/2025-06-18 handshake shim for older
   clients; expose streamable HTTP only (SSE deprecated; WS only for Claude Code
   channels).
2. **Auth:** OAuth 2.1 resource server with RFC 9728 metadata + OIDC discovery;
   **CIMD first, DCR only as legacy fallback** (deprecated in current spec).
3. **One public endpoint is confirmed viable across every target client** — but
   claude.ai/ChatGPT connect **from vendor clouds**, so public reachability
   (tunnel/edge) is a *requirement* for those clients, not a remote-access nicety.
4. **Don't build on Sampling/Roots/Logging** (deprecated). Use the official **Tasks
   extension** for long-running hub operations and messenger async semantics; MRTR
   killed server-initiated push, so the messenger is polling/tasks/webhooks +
   client-specific channels (Claude Code `claude/channel`).
5. **Marketplace = official registry mirror (frozen v0.1 API) + the trust/curation
   layer the registry deliberately lacks** + artifact types: remote MCP servers,
   MCPB (signed, local proxy pattern), Agent Skills, Agent Plugins 1.0.
6. **Ship palaia panels into the chat clients via MCP Apps** (claude.ai, Claude
   Desktop, ChatGPT, VS Code, Goose…).
7. **FastMCP 3.x is the right gateway base** (proxying, mounting, namespacing,
   per-user visibility, per-component auth, SkillsProvider); adopt 4.x when stable.
   **Prefect Horizon** is the commercial competitor shape — palaia differentiates:
   self-hosted, open, memory-centric.
8. **No MCP-standard memory primitive exists** — cross-provider shared memory remains
   palaia's core differentiator; expose it as plain MCP tools/resources.
9. **Distribution:** PR-based listings (Umbrel, CasaOS, TrueNAS), own Runtipi store,
   Anthropic directory (needs Team/Enterprise org + privacy policy + annotations),
   OpenAI plugin directory.

## Unverified / third-party-only items

Claude Desktop MCPB signature *enforcement*; exact ChatGPT Plus/Pro write
restrictions; Anthropic membership in the Agent Plugins TSC; llama.cpp MCP merge
date; launch dates for Grok BYO-MCP (2026-05-06), ChatGPT plugins (2026-07-09),
skills directory (2025-12-18), Cowork GA (2026-04-09).
