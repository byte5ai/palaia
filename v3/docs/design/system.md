# palaia v3 — design system

> The look and interaction language of palaia, fixed **before** any UI code exists.
> SPEC-109 implements this file; SPEC-110 and every later screen compose what it
> defines. The five mockups in [`mockups/`](mockups/) are the visual reference; the
> do/don't rules per screen live in [`principles.md`](principles.md).
>
> Version 1 — 2026-08-22 — grounded in MASTERPLAN §3 (P7), §4 (UX doctrine),
> §5.5, §5.7 and §6.

## 0. What palaia looks like, in one paragraph

palaia is an appliance for a person's accumulated knowledge, so it looks like a
well-kept **archive**, not like a control panel: warm paper in light mode, deep ink
in dark mode, hairline rules instead of boxes-inside-boxes, one confident accent
(verdigris — the patina of something that has been around), and a serif for the
lines that carry meaning (page titles, the health verdict, note titles, metrics).
Type is small and calm; whitespace does the separating; colour appears where
something is *true about the system* — healthy, needs attention, broken — and
almost nowhere else. Nothing blinks, nothing gradients for decoration, nothing
shouts. If a screen looks like an admin panel from 2015, it is not done (UX rule 6).

Three deliberate consequences:

1. **One accent, semantic colour otherwise.** Verdigris means "you can act on
   this". Green/amber/red mean state. A colour that means nothing is a bug.
2. **Serif for meaning, sans for work, mono for machine text.** Endpoints, tool
   names, commits, diffs and frontmatter are monospace — they are literal strings
   the user may have to copy exactly.
