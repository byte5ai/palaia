"""Connecting to an upstream: probes, proxies, credentials, teardown.

This is the only module that decrypts a secret (through
:class:`~palaia_hub.upstream.secrets.SecretStore`) and the only one that
builds a :class:`fastmcp.Client`. Two rules shape all of it:

**1. Mounting must never block hub startup, and a dead upstream must never
hang a profile** (SPEC-302 deliverable #4). Every client is built with an
explicit, bounded ``timeout``/``init_timeout``
(:attr:`~palaia_hub.upstream.models.UpstreamConfig.connect_timeout`), and
:meth:`UpstreamService.probe` swallows every connection failure into an
:class:`UpstreamStatus` with ``up=False`` and a one-line ``detail`` instead of
raising. Nothing in the mount path awaits a network round-trip: building a
proxy is plain object construction (verified against fastmcp 3.4.7 — a proxy
to an unreachable endpoint mounts fine), and fastmcp's own tool aggregator
already logs-and-skips a provider whose ``list_tools`` fails, so a profile
that mounts a down upstream still serves every other tool it has.

**2. The proxy uses the current client-backed-server mount**, not
``FastMCP.as_proxy()`` — deprecated in 3.4.7 (SPEC-002 FINDINGS Q1/Q2).
:func:`fastmcp.server.create_proxy` takes the (disconnected)
:class:`fastmcp.Client` this module builds and forwards every call over it.

A ``stdio`` upstream's :class:`~fastmcp.client.transports.StdioTransport` is
created **once per upstream** and cached, so repeated tool calls reuse one
child process rather than spawning one each time (fastmcp's
``keep_alive=True`` default). :meth:`UpstreamService.aclose` closes every
cached transport, which is what reaps those children at hub shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from fastmcp import Client
from fastmcp.client.transports import ClientTransport, StdioTransport, StreamableHttpTransport
from fastmcp.server import create_proxy
from fastmcp.server.providers.proxy import FastMCPProxy

from .models import UpstreamConfig
from .secrets import SecretStore, SecretStoreError

logger = logging.getLogger("palaia_hub.upstream.service")

#: Published on the event bus when an upstream's reachability changes.
EVENT_UP = "gateway.upstream.up"
EVENT_DOWN = "gateway.upstream.down"

#: What a status looks like before the first probe has run.
UNKNOWN_DETAIL = "Not checked yet."


class UpstreamNotConfiguredError(KeyError):
    """No upstream is registered under that key."""


class UpstreamCredentialError(RuntimeError):
    """An upstream references a secret that is missing or unreadable.

    Its message names the *secret's name* and what to do about it — never
    the value.
    """


@dataclass(frozen=True, slots=True)
class UpstreamStatus:
    """One upstream's last known reachability — the shape REST returns.

    ``detail`` is the "clear one-line status" the SPEC asks for: plain
    language, no stack trace, and never a credential (the probe's own
    exception text is normalized by :func:`_one_line` before it lands here).
    """

    key: str
    display_name: str
    namespace: str
    kind: str
    enabled: bool
    target: str
    up: bool
    detail: str
    checked_at: float | None = None
    tools: tuple[str, ...] = ()

    @property
    def tool_count(self) -> int:
        return len(self.tools)


@dataclass
class _Connection:
    """Cached per-upstream transport + client, so one child process serves
    every call to a ``stdio`` upstream."""

    transport: ClientTransport
    client: Client[ClientTransport]
    proxy: FastMCPProxy | None = None


def _one_line(exc: BaseException) -> str:
    """Collapse an exception into one plain-language line, credential-free.

    Only the exception *type* and its own message are used — never a repr of
    the client, transport or headers, any of which could carry a token.
    """
    message = str(exc).strip().splitlines()
    text = message[0] if message else exc.__class__.__name__
    if len(text) > 200:
        text = text[:197] + "..."
    return text or exc.__class__.__name__


class UpstreamService:
    """The upstream registry: configs, credentials, proxies and health.

    Args:
        upstreams: every configured upstream (see
            :func:`palaia_hub.upstream.models.check_namespace_conflicts` —
            the caller validates the set before handing it over).
        secret_store: where an ``http`` upstream's bearer token and a
            ``stdio`` upstream's injected environment come from. ``None``
            means no upstream may reference a secret; one that does is
            reported down with a plain-language reason rather than
            crashing the hub.
        publish: optional ``(event name, data)`` sink for
            ``gateway.upstream.up``/``down`` — called only on a *change*
            of state, so a healthy upstream does not emit an event per
            probe.
    """

    def __init__(
        self,
        upstreams: Iterable[UpstreamConfig] = (),
        *,
        secret_store: SecretStore | None = None,
        publish: Callable[[str, dict[str, object]], None] | None = None,
    ) -> None:
        self._configs: dict[str, UpstreamConfig] = {u.key: u for u in upstreams}
        self._secret_store = secret_store
        self._publish = publish
        self._status: dict[str, UpstreamStatus] = {
            key: self._unknown_status(cfg) for key, cfg in self._configs.items()
        }
        self._connections: dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- registry

    @property
    def configs(self) -> Mapping[str, UpstreamConfig]:
        """Snapshot of every configured upstream, keyed by ``key``."""
        return dict(self._configs)

    def config(self, key: str) -> UpstreamConfig:
        try:
            return self._configs[key]
        except KeyError as exc:
            raise UpstreamNotConfiguredError(
                f"no external server configured under {key!r}"
            ) from exc

    def statuses(self) -> list[UpstreamStatus]:
        """Every upstream's last known status, ordered by key."""
        return [self._status[key] for key in sorted(self._status)]

    def status(self, key: str) -> UpstreamStatus:
        self.config(key)  # raises UpstreamNotConfiguredError for an unknown key
        return self._status[key]

    def is_up(self, key: str) -> bool:
        """Whether ``key`` was reachable at its last probe."""
        status = self._status.get(key)
        return status is not None and status.up

    async def register(self, upstream: UpstreamConfig) -> UpstreamStatus:
        """Add or replace an upstream, dropping any cached connection to it."""
        async with self._lock:
            await self._drop_connection(upstream.key)
            self._configs[upstream.key] = upstream
            self._status[upstream.key] = self._unknown_status(upstream)
        return await self.probe(upstream.key)

    async def unregister(self, key: str) -> None:
        """Remove an upstream and reap its connection (if any)."""
        async with self._lock:
            self._configs.pop(key, None)
            self._status.pop(key, None)
            await self._drop_connection(key)

    # ---------------------------------------------------------------- health

    async def probe(self, key: str) -> UpstreamStatus:
        """Reachability probe: connect, initialize, ``tools/list``.

        Never raises for an unreachable upstream — the failure becomes the
        returned status's ``detail``. Publishes
        ``gateway.upstream.up``/``down`` when the state changed.
        """
        config = self.config(key)
        if not config.enabled:
            status = self._replace_status(
                key, up=False, detail="Switched off — nothing is connected.", tools=()
            )
            return status
        started = time.time()
        try:
            client = await self._client_for(config)
        except SecretStoreError as exc:
            return self._replace_status(key, up=False, detail=_one_line(exc), tools=())
        except UpstreamCredentialError as exc:
            return self._replace_status(key, up=False, detail=_one_line(exc), tools=())
        try:
            async with asyncio.timeout(config.connect_timeout + 2):
                async with client:
                    tools = await client.list_tools()
        except TimeoutError:
            return self._replace_status(
                key,
                up=False,
                detail=(
                    f"Did not answer within {config.connect_timeout:g} seconds. "
                    "Check that it is running and reachable."
                ),
                tools=(),
            )
        except Exception as exc:  # noqa: BLE001 — every failure is "down", with a reason
            return self._replace_status(key, up=False, detail=_one_line(exc), tools=())
        names = tuple(sorted(tool.name for tool in tools))
        elapsed = time.time() - started
        detail = (
            f"Connected — {len(names)} tool{'' if len(names) == 1 else 's'} "
            f"({elapsed * 1000:.0f} ms)."
        )
        return self._replace_status(key, up=True, detail=detail, tools=names)

    async def probe_all(self) -> list[UpstreamStatus]:
        """Probe every configured upstream concurrently."""
        keys = sorted(self._configs)
        if not keys:
            return []
        await asyncio.gather(*(self.probe(key) for key in keys), return_exceptions=False)
        return self.statuses()

    # ---------------------------------------------------------------- mounts

    async def proxy_for(self, key: str) -> FastMCPProxy:
        """The client-backed proxy server for ``key``, built once and cached.

        Plain object construction — no network round-trip, so a caller may
        mount this into a profile without risking a blocked startup even
        when the upstream is down (see the module docstring).
        """
        config = self.config(key)
        async with self._lock:
            connection = self._connections.get(key)
            if connection is None:
                connection = await self._build_connection(config)
                self._connections[key] = connection
            if connection.proxy is None:
                connection.proxy = create_proxy(
                    connection.client, name=f"palaia-upstream-{config.key}"
                )
            return connection.proxy

    # ------------------------------------------------------------- teardown

    async def aclose(self) -> None:
        """Close every cached transport — this is what reaps ``stdio`` children."""
        async with self._lock:
            for key in list(self._connections):
                await self._drop_connection(key)

    # ------------------------------------------------------------- internals

    def _unknown_status(self, config: UpstreamConfig) -> UpstreamStatus:
        return UpstreamStatus(
            key=config.key,
            display_name=config.display_name,
            namespace=config.mount_namespace,
            kind=config.kind,
            enabled=config.enabled,
            target=config.target,
            up=False,
            detail=UNKNOWN_DETAIL if config.enabled else "Switched off — nothing is connected.",
        )

    def _replace_status(
        self, key: str, *, up: bool, detail: str, tools: tuple[str, ...]
    ) -> UpstreamStatus:
        config = self._configs[key]
        previous = self._status.get(key)
        status = UpstreamStatus(
            key=config.key,
            display_name=config.display_name,
            namespace=config.mount_namespace,
            kind=config.kind,
            enabled=config.enabled,
            target=config.target,
            up=up,
            detail=detail,
            checked_at=time.time(),
            tools=tools,
        )
        self._status[key] = status
        changed = previous is None or previous.up != up or previous.checked_at is None
        if changed and self._publish is not None:
            self._publish(
                EVENT_UP if up else EVENT_DOWN,
                {
                    "upstream": config.key,
                    "display_name": config.display_name,
                    "namespace": config.mount_namespace,
                    "kind": config.kind,
                    "detail": detail,
                    "tool_count": len(tools),
                },
            )
        if not up:
            logger.warning(
                "external server %r (%s) is unavailable: %s",
                config.key,
                config.display_name,
                detail,
            )
        else:
            logger.info(
                "external server %r (%s) is available: %s",
                config.key,
                config.display_name,
                detail,
            )
        return status

    async def _client_for(self, config: UpstreamConfig) -> Client[ClientTransport]:
        """The cached client for ``config``, built on first use.

        Deliberately *not* rebuilt per call, even though a ``stdio`` child's
        environment and an HTTP transport's headers are fixed at construction
        time and would therefore keep serving a rotated secret: rebuilding
        here would respawn the child process on every health probe, and the
        proxy already mounted into a profile would still be holding the old
        client anyway. Invalidation is an explicit event instead —
        :meth:`register` (a server edited through REST) and
        :func:`palaia_hub.upstream.api.build_secret_change_hook` (a secret's
        value replaced) both drop the connection and let the profile be
        rebuilt around a fresh one.
        """
        async with self._lock:
            connection = self._connections.get(config.key)
            if connection is not None:
                return connection.client
            connection = await self._build_connection(config)
            self._connections[config.key] = connection
            return connection.client

    async def _build_connection(self, config: UpstreamConfig) -> _Connection:
        if config.kind == "http":
            headers = dict(config.headers)
            if config.auth is not None:
                secret = self._require_secret(config, config.auth.secret_name)
                headers[config.auth.header] = config.auth.value_template.format(secret=secret)
            assert config.url is not None  # guaranteed by UpstreamConfig's validator
            transport: ClientTransport = StreamableHttpTransport(
                config.url, headers=headers or None
            )
        else:
            env = dict(config.env)
            for env_var, secret_name in sorted(config.env_secrets.items()):
                env[env_var] = self._require_secret(config, secret_name)
            assert config.command is not None  # guaranteed by UpstreamConfig's validator
            transport = StdioTransport(
                command=config.command,
                args=list(config.args),
                env=env or None,
                cwd=config.cwd,
            )
        client: Client[ClientTransport] = Client(
            transport,
            timeout=config.connect_timeout,
            init_timeout=config.connect_timeout,
        )
        return _Connection(transport=transport, client=client)

    def _require_secret(self, config: UpstreamConfig, name: str) -> str:
        if self._secret_store is None:
            raise UpstreamCredentialError(
                f"{config.display_name} needs the stored secret {name!r}, but this "
                "hub has no secret store. Fix: run the hub with a home directory "
                "it can write to."
            )
        value = self._secret_store.get(name)
        if value is None:
            raise UpstreamCredentialError(
                f"{config.display_name} needs a secret called {name!r}, which is "
                "not stored yet. Fix: add it under Settings (it is written once "
                "and never shown again)."
            )
        return value

    async def _drop_connection(self, key: str) -> None:
        """Close and forget ``key``'s cached transport. Caller holds the lock."""
        connection = self._connections.pop(key, None)
        if connection is None:
            return
        try:
            # `ClientTransport.close()` carries no annotations in fastmcp
            # 3.4.7 (it is `async def close(self):`), so mypy's strict mode
            # calls this an untyped call. It is the documented teardown —
            # for a StdioTransport it is what terminates the child process.
            await connection.transport.close()  # type: ignore[no-untyped-call]
        except Exception as exc:  # noqa: BLE001 — shutdown must not raise
            logger.warning("closing the connection to %r did not finish cleanly: %s", key, exc)


__all__ = [
    "EVENT_DOWN",
    "EVENT_UP",
    "UNKNOWN_DETAIL",
    "UpstreamCredentialError",
    "UpstreamNotConfiguredError",
    "UpstreamService",
    "UpstreamStatus",
]
