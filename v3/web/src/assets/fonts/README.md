# Self-hosted fonts

The dashboard ships its two fonts as WOFF2 files so it never requests
`fonts.googleapis.com` or any other font CDN.

- **Nunito Sans** — the only UI and body font. Variable weight (200–1000),
  latin + latin-ext subsets, normal and italic. SIL Open Font License 1.1,
  © The Nunito Sans Project Authors (`LICENSE-nunito-sans.txt`).
- **Days One** — the wordmark only. One weight, latin subset. SIL Open Font
  License 1.1, © Jovanny Lemonad, Reserved Font Name "Days One"
  (`LICENSE-days-one.txt`).

The files are byte-identical to the ones the palaia website self-hosts
(`public/fonts/` in the palaia-homepage repository) and the docs site carries
under `v3/site/docs/src/fonts/`, so all three surfaces render the same faces.
The licence texts are the upstream `OFL.txt` files from the google/fonts
repository. Code uses the system monospace stack; no mono font is bundled.

Loaded by `../styles/fonts.css`. To refresh a font, copy the matching file from
the website repository and keep the `unicode-range` in `fonts.css` in step with
the website's `app/globals.css`.
