# Omadia UI — Visual Specification

> **Material: Lume — light-as-material.** Three user-bindable palettes
> (Petrol · Atelier · Lagoon, Lagoon = default). **Three-register typography**:
> Geist (structural) · Source Serif 4 (prose) · Geist Mono (data/code).
> Codex-review-ready in the CONCEPT.md cadence.

Version 0.4 — **Signal accent.** A single universal, palette-independent
magenta-pink (`#D6177A` light / `#FF5FA8` dark) added for the rare loud
moment — hero CTA, critical emphasis, and non-UI brand surfaces (web,
video). Capped at one element per view; sits outside the accent slot and
never replaces destructive/error semantics. See §2.5.5; constraints in §1.2
and §1.3 amended to carve it out.

Version 0.3 — **Editorial-mix typography adoption.** Three typographic
registers replace the v0.2 sans+mono pair: Geist for structural UI, Source
Serif 4 for agent prose (narration, analysis, summary), Geist Mono for data
and code. Single-source variable-axis fonts, all OFL/MIT licensed.
Prose-vs-structure register is set per text primitive via `style: "prose"`
trait; default is structural. Type scale gains `type.prose.*` tokens. The
Inter + JetBrains Mono pair (v0.2 baseline) is rejected as typographically
indistinguishable from the SaaS-industry default — same "Startup Blue"
problem the palette decision addressed. Fraunces tested in preview
(Architecture D, characterful old-style-revival with SOFT axis) and rejected
for productivity context: too heavy, too ornate, not fluid. Source Serif 4
delivers the editorial register cleanly without character noise.

Version 0.2 — **Lume material adoption.** Light-as-material thesis introduced;
surface luminosity, accent-as-illumination, directional borders and soft corners
formalised as the four Lume forces. Three curated palettes replace v0.1's
single-accent slot; the choice is user-bindable per `contextKey`, set
conversationally (no Settings screen). Radius scale shifted one stop softer
(editor surfaces stay at 0). Two-stop glow primitive replaces v0.1's single
accent-subtle tint. Patch-apply changes from fade-in to condensation. Token
model gains `accent-glow-core` for the inner light source. Companion previews
at [`./visual-spec-preview.html`](./visual-spec-preview.html) (flat v0.1
baseline) and [`./visual-spec-preview-lume.html`](./visual-spec-preview-lume.html)
(this material).

Earlier — v0.1: first draft, written against CONCEPT.md v0.7 and walkthroughs.md;
flat tokens, single-accent choice, restraint baseline. Superseded by this
document; preview retained for material-comparison purposes.

---

## 0. How to read this document

- All values are **semantic tokens**. Implementers consume them through a
  `tokens` module; raw values appear in exactly one place — the token
  definitions in §2.
- Tokens are expressed in **OKLCH** as the source of truth; the token-build
  step generates sRGB hex for renderers that can't consume OKLCH. Both forms
  appear in this document so reviewers can validate visually.
- Lume-specific implementation recipes (the CSS for two-stop glow, donut glow,
  patch-condensation animation) live in §3 as a single normative block.
  Per-primitive sections in §4 reference §3 rather than redefining them.
- ASCII wireframes and tables are the primary illustration formats.
  Pixel-level visuals live in the Lume preview HTML, not in this Markdown.
- **Rationale —** blocks document alternatives that were weighed. Reviewers
  should attack the rationale, not just the choice.

### Non-negotiable constraints inherited from CONCEPT.md

1. **Single material identity.** Lume is the material. No era-skinning.
   Era references resolve to layout idioms (Norton Commander, Photoshop
   workspace, …), never to visual mimicry.
2. **macOS-first.** Windows next, Linux power-user subset. The macOS
   rendering quality is the bar.
3. **Data-dominant typography.** Data carries weight; chrome recedes.
   Hierarchy is typographic plus light-driven, never via heavy chrome.
4. **One accent slot, plus one Signal.** Three curated palettes bind to the
   same accent slot; the slot itself is single. No status-pill salad. A
   single palette-independent **Signal** colour (§2.5.5) exists for the rare
   loud moment (one element per view, never a second accent) — it does not
   make the accent slot plural.
5. **Skeletons, no spinners** for loading (one documented exception in §7.3).
6. **Keyboard-first.** Visible focus, ⌘K palette, full arrow-key reach.
7. **Editor-class first-class.** `canvas-region`, `timeline`, `media`,
   `vector-path` render credibly in the same material that renders a table —
   while keeping a sharp, opaque boundary marking where Lume stops.

### Reference apps (orientation, never mimicry)

- **Apple's design lineage** — Aqua, iOS 7 frosted glass, visionOS spatial
  glass, Liquid Glass (2025). Lume is influenced by, not derived from, this
  lineage. We adopt light-as-material; we reject refraction, blur-everywhere,
  and specular-highlights-on-every-chrome (the Linear "ProKit" lesson for
  productivity-grade UIs).
- **Linear** — typography rigour, density, command palette UX, ProKit
  philosophy.
- **Things 3** — restraint, generous whitespace.
- **Raycast** — Spotlight idiom, compact result lists.
- **Tremor** — chart restraint.
- **shadcn-ui** — token discipline and composability.

**Explicitly NOT references:** Confluence, Microsoft Teams, JIRA Cloud, Figma
sidebars, Slack.

---

## 1. Material — Lume

### 1.1 Thesis

Apple has never shipped "colors and shadows"; each generation has shipped a
named material with physical properties (Aqua → frosted glass → spatial glass
→ Liquid Glass). The current Omadia v0.1 spec adopted tokens in the
Linear/Notion lineage — correct in spirit, but materially flat: it had no
material story.

**Lume is the proposed Omadia material:** UI is not drawn, it is condensed
out of light. The agent's attention is visible as accent-tinted illumination
on the surface it touches. Backgrounds carry a subtle directional luminosity
that suggests they are generated, not printed. The single accent slot has
two visual forms — fill (the hard form, on buttons and indicators) and glow
(the soft form, as halos at selection and focus).

This expresses the Omadia thesis directly. CONCEPT.md says the agent
*materialises* UI per turn; the material identity must say so too.

### 1.2 The four forces

Everything else in this spec is composition of these four.

| Force | What it does | Where it shows up |
|---|---|---|
| **Surface luminosity** | Every surface is a 180° linear-gradient from a slightly lit top to a slightly settled bottom (~1.5% L delta). Imperceptible per-surface; cumulative effect: surfaces feel illuminated, not printed. | `bg.canvas`, `bg.surface`, `bg.surface.raised`, `bg.surface.sunken`, modal surface — all carry a `.top` / `.btm` pair. |
| **Accent as illumination** | The single accent token splits into two visual modes. `accent` is the fill (buttons, indicators). `accent-glow` + `accent-glow-strong` are the accent-tinted corona of a light source. `accent-glow-core` is the bright inner core that reads as *emitted light* rather than as accent-tinted shadow. | Selection halos, focus rings, button-in-flight, active-tool indicators, modal-pane glow. |
| **Directional borders** | Borders use a lighter `top` color and a slightly stronger `btm` color, so an edge reads as catching light from above. Combined with a 1px inner highlight on raised surfaces, every container gains perceived thickness. | All container, input, button, card, modal edges. |
| **Soft corners with editor exception** | Lume shifts the v0.1 radius scale up by one stop. Light has no edges; the material's softness expresses the metaphor. The exception is the editor boundary — `canvas-region`, `timeline` and similar surfaces stay at radius 0. That visual contrast doubles as a Tier-1 boundary marker. | Radius scale §2.9. |

### 1.3 What Lume is NOT

| Out | Reason |
|---|---|
| **Refraction** | Linear's ProKit team rejected refraction explicitly — it makes dense data-driven UIs harder to read. The boundaries between cells in a table need to be stable; refraction wiggles them. |
| **Real-time blur as primary chrome** | We're not in spatial computing. Blur costs performance and competes with text legibility on data surfaces. |
| **Specular highlights on every surface** | Apple uses them everywhere in Liquid Glass; we use them only at semantic-meaning moments (active tool, focused input). |
| **Glassmorphism** | Frosted-everything is a 2020 aesthetic dead end. Lume is solid light, not see-through plastic. |
| **Multiple accent slots** | Still exactly one. Three *palettes* bind to it. Not three accents at once. The one **Signal** colour (§2.5.5) is a separate, deliberately-loud token — capped at one element per view — not a second accent slot. |
| **Settings / Preferences UI for palette** | Palette is set conversationally, per CONCEPT.md prefs model. The user says "make it warmer"; Tier 2 writes to `ui-prefs`. |

### 1.4 Apple-lineage credits

Lume is influenced by Apple's progression from Aqua through Liquid Glass and
by Linear's ProKit adaptation. We take **light shapes hierarchy** as the load-
bearing idea. We discard the optical effects (refraction, specular sheen on
chrome, glass-everywhere translucency) that don't translate to a
productivity-grade canvas. The result is light-as-material at productivity-
tool throttle: subtle enough to recede, present enough to feel.

---

## 2. Design tokens

### 2.1 Token model

