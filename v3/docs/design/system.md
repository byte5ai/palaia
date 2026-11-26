# palaia v3 — design system

> The binding specification of how palaia looks, reads and behaves on its
> surfaces: the dashboard (`v3/web`), the docs site (`v3/site/docs`), the
> pages the server renders itself (sign-in, setup, installer), the in-chat
> panels, and the website. The do/don't rules per screen are in
> [`principles.md`](principles.md).
>
> Version 4 — 2026-11-26 — **"Simplicity is king", written down.** Version 3
> (2026-10-23) replaced the Lume/atelier look after the 3.0.0-rc4 installation
> test (issues #569, #570, #571), with the self-hosted tools people trust at
> home as its models: Home Assistant's settings, umbrelOS, Synology DSM's
> health card. A review against that system's own rules, WCAG and the
> documented design systems of leading web products (issue #642) led the
> owner to Inter and 8 px buttons, to 14 px body text and 36 px controls, and
> to control edges at 3:1. Version 4 (issue #672) makes the result one
> specification: every value lives in `tokens.json`, the token tables below
> are generated from it, and what a machine can check is checked (§7).
> Earlier versions are in git history; [`lume/`](lume/) is kept as history
> only.

## 0. What palaia looks like

palaia is an appliance on a small always-on box, and it looks like the
software that comes with a good one: calm white cards on a light grey ground
(a deep navy one in dark mode), one neutral typeface, one cyan mark, and plain
sentences. Every page answers one question at the top — is palaia running,
which AI apps work, where is my information, what needs me — with the state
first, then the one thing to do, then the details. Status is always a word and
a colour together ("● Running"), never colour alone. What most people never
change sits behind an "Advanced" disclosure. Light and dark are the same
design from the same tokens.

Ten principles, in order of precedence:

1. **One font family.** Inter for everything. Days One only for the wordmark
   (and the website's hero headlines); the system monospace only for commands,
   addresses, access keys and numeric columns.
2. **One brand colour.** `brand` cyan marks palaia — the star, illustrations.
   `action` blue is the colour of buttons, links and selection. No other
   accents.
3. **One primary action per view.** One filled button, or none. Everything
   else is secondary, plain or a row.
4. **Status as word + colour**, in one of five tones (§1.1). A state that
   says nothing ("Not connected") is plain text, not a pill.
5. **Plain words first** (§3). Technical terms only where people type them.
6. **Advanced settings collapsed.** Simple and advanced change what is shown,
   not what is possible.
7. **Defaults that work.** A fresh palaia is safe and useful without opening
   Settings.
8. **Light and dark from the same tokens.** A component never states a
   colour; the theme only swaps token values.
9. **Every value is a token.** A colour, a type size, a radius, a duration or
   a breakpoint that is not in `tokens.json` is not part of palaia.
10. **Readable before dense, then dense.** Sentences at 13 px or more,
    metadata at 12 px or more, nothing uppercase; within that, the density of
    a working tool: 14 px body text, 36 px controls, 44 px table rows.

## 1. Tokens

[`v3/design/tokens.json`](../../design/tokens.json) is the one source.
[`v3/design/gen-tokens.mjs`](../../design/gen-tokens.mjs) turns it into

- `v3/web/src/styles/tokens.css` — the dashboard's custom properties, named
  exactly as in `tokens.json` (`--canvas`, `--type-title-1-size`,
  `--space-5`, `--radius-sm`, `--control-height`, `--duration-quick`, …);
- `v3/site/docs/src/styles/palaia-tokens.css` — Starlight's colour and font
  variables mapped onto the same values;
- the tables in this section, between the `<!-- generated:… -->` markers.

All three are committed. Change a value in `tokens.json`, run
`node v3/design/gen-tokens.mjs`, commit everything it wrote. Never edit a
generated file or a generated table by hand: the test suites fail when one
disagrees with `tokens.json`.

Light is the default; dark applies under `prefers-color-scheme: dark` unless
`<html data-theme="light">` pins light, and always under `data-theme="dark"`.
Settings › General › Appearance sets that attribute (System / Light / Dark).

### 1.1 Colour

<!-- generated:color:start -->
| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `canvas` | #F5F7FA | #0F1520 | Page background behind cards. |
| `surface` | #FFFFFF | #161D2A | Cards, dialogs, the sidebar, inputs. |
| `surface-muted` | #EEF1F5 | #1C2433 | Hover and pressed rows, sunken areas, code blocks. |
| `border` | #E3E7ED | #263043 | Card edges and dividers. Not for the edge of a control: it reaches only 1.2:1. |
| `border-control` | #808B9B | #6F7B8C | The edge of inputs, selects, text areas and the search box: 3:1 or more against surface and surface-muted (WCAG 1.4.11). |
| `text` | #1D232C | #E8ECF1 | Titles and body text on canvas or surface. |
| `text-2` | #4B5563 | #AEB6C2 | Descriptions and helper text. |
| `text-3` | #667080 | #8B95A3 | Metadata only (timestamps, counts); never below 12px. |
| `brand` | #009FE3 | #009FE3 | palaia cyan: wordmark star, focus ring, selection marker, illustrations. Never as a background behind white text. |
| `action` | #0369A1 | #38BDF8 | Primary buttons and links. |
| `action-hover` | #04618F | #7DD3FC | Hover state of primary buttons and links. |
| `on-action` | #FFFFFF | #0A0F1A | Text on a primary button. |
| `focus` | #0369A1 | #009FE3 | 2px focus ring with 2px offset on every interactive element (light uses the action blue: the cyan reaches only 2.97:1 on white). |
| `ok` | #157A3A | #4ADE80 | Status text and dot: connected, running, backed up. |
| `ok-bg` | #E8F2EB | #1E3C38 | Status pill background for ok. |
| `warn` | #8A5A0A | #FACC15 | Status text and dot: needs attention, restart needed. |
| `warn-bg` | #F3EEE6 | #3A3927 | Status pill background for warn. |
| `error` | #B91C1C | #F87171 | Status text and dot: failed, cannot reach; destructive text buttons. |
| `error-bg` | #F8E8E8 | #3A2A35 | Status pill background for error. |
| `info` | #0369A1 | #38BDF8 | Status text and dot: waiting, in progress. |
| `info-bg` | #E6F0F6 | #1B374B | Status pill background for info; the selected sidebar item. |
| `neutral` | #4B5563 | #AEB6C2 | Status text and dot: off, not set up. |
| `neutral-bg` | #EDEEEF | #2E3542 | Status pill background for neutral. |
| `scrim` | rgba(15,21,32,.5) | rgba(15,21,32,.5) | The veil behind a dialog, a side panel and the drawer; the one colour that is not opaque. |
<!-- generated:color:end -->

**Surfaces.** `canvas` is the page; `surface` is anything that sits on it
(cards, dialogs, the sidebar, inputs); `surface-muted` is a hover row, a sunken
area or a code block. Nothing else: no accent palettes, no gradients, no
glows, no coloured side stripes on cards.

**Edges.** `border` (1.2–1.4:1) is for card edges and dividers only. The edge
of anything a person operates — an input, a select, a text area, the search
box, a secondary button — is `border-control`; checkboxes, radios and the off
switch are outlined in `text-3`.

**Status tones** — a tone colour on its own tinted ground, always with a
word:

| Tone | Means | Typical words |
|---|---|---|
| `ok` | Working, nothing to do | Running, Connected, Backed up |
| `info` | In progress, wait | Waiting for first use, Indexing |
| `warn` | Act soon | Needs Cloud mode, Restart needed |
| `error` | Broken, act now | Can't reach, Failed |
| `neutral` | Off or not started | Off, Not set up, Unreviewed |

`brand` is never a ground behind white text (it reaches 2.97:1 on white).

### 1.2 Type

<!-- generated:type:start -->
| Style | Size / line | Weight | Family | Use |
| --- | --- | --- | --- | --- |
| `display` | 48 / 56 | 400 | display | Website hero headlines and the wordmark only. |
| `wordmark` | 20 / 28 | 400 | display | The palaia wordmark in the sidebar, the app bar and setup. |
| `title-1` | 24 / 30 | 600 | sans | Page title. |
| `title-1-phone` | 22 / 28 | 600 | sans | Page title below 768px. |
| `title-2` | 16 / 22 | 600 | sans | Card, section and dialog titles. |
| `body-strong` | 14 / 20 | 600 | sans | Row titles, labels, buttons. |
| `body` | 14 / 20 | 400 | sans | Running text. |
| `secondary` | 13 / 18 | 400 | sans | Descriptions and helper text; the smallest size for sentences. |
| `caption` | 12 / 16 | 600 | sans | Status pills and timestamps; the absolute minimum. |
| `prose` | 16 / 27 | 400 | sans | Docs and long notes. |
| `mono` | 13 / 20 | 400 | mono | Commands, addresses, access keys, numeric columns. |
<!-- generated:type:end -->

`sans` is Inter, `display` is Days One, `mono` is the system monospace stack.
Sentence case everywhere. No uppercase labels, no letter-spaced labels, no
text below 12 px. Running text at most 65 characters per line; page and row
descriptions fit one line (80 characters). Numbers that line up in a column
use tabular figures.

The fonts are self-hosted (OFL); `v3/web/src/assets/fonts/README.md` names
their source. The docs site and the in-chat panels carry the same Inter files;
the server-rendered pages name Inter and fall back to the system font, because
they load nothing.

### 1.3 Space, radius, elevation, sizes, motion

**Space**

<!-- generated:spacing:start -->
| Token | Value | Use |
| --- | --- | --- |
| `space-1` | 4px | Icon to label. |
| `space-2` | 8px | Inside pills and button groups. |
| `space-3` | 12px | Between a label and its control. |
| `space-4` | 16px | Between cards; card padding on phones; page gutter on phones. |
| `space-5` | 20px | Card padding. |
| `space-6` | 24px | Dialog padding; between a page header and content. |
| `space-8` | 32px | Page padding on desktop. |
| `space-12` | 48px | Between page sections. |
| `space-16` | 64px | Website section spacing. |
<!-- generated:spacing:end -->

Everything sits on the 4 px grid. Page padding `space-8` (`space-4` on a
phone); card padding `space-5` (`space-4` on a phone); between cards
`space-4`; between a page header and its content `space-6`.

**Radius and elevation**

<!-- generated:radius:start -->
| Token | Value | Use |
| --- | --- | --- |
| `radius-xs` | 4px | Checkboxes, inline code, chips, keys. |
| `radius-inner` | 6px | An item inside a radius-sm control (a segment, a tree row, a monogram). |
| `radius-sm` | 8px | Buttons, inputs, selects, segmented controls, navigation items. |
| `radius-md` | 10px | Cards, grouped lists, dialogs. |
| `radius-pill` | 999px | Status pills, the switch, count badges. |
<!-- generated:radius:end -->

Buttons are rounded rectangles, never pills; `radius-pill` belongs to status
pills, the switch and count badges. A full circle (`50%`) is for a dot, an
icon's round ground and a radio.

<!-- generated:shadow:start -->
| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `shadow-card` | 0 1px 2px rgba(15,21,32,.06) | none | Cards on the canvas (dark: border only). |
| `shadow-overlay` | 0 12px 32px rgba(15,21,32,.18) | 0 12px 32px rgba(0,0,0,.55) | Dialogs, menus, the drawer. |
<!-- generated:shadow:end -->

Two levels only: a card rests on the page, an overlay floats above it. In
dark mode a card is told apart by its border, not by a shadow.

**Sizes**

<!-- generated:size:start -->
| Token | Value | Use |
| --- | --- | --- |
| `control-height` | 36px (44px on a phone) | Buttons and inputs. |
| `control-height-lg` | 44px | Onboarding buttons. |
| `control-height-sm` | 28px (44px on a phone) | Compact buttons inside rows and card headers. |
| `row-height` | 48px | List rows (taller with a description). |
| `table-row-height` | 44px | Rows of a table that lists a resource. |
| `sidebar-width` | 232px | Sidebar at 1024px and wider. |
| `content-width` | 1120px | Maximum width of app content. |
| `form-width` | 720px | Settings, forms and onboarding. |
| `wizard-width` | 640px | Onboarding panel. |
| `touch-target` | 44px | The smallest area that takes a tap below 768px, also around a checkbox, a radio and the switch. |
| `appbar-height` | 56px | The app bar below 768px. |
| `rail-width` | 64px | The icon rail from 768px to 1023px. |
<!-- generated:size:end -->

A page header's button is the default size; buttons in rows and card headers
are compact. List rows are at least `row-height`, and taller with a
description; a table that lists a resource uses `table-row-height`.

**Motion**

<!-- generated:motion:start -->
| Token | Value | Use |
| --- | --- | --- |
| `duration-quick` | 120ms | A hover, a switch, a chevron. |
| `duration-smooth` | 200ms | The drawer, the progress line. |
| `easing-standard` | cubic-bezier(0.2, 0, 0, 1) | Every transition. |
<!-- generated:motion:end -->

Only short state changes move. Nothing moves on its own except a spinner, a
skeleton and the live dot; all three stop under `prefers-reduced-motion`.

### 1.4 Layout and the shell

- **Desktop**: the sidebar (`sidebar-width`) — the wordmark and the
  notification bell, five places, a divider, Settings, and palaia's state in
  the footer ("● Running · Private", the version, who is signed in). The
  selected item has an `info-bg` ground and `action` text.
- **Tablet**: an icon rail (`rail-width`) with the same items, labels as
  tooltips.
- **Phone**: an app bar (`appbar-height`: menu, wordmark, bell) and the
  sidebar as a drawer.
- **Widths**: app content up to `content-width`; a form or a settings area up
  to `form-width`; the setup panel `wizard-width`.
- Setup and the sign-in page have no sidebar.

**The anatomy of a page**, top to bottom:

1. `PageHeader`: the title (`title-1`), at most one line saying what the page
   is for, and the page's one primary action on the right.
2. Tabs, when the place has more than one view (`TabLinks`; each tab is an
   address).
3. A callout, only while something is blocked or pending, with its fix.
4. The content: cards, a table, or panes.

**Breakpoints**

<!-- generated:breakpoints:start -->
| Name | Width | What changes |
| --- | --- | --- |
| phone | up to 767 px | App bar and drawer, one column, controls at touch size, dialogs as bottom sheets. |
| tablet | 768–1023 px | Icon rail, settings areas as tabs, two panes in Memories. |
| desktop | from 1024 px | Sidebar, settings areas beside the area, three panes in Memories. |
<!-- generated:breakpoints:end -->

A media query uses these widths and no others. Every page works at 390, 768
and 1440 px without a horizontal page scroll.

### 1.5 Iconography

Inline line icons from `v3/web/src/shell/icons.tsx`: 24-unit grid, 1.5 px
stroke, round caps and joins, `currentColor`. Sizes 15 px (inside small text,
chevrons), 18 px (default), 26 px (the Overview verdict), 40 px (empty pages).
An icon never carries meaning alone; an icon-only button has an `aria-label`.
No third-party logos and no emoji: an AI app is marked by a two-letter
monogram. The palaia star (`PalaiaMark`) is the only mark, in `brand`.

### 1.6 Accessibility

The contrast of every pair the system uses, measured from the tokens in both
themes. A pair below its minimum fails the build.

<!-- generated:contrast:start -->
| Pair | Light | Dark | Minimum | Use |
| --- | --- | --- | --- | --- |
| `text` on `surface` | 15.8:1 | 14.2:1 | 7:1 | Titles and body on a card |
| `text` on `canvas` | 14.7:1 | 15.4:1 | 7:1 | Titles and body on the page |
| `text-2` on `surface` | 7.6:1 | 8.3:1 | 4.5:1 | Descriptions and helpers |
| `text-2` on `surface-muted` | 6.7:1 | 7.6:1 | 4.5:1 | Descriptions on a hover row or a muted card |
| `text-2` on `info-bg` | 6.5:1 | 6.1:1 | 4.5:1 | Descriptions on a selected row |
| `text-3` on `surface` | 5.0:1 | 5.6:1 | 4.5:1 | Metadata on a card |
| `text-3` on `canvas` | 4.7:1 | 6.0:1 | 4.5:1 | Metadata on the page |
| `action` on `surface` | 5.9:1 | 7.9:1 | 4.5:1 | Links and plain buttons |
| `action` on `info-bg` | 5.1:1 | 5.8:1 | 4.5:1 | The selected navigation item |
| `on-action` on `action` | 5.9:1 | 8.9:1 | 4.5:1 | The primary button |
| `on-action` on `error` | 6.5:1 | 6.9:1 | 4.5:1 | The confirm button of a destructive dialog |
| `ok` on `ok-bg` | 4.7:1 | 6.9:1 | 4.5:1 | Status pill, ok |
| `warn` on `warn-bg` | 5.1:1 | 7.6:1 | 4.5:1 | Status pill, warn |
| `error` on `error-bg` | 5.5:1 | 4.9:1 | 4.5:1 | Status pill, error |
| `info` on `info-bg` | 5.1:1 | 5.8:1 | 4.5:1 | Status pill, info |
| `neutral` on `neutral-bg` | 6.5:1 | 6.0:1 | 4.5:1 | Status pill, neutral |
| `error` on `surface` | 6.5:1 | 6.1:1 | 4.5:1 | Field errors and destructive buttons |
| `border-control` on `surface` | 3.5:1 | 3.9:1 | 3:1 | The edge of an input or a secondary button |
| `border-control` on `surface-muted` | 3.0:1 | 3.6:1 | 3:1 | The edge of a read-only input |
| `text-3` on `surface` | 5.0:1 | 5.6:1 | 3:1 | The outline of a checkbox, a radio and the off switch |
| `focus` on `surface` | 5.9:1 | 5.7:1 | 3:1 | The focus ring on a card |
| `focus` on `canvas` | 5.5:1 | 6.2:1 | 3:1 | The focus ring on the page |
<!-- generated:contrast:end -->

- Text reaches 4.5:1; the edge of a control and the focus ring reach 3:1
  (WCAG 2.2, 1.4.3 and 1.4.11).
- Every interactive element shows a solid 2 px `focus` ring with a 2 px
  offset on keyboard focus. "Skip to content" comes first; Escape closes
  dialogs, popovers and the drawer; focus stays inside an open dialog and
  returns to whatever opened it.
- Targets are at least `control-height` with a pointer (`control-height-sm`
  for compact buttons) and at least `touch-target` on a phone. A checkbox, a
  radio and the switch keep their size there; the area that takes the tap is
  `touch-target` around their centre.
- Meaning never rests on colour, on an icon or on position alone: a status
  has its word, an icon-only button has its label, a table cell keeps its
  column for a screen reader when the column leaves the screen.
- Pages are checked with axe in the test suite; a serious or critical finding
  fails it.

## 2. Components

React components in `v3/web/src/components/` (Ladle stories next to each),
styles in `v3/web/src/styles/components.css`. A screen composes these; it does
not style its own buttons, pills, rows or fields.

| Component | What it is |
|---|---|
| `PageHeader` | See §1.4. A sub-page that is reached from a list shows where it belongs ("‹ Memories") above the title. |
| `Card`, `CardHeader`, `CardBody`, `CardFoot` | One subject per card: status first, then the action, then details. A card title is `title-2`. Cards in a row share one height; a card's link sits on its bottom edge. |
| `Button`, `LinkButton`, `IconButton` | `primary` (action fill), `secondary` (surface with a `border-control` edge, the default), `plain` (action text), `destructive` (error text on the secondary box), `danger` (filled red — the confirm button of a destructive dialog only). Sizes `md` (default), `sm` (compact) and `lg` (setup). `loading` shows a spinner and keeps the verb ("Preparing the file…"). `IconButton` is a square of `control-height`. |
| `StatusPill` | Dot + word, five tones, `caption` type. (`Badge` is the earlier name, kept as a thin wrapper.) |
| `ListRow` | Optional round icon, title (`body-strong`), one line of description, and on the right a status pill, a value, a control or a chevron. `to` makes it a link, `onClick` a button, `setting` a label-and-control row. For navigation and for settings. |
| `Table`, `.table--flush` | The list of a resource (AI apps): one row per item, a header row, group rows ("In use · 2"), the row's one action on the right. It fills its card edge to edge. Below 768 px the secondary columns go and the status moves under the name, still a table cell for a screen reader. |
| `Field`, `LabeledInput`, `Switch`, `Segmented` | Label above (`body-strong`), "Optional" after the label of optional fields only, helper below, an error replaces the helper. Placeholders are examples, never instructions. A select is an `.input` with the system's own chevron, never the browser's. |
| `Callout` | A tinted box for a blocked or pending state: tone icon, a one-sentence title, at most one more sentence, and the button that fixes it when the dashboard can. |
| `Disclosure` | "What's included?", "Advanced", "Troubleshooting" — closed by default. |
| `EmptyState`, `InlineEmpty`, `LoadingState`, `ErrorState` | An empty page or pane (40 px icon, title, one sentence, one action); an empty section (one line); loading as skeleton lines after 300 ms; an error as a callout with the cause, **Try again** and **Details**. An error never looks empty. |
| `Dialog`, `ConfirmDialog` | Create or confirm: title and close, the form, Cancel plus one primary. A destructive confirm names the object and the action ("Revoke access"). A bottom sheet below 768 px. `size="side"` is the same modal as a full-height panel on the right, for the details of one table row; the row's address carries it (`/apps?app=codex`). With two open, only the topmost answers Escape. |
| `Toast` | A passing confirmation of something the person just did ("Copied"), with Undo where there is one. Never for an error and never the only place something is said. |
| `Stepper`, `StepperPanel` | Full-page flows (setup): wordmark bar with "Step 2 of 5", a progress line, the step list on desktop, one panel with Back on the left and the step's action on the right. A step is `done` only when palaia confirms it; `attention` when it needs a fix or a restart. |
| `TabLinks` | Tabs that are addresses (Memories › Needs review), so a tab can be bookmarked. |
| `RestartButton`, `RestartCallout` | "Restart palaia to apply your changes": the button where palaia can restart itself, the server command where it can't. |

## 3. Words and voice

palaia speaks like a competent colleague: plain, concrete, honest about
limits, never cheerful about nothing. The binding rule above all others is
`principles.md` §0.1 — no jargon in the surface.

1. **Name the action and its effect.** Buttons are verb + object ("Download
   backup", "Create access key"); descriptions say what happens ("Download a
   copy of your memories and settings.").
2. **When something is blocked, say why and give the next step in the same
   place** ("Backups need dashboard sign-in" + **Turn on dashboard sign-in**).
   A server command is the secondary path, under a disclosure, never the only one.
3. **No metaphors, marketing claims or internal references** — no spec or
   issue numbers, file names, literal backticks, git hashes or raw ISO
   timestamps.
4. **Say "you" to the person and "palaia" for the product** — lowercase, also
   at the start of a sentence. Not "the hub", not "we", not "the system".
5. **One idea per sentence.** Explain a concept once, where it is first
   needed; no footer repeated on every page.
6. **Times and counts the way people say them**: "2 min ago", "Updated 23 Oct,
   15:35" (the exact time in a tooltip), "1 of 9 connected".
7. **Errors**: "Couldn't …" or "Can't …", then the cause, then **Try again**
   and **Details**.
8. **Name a client exactly** (`principles.md` §0.2): "Claude Code CLI", never
   a bare "Claude Code".
9. Sentence case, no exclamation marks, no "Oops", no emoji.

### Glossary — one term per concept

| Concept | Say | Notes |
|---|---|---|
| Product, server | **palaia** | "server" only in host and command-line instructions |
| Vault | **memory**, **memories** | "vault" only in docs and tool names |
| Client | **AI app** | "agent" only for live sessions |
| Per-client token | **access key** | "token" only inside snippets |
| Tool profile | **tool set** | under Settings › Advanced |
| Owner login | **dashboard sign-in**, **owner account** | never just "sign-in" for AI app keys |
| `auth_enabled` | **AI apps need an access key** | |
| `dashboard.require_sign_in` | **Require sign-in for this dashboard** | |
| Modes | **Private**, **Cloud**, **Public** | config values stay `locked`, `cloud`, `open`; each mode name comes with its outcome line |
| Unfiled captures | **To file** | |
| Curator proposals | **Needs review** | |
| Embeddings | **search index** | shown only while it is not ready |

## 4. Information architecture

| Place | Address | Tabs / areas | Was |
|---|---|---|---|
| Overview | `/` | — | Home |
| Memories | `/memories` | Browse · Needs review (`/memories/review`) | `/explorer`, `/review-queue` |
| AI apps | `/apps` | Apps (an app's panel: `/apps?app=<id>`) · Live sessions (`/apps/sessions`) | `/clients`, `/agents` |
| Add-ons | `/add-ons` | Installed · Browse | `/marketplace` |
| Automations | `/automations` | Automations · Webhooks | `/automations` |
| Settings | `/settings` | General (`/settings`: what this palaia is, each area's state, Appearance), Access & sign-in, Backups, Telegram, Advanced, About & updates (`/settings/…`) | `/exposure`, `/backups`, `/telegram`, `/tools` |

Every old address redirects to its new place with its query string
(`v3/web/src/routes/index.tsx`, `REDIRECTS`). The packaged image proxies only
`/telegram/webhook` to the hub, so `/telegram` reaches the dashboard.

## 5. The mockups

The five HTML files in [`mockups/`](mockups/) and the screenshots under
[`review/`](review/) show the Lume design (versions 2–2.3). They are kept as
history and are **not** a reference for the current look; the reference is
this file, the Ladle stories (`npm run storybook` in `v3/web`) and the running
dashboard.

## 6. Patterns

Which component for which job. A screen that needs something else brings it
here first.

| Job | Pattern |
|---|---|
| **A list of things of one kind** that have the same attributes (AI apps, tool sets, bots, backup folders) | A table in a card: name first, state as its own column, one action per row. Not a stack of cards and not rows with pills pushed to the right. |
| **A list to move through** (Settings › General, the Overview's memories) | `ListRow`s in a card, a chevron on the right. |
| **The details of one item** in a table | A side panel (`Dialog size="side"`) with its own address. The table stays visible behind it. |
| **Several areas of one place** | Tabs when they are views of the same thing (Memories: Browse, Needs review); a navigation beside the area when they are separate subjects (Settings). |
| **A choice between a few exclusive options with consequences** | Choice cards (`.radiocards`): name, one line saying what follows, the current one marked. |
| **A choice between a few short options** | `Segmented`. |
| **On or off** | `Switch` in a setting row, the label on the left. A switch acts at once; a setting that needs a restart says so in a `RestartCallout`. |
| **Creating or editing one thing** | A `Dialog` with the form; the primary button names the result ("Create automation"). A long or multi-step form is a page of its own. |
| **Something destructive** | A `destructive` button, then a `ConfirmDialog` that names the object; only its confirm button is filled red. |
| **Something is blocked** | A `Callout` in place that names the reason and holds the fix. Never a modal, never a disabled control without a reason beside it. |
| **Nothing there yet** | `EmptyState` with how it fills and the one step that starts it. |
| **Something to copy** | A `.snippet` with a **Copy** button; the button says "Copied" for a moment. |
| **Feedback after an action** | The changed state itself (the row now says "Connected"); a toast only when nothing visible changes. |
| **A value the person may need exactly** | The plain form on screen ("2 min ago"), the exact one in a tooltip. |

## 7. What is enforced

| Rule | Where it fails |
|---|---|
| Generated stylesheets and the tables in this file match `tokens.json` | `gen-tokens.mjs --check` (dashboard and docs-site lint and tests) |
| Every declared colour pair reaches its minimum contrast | `gen-tokens.mjs` |
| No literal colour, type size, radius or transition duration in the dashboard's source | `v3/web/scripts/lint-tokens.mjs` |
| Media queries only at the breakpoints | `lint-tokens.mjs` |
| Every custom property that is read exists | `lint-tokens.mjs` |
| The in-chat panels, the sign-in page and the setup page carry the token colours, the typeface and the radii | `server/tests/gateway/test_apps_shell.py`, `server/tests/oauth/test_page_design.py`, `server/tests/deploy/test_setup_page.py` |
| No serious accessibility finding on a page | `v3/web/src/a11y.test.tsx` and the per-screen axe tests |
| No implementation word in a heading, button, pill or label | the "no jargon in the surface" tests per screen |

What a machine cannot check — one primary action per view, the right pattern
for the job, the words — is checked in review with the list in
`principles.md` §5.

## 8. The other surfaces

- **Docs site**: Starlight with palaia's colours and fonts from the generated
  `palaia-tokens.css`; Days One for the site title only.
- **Sign-in, setup and installer pages**: rendered by the server before any
  session or build exists, so they carry the token values inline and load
  nothing. Same colours, typeface name, radii and one filled button.
- **In-chat panels**: one compact panel inside a chat, not an application.
  The same tokens, the upright Inter file embedded, and the small set of
  components a panel uses (card, status pill, button, list row, input).
- **Website**: its own repository; it follows these tokens and fonts.
