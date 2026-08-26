# Moving from palaia v2 to v3

> User-facing companion to [`import-mappings.md`](import-mappings.md), the
> field-by-field mapping the importer implements. This page answers "should
> I move, and what happens when I do" in plain language; the other page is
> the reference for exactly how each field lands.

## The short version

palaia v3 is a full rewrite: one self-hosted hub your AI tools all connect
to, instead of a Python package each machine installs separately. v2 still
works and still gets hotfixes — nobody has to move today. When you're ready,
your existing knowledge comes with you: one command reads your old store and
writes every entry into a new v3 memory library, unchanged, alongside its
full history of where it came from.

v2's own [README](../../README.md) has the current support policy and the
link back to this page.

## What carries over

Everything you saved. The importer reads your v2 store (the `hot/`, `warm/`,
`cold/` folders — whichever database it used to index them doesn't matter,
the entries themselves live in those folders) and writes each one into a
v3 memory library as its own file, with its title, tags, body, and where it
came from all preserved. Run it with:

```bash
palaia-hub import v2 /path/to/.palaia --vault /path/to/new/vault --vault-name personal
```

Add `--dry-run --json` first to get a report of exactly what would be
created — and what can't be, with a reason for each — before anything is
written. Drop `--dry-run` to actually write. The full field-by-field mapping
(what a v2 "memory" becomes, how tiers and scopes translate, what happens to
an unrecognized entry type) is in
[`import-mappings.md`](import-mappings.md#palaia-v2--v3).

Running the same command again is safe and does nothing new — every entry
already imported is recognized and skipped, so re-running after saving a few
more things in v2 only brings over what's new.

## What changes

- **One hub, not one install per machine.** v2 was a Python package each
  project or machine installed on its own. v3 is a single server you run
  once (self-hosted, on your own hardware); every AI tool connects to it
  over the network instead of loading a local package.
- **Every tool reconnects on its own.** There's no single "migrate my
  setup" switch — each AI tool (Claude Desktop, Claude Code, Codex, and the
  rest) gets pointed at the new hub individually, the same way you first
  connected it to v2. The hub's own setup pages walk through each one by
  name.
- **New credentials.** v2's access, where it had any, doesn't carry over.
  Each tool gets its own new sign-in to the hub, so one tool losing its
  credential never affects another.
- **The browser view moved and grew up.** v2's optional, localhost-only
  browser explorer is replaced by the hub's always-on web dashboard —
  reachable from any device on your network, not just the machine it runs
  on, and it is where sign-in, the memory library, and every tool's
  connection status now live.

## What v3 doesn't have yet

This list is built by checking off every command in v2's own
[CLI reference](../../docs/cli-reference.md) against what v3 ships today —
not written from memory. "Carried" means the same capability exists, though
often reached a different way (a screen in the dashboard, or a tool your AI
calls, rather than a line you type). "Missing" means it plain doesn't exist
yet; don't move a workflow that depends on one of these until it lands.

