# Screenshot shot list

SPEC-503 deliverable #5: this sandbox cannot produce real product
screenshots (no display, and the dashboard's real UI has landed in pieces
across SPECs 109/110/205/304/307/401/405 — several of the screens below are
real and running, but capturing them needs an actual browser against a
running hub, which is an owner action, not something scriptable here).
Every page that would benefit from a screenshot instead carries an HTML
comment marker (invisible when the site renders) naming exactly what
belongs there. This file is the checklist for turning those into real
images — never replace a marker with a placeholder or stock image; leave
it as a marker until a real screenshot exists.

## How to fill one in

1. Take the screenshot against a real, running hub (the dashboard, at the
   state the shot list below describes).
2. Save it as a `.png` under `v3/site/docs/src/assets/screenshots/`,
   named after the page (e.g. `install-wizard-welcome.png`).
3. In the page's Markdown, replace the `<!-- screenshot: ... -->` comment
   with a real image:

   ```md
   ![Alt text describing what the screenshot shows](../../assets/screenshots/install-wizard-welcome.png)
   ```

   (Adjust the relative path to the actual page's depth — Starlight
   resolves images relative to the Markdown file, and optimizes anything
   under `src/assets/`.)
4. Delete this shot's row from the table below once it's done, or mark it
   done — whichever keeps this file useful as a checklist rather than a
   permanent record.

## The list

| # | Page | What to capture | Notes |
|---|---|---|---|
| 1 | `install.md` | The first-run wizard's welcome screen, right after opening the hub for the first time (SPEC-110 deliverable #1) | Before any setup step is filled in — the very first thing a new user sees |
| 2 | `marketplace.md` | The install-confirmation screen for a container-based marketplace entry, showing its declared kind, source, `verified` flag and mounts (SPEC-304 deliverable #3) | Pick an entry that actually shows the "stronger warning" state too if one is easy to demonstrate, or take a second shot for that |
| 3 | `memory.md` | A pending review proposal in the dashboard's memory explorer, with its diff against the note it would change, and the approve/reject controls (SPEC-206 policy, review UI landed with a later dashboard SPEC) | Needs a real merge/rename/retire proposal to exist first — the automated-capture path (SPEC-207) is the easiest way to generate one worth screenshotting |
| 4 | `access.md` | The connected-clients list, showing at least two named connections with their last-activity time and read/write access (SPEC-108 deliverable #1, SPEC-110 deliverable #4) | Real names read better than "Test Client 1" — use whatever two tools were actually connected while testing this guide's own walkthrough |
| 5 | `first-shared-memory.md` | The memory explorer showing the note this walkthrough creates ("Fieldnotes"), with the connected-clients list visible showing both tools that touched it | Best captured by literally running the walkthrough once and screenshotting the result |
| 6 | `automations.md` | The automations editor with one rule open, its three cards (when / if / then) visible (SPEC-307 deliverable #4) | One of the canned recipes is an easy, presentable choice |
| 7 | `agents-messages.md` | The Agents screen: live directory on one side, a message thread open on the other (SPEC-405 deliverable #1) | Needs at least two active sessions and one exchanged message to look like anything |
| 8 | `install-synology.md` | Container Manager's own overview screen right after opening it, showing the left-hand navigation (Project, Container, Image, Registry) (SPEC-602) | Capture on a real Synology device running Container Manager — see this page's own owner checklist (an HTML comment at the bottom of the generated file). This page is generated from `scripts/lib/synology.mjs` — edit the marker text there, not the `.md` file, then run `npm run gen:synology` |
| 9 | `install-synology.md` | The project-creation step with the page's compose file pasted into Container Manager's text box, before continuing to the next step (SPEC-602) | Same device; the compose text should be exactly what the generated page shows — do not retype it. Generated page, see note above |
| 10 | `install-synology.md` | The finished project showing status Running, with its one container (`palaia-hub`) listed (SPEC-602) | Same device, after starting the project. Generated page, see note above |

## Format guidance, once a screenshot exists

- PNG, browser window content only (no OS chrome / title bar) — crop
  tightly to the relevant panel rather than the whole viewport where that
  reads better.
- Prefer the light theme for consistency across shots, unless a shot is
  specifically about the theme itself.
- Redact anything that isn't meant to be public before it's committed —
  this repository is public, and a screenshot is exactly the kind of thing
  that leaks a real token or address by accident.
