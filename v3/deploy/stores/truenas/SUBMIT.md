# Submitting palaia to the TrueNAS SCALE Apps catalog

Source: `truenas/apps` — community submissions, compose-based
(v3/research/mcp-landscape-2026.md §8). The real format (confirmed via
their own docs/community references, since the dossier only names the
repo): each app is `app.yaml` (static metadata) + `ix_values.yaml`
(image + constants) + `questions.yaml` (the Apps UI form) +
`templates/docker-compose.yaml` (a Jinja2 template rendered against both).

## Honesty check before you open a PR

This package was written from field lists gathered from TrueNAS's own
documentation and a real app's `app.yaml` — but **not** independently
rendered or run through `truenas/apps`' own tooling: this environment has
no TrueNAS instance, no docker daemon, and no checkout of that repo's own
CI scripts. Treat every file here as a well-grounded first draft, not a
verified one. Concretely, before submitting:

- **`app.yaml`**: no `lib_version`/`lib_version_hash` is set. Those pin a
  shared template library version from `truenas/apps`' own `library/`
  directory — fill them in from whatever that repo's current library
  version actually is (their contributor docs cover this); guessing a
  hash here would be worse than leaving it out.
- **`app.yaml`**: `run_as_context` is empty. The image runs as its own
  non-root `palaia` user (`useradd --system`, `v3/deploy/Dockerfile`)
  rather than a fixed uid/gid, so there is nothing correct to hardcode —
  read the real uid back with
  `docker run --rm ghcr.io/byte5ai/palaia-hub:stable id palaia` and fill
  it in if the schema wants a specific number rather than an empty list.
- **`questions.yaml`**: written to a plausible shape (groups + questions,
  a `dataset`-typed storage question, a `port`-`$ref`'d network question)
  but not validated against their actual JSON Schema for this file, which
  is more detailed than what's covered in this repo's own research.
- **`templates/docker-compose.yaml`**: not rendered by their Jinja2
  pipeline here — check `values.*`/`ix_values.*` references resolve the
  way their `library/` templates expect (their own community apps are the
  best reference; this file's shape follows the general pattern, not one
  specific example verified line-by-line).

Run their contributor guide's own local dev/test workflow
(`truenas/apps`' own `CONTRIBUTING.md` names it) against this `palaia/`
directory before opening a PR — that catches everything the paragraph
above flags.

## Steps

1. Fork `truenas/apps`.
2. Copy this `palaia/` directory into their `community/` train (matching
   `train: community` in `app.yaml`).
3. Run their local test/render tooling; fix anything it flags per the
   honesty check above.
4. Open the PR.

## What to update before every release

`app_version`/`human_version` in `app.yaml` and `image.tag` in
`ix_values.yaml` should track the `stable` channel — bump on release; the
`:stable` tag itself always points at the current release already.
