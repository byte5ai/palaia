"""``GET /api/backup`` — download the whole hub home as one ``tar.gz``
(SPEC-604 deliverable #1).

Always mounted, the same posture as ``/api/health``/``/api/info``/the funnel
router (:mod:`palaia_hub.app`): every hub has a home directory from the
moment it first boots, so there is nothing to opt into and no store this
route depends on beyond the filesystem itself. Gated the same way every
other ``/api/*`` route is — see :mod:`palaia_hub.admin_session`'s module
docstring for why that is true by construction rather than by remembering
to wire a dependency here — which is the whole security posture this
endpoint relies on: the archive contains upstream secrets and their
encryption key (:mod:`palaia_hub.upstream.secrets`), so it must never be
reachable without a live owner session, in every mode that gates.

Nothing here writes the archive to disk; :func:`palaia_hub.backup.
iter_archive_bytes` streams it straight from the builder thread to the
response body. ``Cache-Control: no-store`` on top, so nothing between the
hub and the browser is tempted to keep a copy either.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from .backup import ARCHIVE_MEDIA_TYPE, archive_filename, iter_archive_bytes

BACKUP_PATH = "/api/backup"


def build_backup_router(*, home: Path) -> APIRouter:
    """Build the ``/api/backup`` router.

    Args:
        home: the hub home to archive — the same directory every other
            store in this package persists under.
    """
    router = APIRouter(tags=["backup"])

    @router.get(BACKUP_PATH)
    async def download_backup() -> StreamingResponse:
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


__all__ = ["BACKUP_PATH", "build_backup_router"]
