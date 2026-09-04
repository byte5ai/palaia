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
There's also no automatic or scheduled backup: **Back up** downloads one
file, once, whenever you choose to run it.
