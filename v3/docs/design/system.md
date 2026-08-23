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
>
> Version 2.1 — 2026-08-23 — the owner rejected version 2's mockups on sight:
> the tokens were right (atelier reads correctly) but the **material** wasn't
> implemented — primaries rendered as flat solid fills instead of Lume's
> accent-gradient + top-edge-highlight + glow, cards/tiles as flat white
> instead of the `bg-surface-raised` gradient pair with `--shadow-raised`, and
> the Geist/Source Serif typefaces never loaded because the mockups shipped
> with no font source at all. This pass fixes all three (§1 decision 3, §2
> Actions/Surfaces, §4) and removes an accent-tinted hero panel on the home
> screen that read as a second, larger accent block — Lume keeps the accent
> to small, sparing touches (selection halos, dots, glows), never a panel
> tint.
>
> Version 2.2 — 2026-08-23 — the owner rejected version 2.1 too: the material
> was right by then, but the **component voice** was not. Measured against the
> owner-supplied Lume application mockups, palaia was spending accent on
> everything that should be neutral. Three rules were added, and they are now
> the load-bearing part of this document: **accent restraint** with a countable
> three-to-six-elements-per-screen budget (§1.1a), a **neutral monospace
> metadata register** for micro-labels, counters, ids, timestamps and metrics
> (§1.2a), and **quiet compact controls** with the raised-surface secondary as
> the default button and at most one accent primary per screen (§2, Actions).
> Consequences: the selected nav item became a near-invisible wash plus a 2px
> accent edge with ink text; card chrome titles became quiet lowercase 12px
> labels with a separate `card__subject` for heads that name a thing; the serif
> retreated to prose and page titles moved to sans; metrics moved to mono; and
> the mockups gained padding and gap so they breathe like the reference does.

## 0. What palaia looks like, in one paragraph

palaia is an appliance for a person's accumulated knowledge, so it looks like a
well-kept **archive materialised out of light**, not like a control panel: Lume's
light-as-material thesis — every surface a soft directional gradient, borders that
catch light from above, selection and focus as a glow rather than a flat tint. The
canvas is a cool light grey; cards are white surfaces floating on it. palaia's own
accent, **atelier** (studio-lamp warmth: the agent as craftsman lighting the work),
appears *sparingly* — a selection edge, a small dot or glow, the one primary
button, a tiny highlight — and never as a panel wash or as the colour of a label.
Prose is set in the serif; everything the machine says about itself — micro-labels,
counters, ids, timestamps, metrics — is neutral monospace. Type is small and calm;
whitespace does the separating; colour appears where something is *true about the
system* — healthy, needs attention, broken — communicated through text and icon
colour, never a filled pill or a status-tinted block. Nothing blinks, nothing
gradients for decoration beyond Lume's own material recipes, nothing shouts except
the one, rare, capped **Signal** moment a view is allowed (§1.1,
`principles.md` rule 6). If a screen looks like an admin panel from 2015, it is
not done (UX rule 6).

Three deliberate consequences:

1. **One accent, spent sparingly — semantic colour otherwise, plus the rare
   Signal.** Atelier means "you can act on this" or "this is the selected one".
   Count the accent-coloured elements on a finished screen: the target is **three
   to six**, matching the Lume reference application (§1.1a). Success/warning/error
   mean state, in text only. Signal is a fourth, palette-independent colour
   reserved for at most one element per view, the single most important commitment
   on the screen — it is not a second accent (see §1.1 and `principles.md` rule 6).
2. **Serif for prose, sans for work, mono for machine text.** The serif carries
   sentence-length content — the health briefing, a wizard question, a note body,
   an empty-state explanation — not chrome. Endpoints, tool names, commits, diffs,
   frontmatter, metrics, counters, timestamps and uppercase micro-labels are
   monospace: they are literal or numeric strings, and the mono register is what
   makes them read as the system talking rather than as emphasis (§1.2a).
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
   that appears in `colors_and_type.css` for shipped product code. The five
   static mockups are the one deliberate exception: they carry that same
   `@import` so a human reviewing them in a browser sees the real Lume
   typefaces, not the fallback stacks. Fallback stacks stay in place under it
   for offline/blocked-network rendering; the only external requests any
   mockup makes are to `fonts.googleapis.com` and `fonts.gstatic.com`.
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
| `accent` (atelier) | The **selected** thing (a 2px edge bar, sometimes a glow halo), the **one** primary button, small dots and glows on live controls, and hairline highlights | State; decoration; panel-sized fills; the resting colour of a link, a label, a counter, an avatar or the brand mark |
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

### 1.1a Accent restraint — the three-to-six rule

The accent is a budget, not a palette. On a finished screen, **count every
element that renders in the accent colour**; the target is **three to six**,
which is what the Lume reference application spends. Everything that is not on
this list is neutral:

