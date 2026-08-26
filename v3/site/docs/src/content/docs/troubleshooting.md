---
title: Troubleshooting & FAQ
description: The specific things that actually go wrong, and what to do about each one.
---

This page covers real, observed issues — not a generic "check your
connection" list. If something else goes wrong, the exact behavior matters
more than a guess, so start with what you actually saw.

## "It says Failed to connect, but the connection actually works"

If you check a newly added connection's status *before* signing in, Claude
Code's own status check can report a scary-looking failure — an address
mismatch — even though nothing is actually broken. Sign in (or finish
whatever setup step comes next for that tool), then check the status again:
it flips to connected. This is a cosmetic bug in how the status check
reports itself before sign-in exists at all, not a sign that anything needs
fixing on your end.

## "Sign-in fails immediately, every time, for every AI tool"

If your hub runs somewhere that routes its own outbound internet traffic
through a company or organizational proxy, the built-in safety check that
fetches a signing-in tool's published details can mistake that proxy for a
risk and refuse to fetch them — so every sign-in fails at the very first
step, for every tool, not just one.

If that describes your setup, set this in your hub's environment before
starting it:

```bash
FASTMCP_SSRF_TRUST_PROXY=1
```

Only set this if you actually run behind a proxy you trust — it tells the
safety check to trust the one already configured in your environment,
rather than turning the check off generally.

## "ChatGPT can look things up but won't save anything"

This is ChatGPT's own rule, not something palaia's setup controls: a
Plus/Pro account gets a read-only connection — lookups work exactly the
same either way — while write access needs a Business, Enterprise or Edu
workspace. The [ChatGPT connect page](/connect/clients/chatgpt/) says this
inline so it isn't a surprise partway through setup.

## "`palaia.local` doesn't resolve on my network"

Expected in a couple of common setups — Docker Desktop on macOS/Windows
runs containers inside a hidden VM that this kind of network advertisement
can't reach past, and it needs a specific network setting turned on even
on Linux. See [Install it](/install/)'s mDNS section for exactly
which setups it works on. It's always a convenience, never a requirement —
your hub's regular address (shown in its startup log, and in the dashboard)
always works.

## "How do I know a save actually happened?"

Ask the AI tool directly — a well-connected one tells you in one short
line what it saved, right after saving it. To check independently, open
your memory in the dashboard's explorer: brand-new saves show up in an
"unreviewed" area first, before a quiet background step files them into a
proper note — see [Your memory](/memory/) for what that step does. If
something you expected to be saved isn't showing up anywhere, the tool
likely didn't call the save action at all — [Connect your AI](/connect/)'s
"teach it to look things up and save things on its own" section for that
tool is worth revisiting.

## "Two AI tools I connected don't seem to know the same things"

Check that both are actually pointed at the *same* memory — if you kept
more than one (work and personal, say), it's easy to connect one tool to
each by mistake. The dashboard's connected-clients list shows exactly
which memory each connection reaches.

## Still stuck?

The project's issue tracker is the right place for anything not covered
here: [github.com/byte5ai/palaia](https://github.com/byte5ai/palaia).
