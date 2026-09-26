"""``/api/backup`` — the archive, out of this hub (SPEC-604, issue #297).

Three routes, one posture:

* ``GET /api/backup`` downloads the whole hub home as one ``tar.gz``
  (SPEC-604 deliverable #1).
* ``GET /api/backup/targets`` lists the destinations this hub is configured
  to write that same archive to itself.
* ``POST /api/backup/targets/{name}/run`` writes one now — the dashboard's
  half of issue #297's "on demand", with no browser in the data path: the
  bytes go from the hub to the operator's directory, never through the
  client that asked for it. A target already being written (by the
  schedule, issue #438, or an earlier click) answers 409.

Always mounted, the same posture as ``/api/health``/``/api/info``/the funnel
router (:mod:`palaia_hub.app`): every hub has a home directory from the
moment it first boots, so there is nothing to opt into and no store this
route depends on beyond the filesystem itself. A hub with no ``backup:``
section simply lists no targets.

**Never without a signed-in owner (issue #317).** Every route here, the
target ones included: naming (or triggering a write to) a destination is
not as grave as handing the archive out, but it is still hub administration
over a surface whose whole subject is key material. The archive contains the
OAuth signing key, the upstream secret store *and* its encryption key
(:mod:`palaia_hub.upstream.secrets`), the owner's password hash and every
client token — a file that can act as the hub. When the admin session gate
is mounted (:mod:`palaia_hub.admin_session`), it answers 401 for an
anonymous caller before this route runs. When it is *not* mounted — ``mode:
locked`` with no ``dashboard.require_sign_in`` override, or a hub with no
sign-in server at all — "trusts the network" is the documented posture for
the rest of ``/api/*``, but not for key material: this route then refuses
with 403 and names the two ways out (turn on sign-in, or ``palaia-hub
backup`` on the host). ``session_gated`` is how :func:`palaia_hub.app.
create_app` tells the route which of the two worlds it lives in.

Nothing here writes the archive to disk; :func:`palaia_hub.backup.
iter_archive_bytes` streams it straight from the builder thread to the
response body. ``Cache-Control: no-store`` on top, so nothing between the
hub and the browser is tempted to keep a copy either.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from .backup import ARCHIVE_MEDIA_TYPE, archive_filename, iter_archive_bytes
from .backup_schedule import (
    MANUAL_TRIGGER,
    BackupLedger,
    BackupScheduler,
    BackupTargetBusyError,
)
from .backup_targets import BackupTarget, BackupTargetError
from .events.schema import HubEventHook

BACKUP_PATH = "/api/backup"
BACKUP_TARGETS_PATH = "/api/backup/targets"
BACKUP_TARGET_RUN_PATH = "/api/backup/targets/{name}/run"


#: The 403 an ungated hub answers (issue #317). Plain language, and it names
#: both fixes — the same "Fix:" convention every other refusal follows.
UNGATED_DETAIL = (
    "Backups are only downloadable by a signed-in owner, and this hub has no "
    "dashboard sign-in turned on — the file would hand every key this hub holds "
    "to anyone who can reach it. Fix: turn on sign-in (`oauth.enabled: true` and "
    "`oauth.issuer` in config.yaml, then `palaia-hub oauth set-password`), or run "
    "`palaia-hub backup` on the machine the hub runs on."
)


#: The 403 an ungated hub answers on the target routes (issue #297). Same
#: reasoning as :data:`UNGATED_DETAIL`, different remedy: the archive these
#: write is the same key material, and the CLI can already run a target on
#: the host without a dashboard session.
UNGATED_TARGETS_DETAIL = (
    "Backup targets are only reachable by a signed-in owner, and this hub has no "
    "dashboard sign-in turned on — the archive a target writes holds every key this "
    "hub has. Fix: turn on sign-in (`oauth.enabled: true` and `oauth.issuer` in "
    "config.yaml, then `palaia-hub oauth set-password`), or run `palaia-hub backup "
    "--target <name>` on the machine the hub runs on."
)


def build_backup_router(
    *,
    home: Path,
    session_gated: bool = True,
    targets: Mapping[str, BackupTarget] | None = None,
    publish: HubEventHook | None = None,
    ledger: BackupLedger | None = None,
    scheduler: BackupScheduler | None = None,
) -> APIRouter:
    """Build the ``/api/backup`` router.

    Args:
        home: the hub home to archive — the same directory every other
            store in this package persists under.
        session_gated: whether :class:`~palaia_hub.admin_session.
            AdminSessionMiddleware` is mounted in front of this route.
            ``False`` makes every route here refuse with 403 and the
            matching detail — see the module docstring.
        targets: the configured destinations, by name
            (:func:`palaia_hub.backup_targets.build_targets`). Omitted or
            empty, the list route answers an empty list and the run route
            404s — a hub with no ``backup:`` section, which is the default.
        publish: the event hook every run reports its outcome on (issue
            #297: failures are never silent). Omitted, runs still happen
            and still return their result; nothing lands on the bus.
            Ignored when ``ledger`` is given — the ledger carries its own.
        ledger: the :class:`~palaia_hub.backup_schedule.BackupLedger` every
            run goes through (issue #438) — shared with ``scheduler`` so a
            click and a scheduled run of one target never overlap, and the
            source of each target's ``last_run``. Omitted, one is built here
            over ``targets``.
        scheduler: the running hub's
            :class:`~palaia_hub.backup_schedule.BackupScheduler`, when
            ``backup.interval_hours`` is set. Only read, for the list
            route's ``schedule`` block; ``None`` answers ``schedule: null``.
    """
    router = APIRouter(tags=["backup"])
    runs = ledger if ledger is not None else BackupLedger(home, targets or {}, publish=publish)
    configured: Mapping[str, BackupTarget] = runs.targets

    @router.get(BACKUP_PATH)
    async def download_backup() -> StreamingResponse:
        if not session_gated:
            raise HTTPException(status_code=403, detail=UNGATED_DETAIL)
        filename = archive_filename()
        return StreamingResponse(
            iter_archive_bytes(home),
            media_type=ARCHIVE_MEDIA_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    @router.get(BACKUP_TARGETS_PATH)
    async def list_targets() -> dict[str, Any]:
        """Every configured destination, in ``config.yaml`` order, with how
        its last run went — and the schedule, when there is one (issue
        #438: "surfaced in the dashboard")."""
        if not session_gated:
            raise HTTPException(status_code=403, detail=UNGATED_TARGETS_DETAIL)
        listed = []
        for name, target in configured.items():
            last = runs.last_run(name)
            listed.append(
                {
                    **target.describe(),
                    "running": runs.is_running(name),
                    "last_run": None if last is None else last.to_json(),
                }
            )
        return {
            "targets": listed,
            "schedule": None if scheduler is None else scheduler.status(),
        }

    @router.post(BACKUP_TARGET_RUN_PATH)
    async def run_backup_target(name: str) -> dict[str, Any]:
        """Write a backup to one target, now.

        Runs in a worker thread: building the archive is minutes of
        blocking filesystem and SQLite work, and this route must not hold
        the event loop for the rest of the hub while it happens.
        """
        if not session_gated:
            raise HTTPException(status_code=403, detail=UNGATED_TARGETS_DETAIL)
        target = configured.get(name)
        if target is None:
            known = ", ".join(sorted(configured)) or "none are configured"
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No backup target named {name!r}. Fix: add it under `backup.targets` "
                    f"in config.yaml and restart the hub (configured targets: {known})."
                ),
            )
        try:
            run = await run_in_threadpool(runs.run, name, trigger=MANUAL_TRIGGER)
        except BackupTargetBusyError as exc:
            # Issue #438: the schedule (or an earlier click) is already
            # writing this very backup. A second writer would collide with
            # it on the same second-stamped file name, so this one is
            # refused rather than queued — the backup is on its way.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BackupTargetError as exc:
            # The operator's own destination failed — an unmounted share, a
            # full disk, a directory the hub cannot write. That is a 500
            # (the request was fine, this hub could not carry it out) with
            # the reason stated plainly; the same reason is already on the
            # bus as `backup.target.failed`.
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return run.to_json()

    return router


__all__ = [
    "BACKUP_PATH",
    "BACKUP_TARGETS_PATH",
    "BACKUP_TARGET_RUN_PATH",
    "UNGATED_DETAIL",
    "UNGATED_TARGETS_DETAIL",
    "build_backup_router",
]
