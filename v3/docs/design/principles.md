# palaia v3 — design principles, made concrete

> MASTERPLAN §4 states the UX doctrine as eight rules. This document turns each
> rule into something a reviewer can check and an implementer can copy: what it
> means on a real screen, and what violating it looks like. The rules bind; PRs
> that break them are rejected (§4 preamble).
>
> Companion document: [`system.md`](system.md) (tokens, components, words,
> information architecture).
>
> Version 3 — 2026-10-23 — the owner replaced the Lume look with the
> "Simplicity is king" design system (#570, #571). Rule 6 is rewritten for it,
> §0.1's list of words follows the new glossary, and the per-screen rules (§3)
> follow the new places: Overview, Memories, AI apps, Add-ons, Automations and
> Settings. Rules 1–5, 7 and 8 and §0.2 are unchanged in substance. Earlier
> versions are in git history.

## 0. Two rules that sit above the eight

The eight rules of MASTERPLAN §4 are about *what a screen does*. These two are
about *what a screen says*, they apply to every screen without exception, and a
PR that breaks either is rejected the same way.

### 0.1 — No jargon in the surface (binding)

**No protocol name, standard, acronym, transport or implementation word appears
in a label, heading, button, badge, status line or option name.** The technical
term is not banned — it is demoted to hint text, a sub-line, a `title`
attribute, or a doc link, where the person who wants it finds it and the person
who does not is never taxed by it.

The test is rule 5's test, applied to every word instead of only to errors: **if
a competent user would have to search the web to know whether a control applies
to them, the label is a bug.** A user who cannot tell "Locked" from "Cloud"
because the badge says `auth required` has been handed a decision they cannot
make.

| Don't | Do |
|---|---|
| "Add any OIDC sign-in later" | "You can add GitHub, Google or **your company sign-in** later" — with `title="Any OpenID Connect provider — Entra ID, Okta, Authentik, Keycloak"` |
| "Streamable HTTP · tool search · push events supported" | "Connects straight over the web · finds tools as it needs them · gets updates without asking" |
| `auth required` · `auth + hardening checklist` | "sign-in required" · "sign-in, plus a security checklist" |
| "tailnet only" | "Private — only devices on your network or VPN" — Tailscale is named in the step that actually sets it up |
| "not connected · signed bundle" | "Ready to connect · one click to install" |
| "Any MCP client" | "Any other AI app" |
| "12 tools exposed" · "Already mounted at the gateway" | "37 tools available to them" · "Your agents can already see these three" |
| "runs a deterministic file operation" | "edits the file directly" |
| "stay out of the context window" | "never reach the chat" |
| "Frontmatter" · "validated — warn only" | "Fields" · "Two optional fields are missing — palaia notes that and keeps the file" |
| "Codex read the signed MSA" | "Codex read the signed **master agreement**" |
| "target: connected in under 2 minutes" | "most people finish this one in a minute" |

palaia's own words are **not** jargon, because the product teaches them once
and then relies on them — but there is exactly one word per concept, and it is
the plain one: **memory** (not vault), **note**, **AI app** (not client),
**access key** (not token), **tool set** (not tool profile), **dashboard
sign-in**, **Private / Cloud / Public**, **To file**, **Needs review**,
**search index**. The full glossary is `system.md` §3. The internal names
(vault, token, profile, `locked`) stay where people type them: tool names,
config files, commands and the docs.

### 0.2 — Name a client exactly, never a family (binding)

**"Claude Code" on its own never appears.** The CLI in a terminal and the
desktop app are two different clients: different install paths, different rows
in the client list, independent tokens, independent last-seen times. One name
for both makes the client list lie ("4 connected" over three rows) and makes an
activity entry unattributable — which breaks rule 7, since provenance that
cannot identify the actor is not provenance.

| Don't | Do |
|---|---|
| "Claude Code" | **"Claude Code CLI"** |
| "Claude Code" (meaning the app), "Claude Desktop" | **"Claude Code (Desktop app)"** |
| "Claude Code wrote Billing service" | "Claude Code CLI wrote Billing service" |
| "Connect Claude Code" · "Start with Claude Code" | "Connect Claude Code CLI" · "Start with Claude Code CLI" |

Applies everywhere a client is named: the home clients card and activity feed,
the connect page's list and its detail head, the onboarding client grid,
provenance chips, commit lines, empty states and button labels. Generalised:
**use the name printed on the thing the user installed.** Where one install
genuinely covers several surfaces, it stays one row and names them in its detail
line — `claude.ai` is one client, "web, desktop and iPhone".

## 1. The eight rules, applied

### Rule 1 — The browser is the interface; the shell is the escape hatch

Everything a user must do exists in the dashboard. The CLI is for admins and
automation, never the only path.

| Don't | Do |
|---|---|
| "Edit `config.toml` and restart the hub" | A form, a toggle, or a wizard step — the hub applies it live |
| Show a path the user must open in an editor | Show the path read-only with a **Change…** button (`onboarding.html`, step 3) |
| Document a `curl` call as the way to replace an access key | **Revoke access** and **Create access key** on the AI app's row |
| "Restart the hub on the server for this to take effect" | Apply live; where a restart is unavoidable, a **Restart palaia** button in the same place, and the server command only where palaia cannot restart itself |

A shell command appears in the main flow in one place only: the one-liner the
*person's own AI app* needs (`claude mcp add …`) — next to the prompt and config
file alternatives. That command configures the app, never palaia. Commands for
palaia's own server (a backup on a hub without dashboard sign-in, a restart
without a supervisor) are the secondary path, behind a disclosure.

