# Fonts

Lume ships three typographic registers, each from a different family:

| Register | Family | License | Use |
|---|---|---|---|
| Structural | **Geist** (Vercel × Basement, 2023) | MIT | UI labels, headings, buttons, form fields, the chrome |
| Prose | **Source Serif 4** (Adobe) | OFL | Agent narration, analysis, multi-sentence explanation |
| Data / Code | **Geist Mono** (Vercel × Basement, 2023) | MIT | Numeric cells, code blocks, file paths, ticket IDs |

## Current state — Google Fonts CDN

`colors_and_type.css` imports the families from Google Fonts:

```css
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap');
```

Each is variable-axis where Google Fonts exposes it:
- Geist — weight 400/500/600
- Geist Mono — weight 400/500/600 (Lume uses 450 for `type.mono.data`; falls back to 500 from the CDN)
- Source Serif 4 — weight 400/600 + optical-size axis 8–60

## Production substitution

For production, swap the CDN import for locally-hosted variable WOFF2 files in this folder:

- `Geist-Variable.woff2` — single file, weight axis 100–900
- `GeistMono-Variable.woff2` — single file, weight axis 100–900
- `SourceSerif4-Variable.woff2` — single file, weight + opsz axes

Sources:
- Geist + Geist Mono — https://github.com/vercel/geist-font/releases
- Source Serif 4 — https://github.com/adobe-fonts/source-serif/releases

Target payload subsetted (Latin + numerics + ligatures): ~280–360 KB across all three.

Loading order: preload Geist for FCP, defer Geist Mono and Source Serif 4. `font-display: swap` everywhere.

## Substitution flag

**No local font files are bundled in this design system.** The CDN import is the live source. If you need the design system to work offline (e.g. an Electron build), download the variable WOFF2 from the sources above and swap the `@import` in `colors_and_type.css` for `@font-face` rules.

If a renderer can't load the chosen family, the fallback chain in `colors_and_type.css` is platform-strongest:

```
--font-sans:  'Geist',           system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-mono:  'Geist Mono',      ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
--font-serif: 'Source Serif 4',  Charter, 'Iowan Old Style', Georgia, serif;
```

macOS gets Charter for serif fallback; Windows gets Georgia; sans + mono fall through to native system fonts.