| Token class | v0.1 shape | v0.2 / Lume shape |
|---|---|---|
| Surface backgrounds | Single value (`bg.canvas`, `bg.surface`, …) | Pair: `<class>.top` + `<class>.btm`, consumed as a linear-gradient |
| Borders | Single value (`border.subtle`, `border.default`) | Pair: `<class>.top` + `<class>.btm`, applied as `border-top-color` + `border-color` |
| Accent | One value + hover/active/subtle | One value + hover/active/subtle + **glow** + **glow-strong** + **glow-core** |
| Text | Unchanged | Unchanged |
| Semantic states | Unchanged | Unchanged |

OKLCH is the source of truth. The token-build step generates sRGB hex for
legacy renderers; the conversion is mechanical and lives in the build
pipeline, not in product code.

### 2.2 Surface tokens

#### Light mode

| Token | OKLCH `top` | OKLCH `btm` | sRGB `top` | sRGB `btm` | Use |
|---|---|---|---|---|---|
| `bg.canvas` | `0.992 0.002 250` | `0.975 0.004 250` | `#FDFDFE` | `#F7F8FB` | Workspace background |
| `bg.surface` | `1.00 0 0` | `0.985 0.003 250` | `#FFFFFF` | `#FAFAFD` | Primary content surface |
| `bg.surface.raised` | `1.00 0 0` | `0.99 0.002 250` | `#FFFFFF` | `#FCFCFE` | Cards, popovers, inputs |
| `bg.surface.sunken` | `0.965 0.004 250` | `0.945 0.005 250` | `#F2F3F7` | `#ECEDF2` | Code blocks, hover, secondary |
| `bg.modal.surface` | `1.00 0 0` | `0.99 0.003 250` | `#FFFFFF` | `#FBFBFE` | Modal pane interior |
| `bg.modal.overlay` | `0.30 0.02 250 / 0.40` | — | `rgba(20,30,50,0.40)` | — | Modal scrim — minimally accent-tinted, never neutral black |

#### Dark mode

| Token | OKLCH `top` | OKLCH `btm` | sRGB `top` | sRGB `btm` | Use |
|---|---|---|---|---|---|
| `bg.canvas` | `0.20 0.01 250` | `0.175 0.012 250` | `#232631` | `#1B1D24` | Workspace background |
| `bg.surface` | `0.22 0.012 250` | `0.20 0.012 250` | `#2A2D38` | `#23262F` | Primary content surface |
| `bg.surface.raised` | `0.245 0.013 250` | `0.215 0.012 250` | `#303440` | `#292C37` | Cards, popovers, inputs |
| `bg.surface.sunken` | `0.18 0.011 250` | `0.15 0.01 250` | `#1D1F26` | `#16181E` | Sunken |
| `bg.modal.surface` | `0.245 0.013 250` | `0.215 0.012 250` | `#303440` | `#292C37` | Modal pane interior |
| `bg.modal.overlay` | `0 0 0 / 0.60` | — | `rgba(0,0,0,0.60)` | — | Modal scrim |

**Renderer rule.** Every surface is rendered as
`background: linear-gradient(180deg, <token>.top 0%, <token>.btm 100%)`.
Renderers that can't gradient (extreme legacy) fall back to `<token>.btm`.
The visible delta is small per-surface and cumulative across the screen.

### 2.3 Text tokens

| Token | OKLCH (light) | sRGB (light) | OKLCH (dark) | sRGB (dark) | Use |
|---|---|---|---|---|---|
| `text.primary` | `0.22 0.01 250` | `#1B1D24` | `0.96 0.005 250` | `#EEEFF3` | Headings, body, data |
| `text.secondary` | `0.45 0.01 250` | `#5B5F6B` | `0.75 0.008 250` | `#B6B9C3` | Labels, captions |
| `text.tertiary` | `0.62 0.01 250` | `#8D9099` | `0.58 0.008 250` | `#888B95` | Hints, placeholders |
| `text.disabled` | `0.78 0.005 250` | `#BFC1C6` | `0.38 0.008 250` | `#525561` | Disabled controls |
| `text.inverse` | `0.99 0.002 250` | `#FCFCFD` | `0.20 0.01 250` | `#1F2127` | Text on accent or inverse |
| `text.accent` | per palette | per palette | per palette | per palette | Links, accent-emphasised values — resolves to the active palette's `accent` |

### 2.4 Border tokens — directional

Borders are not single colors. They render as `1px solid <class>.btm` with
an explicit `border-top-color: <class>.top` override, so the top edge of the
border catches more light than the bottom. Combined with a 1px white-tinted
`box-shadow inset` on raised surfaces, this gives every container a
perceived thickness.

#### Light mode

| Token | `top` color | `btm` color | Use |
|---|---|---|---|
| `border.subtle` | `rgba(20, 24, 36, 0.05)` | `rgba(20, 24, 36, 0.09)` | Default container, table cell, divider |
| `border.default` | `rgba(20, 24, 36, 0.08)` | `rgba(20, 24, 36, 0.14)` | Inputs, buttons, outlines |
| `border.strong` | `rgba(20, 24, 36, 0.16)` | `rgba(20, 24, 36, 0.26)` | Pressed, prominent edges |
| `border.focus` | resolves to `accent` | resolves to `accent` | Focus ring (override, not tinted) |

#### Dark mode

| Token | `top` color | `btm` color | Use |
|---|---|---|---|
| `border.subtle` | `rgba(255, 255, 255, 0.06)` | `rgba(0, 0, 0, 0.40)` | Default |
| `border.default` | `rgba(255, 255, 255, 0.10)` | `rgba(0, 0, 0, 0.50)` | Inputs, buttons |
| `border.strong` | `rgba(255, 255, 255, 0.18)` | `rgba(0, 0, 0, 0.60)` | Pressed |
| `border.focus` | resolves to `accent` | resolves to `accent` | Focus ring |

Dark mode's `top` color is white-tinted and `btm` color is shadow-tinted —
the same physics rule as light mode, expressed in inverted lightness.
Light comes from above, regardless of theme.

### 2.5 Accent tokens — three palettes

#### The accent token shape

Every palette defines exactly the same seven sub-tokens for each of light and
dark mode. The palette binding (§2.5.4) chooses which palette's values fill
this shape; the rest of the spec only references the abstract token names.

| Sub-token | Type | Role |
|---|---|---|
| `accent` | hex | The fill — buttons, focus rings, selection bars, indicator dots |
| `accent.hover` | hex | Hover state of accent fills |
| `accent.active` | hex | Pressed state of accent fills |
| `accent.subtle` | rgba ~10% | Selected-row fill tint, accent-background wash |
| `accent.glow` | rgba ~22% | Soft accent-tinted corona at selection, hover, halo |
| `accent.glow-strong` | rgba ~38% | Stronger corona at focus, active tool, hover-emphasis |
| `accent.glow-core` | rgba ~55% | The **bright inner light source** — white-shifted, *not* accent-tinted. Closes the light-mode-vs-dark-mode asymmetry the v0.1 single-tint approach had |

#### 2.5.1 Palette: **Petrol** — *computational ambient*

Cool steel-blue, hue 235°. Story: the agent as steady daylight, quiet ambient
presence. Most-restrained of the three; doesn't impose a strong identity.

**Light mode** — OKLCH 0.55 0.16 235 base · sRGB `#0F7AB8`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.55 0.16 235` | `#0F7AB8` |
| `accent.hover` | `0.50 0.17 235` | `#0C6CA8` |
| `accent.active` | `0.45 0.17 235` | `#0A5E94` |
| `accent.subtle` | — | `rgba(15, 122, 184, 0.10)` |
| `accent.glow` | — | `rgba(15, 122, 184, 0.22)` |
| `accent.glow-strong` | — | `rgba(15, 122, 184, 0.36)` |
| `accent.glow-core` | — | `rgba(165, 215, 240, 0.55)` |

**Dark mode** — OKLCH 0.72 0.13 235 base · sRGB `#52B0E2`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.72 0.13 235` | `#52B0E2` |
| `accent.hover` | `0.78 0.13 235` | `#74C0E8` |
| `accent.active` | `0.82 0.12 235` | `#90CFEE` |
| `accent.subtle` | — | `rgba(82, 176, 226, 0.16)` |
| `accent.glow` | — | `rgba(82, 176, 226, 0.28)` |
| `accent.glow-strong` | — | `rgba(82, 176, 226, 0.44)` |
| `accent.glow-core` | — | `rgba(197, 229, 245, 0.45)` |

#### 2.5.2 Palette: **Atelier** — *studio warmth*

Warm burnt-amber, hue 50°. Story: studio lamp, the agent as craftsman lighting
the work. Strongest narrative fit with "agent materialises UI" (workshop
metaphor). Separated from semantic states by L+C distance even though hue
neighbours error (25°) and warning (80°).