### Rule 2 — Onboarding is "paste one thing"

Target: **client connected in under two minutes.**

| Don't | Do |
|---|---|
| A page of per-app JSON snippets to adapt | One copy button per AI app, prefilled with the address, the tool set and the access key |
| Explain what MCP is before the user can start | Start with the action; the explanation is one hint line |
| Make the user check the connection manually | The page watches for the first tool call and says which tool it was |
| Hide plan and platform limits until failure | State them where the user is about to paste (ChatGPT plan gating, MCPB being local-only — MASTERPLAN §6) |
| Send the user to the terminal for a phone | QR next to the URL |

### Rule 3 — Host install is one step

Target: **first memory written within five minutes of install.** First-run setup
is five steps — your account, where you'll use palaia, your first memory, connect
an AI app, done — and each one ends in a state the person can leave: skipping the
app step lands on the Overview with the same next action, not in a dead end. A
step is ticked only when the hub confirms it, and setup resumes at the first
unfinished step after a reload or restart.

| Don't | Do |
|---|---|
| Ask for storage layout, embedding model, index type | Defaults; every one of them changeable later (rule 4) |
| Present nine options for how to be reachable | Three access modes with "choose this if…", tunnel details deferred to the step that needs them |
| Finish onboarding with an empty screen | Finish on "You're set up" with what was done (account, memory, app) and one obvious next action |

### Rule 4 — Defaults over decisions

Zero mandatory configuration. Every screen ships opinionated defaults with the
reasoning visible.

| Don't | Do |
|---|---|
| An empty "Name" with no guidance | An example in the placeholder and one helper line ("Lowercase letters, numbers and dashes, e.g. work.") |
| A checkbox list with no recommendation | Ask what the person uses, then derive the choice and say why |
| Ask about git | History on, always, with one line saying what it buys ("you can undo it") |
| Ask for a tool set for every AI app | The default tool set, with per-memory Read / Save; tool sets under Advanced |
| Mark every required field | Mark only the optional ones ("Optional") |

### Rule 5 — Self-healing over error messages

An error the user must google is a bug. Findings come with a fix.

| Don't | Do |
|---|---|
| "Index out of sync (code 3)" | "Index is 42 notes behind on *personal* — someone edited the vault in Obsidian while the hub was updating. Search still works, it just does not know these notes yet." + **Reindex now** |
| A red badge that only counts problems | A row that names the finding and carries the one-click fix |
| Silence while something is degraded | Say what still works. Degraded is not broken |
| A modal that blocks the app until acknowledged | A callout in place that names the reason and holds the fix, and disappears when fixed |
| An error that renders as an empty list | "Couldn't load …" with the cause, **Try again** and **Details** |

### Rule 6 — Beauty is a feature: simplicity is king

The eye eats first, and what it should find is calm. Concretely, for this
system (`system.md`): white cards on a light grey ground (deep navy in dark
mode), Nunito Sans at readable sizes, one cyan mark, one action colour, and a
plain sentence where an admin panel would put a gauge. The models are the
self-hosted tools people trust at home — Home Assistant's settings, umbrelOS,
Synology DSM's health card, Hermes — not developer consoles.

Four restraints keep it that way:

1. **One primary action per view.** Count the filled buttons: one, or none.
   Everything else is secondary, plain, or a row with a chevron.
2. **Status is a word and a colour**, in one of five tones, as a pill in rows
   and card heads, a callout for a blocked state with its fix, and a dot plus
   word in the sidebar footer. palaia's own health has one set of words
   everywhere: the Overview verdict and the sidebar always agree.
