# palaia v3 — design principles, made concrete

> MASTERPLAN §4 states the UX doctrine as eight rules. This document turns each
> rule into something a reviewer can check and an implementer can copy: what it
> means on a real screen, and what violating it looks like. The rules bind; PRs
> that break them are rejected (§4 preamble).
>
> Companion documents: [`system.md`](system.md) (tokens, components, tone) and the
> five screens in [`mockups/`](mockups/).
>
> Version 2 — 2026-08-22 — Rule 6 updated for the restyle onto Lume (glow
> selection instead of a flat tint, the Signal rule); every other rule is
> unchanged from version 1.
>
> Version 2.1 — 2026-08-23 — Rule 6 gained the two restraints that were missing
> from the first Lume pass and that the owner rejected the mockups over:
> **accent restraint** (a countable three-to-six accent elements per screen) and
> the **neutral monospace metadata register**. The review checklist in §5 now
> asks for both. No other rule changed.
>
> Version 2.2 — 2026-08-23 — the mockups were Lume-true by version 2.1 and the
> owner's verdict was **"correct, and clinical"**. Two binding rules are added
> here as §0, because they are not refinements of the eight and a reviewer needs
> to find them: **§0.1 plain language** (no jargon in the surface) and **§0.2
> name a client exactly**. Rule 6 gains a fourth restraint, **the serif rule**,
> and a new half, **warmth** — the mechanisms that make a correct screen
> inviting, written down so that "be warmer" becomes reviewable. §5's checklist
> asks for all four.

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
| "tailnet only" | "your network only" — Tailscale is named in the wizard that actually sets it up |
| "not connected · signed bundle" | "not connected · one click to install" |
| "Any MCP client" | "Any other AI tool" |
| "12 tools exposed" · "Already mounted at the gateway" | "37 tools available to them" · "Your agents can already see these three" |
| "runs a deterministic file operation" | "edits the file directly" |
| "stay out of the context window" | "never reach the chat" |
| "Frontmatter" · "validated — warn only" | "Fields" · "Two optional fields are missing — palaia notes that and keeps the file" |
| "Codex read the signed MSA" | "Codex read the signed **master agreement**" |
| "target: connected in under 2 minutes" | "most people finish this one in a minute" |

palaia's own domain words are **not** jargon and are used freely, because the
product teaches them once and then relies on them: vault, note, observation,
relation, inbox, capture, curator, proposal, client, tool profile, endpoint,
token, access mode, doctor, finding, commit, Markdown. The full list, and where
each demoted term went, is `system.md` §3 rule 0.

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
| Document a `curl` call as the way to rotate a token | **Rotate token** in the client's detail panel (`connect-client.html`, connected state) |
| Offer a "restart required" banner | Apply, then report what changed |

There is exactly one place in these mockups where a shell command appears: the
one-liner the *user's own client* needs (`claude mcp add …`) — and next to it sits
the paste-prompt alternative for agentic clients. That command configures the
client, never palaia.

### Rule 2 — Onboarding is "paste one thing"

Target: **client connected in under two minutes.**

| Don't | Do |
|---|---|
| A page of per-client JSON snippets to adapt | One copy button per client, prefilled with endpoint, profile and token |
| Explain what MCP is before the user can start | Start with the action; the explanation is one hint line |
| Make the user check the connection manually | The page watches for the first tool call and says which tool it was |
| Hide plan and platform limits until failure | State them where the user is about to paste (ChatGPT plan gating, MCPB being local-only — MASTERPLAN §6) |
| Send the user to the terminal for a phone | QR next to the URL |

### Rule 3 — Host install is one step

Target: **first memory written within five minutes of install.** The wizard
(`onboarding.html`) is four steps — owner account, access mode, first vault, first
client — and each one ends in a state the user can leave: skipping the client step
lands on Home with the same next action, not in a dead end.

| Don't | Do |
|---|---|
| Ask for storage layout, embedding model, index type | Defaults; every one of them changeable later (rule 4) |
| Present nine options for how to be reachable | Three access modes with "choose this if…", tunnel details deferred to the step that needs them |
| Finish onboarding with an empty screen | Finish with vault created, tool names visible, one obvious next action |

### Rule 4 — Defaults over decisions