**Light mode** — OKLCH 0.57 0.13 50 base · sRGB `#B36B2E`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.57 0.13 50` | `#B36B2E` |
| `accent.hover` | `0.52 0.13 50` | `#9F5C26` |
| `accent.active` | `0.47 0.13 50` | `#8A4E1F` |
| `accent.subtle` | — | `rgba(179, 107, 46, 0.10)` |
| `accent.glow` | — | `rgba(179, 107, 46, 0.24)` |
| `accent.glow-strong` | — | `rgba(179, 107, 46, 0.38)` |
| `accent.glow-core` | — | `rgba(245, 215, 175, 0.55)` |

**Dark mode** — OKLCH 0.76 0.12 60 base · sRGB `#E0A26B`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.76 0.12 60` | `#E0A26B` |
| `accent.hover` | `0.80 0.12 60` | `#E5B080` |
| `accent.active` | `0.84 0.11 60` | `#EBBE93` |
| `accent.subtle` | — | `rgba(224, 162, 107, 0.18)` |
| `accent.glow` | — | `rgba(224, 162, 107, 0.30)` |
| `accent.glow-strong` | — | `rgba(224, 162, 107, 0.46)` |
| `accent.glow-core` | — | `rgba(250, 228, 200, 0.45)` |

#### 2.5.3 Palette: **Lagoon** *(default)* — *lit water / bioluminescence*

Lit teal-cyan, hue 200°. Story: light passing through shallow water. Strongest
light-metaphor coherence of the three — `accent.glow-core` is bright
cyan-white that reads as emitted light, not as accent-tinted shadow. Refined
from an earlier "Botanical" draft (hue 195°, L 0.54) which under-played the
light metaphor in light mode.

**Light mode** — OKLCH 0.58 0.12 200 base · sRGB `#1F8FA3`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.58 0.12 200` | `#1F8FA3` |
| `accent.hover` | `0.53 0.12 200` | `#197D90` |
| `accent.active` | `0.48 0.12 200` | `#146B7C` |
| `accent.subtle` | — | `rgba(31, 143, 163, 0.12)` |
| `accent.glow` | — | `rgba(60, 175, 195, 0.32)` |
| `accent.glow-strong` | — | `rgba(60, 175, 195, 0.48)` |
| `accent.glow-core` | — | `rgba(180, 238, 248, 0.60)` |

**Dark mode** — OKLCH 0.78 0.10 200 base · sRGB `#6FC8D6`

| Sub-token | OKLCH | sRGB / rgba |
|---|---|---|
| `accent` | `0.78 0.10 200` | `#6FC8D6` |
| `accent.hover` | `0.82 0.10 200` | `#88D2DE` |
| `accent.active` | `0.85 0.09 200` | `#A1DCE6` |
| `accent.subtle` | — | `rgba(111, 200, 214, 0.20)` |
| `accent.glow` | — | `rgba(111, 200, 214, 0.32)` |
| `accent.glow-strong` | — | `rgba(111, 200, 214, 0.48)` |
| `accent.glow-core` | — | `rgba(210, 245, 250, 0.50)` |

#### 2.5.4 Palette binding — user-controlled, context-aware

The palette is **user-bound, not agent-bound**. The Skill never picks a
palette; it only references the abstract `accent` token. The user binds
the token to a palette via conversational preference:

> "Mach das atelier-warm." / "Ich brauche Petrol heute." / "Switch to Lagoon."

Storage: `memory://ui-prefs/<tenantId>/<userId>/<contextKey>/accent` carries
one of `"petrol" | "atelier" | "lagoon"`. Default (no value set): `"lagoon"`.

**Per `contextKey`.** The CONCEPT.md identity model already provides
context-aware preferences keyed by `contextKey`. Palette is one such
preference. A user can have Lagoon as their default work palette, Petrol on
a finance-review canvas, Atelier on a creative-draft canvas. The Tier-2
orchestrator loads the right palette at canvas-activate time.

**Switching mid-session.** When the palette preference changes during a
session, Tier 2 emits a `surface_patch` that re-tints accent tokens. Tree
structure is unchanged; only colors update. The patch increments
`treeRevision` as any other patch does — clients render the change as a
short crossfade (see §6.1).

**No Settings UI.** CONCEPT.md is explicit: user preferences are
conversational, never set via a Preferences pane. The palette follows that
rule. The UI Skill carries a `palette-binding-protocol` block (cross-ref
CONCEPT.md §"The UI Skill") that lists trigger phrases and the persistence
mechanic.

**Marketing default.** App icon, splash, screenshots, demo videos render in
Lagoon. The other two palettes are equal first-class options at runtime but
not equal in brand presence.

**Rationale.** v0.1 forced a single color choice and surfaced eight open
questions just on that decision. The 2026 industry trend (per Pantone
Cloud Dancer + multiple SaaS-design surveys) is away from a single "Startup
Blue" toward palettes that fit context. Apple lets users pick the system
accent on macOS and iOS; OS-like surfaces (which Omadia is) follow that
convention. The user gets agency without the agent gaining a skinning
capability. The single-material constraint is preserved.

### 2.5.5 Signal — the loud accent (palette-independent)

The three accent palettes are deliberately quiet — "subtle enough to recede"
is the whole point of the accent slot. v0.3 surfaced a gap: as Lume began to
be used beyond the canvas (marketing web, video), and for the occasional
high-stakes in-canvas moment, the muted accent could not carry a genuine
*pop*. **Signal** fills that gap.

Signal is **one universal colour, not one-per-palette**. It does not bind to
the accent slot and does not change when the user switches Lagoon / Petrol /
Atelier. Its hue (~335°, magenta-pink) sits in the only open gap in the
token hue map (the occupied hues are error 25°, Atelier 50°, warning 80°,
success 150°, Lagoon 200°, Petrol 235°). That placement makes it the
complement of Lagoon and Petrol (maximum pop against the two cool default
palettes), the split-complement of Atelier, and — critically —
**unambiguously not red**, so a loud Signal CTA never reads as a destructive
/ error action.

| Sub-token | Light (sRGB / rgba) | Dark (sRGB / rgba) | Role |
|---|---|---|---|
| `signal` | `#D6177A` | `#FF5FA8` | The fill — loud CTA, critical emphasis |
| `signal.hover` | `#C2126D` | `#FF77B6` | Hover state |
| `signal.active` | `#AD0E60` | `#FF90C4` | Pressed state |
| `signal.subtle` | `rgba(214,23,122,0.10)` | `rgba(255,95,168,0.18)` | Wash tint |
| `signal.glow` | `rgba(214,23,122,0.24)` | `rgba(255,95,168,0.30)` | Soft corona |
| `signal.glow-strong` | `rgba(214,23,122,0.42)` | `rgba(255,95,168,0.46)` | Stronger corona |
| `signal.glow-core` | `rgba(255,200,230,0.55)` | `rgba(255,215,235,0.50)` | Bright white-shifted core |

Dark mode is the same hue, lighter and slightly less saturated — the same
physics rule as the accent palettes (light emits on dark grounds).

**Usage rules — Signal is loud by design, so discipline is the whole point:**

- **At most one Signal element per view.** Two Signals cancel each other out.
- Reserved for: the single most important CTA; a critically-important
  element or text; and non-UI brand moments (web hero CTAs, video
  lower-thirds, app-store screenshots).
- **Destructive actions keep their dedicated treatment** (`state.error` text
  + 1px `state.error.edge`, never a fill). Signal may *elevate a high-stakes
  confirm* button (e.g. the modal "Send"), but it never replaces error
  semantics and is never the colour of "delete".
- Never a large surface fill, never a status pill, never decorative.
- Subject to the §8 contrast floor like any other interactive colour.

**Rationale.** A second *accent slot* would break the single-accent
constraint and re-open the status-pill-salad risk. A single, capped,
palette-independent Signal does not: it is one recognisable brand pop that
the user (not the agent) reaches for, exactly once per surface. Keeping it
out of the accent slot means the agent's palette-binding protocol is
unaffected — the agent still only ever references the abstract `accent`
token; Signal is an authored decision, not an agent-skinning capability.

### 2.6 Semantic state tokens

Intentionally text-only — never filled pills, badges or block fills. This
rule from v0.1 stands.

#### Light mode

| Token | OKLCH | sRGB | Use |
|---|---|---|---|
| `state.loading` | `0.90 0.008 250` | `#DCDEE3` | Skeleton base |
| `state.loading.hi` | `0.96 0.004 250` | `#EFEFF2` | Skeleton pulse highlight |
| `state.error.fg` | `0.45 0.12 25` | `#A8443B` | Error text (never as pill bg) |
| `state.error.edge` | `0.55 0.14 25` | `#C45A50` | 1px error border |
| `state.success.fg` | `0.42 0.10 150` | `#3F7A55` | Success text |
| `state.warning.fg` | `0.50 0.09 80` | `#8C6A1F` | Warning text |

#### Dark mode

| Token | OKLCH | sRGB | Use |
|---|---|---|---|
| `state.loading` | `0.30 0.01 250` | `#3E414C` | Skeleton base |
| `state.loading.hi` | `0.38 0.012 250` | `#525561` | Skeleton highlight |
| `state.error.fg` | `0.75 0.12 25` | `#E08577` | Error text |
| `state.error.edge` | `0.65 0.14 25` | `#C5685A` | Error border |
| `state.success.fg` | `0.78 0.10 150` | `#88C499` | Success text |
| `state.warning.fg` | `0.80 0.09 80` | `#D6B468` | Warning text |

