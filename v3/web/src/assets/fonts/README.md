# Self-hosted fonts

Geist, Geist Mono and Source Serif 4 — variable-weight WOFF2 files, latin +
latin-ext subsets, normal and italic. Extracted from the `@fontsource-variable`
npm packages (which repackage the upstream OFL font sources) and committed here
so the dashboard build never requests `fonts.googleapis.com` or any other font
CDN, per `v3/docs/design/lume/README.md` decision 3 and this SPEC's fonts note.

- **Geist** / **Geist Mono** — SIL Open Font License 1.1, © The Geist Project
  Authors (`LICENSE-geist.txt`, `LICENSE-geist-mono.txt`).
- **Source Serif 4** — SIL Open Font License 1.1, © Google Inc. / Source Serif
  4 Project Authors (`LICENSE-source-serif-4.txt`).

Loaded by `../styles/fonts.css` via `@font-face`, matching the weight ranges
and unicode-range subsets from the upstream packages. To refresh a font,
reinstall the matching `@fontsource-variable/<name>` package temporarily,
re-copy the files under `files/` for the `wght` axis (latin + latin-ext,
normal + italic), then remove the npm dependency again — the files, not the
package, are what ships.
