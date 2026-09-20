---
title: Edit in Obsidian
description: Your memory is a folder of Markdown files in a git repo — so you can open it in Obsidian and edit alongside your AI. Here's the local setup and the remote (git) setup.
---

palaia stores every memory as plain Markdown files in a git repository — not
inside a database only palaia can read. That is what lets you open your memory
in [Obsidian](https://obsidian.md) (or any Markdown editor) and edit the same
notes your AI tools do. Nothing is exported or copied: you are editing the
real files.

There are two ways to work with your memory by hand, and palaia is built for
both:

- **The default path — the dashboard.** The explorer in palaia's web UI
  (`http://palaia.local`) reads and shows your notes in the browser, wherever
  the hub runs. Nothing to install. This is covered on [Your memory](/memory/).
- **The power path — Obsidian + git.** Open the vault as an Obsidian library
  and let git carry changes between your machine and the hub. This page is
  about that path.

Which setup you use depends on **where palaia runs relative to Obsidian**.

## If palaia runs on the same machine as Obsidian

This is the simple case. The vault is already a local folder, so just point
Obsidian at it:

1. In palaia's dashboard, open the memory and note the **vault path** it shows
   (on the usual setups, a `vaults/<name>` directory inside the hub's data
   directory).
2. In Obsidian: **Open folder as vault** → choose that folder.

That's it. Edit freely — palaia watches the folder and re-indexes a changed
note within moments, so what you write in Obsidian is immediately searchable
by your AI tools. Wikilinks light up in Obsidian's graph; palaia auto-commits
every change to git in the background, so you keep a full, browsable history.

## If palaia runs on another machine (NAS, homelab server, Raspberry Pi)

This is the common case: the hub is an appliance on your network, and Obsidian
is on your laptop. Obsidian only opens **local** folders, and palaia
deliberately does **not** expose the vault as a network drive — that would work
against its local-first, files-are-the-source-of-truth design. The bridge is
**git**, which is why palaia makes every vault a real git repository with
attributed auto-commits.

The shape of the setup:

1. **Get the vault repo onto your machine.** Clone the vault's git repository
   from the hub to a folder on your laptop, over whatever git access you have
   to the host (for a box you control, that is typically SSH). A turnkey
   per-vault git remote served by the hub itself is on the roadmap
   ([issue #438](https://github.com/byte5ai/palaia/issues/438)); until then you
   clone over your own access to the host.
2. **Open the clone as an Obsidian vault** — *Open folder as vault* on the
   cloned folder.
3. **Install the [Obsidian Git](https://github.com/Vinzent03/obsidian-git)
   community plugin** and point it at the clone. Set it to pull on startup and
   push (or commit-and-push on an interval) so your edits travel back to the
   hub and the hub's own auto-commits come down to you.

From then on it is ordinary git: you edit in Obsidian, the plugin commits and
pushes to the hub, palaia's file watcher and git layer pick the change up and
re-index it. palaia's background auto-commits flow the other way on your next
pull. This is what "Obsidian-git compatible" means — git is the sync channel,
not a live network mount.

## Good to know

- **Editor state stays out of your history.** palaia's vault `.gitignore`
  ignores Obsidian's own `.obsidian/` workspace files (and `.trash/`), so
  Obsidian's constantly-rewritten config never becomes a commit in your memory
  history and is never mistaken for a note you wrote.
- **It is not a second backup.** Having a clone on your laptop is convenient,
  not protective — a real backup is a separate, restorable copy. See
  [Back up & restore](/backup-restore/).
- **Formatting.** palaia and Obsidian share the same Markdown dialect
  (wikilinks, tags). Obsidian-specific extras render fine in Obsidian; palaia
  reads the plain Markdown underneath.
