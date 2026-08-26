---
title: For developers
description: The file format, the connection protocol, and the SDK for building your own tool — the technical detail this guide otherwise skips.
---

The rest of this site is written for someone using palaia, on purpose —
this page is the exception, for anyone building against it, extending it,
or just curious what's actually happening under the plain-language
explanations elsewhere.

## The memory's file format

What this guide calls a memory is what the engineering documentation calls
a `vault`: a directory of Markdown files with a small YAML block at the top
of each one, notes linking each other by relative path, and the whole
thing versioned with `git`. The full, normative format — every field,
every rule for what makes a file valid — is in the repository:

- [`v3/docs/`](https://github.com/byte5ai/palaia/tree/main/v3/docs) — the
  format itself is fully specified in the file named `vault-format.md`
  there.
- [`v3/decisions/`](https://github.com/byte5ai/palaia/tree/main/v3/decisions)
  — the recorded decisions behind it, including why it's clean-room rather
  than derived from any existing project's code.

Because it's just files, you can read, script against, or version-control a
memory with ordinary tools — nothing here requires palaia's own code to be
running.

## The connection protocol

Every AI tool in [Connect your AI](/connect/) talks to palaia over `MCP`
(the Model Context Protocol) — an open, cross-vendor standard for how an AI
tool discovers and calls tools, not something specific to palaia. Anything
that speaks it can connect, including a tool you write yourself; see
[Any other AI tool](/connect/clients/generic/) for the bare connection
details a new client needs.

Sign-in for tools that connect from outside your own network follows the
standard `OAuth 2.1` flow with dynamic client registration — again, not a
palaia invention, so any client library that already speaks it works
without palaia-specific code.

## Building an add-on

The marketplace's tools are built against a small, independently
installable SDK — it has no dependency on the hub's own code, so it stays
usable even if you're not running palaia's server at all. It covers what a
tool declares about itself (what it needs from a user, what it's allowed to
touch) and the submission checks a listing has to pass, including the same
plain-language check this whole site is written to satisfy.

- [`v3/sdk/`](https://github.com/byte5ai/palaia/tree/main/v3/sdk) — the SDK
  itself, installable on its own.
- [`v3/docs/addon-submission.md`](https://github.com/byte5ai/palaia/blob/main/v3/docs/addon-submission.md)
  — the submission process end to end.

## Automating and reacting to activity

Everything that happens in a hub — a note saved, a proposal created, a
session connecting — is published as an event a script or an automation
can react to, including outbound messages to another system. The event
shapes and the safe subset of conditions an automation can express (never
a general scripting language — a deliberate limit) are documented at
[`v3/docs/events.md`](https://github.com/byte5ai/palaia/blob/main/v3/docs/events.md).

## Coming from the previous version

The version before this one is still fully supported, on its own separate
branch, for anyone not ready to move. If you're one of its users, start
with the [migration guide](https://github.com/byte5ai/palaia/blob/main/v3/docs/migrate-from-v2.md)
instead — it covers what carries over, what changes, and what this version
doesn't do yet.

## Running the server yourself

The hub itself — the program this whole site is documentation *for* — is
open source. Its own engineering documentation, architecture notes, and
the full specification set that built it live at the root of the
repository:

- [`v3/MASTERPLAN.md`](https://github.com/byte5ai/palaia/blob/main/v3/MASTERPLAN.md)
  — what it is and why it's built the way it is.
- [`v3/docs/`](https://github.com/byte5ai/palaia/tree/main/v3/docs) — every
  subsystem's own reference.
- [`v3/specs/`](https://github.com/byte5ai/palaia/tree/main/v3/specs) — the
  work packages, if you want the full history of a decision rather than
  just its outcome.
