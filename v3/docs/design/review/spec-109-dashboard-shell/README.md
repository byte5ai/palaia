# SPEC-109 visual parity — screenshot evidence

Chromium (Playwright) screenshots of the real dashboard build served by
`palaia-hub` (`npm run build` output, `PALAIA_WEB_DIST` pointed at it),
next to the SPEC-005 reference mockup (`v3/docs/design/mockups/home.html`).
The feature content in the mockup (tiles, activity feed, tool surface) is
SPEC-110's; this SPEC's own content is the live health card. What is
being compared is the shell: sidebar, brand, nav groups and their quiet
selection treatment, topbar, card chrome, tokens, and both themes.

| File | What it shows |
|---|---|
| `shell-1280-light.png` | The built shell at 1280×800, light. |
| `shell-1280-dark.png` | The built shell at 1280×800, `prefers-color-scheme: dark`. |
| `reference-mockup-home-light.png` | The SPEC-005 mockup, same viewport, light — the parity target. |
| `reference-mockup-home-dark.png` | Same mockup, dark. |
| `shell-768.png` | The shell at the 768px breakpoint — icon rail. |
| `shell-360.png` | The shell at the 360px breakpoint — horizontal top nav. |

Reproduce: `npm run build` in `v3/web`, then run the hub with
`PALAIA_WEB_DIST` pointed at `v3/web/dist` and screenshot `/` at each
viewport/color-scheme with Playwright.
