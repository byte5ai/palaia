"""Serve the built dashboard (SPEC-109).

``npm run build`` in ``v3/web`` produces a static single-page app under
``v3/web/dist``. This module mounts that build, with SPA fallback: any
path that is not a real file under the build directory (a deep link like
``/explorer/some-note``) still receives ``index.html``, so client-side
routing works on refresh. ``/api/*`` is never touched by the fallback —
it is excluded before the static app ever sees the request.

Serving is entirely optional: if no build directory is found, the hub
still starts and answers ``/api/*`` (SPEC-101's "starts with zero
config" rule holds for a checkout that has not run ``npm run build``
yet).
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

#: Explicit override for where the built dashboard lives.
WEB_DIST_ENV = "PALAIA_WEB_DIST"


def _default_dist_dir() -> Path:
    # v3/server/src/palaia_hub/static.py -> parents[2] == v3/
    return Path(__file__).resolve().parents[2] / "web" / "dist"


def resolve_dist_dir() -> Path | None:
    """Return the dashboard build directory, or ``None`` if there isn't one."""
    override = os.environ.get(WEB_DIST_ENV)
    candidate = Path(override).expanduser() if override else _default_dist_dir()
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return candidate
    return None


class SPAStaticFiles(StaticFiles):
    """``StaticFiles`` that falls back to ``index.html`` on a 404.

    Any request path under this mount that does not match a real file
    (a client-side route) resolves to the SPA's ``index.html`` instead
    of a 404, so deep links and refreshes work. Requests actually
    404 only if the build itself has no ``index.html``.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            assert self.directory is not None  # set via the constructor's `directory=`
            return FileResponse(Path(self.directory) / "index.html")
        if response.status_code == 404:
            assert self.directory is not None
            return FileResponse(Path(self.directory) / "index.html")
        return response


def mount_dashboard(app: FastAPI, dist_dir: Path | None = None) -> bool:
    """Mount the dashboard build onto ``app`` if one is available.

    Returns whether a build directory was found and mounted. Mounted
    last (by the caller, after every ``/api/*`` route is registered) —
    Starlette matches routes in registration order, so ``/api/*``
    requests never reach the SPA fallback.
    """
    resolved = dist_dir if dist_dir is not None else resolve_dist_dir()
    if resolved is None:
        return False
    app.mount("/", SPAStaticFiles(directory=resolved, html=True), name="dashboard")
    return True


__all__ = ["WEB_DIST_ENV", "SPAStaticFiles", "mount_dashboard", "resolve_dist_dir"]