| Allowed to be accent | Not accent — use this instead |
|---|---|
| The 2px selection edge bar on the selected nav item, tree row, list row, step or tab | — |
| The selection wash: a left-anchored breath of `accent-subtle` that dies out before mid-row (`--p-sel-wash`); data rows may use Lume's fuller two-stop halo (`.lume-selected`) | A tinted pill, a full-width tint on a card-sized target, or accent-coloured text in the selected row — the label stays **ink** |
| **One** `btn--primary` per screen (zero is fine when nothing is the obvious next step) | Every other action: `btn` (raised surface), `btn--quiet`, `btn--ghost`, `btn--risk` |
| Small lit controls: a `dot--live` pulse, a switch that is on, a filled step numeral, the selected graph node, the accent radio dot | Status dots on metric tiles (drop them — the sub-line carries state), tinted marks, tinted chat bubbles, coloured avatars |
| A single highlighted column in a sparkline, a 2px accent edge on a quoted block | An accent-tinted block, a whole accent-coloured sparkline |
| Link and wiki-link **hover** / focus | The resting link colour, which is ink on a hairline underline (`--p-underline`) |

If the count is above six, the screen is warm-washed and reads as a different
product from the Lume reference. The usual culprits, in order: labels, counters,
links, avatars, brand marks, and more than one primary button.

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
| Wizard question | serif, weight 400 | `display` | 32px / 40px | 33px |
| Health verdict (home), note title, empty-state title | serif, weight 400–600 | `h1` / `h2` | 24px / 20px | 26px / 21px |
| Page title, section heads | **sans** | `h2` | 20px | 21px (was serif) |
| Metric | **mono**, tabular numerals | `h1` | 24px / 28px | 26px, serif |
| Card **subject** (`card__subject` — a head that names a thing, not the container) | sans, 600 | between `h3` and `body` | 15px | — |
| Field label, lead paragraph (a sentence → serif) | sans / serif | `h3` | 16px | 17px |
| Body | sans | `body` | 14px, leading 22px | 15px |
| Dense UI (rows, table cells, buttons) | sans | `body-sm` | 13px | 13px (unchanged) |
| Card **chrome** title (`card__title`), chips, hints | sans, 500 | `caption` | 12px | 16px, 600 |
| Counters, timestamps, revisions, system strings (`t-meta`) | mono | sub-caption | 11px | 12px sans |
| Uppercase micro-label (`t-over`, table headers, `dl` label columns) | mono, 500, tracking `.08em` | sub-caption | 10px | 12px sans |
| Endpoints, tool names, commits, diffs, frontmatter | mono | `mono` / `mono-sm` | 13px / 12px | 12–13px (unchanged) |

