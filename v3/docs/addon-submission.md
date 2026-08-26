# Submitting an add-on to the palaia marketplace

This is the whole submission flow. If you built an add-on with
`palaia-addon-sdk` (see [`v3/sdk/README.md`](../sdk/README.md)), you have
everything you need already — this page tells you what happens next and
what to expect from review. There is no web submission form in this
phase: everything below happens as a pull request.

## What "the curated index" is

The marketplace a palaia hub browses is built from three sources: the
official MCP registry, manual entries someone typed in by hand, and the
**curated index** — a small, signed list of add-ons palaia itself
vouches for. Getting your add-on into the curated index is what this
page is about. It is a plain JSON file with one entry per add-on, signed
by the index maintainer's private key so a hub can tell a real update
from a tampered one.

## Before you open a PR

1. Your add-on has a `manifest.json` that passes:

   ```bash
   palaia-addon validate .
   palaia-addon test .
   ```

   Both clean, with no warnings you're ignoring. This is exactly what the
   maintainer will re-run — a manifest that doesn't pass either command
   locally will not pass in review either.

2. Your add-on is publicly reachable the way its manifest's `kind`
   promises: a `container` entry's image is pushed somewhere a hub can
   pull it (a public registry — ghcr.io, Docker Hub, etc.); a `remote`
   entry's URL actually answers MCP requests; a `skill` or `mcpb` entry's
   `source.value` URL actually serves the file.

3. Every string a marketplace user would read — `name`, `one_liner`,
   every `config_schema` field's `title` — is in plain language.
   `palaia-addon validate` already checks this for you against the same
   blocklist the rest of palaia's user-facing text is held to.

## Opening the PR

Add your add-on's manifest as one new entry in the curated index's
source file (the maintainer will tell you exactly which file and repo
that is if it isn't the one you already have write access to — the
signed document you see published at the index URL is a *build product*,
never edited by hand). One PR, one add-on. Include in the PR description:

- what the add-on does, in the same plain language as `one_liner`
- where the artifact lives (image, URL) and how you're keeping it there
- the exact permissions it needs and why each one is needed — this is
  the part reviewers spend the most time on

## What the maintainer does

1. **Validates.** Runs `palaia-addon validate` (and `test`, network and
   image availability permitting) against your manifest exactly as you
   did.
2. **Reviews permissions.** Every permission your manifest declares
   (`network`, `filesystem`, `memory-scope:read`, `memory-scope:write`)
   is a promise about what your add-on can reach once installed. The
   maintainer checks that the add-on's actual behavior doesn't ask for
   more than the manifest admits to, and that what it does ask for
   matches what the one-liner says it's for.
3. **Merges and re-signs.** Once satisfied, the maintainer adds your
   entry to the unsigned index source, then re-signs the whole document
   with `v3/tools/sign_market_index.py sign` (see that script's own
   `--help` and `v3/tools/README.md`) and publishes the signed result to
   the index URL every hub fetches from. Hubs pick up your add-on on
   their next fetch — no release of palaia itself required.

## What "verified" means — and does not mean

An entry that made it through this process is marked `verified: true`
in the merged marketplace shape every hub reads. That means:

- someone at palaia read the manifest, checked the permissions declared
  against what the add-on plausibly needs, and confirmed the artifact
  is reachable where it claims to be.

It does **not** mean:

- the add-on's code was audited line by line, or its container image was
  scanned for vulnerabilities (that's explicitly out of scope for this
  phase — curation here is a human review, not a security guarantee);
- the add-on will keep working forever — an add-on that stops answering,
  or starts asking for more than it used to, can be pulled from the
  index the same way it was added;
- palaia takes any responsibility for what the add-on does once
  installed — the permissions a hub's owner consents to at install time
  are the actual boundary, same as any other add-on.

An unverified entry (a manual, un-reviewed listing) is shown to hub
owners with a visibly stronger warning before install, precisely because
none of the above has happened for it yet.

## If something changes after you're listed

Push a new image tag / update your `remote` server / etc. as normal — the
curated index entry doesn't need to change for that. If your `manifest.json`
itself changes (new permission, new config field, a different `source`),
open a new PR the same way; the maintainer reviews the diff, not just the
new file, so a permission you're adding is exactly as visible as one you
had from the start.
