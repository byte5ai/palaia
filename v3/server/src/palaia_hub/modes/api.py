"""REST surface for the exposure wizard (SPEC-205).

Mounted unconditionally by :func:`palaia_hub.app.create_app` (like
``/api/health``/``/api/info`` — every hub has an operating mode, so this
router needs no opt-in parameter). Every route is thin: it calls into
:mod:`palaia_hub.modes`'s own modules and serializes the answer, so the
*rules* live in ``policy.py``/``hardening.py``/``tunnel.py``/
``selftest.py`` and this module only wires them to HTTP.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ..admin_session import owner_account_exists
from ..config import HubConfig, config_file_path, load_config
from ..events import EventBus, publish_event
from .audit import ModeAuditLog
from .detect import detect_tunnels
from .hardening import build_checklist
from .patch import patch_config_values
from .policy import ModeChangeError, build_candidate_config
from .selftest import SelfTestResult, check_public_url
from .tunnel import cloudflared_guidance, tailscale_guidance

if TYPE_CHECKING:
    from ..oauth import OAuthStore

Mode = Literal["locked", "cloud", "open"]

#: Settings that require restarting the hub process to actually take
#: effect — everything the gateway/oauth wiring is built from once, at
#: startup (:func:`palaia_hub.app.create_app`/`palaia_hub.serve.
#: build_production_app`). ``exposure.public_url``/``exposure.tunnel`` are
#: deliberately not in this set: nothing reads them at wiring time, so a
#: change to either is live the moment it is saved.
_RESTART_SENSITIVE_FIELDS = ("mode", "host", "auth_enabled", "oauth.enabled", "oauth.issuer")


def _field(config: HubConfig, dotted: str) -> Any:
    if "." not in dotted:
        return getattr(config, dotted)
    section, key = dotted.split(".", 1)
    return getattr(getattr(config, section), key)


def _restart_required(active: HubConfig, configured: HubConfig) -> bool:
    return any(_field(active, f) != _field(configured, f) for f in _RESTART_SENSITIVE_FIELDS)


class ModeStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_mode: Mode
    configured_mode: Mode
    restart_required: bool
    host: str
    auth_enabled: bool
    oauth_enabled: bool
    oauth_issuer: str | None
    public_url: str | None
    tunnel: str | None


class ModeChangeRequest(BaseModel):
    """The wizard's "change mode" step. Every field is optional — send only
    what you are changing; omitted fields keep their current value."""

    model_config = ConfigDict(extra="forbid")

    mode: Mode | None = None
    host: str | None = None
    auth_enabled: bool | None = None
    oauth_enabled: bool | None = None
    oauth_issuer: str | None = None
    public_url: str | None = None
    tunnel: Literal["tailscale", "cloudflared", "reverse_proxy"] | None = None


def _dotted_updates(body: ModeChangeRequest) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if body.mode is not None:
        updates["mode"] = body.mode
    if body.host is not None:
        updates["host"] = body.host
    if body.auth_enabled is not None:
        updates["auth_enabled"] = body.auth_enabled
    if body.oauth_enabled is not None:
        updates["oauth.enabled"] = body.oauth_enabled
    if body.oauth_issuer is not None:
        updates["oauth.issuer"] = body.oauth_issuer
    if body.public_url is not None:
        updates["exposure.public_url"] = body.public_url
    if body.tunnel is not None:
        updates["exposure.tunnel"] = body.tunnel
    return updates


def _sign_in_configured(
    candidate: HubConfig, *, home: Path, oauth_store: OAuthStore | None
) -> bool:
    """Does ``candidate`` describe a hub the owner can actually sign in to?

    The same three-part question :func:`palaia_hub.admin_session.
    sign_in_configured` asks — a sign-in server with an address, and either a
    provider or an owner account — answered against the live store when this
    router was given one (the authoritative source, and the one the running
    hub itself reads), falling back to the read-only on-disk probe otherwise.
    """
    if not candidate.oauth.enabled or not candidate.oauth.issuer:
        return False
    if candidate.oauth.idp is not None:
        return True
    if oauth_store is not None:
        return oauth_store.get_owner() is not None
    return owner_account_exists(home)


def _nested_overrides(updates: dict[str, Any]) -> dict[str, Any]:
    """Turn dotted ``updates`` into the nested dict :func:`build_candidate_config` expects."""
    nested: dict[str, Any] = {}
    for dotted, value in updates.items():
        if "." in dotted:
            section, key = dotted.split(".", 1)
            nested.setdefault(section, {})[key] = value
        else:
            nested[dotted] = value
    return nested


def _status(active: HubConfig, configured: HubConfig) -> ModeStatusOut:
    return ModeStatusOut(
        active_mode=active.mode,
        configured_mode=configured.mode,
        restart_required=_restart_required(active, configured),
        host=configured.host,
        auth_enabled=configured.auth_enabled,
        oauth_enabled=configured.oauth.enabled,
        oauth_issuer=configured.oauth.issuer,
        public_url=configured.exposure.public_url,
        tunnel=configured.exposure.tunnel,
    )


class TunnelGuidanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    config: str
    commands: list[str]
    note: str


class TunnelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["tailscale", "cloudflared"]
    local_port: int | None = None
    hostname: str | None = None


class SelfTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_url: str


class SelfTestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_url: str
    reachable: bool
    status_code: int | None
    latency_ms: float | None
    error: str


class DetectionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tailscale: bool
    cloudflared: bool


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    detail: str
    auto: bool
    passed: bool | None


class ExposureOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ModeStatusOut
    detected: DetectionOut
    checklist: list[ChecklistItemOut]


def build_modes_router(
    config: HubConfig,
    *,
    home: Path,
    event_bus: EventBus | None = None,
    audit_log: ModeAuditLog | None = None,
    oauth_store: OAuthStore | None = None,
) -> APIRouter:
    """Build the exposure-wizard router.

    Args:
        config: the live, running configuration (what this process was
            actually built from). Never mutated — a mode change is written
            to ``config.yaml`` and takes effect on the next restart; the
            response says so via ``restart_required`` rather than
            pretending the running process reconfigured itself live.
        home: the hub's home directory — where ``config.yaml`` and the
            mode-change audit log live.
        event_bus: publishes ``hub.mode_changed`` on a successful change
            when given. Omitted, changes are still validated, persisted
            and audited, just not announced on the bus.
        audit_log: defaults to :class:`~palaia_hub.modes.audit.ModeAuditLog`
            at ``home`` when omitted.
        oauth_store: backs the hardening checklist's "owner account
            configured" item with a real answer; omitted, that item is
            rendered as manual (the router has no way to check).
    """
    audit = audit_log or ModeAuditLog(home)
    path = config_file_path(home)
    rate_limiting_active = config.mode in ("cloud", "open")

    router = APIRouter(tags=["modes"])

    def _configured() -> HubConfig:
        return load_config(home=home)

    @router.get("/api/mode", response_model=ModeStatusOut)
    async def get_mode() -> ModeStatusOut:
        return _status(config, _configured())

    @router.post("/api/mode", response_model=ModeStatusOut)
    async def post_mode(body: ModeChangeRequest) -> ModeStatusOut:
        current = _configured()
        updates = _dotted_updates(body)
        target_mode = body.mode or current.mode
        try:
            candidate = build_candidate_config(current, _nested_overrides(updates))
            # Issue #242 / SPEC-401 deliverable #5: `open` puts this
            # dashboard on the public internet, so it is accepted only once
            # there is a way to sign in to it. Checked against the
            # *candidate* (the operator may be turning the sign-in server on
            # in the same call) and refused before anything is written, so
            # the wizard says why instead of leaving a config.yaml the hub
            # would refuse to load on its next start. Same rule as
            # `load_config`, in plain language for the person in the
            # dashboard.
            if candidate.mode == "open" and not _sign_in_configured(
                candidate, home=home, oauth_store=oauth_store
            ):
                raise ModeChangeError(
                    "Fully public also needs a way for you to sign in to this "
                    "dashboard — it would otherwise be reachable from the "
                    "internet by anyone. Fix: set your own password (the "
                    "dashboard's first-run setup, or `palaia-hub oauth set-password`) "
                    "or connect a sign-in "
                    "provider, and turn the sign-in server on with a public "
                    "address for it; then choose fully public again."
                )
        except ModeChangeError as exc:
            audit.record(
                from_mode=current.mode,
                to_mode=target_mode,
                accepted=False,
                reason=str(exc),
                changed_keys=tuple(updates),
            )
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        patch_config_values(path, updates)
        audit.record(
            from_mode=current.mode,
            to_mode=candidate.mode,
            accepted=True,
            changed_keys=tuple(updates),
        )
        status = _status(config, candidate)
        if event_bus is not None:
            publish_event(
                event_bus,
                "hub.mode_changed",
                origin="hub",
                data={
                    "from_mode": current.mode,
                    "to_mode": candidate.mode,
                    "restart_required": status.restart_required,
                    "changed_keys": list(updates),
                },
            )
        return status

    @router.get("/api/exposure", response_model=ExposureOut)
    async def get_exposure() -> ExposureOut:
        configured = _configured()
        detection = detect_tunnels()
        owner_configured = None if oauth_store is None else oauth_store.get_owner() is not None
        checklist = build_checklist(
            configured,
            rate_limiting_active=rate_limiting_active,
            owner_account_configured=owner_configured,
        )
        return ExposureOut(
            status=_status(config, configured),
            detected=DetectionOut(tailscale=detection.tailscale, cloudflared=detection.cloudflared),
            checklist=[
                ChecklistItemOut(
                    id=item.id,
                    title=item.title,
                    detail=item.detail,
                    auto=item.auto,
                    passed=item.passed,
                )
                for item in checklist
            ],
        )

    @router.post("/api/exposure/tunnel", response_model=TunnelGuidanceOut)
    async def post_tunnel_guidance(body: TunnelRequest) -> TunnelGuidanceOut:
        configured = _configured()
        tunnel_mode: Literal["cloud", "open"] = "open" if configured.mode == "open" else "cloud"
        port = body.local_port or configured.port
        if body.kind == "tailscale":
            guidance = tailscale_guidance(
                mode=tunnel_mode, local_port=port, hostname=body.hostname or "<your-tailnet-name>"
            )
        else:
            guidance = cloudflared_guidance(
                mode=tunnel_mode, local_port=port, hostname=body.hostname or "hub.example.com"
            )
        return TunnelGuidanceOut(
            label=guidance.label,
            config=guidance.config,
            commands=list(guidance.commands),
            note=guidance.note,
        )

    @router.post("/api/exposure/selftest", response_model=SelfTestOut)
    async def post_selftest(body: SelfTestRequest) -> SelfTestOut:
        result: SelfTestResult = await check_public_url(body.public_url)
        return SelfTestOut(
            checked_url=result.checked_url,
            reachable=result.reachable,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            error=result.error,
        )

    return router


__all__ = ["ModeChangeRequest", "ModeStatusOut", "build_modes_router"]
