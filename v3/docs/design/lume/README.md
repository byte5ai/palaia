# Lume — palaia v3's design system

**Provenance:** Lume is the owner's design system, authored in Claude Design
(project "Lume Design System", built for Omadia UI, public). Exported to this
repo on 2026-08-22. The design project remains the upstream source of truth;
this copy is the normative reference for palaia implementation work.

**Files here:**
- `colors_and_type.css` — the token single source of truth (color, type,
  spacing, radii, elevation, motion) plus the Lume material recipes
  (surface gradients, directional borders, glow, focus ring, selection halo,
  skeleton).
- `visual-spec.md` — the written visual specification behind the tokens.

**palaia-specific decisions (owner, 2026-08-22):**
1. **Default accent: `atelier`** (studio warmth). Lagoon and Petrol remain
   available — the accent slot is user-switchable by design.
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
the SPEC-005 mockups (PR #207) render them.
