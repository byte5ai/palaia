# Omadia UI

> A persistent canvas surface for the [Omadia Agentic OS](https://github.com/byte5ai/omadia). The agent synthesises UI live the way it synthesises prose today — on a blank canvas, in the layout that fits the user's task and preferences in the moment.

**Status — concept phase complete, pre-implementation.** No code yet. The architecture, primitive vocabulary, wire protocol, security surface, and forward-compatibility constraints are defined in [`CONCEPT.md`](CONCEPT.md).

## What is this

Chat is the "DOS era" of LLM interaction: powerful but linear and text-only. Omadia UI is the next layer — a desktop application where the agent **materialises live UI** (text, tables, panes, media, editor regions) as it orchestrates a request across source systems (Jira, ERP, HR, …). Persistent, multi-turn, stateful, own surface next to the chat channels.

Designed to be ready for the next 1–2 LLM generations without architectural rework. Editor-class workloads (Photoshop-, DaVinci-, Logic-Pro-style) are first-class from v1; the bottleneck should be the model, not the architecture.

## Concept summary

- **24 primitives** as the wire-format vocabulary (`omadia-canvas-protocol/1.0`), composable into any era of UI from TUI-list to Photoshop workspace, all rendered in a single Omadia theme.
- **Three-tier architecture** split across **Client × Server**:
  - **Tier 1** (deterministic, no LLM, instant): Canvas Host App (client) + `omadia-ui-channel` (server-side channel plugin). Local operations catalog for editor-grade direct manipulation.
  - **Tier 2** (small/fast LLM, sub-second): `omadia-ui-orchestrator` extension plugin. UI Skill, composition, style inference, action routing.
  - **Tier 3** (heavy LLM + slow tools): existing omadia plugins. Data, AI services, long-running operations.
- See [`docs/architecture-3tier.svg`](docs/architecture-3tier.svg) for the diagram.
- **Forward-compatible** for shared canvases (v2+ multi-user collaboration) without identity/state/wire-format refactor.

## Documents

| File | Purpose |
|---|---|
| [`CONCEPT.md`](CONCEPT.md) | Architecture, primitives, protocol, security, identity, SDK extension plan |
| [`docs/architecture-3tier.svg`](docs/architecture-3tier.svg) | Visual three-tier architecture |
| [`docs/walkthroughs.md`](docs/walkthroughs.md) | Use-case walkthroughs — multi-source comparison + editor micro-task |
| [`docs/tech-stack.md`](docs/tech-stack.md) | Tech-stack decision for the Tier 1 Host App — Electron, with reasoning and spike plan |
| `docs/protocol/1.0.md` | Protocol specification (written during spike — TBD) |

## Relationship to omadia core

Omadia UI rides on [`byte5ai/omadia`](https://github.com/byte5ai/omadia). The concept defines a set of additive SDK extensions to the core (channel manifest fields, surface event family, sentinel origin metadata, `tenantId` on `IncomingTurn`, …) — see CONCEPT.md § "SDK changes" for the full list. Each extension is planned as a separate mergeable PR against `byte5ai/omadia` main.

One capability is marked **depends-on-core** (not part of this repo): `crossChannelConversationMemory@1` — a durable, user-scoped conversation memory across channels, needed so a user can start research in Telegram and continue seamlessly in Omadia UI.

## Status

| Phase | State |
|---|---|
| Concept | Complete (v0.7, three Codex review rounds, implementation-ready) |
| Tech stack decision | **Electron** — see [`docs/tech-stack.md`](docs/tech-stack.md) |
| Implementation plan | Open |
| Spike | Skeleton drafted in [`docs/tech-stack.md`](docs/tech-stack.md); pending kickoff |

## License

MIT — Copyright © 2026 byte5 GmbH.

## Maintainership

Maintained by [byte5 GmbH](https://byte5.de) under the GitHub organisation [`byte5ai`](https://github.com/byte5ai).
