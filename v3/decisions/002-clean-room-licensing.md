# ADR-002: Adopt concepts, never code — licensing guardrail for v3

- **Status:** Proposed (final license choice pending — see MASTERPLAN open decisions)
- **Date:** 2026-08-22
- **Deciders:** cwendler

## Context

palaia v3 deliberately combines ideas from three sources: palaia v2 (MIT, our own),
[basic-memory](https://github.com/basicmachines-co/basic-memory) (**AGPL-3.0** with
CLA), and the private mcp-hub prototype (our own, built as a wrapper around
basic-memory). palaia v2 is MIT; the owner has larger plans for v3, so license
flexibility matters.

AGPL-3.0 is a strong copyleft license with a network clause: copying basic-memory
code into palaia — or linking it into the same process — would force the combined
work under AGPL-3.0 and bind all future distribution and hosted use.

## Decision

1. **No code, schema, or verbatim prompt/doc text is copied from basic-memory into
   palaia v3.** Its concepts (Markdown-first knowledge graph, entities/observations/
   relations, Obsidian compatibility) are reimplemented clean-room. Ideas are not
   copyrightable; expression is.
2. **No runtime dependency on basic-memory** in the core. Interop is limited to data
   formats: v3 ships an *importer* for basic-memory vaults (reading a user's own
   Markdown files is not a license event).
3. Code and concepts from **palaia v2** (MIT, byte5-owned) and **mcp-hub**
   (byte5/owner-authored) may be reused freely.
4. v3's own license is a pending decision: MIT (v2 continuity) vs. Apache-2.0
   (patent grant; the Home Assistant choice). Both keep the options open that AGPL
   would close. Recommendation in MASTERPLAN: Apache-2.0 for the platform.

## Alternatives considered

- **Build on basic-memory as a dependency** — fastest start, but AGPL propagation
  constrains commercial options and add-on ecosystem; also their CLA/dual-licensing
  asymmetry benefits their cloud, not ours.
- **Relicense palaia v3 as AGPL** — maximally protective against cloud free-riders,
  but conflicts with a permissive add-on ecosystem and with byte5's plans.

## Consequences

- Memory engine is written from scratch (that was the plan anyway — v3 is a rewrite).
- Contributors must be told (CONTRIBUTING for v3) never to port basic-memory code.
- An import path for basic-memory users becomes a feature, not a dependency.
