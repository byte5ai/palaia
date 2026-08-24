"""Serve the built dashboard (SPEC-109).

``npm run build`` in ``v3/web`` produces a static single-page app under
``v3/web/dist``. This module mounts that build, with SPA fallback: any
path that is not a real file under the build directory (a deep link like
``/explorer/some-note``) still receives ``index.html``, so client-side
routing works on refresh. ``/api/*`` and ``/mcp/*`` are never touched by
the fallback: a *registered* route under either is matched by Starlette
before this mount is even considered, and :class:`SPAStaticFiles` itself
refuses to fall back for either prefix when nothing matched — so a
disabled/absent backend feature 404s like it should, rather than
returning the dashboard shell with a 200.

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
    # v3/server/src/palaia_hub/static.py -> parents[0]=palaia_hub,
    # [1]=src, [2]=server, [3]==v3/ (SPEC-110: the previous parents[2]
    # here resolved to v3/server/, one level short of v3/ — every existing
    # test overrides PALAIA_WEB_DIST, so a zero-config `palaia-hub serve`
    # was the only path that ever exercised this default, and it silently
    # served no dashboard at all. See tests/test_static.py's regression
    # test for the default path itself, not just an overridden one.)
    return Path(__file__).resolve().parents[3] / "web" / "dist"


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

    #: Path prefixes this mount never falls back to index.html for, even
    #: unmatched — backend surfaces, not client-side routes. "api" is the
    #: REST surface (some of it opt-in per create_app()'s parameters);
    #: "mcp" is the gateway's mount namespace (palaia_hub.gateway.build,
    #: "/mcp/<profile>"), absent entirely with no gateway given. "oauth" is
    #: the SPEC-203/204 authorization server's surface: SPEC-204's one-door
    #: rule depends on an IdP-configured hub's password route (registered
    #: conditionally, see :mod:`palaia_hub.oauth.routes`) 404ing when
    #: absent — without this prefix here, an unregistered `/oauth/login`
    #: would instead fall through to this mount and get the dashboard shell
    #: back with a 200, silently hiding that the route does not exist.
    _BACKEND_PREFIXES = ("api", "mcp", "oauth")

    async def get_response(self, path: str, scope: Scope) -> Response:
        # SPEC-110 fix: reaching this mount at all with a backend-prefixed
        # path means no route matched it — an opt-in REST endpoint whose
        # backing store was never given to create_app() (no
        # vault_registry/token_store), or an MCP profile with no gateway
        # mounted at all — not a client-side route. Every *registered*
        # backend route is already caught earlier by Starlette's routing
        # (this class's own docstring, and mount_dashboard's), but nothing
        # stopped an *unregistered* one from falling through to here and
        # getting index.html back with a 200 — silently turning a disabled
        # or absent feature into what looks like a successful response.
        first_segment = path.split("/", 1)[0]
        if first_segment in self._BACKEND_PREFIXES:
            return Response(status_code=404)
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