3. **Readable before dense.** Sentences at 13 px or more, metadata at 12 px or
   more, nothing uppercase, rows at least 56 px tall. Density comes from
   showing less, not from smaller type.
4. **Advanced is collapsed.** Tool sets, renamed tools, webhooks, tunnel
   configuration and server commands sit behind an "Advanced" or
   "Troubleshooting" disclosure; the default path never needs them.

| Don't | Do |
|---|---|
| A dashboard of dial charts and version numbers | One verdict ("palaia is running") with a few pills underneath, each linking to its detail |
| Twelve equal navigation items in groups named after internals | Five places named after tasks, Settings at the bottom |
| Settings as one long page | A hub: a top card (version, state, access, address, Sign out, Restart) and one row per area with its live state in the description |
| A paragraph that explains a control | A label, one helper line, and "What's included?" for the rest |
| A footer note repeated on every page | Say it once, where the decision is |
| Colour as decoration, accent washes, gradients, glows | Colour as state (`system.md` §1.1) |
| A different look from the website and the docs | The same tokens, fonts and mark on all three surfaces |
| Dark mode as inverted light mode | The same design from the dark token values |
| Fixed pixel widths | Usable at 390, 768 and 1440 px; no horizontal page scroll |

### Rule 7 — Trust through transparency

Every automatic action is visible and reversible.

| Don't | Do |
|---|---|
| "Memory updated" | "Claude Code CLI created **Billing service** · work · 2 min ago" |
| Auto-capture running invisibly | A "to file" count and an activity entry per capture |
| A curator that rewrites notes silently | The two-tier rule made visible: adding is autonomous, changing existing knowledge becomes a proposal you approve (Memories › Needs review) |
| "Trust us, it worked" | Verification stated: "All 34 writes verified against their capture id before the inbox entries disappeared" |
| Hiding which AI apps can reach your memory | Every app with its state and last request, and **Revoke access** on its row |

Every change says who made it and when ("Saved by Claude Code CLI · 15:35"); the
history behind it is one click away. History is the undo, and the UI says so.

### Rule 8 — MCP Apps are a standing design question

For every user-facing feature the review asks: is an in-client app surface (§5.7)
the right way to deliver this, or at least a sensible addition? The answer may be
"no" — and must be for security-sensitive administration — but the question is
mandatory. §3 answers it per screen; §4 collects the verdicts.

## 2. The places

| Place | Primary question |
|---|---|
| Overview | Is palaia running, and what needs me? |
| Memories | What do my AI apps remember, and what does palaia want me to check? |
| AI apps | Which apps are connected and working, and how do I connect another? |
| Add-ons | Which tools do my AI apps share, and what else can I add? |
| Automations | What does palaia do by itself when something happens? |
| Settings | How is palaia reached, backed up and kept up to date? |

The Lume-era mockups in `mockups/` are history, not a reference (`system.md` §5).

## 3. Per-screen rules

### 3.1 Overview

Above the fold, in this order: the verdict with its icon ("palaia is running",
"Finish setting up palaia", "Can't reach palaia"), a few pills that summarise
the state ("1 memory · 7 notes", "1 AI app connected", "1 note to file"), the
one next action when there is one, then summary cards that each link to their
detail, and the activity feed.

| Don't | Do |
|---|---|
| Lead with a version number and component names | Lead with the verdict and the next action |
| A primary "Connect your first client" while the real blocker (no memory) is a text link | The blocker is the primary: "Continue setup" |
| "Semantic search: caught up" on an empty hub | The search index only appears while it is not ready |
| "Next step …" visible while the page is still loading or has failed | Loading is a skeleton; an error is "Couldn't load …" with Try again |
| "0 connected · waiting" after a restart for an app that worked before | The last request survives a restart |
| Backups explained on the Overview | One row, "Backup · Last backup 2 days ago", linking to Settings › Backups |

**Rule 8:** yes, as **Hub status** (§5.7) — the dashboard stays the fuller surface.

### 3.2 First-run setup

Five steps on their own page (no sidebar): your account, where you'll use
palaia, your first memory, connect an AI app, done. Restore from a backup is
offered up front. The final screen says "You're set up" with what was done and
**Open palaia**.

| Don't | Do |
|---|---|
| Ask for a network topology | Ask which AI apps the person uses, then derive Private or Cloud |
| Tick a step because the person moved past it | Tick it when the hub has it |
| Mark required fields, leave optional ones unmarked | Mark optional fields "Optional"; give examples, not instructions, as placeholders |
| Preview tool names in the default path | The memory's name and what it's for; tool names under Advanced |
| Let Back from the last step lose a completed step | Back moves one step and keeps every answer |