**Hue separation from accent palettes:**

| Palette | Δ to error 25° | Δ to warning 80° | Δ to success 150° |
|---|---|---|---|
| Petrol 235° | 210° | 155° | 85° |
| Atelier 50° | 25° | 30° | 100° |
| Lagoon 200° | 175° | 120° | 50° |

Atelier has the tightest hue separation from error/warning; L+C separation
takes over there (error at L 0.45 hue 25 vs Atelier at L 0.57 hue 50 is
clearly distinct in both lightness and chroma to daltonism-simulator passes
of red-green and blue-yellow types).

### 2.7 Typography — three registers, three families

Lume ships three typographic registers, each from a different family, each
variable-axis, all OFL or MIT licensed. The agent expresses different speech
acts in different registers; the typography itself communicates *what kind of
thing the user is reading*. Companion preview:
[`./visual-spec-preview-type.html`](./visual-spec-preview-type.html) compares
the chosen architecture against three alternatives (A · Inter+JBM, B · Geist
only, D · Fraunces).

#### Family choice

| Register | Family | License | Use | Skill trigger |
|---|---|---|---|---|
| **Structural** | **Geist** (Vercel × Basement, 2023; variable-axis) | MIT, open-source | UI labels, headings, buttons, form fields, instructions, eyebrows, menubars | default — no opt-in needed |
| **Prose** | **Source Serif 4** (Adobe; variable-axis with optical sizing) | OFL | Agent narration, analysis, summary, long-form explanation | `style: "prose"` on the `text` primitive |
| **Data / Code** | **Geist Mono** (Vercel × Basement, 2023; sibling to Geist) | MIT, open-source | Numeric table cells, code blocks, terminal output, file paths, IDs | column kind `number \| currency \| code`, or explicit `style: "mono"` |

#### Family rationale (compressed)

**Geist (structural).** Vercel commissioned Geist in 2023 specifically because
existing UI sans (Inter, Söhne, Helvetica Now) weren't good enough for
data-dense developer UIs. Swiss-design inspired, angular terminals, high
x-height, short descenders, weight axis 100–900. Geist Sans and Geist Mono
were designed as siblings — every weight aligns across the two families
without ad-hoc visual matching. This eliminates the "the mono column reads
heavier than the surrounding prose" miscalibration that Inter + JBM has.

**Source Serif 4 (prose).** Adobe-developed transitional serif, OFL-licensed,
with explicit `opsz` (8–60) optical-sizing axis tuned for body reading. The
character is deliberately neutral — designed as a body face that doesn't
compete with content. Lume's prose channel needs *authority*, not
*personality*; an old-style-revival like Fraunces (tested as Architecture D
in the preview) was rejected for productivity context — too heavy, too
ornate, not fluid.

**Geist Mono (data/code).** Family-matched to Geist Sans. Distinguishable
0/O, 1/l/I; ligatures (`->`, `>=`, `!=`, `=>`) supported. Tabular figures by
default. Weight 450 used for `type.mono.data` so digits hold their weight
against gradient surface backgrounds (Lume surfaces have ~1.5% L gradient;
the 450 weight is calibrated against this delta).

#### Why not the v0.2 baseline (Inter + JetBrains Mono)

The v0.2 sans+mono pair (Inter + JBM) is the same combination Linear, Notion
(pre-Diatype), Vercel (pre-Geist) and most 2020-2024 productivity tools use.
Functional, free, but typographically *identical to the SaaS industry
default* — zero differentiation. With Lume as a distinct material and Lagoon
as a distinct palette, falling back to the everyone-uses-it type pair would
undermine the rest of the spec's distinctness claim. This is the same trade
the palette section made when rejecting Startup-Blue territory.

#### Why not other strong candidates

- **Fraunces in the prose slot** (tested as Architecture D in the preview):
  variable SOFT axis is genuinely Lume-coherent, but the old-style-revival
  character is too heavy, ornate, and broad for productivity-tool prose.
  Rejected on field-test feedback.
- **Berkeley Mono** for code: excellent font, paid commercial license,
  single-foundry dependency. Lock-in risk for an open-source-aligned project.
