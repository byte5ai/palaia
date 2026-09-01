# Spec update — v0.4 Signal accent

This folder holds the changes to land on
[`byte5ai/omadia-ui`](https://github.com/byte5ai/omadia-ui) for the **v0.4
Signal accent**. I can read the repo but cannot push to it, so this is the
hand-off package — apply it however you commit (paste, PR, or copy the file).

## What changed in `docs/visual-spec.md`

The updated `docs/visual-spec.md` in **this** project is the canonical v0.4.
The concrete edits over the repo's v0.3:

1. **Header version line** — added a `Version 0.4 — Signal accent` paragraph
   above the v0.3 paragraph.
2. **§1.2 constraint #4** — "One accent slot" → "One accent slot, plus one
   Signal", with the carve-out sentence.
3. **§1.3 "What Lume is NOT"** — the *Multiple accent slots* row now notes
   Signal is a separate, capped token, not a second accent slot.
4. **New §2.5.5 — Signal — the loud accent (palette-independent)** — full
   token table (light + dark), hue-gap rationale, usage rules, and the
   "why not a second accent slot" rationale. Inserted between §2.5.4 and
   §2.6.
5. **§12 Changelog** — new `v0.4` entry at the top.

## How to apply

Easiest: copy the whole updated `docs/visual-spec.md` from this project over
the repo's copy and commit:

```
git switch -c spec/v0.4-signal-accent
# replace docs/visual-spec.md with the version from the Lume design system
git add docs/visual-spec.md
git commit -m "spec: v0.4 — add Signal accent (§2.5.5)

One universal, palette-independent magenta-pink (#D6177A light / #FF5FA8 dark)
for the rare loud moment — hero CTA, critical emphasis, non-UI brand surfaces.
Capped at one element per view; outside the accent slot; does not replace
destructive/error semantics. Amends constraint #4 and §1.3."
git push -u origin spec/v0.4-signal-accent
# open PR against main
```

## Token reference (for any other repo file that needs it)

Light mode:

```
signal            #D6177A
signal.hover      #C2126D
signal.active     #AD0E60
signal.subtle     rgba(214,23,122,0.10)
signal.glow       rgba(214,23,122,0.24)
signal.glow-strong rgba(214,23,122,0.42)
signal.glow-core  rgba(255,200,230,0.55)
```

Dark mode:

```
signal            #FF5FA8
signal.hover      #FF77B6
signal.active     #FF90C4
signal.subtle     rgba(255,95,168,0.18)
signal.glow       rgba(255,95,168,0.30)
signal.glow-strong rgba(255,95,168,0.46)
signal.glow-core  rgba(255,215,235,0.50)
```

Hue ≈335°. Sits in the only open gap in the token hue map (error 25°,
Atelier 50°, warning 80°, success 150°, Lagoon 200°, Petrol 235°).
Complement of Lagoon/Petrol, split-complement of Atelier, unambiguously
not-red so a loud CTA never reads as destructive.

## Note on `docs/visual-spec-preview-lume.html`

The repo's companion preview HTML still renders the v0.3 palette set. A
paste-ready Signal block is now in **`docs/spec-preview-signal-block.html`**
— a standalone, self-contained page (light + dark toggle) for review. To land
it in the repo's preview:

1. Add the `--signal-*` CSS variables to the preview's `:root` (light) and
   `[data-mode="dark"]` token blocks — the exact values are commented at the
   top of `spec-preview-signal-block.html` (note: the repo preview names its
   base accent token `--accent`, not `--accent-fill`, so the Signal base is
   `--signal-fill` there too, matching the design-system naming used in the
   block).
2. Copy the `<section class="section" id="signal"> … </section>` (marked with
   `PASTE FROM HERE … PASTE TO HERE`) into the preview body, right after the
   accent-palette section. Move the few local helper rules from the block's
   `<style>` into the preview's stylesheet if you prefer.

The design system's own `preview/colors-signal.html` (light) and
`preview/colors-signal-dark.html` (dark) already demonstrate Signal in the
Design System tab.