| v2 command | Status in v3 | Notes |
|---|---|---|
| `palaia write`, `query`, `get`, `list`, `edit` | Carried, changed | Your AI tools save and search through their own built-in connection to the hub; the dashboard's memory library also lists, opens, and edits entries by hand. No standalone command-line equivalent. |
| `palaia init`, `setup claude-code`, `setup --multi-agent` | Carried, changed | The hub's first-run setup screen and per-tool connect pages replace these; nothing to run per machine. |
| `palaia ui` | Carried, changed | Always-on web dashboard, reachable from any device on the network — not a localhost-only, opt-in extra. |
| `palaia status`, `upgrade` | Carried, changed | Health lives in the dashboard; updates are one click from there instead of a command. |
| `palaia curate analyze`, `curate apply` | Carried | The curator runs the same two-pass review, now on a schedule or on demand via `palaia-hub curator run` / `curator apply`. |
| `palaia project create/list/show/write/query/set-scope/set-owner/delete` | Carried, changed | Multiple memory libraries and their access scopes are a dashboard/config concern now, not a `project` subcommand. |
| `palaia memo send/broadcast/inbox/ack/gc` | Carried, changed | Replaced by the built-in agent-to-agent messenger (structured handoffs between sessions), not a like-for-like command. |
| `palaia config list/get/set/set-chain/set-alias/get-aliases/remove-alias` | Carried, changed | One `config.yaml` plus dashboard settings screens; no `set-chain`/alias equivalent — v3's embedding setup is one choice, not a fallback chain. |
| `palaia warmup`, `embed-server` | Carried, changed | Indexing and embeddings run inside the hub process; there's no separate server to start or index to pre-warm by hand. |
| `palaia mcp-server --read-only` | Carried, changed | Read-only access is a scope on a tool's own credential, granted when it's connected — not a server flag. |
| `palaia doctor` | **Missing** | No guided diagnose-and-fix pass yet. The dashboard surfaces connection and health problems as they occur, but nothing walks you through fixing them. |
| `palaia prune`, `gc` (knowledge cleanup, decay-based) | **Missing** | v3 records the same tiering data on import (`import.tier`, `import.decay_seed`) but nothing yet recomputes or prunes by it — see the honest scope note in [`import-mappings.md`](import-mappings.md#cold-embed-as-a-background-job-honest-scope-note). |
| `palaia priorities` (injection budget control) | **Missing** | No equivalent yet. |
| `palaia ingest <source>` (document indexing) | **Missing** | No bulk "index this folder of documents" command yet. |
| `palaia sync export/import` (git-based exchange) | Carried, changed | Every v3 memory library already keeps its own version history as it's written — nothing separate to export or import. |
| `palaia package export/import/info` (portable bundles) | **Missing** | No portable-bundle format yet; a memory library is moved by moving/copying its files directly. |
| `palaia process list/run` | **Missing** | No equivalent yet. |
| `palaia lock/unlock` | **Missing** | No equivalent yet — nothing in v3 currently needs a project-level lock. |
| `palaia instance set/get/clear` (session identity) | Carried, changed | Each tool's own hub credential is its identity; no separate instance concept. |
| `palaia recover` | **Missing** | No equivalent yet; the version history every memory library keeps is the closest safety net today. |
| `palaia detect` (provider detection) | **Missing** | Providers are configured explicitly rather than auto-detected. |
| `palaia skill` | Carried, changed | Each AI tool gets its own connect-and-teach package from the hub's setup pages, in that tool's own format — not one printed file. |

If something you rely on is marked **Missing** above, stay on v2 for that
workflow — it keeps getting hotfixes on `v2-maintenance` — and re-check this
page later; it's kept current as v3 gains ground.

## Rolling back

The importer only ever *reads* your v2 store. It never opens it for writing,
never deletes an entry, and never touches its database — nothing about your
v2 install changes by running it, whether you `--dry-run` or actually apply.
If a v3 import doesn't look right, delete the `imported/v2/` folder it wrote
inside your new memory library (or just discard the whole new library) and
try again — v2 is exactly as it was before you started, still fully
installed and fully usable, and importing again later picks up right where
it left off.

## Support timeline

<!-- DECISION NEEDED (owner): fill in real dates before this page ships
     publicly. The structure below is fixed by this page's own plan; the dates are not.
     Until filled in, treat every bracketed line as a placeholder, not a
     commitment. -->

- v2 is in **maintenance mode now**: no new features, hotfixes only
  (security, data loss, a broken release), landing on `v2-maintenance`.
- **[DECISION: date]** — target date by which v3 reaches feature parity
  with the items marked Missing above that the owner considers
  release-blocking.
- **[DECISION: date]** — earliest date v2 hotfixes are expected to stop.
  Not before the parity date above, and not without advance notice on the
  v2 README and in this document.
- **[DECISION: policy]** — how much advance notice a support-ending change
  gets (e.g., "at least N months," announced in the v2 README banner and
  the project's release notes).

No entry in this list is enforced by anything in this repository; it is
prose the owner is expected to fill in and keep current, not a promise the
software makes on its own.
