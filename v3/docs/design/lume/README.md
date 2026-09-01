# Lume — palaia v3's design system

**Provenance:** Lume is the owner's design system, authored in Claude Design
(project "Lume Design System", built for Omadia UI, public). First exported to
this repo on 2026-08-22 (token core); completed on 2026-09-01 with the full
upstream export ("Lume Export" artifact — previews, concept docs, the Omadia
canvas UI kit, agent skill). The design project remains the upstream source of
truth; this copy is the normative reference for palaia implementation work.
See [IMPORT-NOTES.md](IMPORT-NOTES.md) for exactly what the 2026-09-01 import
contains and what it deliberately leaves out.

**Layout here:**
- `colors_and_type.css` — the token single source of truth (color, type,
  spacing, radii, elevation, motion, the v0.4 Signal accent) plus the Lume
  material recipes (surface gradients, directional borders, glow, focus ring,
  selection halo, skeleton). Bound byte-identically into the dashboard at
  `v3/web/src/styles/tokens.css` (SPEC-109) — a lint
  (`v3/web/scripts/lint-tokens.mjs`) keeps the two from drifting.
- `styles.css` — upstream's demo stylesheet (reference only; the dashboard's
  component layer is `v3/web/src/styles/components.css`).
- `docs/visual-spec.md` — the written visual specification (v0.4), upstream's
  native location. `docs/` also carries the Omadia concept, walkthroughs, the
  v0.4 Signal hand-off note, and the spec author's reference HTML renders.
- `preview/` — per-token/per-component reference cards (static HTML).
- `ui_kits/omadia-canvas/` — high-fidelity React recreation of the Omadia
  canvas (primitives + dashboard/wizard/workspace/empty scenes). Reference
  for layout and component behavior, **not** code palaia imports.
- `assets/`, `fonts/` — iconography (standard Lucide; exact path data in
  `ui_kits/omadia-canvas/lucide-paths.js`) and font strategy READMEs.
- `SKILL.md` — the agent-facing skill from the design project. It says "read
  the README.md within this skill": upstream's own README is preserved
  verbatim as [UPSTREAM-README.md](UPSTREAM-README.md) (its index and design
  language); this file adds palaia's bindings on top.

**palaia-specific decisions (owner, 2026-08-22):**
1. **Default accent: `atelier`** (studio warmth). Lagoon and Petrol remain
   available — the accent slot is user-switchable by design. (Upstream's own
   default is Lagoon.)
2. Theme switching: Lume's `[data-mode="light|dark"]` attribute is the
   mechanism; palaia defaults it to the system preference with a manual
   override (dashboard) — MCP Apps receive the host's theme.
3. Fonts (Geist / Geist Mono / Source Serif 4) are **self-hosted** in the
   dashboard build and **bundled** in MCP Apps (their iframe CSP blocks font
   CDNs). The Google Fonts `@import` in `colors_and_type.css` is the design-
   project convenience only — never ship it.
4. The **Signal** rule is binding UX doctrine: at most ONE signal element per
   view, never as surface fill, never as a status pill.

Implementation entry point: SPEC-109 (dashboard shell) lifts these tokens;
the SPEC-005 mockups (PR #207) render them. The dashboard is already bound to
this token set — the 2026-09-01 import changed no token values (verified
byte-identical), it completed the surrounding reference material.
