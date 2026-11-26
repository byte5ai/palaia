# Self-hosted fonts

The dashboard ships its two fonts as WOFF2 files so it never requests
`fonts.googleapis.com` or any other font CDN.

- **Inter** — the only UI and body font. Variable weight (100–900), latin +
  latin-ext subsets, normal and italic. SIL Open Font License 1.1, © The Inter
  Project Authors (`LICENSE-inter.txt`).
- **Days One** — the wordmark only. One weight, latin subset. SIL Open Font
  License 1.1, © Jovanny Lemonad, Reserved Font Name "Days One"
  (`LICENSE-days-one.txt`).

The Inter files and their licence text come from the npm package
`@fontsource-variable/inter` 5.3.0 (`files/inter-<subset>-wght-<style>.woff2`,
renamed to `inter-<style>-<subset>.woff2`; `LICENSE`), which repackages the
Google Fonts subsets of rsms/inter. The docs site carries the same files under
`v3/site/docs/src/fonts/`, plus the Cyrillic and Vietnamese subsets, and the
in-chat panels embed the latin file, so every surface renders the same face.
Days One is byte-identical to the file the palaia website self-hosts. Code uses
the system monospace stack; no mono font is bundled.

Loaded by `../styles/fonts.css`. To refresh Inter, take the files from a newer
version of the same package and copy the `unicode-range` values from its
`wght.css` and `wght-italic.css`.
