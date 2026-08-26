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
import logging
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import dataclass

from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.server.middleware import Middleware
from starlette.routing import Mount, Router
from starlette.types import ASGIApp

from ..auth.policy import check_gateway_auth_policy
from ..directory.service import DirectoryService
from ..messenger.service import MessengerService
from ..stash.service import StashService
from ..upstream.models import UpstreamConfig
from ..upstream.service import UpstreamCredentialError, UpstreamService
from .build import (
    GatewayConfigError,
    UpstreamMount,
    _build_profile_server,
    _build_vault_servers,
)
from .config import GatewayConfig, ProfileConfig, VaultMountConfig
from .vault_protocol import VaultService

logger = logging.getLogger("palaia_hub.gateway.dynamic")

#: Sentinel telling the background task to stop and close everything.
_STOP = object()


@dataclass
class _MountCommand:
    """One "mount this profile" request to the background task."""

    profile_path: str
    server: FastMCP
    asgi_app: StarletteWithLifespan
    done: asyncio.Future[None]


@dataclass
class _UnmountCommand:
    """One "drop this profile from the router" request to the background
    task (SPEC-301's ``DELETE /api/gateway/profiles/{path}``).

    Unlike :class:`_MountCommand`, there is no ASGI app to enter a lifespan
    for — only a route to remove. The profile's already-entered lifespan
    stays in the background task's exit stack regardless (the same
    deliberate-leak rule the class docstring's "old FastMCP app" bullet
    describes for a rebuild: an in-flight request or open session against
    it keeps running until :meth:`DynamicGateway.aclose`).
    """

    profile_path: str
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
        auth_provider_factory: SPEC-504 first-run funnel audit fix. Given,
            :meth:`add_vault` calls it for any profile path it is about to
            mount for the first time and no verifier already covers (a
            brand-new path — the common "hub had zero vaults, wizard just
            created the first one" case ``token_verifiers`` above cannot
            cover, because that path did not exist yet when this gateway
            was constructed). Its result, when not ``None``, is cached into
            ``self._token_verifiers`` exactly like an entry that had been
            in the constructor's own ``token_verifiers`` all along — every
            later rebuild of that path reuses the same verifier, never
            calls the factory again. Omitted, a genuinely new path mounts
            with whatever ``token_verifiers`` already had for it (``None``
            if nothing did) — the pre-SPEC-504 behavior, which is how a
            hub with no auth configured at all (``auth_enabled: false``)
            is meant to keep working: the factory itself is what decides
            "nothing to verify with" versus "a verifier exists", not this
            class.
        profile_middleware: optional per-profile-path fastmcp middleware,
            same contract as :func:`~.build.build_gateway` — re-applied on
            every rebuild of that profile (SPEC-206: the curator profile's
            policy must survive a vault being added at runtime).
        stash_service: the hub-wide stash (SPEC-202), mounted into any
            profile whose ``stash`` flag is set (SPEC-301) — same contract
            as :func:`~.build.build_gateway`.
        directory_service: the hub-wide session directory (SPEC-402),
            mounted into any profile whose ``directory`` flag is set — same
            "flag ahead of the service" contract as ``stash_service``.
        messenger_service: the hub-wide messenger (SPEC-403), mounted into
            any profile whose ``messenger`` flag is set — same contract
            again, and never onto the curator profile (refused by
            ``ProfileConfig`` and again at mount time).
        upstream_service: the external-server registry (SPEC-302). Given,
            a profile's ``upstreams`` entries are mounted **only while the
            upstream's last probe said it was reachable** — a down or
            switched-off server contributes no tools and, crucially, no
            wait: nothing in a profile build or a ``tools/list`` reaches
            for an unreachable endpoint. :meth:`start` deliberately does
            **not** probe (SPEC-302 deliverable #4: "the mount must not
            block hub startup"), so a freshly started hub mounts no
            upstream at all until
            :class:`palaia_hub.upstream.monitor.UpstreamHealthMonitor`'s
            first pass reports one up and calls
            :meth:`refresh_upstreams`.
    """

    def __init__(
        self,
        config: GatewayConfig,
        vault_services: Mapping[str, VaultService],
        *,
        mode: str = "locked",
        token_verifiers: Mapping[str, TokenVerifier] | None = None,
        auth_provider_factory: Callable[[str], TokenVerifier | None] | None = None,
        profile_middleware: Mapping[str, Sequence[Middleware]] | None = None,
        stash_service: StashService | None = None,
        upstream_service: UpstreamService | None = None,
        directory_service: DirectoryService | None = None,
        messenger_service: MessengerService | None = None,
    ) -> None:
        self._config = config
        self._upstream_service = upstream_service
        self._vault_services: dict[str, VaultService] = dict(vault_services)
        self._vault_servers: dict[str, FastMCP] = _build_vault_servers(config, self._vault_services)
        self._mode = mode
        self._token_verifiers: dict[str, TokenVerifier] = dict(token_verifiers or {})
        self._auth_provider_factory = auth_provider_factory
        self._profile_middleware: dict[str, Sequence[Middleware]] = dict(
            profile_middleware or {}
        )
        self._stash_service = stash_service
        self._directory_service = directory_service
        self._messenger_service = messenger_service
        self.router = Router(routes=[])
        self._profile_servers: dict[str, FastMCP] = {}
        self._lock = asyncio.Lock()
        # See the class docstring's "cancel-scope finding": every lifespan
        # enter/exit happens inside `_lifecycle_task`, via `_queue`, never
        # directly in the caller's own task.
        self._queue: asyncio.Queue[_MountCommand | _UnmountCommand | object] = asyncio.Queue()
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

    @property
    def config(self) -> GatewayConfig:
        """The gateway's current shape — a snapshot, safe to read from
        anywhere (SPEC-301's ``GET /api/gateway/profiles`` reads this)."""
        return self._config

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
            # SPEC-302 deliverable #5, the other direction: a *vault* created
            # at runtime must not silently shadow an already-connected
            # external server's tool prefix either. `model_copy` below does
            # not re-run GatewayConfig's validators, so the check is explicit.
            clashing = [u for u in self._config.upstreams if u.mount_namespace == vault.namespace]
            if clashing:
                raise GatewayConfigError(
                    f"vault {vault.key!r} would use the tool prefix "
                    f"{vault.namespace!r}, which the connected external server "
                    f"{clashing[0].key!r} ({clashing[0].display_name}) already "
                    "uses. Fix: name the vault differently, or give that server "
                    "another namespace."
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

            # SPEC-504 first-run funnel audit fix: a profile path that has
            # never been mounted before (the overwhelmingly common case for
            # the very first vault a fresh install's wizard creates — see
            # this class's docstring on `auth_provider_factory`) has no
            # entry in `self._token_verifiers` yet, because it did not
            # exist when this gateway — or the last config-driven rebuild
            # that repopulated `token_verifiers` — was built. Left
            # unfilled, `_request_mount` below would mount it with no
            # verifier at all, silently serving it unauthenticated even on
            # a hub with `auth_enabled: true` (the default in every mode,
            # not only cloud/open). Ask the factory once per path; cache
            # whatever it returns so every later rebuild of this same path
            # reuses it without calling the factory again.
            if self._auth_provider_factory is not None:
                for path in profile_paths:
                    if path not in self._token_verifiers:
                        verifier = self._auth_provider_factory(path)
                        if verifier is not None:
                            self._token_verifiers[path] = verifier

            for path in profile_paths:
                await self._request_mount(profiles_by_path[path])

        check_gateway_auth_policy(self._mode, self._profile_servers)

    async def refresh_upstreams(self, keys: Sequence[str] | None = None) -> list[str]:
        """Rebuild every profile that mounts one of ``keys`` (SPEC-302).

        Called whenever an external server's *mountability* changed — it
        came up, went down, was switched off, had its renames edited, or was
        just added. ``None`` refreshes every profile that mounts any
        upstream at all.

        Returns the profile paths that were actually rebuilt, so a caller
        can log or report it. A profile that mounts no affected upstream is
        left completely alone (no rebuild, no retired session manager).
        """
        async with self._lock:
            affected = [
                profile
                for profile in self._config.profiles
                if profile.upstreams
                and (keys is None or any(key in profile.upstreams for key in keys))
            ]
            for profile in affected:
                await self._request_mount(profile)
        return [profile.path for profile in affected]

    async def upsert_profile(
        self,
        path: str,
        vault_keys: Sequence[str],
        *,
        label: str | None = None,
        stash: bool = False,
        directory: bool = False,
        messenger: bool = False,
        hidden_tools: Sequence[str] = (),
        semantic_routing: bool = False,
        upstreams: Sequence[str] | None = None,
        auth: TokenVerifier | None = None,
    ) -> None:
        """Create a new profile, or fully replace an existing one's shape.

        The runtime profile-editor's create/edit operations (SPEC-301
        deliverable #2) — unlike :meth:`add_vault` (adds one vault to
        already-relevant profiles), this replaces the *whole* vault set,
        label and stash flag for one profile path. ``path`` itself is never
        edited this way (see :class:`~.config.ProfileConfig`'s docstring
        for why) — a caller wanting a new URL creates a new profile.

        Args:
            path: the profile to create, or the existing one to rebuild.
            vault_keys: every vault this profile should mount, replacing
                whatever it mounted before (an edit that only adds one
                vault to an existing list must pass the whole new list).
            label: the display name; ``None`` clears it back to "use the
                path".
            stash: whether this profile also carries the stash tool family.
            directory: whether this profile also carries the session
                directory tool family (SPEC-402).
            messenger: whether this profile also carries the messenger tool
                family (SPEC-403). Never valid on the curator profile.
            hidden_tools: final (post-namespace) tool names this profile
                should hide (SPEC-305 deliverable #3) — replaces whatever
                it hid before, same "whole list, not a delta" contract as
                ``vault_keys``.
            semantic_routing: whether this profile should expose
                ``find_tool``/``invoke_tool`` instead of its full surface
                (SPEC-305 deliverable #4).
            upstreams: every external server (SPEC-302) this profile should
                mount, by key — replacing whatever it mounted before, the
                same whole-list contract ``vault_keys`` follows. ``None``
                keeps an existing profile's list untouched (and means "none"
                for a brand-new one), so a caller editing only the vault
                list never silently unmounts a connected server.
            auth: the verifier this path should use for every future
                rebuild, recorded into ``self._token_verifiers``. Pass this
                for a genuinely new path if the hub's mode requires auth
                (:func:`~palaia_hub.auth.policy.check_gateway_auth_policy`
                refuses an unauthenticated profile in cloud/open, same as
                at startup). ``None`` leaves an existing path's verifier
                untouched — the normal case for editing only the vault
                list of an already-authenticated profile.

        Raises:
            GatewayConfigError: a vault key in ``vault_keys`` is not
                mounted at this gateway at all (create the vault first).
            palaia_hub.auth.policy.AuthPolicyError: the resulting profile
                would be unauthenticated in cloud/open mode.
        """
        async with self._lock:
            missing = [k for k in vault_keys if k not in self._vault_services]
            if missing:
                raise GatewayConfigError(
                    f"cannot mount profile {path!r}: vault key(s) {missing} are not "
                    "mounted at this gateway. Fix: create the vault first."
                )
            if auth is not None:
                self._token_verifiers[path] = auth
            profiles_by_path = {p.path: p for p in self._config.profiles}
            if upstreams is None:
                previous = profiles_by_path.get(path)
                resolved_upstreams = list(previous.upstreams) if previous is not None else []
            else:
                resolved_upstreams = list(upstreams)
            unknown_upstreams = [
                key
                for key in resolved_upstreams
                if key not in {u.key for u in self._config.upstreams}
            ]
            if unknown_upstreams:
                raise GatewayConfigError(
                    f"cannot mount profile {path!r}: no external server is "
                    f"configured under {unknown_upstreams}. Fix: connect the "
                    "server first."
                )
            new_profile = ProfileConfig(
                path=path,
                label=label,
                vaults=list(vault_keys),
                stash=stash,
                directory=directory,
                messenger=messenger,
                hidden_tools=list(hidden_tools),
                semantic_routing=semantic_routing,
                upstreams=resolved_upstreams,
            )
            profiles_by_path[path] = new_profile
            self._config = self._config.model_copy(
                update={"profiles": list(profiles_by_path.values())}
            )
            await self._request_mount(new_profile)
        check_gateway_auth_policy(self._mode, self._profile_servers)

    async def update_vault_identity(self, vault: VaultMountConfig) -> None:
        """Replace one already-mounted vault's identity (SPEC-305
        deliverable #1's inline rename): its display ``name``, ``purpose``,
        and/or ``tool_renames``, rebuilding that vault's own tool server
        plus every profile that mounts it — live, no restart.

        ``vault.key`` must already be mounted at this gateway (created via
        :meth:`add_vault` — this method only ever changes an existing
        vault's *identity*, never its key or backing service).

        Raises:
            GatewayConfigError: ``vault.key`` is not mounted at this gateway.
        """
        async with self._lock:
            if vault.key not in self._vault_services:
                raise GatewayConfigError(
                    f"cannot update vault identity: {vault.key!r} is not mounted "
                    "at this gateway."
                )
            self._config = self._config.model_copy(
                update={
                    "vaults": [
                        vault if v.key == vault.key else v for v in self._config.vaults
                    ]
                }
            )
            self._vault_servers[vault.key] = _build_vault_servers(
                GatewayConfig(vaults=[vault]), {vault.key: self._vault_services[vault.key]}
            )[vault.key]

            affected = [p for p in self._config.profiles if vault.key in p.vaults]
            for profile in affected:
                await self._request_mount(profile)
        check_gateway_auth_policy(self._mode, self._profile_servers)

    async def remove_profile(self, path: str) -> None:
        """Unmount ``path`` (SPEC-301's ``DELETE /api/gateway/profiles/{path}``).

        Raises:
            KeyError: no profile named ``path`` is currently mounted.
        """
        async with self._lock:
            if path not in {p.path for p in self._config.profiles}:
                raise KeyError(f"no profile {path!r} mounted at this gateway")
            self._config = self._config.model_copy(
                update={"profiles": [p for p in self._config.profiles if p.path != path]}
            )
            await self._request_unmount(path)

    async def register_upstream(self, upstream: UpstreamConfig) -> None:
        """Add or replace an external server in this gateway's own config.

        Only the *registry* changes here — no profile mounts it until a
        caller names it in :meth:`upsert_profile`'s ``upstreams``. The
        replacement is validated by :class:`~.config.GatewayConfig` itself,
        so a namespace that collides with a vault or another upstream is
        refused here rather than at mount time (SPEC-302 deliverable #5).
        """
        async with self._lock:
            others = [u for u in self._config.upstreams if u.key != upstream.key]
            # A fresh `GatewayConfig(...)` rather than `model_copy(update=...)`:
            # only the constructor re-runs the model validators, which is
            # where the namespace-conflict refusal lives.
            self._config = GatewayConfig(
                vaults=list(self._config.vaults),
                profiles=list(self._config.profiles),
                upstreams=[*others, upstream],
            )

    async def remove_upstream(self, key: str) -> list[str]:
        """Drop an external server and rebuild every profile that mounted it.

        Returns the profile paths rebuilt. Raises :class:`KeyError` when no
        such upstream is configured.
        """
        async with self._lock:
            if key not in {u.key for u in self._config.upstreams}:
                raise KeyError(f"no external server configured under {key!r}")
            profiles = [
                profile.model_copy(
                    update={"upstreams": [k for k in profile.upstreams if k != key]}
                )
                if key in profile.upstreams
                else profile
                for profile in self._config.profiles
            ]
            affected = [
                profile.path
                for profile, before in zip(profiles, self._config.profiles, strict=True)
                if profile.upstreams != before.upstreams
            ]
            self._config = GatewayConfig(
                vaults=list(self._config.vaults),
                profiles=profiles,
                upstreams=[u for u in self._config.upstreams if u.key != key],
            )
            for profile in profiles:
                if profile.path in affected:
                    await self._request_mount(profile)
        return affected

    async def _upstream_mounts_for(self, profile: ProfileConfig) -> dict[str, UpstreamMount]:
        """The subset of ``profile.upstreams`` that is actually mountable now.

        An upstream is mounted only when it is enabled *and* its last probe
        found it reachable — see the class docstring's ``upstream_service``
        note for why an unreachable one is left out entirely rather than
        mounted and allowed to time out on every ``tools/list``.
        """
        service = self._upstream_service
        if service is None or not profile.upstreams:
            return {}
        mounts: dict[str, UpstreamMount] = {}
        for key in profile.upstreams:
            config = service.configs.get(key)
            if config is None or not config.enabled or not service.is_up(key):
                continue
            try:
                proxy = await service.proxy_for(key)
            except UpstreamCredentialError as exc:
                logger.warning(
                    "not mounting external server %r on profile %r: %s",
                    key,
                    profile.path,
                    exc,
                )
                continue
            mounts[key] = UpstreamMount(config=config, server=proxy)
        return mounts

    async def _request_mount(self, profile: ProfileConfig) -> None:
        """Build one profile's FastMCP app (plain construction — safe in the
        caller's own task) and hand it to the lifecycle task to actually
        mount. Caller holds ``self._lock``."""
        auth = self._token_verifiers.get(profile.path)
        middleware = self._profile_middleware.get(profile.path, ())
        upstream_mounts = await self._upstream_mounts_for(profile)
        server = _build_profile_server(
            profile,
            self._config,
            self._vault_servers,
            auth,
            middleware,
            self._stash_service,
            upstream_mounts,
            self._directory_service,
            self._messenger_service,
        )
        asgi_app = server.http_app(path="/")
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_MountCommand(profile.path, server, asgi_app, done))
        await done
        self._profile_servers[profile.path] = server

    async def _request_unmount(self, path: str) -> None:
        """Ask the lifecycle task to drop ``path`` from the router. Caller
        holds ``self._lock``."""
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self._queue.put(_UnmountCommand(path, done))
        await done
        self._profile_servers.pop(path, None)

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
                if isinstance(item, _UnmountCommand):
                    # No lifespan to enter or exit here — its already-
                    # entered generation (if any) stays in `stack`,
                    # unwound only at `aclose`, same deliberate-leak rule
                    # a rebuild's retired generation follows (class
                    # docstring). Only the route disappears, atomically.
                    target = f"/{item.profile_path}"
                    self.router.routes = [
                        route
                        for route in self.router.routes
                        if getattr(route, "path", None) != target
                    ]
                    if not item.done.done():
                        item.done.set_result(None)
                    continue
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
