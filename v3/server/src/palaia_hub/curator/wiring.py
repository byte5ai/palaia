"""One place that assembles a working curator (SPEC-206).

Both entry points — the hub's own scheduled curator
(:func:`palaia_hub.serve.build_production_app`) and the ``palaia-hub curator``
CLI — go through :func:`build_curator`, so "how the curator is put together"
has one definition: same guards, same audit sinks, same runner command.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fastmcp.server.middleware import Middleware

from ..config import HubConfig
from ..events.schema import Envelope
from ..gateway.config import VaultMountConfig
from ..stash import StashService, StashStore
from ..vault import VaultEngine
from .apply import ProposalApplier
from .audit import CuratorAudit, Publisher
from .middleware import CuratorScopeMiddleware
from .policy import ActiveCaptures
from .profile import (
    CURATOR_PROFILE_PATH,
    allowed_tool_specs,
    curator_profile_middleware,
    curator_tool_actions,
)
from .runner import CuratorRunner
from .service import CuratorScheduler
from .session import SessionRunner, SubprocessSessionRunner

#: ``EventBus.on`` — how the scheduler subscribes to ``inbox.captured``.
SchedulerSubscribe = Callable[[Callable[[Envelope], None]], Callable[[], None]]

#: The environment variable holding the curator token. Preferred over
#: ``curator.token`` in ``config.yaml``: a token in a config file is a secret
#: in a config file.
TOKEN_ENV = "PALAIA_CURATOR_TOKEN"

#: The stash file the curator's audit trail lands in, under the hub's home.
STASH_FILENAME = "stash.db"


@dataclass
class CuratorWiring:
    """Everything a wired-up curator consists of.

    The fields after ``stash_store`` are private wiring context, kept only
    so :meth:`add_vault` can build a *matching* runner/applier for a vault
    created after this curator was assembled — SPEC-301 deliverable #4,
    closing SPEC-206's documented "known limitation, deliberately
    fail-closed" gap (see :mod:`palaia_hub.curator.profile`'s docstring).
    """

    scheduler: CuratorScheduler
    runners: dict[str, CuratorRunner]
    appliers: dict[str, ProposalApplier]
    active_captures: ActiveCaptures
    profile_middleware: dict[str, list[Middleware]] = field(default_factory=dict)
    stash_store: StashStore | None = None
    _session_runner: SessionRunner | None = field(default=None, repr=False)
    _audit: CuratorAudit | None = field(default=None, repr=False)
    _endpoint: str = field(default="", repr=False)
    _token: str | None = field(default=None, repr=False)
    _max_attempts: int = field(default=3, repr=False)
    _auto_apply: bool = field(default=True, repr=False)
    _mounts: list[VaultMountConfig] = field(default_factory=list, repr=False)

    async def aclose(self) -> None:
        await self.scheduler.aclose()
        if self.stash_store is not None:
            self.stash_store.close()

    async def add_vault(self, engine: VaultEngine, mount: VaultMountConfig) -> None:
        """Wire a vault created at runtime into this curator, live.

        Called by the wizard's ``POST /api/vaults`` handler
        (:mod:`palaia_hub.dashboard_api`) right after the vault joins the
        gateway's curator profile. Builds a new :class:`CuratorRunner` (and,
        when ``auto_apply`` was on, a matching :class:`ProposalApplier`),
        registers both with the scheduler, and merges this vault's tool
        names into the curator profile's guard — the exact three things
        SPEC-206's profile module named as the gap ("its tools are absent
        from the curator's map ... the curator starts curating that
        vault's inbox after the next hub restart"). A no-op if this vault
        key is already known (idempotent against a retry).
        """
        if mount.key in self.runners:
            return
        if self._session_runner is None:
            raise RuntimeError(
                "CuratorWiring.add_vault called on a wiring with no session "
                "runner recorded — build it via curator.wiring.build_curator, "
                "which always sets one."
            )
        self._mounts.append(mount)
        allowed_tools = allowed_tool_specs(self._mounts)
        runner = CuratorRunner(
            engine,
            session_runner=self._session_runner,
            endpoint=self._endpoint,
            token=self._token,
            allowed_tools=allowed_tools,
            audit=self._audit,
            active_captures=self.active_captures,
            max_attempts=self._max_attempts,
            purpose=mount.purpose,
        )
        self.runners[mount.key] = runner
        applier: ProposalApplier | None = None
        if self._auto_apply:
            applier = ProposalApplier(engine, audit=self._audit)
            self.appliers[mount.key] = applier
        self.scheduler.add_vault(mount.key, runner, applier)
        for item in self.profile_middleware.get(CURATOR_PROFILE_PATH, []):
            if isinstance(item, CuratorScopeMiddleware):
                item.add_tool_actions(curator_tool_actions([mount]))


def curator_token(config: HubConfig) -> str | None:
    """The curator token: environment first, then ``config.yaml``."""
    return os.environ.get(TOKEN_ENV) or config.curator.token


def build_curator(
    config: HubConfig,
    engines: Mapping[str, VaultEngine],
    mounts: Sequence[VaultMountConfig],
    *,
    home: Path | None = None,
    publish: Publisher | None = None,
    session_runner: SessionRunner | None = None,
    with_stash: bool = True,
    stash_service: StashService | None = None,
    subscribe: SchedulerSubscribe | None = None,
) -> CuratorWiring:
    """Assemble runners, appliers, the scheduler and the profile guard.

    Args:
        config: the hub config (``curator:`` section).
        engines: the vaults to curate, ``{vault_key: opened engine}``.
        mounts: the same vaults' gateway mount configs — the guard needs
            them to know each vault's tool names.
        home: where the audit stash lives (the hub's data dir). Unused when
            ``stash_service`` is given.
        publish: the event sink (``publish(event, data)``); omitted, no
            events are emitted.
        session_runner: overrides how a session is launched. Tests pass a
            scripted runner; production leaves this alone and gets
            :class:`~palaia_hub.curator.session.SubprocessSessionRunner`
            built from ``config.curator.runner_command``.
        with_stash: open the audit stash. ``False`` keeps the whole wiring
            free of any file I/O beyond the vaults themselves. Ignored
            when ``stash_service`` is given.
        stash_service: use this stash instead of opening a new store — the
            hub's *one* stash (SPEC-301: ``build_production_app`` builds a
            single :class:`~palaia_hub.stash.service.StashService` for both
            the ``/mcp/stash`` tool family and the curator's own audit
            trail, so a client's ``stash_list`` and the curator's audit
            entries are the same store, not two SQLite connections racing
            each other on one file). The returned
            :class:`CuratorWiring`'s ``stash_store`` stays ``None`` in this
            case — ownership (who opens it, who closes it) stays with
            whoever built ``stash_service``, not with this function.
        subscribe: the event bus's ``on()``, so a capture wakes the curator
            (debounced). Omitted, the scheduler runs on its interval only —
            which is what the one-shot CLI wants.
    """
    settings = config.curator
    stash_store: StashStore | None = None
    if stash_service is None and with_stash:
        stash_store = StashStore(Path(home or Path.cwd()) / STASH_FILENAME)
        stash_service = StashService(stash_store)
    audit = CuratorAudit(publish=publish, stash=stash_service)

    runner = session_runner or SubprocessSessionRunner(
        command=list(settings.runner_command), timeout=settings.session_timeout
    )
    active_captures = ActiveCaptures()
    allowed_tools = allowed_tool_specs(mounts)
    endpoint = f"{config.curator_endpoint()}/mcp/{CURATOR_PROFILE_PATH}"
    token = curator_token(config)
    purposes = {mount.key: mount.purpose for mount in mounts}

    runners = {
        key: CuratorRunner(
            engine,
            session_runner=runner,
            endpoint=endpoint,
            token=token,
            allowed_tools=allowed_tools,
            audit=audit,
            active_captures=active_captures,
            max_attempts=settings.max_attempts,
            purpose=purposes.get(key, ""),
        )
        for key, engine in engines.items()
    }
    appliers = (
        {key: ProposalApplier(engine, audit=audit) for key, engine in engines.items()}
        if settings.auto_apply
        else {}
    )
    scheduler = CuratorScheduler(
        runners,
        appliers=appliers,
        debounce_seconds=settings.debounce_seconds,
        interval_seconds=settings.interval_seconds,
        subscribe=subscribe,
    )
    return CuratorWiring(
        scheduler=scheduler,
        runners=runners,
        appliers=appliers,
        active_captures=active_captures,
        profile_middleware=curator_profile_middleware(
            mounts, active_captures=active_captures
        ),
        stash_store=stash_store,
        _session_runner=runner,
        _audit=audit,
        _endpoint=endpoint,
        _token=token,
        _max_attempts=settings.max_attempts,
        _auto_apply=settings.auto_apply,
        _mounts=list(mounts),
    )


__all__ = [
    "STASH_FILENAME",
    "TOKEN_ENV",
    "CuratorWiring",
    "SchedulerSubscribe",
    "build_curator",
    "curator_token",
]