Zero mandatory configuration. Every screen ships opinionated defaults with the
reasoning visible.

| Don't | Do |
|---|---|
| An empty "Vault name" with no guidance | Prefilled name and a purpose line, with the hint that agents read it |
| A checkbox list with no recommendation | Mark the recommendation (`Cloud` carries a *recommended* badge) and say why |
| Ask about git | Git on by default, with one line saying what it buys ("this is your undo") |
| Ask for the tool profile per client every time | Default profile per client kind, changeable in one segmented control |

### Rule 5 — Self-healing over error messages

An error the user must google is a bug. Findings come with a fix.

| Don't | Do |
|---|---|
| "Index out of sync (code 3)" | "Index is 42 notes behind on *personal* — someone edited the vault in Obsidian while the hub was updating. Search still works, it just does not know these notes yet." + **Reindex now** |
| A red badge that only counts problems | A tile that names the finding and carries the one-click fix (`home.html`, Doctor tile) |
| Silence while something is degraded | Say what still works. Degraded is not broken |
| A modal that blocks the app until acknowledged | An inline banner that survives navigation and disappears when fixed |

### Rule 6 — Beauty is a feature

The eye eats first. Concretely, for this system: Lume's light-as-material —
gradient surfaces, directional borders that catch light from above, glow
instead of flat tint at selection and focus — on a **cool light-grey canvas with
white cards floating on it**, in both light and dark (both flawless, neither an
afterthought); semantic colour that is always text or icon, never a fill; the
serif kept for prose; and a verdict sentence in plain language instead of a wall
of gauges.

Three restraints sit on top of all of this, and they are the difference between
"uses the Lume tokens" and "looks like Lume":

1. **Accent restraint.** Atelier appears only as selection edges, small dots and
   glows, the one primary button, and tiny highlights. **Count the
   accent-coloured elements per screen: three to six**, which is what the Lume
   reference application spends (`system.md` §1.1a). Everything else is neutral
   — including labels, counters, links at rest, avatars and the brand mark.
2. **Metadata is neutral and monospace.** Micro-labels, counters, ids,
   timestamps, revisions and metrics are Geist Mono in `text-tertiary` /
   `text-secondary`, uppercase with `.08em` tracking where they are labels
   (`system.md` §1.2a). Metadata never borrows the accent to look important.
3. **Signal**, Lume's separate, palette-independent, deliberately loud colour, is
   capped at one element across the *entire currently-visible view* and reserved
   for the single most important one-time commitment on that screen (`system.md`
   §1.1) — not a second accent, not a way to make an ordinary action feel more
   urgent than it is.
4. **The serif is the prose register, and nothing else.** visual-spec §2.7 says
   it in four words — *"Headings always stay structural"* — and version 2.1 broke
   it in five places while claiming to honour it: the brand mark's single glyph,
   every empty-state title, the note title (at weight 600, which the Don't table
   below already forbade), the wizard question, and the lead paragraph. Meanwhile
   the one genuinely prose-shaped surface in the product — a note's observations,
   sentences an agent wrote about the world — was set in sans. Two tests, both
   must pass: **more than one sentence** (a passage you read, not a line you
   scan), **and** the content rather than the frame around it. That leaves
   exactly three serif surfaces in these five screens: a note's observations, the
   home health briefing, and a proposal's rationale. Everything else is Geist.
   Full rule and the full never-list: `system.md` §1.2b.

