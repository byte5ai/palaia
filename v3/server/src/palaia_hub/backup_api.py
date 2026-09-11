"""``GET /api/backup`` — download the whole hub home as one ``tar.gz``
(SPEC-604 deliverable #1).

Always mounted, the same posture as ``/api/health``/``/api/info``/the funnel
router (:mod:`palaia_hub.app`): every hub has a home directory from the
moment it first boots, so there is nothing to opt into and no store this
route depends on beyond the filesystem itself.

**Never without a signed-in owner (issue #317).** The archive contains the
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

from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from .backup import ARCHIVE_MEDIA_TYPE, archive_filename, iter_archive_bytes

BACKUP_PATH = "/api/backup"


#: The 403 an ungated hub answers (issue #317). Plain language, and it names
#: both fixes — the same "Fix:" convention every other refusal follows.
UNGATED_DETAIL = (
    "Backups are only downloadable by a signed-in owner, and this hub has no "
    "dashboard sign-in turned on — the file would hand every key this hub holds "
    "to anyone who can reach it. Fix: turn on sign-in (`oauth.enabled: true` and "
    "`oauth.issuer` in config.yaml, then `palaia-hub oauth set-password`), or run "
    "`palaia-hub backup` on the machine the hub runs on."
)


def build_backup_router(*, home: Path, session_gated: bool = True) -> APIRouter:
    """Build the ``/api/backup`` router.

    Args:
        home: the hub home to archive — the same directory every other
            store in this package persists under.
        session_gated: whether :class:`~palaia_hub.admin_session.
            AdminSessionMiddleware` is mounted in front of this route.
            ``False`` makes the route refuse every request with 403 and
            :data:`UNGATED_DETAIL` — see the module docstring.
    """
    router = APIRouter(tags=["backup"])

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

    return router


__all__ = ["BACKUP_PATH", "UNGATED_DETAIL", "build_backup_router"]
