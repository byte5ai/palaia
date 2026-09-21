---
title: Edit in Obsidian
description: Your memory is a folder of Markdown files in a git repo — so you can open it in Obsidian and edit alongside your AI. Here's the git setup for a hub on your network, and the local shortcut.
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
- **The power path — Obsidian + git.** Open your memory as an Obsidian library
  and let git carry changes between your machine and the hub. This page is
  about that path.

## The normal setup: hub on your network, Obsidian on your machine

palaia earns its keep as an always-on hub — a shared memory that every AI tool
and every device reaches at one endpoint, the way Home Assistant sits on your
network. So it almost always runs on a **separate box** (a NAS, a homelab
server, a Raspberry Pi), not on the laptop you happen to be typing on. Obsidian
runs on that laptop.

Obsidian only opens **local** folders, and palaia deliberately does **not**
expose that memory as a network drive — that would work against its local-first,
files-are-the-source-of-truth design. The bridge is **git**, which is exactly
why palaia makes every memory a real git repository with attributed
auto-commits.

The shape of the setup:

1. **Get the memory repo onto your machine.** Clone the memory's git repository
   from the hub to a folder on your laptop, over whatever git access you have
   to the host (for a box you control, that is typically SSH). A turnkey
   per-memory git remote served by the hub itself is on the roadmap
   ([issue #438](https://github.com/byte5ai/palaia/issues/438)); until then you
   clone over your own access to the host.
2. **Open the clone in Obsidian** — `Open folder as vault` on the
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

## The shortcut: palaia on the same machine as Obsidian

Running palaia on the very machine you edit from is uncommon — a hub that only
serves the one laptop it lives on gives up most of what palaia is for (always
on, reachable from your phone and your other tools). But if that is your setup,
skip git entirely: the memory is already a local folder.

1. In palaia's dashboard, open the memory and note the **folder path** it shows
   (on the usual setups, a `vaults/<name>` directory inside the hub's data
   directory).
2. In Obsidian: `Open folder as vault` → choose that folder.

Edit freely — palaia watches the folder and re-indexes a changed note within
moments, and still auto-commits every change to git in the background, so you
keep the same browsable history.

## Good to know

- **Editor state stays out of your history.** palaia's memory `.gitignore`
  ignores Obsidian's own `.obsidian/` workspace files (and `.trash/`), so
  Obsidian's constantly-rewritten config never becomes a commit in your memory
  history and is never mistaken for a note you wrote.
- **It is not a second backup.** Having a clone on your laptop is convenient,
  not protective — a real backup is a separate, restorable copy. See
  [Back up & restore](/backup-restore/).
- **Formatting.** palaia and Obsidian share the same Markdown dialect
  (`[[wikilinks]]`, tags). Obsidian-specific extras render fine in Obsidian; palaia
  reads the plain Markdown underneath.