3. **Live, not reloadable.** Every list is event-driven (SPEC-109's SSE layer).
   There is no refresh button anywhere in this system, and no spinner that owns a
   whole screen: skeletons and inline `waiting` indicators only.

## 1. Design tokens

Tokens are the contract between this document and the code. **Nothing in the UI
may hardcode a colour, radius, duration or type size** — SPEC-109 enforces that
with a lint rule.

Theming works in two layers, both required:

- `prefers-color-scheme` provides light and dark automatically (system default);
- `data-theme="light" | "dark"` on the root element overrides it for the explicit
  theme switch in the app chrome.

The block below is the canonical definition. Every mockup embeds it **verbatim**;
`v3/web` will ship exactly these custom properties (Tailwind config binds to them
rather than redefining them).

```css
/* ================================================================
   palaia design tokens v1
   ================================================================ */
:root{
  color-scheme: light dark;

  /* Neutrals - warm paper */
  --p-canvas:#F6F4F0;
  --p-surface:#FFFFFF;
  --p-surface-2:#FBF9F6;
  --p-sunken:#EFEBE4;
  --p-line:#E4DFD6;
  --p-line-strong:#CFC8BB;
  --p-ink:#1E1C19;
  --p-ink-muted:#6A645B;
  --p-ink-subtle:#776E63;

  /* Accent - verdigris (brand + everything interactive) */
  --p-accent:#0B6E6B;
  --p-accent-hover:#095857;
  --p-accent-ink:#0A5F5D;
  --p-accent-soft:#E3F0EE;
  --p-accent-line:#B9DAD6;
  --p-on-accent:#FFFFFF;

  /* Semantic - state, never decoration */
  --p-ok:#377346;   --p-ok-soft:#E7EFE7;   --p-ok-line:#C2DAC4;
  --p-warn:#8F5D10; --p-warn-soft:#F8EFDC; --p-warn-line:#E4D0A7;
  --p-risk:#A63929; --p-risk-soft:#F8E8E5; --p-risk-line:#E8C5BE;
  --p-info:#3A5A85; --p-info-soft:#E8EEF7; --p-info-line:#C5D3E7;

  /* Elevation */
  --p-shadow-1:0 1px 2px rgba(30,28,25,.06);
  --p-shadow-2:0 1px 2px rgba(30,28,25,.05), 0 10px 24px -14px rgba(30,28,25,.22);
  --p-shadow-3:0 2px 4px rgba(30,28,25,.06), 0 24px 48px -20px rgba(30,28,25,.28);

  /* Type */
  --p-font-sans:ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --p-font-serif:ui-serif, "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, "Times New Roman", serif;
  --p-font-mono:ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  --p-size-2xs:.6875rem;  /* 11px - overlines only */
  --p-size-xs:.75rem;     /* 12px - meta, chips */
  --p-size-sm:.8125rem;   /* 13px - dense UI, table cells */
  --p-size-md:.9375rem;   /* 15px - body, the default */
  --p-size-lg:1.0625rem;  /* 17px - lead paragraph, card titles */
  --p-size-xl:1.3125rem;  /* 21px - section heads */
  --p-size-2xl:1.625rem;  /* 26px - page titles, metrics */
  --p-size-3xl:2.0625rem; /* 33px - the one-glance verdict */
  --p-size-display:2.625rem; /* 42px - onboarding only */
  --p-leading-tight:1.15;
  --p-leading-snug:1.35;
  --p-leading-normal:1.55;
  --p-leading-loose:1.7;
  --p-track-tight:-.012em;
  --p-track-label:.09em;

  /* Space - 4px base */
  --p-space-1:.25rem;  --p-space-2:.5rem;  --p-space-3:.75rem; --p-space-4:1rem;
  --p-space-5:1.25rem; --p-space-6:1.5rem; --p-space-8:2rem;   --p-space-10:2.5rem;
  --p-space-12:3rem;   --p-space-16:4rem;

  /* Radii */
  --p-radius-sm:6px; --p-radius-md:10px; --p-radius-lg:14px; --p-radius-xl:20px; --p-radius-pill:999px;

  /* Motion - short, eased, always skippable */
  --p-ease:cubic-bezier(.2,.7,.3,1);
  --p-dur-1:120ms; --p-dur-2:180ms; --p-dur-3:260ms;

  /* Layout */
  --p-nav-w:248px; --p-rail-w:64px; --p-topbar-h:60px; --p-content-max:1180px;
}

/* Dark: only the colour and elevation tokens change. Declared twice on purpose —
   once for the system preference, once for the explicit theme switch. */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  /* Neutrals - ink */
  --p-canvas:#121417;
  --p-surface:#191C21;
  --p-surface-2:#1E2228;
  --p-sunken:#0E1013;
  --p-line:#282D34;
  --p-line-strong:#3A4048;
  --p-ink:#EAE7E1;
  --p-ink-muted:#9EA4AC;
  --p-ink-subtle:#8A9099;

  /* Accent */
  --p-accent:#2E9E97;
  --p-accent-hover:#3BB3AB;
  --p-accent-ink:#5FC8BF;
  --p-accent-soft:#102B2A;
  --p-accent-line:#22514D;
  --p-on-accent:#04211F;

  /* Semantic */
  --p-ok:#79B886;   --p-ok-soft:#13211A;   --p-ok-line:#264430;
  --p-warn:#DCA85C; --p-warn-soft:#241C0F; --p-warn-line:#4A3A1D;
  --p-risk:#E0857A; --p-risk-soft:#251411; --p-risk-line:#4E2620;
  --p-info:#8CB0E2; --p-info-soft:#131C29; --p-info-line:#26364B;

  /* Elevation - dark leans on lines, not shadows */
  --p-shadow-1:0 1px 2px rgba(0,0,0,.45);
  --p-shadow-2:0 1px 2px rgba(0,0,0,.45), 0 12px 28px -16px rgba(0,0,0,.75);
  --p-shadow-3:0 2px 6px rgba(0,0,0,.5), 0 28px 56px -24px rgba(0,0,0,.85);
}}
:root[data-theme="dark"]{ /* same dark values as above */ }
```

### 1.1 Colour semantics

| Token family | Means | Never used for |
|---|---|---|
| `accent` | Anything the user can act on: primary buttons, links, wiki-links, the selected item, the brand mark | State, decoration, large fills |
| `ok` | Verified good: healthy checks, committed writes, additions in a diff | "Success" toasts that nobody needed |
| `warn` | Needs a human eventually: inbox backlog, index lag, mode conflicts, merge proposals | Anything the system can fix by itself silently |
| `risk` | Destructive or broken: revoke, reject, retire, removals in a diff, failed checks | Warnings that are merely unusual |
| `info` | Context and explanation, including the honest "this cannot work here" callouts | Attention-seeking |
| `ink` / `ink-muted` / `ink-subtle` | Primary text / secondary text / meta and overlines | Meta text below 11px |

Contrast is verified, not assumed. Every text pair in this system is **≥ 4.5:1 in
both themes** (measured, including `ink-subtle` on `canvas` at 4.56 light / 5.74
dark, and `on-accent` on `accent` at 6.07 / 5.19). Never use `line` or `*-line`
tokens for text.

### 1.2 Type

| Role | Font | Size | Weight / tracking |
|---|---|---|---|
| Health verdict (home) | serif | `3xl` | 600, tight |
| Wizard question | serif | `3xl` | 600, tight |
| Page title | serif | `xl` | 600, tight |
| Note title, empty-state title | serif | `2xl` / `xl` | 600, tight |
| Metric | serif, tabular numerals | `2xl` | 600 |
| Card title, field label | sans | `md` | 600 |
| Body | sans | `md` | 400, leading normal (`loose` inside note prose) |
| Dense UI (rows, table cells, buttons) | sans | `sm` | 400–550 |
| Meta, chips, hints | sans | `xs` | 400 |
| Overline | sans | `2xs` | 600, uppercase, tracking `label` |
| Endpoints, tool names, commits, diffs, frontmatter | mono | `xs`–`sm` | 400 |

Sentence case everywhere, including buttons and headings. No text below 11px. No
italics except for a quoted vault name or an emphasised word inside prose.

### 1.3 Space, radius, elevation, motion

- **Space** is a 4px scale. Card padding `space-5`, card head/foot `space-4`,
  gaps between sections `space-4`, related items `space-2`–`space-3`.
- **Radius**: `sm` for chips and inline code, `md` for buttons, inputs and inner
  cards, `lg` for cards and panels, `xl` for the in-client app frame, `pill` for
  badges and dots.
- **Elevation** is used sparingly: `shadow-1` for resting cards, `shadow-2` for the
  card that carries the current decision, `shadow-3` for overlays only. In dark
  mode, hairlines do the work shadows do in light mode.
- **Motion**: 120/180/260ms with `--p-ease`. Hover and state changes only; nothing
  animates on load except the live dot and the waiting indicator.
  `prefers-reduced-motion: reduce` disables all of it — required, not optional.

### 1.4 Layout & breakpoints

| Width | Navigation | Content |
|---|---|---|
| **≥ 1280px** (design target) | Full sidebar, 248px | Multi-column: 2-up on home, 3 panes in the explorer, main + rail in the review queue |
| **768–1279px** | Icon rail, 64px | Two columns collapse to one; the explorer drops its context pane into the note pane's flow |
| **< 768px** | Horizontal nav strip at the top, brand visible, scrollable | Single column, cards full width, diffs stack before/after vertically |

The app shell owns the viewport height (`100dvh`); long lists scroll **inside**
their pane, so the chrome, the health verdict and the primary action never scroll
away. At 1280×800, every screen in `mockups/` shows its complete answer with no
clipping — that is a verified property, not an aspiration.

### 1.5 Iconography

Inline SVG, 24-unit grid, 1.5px stroke, `currentColor`, round caps — 16px in dense
UI, 20px default, 28px in empty states. No icon fonts, no emoji, no external
sprite sheets. Icons never appear without a label except in the icon rail (where
they carry a `title`) and in single-purpose icon buttons.

## 2. Component inventory

The list SPEC-109 must deliver. "Anatomy" says what it is made of; "states" is
the minimum a component must render.

### Actions

| Component | Anatomy | States | Rules |
|---|---|---|---|
| `btn--primary` | 36px, accent fill, optional leading icon | hover, active, focus-visible, disabled | **One per view.** The primary is the thing you most likely want next |
| `btn` (secondary) | surface + `line-strong` border | as above | For alternatives that are equally safe |
| `btn--quiet` / `btn--ghost` | border only / text only | as above | Row-level and tertiary actions |
| `btn--risk` | risk border, risk text, tinted on hover | as above | Revoke, reject, delete. Never filled red |
| `btn--sm` / `btn--lg` | 28px / 44px | — | `sm` inside rows and cards, `lg` in the wizard |
| `iconbtn` | 32px square, ghost | hover, focus | Needs `title`; never the only path to an action |
| `kbd` | 20px key cap | — | Shown next to an action that has a shortcut, not in a legend somewhere else |

### Surfaces & structure

`card` (+`--flat`, `--raised`) with `card__head` / `card__body` / `card__foot`;
`tile` (metric tile, `--attention` variant with a one-click fix button);
`banner` (info / warn / ok — an explanation with an optional title, never a bare
error string); `sep`; `scrollpane` (thin themed scrollbars); `pane` (explorer
column with its own sticky head).

### Navigation

`sidebar` (brand, grouped `nav__item`s with optional `nav__count` badges, footer
with operating mode and version), `topbar` (page title + one-line subtitle,
command bar `⌘K`, global health badge, avatar), `tabbar` (in-card tabs),
`segmented` (small mutually exclusive choices, e.g. tool profiles), `steps`
(wizard rail with done/current/upcoming), `numstep` (numbered step inside a flow).

### Data display

`table` (hairline rows, no zebra, uppercase micro-headers, horizontally scrollable
in its own wrapper), `listrow` (icon + title + meta + trailing value/action),
`feed` (activity item: mark, sentence, provenance chips, relative time, hover
action), `diff` (two columns at ≥ 768px, stacked below; `dline--add` / `--del` /
`--same`), `graph` (local relation graph as inline SVG: pill nodes, typed edge
labels, dashed nodes for forward references — never a global hairball),
`snippet` (mono block + copy button; wraps rather than truncates), `qr`,
`fm` (frontmatter key/value list), `commitrow`.

### Status

`badge` (neutral / ok / warn / risk / info / accent), `dot` (+`dot--live` for
event-stream-backed liveness), `chip` (provenance: which agent, which session,
which capture id; `chip--mono` for identifiers), `waiting` (three-dot inline
indicator with a sentence saying what is being waited for), `meter`.

### Forms

`field` (label + control + hint — hints explain *why*, not *what*), `input`
(+`input--readonly` for machine-owned values like paths, which get a
`Change…` button rather than becoming editable text), `switchrow` (toggle +
label + consequence), `radiocard` (a choice with its trade-offs: "choose this
if…", what works, what does not), `clientcard`, `preview` (dashed panel showing
what the machine will see, e.g. generated tool names).

### Empty & first-run

`empty` (mark, serif title, one explanatory sentence, one or more next actions)
plus the compact inline variant (`empty__mark` + two lines) for panels that are
empty inside an otherwise populated screen. Every empty state must name the next
action; see `principles.md` §3.

### Feedback (SPEC-109 also implements)

Toast (bottom-right, 4s, one line + optional undo), inline validation (never a
modal), skeleton rows (never a full-screen spinner), destructive confirmation
(dialog naming exactly what will change and how to undo it).

## 3. Tone of voice for UI copy

palaia speaks like a competent colleague who respects the user's time: plain,
concrete, honest about limits, never cheerful about nothing.

**Rules**

1. **Second person, active voice, present tense.** "Connect your first client",
   not "Client connection can be established".
2. **State the fact, then the next action.** "Index is 42 notes behind on
   *personal*. Reindex now."
3. **Never make the user google.** An error message says what happened, what it
   means, and offers the fix (UX rule 5). If there is no fix, say who can fix it.
4. **Say the inconvenient thing.** "claude.ai connects from Anthropic's cloud, not
   from this device. In Locked mode it cannot reach palaia." Honesty is the
   product's trust surface (UX rule 7).
5. **Numbers with units and provenance.** "12 waiting, oldest 3 days" beats
   "several pending items".
6. **Relative time in the UI, absolute on hover.** "6 min ago" / title
   `2026-08-22 14:00:12 CEST`.
7. **No exclamation marks, no "Oops", no "Awesome!", no emoji.** Sentence case,
   no ALL CAPS except the 11px overline style.
8. **Name palaia's own actors.** "The curator merged two captures", "Claude Code
   wrote…" — never "the system" or a passive construction that hides who acted.
9. **Empty states teach in two sentences**: what this place is for, and the one
   thing to do next.
10. **Buttons are verbs**: Approve, Reindex now, Connect a client, Rotate token.
    Never "OK", "Submit", "Yes".

**Vocabulary** (use consistently — these words appear in the mockups and must not
drift): vault, note, observation, relation, inbox, capture, curator, proposal,
client, tool profile, endpoint, access mode (Locked / Cloud / Open), doctor,
finding.

| Don't | Do |
|---|---|
| "Error: ECONNREFUSED (500)" | "The hub could not reach the tunnel. Retry, or check the tunnel add-on." |
| "Settings saved successfully!" | (toast) "Profile updated — Codex now sees 6 tools." |
| "Are you sure?" | "Revoke Codex's token? It loses access immediately; you can issue a new one any time." |
| "No data" | "Nothing captured yet. Connect a client and ask it to remember something." |
| "Advanced configuration" | "Change how palaia is reachable" |
| "The system will process your request" | "The curator picks this up within a minute." |

## 4. The mockups

| File | Screen | States it renders |
|---|---|---|
| [`mockups/home.html`](mockups/home.html) | Home — "is everything healthy, what happened?" | populated · first run |
| [`mockups/onboarding.html`](mockups/onboarding.html) | First-run wizard | account · access mode · first vault · first client |
| [`mockups/connect-client.html`](mockups/connect-client.html) | Connect a client | guided · connected · blocked by access mode · first run |
| [`mockups/memory-explorer.html`](mockups/memory-explorer.html) | Memory explorer | populated (note + local graph) · empty vault |
| [`mockups/review-queue.html`](mockups/review-queue.html) | Review queue (curator proposals) | populated · empty · in-client app |

They are single static HTML files: inline CSS, inline SVG, no build step, no
external fonts or CDNs, no network requests at all. Open one in a browser — or
several, at 360 / 768 / 1280 — and use the thin dashed bar at the top to switch
state or force a theme (that bar is scaffolding, not product). Everything in them
is fake data; nothing talks to a backend.

**When you change a token**, change it here first, then in every mockup's token
block (they are byte-identical copies), then in `v3/web`.
