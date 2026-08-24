"""Dynamic gateway mounting (SPEC-210 deliverable #1).

:func:`~palaia_hub.gateway.build.build_gateway` builds the gateway's whole
mountable surface once, at hub-startup time, from a :class:`GatewayConfig`
known in advance. That is fine for the profiles/vaults ``config.yaml``
names before the hub starts, but a vault created later — through the
dashboard wizard's ``POST /api/vaults``, at runtime, while the hub keeps
serving other requests — has nowhere to go: Starlette's own route table
(``app.router.routes``) is built once when :class:`~fastapi.FastAPI` is
constructed, and a mounted :class:`~fastmcp.FastMCP` profile's ASGI lifespan
(its streamable-HTTP session manager) must run for the whole time that
profile is reachable, started before the first request and stopped after
the last — see ``gateway/build.py``'s module docstring for why skipping
that hangs a request rather than erroring.

:class:`DynamicGateway` is the seam that lets a profile be **rebuilt and
swapped** while the hub's own top-level ASGI lifespan keeps running,
without ever touching :class:`~fastapi.FastAPI`'s own (immutable-after-
construction) route list, and without violating anyio's cancel-scope
ownership rule (the concurrency finding this module is built around — see
below):

- The gateway is mounted **once**, at ``/mcp``, as a single
  :class:`starlette.routing.Router` (``self.router`` /
  :attr:`DynamicGateway.asgi_app`) — not as one ``app.mount()`` per profile
  path. Everything below this ``/mcp`` mount is this class's own business.
- Each profile is one entry in ``self.router.routes`` (a
  :class:`starlette.routing.Mount`). Adding or replacing a profile builds a
  **new list** (``[*kept, new_mount]``) and assigns it to
  ``self.router.routes`` in one statement — never ``.append()``/``.pop()``
  in place. Starlette's own request dispatch (``Router.app``) does
  ``for route in self.routes: ...`` with no ``await`` between reading
  ``self.routes`` and finishing that scan, and this process runs one
  coroutine at a time on asyncio's event loop, so a request that started
  its route scan a microsecond before a swap always sees one fully-formed
  generation of the list — the old one or the new one, never a half-built
  mix. No lock is needed for *readers*; the internal ``asyncio.Lock`` this
  class uses only serializes *writers* (concurrent ``add_vault`` calls)
  against each other.

- **The cancel-scope finding.** A mounted FastMCP app's ASGI lifespan
  (``app.lifespan(app)``, confirmed against the installed fastmcp to
  already be an ``@asynccontextmanager``-wrapped callable — the same one
  :func:`~palaia_hub.gateway.build.build_gateway` hands to
  ``combine_lifespans``) opens an anyio cancel scope/task group *bound to
  the asyncio task that enters it*. Entering it from a short-lived request-
  handling task (e.g. the coroutine running the wizard's ``POST
  /api/vaults`` handler) and only exiting it later from a *different* task
  (the hub's own top-level lifespan, at shutdown) is exactly the mistake
  anyio refuses: the first attempt to actually use the mounted app raises
  ``RuntimeError: Attempted to exit a cancel scope that isn't the current
  task's current cancel scope`` — found empirically while building this
  class; there is no public fastmcp/anyio flag to opt out of it, because
  the rule is correct. The fix is structural: **one dedicated, long-lived
  background task per** :class:`DynamicGateway` (started in :meth:`start`,
  stopped in :meth:`aclose`) **owns every profile's lifespan enter *and*
  exit**, via one :class:`~contextlib.AsyncExitStack` that never leaves
  that task. :meth:`add_vault` only builds the new FastMCP app/server
  (plain object construction — no anyio scope) in the caller's own task,
  then hands the *already-built* app to the background task over a queue
  and awaits a future it resolves; the background task does the actual
  ``enter_async_context`` and the route-list swap, both from itself, then
  resolves the caller's future. ``aclose()`` is the same pattern: it asks
  the background task to stop, and that task closes its own exit stack —
  every profile ever mounted, oldest first — from the one task that ever
  touched any of them.
- The **old** FastMCP app for a rebuilt profile is deliberately **not**
  torn down synchronously at swap time (the route swap happens before the
  old entry's removal from the exit stack's perspective — it stays
  registered in the stack, to be exited at :meth:`aclose`). A request
  already dispatched to it, or an open streamable-HTTP/SSE session against
  it, keeps running against the old session manager for as long as it
  naturally takes — tearing down a live session out from under an
  in-flight request would be strictly worse than the small resource cost
  of letting it finish. This is a deliberate, bounded leak: one retired
  FastMCP session-manager task group per profile rebuild (no vault engine
  or database handle — those are owned by the caller, not by this class),
  held open until :meth:`aclose`, and profile rebuilds are a rare, human-
  paced event (someone creating a vault through the wizard), never a
  per-request occurrence.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.http import StarletteWithLifespan
from starlette.routing import Mount, Router
from starlette.types import ASGIApp

from ..auth.policy import check_gateway_auth_policy
from .build import GatewayConfigError, _build_profile_server, _build_vault_servers
from .config import GatewayConfig, ProfileConfig, VaultMountConfig
from .vault_protocol import VaultService

#: Sentinel telling the background task to stop and close everything.
_STOP = object()


@dataclass
class _MountCommand:
    """One "mount this profile" request to the background task."""

    profile_path: str
    server: FastMCP
    asgi_app: StarletteWithLifespan
    done: asyncio.Future[None]


class DynamicGateway:
    """The gateway's mountable surface, rebuildable after the hub has started.

    Args:
        config: the gateway shape known at construction time (may be
            empty — a hub with no vaults yet still starts).
        vault_services: backing service per vault in ``config.vaults``.
        mode: the hub's operating mode (``HubConfig.mode``) — checked
            against every profile, at :meth:`start` and again at every
            :meth:`add_vault`, the same way
            :func:`~palaia_hub.auth.policy.check_gateway_auth_policy`
            already checks a static :class:`~.build.GatewayASGI` (SPEC-108):
            a profile added at runtime in ``cloud``/``open`` mode still
            needs a token verifier, exactly like one named in
            ``config.yaml`` at startup does.
        token_verifiers: optional per-profile-path verifier, same contract
            as :func:`~.build.build_gateway`.
    """

    def __init__(
        self,
        config: GatewayConfig,
        vault_services: Mapping[str, VaultService],
        *,
        mode: str = "locked",
        token_verifiers: Mapping[str, TokenVerifier] | None = None,
    ) -> None:
        self._config = config
        self._vault_services: dict[str, VaultService] = dict(vault_services)
        self._vault_servers: dict[str, FastMCP] = _build_vault_servers(config, self._vault_services)
        self._mode = mode
        self._token_verifiers: dict[str, TokenVerifier] = dict(token_verifiers or {})
        self.router = Router(routes=[])
        self._profile_servers: dict[str, FastMCP] = {}
        self._lock = asyncio.Lock()
        # See the class docstring's "cancel-scope finding": every lifespan
        # enter/exit happens inside `_lifecycle_task`, via `_queue`, never
        # directly in the caller's own task.
        self._queue: asyncio.Queue[_MountCommand | object] = asyncio.Queue()
        self._lifecycle_task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @property
    def asgi_app(self) -> ASGIApp:
        """The single ASGI app to mount once, at a fixed parent path (``/mcp``)."""
        return self.router

    @property
    def profile_servers(self) -> Mapping[str, FastMCP]:
        """Snapshot of every currently-mounted profile's :class:`FastMCP` server."""
        return dict(self._profile_servers)

    async def start(self) -> None:
        """Start the background lifecycle task and mount every configured profile."""
        self._lifecycle_task = asyncio.create_task(self._lifecycle())
        async with self._lock:
            for profile in self._config.profiles:
                await self._request_mount(profile)
        check_gateway_auth_policy(self._mode, self._profile_servers)

    async def add_vault(
        self,
        vault: VaultMountConfig,
        service: VaultService,
        *,
        profile_paths: list[str],
    ) -> None:
        """Register a new vault and rebuild-and-swap every profile that mounts it.

        ``profile_paths`` names the profile(s) the new vault should be
        reachable under — an existing profile gets the vault key appended
        to its ``vaults`` list (rebuilt from scratch with the new set); a
        profile path not yet in the config becomes a brand-new one-vault
        profile. Either way, only the named profiles are rebuilt — every
        other already-mounted profile is untouched.
        """
        async with self._lock:
            if vault.key in self._vault_services:
                raise GatewayConfigError(
                    f"vault key {vault.key!r} is already mounted at this gateway"
                )
            self._config = self._config.model_copy(update={"vaults": [*self._config.vaults, vault]})
            self._vault_services[vault.key] = service
            self._vault_servers[vault.key] = _build_vault_servers(
                GatewayConfig(vaults=[vault]), {vault.key: service}
            )[vault.key]

            profiles_by_path = {p.path: p for p in self._config.profiles}
            for path in profile_paths:
                existing = profiles_by_path.get(path)
                if existing is None:
                    new_profile = ProfileConfig(path=path, vaults=[vault.key])
                else:
                    new_profile = existing.model_copy(
                        update={"vaults": [*existing.vaults, vault.key]}
                    )
                profiles_by_path[path] = new_profile
            self._config = self._config.model_copy(
                update={"profiles": list(profiles_by_path.values())}
            )

            for path in profile_paths:
                await self._request_mount(profiles_by_path[path])

        check_gateway_auth_policy(self._mode, self._profile_servers)

    async def _request_mount(self, profile: ProfileConfig) -> None:
        """Build one profile's FastMCP app (plain construction — safe in the
        caller's own task) and hand it to the lifecycle task to actually
        mount. Caller holds ``self._lock``."""
        auth = self._token_verifiers.get(profile.path)
        server = _build_profile_server(profile, self._config, self._vault_servers, auth)
        asgi_app = server.http_app(path="/")
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_MountCommand(profile.path, server, asgi_app, done))
        await done
        self._profile_servers[profile.path] = server

    async def _lifecycle(self) -> None:
        """The one task that ever enters or exits a profile's ASGI lifespan.

        Owns a single :class:`~contextlib.AsyncExitStack` for the whole
        gateway's life: every generation of every profile ever mounted is
        entered here and stays in this stack (even after being swapped out
        of ``self.router.routes``, see the class docstring) until
        :meth:`aclose` asks this task to stop, at which point ``async with
        stack:`` unwinds everything, oldest first, from this same task.
        """
        async with AsyncExitStack() as stack:
            while True:
                item = await self._queue.get()
                if item is _STOP:
                    break
                command = item
                assert isinstance(command, _MountCommand)
                try:
                    await stack.enter_async_context(command.asgi_app.lifespan(command.asgi_app))
                except Exception as exc:  # noqa: BLE001 - relayed to the waiting caller
                    if not command.done.done():
                        command.done.set_exception(exc)
                    continue
                new_mount = Mount(f"/{command.profile_path}", app=command.asgi_app)
                kept = [
                    route
                    for route in self.router.routes
                    if getattr(route, "path", None) != new_mount.path
                ]
                self.router.routes = [*kept, new_mount]  # atomic swap — see class docstring
                if not command.done.done():
                    command.done.set_result(None)
        self._stopped.set()

    async def aclose(self) -> None:
        """Ask the lifecycle task to stop; it closes every mounted generation."""
        if self._lifecycle_task is None:
            return
        await self._queue.put(_STOP)
        await self._stopped.wait()
        with contextlib.suppress(asyncio.CancelledError):
            await self._lifecycle_task
        self._lifecycle_task = None


__all__ = ["DynamicGateway"]
