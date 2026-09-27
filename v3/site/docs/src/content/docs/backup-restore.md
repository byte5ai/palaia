---
title: Back up & restore
description: One button downloads everything palaia has saved. Here's what's in that file, and how to bring it back.
---

## Back up

On the dashboard's home screen, **Back up** downloads one file with
everything palaia has saved on your behalf: every memory, your sign-in and
connection setup, and anything else you've connected (saved passwords or
keys for other tools included).

**Treat that file like a password.** Anyone who has it can act as your hub
— read everything in it and, if they restore it somewhere, look and behave
exactly like your setup. Store it the way you'd store a password: in a
password manager or an encrypted drive, never in a plain, shared, or
public place, and never sent casually over email or chat.

You need to be signed in as the administrator to download one — the same
sign-in the dashboard itself uses. If your hub's dashboard has no sign-in
turned on (the default when it only runs on your own network), the button
is replaced by a note: on the machine the hub runs on, `palaia-hub backup`
writes the same file. Running palaia in Docker, that is
`docker exec palaia-hub palaia-hub backup --out /tmp/hub.tar.gz` followed by
`docker cp palaia-hub:/tmp/hub.tar.gz .`.

One thing is deliberately left out to keep the file smaller: the part that
makes searching fast. It isn't a record of anything — it's rebuilt
automatically from your actual notes the moment a restored install starts
up, so leaving it out costs you nothing.

<!-- screenshot: the "Back up" action on the dashboard home screen, with
     its warning text visible -->

## Have palaia write the file for you

Downloading needs a browser and you. You can instead name a folder once and
have palaia write the very same file there itself — an external drive, or a
folder on your network storage that the machine running palaia can reach.
Nothing goes through your browser, so the size of the file stops mattering.

Add it to `config.yaml` on the machine palaia runs on:

```yaml
backup:
  targets:
    - type: local_directory
      name: nas
      path: /mnt/nas/palaia-backups
      keep_last: 7
```

`name` is how you'll refer to that folder; `path` has to be the full path,
and the folder is created if it isn't there. `keep_last` deletes palaia's
own older files in that folder once there are more than that many — files
palaia didn't write are never touched. Write `keep_last: null` to keep
every one of them.

Restart palaia. The dashboard's **Backups** screen (also linked from the
backup card on the home screen) now lists that folder, when palaia last
backed up into it and whether that worked, with a **Back up now** button
next to it. The file goes straight from palaia into the folder, never
through your browser.

On the machine palaia runs on, the same thing from the command line:

```bash
palaia-hub backup --target nas     # one folder
palaia-hub backup --all-targets    # every folder you've configured
palaia-hub backup --list-targets   # which ones are configured, and how the last backup went
```

Running in Docker, put `docker exec palaia-hub` in front, e.g.
`docker exec palaia-hub palaia-hub backup --target nas`.

### Back up on a schedule

To have palaia back up by itself, add how many hours apart, in the same
`backup` section:

```yaml
backup:
  interval_hours: 24
  targets:
    - type: local_directory
      name: nas
      path: /mnt/nas/palaia-backups
      keep_last: 7
```

After a restart, palaia writes a backup into every folder you've listed
once a day — `24` hours apart; the shortest you can set is `1`. Together
with `keep_last`, that is a rolling week of daily backups that looks after
itself. The Backups screen shows when the next one is due.

A few things it takes care of for you:

- **Restarts don't reset the clock.** palaia remembers when it last backed
  up. If it was switched off when a backup was due, it writes one about a
  minute after it starts again.
- **One folder that fails doesn't stop the others.** An unplugged drive is
  reported, and the next folder still gets its backup.
- **Never twice at once.** Pressing **Back up now** while a scheduled
  backup is being written into that folder just tells you it's already on
  its way.

If you used to run `palaia-hub backup --all-targets` from your own
scheduler (a `cron` entry or a timer), remove it once `interval_hours` is
set — two schedulers writing into one folder at the same moment can get in
each other's way.

**The same warning applies, and more so:** that file can act as your hub.
Only point this at a place you'd be comfortable storing a password — an
encrypted drive, or a share only you can read. A folder inside palaia's own
saved data is refused outright: every backup would contain every earlier
one, and losing that disk would take all of them at once.

If a backup fails — the drive isn't mounted, the share is full — you'll
hear about it rather than find out later: the Backups screen shows what
went wrong next to that folder, and the command says exactly what went
wrong and exits with an error. Every backup palaia writes by itself or from
the dashboard also raises an event, which you can route to a notification
like any other — including telling a scheduled one apart from one you
started.

<!-- screenshot: the Backups screen — the configured folders, each with its
     last backup and a "Back up now" action, and the schedule below -->

## Restore

Restoring is a few manual steps rather than a button, on purpose — bringing
back a full download like this is a bigger, less-frequent action than
anything else the dashboard does day to day, and it's safer to walk through
deliberately than to trigger by accident from a web page.

The idea in three steps: **stop palaia, replace its saved data with what's
in your download, start it again.**

If you installed with the one-line command from [Install it](/install/):

```bash
docker rm -f palaia-hub

docker run --rm \
  -v palaia_home:/data \
  -v "$PWD":/backup \
  alpine sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; \
                tar xzf /backup/palaia-backup-YOUR-FILE.tar.gz -C /data"

docker run -d --name palaia-hub \
  -p 8420:8420 -v palaia_home:/data --restart unless-stopped \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --read-only --tmpfs /tmp --tmpfs /run \
  ghcr.io/byte5ai/palaia-hub:stable
```

<!-- rc-channel-note -->
> **Release candidate:** until `3.0.0` is final there is no `stable` image yet. Where a
> command or file on this page says `ghcr.io/byte5ai/palaia-hub:stable`, use
> `ghcr.io/byte5ai/palaia-hub:beta` for now.

If you installed with the docker-compose file:

```bash
cd v3/deploy
docker compose down

docker run --rm \
  -v palaia_home:/data \
  -v "$PWD":/backup \
  alpine sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null; \
                tar xzf /backup/palaia-backup-YOUR-FILE.tar.gz -C /data"

docker compose up -d
```

Replace `palaia-backup-YOUR-FILE.tar.gz` with the actual name of the file
you downloaded, and run these from the folder you saved it in.

Open the dashboard once it's back up — everything should look exactly the
way it did when you took the backup, including your connected tools.
Setting this up on a brand-new machine works the same way: install palaia
there first (so the empty saved-data location exists), then run the
restore steps against it before connecting anything.

## Not yet supported

Restoring by uploading a file straight from the dashboard isn't available
yet — the offline steps above are the only path back in this release.

Backups don't run on a timer yet either: a folder you configure above is
written when you ask for it, not on a schedule. Until that lands, a `cron`
entry or a `systemd` timer around `palaia-hub backup --all-targets` does
the job — it exits with an error if any folder failed, so your scheduler
notices.

Two other places to send a backup are planned and not built: a destination
you define yourself, and pushing a memory to a remote copy of its own
history (which would carry your notes only, never any of your keys).

To restore from a folder palaia wrote to, use the newest
`palaia-backup-*.tar.gz` file in it — it is byte-for-byte the same file the
**Back up** button hands you, and the steps above work unchanged.