| Don't | Do |
|---|---|
| A dashboard of dial charts | One sentence: "Everything is healthy." with the numbers underneath |
| Six differently-shaped cards per screen | One card grammar (head / body / foot) everywhere |
| Colour as decoration | Colour as state (`system.md` §1.1) |
| An accent-tinted pill on the selected nav item, with accent label and icon | A near-invisible left-anchored wash plus a **2px accent edge bar**; the label stays ink (`system.md` §2, Navigation). Data rows may use Lume's fuller two-stop halo (`.lume-selected`) |
| Accent-brown section labels, counters, links, avatars and brand marks | Uppercase mono micro-labels in `text-tertiary`; counts as mono tabular numerals; links ink-on-hairline-underline with the accent arriving on hover (`system.md` §1.2a) |
| Large solid accent buttons everywhere | 30px quiet buttons on the raised surface by default; **at most one** accent-gradient primary per screen, and zero is a legitimate answer |
| A warm accent wash over a card, hero panel or selected 640px option | Cool grey canvas, white cards; accent confined to a hairline edge, a glow ring or a small dot |
| Serif set at 600 with tight tracking used as chrome; a serif empty-state title, note title, wizard question, lead paragraph or brand glyph | Serif at 400 for a **passage**; sans for every title, head, label and single line; mono for metrics and metadata (restraint 4) |
| A filled, coloured pill for "healthy" / "needs attention" / "broken" | Text and icon colour only — a status is never a block fill (`system.md` §1.1) |
| Reaching for Signal because a button feels important | Signal only for the one genuine one-time commitment per view (`onboarding.html`'s "Create vault"); everything else, including a routine "Approve", stays accent |
| Dark mode as inverted light mode | Its own palette; shadows replaced by hairlines and Lume's directional borders |
| Fixed pixel widths | Fits 360 / 768 / 1280; primary answer never scrolls away |
| Tight boxes to fit more in | More padding inside cards, more gap between them; density comes from smaller metadata type, not smaller whitespace |

#### Beauty is not enough — the screen also has to be inviting

The four restraints above are how a screen stops being *wrong*. They are not how
it becomes *good*. Version 2.1 passed every one of them and the owner's verdict
was "correct, and clinical" — a server report rendered in a beautiful material.

So warmth is the second half of this rule, and because "be warmer" is not
something a reviewer can check, it is specified as **mechanisms**. The
restraints stay in force while you use them: warmth is made of copy, rhythm,
spacing, progress and at most one drawn mark. **It is never made of more
colour.** If a change to make a screen warmer added accent area, a second
primary, a tinted surface or an exclamation mark, it is the wrong change.

| Don't | Do |
|---|---|
| "Home" and a timestamp on the screen someone opens every morning | "Good afternoon, Christian." with the date and one continuity fact — "you were last here two hours ago" |
| A greeting with a personality ("Rise and shine", "Working late?") or an emoji | One steady, plain greeting; the warmth is being addressed, not being entertained |
| A queue that shows twelve rows and lets you pick | One proposal at full size, with the rest visible but quiet — a decision, not a list |
| "4 of 12" in 11px mono in the corner of a card head | A strip above the decision: the position in words ("the fourth of twelve"), the remainder in figures ("8 left"), one hairline cell per item, and an honest estimate — the end visible before you start |
| A percentage, or a bar that fills | A count that **shrinks**: what is left is the motivating number (`system.md` §1.6) |
| Shortcuts in a help modal, or discoverable only by hover | The keycap inside the button that owns the action, plus a legend row where the foot would otherwise be empty |
| Undo as a toast that disappears | Undo named next to the decisions, and named again in the sentence that describes the risk: "…and `Z` takes it back for ten seconds after that" |
| "Nothing to review." over an empty card | "The queue is clear." — one drawn mark, a prose passage, and a recap of what the curator did while nobody was watching, with mono figures |
| An empty screen that lists what is missing | An empty screen that says what the user already has: "you already have these — 23, all built in" |
| A completed flow that shows only configuration | One plain sentence of payoff among the config lines: "From now on it shares one memory with everything else on this list" |
| Delight applied everywhere (animated ticks, celebratory colour) | One drawn mark per screen, stroke-only, spent on the moment that earns it |

### Rule 7 — Trust through transparency

Every automatic action is visible and reversible.

| Don't | Do |
|---|---|
| "Memory updated" | "Claude Code wrote **Billing service** — 3 observations, 1 relation", with session id and **Undo** |
| Auto-capture running invisibly | An inbox count in the navigation and an activity feed entry per drop |
| A curator that rewrites notes silently | The two-tier rule made visible: adding is autonomous, changing existing knowledge becomes a proposal you approve (`review-queue.html`) |
| "Trust us, it worked" | Verification stated: "All 34 writes verified against their capture id before the inbox entries disappeared" |
| Hiding that a client connected from a new device | An activity entry with the device and a **Revoke** action |

Every mutation shows its provenance chips (who, which session, which capture) and,
where it changed the vault, its commit. Git is the undo, and the UI says so.

### Rule 8 — MCP Apps are a standing design question

For every user-facing feature the review asks: is an in-client app surface (§5.7)
the right way to deliver this, or at least a sensible addition? The answer may be
"no" — and must be for security-sensitive administration — but the question is
mandatory. §3 answers it per screen; §4 collects the verdicts.

## 2. Reading the mockups

Each file carries a thin dashed bar at the top with the states it renders and a
theme cycler. That bar is scaffolding — it is not part of the product. Everything
below it is: light and dark follow the OS, and the layouts hold at 360, 768 and
1280px.

## 3. Per-screen rules

### 3.1 Home — `mockups/home.html`

**Primary question:** is everything healthy, and what happened while I was away?

Above the fold, in this order: the greeting, the verdict sentence, the four state
tiles (vaults, inbox, clients, doctor), then the activity feed on the left and,
in the rail, the **tool surface** followed by the connected clients. Anything
that is not evidence for the verdict, a next action, or an answer to "what can my
agents actually do" belongs on another screen.

**The tool surface is a required element, not a nice-to-have.** Half of what
palaia *is* lives in MASTERPLAN P2 (one endpoint, configure once, use
everywhere) and P3 (the marketplace), and until version 2.2 the home screen
showed neither — a reviewer could read the whole dashboard and conclude palaia
was a memory tool. The rail therefore leads with a "tools your agents can use"
card: palaia's built-ins (memory, stash, messenger) and every added server in
one uniform list, because an agent cannot tell which of them palaia wrote and
which it merely carries, and that indistinguishability *is* the gateway's claim.
It is the rail's **first** card, above clients, since capability precedes the
list of who consumes it.

| Don't | Do |
|---|---|
| A home screen that never mentions the tools, so palaia reads as a memory tool | The rail's first card: sources with tiny glyphs and mono counts, "37 · 3 built in, 3 added" |
| Brand logos for third-party servers | Neutral functional glyphs on the standard raised chip — palaia does not host other people's marketing |
| A tinted "upgrade" panel for the marketplace | One quiet `btn--sm` in the card foot, and a mono meta line: "42 more available" |
| Hiding a server that is installed but broken | `tool--off`: the name goes quiet and the count is replaced by the reason as **text** ("no key") |
| An empty first-run screen listing what is missing | "you already have these — 23, all built in", with what each built-in is for |

| Don't | Do |
|---|---|
| A grid of every entity the hub knows | Four tiles that answer four questions, each with one action when it needs one |
| A number without a consequence ("Inbox 12") | "12 waiting, oldest capture 3 days old" + **Review now** |
| An activity log of internal events | A feed of things *actors* did, in sentences, with undo |
| A refresh button | The live dot: the feed is event-driven (SPEC-109 SSE) |
| Charts for their own sake | One sparkline of memories written, because trend answers "is it being used?" — neutral bars, with only the latest column accent-tinted |
| A chip-salad status line under the verdict | A **briefing**: a mono micro-label, a serif sentence, a hairline rule, then three bulleted facts with mono numbers — the register of the "prepared briefing" container in the Lume reference application |

**First run** (`first run` state) is a designed screen, not a fallback: the verdict
becomes "Your hub is up. Nothing to remember yet.", the tiles show honest zeros
with teaching subtitles, a three-step checklist carries the next action, and the
import card offers palaia v2 / basic-memory / Obsidian — the migration path from
MASTERPLAN §11 and research/basic-memory.md §7, offered before it is asked for.

**Rule 8:** yes, as **Hub status** (§5.7, phase 2) — health, clients, vault
overview, doctor findings with one-click fixes make a good welcome panel inside a
client. The dashboard stays the fuller surface.

### 3.2 Onboarding wizard — `mockups/onboarding.html`

**Primary question:** what do I have to decide before palaia is useful?

Four steps, a persistent rail showing progress, and one reassurance that never
moves: *nothing here is a one-way door.*

| Don't | Do |
|---|---|
| Ask for a network topology | Ask what the user *uses*, then derive the mode (§5.5) |
| "Enable authentication?" as a checkbox | Auth is a property of the mode; the mode card says "auth required" and the hub enforces it fail-closed |
| Let the user pick a mode that cannot serve their clients | State it in the mode card *and* in the info banner: vendor-cloud clients cannot reach a tailnet-only hub |
| Bury the vault purpose line as an optional description | Make it a step with the hint that agents read this line to pick the right memory (§5.2) |
| Show generated tool names only after the fact | Preview them live (`work_memory_search`, …) and say they are renamable |
| Require the client step to finish | **Skip for now** — Home repeats the same next action |

**Rule 8:** no. First-run setup decides the security posture, and the wizard needs
the browser's full context. A chat-embedded frame is the wrong place for it (§5.7,
"deliberately not apps").