**Rule 8:** no — setup decides the security posture and needs the browser.

### 3.3 AI apps and connecting one

Apps: every supported app as a row with name, status pill, one line and an
action ("1 of 9 connected"). Connecting one: "Choose what Claude Code CLI can
use" (Read / Save per memory), **Create access key**, the one command, prompt
or config file to paste, and "Test the connection", which turns green on the
first request. Live sessions is the second tab.

| Don't | Do |
|---|---|
| Ask a newcomer to name a tool profile | Per-memory Read / Save, all checked; the tool set under Advanced |
| Present the access key as a secret to carry around | It is already in the command; "Copy it now — palaia can't show it again" |
| No way to take access back | **Revoke access** on the row, with a confirm that names the app |
| An app that cannot work in this mode, offered anyway | "claude.ai needs Cloud mode" with **Set up Cloud mode** |
| The skill texts printed on the page | "Recommended: install the palaia skill" collapsed, with **Install skill** |

**Rule 8:** partly — useful for adding a second app, not for the first one.

### 3.4 Memories

Browse: the folder tree, the note, and its context (fields, history, links).
Needs review: one curator proposal at a time with the change, the reason and the
actions. Errors never render as "No memories yet".

| Don't | Do |
|---|---|
| Raw ISO timestamps, git hashes, "-/-/engine: write …" | "Updated 23 Oct, 15:35", "Saved by Claude Code CLI · 15:35" |
| "1 uncurated" | "1 to file" |
| A generated default description shown as if the person wrote it | "No description yet — Add one" |

**Rule 8:** yes — the recall explorer and the review queue are the in-chat apps.

### 3.5 Settings

A hub: the top card (version, state, access, address, who is signed in, Sign
out, Restart where palaia can restart itself), then rows with their live state
— Access & sign-in, Backups, Telegram, Appearance, Advanced, About & updates.

| Don't | Do |
|---|---|
| One switch labelled "Require sign-in" that actually controls AI apps' access keys | Two rows: "AI apps need an access key" and "Require sign-in for this dashboard" |
| "Saved. Restart the hub for this to take effect." | "Restart palaia to apply your changes" + **Restart palaia** |
| A backup page that is only an error in the default setup | The status, **Download backup**, the security note always visible, and — when blocked — the reason with the control that fixes it |
| Raw tunnel JSON in the main flow | "Show configuration" under the guided step |

**Rule 8:** no — access, sign-in and access keys change the attack surface;
dashboard only (§5.7).

## 4. The rule-8 answers, collected

| Surface | In-chat app? | Reasoning |
|---|---|---|
| Memories › Needs review | **Yes — first** | Decisions with actions; the phone is where this happens (§5.7) |
| Memories › Browse (recall) | **Yes** | Explore, then select; only picked notes enter the chat |
| Overview (hub status) | **Yes** | A welcome panel on the first tool call |
| Add-ons | Yes | Browse in the chat, install in the dashboard |
| AI apps › connect | Partly | Adding a second app, not the first |
| First-run setup | **No** | Decides the security posture; needs the browser |
| Settings › Access & sign-in, access keys | **No** | Changes the attack surface — dashboard only (§5.7) |

Progressive enhancement everywhere: a host without the apps extension gets the
plain-text tool result, and every app has a dashboard equivalent (rule 1).

## 5. Review checklist

Use this on any PR that adds or changes UI:

- [ ] The page's primary question is answered at 1440×900 without scrolling,
      and the page works at 390 and 768 px with no horizontal page scroll.
- [ ] **No jargon in the surface** (§0.1) and the glossary terms only
      (`system.md` §3): read every label, heading, button, pill, status line
      and option aloud.
- [ ] **Every AI app is named exactly** (§0.2).
- [ ] **One primary action** on the page; destructive actions are red text,
      filled red only in their confirm dialog.
- [ ] **Status is word + colour** in one of the five tones; palaia's health
      wording matches the sidebar.
- [ ] Optional fields say "Optional"; required ones carry no marker;
      placeholders are examples.
- [ ] Loading is a skeleton, empty is one sentence and one action, an error is
      "Couldn't …" with Try again — and an error never renders as empty.
- [ ] A blocked state names its reason and holds its fix; a server command is
      only the secondary path.
- [ ] Advanced settings are collapsed.
- [ ] Light and dark both checked; no colour outside the tokens
      (`npm run lint`).
- [ ] Keyboard: every control reachable, focus ring visible, Escape closes
      what it opened.
- [ ] Every automatic action is visible, attributed and reversible.
- [ ] Rule 8 answered in the PR description: in-chat app — yes, no, or later, and why.
