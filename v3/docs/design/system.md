# palaia v3 — design system

> The look and interaction language of palaia, fixed **before** any UI code exists.
> SPEC-109 implements this file; SPEC-110 and every later screen compose what it
> defines. The five mockups in [`mockups/`](mockups/) are the visual reference; the
> do/don't rules per screen live in [`principles.md`](principles.md).
>
> Version 2 — 2026-08-22 — restyled onto **Lume**, palaia's shared design system
> (source of truth: [`../lume/colors_and_type.css`](../lume/colors_and_type.css),
> written up in [`../lume/visual-spec.md`](../lume/visual-spec.md), palaia's own
> binding decisions in [`../lume/README.md`](../lume/README.md)). Version 1's
> bespoke "warm paper / verdigris" token system is retired; this document now
> describes how palaia binds Lume, not an invented parallel system. Still
> grounded in MASTERPLAN §3 (P7), §4 (UX doctrine), §5.5, §5.7 and §6.

## 0. What palaia looks like, in one paragraph

palaia is an appliance for a person's accumulated knowledge, so it looks like a
well-kept **archive materialised out of light**, not like a control panel: Lume's
light-as-material thesis — every surface a soft directional gradient, borders that
catch light from above, selection and focus as a glow rather than a flat tint — in
palaia's own accent, **atelier** (studio-lamp warmth: the agent as craftsman
lighting the work), with a serif for the lines that carry meaning (page titles,
the health verdict, note titles, metrics). Type is small and calm; whitespace
does the separating; colour appears where something is *true about the system* —
healthy, needs attention, broken — communicated through text and icon colour,
never a filled pill or a status-tinted block. Nothing blinks, nothing gradients
for decoration beyond Lume's own material recipes, nothing shouts except the one,
rare, capped **Signal** moment a view is allowed (§1.1, `principles.md` rule 6).
If a screen looks like an admin panel from 2015, it is not done (UX rule 6).

Three deliberate consequences:

1. **One accent, semantic colour otherwise — plus the rare Signal.** Atelier means
   "you can act on this". Success/warning/error mean state, in text only. Signal
   is a fourth, palette-independent colour reserved for at most one element per
   view, the single most important commitment on the screen — it is not a second
   accent (see §1.1 and `principles.md` rule 6).
2. **Serif for meaning, sans for work, mono for machine text.** Endpoints, tool
   names, commits, diffs and frontmatter are monospace — they are literal strings
   the user may have to copy exactly.
