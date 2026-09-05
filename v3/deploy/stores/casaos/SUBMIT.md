# Submitting palaia to the CasaOS App Store

Source: `IceWhaleTech/CasaOS-AppStore` — PR into the "v2 source" repo (a
`docker-compose.yml` with a top-level `x-casaos` block, plus per-service
`x-casaos` metadata), or a third-party store added by URL
(v3/research/mcp-landscape-2026.md §8). This package targets the PR route.

`docker-compose.yml` here was written against a real, currently-listed
app's manifest (`Apps/Syncthing/docker-compose.yml` in that repo)
field-for-field — every `x-casaos` key present there is present here,
minus the ones that only make sense for a multi-language listing
(this file ships `en_US` only; CasaOS renders whatever locales are
present and falls back for the rest, so this is not a broken listing,
just a smaller one — add more locales in the PR if you want them).

## Steps

1. Fork `IceWhaleTech/CasaOS-AppStore`.
2. Create `Apps/palaia/docker-compose.yml` from this directory's file.
   Copy `icon.png` alongside it, or host it anywhere reachable and point
   `x-casaos.icon`/`x-casaos.thumbnail` at that URL instead (both fields
   here currently point at this repo's own `main` branch — fine once this
   PR merges and the file is actually on `main`, but confirm the path
   before submitting).
3. Read `docs/specs/overview.md` and `docs/quick-start/overview.md` in
   that repo (their CONTRIBUTING.md names these as the source of truth for
   field-by-field detail — this package matches their real Syncthing
   listing but was not cross-checked against every field those docs
   describe).
4. Run `./scripts/build_dist.sh` locally per their CONTRIBUTING.md — it
   must produce a `dist/index.json` with no errors before a PR is opened.
5. Open the PR.

## Data directory ownership

The container runs as uid/gid `1000:1000` (pinned in `v3/deploy/Dockerfile`,
issue #329), and `docker-compose.yml` says so with `user: "1000:1000"`.
`/DATA/AppData/$AppID/data` is a bind mount; CasaOS creates it as root when
the app first starts, so the non-root process inside cannot write to it
(the container drops every capability and has no root step that could
chown). Until CasaOS itself sets the ownership — check its current
behaviour when you validate the listing — the one-time fix on the host is:

```bash
sudo chown -R 1000:1000 /DATA/AppData/palaia/data
```

(`$AppID` resolves to this app's `name`, `palaia`.) Put this line in the
listing's description or the PR notes so a user hitting `PermissionError`
on first boot finds it.

## Faster alternative: a third-party store

CasaOS also loads app stores by URL, no PR needed. Publishing this same
`Apps/palaia/docker-compose.yml` in a small public git repo laid out the
same way, then adding that repo's URL as a custom store in CasaOS, works
today — worth doing in parallel with the PR above.

## What to update before every release

`x-casaos.version` and the container's `image:` tag should track the
`stable` channel — bump `version` on each release; the `:stable` tag
itself always points at the current release already.
