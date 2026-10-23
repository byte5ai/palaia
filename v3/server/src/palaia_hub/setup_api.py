"""``/api/setup`` — where first-run setup stands, and ``/api/hub/restart``.

Issues #559 and #561. The first-run wizard used to keep its progress in the
browser: a reload started it at step 1 again, and its rail ticked a step off
because the wizard had moved past it, not because the hub had it. This
router answers from the hub itself:

* what exists — the owner account, memories (vaults) and the profiles AI
  tools connect to;
* what the running hub uses — operating mode, whether its sign-in server
  runs and under which address — next to what ``config.yaml`` says it will
  use after a restart, and whether a restart is therefore due;
* what the owner chose — the goal (cloud or private), and whether setup was
  finished or skipped. Only these two are stored (``setup.json`` in the hub
  home); everything else is read live, so the answer cannot drift from the
  hub's real state.

A hub that already has memories but no ``setup.json`` (one installed before
this file existed) counts as set up, so updating never sends its owner back
into the wizard.

``POST /api/hub/restart`` lets the browser apply a change that needs a
restart. It ends the hub process gracefully; whatever runs it starts it
again — the packaged container's restart policy. It is offered only where
the installer says such a supervisor exists (``PALAIA_SELF_RESTART=1``),
because elsewhere it would just stop the hub, and it answers only the
dashboard's own JSON request, never another site's form.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from .admin_session import owner_account_exists
from .config import HubConfig, config_file_path
from .events import EventBus, publish_event
from .funnel import FunnelStore
from .security.files import harden_file
from .vault import VaultRegistry
from .vault.atomic import atomic_write_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .oauth import AuthorizationServer

logger = logging.getLogger("palaia_hub.setup_api")

SETUP_FILE = "setup.json"

#: Set by the installer and the compose file, where a restart policy brings
#: the container back after the hub exits.
SELF_RESTART_ENV = "PALAIA_SELF_RESTART"
#: The public https address the installer set up for cloud access (Tailscale
#: Funnel), if any. A suggestion for the wizard — never configuration.
CLOUD_URL_HINT_ENV = "PALAIA_CLOUD_URL_HINT"

Goal = Literal["cloud", "private"]
#: Wizard steps the owner may leave out on purpose: an account on a private
#: hub, cloud access, connecting an AI app now.
SkippableStep = Literal["account", "cloud", "client"]


class SetupStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Finished or skipped — the dashboard then opens on Home.
    completed: bool
    goal: Goal | None
    #: Steps the owner chose to leave out (so the wizard does not ask again).
    skipped: list[SkippableStep]
    owner_configured: bool
    vaults: list[str]
    profiles: list[str]
    #: The running hub.
    mode: Literal["locked", "cloud", "open"]
    sign_in_active: bool
    issuer: str | None
    #: config.yaml, which the next start uses.
    configured_mode: Literal["locked", "cloud", "open"]
    configured_sign_in: bool
    configured_issuer: str | None
    public_url: str | None
    cloud_url_hint: str | None
    #: The running hub uses something else than config.yaml says — or its
    #: sign-in server cannot grant access to a memory created since it started.
    restart_required: bool
    restart_supported: bool
    #: Cloud access is live: cloud mode, sign-in under an https address,
    #: an owner, and a profile for AI tools to connect to.
    cloud_ready: bool
    #: The hub's last self-test of its public address (the configured one)
    #: passed every check.
    cloud_verified: bool
    client_connected: bool
    first_memory_saved: bool
    #: Plain-language problems the hub found while starting.
    problems: list[str]


class SetupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Goal | None = None
    completed: bool | None = None
    skipped: list[SkippableStep] | None = None


class RestartOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    restarting: bool


def _read_choices(home: Path) -> dict[str, object] | None:
    path = home / SETUP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("could not read %s; treating setup as not started", path)
        return {}
    return data if isinstance(data, dict) else {}


def _write_choices(home: Path, choices: dict[str, object]) -> None:
    path = home / SETUP_FILE
    atomic_write_text(path, json.dumps(choices, indent=2) + "\n")
    harden_file(path)


#: Every read-modify-write of ``setup.json`` — the wizard's choices and the
#: self-test's result — holds this, so neither overwrites what the other
#: stored a moment before.
_CHOICES_LOCK = threading.Lock()


def _update_choices(
    home: Path,
    change: Callable[[dict[str, object]], None],
    *,
    has_memories: Callable[[], bool],
) -> None:
    """Read ``setup.json``, apply ``change`` and write it back, as one step.

    A hub installed before the file existed counts as set up when it has
    memories; the write that first creates the file keeps that answer
    instead of turning it into "not set up".
    """
    with _CHOICES_LOCK:
        choices = _read_choices(home)
        if choices is None:
            choices = {"completed": has_memories()}
        change(choices)
        _write_choices(home, choices)


def record_cloud_check(home: Path, url: str, passed: bool) -> None:
    """Remember the last public-address self-test (``/api/exposure/selftest``).

    The wizard ticks cloud access only once the hub itself has reached its
    public address and found every check passing — configuration alone does
    not prove a tunnel leads here (issue #561).
    """

    def change(choices: dict[str, object]) -> None:
        choices["cloud_check"] = {"url": url.rstrip("/"), "passed": passed}

    _update_choices(home, change, has_memories=lambda: bool(VaultRegistry(home).names()))


def _refuse_unless_sent_by_this_hubs_pages(request: Request) -> None:
    """Refuse a request that another site's page could have sent.

    The restart takes no input and is reachable on hubs without the admin
    session gate (``locked`` mode by default), so a plain form on another
    site could otherwise trigger it through the owner's browser. The
    dashboard sends JSON; another site's page cannot send that content type
    without a CORS preflight, which this hub never grants. Where a browser
    says where a request came from (``Sec-Fetch-Site``, over https), anything
    but this hub's own pages is refused as well.
    """
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail="the hub restarts only on its dashboard's own request (JSON).",
        )
    if request.headers.get("sec-fetch-site", "same-origin").lower() != "same-origin":
        raise HTTPException(
            status_code=403,
            detail="the hub can only be restarted from its own dashboard.",
        )


def build_setup_router(
    config: HubConfig,
    *,
    home: Path,
    vault_keys: Callable[[], Sequence[str]],
    oauth_server: AuthorizationServer | None,
    funnel_store: FunnelStore | None = None,
    event_bus: EventBus | None = None,
    problems: Sequence[str] = (),
) -> APIRouter:
    """Build the setup-status router.

    Args:
        config: the running configuration.
        vault_keys: the memories that exist right now.
        oauth_server: the running sign-in server, if any.
        problems: start-up problems worth showing the owner (for example a
            sign-in server that could not start).
    """
    router = APIRouter(tags=["setup"])
    # Polled by the wizard: re-read config.yaml only when it changed (#348).
    from .modes.api import _ConfiguredConfig

    configured_cache = _ConfiguredConfig(home)

    def _profiles(configured: HubConfig, keys: list[str]) -> list[str]:
        # Lazy: palaia_hub.cli imports the app that mounts this router.
        from .cli import _gateway_profiles_for_oauth, _profile_scopes

        try:
            resolved = _gateway_profiles_for_oauth(configured, keys)
        except SystemExit:
            return []
        return sorted(_profile_scopes(resolved))

    def _scopes_missing(configured: HubConfig, keys: list[str]) -> bool:
        if oauth_server is None:
            return False
        from .cli import _gateway_profiles_for_oauth, _profile_scopes

        try:
            wanted = _profile_scopes(_gateway_profiles_for_oauth(configured, keys))
        except SystemExit:
            return False
        granted = oauth_server.grantable_scopes()
        return any(
            not set(scopes) <= set(granted.get(profile, ())) for profile, scopes in wanted.items()
        )

    def _status() -> SetupStatus:
        from .modes.api import _restart_required

        configured = configured_cache.get() if config_file_path(home).exists() else config
        keys = sorted(vault_keys())
        choices = _read_choices(home)
        skipped: list[SkippableStep] = []
        check = (choices or {}).get("cloud_check")
        public = (configured.exposure.public_url or configured.oauth.issuer or "").rstrip("/")
        cloud_verified = (
            isinstance(check, dict)
            and bool(check.get("passed"))
            and bool(public)
            and check.get("url") == public
        )
        if choices is None:
            completed = bool(keys)
            goal: Goal | None = None
        else:
            raw_skipped = choices.get("skipped")
            if isinstance(raw_skipped, list):
                skipped = [step for step in ("account", "cloud", "client") if step in raw_skipped]
            completed = bool(choices.get("completed", False))
            raw_goal = choices.get("goal")
            goal = "cloud" if raw_goal == "cloud" else "private" if raw_goal == "private" else None
        owner = (
            oauth_server.store.get_owner() is not None
            if oauth_server is not None
            else owner_account_exists(home)
        )
        issuer = oauth_server.issuer if oauth_server is not None else None
        profiles = _profiles(configured, keys)
        funnel = funnel_store.status() if funnel_store is not None else None
        return SetupStatus(
            completed=completed,
            goal=goal,
            skipped=skipped,
            owner_configured=owner,
            vaults=keys,
            profiles=profiles,
            mode=config.mode,
            sign_in_active=oauth_server is not None,
            issuer=issuer,
            configured_mode=configured.mode,
            configured_sign_in=configured.oauth.enabled,
            configured_issuer=configured.oauth.issuer,
            public_url=configured.exposure.public_url,
            cloud_url_hint=os.environ.get(CLOUD_URL_HINT_ENV, "").strip() or None,
            restart_required=_restart_required(config, configured)
            or _scopes_missing(configured, keys),
            restart_supported=os.environ.get(SELF_RESTART_ENV) == "1",
            cloud_ready=(
                config.mode == "cloud"
                and oauth_server is not None
                and bool(issuer)
                and str(issuer).startswith("https://")
                and owner
                and bool(profiles)
            ),
            cloud_verified=cloud_verified,
            client_connected=bool(funnel and funnel.client_connected_at),
            first_memory_saved=bool(funnel and funnel.first_memory_at),
            problems=list(problems),
        )

    @router.get("/api/setup", response_model=SetupStatus)
    async def get_setup() -> SetupStatus:
        return await asyncio.to_thread(_status)

    @router.put("/api/setup", response_model=SetupStatus)
    async def put_setup(body: SetupUpdate) -> SetupStatus:
        def change(choices: dict[str, object]) -> None:
            if body.goal is not None:
                choices["goal"] = body.goal
            if body.completed is not None:
                choices["completed"] = body.completed
            if body.skipped is not None:
                choices["skipped"] = sorted(set(body.skipped))

        await asyncio.to_thread(
            _update_choices, home, change, has_memories=lambda: bool(vault_keys())
        )
        return await asyncio.to_thread(_status)

    @router.post("/api/hub/restart", response_model=RestartOut, status_code=202)
    async def restart(request: Request) -> RestartOut:
        _refuse_unless_sent_by_this_hubs_pages(request)
        if os.environ.get(SELF_RESTART_ENV) != "1":
            raise HTTPException(
                status_code=409,
                detail="this hub cannot restart itself here. Fix: restart it where it runs "
                "(for the container: `docker restart palaia-hub`).",
            )
        if event_bus is not None:
            publish_event(event_bus, "hub.restarting", origin="hub", data={})
        logger.info("restart requested from the dashboard")
        # A moment for this answer to reach the browser; then the same
        # graceful shutdown `docker stop` triggers. The container's restart
        # policy starts the hub again.
        asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)
        return RestartOut(restarting=True)

    return router


__all__ = [
    "SETUP_FILE",
    "SetupStatus",
    "SetupUpdate",
    "build_setup_router",
    "record_cloud_check",
]
