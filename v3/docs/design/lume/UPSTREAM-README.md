# Lume — Design System for Omadia UI

> **Material: light-as-material.** UI is not drawn — it is condensed out of light. The agent's attention is visible as accent-tinted illumination on the surface it touches. Default palette: **Lagoon**. Typography: **Geist + Source Serif 4 + Geist Mono**.

This is the design system for [Omadia UI](https://github.com/byte5ai/omadia-ui) — a generative desktop canvas application where an agent materialises UI live, in the layout that fits the user's task. The agent renders 24 primitive types into one consistent material (Lume) across any era of UI from TUI-list to Photoshop workspace.

## Source materials

- **Repository** — [`byte5ai/omadia-ui`](https://github.com/byte5ai/omadia-ui) (concept phase complete, pre-implementation)
- **Visual specification** — [`docs/visual-spec.md`](docs/visual-spec.md) (v0.3, the normative source)
- **Concept** — [`docs/omadia-CONCEPT.md`](docs/omadia-CONCEPT.md) (architecture, primitives, protocol)
- **Walkthroughs** — [`docs/walkthroughs.md`](docs/walkthroughs.md) (use-case scenarios)
- **Visual reference HTML** — [`docs/visual-spec-preview-lume.html`](docs/visual-spec-preview-lume.html) — the reference render from the spec author
- **Type reference HTML** — [`docs/visual-spec-preview-type.html`](docs/visual-spec-preview-type.html) — type-architecture comparison

These are imported into this project for offline use; the reader does not need direct GitHub access to use this design system.

---

## Index

| Path | What |
|---|---|
| [`colors_and_type.css`](colors_and_type.css) | All design tokens — colors, type, spacing, radii, shadows, motion. Single source of truth. |
| [`fonts/README.md`](fonts/README.md) | Font registers, loading strategy, production substitution plan. |
| [`preview/`](preview/) | Per-token cards rendered for the Design System tab. |
| [`assets/`](assets/) | Brand-text + iconography (no logo asset — see Iconography). |
| [`ui_kits/omadia-canvas/`](ui_kits/omadia-canvas/) | High-fidelity React recreation of the Omadia canvas. |
| [`docs/`](docs/) | Imported source spec, walkthroughs and reference HTML. |
| [`SKILL.md`](SKILL.md) | Skill entry — read first when used inside Claude Code. |

---

## 1. Context — what Omadia UI is

Omadia UI is the **canvas surface** of the [Omadia Agentic OS](https://github.com/byte5ai/omadia). Chat is the "DOS era" of LLM interaction — powerful but linear and text-only. Omadia UI is the next layer: a desktop application where the agent **materialises live UI** (text, tables, panes, media, editor regions) as it orchestrates a request across source systems (Jira, ERP, HR, …).

The agent speaks a wire-format vocabulary of **24 primitives** — composable into any era of UI from a Norton-Commander-style two-pane file manager to a Photoshop-style workspace — all rendered in one single material identity.

### The four forces of Lume

Everything else is composition of these:

1. **Surface luminosity** — every surface is a 180° linear gradient from a slightly lit top to a slightly settled bottom (~1.5% L delta). Imperceptible per-surface; cumulative across a screen the surfaces feel *illuminated*, not printed.
2. **Accent as illumination** — the single accent token splits into *fill* (the hard form, on buttons and indicators) and *glow* (the soft form, as halos at selection and focus). Glow has three layers: outer accent-tinted corona, stronger mid-ring, and a bright white-shifted inner core.
3. **Directional borders** — 1px borders use a lighter top color and a slightly stronger bottom + side color, so every edge reads as catching light from above. Raised surfaces carry a 1px inset white top-edge highlight (~6% alpha).
4. **Soft corners with editor exception** — radius scale 6/8/10/12 px for all containers; **radius 0** for `canvas-region`, `timeline`, `vector-path`. The hardness is intentional and marks the Tier-1 boundary where the agent's chrome ends and the user's raw work begins.

### Lume is NOT

- Refraction, real-time blur as primary chrome, frosted glass, glassmorphism.
- Specular highlights on every surface.
- Multiple accents at once. There is one accent slot; three palettes bind to it (Lagoon default + Petrol + Atelier).
- A Settings/Preferences UI. Palette is set conversationally.

---

## 2. Content fundamentals

### Tone

Omadia speaks like a **calm utility**, not a brand voice. Sentences are short, declarative, and load-bearing — every word has a job. The product is named in lowercase (`omadia`) and never given a wordmark treatment. There is no enthusiasm, no exclamation, no "Welcome!" Status messages and prompts are written as if the agent already has a thought and is sharing it, not as if the agent is performing for an audience.

**Reference voice — the canonical empty state:**

> `Canvas ready. ⌘K to start.`

That's the entire message. No illustration, no headline, no body, no help link.

**Reference voice — the prompt bar placeholder:**

> "Ask anything. The canvas will answer."

Eight words. The serif (Source Serif 4) signals that this is *prose addressed to the user*, not chrome.

**Reference voice — the top status bar:**

> `omadia    ·    10 connectors live · 2 resolving · Mon · 18 May · 09:42`

The brand sits in `text.secondary`, never a wordmark. The connector + clock indicators sit in `text.tertiary`. Separators are middle-dots, not pipes.

### Casing

- **Sentence case** for everything user-facing — buttons, menu items, headings, labels. Never title case.
- **Lowercase** for the product name (`omadia`).
- **Uppercase eyebrows** are reserved for the rare `caption.strong` token (e.g. small section labels above a chart). Letter-spacing +0.02em.
- **Mono** for identifiers: ticket IDs (`OPS-1284`), file paths (`/usr/local/bin`), version strings (`v0.3.2`), keyboard hints (`⌘K`, `⌘↩`).

### Pronouns

- **You** addresses the user. "Send PDF?" never "Send PDF to **the user**?"
- The agent does **not** refer to itself as "I". The canvas is the agent's surface — the agent's voice is *the materialising of UI itself*, not a chat persona. When narrating, use neuter constructions: "Three people are under budget — Anna, Bernd, Cara." Not "I noticed three people…".
- **Never** "we" — Omadia is not a company addressing you, it's a tool.

### Three registers express three speech acts

| Register | Family | What it signals |
|---|---|---|
| **Structural** (Geist) | sans | UI chrome — labels, buttons, menu items, table contents, status text. The default. |
| **Prose** (Source Serif 4) | serif | Multi-sentence narration, analysis, summary. The serif is the *editorial voice* — "this is something for you to read, not click". |
| **Mono** (Geist Mono) | mono | Identifiers, numerics where alignment matters, code, TUI-style data grids. The mono is *machine-truth* — "this is exact". |

The shift between registers carries meaning. A confirmation modal looks like this:

```
[heading.2 / Geist]   Send PDF to project-leads@byte5.de?
[prose / Source Serif] This email cannot be unsent. The
                      attached PDF is the version at 09:42.
[toolbar]             Cancel    Send
```

The heading is structural — it's *the question being asked*. The body is prose — it's *the thing the user needs to read, weigh, understand*. The buttons return to structural — they're chrome again.

### Emoji

**No.** Implementer-chrome emoji is forbidden. Agent-content emoji passes through unmodified (if the source data contains an emoji, the agent renders it as data). But the chrome never carries decorative emoji — no 🚀 in empty states, no ✓ in success messages (use text or the appropriate Lucide icon).

### What never appears in copy

- **"Welcome to Omadia"** or any branded greeting.
- **Exclamation marks** in chrome strings.
- **Help/learn-more links** in empty states. The empty state is the agent waiting.
- **Toasts** ("Saved!", "Item deleted"). Errors live in the tree, in context.
- **Loading spinners with "Loading…" text** — use skeletons.
- **"Are you sure?"** Confirmation modals state the *consequence*: "This email cannot be unsent."

---

## 3. Visual foundations

### Colors

Defined in [`colors_and_type.css`](colors_and_type.css). All surface tokens are **pairs** (`-top` + `-btm`), consumed as 180° linear gradients. Borders are **directional** (`-top` lighter, `-btm` stronger). Accent is one slot, three palettes — see §4.

| Use | Token |
|---|---|
| Workspace background | `--bg-canvas-top` → `--bg-canvas-btm` |
| Primary content surface | `--bg-surface-top` → `--bg-surface-btm` |
| Cards, popovers, inputs | `--bg-surface-raised-top` → `--bg-surface-raised-btm` + inset top-edge highlight |
| Code blocks, hover, secondary | `--bg-surface-sunken-top` → `--bg-surface-sunken-btm` |
| Modal interior | `--bg-modal-surface-*` |
| Modal scrim | `--bg-modal-overlay` (accent-tinted dark, never pure black) |
| Primary text | `--text-primary` `#1A1D20` |
| Secondary | `--text-secondary` `#5A6068` — labels, captions, the `omadia` brand text |
| Tertiary | `--text-tertiary` `#8A9098` — hints, placeholders, clock & status indicators |
| Disabled | `--text-disabled` `#B8BDC2` |
| On accent fill | `--text-on-accent` `#FFFFFF` |

Semantic state colors are **text-only** — never filled pills, never block fills. `--state-error-fg`, `--state-success-fg`, `--state-warning-fg`. Errors carry a 1px `--state-error-edge` border on the affected primitive; nothing more.

#### Signal — the loud accent

Lume's accent is deliberately quiet ("subtle enough to recede"). For the rare moment something must genuinely *pop* — a hero CTA, a critically-important element or text, and especially non-UI surfaces (websites, videos) — the system ships one **palette-independent** loud accent: **Signal**, a vivid magenta-pink (`--signal-fill` `#D6177A` light · `#FF5FA8` dark).

It is one universal colour, not one-per-palette: its hue (≈340°) sits in the only open gap (270–350°) and pops against all three accents — complement of Lagoon/Petrol, split-complement of Atelier — while staying clear of the red error token. Same seven-sub-token shape as an accent (`--signal-fill` / `-hover` / `-active` / `-subtle` / `-glow` / `-glow-strong` / `-glow-core`). It does **not** rebind when the user switches Lagoon/Petrol/Atelier.

**Rules — Signal is loud by design, so discipline is the whole point:**
- **At most one signal element per view.** Two signals cancel each other out.
- Use for: the single most important CTA, a critically-important element/text, brand pop on web/video.
- Destructive actions keep their dedicated treatment (`state.error` text + 1px edge). Signal may elevate a high-stakes *confirm* button (e.g. the modal "Send"), not replace error semantics.
- Never a large surface fill, never a status pill, never decorative.
- `.btn-signal` (in `preview/_card.css` and the kit) is the ready-made button recipe.

### Type

Three registers — see [Content fundamentals](#2-content-fundamentals) for *when* to use each.

| Token | Size / lh | Weight | Family |
|---|---|---|---|
| `display` | 32 / 40 | 600 | Geist |
| `h1` | 24 / 32 | 600 | Geist |
| `h2` | 20 / 28 | 600 | Geist |
| `h3` | 16 / 24 | 600 | Geist |
| `body` | 14 / 22 | 400 | Geist |
| `body.sm` | 13 / 20 | 400 | Geist |
| `caption` | 12 / 18 | 400 | Geist |
| `prose` | 16 / 26 | 400 | Source Serif 4 |
| `mono` | 13 / 20 | 450 | Geist Mono |
| `mono.sm` | 12 / 18 | 450 | Geist Mono |

Weights used: 400, 450 (mono only), 500 (optional emphasis), 600. **No 300, no 700+** — the spec is deliberate about not using the extreme weights.

### Spacing

4pt base scale: `--space-1` 4px · `--space-2` 8px · `--space-3` 12px · `--space-4` 16px · `--space-5` 20px · `--space-6` 24px · `--space-8` 32px · `--space-10` 40px · `--space-12` 48px · `--space-16` 64px.

Default block stack-gap is `--space-3` (12px). Container padding is `--space-4` or `--space-5`. Canvas padding is `--space-8` (32px).

### Backgrounds

**No hand-drawn illustrations. No repeating patterns. No textures. No full-bleed photographic backgrounds.** The background of the canvas is a single subtle gradient (the `bg.canvas` pair). The only "background image" that appears anywhere in Omadia UI is *content the agent has materialised* — a chart, an image the user dropped, a video frame, a canvas-region.

### Animation

| Token | Value | Use |
|---|---|---|
| `--duration-quick` | 100ms | Hover, focus fade-in |
| `--duration-smooth` | 200ms | Modal open/close, accordion |
| `--duration-condense` | 300ms (contract) — full spec specifies 800ms condensation | Patch arrival animation |
| `--easing-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Default decelerate |
| `--easing-emphasis` | `cubic-bezier(0.4, 0, 0.2, 1)` | Modal, condensation |

**Patch-condensation** is the signature animation: new content from the agent doesn't fade in, it **condenses** into existence — opacity 0 → 1, scale 1.03 → 1, blur 2px → 0, with an optional bloom-collapse and sweep-bar for the full 800ms variant. Reduced-motion: collapse to a 200ms opacity fade.

**No spinners.** Loading is always a skeleton-pulse — same shape as the eventual content, animated with a `linear-gradient(90deg, base, hi, base)` sweep over 1400ms. The single documented exception: external-effect action buttons in flight ("Sending…") may show animated dots, never a circular ring.

**No bounces.** Easing is always decelerate (`standard`) or emphasis-decelerate — never spring, never overshoot.

### Hover states

- **Buttons** — primary: fill becomes `accent.hover`; secondary: surface gets `accent.subtle` tint over `motion.quick`.
- **List/tree items** — background paints `accent.subtle` (no glow yet).
- **Menu items** — `accent.subtle` background, no glow.

**Selection** (the *active* state, not hover) is what gets the glow — see below.

### Press states

Primary buttons darken to `accent.active` for the duration of the press. No scale-down, no shrink. The light gets *deeper*, not *smaller*.

### Borders

**Always directional.** 1px solid `<token>.btm` with `border-top-color: <token>.top` override. Raised surfaces additionally carry a 1px inset white-tinted top-edge highlight (`rgba(255,255,255,0.06)` light mode; same in dark).

```css
border: 1px solid var(--border-subtle-btm);
border-top-color: var(--border-subtle-top);
box-shadow: 0 1px 0 var(--top-edge-highlight) inset;
```

### Shadows

Cards do **not** get shadows. Cards are differentiated by border + radius + surface luminosity. Shadows are reserved for **temporally elevated** surfaces:

| Token | Use |
|---|---|
| `--shadow-flat` | none — flat content (the default) |
| `--shadow-raised` | KPI tile, card-like-but-floating — 1px hairline + soft ambient |
| `--shadow-popover` | Dropdowns, popovers, hover cards |
| `--shadow-modal` | Modals — includes accent-glow components, modal is **the lit object** |
| `--shadow-drag` | Drag-in-flight ghost only |

### Glow — the load-bearing primitive

Selection, focus, active-tool: rendered with a **two-stop glow** — bright `glow-core` close to the surface (white-shifted, *not* accent-tinted), accent-tinted `glow` corona further out.

```css
box-shadow:
  0 0 4px var(--accent-glow-core),
  0 4px 12px var(--accent-glow);
```

Three-stop variant for the Spotlight idiom (the showcase moment):

```css
box-shadow:
  0 0 0 4px var(--accent-glow),
  0 0 16px var(--accent-glow-core),
  0 12px 40px var(--accent-glow-strong);
```

A **donut** variant exists for surfaces with a centered glyph (Photoshop tool button, KPI delta arrow) — the bright core radiates *around* the glyph, not under it. See `colors_and_type.css` and the per-primitive docs in `docs/visual-spec.md` §3.3.

### Transparency and blur

**Blur is forbidden as primary chrome.** No frosted-glass surfaces. Lume is solid light, not see-through plastic. The only transparency in the system is:
- `accent-subtle` / `accent-glow` / `accent-glow-strong` / `accent-glow-core` (the glow alphas)
- `bg.modal.overlay` (the modal scrim — 40% alpha light, 60% dark, minimally accent-tinted)
- The mandatory 6% inset top-edge highlight on raised surfaces

That's it.

### Corner radii

| Token | Value | Use |
|---|---|---|
| `--radius-editor` | 0 | `canvas-region`, `timeline`, `vector-path` — opaque editor surfaces. **The Tier-1 boundary marker.** |
| `--radius-sm` | 6px | Small chips, list-item hover/selected backgrounds |
| `--radius-md` | 8px | Buttons, inputs, containers |
| `--radius-lg` | 10px | Cards, popovers |
| `--radius-xl` | 12px | Modals, panes, the outer window |
| `--radius-pill` | 999px | Switches, badge chips, progress bars |

Light has no edges, so the chrome is soft. The editor exception is intentional — a Photoshop-style canvas-region with rounded corners reads "consumer photo app", not "professional tool".

### Cards

A card is **just**: gradient surface + directional border + radius. **No drop shadow.** This is aligned with Linear/Things/Apple Catalyst, against Material Design's everything-is-elevated. Use `--shadow-raised` only when a card is *floating* in a way the layout doesn't already establish (KPI tile over a chart, hover-card popping above content).

### Layout rules

- **Window:** 1440 × 900 default canvas, macOS traffic lights top-left, no other OS chrome.
- **Top status bar:** ~28px tall, **no background fill** (sits directly on `bg.canvas`). Left: `omadia` in Geist 13px `text.secondary`. Right: connector + clock indicators in Geist 13px `text.tertiary`.
- **Bottom prompt bar:** centred, ~640px wide on a 1440px canvas, ~52px tall. `bg.surface.raised` gradient, `radius.xl` (12px), directional border. Placeholder "Ask anything. The canvas will answer." in `text.tertiary` Source Serif 4. Right-aligned `⌘K` and `⌘↩` hints in Geist Mono 12px `text.tertiary`.
- **Everything in between** is the agent's canvas — primitives the agent has materialised.

### Imagery vibe

Omadia UI does not ship hero imagery. The only images in the product are:
- **Agent-rendered images** the user dropped or the agent fetched (charts, photos in a Photoshop workspace, etc).
- **Architecture-3tier diagram** for documentation.

There is no marketing imagery, no team photos, no illustrations. If imagery is needed in a deck or external surface, it should be **technical and restrained** — system architecture diagrams, code screenshots, schematic illustrations. Cool, slightly desaturated, never overly warm.

---

## 4. Iconography

### System

**[Lucide](https://lucide.dev/)** is the icon library. Sizes **14 / 16 / 20 / 24 px** with stroke widths **1.5 / 1.75 / 2.0**. We use Lucide via CDN (`https://unpkg.com/lucide@latest`) — no copy of the icon font is bundled in this design system. If a UI kit needs offline icons, copy the specific SVGs from the Lucide repo into `assets/icons/`.

### Sourcing

A small starter set of Lucide SVGs lives in [`assets/icons/`](assets/icons/) — the ones used by the UI kit and preview cards. The rest are pulled live from the Lucide CDN in the UI kit's `index.html`.

### Custom icons

The spec permits **three** custom icons that Lucide doesn't cover, for editor-specific glyphs. Real custom design is Tier-1 spike work; for this design-system iteration they ship as Lucide stand-ins:

| Custom name | Lucide stand-in | Use |
|---|---|---|
| `magic-wand` | `wand-sparkles` | Agent action handle |
| `brush-pressure` | `brush` | Pressure-sensitive paint |
| `vector-pen-anchor` | `pen-tool` | Bezier anchor variant |

When the spike draws the real glyphs, drop them under `assets/icons/custom/` and update the `Icon` component to prefer that source by name.

### Emoji

**Not used as chrome.** See [Content fundamentals → Emoji](#emoji).

### Unicode glyphs

Used sparingly for keyboard hints — `⌘`, `⌥`, `⇧`, `↵`, `↩`, `→`, `←`, `↑`, `↓`. Always in `Geist Mono`, `text.tertiary`. Center-dots (`·`) are the canonical separator between micro-status items (e.g. `Mon · 18 May · 09:42`).

### Brand mark / logo

**There is no logo asset.** The product name appears only as the word `omadia` in muted body text (`Geist`, 13px, `text.secondary`), top-left of the status bar. There is no wordmark, no app icon shipped, no splash. App-icon and splash design are explicitly out-of-scope for the v0.3 spec — see `docs/visual-spec.md` §9.

The narrative reason: Omadia is a *canvas*, not a brand surface. Branding belongs to the agentic OS layer, not to the canvas the OS draws on.

---

## 5. The 24 primitives + 5 composition idioms

The wire-format vocabulary the agent emits. See `docs/visual-spec.md` §4 for the full per-primitive spec.

### Core (1–20)
`text` · `heading` · `container` · `list` · `table` · `tree` · `button` · `input` · `choice` · `toggle` · `image` · `chart` · `form` · `toolbar` · `menubar` · `tabs` · `pane` · `status` · `progress` · `divider`

### Editor class (21–24)
`media` (audio/video + transport) · `canvas-region` (sharp-cornered pixel buffer) · `timeline` (multi-track, frame-precise) · `vector-path`

### Composition idioms

The agent infers layout from the user's request and emits one of these idioms — but every idiom is rendered in Lume material, never in era-appropriate skinning.

1. **Wizard** — top step-bar (capsule indicators, current step has accent-glow halo) → form region → bottom toolbar (ghost Back, accent-fill Next).
2. **Two-pane split (Norton-Commander)** — vertical 50/50, no resizer chrome by default, mono data-grids inside.
3. **Spotlight** — centred input + list of hits, ample whitespace, the three-stop glow showcase.
4. **Dashboard** — grid of containers — KPI tiles top row, chart/status/table below.
5. **Photoshop workspace** — central `canvas-region` (sharp corners) + left vertical tool toolbar + right inspector form + bottom-right layer-stack tree.

Each renders in `ui_kits/omadia-canvas/` as a click-through React mock.

---

## 6. Anti-patterns — the system refuses to render these

(Cross-ref `docs/visual-spec.md` §7.6.)

- **Status-pill cocktails** — multiple bright colours at once. Use body text + accent row tint. (The single **Signal** accent §3 is the *one* sanctioned loud colour — one element per view, never a pill or a second bright hue alongside it.)
- **Drop shadows that scream** — outer shadows only on modal-class surfaces.
- **`border-bottom: 1px solid lightgrey` everywhere** — use surface gradients for stacked-element separation.
- **Branded logo treatment** at the top. `omadia` is muted body text, not a wordmark.
- **Loading spinners** — skeletons. The button-in-flight dots are the one exception.
- **"Welcome to Omadia"** empty states with illustrations.
- **Settings / Preferences UI** for palette or theme.
- **Sidebars** with Settings / Profile / Help / Workspaces / Recent.
- **Save buttons** in workspace surfaces — everything autosaves.
- **Toasts** / floating notifications. Errors live in the tree.
- **Decorative emoji** in chrome.
- **Gradient buttons** beyond the documented two — surface gradients (§3.1) and primary-button-fill gradients (§4.2). No accent-to-purple, no glassmorphism, no neumorphism.

---

## 7. Caveats and substitutions

- **No local font files.** Geist / Geist Mono / Source Serif 4 are pulled from Google Fonts CDN. For an offline-capable Electron build, swap to local variable WOFF2s — see [`fonts/README.md`](fonts/README.md).
- **No app-icon or splash artwork, no wordmark.** Per spec §6 these are explicitly out of scope. The "logo" everywhere is the lowercase word `omadia` in `text.secondary` Geist 13px.
- **All token values match the spec exactly.** Lagoon, Petrol and Atelier sub-tokens are the mechanical OKLCH→sRGB derivations from `docs/visual-spec.md` §2.5. No drift, no custom hexes.
- **Icon library is CDN-linked.** Lucide via `https://unpkg.com/lucide`. No SVG sprite is bundled. The handful of icons used by the UI kit live in `assets/icons/`. Three custom editor icons (`magic-wand`, `brush-pressure`, `vector-pen-anchor`) currently use Lucide stand-ins (`wand-sparkles`, `brush`, `pen-tool`) — real custom icon design is Tier-1 spike work.
- **Patch-condensation full spec is 800ms** with three concurrent components (materialise + bloom collapse + sweep bar). This design system implements the simpler 300ms materialise-only variant called out in the contract; the 800ms three-component recipe is documented in `docs/visual-spec.md` §3.5 for renderers that want the full effect.

---

## 8. Using this design system

When designing a new Omadia UI surface, slide, or deliverable:

1. **Include the tokens.** Reference `colors_and_type.css` from your HTML.
2. **Set `data-mode` and `data-accent`** on `<html>` or a wrapper — `data-mode="light"` and `data-accent="lagoon"` are the defaults.
3. **Use the four forces.** Every surface is a gradient pair; every border is directional; every raised surface has the 6% inset top-edge highlight; selection and focus emit light, not paint.
4. **Stay inside the 24 primitives.** The spec is intentionally small. If you find yourself reaching for a new primitive, you're probably missing a composition idiom.
5. **Check the anti-pattern list.** Most "good ideas" we have for Lume are already on it.
