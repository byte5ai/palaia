# palaia v3 — design system

> How palaia looks, reads and behaves on its three surfaces: the dashboard
> (`v3/web`), the docs site (`v3/site/docs`) and the website. The do/don't
> rules per screen live in [`principles.md`](principles.md).
>
> Version 3 — 2026-10-23 — **"Simplicity is king."** The owner replaced the
> Lume/atelier system (versions 2–2.3) with this one after the 3.0.0-rc4
> installation test (issues #569, #570, #571): the admin UI read as dated and
> confusing, its words described palaia's internals instead of the person's
> task, and the dashboard looked like a different product from the website
> and the docs. The benchmarks are the self-hosted tools people already trust
> at home — Home Assistant's settings, umbrelOS, Synology DSM's health card,
> Hermes — for an audience that includes people who otherwise only use a Mac.
> Versions 1–2.3 of this file are in git history; [`lume/`](lume/) is kept as
> history only.

## 0. What palaia looks like, in one paragraph

palaia is an appliance on a small always-on box, and it looks like the
software that comes with a good one: calm white cards on a light grey ground
(a deep navy one in dark mode), one friendly typeface, one cyan mark, and
plain sentences. Every page answers one question at the top — is palaia
running, which AI apps work, where is my information, what needs me — with
the state first, then the one thing to do, then the details. Status is always
a word and a colour together ("● Running"), never colour alone and never a
sentence the reader has to decode. What most people never change sits behind
an "Advanced" disclosure. Light and dark are the same design from the same
tokens.

Eight principles, in order of precedence:

1. **One font family.** Nunito Sans for everything. Days One only for the
   wordmark (and the website's hero headlines); the system monospace only for
   commands, addresses, access keys and numeric columns.
2. **One brand colour.** `brand` cyan marks palaia — the star, the selection,
   illustrations. `action` blue is the colour of buttons and links. No other
   accents, no accent switching.
3. **One primary action per view.** Everything else is secondary, plain or
   inside a card.
4. **Status always as word + colour**, in one of five tones (§1.1).
5. **Plain words first** (§3). Technical terms only where people type them.
6. **Advanced settings collapsed.** Simple and advanced change what is shown,
   not what is possible.
7. **Defaults that work.** A fresh palaia is safe and useful without opening
   Settings.
8. **Light and dark from the same tokens.** Components never hard-code a
   colour; the theme only swaps token values.

## 1. Tokens

[`v3/design/tokens.json`](../../design/tokens.json) is the one source.
[`v3/design/gen-tokens.mjs`](../../design/gen-tokens.mjs) turns it into

- `v3/web/src/styles/tokens.css` — the dashboard's custom properties, named
  exactly as in `tokens.json` (`--canvas`, `--text-2`, `--type-title-1-size`,
  `--space-5`, `--radius-md`, `--control-height`, …);
- `v3/site/docs/src/styles/palaia-tokens.css` — Starlight's colour and font
  variables mapped onto the same values.

Both are committed and both test suites fail when either is stale or edited by
hand. Change a value in `tokens.json`, run `node v3/design/gen-tokens.mjs`, commit
all three files. Light is the default; dark applies under
`prefers-color-scheme: dark` unless `<html data-theme="light">` pins light, and
always under `data-theme="dark"`. The dashboard's Settings › Appearance sets that
attribute (System / Light / Dark).

`v3/web/scripts/lint-tokens.mjs` (part of `npm run lint`) rejects a literal
colour or transition duration anywhere in the dashboard's source outside a
custom-property definition, and any `var(--…)` that no stylesheet defines.

### 1.1 Colour

| Token | Light | Dark | Use |
|---|---|---|---|
| `canvas` | #F5F7FA | #0F1520 | Page ground behind cards |
| `surface` | #FFFFFF | #161D2A | Cards, dialogs, sidebar, inputs |
| `surface-muted` | #EEF1F5 | #1C2433 | Hover rows, sunken areas, code blocks |
| `border` | #E3E7ED | #263043 | Card edges, dividers, input borders |
| `text` | #1D232C | #E8ECF1 | Titles and body |
| `text-2` | #4B5563 | #AEB6C2 | Descriptions and helper text |
| `text-3` | #667080 | #8B95A3 | Metadata only, 12 px or larger, on `canvas`/`surface` |
| `brand` | #009FE3 | #009FE3 | The palaia star, selection marks, illustrations — never behind white text |
| `action` / `action-hover` | #0369A1 / #04618F | #38BDF8 / #7DD3FC | Primary buttons and links |
| `on-action` | #FFFFFF | #0A0F1A | Text on a primary (or confirm-red) button |
| `focus` | #0369A1 | #009FE3 | The 2 px focus ring, 2 px offset |

**Status tones** — a tone colour on its own tinted ground, always with a word:

| Tone | Light fg / bg | Dark fg / bg | Means | Typical words |
|---|---|---|---|---|
| `ok` | #157A3A / #E8F2EB | #4ADE80 / #1E3C38 | Working, nothing to do | Running, Connected, Backed up |
| `info` | #0369A1 / #E6F0F6 | #38BDF8 / #1B374B | In progress, wait | Waiting for first use, Indexing |
| `warn` | #8A5A0A / #F3EEE6 | #FACC15 / #3A3927 | Act soon | Needs Cloud mode, Restart needed |
| `error` | #B91C1C / #F8E8E8 | #F87171 / #3A2A35 | Broken, act now | Can't reach, Failed |
| `neutral` | #4B5563 / #EDEEEF | #AEB6C2 / #2E3542 | Off or not started | Off, Not set up, Unreviewed |

Nothing else: no accent palettes, no signal colour, no gradients, no glows, no
coloured side stripes on cards. The one non-token colour is the dialog scrim
(`rgba(15, 21, 32, .5)`, both themes), named once in `components.css`.

### 1.2 Type

| Style | Size / line | Weight | Use |
|---|---|---|---|
| `display` | 48 / 56, Days One | 400 | Website hero; the wordmark (20 / 28) |
| `title-1` | 28 / 34 | 700 | Page title |
| `title-2` | 18 / 24 | 700 | Card, section and dialog titles |
| `body-strong` | 15 / 22 | 600 | Row titles, labels, buttons |
| `body` | 15 / 24 | 400 | Running text |
| `secondary` | 13 / 20 | 400 | Descriptions and helpers — the smallest size for a sentence |
| `caption` | 12 / 16 | 600 | Status pills, timestamps — the absolute minimum |
| `prose` | 16 / 27 | 400 | Docs, and a note's text in Memories |
| `mono` | 13 / 20, system mono | 400 | Commands, addresses, access keys, numeric columns |

Sentence case everywhere. No uppercase labels, no letter-spaced labels, no 10
or 11 px text. Running text at most 65 characters per line; page and row
descriptions fit one line (80 characters). The fonts are self-hosted (OFL,
`v3/web/src/assets/fonts/`), byte-identical to the website's and the docs'.

### 1.3 Space, radius, elevation, motion

- **Spacing** on a 4 px base: `space-1` 4 · `space-2` 8 · `space-3` 12 ·
  `space-4` 16 · `space-5` 20 · `space-6` 24 · `space-8` 32 · `space-12` 48 ·
  `space-16` 64. Page padding 32 (16 on phones); card padding 20 (16 on phones);
  between cards 16; page header to content 24; label to control 12.
- **Radii**: `radius-sm` 10 (inputs, selects, segmented controls), `radius-md`
  14 (cards, grouped lists, dialogs), `radius-pill` (buttons, pills, the
  selected nav item).
- **Elevation**: cards get `shadow-card` in light and only their border in
  dark; dialogs, menus and the drawer get `shadow-overlay`.
- **Controls**: 40 px (`control-height`) for buttons and inputs, 48 px in
  onboarding and for touch, 32 px for compact buttons inside rows. List rows
  56 px, 64 px with a description.
- **Motion**: only short state changes (120–200 ms: a switch, a chevron, the
  drawer). Nothing moves on its own except spinners and skeletons; both calm
  down under `prefers-reduced-motion`.

### 1.4 Layout and the shell

- **≥ 1024 px**: a 248 px sidebar — the wordmark and the notification bell,
  five places, a divider, Settings, and the hub's state in the footer
  ("● Running · Private", the version, who is signed in). The selected item
  is an `info-bg` pill with `action` text.
- **768–1023 px**: a 64 px icon rail with the same items (labels as tooltips).
- **< 768 px**: a 56 px app bar (menu, wordmark, bell) and the sidebar as a
  drawer.
- **Widths**: app content up to 1120 px; settings, forms and onboarding up to
  720 px; the onboarding panel 640 px.
- Onboarding and the sign-in page have no sidebar.

### 1.5 Iconography

Inline line icons from `v3/web/src/shell/icons.tsx`: 24-unit grid, 1.5 px
stroke, round caps and joins, `currentColor`. Sizes 15 px (inside small text,
chevrons), 18 px (default), 26 px (the Overview verdict), 40 px (empty pages).
An icon never carries meaning alone; an icon-only button has an `aria-label`.
No third-party logos, no emoji. The palaia star is the website's mark
(`PalaiaMark`), in `brand`.

### 1.6 Accessibility

| Pair | Light | Dark |
|---|---|---|
| `text` on `surface` | 15.8 | 14.2 |
| `text-2` on `surface` | 7.6 | 8.3 |
| `text-3` on `surface` · on `canvas` | 5.0 · 4.7 | 5.6 · 6.0 |
| `action` on `surface` (links) | 5.9 | 7.9 |
| `on-action` on `action` (primary button) | 5.9 | 8.9 |

- `text-3` is only 4.4:1 on `surface-muted` in light: never put metadata on
  hover rows or code blocks.
- `border` (1.2–1.4:1) is for card edges and dividers; checkboxes, radios and
  the off switch are outlined in `text-3`.
- Every interactive element shows a solid 2 px `focus` ring with a 2 px
  offset on keyboard focus. "Skip to content" comes first; Escape closes
  dialogs, popovers and the drawer; focus stays inside an open dialog and
  returns to whatever opened it.
- Targets at least 40 px (48 px in onboarding); 32 px only for compact row
  buttons.

## 2. Components

React components in `v3/web/src/components/` (Ladle stories next to each),
styles in `v3/web/src/styles/components.css`.

| Component | What it is |
|---|---|
| `PageHeader` | `title-1`, at most one line saying what the page is for, the page's one primary action on the right; a sub-page shows "‹ Settings" above the title. The shell renders it from the route's `handle` unless the page renders its own. |
| `Card`, `CardHeader`, `CardBody`, `CardFoot` | One subject per card: status first, then the action, then details. Settings use one card per group of rows. |
| `ListRow` | Optional 32 px round icon, title (`body-strong`), one line of description, and on the right a status pill, a value, a control or a chevron. `to` makes it a link, `onClick` a button, `setting` a label-and-control row. |
| `StatusPill` | 24 px, dot + word, five tones. (`Badge` is the earlier name, kept as a thin wrapper.) |
| `Button`, `LinkButton`, `IconButton` | `primary` (action fill), `secondary` (surface + border, the default), `plain` (action text), `destructive` (error text on the secondary box), `danger` (filled red — inside a confirm dialog only). 40 / 48 / 32 px. `loading` shows a spinner and keeps the verb ("Preparing the file…"). `IconButton` is 36 px round. |
| `Field`, `LabeledInput`, `Switch`, `Segmented` | Label above (`body-strong`), "Optional" after the label of optional fields only, helper below, an error replaces the helper. Placeholders are examples, never instructions. |
| `Callout` | A tinted box for a blocked or pending state: tone icon, a one-sentence title, at most one more sentence, and the button that fixes it when the dashboard can. |
| `Disclosure` | "What's included?", "Advanced", "Troubleshooting" — closed by default. |
| `EmptyState`, `InlineEmpty`, `LoadingState`, `ErrorState` | An empty page (40 px icon, title, one sentence, one action); an empty section (one line); loading as skeleton lines after 300 ms; an error as a callout with the cause, **Try again** and **Details**. An error never looks empty. |
| `Dialog`, `ConfirmDialog` | Create or confirm: title and close, the form, Cancel plus one primary. A destructive confirm names the object and the action ("Revoke access"). A bottom sheet below 768 px. |
| `Stepper`, `StepperPanel` | Full-page flows (onboarding): wordmark bar with "Step 2 of 5", a 4 px progress line, the step list from 1024 px, one 640 px panel with Back on the left and the primary on the right. A step is `done` only when the hub confirms it; `attention` when it needs a fix or a restart. |
| `TabLinks` | Tabs that are addresses (Memories › Needs review), so a tab can be bookmarked. |
| `RestartButton`, `RestartCallout` | "Restart palaia to apply your changes": the button where the hub can restart itself (`restart_supported`), the server command where it can't. |

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
3. **No metaphors, marketing claims or internal references** — no "This file
   can act as your hub", no "A hundred tools in one conversation ruins an
   agent", no spec or issue numbers, file names, literal backticks, git hashes
   or raw ISO timestamps.
4. **Say "you" to the person and "palaia" for the product** — lowercase, also
   at the start of a sentence. Not "the hub", not "we", not "the system".
5. **One idea per sentence.** Don't repeat the same footer on every page;
   explain a concept once, where it is first needed.
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

| Place | Address | Tabs / sub-pages | Was |
|---|---|---|---|
| Overview | `/` | — | Home |
| Memories | `/memories` | Browse · Needs review (`/memories/review`) | `/explorer`, `/review-queue` |
| AI apps | `/apps` | Apps · Live sessions (`/apps/sessions`) | `/clients`, `/agents` |
| Add-ons | `/add-ons` | Installed · Browse | `/marketplace` |
| Automations | `/automations` | Automations · Webhooks | `/automations` |
| Settings | `/settings` | Access & sign-in, Backups, Telegram, Advanced, About & updates (`/settings/…`); Appearance in the hub | `/exposure`, `/backups`, `/telegram`, `/tools` |

Every old address redirects to its new place with its query string
(`v3/web/src/routes/index.tsx`, `REDIRECTS`). The packaged image proxies only
`/telegram/webhook` to the hub, so `/telegram` reaches the dashboard.

## 5. The mockups

The five HTML files in [`mockups/`](mockups/) and the screenshots under
[`review/`](review/) show the Lume design (versions 2–2.3). They are kept as
history and are **not** a reference for the current look; the reference is
this file, the Ladle stories (`npm run storybook` in `v3/web`) and the running
dashboard.