### 3.3 Connect a client — `mockups/connect-client.html`

**Primary question:** how do I get *this* client talking to palaia, and did it work?

Left: every client from the §6 matrix with its live status. Right: the guided flow
for the selected one — profile choice, the one thing to paste, and the watch for
the first tool call.

| Don't | Do |
|---|---|
| One generic "MCP endpoint" page | Per-client flows; the user never needs to know the quirks (§6) |
| Silently offer a flow that cannot work | The `blocked by mode` state: name the reason, then offer the two honest ways forward |
| Let a client see all 37 tools by default | A profile in the URL path (`/mcp/coding`), stated as "this client will see 12 tools, not 37" (§5.2) |
| Present the token as a secret to copy around | The token is inside the copied command; rotation and revocation are buttons |
| "Connected ✓" and nothing else | Which profile, which scopes, first call, last seen, and what it did with your memory |
| Hide plan gating until it fails | ChatGPT's write gating and the MCPB local-only constraint stated inline |

**Empty / first run:** a teaching empty state — what a "client" even is, and two
buttons: the most likely client, and "I use something else".

**Rule 8:** partly. A connect *panel* inside a client that can already reach palaia
is useful for adding a second surface (phone), but the first connection is a
chicken-and-egg problem and mode changes stay dashboard-only.

