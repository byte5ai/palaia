# Iconography assets

Lucide SVGs used by the Omadia UI kit and preview cards. Stroke width is 2px (Lucide default at 24×24 viewBox); colour is `currentColor` so they pick up `text.primary` / `text.secondary` / `text.tertiary` based on surrounding context.

Source: [lucide-icons/lucide](https://github.com/lucide-icons/lucide), MIT license. Updates: `npm i -g lucide` and copy fresh SVGs out.

The full Lucide set is also available at runtime via CDN:

```html
<script src="https://unpkg.com/lucide@latest"></script>
<script>lucide.createIcons();</script>
```

`<i data-lucide="search"></i>` is replaced in-place with the SVG.

## Custom icons not yet drawn

The spec permits three editor-specific custom icons. They ship as Lucide stand-ins until the Tier-1 spike draws real ones:

| Custom name | Lucide stand-in |
|---|---|
| `magic-wand` | `wand-sparkles` |
| `brush-pressure` | `brush` |
| `vector-pen-anchor` | `pen-tool` |