- **Söhne + Tiempos** (Anthropic's pair): paid, beautiful, and architecturally
  identical to our chosen approach. Rejected on cost.

#### Type scale

The structural register inherits v0.2's scale. The prose register uses a
slightly larger body size to compensate for serif air — serif body text
reads ~1px smaller than sans at the same metric weight, so we render it
larger. Prose tokens carry a `.prose` suffix.

| Token | Register | Size | Line height | Weight | Letter-spacing | Use |
|---|---|---|---|---|---|---|
| `type.display` | structural | 1.75rem (28px) | 1.20 | 600 | -0.01em | Rare top-level title |
| `type.heading.1` | structural | 1.375rem (22px) | 1.25 | 600 | -0.005em | Canvas-level title |
| `type.heading.2` | structural | 1.125rem (18px) | 1.30 | 600 | 0 | Section heading |
| `type.heading.3` | structural | 0.9375rem (15px) | 1.35 | 600 | 0 | Sub-section |
| `type.body` | structural | 0.875rem (14px) | 1.50 | 400 | 0 | Default UI text |
| `type.body.strong` | structural | 0.875rem (14px) | 1.50 | 600 | 0 | Inline emphasis |
| `type.body.compact` | structural | 0.8125rem (13px) | 1.45 | 400 | 0 | Dense rows |
| `type.caption` | structural | 0.75rem (12px) | 1.40 | 400 | 0.005em | Labels |
| `type.caption.strong` | structural | 0.75rem (12px) | 1.40 | 600 | 0.02em | Uppercase eyebrows |
| **`type.prose`** | **prose** | **1rem (16px)** | **1.65** | **400** | **0** | **Agent narration, analysis, summary** |
| **`type.prose.strong`** | **prose** | **1rem (16px)** | **1.65** | **600** | **0** | **Emphasis within prose** |
| **`type.prose.compact`** | **prose** | **0.9375rem (15px)** | **1.55** | **400** | **0** | **Inline prose in dense context** |
| **`type.prose.heading`** | **prose** | **1.25rem (20px)** | **1.40** | **600** | **0** | **Title of a prose-mode pane (rare)** |
| `type.mono.data` | mono | 0.8125rem (13px) | 1.45 | 450 | 0 | Numeric cells, IDs |
| `type.mono.code` | mono | 0.8125rem (13px) | 1.55 | 400 | 0 | Code blocks |

Headings always stay structural — they are structural elements even when
introducing a prose-mode pane. The `type.prose.heading` token covers the rare
case of an end-to-end prose pane (primarily Walkthrough-4-style live-research
panes).

Weights used: 400, 450 (mono only), 500 (Geist optional emphasis), 600. No
300, no 700+.

#### Variable-axis usage

- **Geist** — weight axis 400, 500, 600. No slant. `font-variation-settings`
  not needed; weight via CSS `font-weight`.
- **Source Serif 4** — weight axis 400, 600. `font-optical-sizing: auto`
  enables the 8–60 `opsz` axis automatically per font-size. Renderers without
  optical-sizing support fall back to weight only — degradation is graceful.
- **Geist Mono** — weight axis 400, 450, 600. `font-feature-settings: 'tnum'`
  for tabular figures.

#### Font loading

- Variable files only — one file per family, ~80–120 KB each subsetted to
  Latin + numerics + needed glyphs + ligatures.
- Total payload: ~280–360 KB across all three families subsetted.
- Strategy: preload `Geist` for FCP; defer `Geist Mono` and `Source Serif 4`.
  `font-display: swap` so the page renders immediately and re-renders to the
  chosen architecture when fonts arrive.

#### Fallback chains

```
--font-sans:  'Geist',           system-ui, -apple-system, 'Segoe UI', sans-serif;
--font-mono:  'Geist Mono',      ui-monospace, 'SF Mono', Menlo, Consolas, monospace;
--font-serif: 'Source Serif 4',  Charter, 'Iowan Old Style', Georgia, serif;
```

Fallbacks are chosen per-platform-strongest: macOS gets Charter for serif
(beautiful native body face); Windows gets Georgia (the strongest native
serif); Linux falls through to generic. Sans and mono fall through to native
system fonts.

#### Prose-vs-structure protocol (cross-ref CONCEPT.md UI Skill)

The agent declares which register a `text` primitive belongs to via the
`style` trait:

| Trait value | Register | When the agent emits this |
|---|---|---|
| (omitted) | structural | Default — labels, captions, instructions, eyebrows, inline UI text, headings |
| `style: "prose"` | prose | Multi-sentence narration, analysis, summary, explanation, long-form response |
| `style: "mono"` | mono | Code, terminal output, file paths, IDs, dense ID/version strings inline |

The CONCEPT.md UI Skill carries the trigger rules (when to emit `style:
"prose"`). The renderer maps the trait to the typographic family without
further negotiation.

### 2.8 Spacing

Unchanged: 4pt grid.

| Token | Value | Use |
|---|---|---|
| `space.0` | 0 | Touching |
| `space.1` | 2px | Hairline |
| `space.2` | 4px | Tight group |
| `space.3` | 8px | Default row |
| `space.4` | 12px | Default block / stack gap |
| `space.5` | 16px | Container padding |
| `space.6` | 24px | Generous block |
| `space.7` | 32px | Canvas padding |
| `space.8` | 48px | Major layout |
| `space.9` | 64px | Rare breathing-room |

Density variants per primitive: `compact` shifts one step down, `spacious`
one step up.

### 2.9 Radii — Lume scale

Lume shifts v0.1's radius scale up by one stop, with the editor exception
remaining at 0.

| Token | Value | Use |
|---|---|---|
| `radius.0` | 0 | **Editor-class surfaces** — `canvas-region`, `timeline`, Photoshop-style tool buttons inside the editor toolbar. Where Lume material stops, sharp corners take over |
| `radius.sm` | 6px | Buttons, inputs, list-item hover/selected backgrounds |
| `radius.md` | 8px | Containers, cards, popovers |
| `radius.lg` | 12px | Modals, panes, outermost windows — matches macOS window-corner radius (Apple's "concentric corners" rule) |
| `radius.pill` | 999px | Switches, badge chips, progress bars |

**Rationale — softer than v0.1.** Light has no edges. If the material is
condensed luminosity, hard corners fight the metaphor. The shift is one
stop (sm 4→6, md 6→8, lg 8→12); not a redesign, a calibration to the
material. The editor exception is load-bearing: a Photoshop-like
canvas-region with rounded corners reads "consumer photo app", not
"professional tool" — *and* the visual hardness at the edge reinforces the
Tier-1 boundary marker.

### 2.10 Elevation

Three shadow tokens. All include an accent-tinted ambient component for
prominent surfaces (modals).

| Token | Light | Dark | Use |
|---|---|---|---|
| `elev.0` | none | none | Flat content |
| `elev.popover` | `0 1px 2px rgba(20,24,36,0.04), 0 8px 24px rgba(20,24,36,0.06)` | `0 1px 2px rgba(0,0,0,0.30), 0 8px 24px rgba(0,0,0,0.45)` | Dropdowns, popovers, hover cards |
| `elev.modal` | `0 4px 16px rgba(20,24,36,0.06), 0 24px 48px rgba(20,24,36,0.12), 0 0 32px var(--accent-glow-core), 0 0 96px var(--accent-glow)` | `0 4px 16px rgba(0,0,0,0.55), 0 24px 48px rgba(0,0,0,0.65), 0 0 32px var(--accent-glow-core), 0 0 96px var(--accent-glow)` | Modal panes — the modal is *the lit object*, scrim is its shadow |
| `elev.drag` | `0 8px 24px rgba(20,24,36,0.16)` | `0 8px 24px rgba(0,0,0,0.55)` | Drag-in-flight ghost |

Cards do **not** get a shadow. Cards are differentiated by border + radius +
surface luminosity (the gradient pair). This is a deliberate alignment with
Linear/Things/Apple Catalyst, against Material Design's everything-is-elevated.

### 2.11 Motion

| Token | Value | Use |
|---|---|---|
| `motion.instant` | 0ms | Theme switch, scroll jump, focus on tab |
| `motion.quick` | 100ms | Hover, focus fade-in |
| `motion.smooth` | 200ms | Modal open/close, accordion |
| `motion.deliberate` | 320ms | Canvas-activate (Spaces switch) |
| `motion.condense` | 800ms | **Patch-condensation animation** (§3.5) |
| `easing.standard` | `cubic-bezier(0.22, 0.61, 0.36, 1.00)` | Default decelerate |
| `easing.emphasis` | `cubic-bezier(0.4, 0.0, 0.2, 1.0)` | Bigger moves (modal, condensation) |
| `easing.linear` | `linear` | Skeleton pulse |

Reduced-motion: every animation respects `prefers-reduced-motion: reduce`.
Condensation collapses to a single opacity 0→1 fade. Skeleton pulse becomes
static fill. Modal open/close becomes instant.

### 2.12 Icons

Unchanged: Lucide as the icon library, 14/16/20/24 px sizes with
1.5/1.75/2.0 stroke widths. Three documented custom icons allowed
(`magic-wand`, `brush-pressure`, `vector-pen-anchor`) for editor-specific
glyphs Lucide doesn't cover.

---

## 3. Lume implementation primitives

The CSS recipes that every renderer must implement. Per-primitive specs
in §4 reference these by name rather than re-defining them. Each recipe is
the single source of truth.

### 3.1 Surface gradient

Every surface is rendered as a 180° linear-gradient between the surface
token's `.top` and `.btm` colors.

```css
background: linear-gradient(180deg, var(--bg-surface-top) 0%, var(--bg-surface-btm) 100%);
```

Fallback for renderers that cannot gradient: use `<token>.btm` as a solid
fill. The Lume effect degrades to flat; functionality is unaffected.

### 3.2 Two-stop glow (the default Lume glow)

The standard accent-glow recipe. A bright inner core close to the surface,
an accent-tinted corona further out.

```css
box-shadow:
  0 0 4px var(--accent-glow-core),       /* tight inner core, white-shifted */
  0 4px 12px var(--accent-glow);         /* wider corona, accent-tinted */
```

For **emphasis states** (focused input, hovered primary button), the recipe
intensifies:

```css
box-shadow:
  0 0 6px var(--accent-glow-core),
  0 6px 18px var(--accent-glow-strong);
```

For the **Spotlight idiom** (§5.3), the recipe extends to three stops as
its single showcase moment:

```css
box-shadow:
  0 0 0 4px var(--accent-glow),          /* hard outline */
  0 0 16px var(--accent-glow-core),      /* tight bright core */
  0 12px 40px var(--accent-glow-strong); /* wide deep corona */
```

**Why two stops, not one (the v0.1 single-tint had problems):** with a
single `rgba(accent, alpha)` shadow, a light-mode glow reads as a *darker
accent-tinted shadow* underneath the surface — not as light coming *from*
the surface. The bright `glow-core` (white-shifted) is what closes that
asymmetry. In light mode it adds a luminous halo that the accent-tinted
shadow alone could never produce; in dark mode it intensifies the corona's
"emitting" quality.

### 3.3 Donut glow — for surfaces with a glyph at center

When the surface has a centered glyph (Photoshop tool button, status-dot
chip, KPI-card delta arrow), the standard recipe places the glow-core
*at the glyph's pixel position*, drowning the glyph in bright white. Bug.

**Recipe — donut variant:**

```css
background: radial-gradient(
  circle at center,
  var(--accent-subtle) 0%,
  var(--accent-subtle) 35%,    /* clear pocket for the glyph */
  var(--accent-glow-core) 75%, /* bright ring radiates outward */
  transparent 100%
);
box-shadow:
  0 0 12px var(--accent-glow-core),
  0 0 22px -4px var(--accent-glow-strong);
```

Physical analogue: a lit lampshade where the reflector edge glows, not the
bulb seen through. The glyph sits in a clean accent-subtle pocket; the
bright light radiates around it.

**Where the donut applies:**

- `ps-tool.active` (editor-workspace toolbar)
- `kpi.delta` chip when it carries an arrow glyph
- Status dots with `loading: true` + icon
- Any primitive declaring `style.center-glyph: true`

**Open issue (carry-over from preview).** The donut still needs visual
refinement — early implementations show the ring landing too close to the
border, slightly clipped. Spike-phase to refine; the rule stays normative.

### 3.4 Directional border

```css
border: 1px solid var(--border-default-btm);
border-top-color: var(--border-default-top);
box-shadow: 0 1px 0 rgba(255,255,255,0.06) inset; /* top-edge highlight, raised surfaces */
```

For raised surfaces (cards, modal), the inset highlight is mandatory.
For sunken surfaces (`bg.surface.sunken`), omit the highlight (sunken
surfaces shouldn't catch light on their top edge).

### 3.5 Patch-condensation animation

Replaces v0.1's fade-in + highlight-wash. When a `surface_patch` arrives,
the new content **condenses** into existence.

**Three components, all running concurrently over 800ms (`motion.condense`):**

1. **Content materialisation** — the new content starts at `opacity: 0`,
   `transform: scale(1.03)`, `filter: blur(2px)`. Over 800ms (`easing.emphasis`),
   it animates to `opacity: 1`, `scale: 1`, `blur: 0`. The transition is
   front-loaded — by 40% of the duration (~320ms) the content is already
   90% visible and sharp; the remaining 60% is settle.

2. **Bloom collapse** — a radial-gradient pulse appears centered on the
   new content's bounding box, sized 120% with `accent-glow-strong` at
   center fading to transparent at edges. Over 800ms, it collapses to 50%
   scale and opacity 0. This is the "light converging" effect.

3. **Sweep bar** — a 1px horizontal accent-colored bar sweeps across the
   bottom of the new content over the first 500ms, then fades. This is
   the "ink-jet pass" reading — the agent's stroke laying down the new
   content.

**Reduced-motion fallback:** Components 2 and 3 are dropped entirely.
Component 1 collapses to a simple opacity 0→1 fade over 200ms
(`motion.smooth`). No blur, no scale, no bloom, no sweep.

**Rapid-stream throttling.** When more than 5 patches arrive per second
(typing-speed canvas updates), the animation degrades automatically:
component 2 is skipped (the bloom would visually noise the stream),
component 3 is skipped, only the materialisation (component 1) runs but
at 400ms instead of 800ms. Renderer detects rapid-stream by counting
patch arrivals in a 1-second sliding window.

### 3.6 Modal materialization

```
opacity: 0 → 1 over motion.smooth, easing.emphasis
transform: scale(0.97) → 1.0 concurrently
scrim opacity: 0 → 0.4 (light) / 0.6 (dark) over motion.smooth
```

The scrim is `bg.modal.overlay` — minimally accent-tinted, never pure black.
The modal pane carries `elev.modal` (which includes the accent-glow
component) so it reads as the lit object emerging into focus.

Modal dismiss: reverse over `motion.quick`.

---

## 4. Per-primitive visual

### 4.1 General Lume rules (apply to every primitive)

Before primitive-specific notes, the following universal rules apply
unless overridden:

| Rule | What it means in CSS |
|---|---|
| Surfaces are gradient pairs | `background: linear-gradient(180deg, <token>.top, <token>.btm)` |
| Borders are directional | `border: 1px solid <token>.btm; border-top-color: <token>.top` |
| Raised surfaces carry a top-edge highlight | `box-shadow: 0 1px 0 rgba(255,255,255,X) inset` (X = 0.06 light, 0.06 dark) |
| Selection / focus emit light | Two-stop glow recipe §3.2 |
| Loading is a skeleton pulse with linear gradient | (unchanged from v0.1) |
| Hover transitions over `motion.quick` | (unchanged) |
| Center-glyph surfaces use donut glow | §3.3 |

Each primitive table below lists only the **Lume-specific notes**. Layout,
density, edge cases, states inherited from v0.1 §2 are preserved unless
explicitly contradicted here.

### 4.2 Primitive-by-primitive notes

#### `text` · `heading`

Inherit body and section-title styles from v0.1. No Lume-specific
treatment — typography carries hierarchy, light does not.

Exception: an `h1`-equivalent at the top of a freshly-materialised pane
inherits the patch-condensation animation §3.5 like any other new content.

#### `container`

Default container (`border: true`): directional `border.subtle`, surface
gradient `bg.surface`, padding `space.5`, radius `radius.md` (= 8px under
Lume). Raised variant: gradient `bg.surface.raised`, inset top-highlight.

#### `list` · `tree`

Selection rendering uses the two-stop glow §3.2:

```css
.list-item.selected, .tree-item.selected {
  background:
    radial-gradient(ellipse at 30% 50%, var(--accent-glow-core) 0%, var(--accent-glow) 20%, transparent 70%),
    linear-gradient(180deg, var(--accent-subtle), transparent);
  box-shadow:
    0 0 12px -2px var(--accent-glow-core),
    0 0 24px -6px var(--accent-glow-strong);
}
.list-item.selected::before {
  content: '';
  position: absolute;
  left: 0; top: 4px; bottom: 4px;
  width: 2px;
  background: var(--accent);
  border-radius: 2px;
  box-shadow: 0 0 6px var(--accent-glow-strong);
}
```

The accent left-bar gains an accent-glow itself — the bar is the *edge of
the lit pocket*, not a paint stroke.

#### `table`

Highlighted row (the agent flagged this row): same recipe as selected
list-item, but with `background-position: 0 50%` so the gradient sits
toward the left of the row (where the eye enters). Sort-active column
header gets `accent.subtle` text color, no glow (header text must read
clearly).

Skeleton rows: `state.loading` linear-gradient with skeleton-pulse
animation §3.5 — unchanged from v0.1.

#### `button`

- **Primary:** `linear-gradient(180deg, accent, accent.hover)` fill,
  `border: 1px solid accent.hover; border-top-color: rgba(255,255,255,0.18)`,
  two-stop glow §3.2.
- **Secondary:** `linear-gradient(180deg, bg.surface.raised.top, bg.surface.raised.btm)`,
  directional `border.default`, inset top-highlight.
- **Ghost:** transparent; hover paints `accent.subtle`. No glow until hover.
- **Danger:** transparent fill, `border.state.error.edge`, `text.state.error.fg`.
- **Disabled:** `state.loading` fill, `text.disabled` text, no glow, no border.
- **Focus:** layered box-shadow — `0 0 0 2px accent, 0 0 0 6px accent.glow`
  on top of the existing two-stop glow.

#### `input`

Default: gradient `bg.surface.raised`, directional `border.default`,
inset top-highlight (1px). Focus: `border-color: accent`, layered shadow
`box-shadow: 0 0 0 1px accent, 0 0 0 4px accent.glow, 0 0 12px accent.glow-core`.

Error: `border-color: state.error.edge`, error-message helper below.
No glow on error state — the error is the salient signal, glow would compete.

#### `choice` · `toggle`

Dropdown trigger inherits secondary-button look. Open menu: `bg.surface.raised`
gradient, `elev.popover`, directional border. Selected item in menu:
accent.subtle background, accent checkmark.

Radio + checkbox + switch: same v0.1 shapes; checked state uses `accent`
fill with the two-stop glow recipe applied as `box-shadow` (smaller-radius
glow because the elements are small: `0 0 3px accent.glow-core, 0 0 6px accent.glow`).

#### `image` · `chart`

Image: surface-sunken background as placeholder; no Lume chrome — images
are content, not material.

Chart: bars/lines use `accent` fill with a soft `accent.glow` underglow
(`box-shadow: 0 0 6px accent.glow`). Tooltip: `bg.surface.raised`,
`elev.popover`, directional border. Multi-series uses chroma-reduction
on a single hue (per v0.1).

#### `form`

Inspector mode (with context-binding trait): label-left grid layout,
inputs use Lume input recipe above, no per-form chrome.

Submit row: primary button + secondary "Cancel".

#### `toolbar`

Surface `bg.surface` gradient, directional `border.subtle` (top or bottom
depending on toolbar position). Separators 1px `border.subtle`, vertical,
16px tall.

#### `menubar`

Menu surface: `bg.surface.raised`, `elev.popover`, directional border.
Item hover: `accent.subtle` background (no glow — menubars are mode-bridges,
glow would noise them).

#### `tabs`

Tab labels: `type.body`, `text.secondary` inactive, `text.primary` active.
Active tab: 2px `accent` underline + 1px `accent.glow` underglow below
(makes the underline read as *lit*, not just *colored*).

Wizard variant: step dots use a small donut-glow §3.3 around the current step.

#### `pane`

Container surface: gradient `bg.surface`, directional border, `radius.md`
(= 8px). Modal pane variant: `radius.lg` (= 12px, concentric with window),
`elev.modal` including its accent-glow components.

Drag-in-flight: `elev.drag` shadow, ghost at 50% opacity. No accent-glow
on drag (it's a transient operation, not an active state).

#### `status` · `progress`

Status: text only, optional leading icon. When carrying `loading: true`
trait, icon-area renders an 8×12px skeleton pulse-bar.

Progress: 4px track `bg.surface.sunken` gradient, accent-fill bar with
the two-stop glow shadow underneath (the bar reads as *lit*, not painted).
Knob (for scrubbers): accent-fill circle with surrounding glow.

#### `divider`

Single 1px line, `border.subtle.btm` color. No Lume glow — dividers are
quiet by design.

#### `media` · `canvas-region` · `timeline` · `vector-path` *(editor-class)*

**`canvas-region`** — the Lume boundary marker.

- Background: `bg.surface.sunken.btm` solid (no gradient — opaque is the point).
- Border: 2px solid `accent` (active editing target) or
  `border.default.btm` (inactive). Border is solid color, not directional —
  this surface is opaque material, not light.
- Radius: **0** (`radius.0`).
- Outer ambient: 0 0 20px `accent.glow` shadow (so the active canvas signals
  "this is the focus" without applying Lume material *inside* the region).
- Cursor: per active tool.
- Selection overlay: 1px dashed marching-ants line, `accent` color.

The contrast between the lit chrome surrounding the canvas-region and the
opaque sharp-cornered region itself is load-bearing: it visually marks the
Tier-1 boundary where the agent's chrome ends and the user's raw work begins.

**`media`** (audio/video):

- Frame area: `bg.surface.sunken.btm` opaque (same logic as canvas-region).
- Transport bar: full Lume material (gradient surface, directional border,
  accent-glow on scrubber knob).
- Waveform (audio): `accent.subtle` fill, `accent` for played portion.
  (Detail mockup follows in spike.)

**`timeline`:**

- Ruler row: surface gradient with `type.caption` `text.secondary` ticks.
- Track row: opaque `bg.surface.sunken.btm` (the track surface is editor-class).
- Clip rendering: `border.default` outline, `bg.surface.sunken.btm` interior
  with media thumbnails inside.
- Selected clip: 2px `accent` border + outer accent.glow.
- Playhead: 2px vertical `accent` line spanning all tracks, with a 12×12 downward
  triangle at top.

**`vector-path`:**

- Path stroke: 2px `accent` (active) or 1px `text.primary` (inactive).
- Anchor: 8×8 `bg.surface.raised` square with 1px `accent` border.
- Selected anchor: 8×8 `accent` solid + 4px `accent.glow` halo (small donut).

---

## 5. Composition idioms

The five idioms from CONCEPT.md's Composition-Idiom Library, rendered in
Lume material. None of them visually mimic the era they reference; all
of them are layouts the agent infers from a request, painted in this
material.

### 5.1 Norton-Commander

Two panes side-by-side, equal width by default. Each pane: directional
border, surface gradient, internal `list` with `type.mono.data` for the
data-grid feel. Resize divider between them carries the standard pane
drag treatment. Shared toolbar below.

Focus moves between panes via Tab; arrow keys within active pane. Density
typically compact.

What is **not** taken: blue-on-white box-drawing, function-key labels at
bottom, heavy borders. The agent expresses the layout; Lume renders it.

### 5.2 Wizard

`container` with step `tabs` + `form` per step + `toolbar` (back/next).

Steps render as small dots connected by lines:

- Completed: filled `accent` dot, connecting line is filled `accent`.
- Current: ring of `accent` around `bg.surface.raised` core, plus
  `accent.glow-strong` halo (donut glow — the current step is *the
  lit one*).
- Upcoming: `border.subtle` ring around `bg.surface.raised`.

Form renders inspector-mode (label-left grid). Back / Next: secondary /
primary buttons at bottom, right-aligned for forward motion.

### 5.3 Spotlight

Centered `input` + `list` of hits. The **showcase moment** for Lume.

- Stage: radial accent-glow centered on the input (background of the
  stage gets `radial-gradient(ellipse at 50% 30%, accent.glow, transparent)`).
- Input: 48px tall, `type.heading.2` size, leading search icon, the
  three-stop Spotlight glow recipe §3.2.
- Results: `bg.surface.raised` gradient, `elev.popover`, padding
  `space.2`. Focused item uses the two-stop glow §3.2 with
  `radial-gradient(at 25% 50%, glow-core, glow, transparent)` background.

The stage itself glows — the user's eye is led by the canvas before they
even read the input. This is what makes Spotlight feel less like a search
box and more like the agent *lighting up* in response.

### 5.4 Dashboard

`grid` of `container` with `chart`, `status`, KPI-`text`.

KPI cards: standard raised-surface treatment (gradient + directional
border + inset highlight). Value rendered in `type.mono.data` at display
size; delta line below in `type.caption`. The delta-arrow glyph gets a
small text-shadow in `accent.glow` when positive
(`text-shadow: 0 0 6px accent.glow`) — text-only, no pill, no badge.

Charts: bars use `accent` fill with `accent.glow` underglow.

### 5.5 Photoshop-workspace

The critical Lume test — material around an opaque editor boundary.

- Left toolbar: 48px wide, surface-sunken gradient (this is editor-class
  chrome, but still chrome, so it gets Lume material). Tool buttons:
  `style: "compact"` ghost buttons.
- Active tool button: **donut glow** §3.3 + 1px `accent` border. The
  icon glyph sits in a clean `accent.subtle` pocket; the bright cyan-white
  ring radiates outward.
- Center canvas-region: opaque, sharp-cornered, 2px `accent` border
  + outer `accent.glow` shadow.
- Right inspector (`form` with context-binding): full Lume material,
  sliders use the standard track + accent-glow knob recipe.
- Right layer-stack (`tree` with layer trait): full Lume selection halos
  on selected layers.

The visual story: lit toolbar holding lit tools, opening into an
unlit raw work surface, surrounded by lit inspector + lit layers. The
agent's hand is the lit part; the canvas is the user's.

---

## 6. Motion language

### 6.1 Patch arrival — condensation

Per §3.5: 800ms three-component condensation (content materialise + bloom
collapse + sweep bar). Reduced-motion: collapses to a 200ms opacity fade.
Rapid-stream: degrades automatically when >5 patches/sec.

Snapshot arrival: full-canvas crossfade over `motion.smooth` with
`easing.emphasis`. No condensation (snapshot is too big to materialise
gracefully).

### 6.2 Modal — materialisation

Per §3.6: 200ms opacity + scale, scrim fades concurrently. Dismiss reverses
over `motion.quick`.

### 6.3 Selection / focus — light-on

Background tint fades in over `motion.quick`. Glow recipe applies
instantly (focus must be visible the moment the user tabs to it; we
don't fade the focus *visibility*, only the background tint).

### 6.4 Hover

`motion.quick` fade on background tint. Cursor change instant. Glow on
hover (for primary buttons) intensifies via the emphasis variant of the
two-stop recipe §3.2.

### 6.5 Canvas-activate (Spaces switch)

Outgoing canvas: opacity 1→0, 4px horizontal slide over `motion.deliberate`.
Incoming canvas: opacity 0→1, 4px slide-in over `motion.deliberate`,
starting 60ms after outgoing. Direction follows the direction of the user's
switch (next / prev).

Reduced-motion: instant swap.

### 6.6 Palette switch

When the user changes palette mid-session ("make it warmer"), Tier 2 emits
a `surface_patch` that re-tints accent tokens. Client renders the change
as a 200ms crossfade over the affected surfaces (`motion.smooth`,
`easing.standard`). Tree structure is unchanged; only color values cross-fade.

Reduced-motion: instant token swap, no transition.

### 6.7 Drag-in-flight

Ghost: 50% opacity, `elev.drag`. Drop-target: 2px dashed `accent` border
fade-in over `motion.quick`. No glow during drag — drag is operational,
not active-state.

---

## 7. Edge cases and anti-patterns

### 7.1 Empty canvas

Unchanged from v0.1. `bg.canvas` gradient, no chrome, single `status`
primitive in lower-left: `Canvas ready. ⌘K to start.` in
`type.caption text.tertiary`.

### 7.2 Loading > 300ms

Skeleton-pulse animation per §3.5. No spinner. Optional status text
appears below skeleton after 3s.

### 7.3 Button-in-flight (the single spinner exception)

A button that fires an external-effect action (Send, Publish, Delete)
cannot show a skeleton — there's no content to skeletonise. Recipe:
button stays in primary variant, label replaces with verb + animated dots
("Sending."/"Sending.."/"Sending..."), no spinner glyph, no spinning ring.
Period.

### 7.4 Errors

Three scopes — unchanged from v0.1:

1. Primitive-scoped: 1px `state.error.edge` border, inline message
   `state.error.fg`.
2. Field error: `state.error.edge` border on input, helper-text becomes
   error.
3. Canvas-scoped: a `status` primitive at the top of the affected
   container, leading `alert-triangle` icon, inline retry action.

**No toasts.** The canvas is the surface of record. Errors live in the
tree, in context.

### 7.5 Confirmation modal

Per CONCEPT.md "External-effect action confirmation contract". Visual:
modal pane with `radius.lg`, `elev.modal` (including the accent-glow
components), scrim is `bg.modal.overlay`. Title heading.2, body, caveat
in `text.secondary`, toolbar right-aligned (Cancel secondary, primary
action verb-labelled).

Danger variant: primary button uses `button.danger` style (transparent +
error-border + error-text). Focus opens on Cancel (deliberate friction).

### 7.6 Anti-pattern list — implementers must NOT

- Add colored **status pills** in any palette. Body text + accent row tint
  is the affordance.
- Add **emoji glyphs** as decorative chrome. Agent-content emoji passes
  through; implementer-chrome emoji is forbidden.
- Add **toasts** / floating notifications.
- Add **circular spinners** outside the §7.3 exception.
- Add **gradients** beyond the documented ones (surface gradients §3.1,
  button-fill gradients §4.2, skeleton pulse §3.5). No accent-to-purple
  gradient buttons, no glassmorphism, no neumorphism.
- Add **drop shadows** to flat content. Shadows are reserved for
  temporally elevated surfaces (§2.10).
- Add a **branded splash** or empty-state illustration.
- Place **bright `accent-glow-core` directly under a centered glyph**.
  Use the donut variant §3.3 instead.
- **Skin per era.** Single material, three user-bound palettes. Anything
  else is dynamic skinning, which v1 doesn't ship.

---

## 8. Accessibility floor

Unchanged from v0.1.

- Contrast ratios verified WCAG 2.2 AA at body-text size against canvas:
  text.primary ≥ 7.0:1, text.secondary ≥ 4.5:1, text.inverse on accent
  ≥ 4.5:1, accent on canvas ≥ 3.0:1 for non-text uses.
- Focus rings: always 2px solid + glow halo, never colour-only.
- Hit targets: 32×32 minimum (24×24 only in dense toolbars with
  keyboard-accessible parallel paths).
- Motion respects `prefers-reduced-motion: reduce` — concretely the
  fallbacks documented in §3.5 (condensation collapse), §6.5 (Spaces
  switch) etc.
- Colour as sole signal: forbidden. Every state communicated through
  colour also carries a text label, an icon, or both.
- Keyboard reach: every interactive primitive Tab-reachable, Enter/Space-
  operable, arrow-key navigable within composite primitives.

Lume-specific accessibility note: the `accent.glow-core` token at high
alpha (≥0.50) approaches `bg.surface.raised` lightness. Renderers must
verify that text *inside* a glow-core-affected region (e.g. focused
input) still meets contrast against the resulting blended background,
not against the unblended surface. The token-build step generates a
blended-background reference per palette for this check.

---

## 9. Out of scope (explicit)

| Out of scope | Belongs in |
|---|---|
| Pixel-level editor-workspace mockup | Mockup phase + Tier-1 spike |
| `canvas-region` / `timeline` / `media` pixel detail | Mockup phase |
| Brand identity — logo, wordmark, app icon | Separate brand work |
| Onboarding / first-run | Separate UX phase |
| Settings / Preferences screen | **Does not exist by design** — prefs are conversational |
| Marketing site visuals | Separate track |
| Email / transactional notification visuals | No such surface |
| Cross-platform native-control divergence | Tier-1 spike |
| Print stylesheets | Not a v1 workload |

---

## 10. Implementation contract

- Token names from §2 are authoritative; renderer code references tokens
  by semantic name, never raw values.
- Lume implementation recipes from §3 are normative. Renderers must
  implement them. Any divergence requires a spec amendment.
- Per-primitive Lume notes in §4 are normative for default + interactive
  states. Variants restricted to those listed.
- Composition idioms (§5) are normative for the layout relationships.
  The Skill may swap primitive choices within an idiom (e.g. `list` →
  `table` when data is uniform); the layout language is fixed.
- Motion language (§6) is normative. New transitions require an amendment.
- Anti-patterns (§7.6) are blockers. Code that reintroduces them must
  not ship.
- The default palette is **Lagoon**. Palette binding is per-`contextKey`
  via `ui-prefs`. Renderers must implement the §6.6 palette-switch
  crossfade.

---

## 11. Open questions for review

The 8 questions in v0.1 §9 are mostly resolved by the Lume decision and
the three-palette adoption. Carry-over and new questions:

1. **Donut glow refinement.** The current recipe (§3.3) is normative but
   visually unfinished — the ring lands slightly close to the border in
   small surfaces (36px Photoshop tool button). Spike-phase to refine
   the gradient stops without changing the principle. *Carry-over to
   the Tier-1 spike, not blocking spec freeze.*

2. **Glow alpha calibration.** Per-palette glow / glow-strong / glow-core
   alphas are tuned to feel "subtle but present". Codex review or first-
   user feedback may push them up or down. Specifically: Lagoon's
   glow-core at 0.60 in light mode is the brightest of the three; if
   sustained-use feedback says "too magical", lower to 0.50.

3. **Patch-condensation duration.** 800ms matches v0.1's fade-in. Lume
   spike-time empirically: with three components running, does it feel
   slower than 800ms? Rapid-stream throttling (§3.5) helps but doesn't
   address the single-patch case. Try-it-and-see.

4. **Performance budget under Lume.** Multi-layer box-shadows + gradients
   + no blur should stay 60fps in Electron + Skia at typical canvas
   density (50 rows + 8 panes + active patch animation). Verified by
   measurement in spike, not by assumption.

5. **Marketing accent for app icon / splash / launch video.** Lagoon is
   the runtime default and the spec recommendation. A reviewer might
   argue for Petrol on the icon (more "professional, calmer") with
   Lagoon at runtime. This is a brand decision adjacent to the spec.

6. **Three palettes is the right number.** Two might be cleaner; four
   might be necessary for cultural reach (a green for natural-sciences
   users, a magenta for design audiences). Three feels like the right
   trade-off between *user agency* and *brand coherence*; revisit at
   v2 if usage data argues otherwise.

7. **Palette per-canvas vs per-user.** Spec says per-`contextKey`, which
   means per-canvas when contexts differ. Some users may want a single
   global palette; CONCEPT.md's pref model allows a fallback chain
   (canvas-context → user-global → default) — that fallback may need
   explicit documentation.

8. **Reduced-motion fallback for condensation (§3.5).** Currently:
   components 2+3 dropped, component 1 reduces to opacity fade only.
   A reviewer might argue we should also retain the sweep bar (it's
   the smallest of the three, doesn't violate motion-reduction). Open.

### Type-architecture questions (added in v0.3)

9. **Prose-trigger heuristics for the Skill.** The "two+ sentences = prose,
   single sentence may stay structural" rule is a starting point but
   under-specified at the edges. Concrete cases that need codification:
   single-sentence narration like Walkthrough-1 step 14 ("Three people
   are under budget — Anna, Bernd, Cara") — narration or structural?
   Confirmation modal bodies that mix narrative + warning ("Send PDF to
   X? This email cannot be unsent.") — fully prose, or split? Bullet
   lists embedded in prose mode — list items prose or structural?
   Under-triggering means everything reads structural and we lose the
   editorial gain; over-triggering means random sans/serif flapping.
   Needs a Skill heuristic with worked examples before first ship.

10. **Mixed registers within a single primitive.** The `style` trait
    sits at the primitive level. If a prose-mode `text` primitive
    contains inline code (`ticket-1234`, file paths, version strings),
    does the renderer auto-switch those tokens to mono, or must the
    Skill emit nested primitives? Decision affects Skill output shape
    and renderer complexity. Recommendation pending: probably auto-
    detect classic monospace contexts (backticked content, IDs matching
    a regex), but the rule needs to be deterministic and documented.

11. **Composition idiom × register mapping.** Each of the five idioms
    has a natural typographic distribution. Wizard summary screens —
    prose body, structural headings, structural form fields, no mono.
    Norton-Commander — all mono (data-grid), no prose. Photoshop-workspace
    inspector — all structural, no prose. Dashboard — structural for
    KPIs, optional prose for narrative caption above. Spec should ship
    an idiom-register table in §5 so implementers don't improvise.

12. **Prose register × canvas-activate × palette swap performance.** When
    the user switches between canvases with different palette bindings
    *and* different prose content, the activate transition crossfades
    both palette tokens and (in some cases) typographic content. CSS
    variables make palette cross-fade near-free; the type families are
    pre-loaded once per session, so font cost is zero per switch. Worth
    verifying in the Tier-1 spike — particularly that variable-axis
    rendering doesn't introduce repaint cost above 16ms on mid-range
    hardware.

---

## 12. Changelog

- **v0.4 (this document)** — **Signal accent added** (§2.5.5). One
  universal, palette-independent magenta-pink (`#D6177A` light / `#FF5FA8`
  dark) for the rare loud moment — hero CTA, critical emphasis, non-UI
  brand surfaces (web, video). Capped at one element per view; does not
  bind to the accent slot, does not replace destructive/error semantics.
  Constraint #4 ("one accent slot") and §1.3 ("multiple accent slots")
  amended to carve out Signal explicitly. Rationale: as Lume extended
  beyond the canvas to marketing and video, the deliberately-quiet accent
  could not carry a genuine pop; a single capped Signal closes that gap
  without re-pluralising the accent slot. Companion implementation in the
  Lume design system (`colors_and_type.css` §4b, `.btn-signal`, preview
  card `colors-signal.html`).

- **v0.3** — Three-register typography adoption. Geist
  (structural) + Source Serif 4 (prose) + Geist Mono (data/code) replace
  the v0.2 Inter + JetBrains Mono baseline. Type scale gains
  `type.prose.*` tokens. The `style: "prose"` trait on `text` primitives
  routes to the serif register; default remains structural. Companion
  preview at `./visual-spec-preview-type.html` (Architecture C —
  recommended path). Open question 1 (donut-glow refinement) carries over.
  New open questions in §11: prose-mode trigger calibration, font-loading
  budget under offline-first scenarios, prose-register-in-walkthrough-4
  density.

- **v0.2** — Lume material adoption. Light-as-material
  thesis introduced; surface luminosity, accent-as-illumination,
  directional borders, soft corners formalised. Three user-bindable
  palettes (Petrol, Atelier, Lagoon — Lagoon default) replace the
  single-accent choice. Radius scale shifted one stop softer (editor
  surfaces stay 0). Two-stop glow primitive replaces v0.1 single
  accent-subtle. Patch-condensation replaces fade-in. Donut-glow rule
  introduced for centered-glyph surfaces. Token model gains
  `accent.glow-core`. Open questions 1-7 from v0.1 §9 resolved by
  material decision; new questions in §11.

- **v0.1** — first draft. Flat tokens, single-accent choice (Petrol
  proposed default), restraint baseline. Defined the 24-primitive
  catalogue, the five composition idioms, motion/edge-cases/a11y.
  Superseded by v0.2; preview retained at
  `./visual-spec-preview.html` for material-comparison.