### 3.4 Memory explorer — `mockups/memory-explorer.html`

**Primary question:** what does palaia know, and where did it come from?

Three panes at 1280: the note tree, the note, and the context (frontmatter,
provenance, local graph, git history). The context pane folds away at 1024 and the
panes stack at 768.

| Don't | Do |
|---|---|
| A global graph hairball | A local graph, one hop, typed edges, expandable on request |
| Render the note as a database record | Render it as the Markdown it is; observations keep their categories, wiki-links stay links |
| Hide forward references | Show links to notes that do not exist yet as dashed — they are a feature (§5.1) |
| Put volatile values in titles | Version, status and dates are observation fields; the note title stays stable, and the UI shows the field ("2026.5.7 — the version lives in a field, so links never rot") |
| Copy a shared value into every note | Render the referenced block with its source ("live value from Platform SLAs · sla-core") |
| Show only the current text | Show provenance and the last commits — every change is attributable and revertible |
| Ask the user to choose a folder structure first | "Structure appears as knowledge arrives" — schema-as-notes, warn-first (research/basic-memory.md §7) |

**Empty vault** is a first-class screen: three ways in (let an agent write it,
import, write it yourself), and the promise that whatever lands stays a file on
disk.

**Rule 8:** yes, as **Recall explorer** (§5.7, phase 2) — search results as a
browsable panel where only the picked notes enter the context window. That is
selective context as a UI property, and it is worth more inside the chat than in
the dashboard.

### 3.5 Review queue — `mockups/review-queue.html`

**Primary question:** what does the curator want to change, and do I agree?

One proposal at a time, with the diff, the reason, the provenance and the actions
on one screen. The queue rail shows what follows; the curator card shows that the
job is doing its work honestly.

| Don't | Do |
|---|---|
| A queue of everything the curator did | Only proposals: rewrites, merges, retirements. Adding is autonomous (§5.1 two-tier rule) — say so on the screen |
| "Apply changes?" with no diff | Before/after, additions and removals coloured, file name shown |
| Hide where the knowledge came from | Provenance chips: agent, inbox entry, capture id, and the verbatim capture on request |
| Imply a model will rewrite the note on approval | "Approving runs a deterministic file operation — no model rewrites your note" |
| Approve-only | Approve, edit-then-approve, reject, skip — with keyboard shortcuts shown next to them |
| The queue position as 11px mono in a card head | A focus strip above the decision: "The fourth of twelve. Eight more after this one." + a `qmeter` + "about 4 minutes at this pace" |
| Shortcuts discoverable only by trying them | Keycaps inside the four action buttons, plus a `keys` legend row: next, previous, **undo the last decision**, every shortcut |
| Undo implied by "it's all in git" | `Z` named in the legend *and* in the sentence under the buttons |
| Make an empty queue feel like a failure | "The queue is clear." — the drawn mark, a prose passage, and the since-Monday recap (128 added without asking, 9 approved, 2 rejected, all revertible) |
| "An empty queue is the normal state" as a bare fact | "A clear queue is the normal state, **not a lucky day**" |

