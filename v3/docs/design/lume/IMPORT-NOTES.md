# Lume full-export import — 2026-09-01

Imported from the owner's Claude Design project ("Lume Export" artifact,
54 of the project's ~100 files — the text core). Canonical upstream is the
Claude Design project; this directory is the in-repo reference palaia
implementation work builds against.

**Key finding:** the export's `colors_and_type.css` and `styles.css` are
**byte-identical** to what this repo already carried from the 2026-08-22
import (both already at spec v0.4 including the Signal accent), and the
dashboard (`v3/web`) is already bound to those tokens with self-hosted fonts
(SPEC-109). This import therefore changed no token values and required no
dashboard changes — it completed the surrounding reference material.

**Added by this import:**
- `docs/` — Omadia concept, walkthroughs, v0.4 Signal hand-off note, the spec
  author's reference HTML renders (`visual-spec-preview-*.html`,
  `spec-preview-signal-block.html`).
- `preview/` — per-token and per-component reference cards (static HTML).
- `ui_kits/omadia-canvas/` — React recreation of the Omadia canvas:
  `primitives.jsx` + dashboard/wizard/workspace/empty scenes. Reference
  material, not imported code.
- `SKILL.md`, `UPSTREAM-README.md` (upstream's own README, verbatim),
  `fonts/README.md`, `assets/icons/README.md`.

**Moved by this import (deduplication):**
- Root `visual-spec.md` → `docs/visual-spec.md` (upstream's native location;
  the two were identical).
- Root `kit.css` removed — identical to `ui_kits/omadia-canvas/kit.css`,
  and nothing referenced the root copy.

**Not in the export (known, deliberate):**
- `assets/icons/*.svg` — standard Lucide icons; `ui_kits/omadia-canvas/
  lucide-paths.js` carries the exact path data, and the icons README lists
  the set.
- `_ds_bundle.js`, `_ds_manifest.json`, `_adherence.oxlintrc.json` — the
  design project's Design-System-pane machinery, not needed for adoption.
- `screenshots/` — visual reference only.
- Font binaries — the tokens reference Geist / Geist Mono / Source Serif 4
  via the Google Fonts CDN; the dashboard's CSP (`default-src 'self'`)
  forbids that, so palaia self-hosts the fonts
  (`v3/web/src/assets/fonts/`, decision 3 in [README.md](README.md)).