Lume tops out at `display` (32px); the old 42px onboarding-only display size has
no Lume equivalent and is retired. Sentence case everywhere, including buttons
and headings; **container chrome labels are lowercase** (§1.2a). No italics
except for a quoted vault name or an emphasised word inside prose (which, per
Lume's register rule, would be the serif channel already).

The two sub-caption steps (10px, 11px) are mono-only and never carry sentence
text. They are not an invention: the Lume reference application sets its
micro-labels and meta strings at 9.5–11px (the KPI tile labels, the
`LAYERS`/`SOURCES` rail labels, the `rev 4 · 14:08` container metas), and these
are those two sizes rounded onto whole pixels. Lume's 12px caption floor still
governs everything in the sans register.

### 1.2a The metadata register, and the two kinds of heading

Two rules make palaia read like the Lume reference rather than like a generic
admin panel, and they are worth stating on their own.

**1. Metadata speaks in neutral mono.** Anything the system says *about* content
— an uppercase micro-label, a counter, a revision, a timestamp, an id, a
column header, the label column of a definition list — is Geist Mono in
`text-tertiary` (or `text-secondary` when it must be read), with `.08em`
tracking when uppercased and `tnum` always on. It is never accent-coloured, never
wrapped in a bordered pill, and never bold. A nav counter is `12`, not a badge
saying `12`. Metrics belong here too: mono tabular numerals in ink, with the unit
as a small neutral sans word beside them.

**2. A card head has two possible voices.** `card__title` is the *container*
label — 12px, weight 500, `text-secondary`, **lowercase** ("activity",
"clients", "next in queue"), exactly as the Lume containers are labelled
("prepared briefing", "this week", "knowledge graph · current snapshot"). Its
right-hand slot is a mono meta string. When the left slot instead names a
**subject** — "Claude Code", "Acme Corp — contract terms" — it is a real heading
and uses `card__subject` (15px/600, ink). Getting this backwards is what makes a
dashboard shout: eight 16px bold headings competing with the content they label.

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

Buttons are **small and quiet**. The default button is the raised-surface
secondary; the accent-gradient primary is the exception, capped at one per
screen. A screen with no primary at all is a legitimate outcome — the Lume
reference application's editor screens have none.

| Component | Anatomy | States | Rules |
|---|---|---|---|
| `btn` (secondary — **the default**) | 30px, `bg-surface-raised` gradient + hairline directional `line-subtle` border + top-edge highlight, 13px/500 label; hover adds an `accent-subtle` wash over the gradient | hover, active, focus-visible (Lume focus ring), disabled | Use this unless the action is *the* next step. Two or three of these side by side is the normal action bar |
| `btn--primary` | Same 30px box, accent gradient fill (top→hover stop), two-stop accent glow, optional leading icon | as above | **One per screen, at most.** It counts against the accent budget (§1.1a) |
| `btn--signal` | Same anatomy as `btn--primary`, palette-independent Signal fill/glow instead of accent | as above | **At most one across the entire dashboard's currently-visible view**, and only for the single most important, one-time commitment — see `principles.md` rule 6. Not a second `btn--primary`; do not reach for it for a routine action |
| `btn--quiet` / `btn--ghost` | hairline border only / text only, `text-secondary` | as above | Row-level and tertiary actions |
| `btn--risk` | transparent fill, border/text = `state.error.edge`/`state.error.fg` (the one semantic state with a real border token), low-alpha error wash on hover | as above | Revoke, reject, delete. Never filled red |
| `btn--sm` / `btn--lg` | 25px / 34px | — | `sm` inside rows, tiles and cards; `lg` only for a wizard's forward action |
| `btn--block` | full width | — | Only where the container really is one column wide *and* the action is not the primary; a full-width accent slab is the loudest object on any screen |
| `iconbtn` | 28px square, ghost | hover, focus | Needs `title`; never the only path to an action |
| `kbd` | 18px key cap, mono 10px, hairline border | — | Shown next to an action that has a shortcut, not in a legend somewhere else |

### Surfaces & structure

`card` (+`--flat`, `--raised`) with `card__head` / `card__title` or
`card__subject` (§1.2a) / `card__body` / `card__foot` — a card is a **white
surface floating on the cool canvas**: the `bg-surface` gradient pair, a hairline
directional border, a 1px top-edge highlight and `--shadow-raised`, never a flat
fill and never a tint (see below on `tile--attention`). `card__head` carries a quiet lowercase container label on
the left and a mono meta string on the right; actions belong in `card__foot`, not
in the head. Cards get generous internal padding (20px body, 16/20 head) and sit
20px apart — the reference application breathes, and density comes from smaller
metadata type, not tighter boxes. `tile` (metric tile, on the *raised* gradient
since it nests inside a surface; `--attention` colours **the number and nothing
else** — no fill, no coloured border, no status dot, no coloured sub-line — which
is how the Lume reference renders its own `Δ vs. last wk  −4.2 %` tile. This
matters more than it looks: Lume's `warning` token is an olive-brown that sits
close to atelier, so a *sentence* in warn reads to the eye as another accent
element, while one short numeral does not); `banner`
(info / warn / ok — a neutral gradient surface whose icon and title take the
state colour; the box itself never does. An explanation with an optional
title, never a bare error string); `sep`; `scrollpane` (thin themed
scrollbars); `pane` (explorer column with its own sticky head). No card, tile
or hero panel is ever tinted with the accent as a background wash — accent
stays confined to small touches (a dot, a glow, a 2px selection edge), per
§1.1; a panel-sized accent tint reads as a second, competing accent block.

### Navigation

`sidebar` (brand — a **neutral** raised chip, not an accent tile; the shell
spends no accent on branding — grouped `nav__item`s with mono `nav__count`
numbers, footer with operating mode and version), `topbar` (sans page title +
one-line sentence subtitle — or a mono `t-meta` line when the subtitle is a
date/clock — command bar `⌘K`, global health badge, **neutral** avatar),
`tabbar` (in-card tabs; the active tab is a 2px accent bottom edge and ink text,
nothing else), `segmented` (small mutually exclusive choices, e.g. tool
profiles; the active segment is a raised neutral surface), `steps` (wizard rail
with done/current/upcoming), `numstep` (numbered step inside a flow).

**The selected nav item is the quiet treatment**, and this is the single most
visible difference from an admin panel: a near-invisible left-anchored
`accent-subtle` wash (`--p-sel-wash`) plus a **2px accent edge bar**, with the
label and icon staying **ink** — never an accent-tinted pill, never accent text,
never a bold accent icon. The same treatment carries `steps`, `numstep`,
`listrow--selected`, `clientrow--on`, `tree__row--on` and the checklist's current
row. Lume's fuller two-stop glow halo (`.lume-selected`) is reserved for **data**
rows, where the surrounding rows are also data and the halo has to carry the
selection on its own. In `steps` and `numstep`, done = neutral disc + success
ring; the current step additionally gets the one small accent-filled numeral
disc; peer steps in a flow that has no "current" (e.g. connect-client's three
instructions) are **all** neutral mono discs.

### Data display

`table` (hairline rows, no zebra, **mono uppercase micro-headers** in
`text-tertiary`, horizontally scrollable in its own wrapper), `listrow` (icon +
title + meta + trailing mono value/action; `--selected` uses the quiet wash + 2px
edge, not a fill), `feed` (activity item: neutral mark, sentence, provenance
chips, mono relative time, hover action — the mark's colour carries the event
type only when that type is a semantic state, and is neutral otherwise; never a
coloured circle fill), `diff` (two columns at
≥ 768px, stacked below; `dline--add` / `--del` / `--same` render as a coloured
left edge plus a coloured `+`/`−` glyph on a neutral row — **never a coloured
block fill behind the line**, per the text-only state rule), `graph` (local
relation graph as inline SVG: pill nodes, typed edge labels, dashed nodes for
forward references — never a global hairball), `snippet` (mono block + copy
button; wraps rather than truncates), `qr`, `fm` (frontmatter key/value list),
`commitrow`.

### Status

`badge` (neutral / ok / warn / risk / info — **text and optional `dot` only, no
pill background or border**, per `colors_and_type.css` §2.6; there is no
`badge--accent`, because a badge is metadata and metadata is neutral. `--ok` is
the resting state, so its *dot* is green and its words stay neutral — the same
reading as "10 connectors live" in the Lume reference; `--warn` and `--risk` do
colour their text, because those are the states worth saying out loud), `dot`
(+`dot--live`, the accent pulse for event-stream-backed liveness), `chip` (provenance: which
agent, which session, which capture id; `chip--mono` for identifiers — a neutral
tag, not a status indicator, so it may still carry a background wash), `waiting`
(three-dot inline indicator with a sentence saying what is being waited for —
Lume's one sanctioned non-skeleton loading affordance), `skeleton`
(`lume-skeleton`, a linear pulse for content that has not arrived yet — the
default loading treatment everywhere else), `meter` (accent-fill bar with a
soft accent-glow underneath, on a sunken track — reads as lit, not painted).

### Forms

`field` (label + control + hint — hints explain *why*, not *what*), `input`
(`bg-surface-raised` gradient, directional border, top-edge highlight; focus =
the Lume glow ring, not a flat outline; `+input--readonly` for machine-owned values like
paths, which get a `Change…` button rather than becoming editable text),
`switchrow` (toggle + label + consequence; the "on" track is accent-fill with a
small glow — a switch is one of the few places the accent is allowed to be a
fill), `radiocard` (a choice with its trade-offs: "choose this if…", what works,
what does not — **the selected card gets a hairline accent border and a 1px
accent-glow ring, and nothing else**: a 640px-wide card is far too much area to
tint, so the filled accent radio dot carries the choice. The same "resting
active" treatment the Lume reference gives an active container),
`clientcard` (same selected treatment), `preview` (dashed panel showing what the
machine will see, e.g. generated tool names).

### Empty & first-run

`empty` (mark — a small **neutral** raised icon chip; an empty screen has nothing
selected, so it has nothing to spend accent on — serif title at weight 400, one
explanatory sentence, one or more next actions) plus the compact inline variant
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
network requests beyond the Google Fonts `@import` for Geist / Geist Mono /
Source Serif 4 (§1, decision 3) — the one exception to palaia's normal
self-hosted/bundled font rule, made so a human reviewing a mockup in a browser
sees Lume's real material instead of a system-font approximation. Open one in a
browser — or several, at 360 / 768 / 1280 — and use the thin dashed bar at the
top to switch state or force a theme (that bar is scaffolding, not product).
Everything in them is fake data; nothing talks to a backend. Every mockup binds
`atelier` as the active accent inline; Lagoon and Petrol are present in every
mockup's token block, gated behind `data-accent`, so the accent-switch story
stays visible and testable in code without any of the mockups needing a second
copy.

All five files carry the same shared block — tokens **and** the component layer,
from the bare `:root{` through `.state{display:none}` — byte-identically; only
the comment header above it, the `<title>`, the per-screen CSS after it and the
markup differ. Keep it that way: a change to a shared component means the same
edit in all five files, and `md5` of that slice must match across them.

**When you change a token**, change it in
[`../lume/colors_and_type.css`](../lume/colors_and_type.css) first, then mirror
it here and in every mockup's shared block, then in `v3/web`.