**Rule 8:** yes — this is *the* app (§5.7 calls it the killer use case). The
`in-client app` state in the mockup is the visual reference for it: the same
tokens and components in one column, full-width primary action, stacked diff, and
the selective-context note ("only what you approve enters the conversation").
Approving curation from the phone beats editing frontmatter in Obsidian, which is
exactly the workflow the mcp-hub prototype lacked.

## 4. The rule-8 answers, collected

| Surface | In-client app? | Reasoning |
|---|---|---|
| Review queue | **Yes — first** | Multi-step decisions with actions; mobile is where this workflow actually happens (§5.7) |
| Recall / memory explorer | **Yes** | Explore-then-select; only picked notes enter context |
| Hub status (home) | **Yes** | Live monitoring; a good first-tool-call welcome panel |
| Inbox peek | Yes, later | Cheap trust check on auto-capture |
| Connect a client | Partly | Useful for adding another surface; not for the first connection |
| Onboarding wizard | **No** | Decides the security posture; needs the browser |
| Access mode / exposure, token revocation | **No** | Changes the attack surface — dashboard only, per §5.7 |

Progressive enhancement is the rule everywhere: a host without the apps extension
gets the plain-text tool result, and every app has a dashboard equivalent (rule 1).

## 5. Review checklist

Use this on any PR that adds or changes UI:

- [ ] The screen's primary question is answered at 1280×800 without scrolling.
- [ ] **No jargon in the surface** (§0.1) — read every label, heading, button,
      badge, status line and option name aloud. No protocol, standard, acronym
      or transport word among them; each one that was needed is demoted to hint
      text or a `title`.
- [ ] **Every client is named exactly** (§0.2) — no bare "Claude Code" anywhere;
      the client list's row count agrees with its "N connected".
- [ ] **The serif sets only passages** (rule 6, restraint 4) — grep the diff for
      `font-serif`: every hit is a note's observations, the home briefing, or a
      rationale. No serif title, head, label, lead, button or brand glyph, and
      no serif above weight 400 outside emphasis inside a passage.
- [ ] **Warmth mechanisms present where they apply** (rule 6, second half) — a
      daily screen greets by name; a queue shows one item with visible progress
      and its shortcuts on screen; undo is named at the moment of risk; the
      done-state says the work is finished and recaps what happened; nothing
      warm was achieved by adding colour.
- [ ] **Accent budget: count the accent-coloured elements — three to six**
      (`system.md` §1.1a). At most one `btn--primary`; no accent labels,
      counters, avatars, brand marks or resting link colours.
- [ ] **Metadata is neutral mono** — micro-labels, counters, timestamps, ids and
      metrics (`system.md` §1.2a). Card chrome titles are quiet and lowercase;
      only a head that names a *subject* gets `card__subject`.
- [ ] **Buttons are quiet** — 30px raised-surface secondary by default; the
      screen does not read as a row of coloured slabs.
- [ ] The selected item is a wash plus a 2px accent edge with ink text, not a
      tinted pill.
- [ ] Light and dark both look deliberate; no colour outside the tokens.
- [ ] Responsive at 360 / 768 / 1280; no horizontal page scroll; wide content
      scrolls inside its own container.
- [ ] Empty and first-run states exist and name the next action.
- [ ] No flow requires editing a file, restarting a service, or using the CLI.
- [ ] Every automatic action is visible, attributed and reversible.
- [ ] Every failure state names a fix or names who can fix it.
- [ ] Copy follows `system.md` §3 (verbs on buttons, no exclamation marks,
      inconvenient truths stated).
- [ ] Keyboard: focus visible, shortcuts shown where they exist, no mouse-only path.
- [ ] Rule 8 answered in the PR description: app surface — yes, no, or later, and why.