3. **Live, not reloadable.** Every list is event-driven (SPEC-109's SSE layer).
   There is no refresh button anywhere in this system, and no spinner that owns a
   whole screen: Lume's skeleton pulse and inline `waiting` indicators only.

## 1. Design tokens

**Source of truth: [`../lume/colors_and_type.css`](../lume/colors_and_type.css).**
Every value in this document and every mockup is copied or mechanically derived
from that file — never invented. Change a value there first, then mirror it here
and in every mockup's token block (still byte-identical to each other, per §4).
[`../lume/visual-spec.md`](../lume/visual-spec.md) is the written spec behind the
tokens; [`../lume/README.md`](../lume/README.md) records palaia's four binding
decisions on top of it, restated here because they are load-bearing for this
document:

1. **Default accent: `atelier`** (studio warmth — the agent as craftsman lighting
   the work). Lagoon (Lume's own default) and Petrol remain fully implemented,
   gated behind `data-accent="lagoon" | "petrol"` — the accent slot is
   user-switchable, conversationally, never via a Settings screen.
2. **Theme switching** uses Lume's own attribute, `data-mode="light" | "dark"`,
   defaulted to the system preference (`prefers-color-scheme`) with a manual
   override for the dashboard's explicit theme switch. (v1 of this document used
   `data-theme`; that name is retired in favour of Lume's own.)
3. **Fonts** (Geist / Geist Mono / Source Serif 4) are self-hosted in the
   dashboard build and bundled in MCP Apps — never the Google Fonts `@import`
   that appears in `colors_and_type.css` (a design-tool convenience only). The
   mockups ship zero external requests; their fallback stacks carry rendering.
4. **The Signal rule is binding UX doctrine**: at most one Signal element per
   view, never as a surface fill, never as a status pill. See §1.1 below and
   `principles.md` rule 6.

**Nothing in the UI may hardcode a colour, radius, duration or type size** —
SPEC-109 enforces that with a lint rule against Lume's tokens, exactly as v1's
lint rule enforced it against the bespoke tokens it replaces.

The mockups keep working under the same short `--p-*` names this document used
before (`--p-canvas`, `--p-ink`, `--p-accent`, …) so their component CSS did not
need a line-by-line rewrite — but every one of those names is now a straight
alias onto a real Lume token, several of them (`--p-canvas`, `--p-surface`,
`--p-sunken`, …) holding the **whole gradient**, not a flat colour, so that
`background:var(--p-surface)` renders Lume's surface-luminosity recipe (directional
gradient, §1.4) with no per-rule rewrite needed. `v3/web` binds Tailwind config to
the raw Lume custom properties directly; the `--p-*` layer is a mockup-only
convenience and does not ship in the dashboard build.

### 1.1 Colour semantics

| Token family | Means | Never used for |
|---|---|---|
| `accent` (atelier) | Anything the user can act on: primary buttons, links, wiki-links, the selected item, the brand mark | State, decoration, large fills |
| `signal` | The one, rare, most-important commitment in a view (e.g. the onboarding wizard's "Create vault") — palette-independent, capped at one per view | A second accent, a routine action (Approve is accent, not signal — see `principles.md` rule 6), a status pill |
| `success` | Verified good: healthy checks, committed writes, additions in a diff | "Success" toasts that nobody needed |
| `warning` | Needs a human eventually: inbox backlog, index lag, mode conflicts, merge proposals | Anything the system can fix by itself silently |
| `error` | Destructive or broken: revoke, reject, retire, removals in a diff, failed checks | Warnings that are merely unusual |
| `info` (no dedicated Lume hue) | Context and explanation, including the honest "this cannot work here" callouts — rendered as quieter neutral text plus a neutral icon, since Lume's semantic-state tokens cover only error/success/warning | Attention-seeking; do not invent an info hue that Lume doesn't define |
| `text-primary` / `text-secondary` / `text-tertiary` | Primary text / secondary text / meta and overlines | Meta text below 12px (Lume's caption size is the floor) |

**Semantic state is text-only — never a filled pill, badge or block fill**
(`colors_and_type.css` §2.6, carried through to every mockup: badges, banners,
diff add/remove lines, proposal-kind tags and nav counters all render as
coloured text/icon on a neutral surface, never a colour-tinted box). The one
partial exception Lume itself ships is `error`, which does get a real 1px
border token (`state-error-edge`) for field-level errors — success and warning
have no border token and stay text-only everywhere.

Contrast is verified, not assumed (§5 of the PR that introduced this version
re-ran the check against every new Lume surface/text pair — see that PR's
comment for the numbers). Never use a `-line` alias for body text; they are
low-alpha derivations meant for rings, glows and thin edges, not reading text.

### 1.2 Type

Three registers, each a different family — **Geist** (structural), **Source
Serif 4** (prose/meaning), **Geist Mono** (data/machine text) — per
`colors_and_type.css` §1 and visual-spec §2.7. palaia's own scale collapses onto
Lume's actual steps; Lume ships fewer, larger jumps than palaia's v1 scale had,
so this is a nearest-step mapping, not an invention:

| Role | Font | Lume step | Size | v1 size (for reference) |
|---|---|---|---|---|
| Health verdict (home), wizard question | serif | `display` | 32px | 33px |
| Page title, section heads | serif / sans | `h2` | 20px | 21px |
| Note title, empty-state title | serif | `h1` / `h2` | 24px / 20px | 26px / 21px |
| Metric | serif, tabular numerals | `h1` | 24px | 26px |
| Card title, field label, lead paragraph | sans | `h3` | 16px | 17px |
| Body | sans | `body` | 14px, leading 22px | 15px |
| Dense UI (rows, table cells, buttons) | sans | `body-sm` | 13px | 13px (unchanged) |
| Meta, chips, hints, overline | sans | `caption` | 12px | 11–12px |
| Endpoints, tool names, commits, diffs, frontmatter | mono | `mono` / `mono-sm` | 13px / 12px | 12–13px (unchanged) |

Lume tops out at `display` (32px); the old 42px onboarding-only display size has
no Lume equivalent and is retired — the wizard's step titles now render at the
same 32px as the home verdict. Sentence case everywhere, including buttons and
headings. No italics except for a quoted vault name or an emphasised word inside
prose (which, per Lume's register rule, would be the serif channel already).

### 1.3 Space, radius, elevation, motion

Lume's 4pt grid (`colors_and_type.css` §1) already matches palaia's own 4px scale
almost exactly — `--p-space-1`..`--p-space-8` and `--p-space-12`/`16` are exact
1:1 aliases onto `--space-1`..`--space-16`; only `--p-space-10` (40px) has no
single Lume step and is `calc(var(--space-8) + var(--space-2))`.

- **Radius** moves to Lume's scale, one notch tighter than v1's: `sm` 6px
  (unchanged) for chips and inline code, `md` 8px (was 10px) for buttons, inputs
  and inner cards, `lg` 10px (was 14px) for cards and panels, `xl` 12px (was
  20px) for the in-client app frame — matching macOS's own window-corner radius,
  per Lume's "concentric corners" rationale — `pill` for badges and dots
  (unchanged). The editor-class exception (radius 0) does not apply to any
  palaia screen in this iteration; it exists in Lume for future canvas-region
  primitives.
- **Elevation** maps straight onto Lume's three shadow tokens: `shadow-1` =
  `--shadow-raised` for resting cards, `shadow-2` = `--shadow-popover` for the
  card that carries the current decision, `shadow-3` = `--shadow-modal` for
  overlays (which also carries an accent-glow ambient component — the modal
  reads as the lit object, its scrim as its shadow). Every raised surface also
  carries Lume's 1px top-edge highlight (`--top-edge-highlight`) as an inset
  box-shadow — the material's perceived thickness, not decoration.
- **Motion**: Lume's `--duration-quick`/`-smooth`/`-condense` (100/200/300ms)
  with `--easing-standard`. Hover and state changes only; nothing animates on
  load except the live dot and the waiting indicator.
  `prefers-reduced-motion: reduce` disables all of it, including Lume's skeleton
  pulse (which drops to a static 40% fill) — required, not optional.

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
| `btn--primary` | 36px, accent gradient fill (top→hover stop), two-stop accent glow, optional leading icon | hover (deeper glow), active, focus-visible (Lume focus ring), disabled | **One per view.** The primary is the thing you most likely want next |
| `btn--signal` | Same anatomy as `btn--primary`, palette-independent Signal fill/glow instead of accent | as above | **At most one across the entire dashboard's currently-visible view**, and only for the single most important, one-time commitment — see `principles.md` rule 6. Not a second `btn--primary`; do not reach for it for a routine action |
| `btn` (secondary) | surface gradient + directional `line-strong` border + top-edge highlight | as above | For alternatives that are equally safe |
| `btn--quiet` / `btn--ghost` | border only / text only | as above | Row-level and tertiary actions |
| `btn--risk` | transparent fill, border/text = `state.error.edge`/`state.error.fg` (the one semantic state with a real border token), low-alpha error wash on hover | as above | Revoke, reject, delete. Never filled red |
| `btn--sm` / `btn--lg` | 28px / 44px | — | `sm` inside rows and cards, `lg` in the wizard |
| `iconbtn` | 32px square, ghost | hover, focus | Needs `title`; never the only path to an action |
| `kbd` | 20px key cap | — | Shown next to an action that has a shortcut, not in a legend somewhere else |

### Surfaces & structure

`card` (+`--flat`, `--raised`) with `card__head` / `card__body` / `card__foot` —
every non-flat card is a Lume gradient surface with a directional border and a
1px top-edge highlight, never a flat fill; `tile` (metric tile, `--attention`
variant — text and icon colour only, **no fill or coloured border**, per the
text-only state rule); `banner` (info / warn / ok — a neutral gradient surface
whose icon and title take the state colour; the box itself never does. An
explanation with an optional title, never a bare error string); `sep`;
`scrollpane` (thin themed scrollbars); `pane` (explorer column with its own
sticky head).

### Navigation

`sidebar` (brand — accent-glow mark — grouped `nav__item`s with optional
`nav__count` badges, footer with operating mode and version), `topbar` (page
title + one-line subtitle, command bar `⌘K`, global health badge, avatar),
`tabbar` (in-card tabs; the active tab's underline carries an accent-glow
underglow, per Lume's tabs recipe), `segmented` (small mutually exclusive
choices, e.g. tool profiles), `steps` (wizard rail with done/current/upcoming —
**selection states use the Lume two-stop glow halo, never a flat accent-tinted
fill**: done = neutral + success ring, current = the donut-glow number), `numstep`
(numbered step inside a flow, same done/current treatment as `steps`).

### Data display

`table` (hairline rows, no zebra, uppercase micro-headers, horizontally scrollable
in its own wrapper), `listrow` (icon + title + meta + trailing value/action;
`--selected` uses the glow halo, not a fill), `feed` (activity item: mark,
sentence, provenance chips, relative time, hover action — the mark's colour
carries the event type, never a coloured circle fill), `diff` (two columns at
≥ 768px, stacked below; `dline--add` / `--del` / `--same` render as a coloured
left edge plus a coloured `+`/`−` glyph on a neutral row — **never a coloured
block fill behind the line**, per the text-only state rule), `graph` (local
relation graph as inline SVG: pill nodes, typed edge labels, dashed nodes for
forward references — never a global hairball), `snippet` (mono block + copy
button; wraps rather than truncates), `qr`, `fm` (frontmatter key/value list),
`commitrow`.

### Status

`badge` (neutral / ok / warn / risk / info / accent — **text and optional `dot`
only, no pill background or border**, per `colors_and_type.css` §2.6), `dot`
(+`dot--live` for event-stream-backed liveness), `chip` (provenance: which
agent, which session, which capture id; `chip--mono` for identifiers — a neutral
tag, not a status indicator, so it may still carry a background wash), `waiting`
(three-dot inline indicator with a sentence saying what is being waited for —
Lume's one sanctioned non-skeleton loading affordance), `skeleton`
(`lume-skeleton`, a linear pulse for content that has not arrived yet — the
default loading treatment everywhere else), `meter` (accent-fill bar with a
soft accent-glow underneath, on a sunken track — reads as lit, not painted).

### Forms

`field` (label + control + hint — hints explain *why*, not *what*), `input`
(gradient surface, directional border, top-edge highlight; focus = the Lume
glow ring, not a flat outline; `+input--readonly` for machine-owned values like
paths, which get a `Change…` button rather than becoming editable text),
`switchrow` (toggle + label + consequence; the "on" thumb is accent-fill with a
small glow), `radiocard` (a choice with its trade-offs: "choose this if…", what
works, what does not — the selected card is an accent-subtle wash plus a glow
ring, never a flat tinted fill), `clientcard` (same selected treatment),
`preview` (dashed panel showing what the machine will see, e.g. generated tool
names).

### Empty & first-run

`empty` (mark — a small accent-glow icon tile — serif title, one explanatory
sentence, one or more next actions) plus the compact inline variant
(`empty__mark` + two lines) for panels that are empty inside an otherwise
populated screen. Every empty state must name the next action; see
`principles.md` §3.

### Feedback (SPEC-109 also implements)

Toast (bottom-right, 4s, one line + optional undo), inline validation (never a
modal), `lume-skeleton` rows (never a full-screen spinner — the one exception is
button-in-flight text, §7.3 of `../lume/visual-spec.md`), destructive
confirmation (dialog naming exactly what will change and how to undo it).

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
   no ALL CAPS except the 12px overline style (Lume's `caption` step, §1.2).
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
external fonts or CDNs, no network requests at all — deliberately, since Lume's
own `colors_and_type.css` carries a Google Fonts `@import` for design-tool
convenience that the mockups omit on purpose (§1, decision 3). Open one in a
browser — or several, at 360 / 768 / 1280 — and use the thin dashed bar at the
top to switch state or force a theme (that bar is scaffolding, not product).
Everything in them is fake data; nothing talks to a backend. Every mockup binds
`atelier` as the active accent inline; Lagoon and Petrol are present in every
mockup's token block, gated behind `data-accent`, so the accent-switch story
stays visible and testable in code without any of the mockups needing a second
copy.

**When you change a token**, change it in
[`../lume/colors_and_type.css`](../lume/colors_and_type.css) first, then mirror
it here and in every mockup's token block (they are byte-identical copies of
each other), then in `v3/web`.
