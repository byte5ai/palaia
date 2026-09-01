---
name: lume-design
description: Use this skill to generate well-branded interfaces and assets for Omadia UI (Lume design system), either for production or throwaway prototypes/mocks/etc. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

The system implements **Lume** — light-as-material — for **Omadia UI**, a generative desktop canvas application. The defining trait: every surface is a gradient pair (top + btm), every border is directional, accent renders as both fill *and* glow (two-stop, with a bright white-shifted inner core). Default palette is **Lagoon** (`#1F8FA3`). Typography is three-register: **Geist** (sans, structural) + **Source Serif 4** (serif, prose) + **Geist Mono** (mono, data/code).

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy `colors_and_type.css` and `assets/` out of this folder and create static HTML files for the user to view. Add `<html data-mode="light" data-accent="lagoon">` on the root.

If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

Key files:
- `README.md` — full design language (content tone, visual foundations, iconography, anti-patterns)
- `colors_and_type.css` — every design token, ready to import
- `docs/visual-spec.md` — the normative source spec from the Omadia UI repo
- `docs/visual-spec-preview-lume.html` — visual reference rendered by the spec author
- `ui_kits/omadia-canvas/` — high-fidelity React recreation of core canvas screens
- `preview/` — small per-token cards for the design-system tab

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts _or_ production code, depending on the need. Hard constraints to remember:

1. No logo — `omadia` is muted body text, not a wordmark.
2. No emoji as chrome (agent-content emoji passes through unchanged).
3. No drop shadows on cards. Shadows are reserved for modal-class surfaces.
4. No status-pill cocktails or filled badges. Semantic states are text + 1px border, never block fills.
5. No spinners. Skeletons or the button-in-flight dots are the only loading affordances.
6. No "Welcome!" or branded empty states.
7. The editor exception: `canvas-region`, `timeline`, `vector-path` get **radius 0** and opaque (non-gradient) fills.
