# palaia Backup & Restore

> **Normative.** Implements [SPEC-604](../specs/SPEC-604-backup-restore.md):
> `GET /api/backup` (`server/src/palaia_hub/backup.py`,
> `server/src/palaia_hub/backup_api.py`), the dashboard's "Back up" action
> (`web/src/routes/Home.tsx`), and the offline restore path documented here
> — plus the first of issue #297's **backup targets**
> (`server/src/palaia_hub/backup_targets.py`), §5 below.
> The user-facing version of this page (no repository-internal terms) is
> [Back up & restore](../site/docs/src/content/docs/backup-restore.md) on
> the docs site.

## 1. What the archive contains, and why

`GET /api/backup` streams a `tar.gz` of the whole hub home — the same
directory every store in this package persists under
(`palaia_hub.config.palaia_home()`, or `PALAIA_HOME` if set):

- `config.yaml`, `vaults.yaml`
- every vault: notes, `.git` history, `meta/vault.md`
- `oauth/oauth.sqlite3`, `oauth/signing-key.pem`
- `secrets.sqlite3` **and** `secrets.key` — the upstream credential store
  and the key it is encrypted under (SPEC-302,
  `server/src/palaia_hub/upstream/secrets.py`). Leaving either one out
  would make a "backup" that cannot restore secrets, which the SPEC states
  plainly is not a backup at all.
- `tokens.yaml`, `hooks.yaml`, `hooks_outbox.sqlite3`,
  `automations.yaml`, `automations_outbox.sqlite3`,
  `notifications.sqlite3`, `stash.db`, `directory.db`, `messenger.db`,
  the marketplace caches, `funnel_stats.json`, `mode_audit.jsonl`

**Excluded on purpose: each vault's `.palaia/index.sqlite3`.** It is
rebuildable state, not a system of record — the notes on disk are the
source of truth. It is left out to keep the archive smaller, and this is
safe *because* the index is already rebuilt from the vault's notes on every
hub start (`VaultIndex.open(build=True)`, the default, called for every
vault in `serve.py`/`cli.py`) — restoring an archive with no index file
puts a vault in exactly the state it is in the first time it is ever
opened, a path already exercised on every boot. Proven by
`server/tests/backup/test_archive.py` (the exclusion itself) and
`server/tests/e2e/test_spec604_backup_restore.py` (the rebuild, end to
end, against a real restored home).

**Not included: a vault registered at a custom path outside the hub
home.** `VaultRegistry` allows an absolute path anywhere on disk; the
default "create a memory" flow always places one under the home
(`<home>/vaults/<key>`), so this only matters for an operator who chose a
custom location deliberately. Back that vault up separately (it is a plain
git-tracked directory — copy it, or use your own backup tooling on it).

## 2. Consistency claim

There is no cross-store quiesce lock — building one would be new machinery
invented for this feature alone, which the SPEC explicitly asks not to do.
What is actually claimed, and why it holds:

- **Every SQLite database** (found by content — the on-disk magic header,
  not by filename convention, since this repository uses both `.sqlite3`
  and `.db` for the same thing) is captured through SQLite's own online
  backup API (`sqlite3.Connection.backup`) into an in-memory database, then
  serialized. That is correct even while another connection holds the file
  open in WAL mode with committed rows still sitting in `-wal`, unlike a
  raw file copy — see `server/tests/backup/test_archive.py::
  test_a_sqlite_snapshot_includes_wal_resident_data_and_omits_the_wal_file`.
- **Everything else** (`config.yaml`, `vaults.yaml`, notes, the YAML
  stores) is written via `palaia_hub.vault.atomic.atomic_write_bytes` — a
  temp file plus `os.replace` — so a read mid-write can only ever see the
  whole old content or the whole new content. A vault's `.git` history is
  git's own content-addressed, effectively-immutable object store.

**Not claimed:** that the archive is one atomic snapshot *across* stores.
Two stores written to in the same second could land a moment apart in one
archive. For a single-operator personal hub with no distributed
transaction spanning multiple stores, that gap is not a real exposure —
see `docs/security/threat-model.md` §8, item 9.

## 3. Restore — offline, by design

A dashboard *upload*-restore endpoint is explicitly out of scope for this
pass (SPEC-604 non-goal: "too much risk surface for this pass" — accepting
an arbitrary uploaded archive that gets unpacked over a running hub's own
state is a materially larger attack surface than a download). Restore is a
few manual steps instead:

**stop the hub → unpack the archive into its data volume → start it again.**

Both the one-liner install and the compose file use the same named Docker
volume (`palaia_home` by default) as the hub's home, so the unpack step is
identical either way.

### Unpack the archive into the volume

```bash
# Run once, regardless of which of the two variants below started the hub.
# Replace the filename with the one you actually downloaded.
docker run --rm \
  -v palaia_home:/data \
  -v "$PWD":/backup \
  alpine sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; \
                tar xzf /backup/palaia-backup-YYYYMMDDTHHMMSSZ.tar.gz -C /data"
```

The `rm -rf` clears the volume first (including dotfiles) — omit it only
if you are restoring into a genuinely empty volume (a fresh install), in
which case there is nothing to clear.

### One-liner variant

