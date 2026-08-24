"""One helper that wires a real curator over a real vault, for the tests.

Same pieces production uses (:mod:`palaia_hub.curator.wiring` builds the same
graph): a vault engine, the gateway's curator profile with its middleware, and
a runner whose sessions are scripted instead of modelled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP
from scripted import Script, ScriptedSessionRunner

from palaia_hub.curator.audit import CuratorAudit
from palaia_hub.curator.models import CaptureRecord, CuratorRunReport
from palaia_hub.curator.policy import ActiveCaptures
from palaia_hub.curator.profile import (
    CURATOR_PROFILE_PATH,
    curator_profile,
    curator_profile_middleware,
)
from palaia_hub.curator.runner import CuratorRunner
from palaia_hub.gateway.build import build_gateway
from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.wiring import EngineVaultService
from palaia_hub.vault import VaultEngine


@dataclass
class RecordingStash:
    """A stash stand-in that just remembers what was written."""

    entries: dict[tuple[str, str], Any] = field(default_factory=dict)

    async def set(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None = None,
        stale_after_seconds: float | None = None,
    ) -> None:
        self.entries[(namespace, key)] = value


@dataclass
class CuratorHarness:
    engine: VaultEngine
    mount: VaultMountConfig
    service: EngineVaultService
    profile: FastMCP
    active_captures: ActiveCaptures
    session_runner: ScriptedSessionRunner
    runner: CuratorRunner
    events: list[tuple[str, dict[str, Any]]]
    stash: RecordingStash

    @property
    def namespace(self) -> str:
        return self.mount.namespace

    async def capture(
        self, *, what_it_concerns: str, why_keep: str, content: str
    ) -> str:
        """Drop a real capture into ``inbox/`` and return its capture_id."""
        result = await self.service.capture(
            what_it_concerns=what_it_concerns, why_keep=why_keep, content=content
        )
        return result.capture_id

    async def run_once(self) -> CuratorRunReport:
        return await self.runner.run_once()

    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]

    def records(self, report: CuratorRunReport) -> list[CaptureRecord]:
        return list(report.records)


def build_harness(
    engine: VaultEngine,
    mount: VaultMountConfig,
    script: Script,
    *,
    stdout: str = "",
    exit_code: int = 0,
    max_attempts: int = 3,
) -> CuratorHarness:
    service = EngineVaultService(engine)
    active_captures = ActiveCaptures()
    middleware = curator_profile_middleware([mount], active_captures=active_captures)
    gateway = build_gateway(
        GatewayConfig(vaults=[mount], profiles=[curator_profile([mount.key])]),
        {mount.key: service},
        profile_middleware=middleware,
    )
    profile = gateway.profile_servers[CURATOR_PROFILE_PATH]
    session_runner = ScriptedSessionRunner(
        server=profile, script=script, stdout=stdout, exit_code=exit_code
    )
    events: list[tuple[str, dict[str, Any]]] = []
    stash = RecordingStash()
    audit = CuratorAudit(
        publish=lambda event, data: events.append((event, data)), stash=stash
    )
    runner = CuratorRunner(
        engine,
        session_runner=session_runner,
        endpoint="http://testserver/mcp/curator",
        token="plt_test",
        allowed_tools=(),
        audit=audit,
        active_captures=active_captures,
        max_attempts=max_attempts,
        purpose=mount.purpose,
    )
    return CuratorHarness(
        engine=engine,
        mount=mount,
        service=service,
        profile=profile,
        active_captures=active_captures,
        session_runner=session_runner,
        runner=runner,
        events=events,
        stash=stash,
    )
