# palaia-addon-sdk

Build, check and submit an add-on for the palaia marketplace. If you can
write a small MCP server, this gets you from nothing to a listing a
stranger can install with one click.

This package is small on purpose: stdlib plus [pydantic](https://docs.pydantic.dev/).
It has no dependency on the palaia hub itself — install it on its own,
anywhere.

## Install

```bash
uv tool install palaia-addon-sdk   # once published
# or, from a checkout of this repo:
uv run --project v3/sdk palaia-addon --help
```

## The five-minute path

### 1. `init` — scaffold

```bash
palaia-addon init my-fetch-addon --maintainer yourname
cd my-fetch-addon
```

This writes three files:

- `manifest.json` — what your add-on is called, what it does in one
  sentence, what it needs from whoever installs it, and where the
  finished version will be fetched from.
- `server.py` — a working example MCP server (a "say hello" tool). Run it
  with `uv run server.py` — nothing else to install first.
- `README.md` — a starting point for your own add-on's docs.

### 2. Implement

Replace the example tool in `server.py` with your own. Nothing about the
manifest or the SDK cares what your server is written in or how it talks
to the world, as long as it's an MCP server reachable over stdio for local
testing (containers ship differently — see step 4).

Fill in `manifest.json`'s `config_schema` with whatever settings your
add-on needs from the person installing it (an API key, a folder to read
from, a toggle). Four kinds are supported, and that's all the marketplace
form renderer understands:

| `type` | Rendered as | Notes |
|---|---|---|
| `string` | a text field | add `"enum": [...]` for a dropdown instead of free text |
| `number` | a number field | |
| `boolean` | a switch | |
| `secret` | a password-style field | value goes straight to the secret store — the marketplace never echoes it back, ever |

Every `title` you write is shown to whoever installs your add-on — keep
it in plain language (see "jargon" below).

### 3. `validate`

```bash
palaia-addon validate .
```

Checks your `manifest.json` against the shape the marketplace actually
uses:

- `kind` is one of `remote`, `container`, `mcpb`, `skill`, `plugin`
- every `permissions` entry is one of `network`, `filesystem`,
  `memory-scope:read`, `memory-scope:write`
- every `config_schema` field's `type` is one of the four kinds above
- no in-house jargon in any text a marketplace user would actually read
  (the `name`, the `one_liner`, and every `config_schema` field `title`) —
  the same blocklist the palaia skill format lint uses, so an add-on and
  a skill are held to one bar

Every failure names the exact field and the fix — there's nothing to look
up.

Two of the permissions are enforced, not just displayed, when a hub runs a
`container` add-on:

| Permission declared | What the hub does |
|---|---|
| `network` missing | The container gets no network at all (`--network none`). |
| `filesystem` missing | The container's root filesystem is read-only, with `/tmp` as scratch space; the folders declared as `"format": "path"` mounts stay writable. |
| always | Every capability is dropped, `no-new-privileges` is set, and a memory and a process ceiling apply. |

So declare `network` if your add-on talks to anything, and `filesystem` if it
writes anywhere other than `/tmp` and its declared mounts — an add-on that
needs more than it declared does not start, rather than quietly getting it.

### 4. `test`

```bash
palaia-addon test .
```

Runs your `server.py` (`uv run server.py`) and drives it through a real,
minimal MCP client: `initialize`, then `tools/list` — exactly what a
marketplace user's agent does the moment they connect. Prints what that
user would see:

```
Fetch — Fetch and convert web pages to text for an agent to read.
maintainer: yourname
kind: container
permissions: network
config form fields:
  - User agent string [string]
live check: Fetch answered tools/list with 1 tool(s): fetch_page
```

If `test` runs clean, your add-on behaves the way the marketplace expects
it to.

### 5. Submit

See [`v3/docs/addon-submission.md`](../docs/addon-submission.md) in the
palaia repository for how a validated manifest becomes a listing in the
curated index — what review happens, what "verified" means, and what it
doesn't.

## Command reference

```
palaia-addon init <dir> --maintainer NAME [--id ID] [--name NAME] [--one-liner TEXT]
palaia-addon validate [<dir-or-manifest.json>]      # default: .
palaia-addon test [<dir>] [--timeout SECONDS]       # default: .
```

## Why `kind: container` by default

A finished palaia add-on is a small containerized MCP server (the
marketplace's most common shape — see the palaia repo's design docs).
`init` scaffolds your manifest that way, with a placeholder image name to
fill in once you've built and pushed one. `palaia-addon test` never needs
that image: it runs your `server.py` directly over stdio, so your local
loop stays fast (`init` → edit → `test`, no container build in between).
If your add-on is actually a `remote` (plain HTTPS) server instead, change
`kind` and `source` in `manifest.json` accordingly — everything else in
this guide still applies.