```bash
docker rm -f palaia-hub          # stop, if it exists
# (unpack step above)
docker run -d --name palaia-hub \
  -p 8420:8420 -v palaia_home:/data --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

### Compose variant

```bash
cd v3/deploy
docker compose down
# (unpack step above, still pointed at the palaia_home volume this
#  compose file declares)
docker compose up -d
```

On the next start, every store opens exactly as it does on any other
boot — including each vault's search index, which rebuilds itself from the
restored notes. There is no separate "restore mode": a hub that starts
against a home directory built this way behaves identically to one that
grew there naturally.

## 4. Security posture

- `GET /api/backup` is served only to a signed-in owner (issue #317). Where
  the admin session gate (`palaia_hub.admin_session`) is mounted it answers
  401 like every other `/api/*` route; where it is *not* — `mode: locked`
  without a `dashboard.require_sign_in` override, or a hub with no sign-in
  server — the route refuses with 403 and names the two ways out, because
  the archive is key material rather than "the vault" the locked-mode LAN
  posture was written for. `create_app` tells the route which case applies
  (`session_gated`); no opt-in parameter exists to mount it any other way.
- `palaia-hub backup [--out PATH]` writes the identical archive on the
  machine the hub runs on (mode `0600`, via a `.part` file renamed into
  place) — the way to back up a hub whose dashboard has no sign-in. In the
  container: `docker exec palaia-hub palaia-hub backup --out /tmp/hub.tar.gz`
  then `docker cp palaia-hub:/tmp/hub.tar.gz .`.
- The archive is built and streamed straight into the HTTP response body;
  `server/src/palaia_hub/backup.py` never writes it to a temp file, so
  there is no window where a full copy of a hub's secrets sits in a
  world-readable location server-side.
- `Cache-Control: no-store` is set on the response.
- The dashboard's "Back up" button carries the warning in plain language:
  *this file can act as your hub — store it like you would a password.*

## 5. Backup targets (issue #297)

SPEC-604's floor needs a person at either end: a browser session for the
download, a shell for `palaia-hub backup`. The owner decision on 2026-09-01
is that a hub must also write its archive **itself**, into a destination
named once — starting with a local directory, "which must always work".

### 5.1 The abstraction

`server/src/palaia_hub/backup_targets.py`. A target declares two class-level
facts about what it moves and implements one method that moves it:

| | `carries_full_archive` | `secret_safe` |
|---|---|---|
| `LocalDirectoryTarget` (built) | yes — the whole hub home | yes — a path on the operator's own filesystem, the same place `palaia-hub backup` already writes these bytes |
| user-defined external target (not built) | yes | must be answered by whoever builds it |
| per-vault git remote (not built) | **no** — notes only; no hub secret has ever lived in a vault | n/a |

`BackupTarget.run` refuses, before building a single byte, any target whose
`carries_full_archive` is not matched by `secret_safe`. That is issue #297's
"never pushed to a git remote or any target the operator hasn't explicitly
designated as secret-safe", enforced as an invariant rather than as a
comment — `server/tests/backup/test_targets.py::
test_a_target_that_would_move_the_full_archive_somewhere_unsafe_is_refused`
proves a deliberately misdeclared target class fails on its first call.

### 5.2 The local-directory target

Configured under `backup.targets` in `config.yaml`
(`palaia_hub.config.BackupSettings`):

```yaml
backup:
  targets:
    - type: local_directory
      name: nas
      path: /mnt/nas/palaia-backups
      keep_last: 7
```

- `name` — the handle used by `--target`, by
  `POST /api/backup/targets/{name}/run` and in every `backup.target.*`
  event. Slug-shaped, unique.
- `path` — absolute (the hub runs as a service and in a container, where a
  relative path resolves against an unpredictable cwd). Created on first
  run; `~` is expanded.
- `keep_last` — retention, `null` to keep everything. Only files matching
  `palaia-backup-*.tar.gz` are candidates, ordered **by name** (the
  timestamp is fixed-width UTC, so lexicographic order is chronological and
  no mtime a copy rewrote is trusted). Anything else in that directory is
  never touched.

The archive is written through a `.part` sibling renamed into place only
once complete, `chmod 0600` **before** the rename, exactly like
`palaia-hub backup`. A directory inside the hub home is refused: each
archive would contain every archive before it, and none would survive
losing that directory.

### 5.3 Surfaces

| Surface | |
|---|---|
| `GET /api/backup/targets` | the configured destinations (`backup_api.py`) |
| `POST /api/backup/targets/{name}/run` | writes one now, on a worker thread; 404 unknown, 500 with the reason when the destination failed |
| `palaia-hub backup --target NAME` | the same run on the host (repeatable) |
| `palaia-hub backup --all-targets` | every one, continuing past a failure, exit 1 if any failed |
| `palaia-hub backup --list-targets` | what is configured; writes nothing |

Both REST routes carry the same admin gate as the download itself (issue
#317) and refuse with a 403 naming the CLI on a hub with no sign-in.

### 5.4 Events

`backup.target.succeeded` / `backup.target.failed`, origin `backup` — issue
#297's "failures surface as events/notifications, never silently", and
routable by SPEC-307 automations like any other event. See
[`events.md` §3.9](events.md). A publish that itself raises is logged and
never turns a completed backup into a reported failure. The CLI path has no
bus attached (one-shot process): it reports on stdout/stderr and exits
non-zero instead, which is what a `cron`/`systemd` wrapper reads.

### 5.5 Not built in this pass

The user-defined external target and the per-vault git remote push, and a
**scheduler** (retention shipped; the interval did not — `cron`/`systemd`
around `--all-targets` is the honest interim, and the docs site says so).
A `config.yaml` naming an unimplemented `type` is refused at load with a
message saying it does not exist yet, rather than validating into a hub
that would never produce that backup. The dashboard shows no target UI yet
either; the REST surface it will use is the one above.

## 6. Verifying this yourself

```bash
cd v3
uv run pytest server/tests/backup -q
uv run pytest server/tests/e2e/test_spec604_backup_restore.py -q
uv run pytest server/tests/security/test_threat_model_coverage.py -q
```
