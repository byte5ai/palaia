# Omadia canvas — UI kit

A hi-fidelity React mock of the Omadia UI canvas surface, painted in **Lume** material with the **Lagoon** palette. The kit is a click-through across four of the five composition idioms from the visual spec — the fifth (Norton-Commander) is omitted as it adds no Lume-specific recipe beyond what the dashboard already exercises.

[`index.html`](index.html) — the demo. Use the **demo** picker top-right (or **⌘K** for Spotlight) to switch scenes.

## Status

This is a **prototype**, not production code. Omadia UI is itself concept-phase (no shipping app yet) — see [`docs/omadia-CONCEPT.md`](../../docs/omadia-CONCEPT.md). The kit recreates the visuals defined in [`docs/visual-spec.md`](../../docs/visual-spec.md) for design exploration. There's no real agent, no wire protocol, no canvas state — just the chrome the spec describes.

## Files

| File | What |
|---|---|
| `kit.css` | UI-kit-specific styles on top of `colors_and_type.css` — frame, primitives, scene chrome |
| `lucide-paths.js` | Bundled Lucide SVG paths (generated from `assets/icons/`) |
| `primitives.jsx` | Reusable `Button`, `Pane`, `ListRow`, `Mono`, `Prose`, `StatusDot`, `Skel`, `KPI`, `Toolbar`, `Icon` |
| `frame.jsx` | `CanvasFrame` — traffic lights + top status bar + bottom prompt bar |
| `scene-empty.jsx` | Empty canvas + Spotlight overlay |
| `scene-dashboard.jsx` | Walkthrough 1 — Jira × ERP × HR comparison with highlighted rows and inspector |
| `scene-workspace.jsx` | Walkthrough 2 — Photoshop workspace with tool rail, canvas-region, inspector and layer stack |
| `scene-wizard.jsx` | Walkthrough 3 — sales-proposal wizard with confirmation modal |
| `app.jsx` | Root component, scene switcher, ⌘K shortcut |

## Scenes

1. **empty** — `Canvas ready. ⌘K to start.` The agent is waiting. No chrome.
2. **spotlight** — the Lume showcase moment. Three-stop glow on the input, radial accent-glow on the stage.
3. **dashboard** — KPI strip + agent prose narration + table with highlighted rows + right-side inspector. The dashboard from walkthrough 1, after the agent has materialised + patched the surface five times.
4. **workspace** — Photoshop-class composition. Left tool rail (Lume material, donut glow on the active brush), centre canvas-region (sharp corners, opaque, 2px accent border + outer accent.glow), right inspector + layer stack (Lume material around the editor boundary).
5. **wizard** — proposal wizard at step 3. Donut-glow current step, completed steps filled, tier choice with the focus-ring recipe. Sending opens a confirmation modal — modal pane carries the full `elev.modal` shadow including accent-glow.

## Component coverage

- `text`, `heading`, `container`, `list`, `table`, `tree` (layer-stack), `button`, `input`, `choice` (tier radio), `toggle` (not yet), `image` (canvas mock), `chart` (KPI tile), `form` (wizard form, inspector), `toolbar` (button rows), `menubar` (—), `tabs` (step-bar), `pane` (modal + raised), `status` (StatusDot), `progress` (—), `divider` (—)
- Editor: `media` (—), `canvas-region` (workspace), `timeline` (—), `vector-path` (—)

Gaps are noted with `(—)` — primitives that would belong in a more comprehensive kit but aren't yet implemented. None of them adds a new Lume recipe beyond what the existing primitives show.

## How to extend

The primitives in `primitives.jsx` are intentionally thin. To add a new screen, drop a `scene-*.jsx` file that exports a top-level component to `window`, and wire it into `app.jsx`. Use the Lume CSS classes from `kit.css` (`.pane`, `.pane-raised`, `.btn`, `.input`, `.list-row.selected`, etc.) rather than inventing new ones — the directional borders and glow recipes are subtle, and the existing classes encode the spec faithfully.

## Known limitations

- No real keyboard navigation beyond ⌘K and Esc.
- No real `surface_patch` animation flow — the `condense` CSS class runs once per scene mount, simulating arrival.
- No dark mode toggle in the demo. The tokens support it (set `data-mode="dark"` on `<html>`); the kit just doesn't expose a switch.
- `media`, `timeline`, `vector-path` primitives aren't drawn.
- Designed at 1440 × 900; smaller viewports scroll the canvas vertically.
