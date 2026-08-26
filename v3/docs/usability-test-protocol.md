# Usability test protocol: install → first shared memory, unaided

**Owner action** (MASTERPLAN §12's Phase-5 exit criterion: *"a non-developer
completes install → first shared memory unaided"*). Everything scriptable
about this criterion is covered by `v3/server/tests/e2e/
test_spec506_phase5_gate.py`; this page is the part that needs a real
person — hand it to them as-is, or read it aloud while they drive. Budget
about 20 minutes.

Every step below points at a page that exists in the shipped docs site
today (`v3/site/docs`) — none of it describes UI that has not landed. If a
step's instructions and the live site ever disagree, the site is right;
file that as a finding (see §5) rather than trusting this page.

## 1. Before the session (observer prep, not shown to the tester)

- Pick someone who has never used palaia and does not read this repository
  — "non-developer" for this test means: comfortable installing an app and
  typing in a terminal if told exactly what to type, but with no prior
  knowledge of palaia, MCP, or which of the tasks below is expected to be
  hard.
- Have two AI tools ready on their machine that they already use day to
  day — e.g. Claude Code CLI and Codex, or any two from
  [Connect your AI](/connect/)'s "Works right now" list. They do not need
  to be the same two every session; write down which two were used.
- Sit where you can see their screen and hear them think aloud, but say
  nothing unless they ask — see §4.
- Have `v3/docs/client-matrix-results.md` and this repository's GitHub
  Issues open, ready to write down what happens.

## 2. The tasks (read aloud, or hand over verbatim)

> You're going to set up a piece of software called palaia and get two AI
> tools sharing one memory. Do exactly what the instructions in front of
> you say, in the order they say it. Talk out loud about what you're
> looking at and what you expect to happen next — if something confuses
> you, say so instead of guessing; that's exactly the thing this test is
> for.

**Task 1 — Install it.** Open [Install it](/install/) and follow it from
the top: run the one command, open the address it prints in your browser,
and go through the first-run setup that appears (owner account, access
mode, first vault — same order the page walks you through).

**Task 2 — Connect your AI.** From the page the wizard lands you on (or
[Connect your AI](/connect/) if you navigate away), pick one of your two
AI tools and connect it, following that tool's own connect page exactly
(e.g. [Claude Code CLI](/connect/clients/claude-code-cli/)).

**Task 3 — Save and retrieve one memory.** Ask your connected AI tool to
remember something specific and made-up — a fake project name and one
fact about it works well (the same shape [Your first shared memory](
/first-shared-memory/) demonstrates). Then, in the same tool, ask it to
recall that same fact, to confirm it actually saved.

**Task 4 — Connect a second AI and confirm it already knows.** Connect
your other AI tool the same way as Task 2. Without telling it anything
about what you saved in Task 3, ask it the same question you asked the
first tool. It should answer correctly.

The session ends the moment Task 4's answer comes back correct — or the
moment the tester gives up on a task and cannot continue without being
told what to do.

## 3. What the observer records

For each task: pass / stuck / gave up, elapsed time, and — this is the
part that matters most — the exact moment and exact words of any
confusion, wrong click, or "I don't know what this means." A task the
tester finishes but describes as confusing afterward still counts as a
usability finding, even though it technically passed.

| Task | Pass / stuck / gave up | Time | What they said/did when confused |
|---|---|---|---|
| 1. Install | | | |
| 2. Connect AI #1 | | | |
| 3. Save + retrieve | | | |
| 4. Connect AI #2, confirm | | | |

Also record: total wall-clock time from "start the timer" (the moment
they open [Install it](/install/)) to Task 4's correct answer — this is
the human-driven counterpart to MASTERPLAN §13's <5-minute *machine*-time
target, and it is expected to run longer, since a real person reads,
thinks, and occasionally mis-clicks in ways a script does not.

## 4. What counts as "unaided"

**Unaided** means the tester used only what is already on the page or in
the product's own UI at the moment they needed it — nothing the observer
said, typed, or pointed at, and nothing outside the docs site (no asking
a search engine, no asking an AI assistant "how do I do this," no asking
the observer "what does this mean").

Concretely:

- The observer may start the session, hand over Task 1's instructions,
  and start the clock. From that point, the observer speaks only to
  acknowledge what they are seeing ("okay," "go on") — never to explain,
  hint, correct, or answer a question about what to do next.
- If the tester asks a direct question ("what do I click?"), the honest
  answer is silence, followed by a note in §3: *this is the moment
  unaided completion failed*, not a prompt to improvise a workaround.
  Record what would have unblocked them, then let them try to find it
  themselves for up to two more minutes before ending that task as "gave
  up" and moving on (later tasks may still be attempted independently).
- A task that only worked because the tester's general tech background
  filled a gap the product should have (e.g., they already knew what a
  terminal is, or guessed correctly that "connect" meant something
  specific) still counts as unaided — the bar is *no palaia-specific help
  from a person*, not zero prior computing experience.
- [Troubleshooting & FAQ](/troubleshooting/) is part of the product, not
  outside help — the tester may read it if they think to, and doing so
  still counts as unaided.

## 5. Where findings get filed

- A concrete product bug or confusing step (wrong instructions, a button
  that does nothing, an error message that doesn't say what to do) — file
  a GitHub issue on `byte5ai/palaia`, same shape as every other gate-
  evidence quirk this project has filed (see the SPEC-506 PR's issue list
  for examples): what the tester did, what they expected, what actually
  happened, and which task/step it was.
- A timing or pass/fail result — add it to
  `v3/docs/client-matrix-results.md`'s usability section, dated, with the
  filled-in table from §3 and the total time from §3's last paragraph.
- A design or copy question with no single obvious fix (not a bug, but
  "this wording confused two testers in a row") — note it in the same
  place as the timing result, for the next docs/UX pass to triage rather
  than turning into an issue on its own.

## 6. Observer-only notes (do not read to the tester)

These are known, already-documented gaps this protocol was written
against — expected, not a sign the session is going wrong:

- The wizard's "Owner account" and "Access mode" steps (Task 1) are real,
  clickable UI, but only "First vault" and "First client" are wired to the
  server today (`v3/web/src/routes/onboarding/Onboarding.tsx`'s own
  comment says so). If the tester's browser session resets mid-wizard,
  they may need to redo the first two steps' clicks — that is expected,
  not evidence the install failed.
- Two different AI tools authenticate differently depending on which
  you picked for Tasks 2/4 (some do a browser sign-in automatically, some
  use a pasted address with no separate sign-in step) — both are correct;
  `v3/docs/client-matrix-results.md` names which is which per tool.
