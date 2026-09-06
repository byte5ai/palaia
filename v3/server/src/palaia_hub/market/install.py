"""Install flows for marketplace entries (SPEC-304 deliverables #1/#3/#4).

Every install lands in *existing* machinery rather than reinventing it: a
successful plan is exactly one :class:`~palaia_hub.upstream.models.
UpstreamConfig`, handed to the same
:meth:`~palaia_hub.gateway.dynamic.DynamicGateway.register_upstream` /
:meth:`~palaia_hub.upstream.service.UpstreamService.register` /
``config.yaml`` write-back sequence SPEC-302's own
``POST /api/gateway/upstreams`` uses (see
:mod:`palaia_hub.gateway.settings_bridge`'s ``snapshot_gateway_settings``,
shared by both). This module's only real job is *resolving* that config
from a marketplace entry's ``kind``/``source``/``config_schema`` — plus the
consent gate deliverable #3 requires, and the small amount of bookkeeping
(:mod:`palaia_hub.market.installed_store`) the update surface needs.

**The four install shapes** (deliverable #1):

- ``remote`` with ``source.type == "url"`` — a straight ``http`` upstream.
- ``remote`` with ``source.type == "registry_ref"`` — the official
  registry's ``server.json`` for that id is fetched (never cached from the
  merged entry, which never carries ``remotes``/``packages`` — see
  :mod:`palaia_hub.market.service`); a ``remotes[]`` entry there resolves to
  ``http`` the same as above, otherwise its first ``packages[]`` entry (an
  npm/pypi/nuget package — the "stdio command entries" the SPEC names) is
  resolved to a ``stdio`` upstream running ``npx``/``uvx``/``dnx``. Any
  other package kind is refused with a plain-language reason rather than a
  guess.
- ``container`` — the declared image is pulled, then run as ``docker run
  --rm -i`` and connected as a ``stdio`` upstream (see
  :mod:`palaia_hub.market.docker_runtime` for why this is also how
  restart-on-crash and "no leftover container" both fall out for free).
- ``skill`` / ``mcpb`` / ``plugin`` — refused here, by design: "the
  marketplace lists them, it does not reinvent their delivery" (the SPEC's
  own words). The dashboard hides the install button for these kinds and
  offers the connect page instead.

**Config fields → env / mounts / secrets.** A ``config_schema`` property is
one of three things, from its own JSON Schema keywords (deliverable #2's
fixed subset): ``"type": "secret"`` writes the submitted value into the
secret store, named ``market.<entry id>.<field>``, and is never handed
back — decrypted only at connect/spawn time, exactly like every other
upstream secret (:mod:`palaia_hub.upstream.secrets`'s never-return-values
rule, unchanged, reused). A string property with ``"format": "path"`` is a
declared filesystem mount (container installs only) — bind-mounted
read-write at the same absolute path inside the container. Everything else
becomes a plain environment variable / header, named by the field's own
key, upper-cased.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets as secrets_module
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import HubConfig, config_file_path
from ..events import EventBus
from ..events.schema import Envelope
from ..gateway.build import GatewayConfigError
from ..gateway.config import CURATOR_PROFILE_PATH
from ..gateway.dynamic import DynamicGateway
from ..gateway.settings_bridge import persist_gateway_settings, snapshot_gateway_settings
from ..registry.client import RegistryOfflineError
from ..upstream.models import UpstreamAuthConfig, UpstreamConfig, UpstreamConflictError
from ..upstream.secrets import SecretStore, SecretStoreError
from ..upstream.service import UpstreamNotConfiguredError, UpstreamService
from . import docker_runtime
from .curated import CuratedIndexResult
from .installed_store import InstalledAddonRecord, InstalledAddonStore
from .models import EntryKind, MarketEntry
from .service import MarketService

logger = logging.getLogger("palaia_hub.market.install")

#: How long a consent token lives before it must be re-issued (deliverable
#: #3): long enough to fill in a config form, short enough that a leaked
#: token (e.g. in a shared screen recording) is not useful for long.
CONSENT_TTL_SECONDS = 600.0

_KIND_LABELS: dict[str, str] = {
    "skill": "a skill",
    "mcpb": "a downloadable bundle",
    "plugin": "a plugin",
}


class MarketInstallError(RuntimeError):
    """An install/update/consent request cannot be honored.

    The message is plain language, safe to return to the dashboard
    verbatim — it never interpolates a secret value (every place a secret
    could appear instead names the secret by field/name only, the same
    rule :mod:`palaia_hub.upstream.secrets` already holds to).
    """


# --------------------------------------------------------------- consent


@dataclass
class _ConsentEntry:
    entry_id: str
    expires_at: float
    #: Issue #349: the hash of what the owner was shown — command, address
    #: or image. The install re-derives it and refuses a mismatch.
    plan_hash: str = ""
    used: bool = False


class ConsentStore:
    """Short-lived, single-use consent tokens (deliverable #3).

    The dashboard's consent screen itself is just ``GET
    /api/market/entry/{id}`` (already carries kind/source/verified/
    permissions) rendered with a confirm button; this store is what makes
    skipping that screen structurally impossible rather than a UI
    convention — ``install`` refuses without a token this store issued
    for the *same* entry, unused, unexpired.
    """

    def __init__(self, *, ttl_seconds: float = CONSENT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._tokens: dict[str, _ConsentEntry] = {}

    def issue(self, entry_id: str, *, plan_hash: str = "") -> tuple[str, float]:
        token = secrets_module.token_urlsafe(24)
        expires_at = time.time() + self._ttl
        self._tokens[token] = _ConsentEntry(
            entry_id=entry_id, expires_at=expires_at, plan_hash=plan_hash
        )
        return token, expires_at

    def consume(self, token: str, entry_id: str) -> str:
        """Raise :class:`MarketInstallError` unless ``token`` was issued for
        ``entry_id``, is unused and unexpired — then mark it used and return
        the plan hash it was bound to (issue #349)."""
        entry = self._tokens.pop(token, None)
        if (
            entry is None
            or entry.used
            or entry.expires_at < time.time()
            or entry.entry_id != entry_id
        ):
            raise MarketInstallError(
                "This install link is missing, already used, expired, or was "
                "issued for a different entry. Fix: open the entry again and "
                "confirm the consent screen before installing."
            )
        return entry.plan_hash


# ----------------------------------------------------------- config split


def _secret_name(entry_id: str, field_name: str) -> str:
    slug = entry_id.replace(".", "_").replace("/", "_")
    return f"market.{slug}.{field_name}"


def _split_config(
    config_schema: dict[str, Any] | None, config: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Split submitted ``config`` values into ``(plain, secret, mounts)`` —
    each ``{field name: string value}`` — per the module docstring's
    "config fields → env / mounts / secrets" rule. A field absent from
    ``config_schema`` (or with no schema at all) is treated as plain."""
    properties = (config_schema or {}).get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    mounts: dict[str, str] = {}
    for key, value in config.items():
        prop = properties.get(key, {})
        raw = "" if value is None else str(value)
        if isinstance(prop, dict) and prop.get("type") == "secret":
            secret[key] = raw
        elif isinstance(prop, dict) and prop.get("format") == "path":
            mounts[key] = raw
        else:
            plain[key] = raw
    return plain, secret, mounts


# -------------------------------------------------------------- planning


@dataclass(frozen=True, slots=True)
class InstallPlan:
    """What :func:`_build_plan` resolved: the upstream to connect, plus the
    bookkeeping :class:`~palaia_hub.market.installed_store.
    InstalledAddonRecord` needs that an :class:`UpstreamConfig` alone
    cannot carry."""

    upstream: UpstreamConfig
    image: str | None = None
    container_name: str | None = None
    #: A container's resolved mounts and plain environment (issue #344) —
    #: persisted on the install record so an update can rebuild the exact
    #: ``docker run`` with a new image.
    mounts: dict[str, str] = field(default_factory=dict)
    plain_env: dict[str, str] = field(default_factory=dict)


def _resolve_stdio_command(package: dict[str, Any]) -> tuple[str, list[str]]:
    """The command line for one official-registry package entry.

    Only npm (``npx``), pypi (``uvx``) and nuget (``dnx``) packages are
    resolved — every other ``registry_type``/``runtime_hint`` combination
    is refused with a plain reason (deliverable #1's "stdio command
    entries") rather than guessed at.
    """
    registry_type = str(package.get("registry_type", "")).lower()
    identifier = str(package.get("identifier", ""))
    version = package.get("version")
    ref = f"{identifier}@{version}" if version else identifier
    runtime_hint = str(package.get("runtime_hint", "")).lower()
    if not runtime_hint:
        runtime_hint = {"npm": "npx", "pypi": "uvx", "nuget": "dnx"}.get(registry_type, "")
    if runtime_hint not in ("npx", "uvx", "dnx") or not identifier:
        label = registry_type or "this"
        raise MarketInstallError(
            f"palaia does not know how to run a {label!r} package yet — only npm "
            "(npx), pypi (uvx) and nuget (dnx) packages install automatically."
        )
    if identifier.startswith("-") or ref.startswith("-") or any(c.isspace() for c in ref):
        # Registry content is unverified: a "package name" of `--flag` would
        # become an option to the package runner, not a package (issue #349).
        raise MarketInstallError(
            f"the registry lists {identifier!r} as the package to run, which is not a "
            f"package name {runtime_hint} would accept. Fix: this listing cannot be "
            "installed automatically; add the server by hand if you trust it."
        )
    base_args = ["-y", ref] if runtime_hint == "npx" else [ref]
    extra_args = [
        str(arg.get("value"))
        for arg in (package.get("package_arguments") or [])
        if isinstance(arg, dict) and arg.get("value")
    ]
    return runtime_hint, [*base_args, *extra_args]


@dataclass(frozen=True, slots=True)
class _RegistryTarget:
    """What a ``registry_ref`` resolves to: a remote address, or a command."""

    url: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()


async def _resolve_registry_target(
    entry: MarketEntry, *, market_service: MarketService
) -> _RegistryTarget:
    """Fetch the registry's ``server.json`` and derive what would run.

    Shared by the consent preview and the install itself (issue #349), so
    what the owner is shown is derived by the very code that installs it.
    """
    registry_id = entry.source.value
    try:
        server = await market_service.registry_client.detail(registry_id)
    except RegistryOfflineError as exc:
        raise MarketInstallError(
            f"could not reach the registry to resolve {registry_id!r}: {exc}"
        ) from exc
    if server is None:
        raise MarketInstallError(f"the registry no longer lists {registry_id!r}.")
    raw = server.raw.get("server", server.raw)
    remotes = raw.get("remotes") or []
    if remotes:
        url = str(remotes[0].get("url", ""))
        if not url:
            raise MarketInstallError(f"{entry.name!r}'s registry listing has no usable address.")
        return _RegistryTarget(url=url)

    packages = raw.get("packages") or []
    if not packages:
        raise MarketInstallError(
            f"{entry.name!r} declares neither a remote address nor a runnable "
            "package — palaia does not know how to install it yet."
        )
    command, args = _resolve_stdio_command(packages[0])
    return _RegistryTarget(command=command, args=tuple(args))


async def _resolve_registry_ref_plan(
    entry: MarketEntry,
    config: dict[str, Any],
    *,
    key: str,
    display_name: str,
    market_service: MarketService,
    secret_store: SecretStore,
) -> InstallPlan:
    target = await _resolve_registry_target(entry, market_service=market_service)
    if target.url is not None:
        return _build_http_plan(
            entry,
            config,
            key=key,
            display_name=display_name,
            url=target.url,
            secret_store=secret_store,
        )
    command, args = target.command or "", list(target.args)
    plain, secret_values, _mounts = _split_config(entry.config_schema, config)
    env = {k.upper(): v for k, v in plain.items()}
    env_secrets: dict[str, str] = {}
    for field_name, value in secret_values.items():
        name = _secret_name(entry.id, field_name)
        secret_store.put(name, value)
        env_secrets[field_name.upper()] = name
    upstream = UpstreamConfig(
        key=key,
        kind="stdio",
        display_name=display_name,
        command=command,
        args=args,
        env=env,
        env_secrets=env_secrets,
    )
    return InstallPlan(upstream=upstream)


def _build_http_plan(
    entry: MarketEntry,
    config: dict[str, Any],
    *,
    key: str,
    display_name: str,
    url: str,
    secret_store: SecretStore,
) -> InstallPlan:
    plain, secret_values, _mounts = _split_config(entry.config_schema, config)
    headers = {k.upper(): v for k, v in plain.items()}
    auth: UpstreamAuthConfig | None = None
    if secret_values:
        # The first declared secret field is the bearer/API-key token — the
        # overwhelmingly common case for a `remote` entry's `config_schema`
        # (one credential). Any *additional* secret field still gets stored
        # (never lost), just not wired into `auth` — a `remote` upstream has
        # exactly one auth slot (`UpstreamAuthConfig`); a second credential
        # is a shape this SPEC's fixed config_schema subset does not
        # anticipate, and silently dropping it would be worse than storing
        # it unused.
        first_field = next(iter(secret_values))
        for field_name, value in secret_values.items():
            secret_store.put(_secret_name(entry.id, field_name), value)
        auth = UpstreamAuthConfig(secret_name=_secret_name(entry.id, first_field))
    upstream = UpstreamConfig(
        key=key,
        kind="http",
        display_name=display_name,
        url=url,
        headers=headers,
        auth=auth,
    )
    return InstallPlan(upstream=upstream)


async def _resolve_container_plan(
    entry: MarketEntry,
    config: dict[str, Any],
    *,
    key: str,
    display_name: str,
    secret_store: SecretStore,
) -> InstallPlan:
    image = entry.source.value
    if not image:
        raise MarketInstallError(f"{entry.name!r} has no image declared to install.")
    await docker_runtime.ensure_image(image)
    plain, secret_values, mounts = _split_config(entry.config_schema, config)
    env = {k.upper(): v for k, v in plain.items()}
    env_secrets: dict[str, str] = {}
    for field_name, value in secret_values.items():
        name = _secret_name(entry.id, field_name)
        secret_store.put(name, value)
        env_secrets[field_name.upper()] = name
    container_name = _container_name(key)
    run_args = docker_runtime.build_stdio_run_args(
        image,
        container_name=container_name,
        mounts=mounts,
        plain_env=env,
        secret_env_vars=list(env_secrets.keys()),
        permissions=entry.permissions,
    )
    upstream = UpstreamConfig(
        key=key,
        kind="stdio",
        display_name=display_name,
        command=run_args.command,
        args=run_args.args,
        env={},
        env_secrets=env_secrets,
    )
    return InstallPlan(
        upstream=upstream,
        image=image,
        container_name=container_name,
        mounts=mounts,
        plain_env=env,
    )


def _container_name(key: str) -> str:
    return f"palaia-addon-{key}"


def _plan_from_run_args(
    args: Sequence[str], *, secret_env_vars: Iterable[str]
) -> tuple[dict[str, str], dict[str, str]]:
    """Recover ``(mounts, plain_env)`` from a ``docker run`` argv this hub built.

    For install records written before the plan was persisted (issue #344):
    :func:`~palaia_hub.market.docker_runtime.build_stdio_run_args` emits
    ``-v host:host`` per mount and ``-e KEY=value`` per plain variable
    (``-e KEY`` alone is a secret, injected at start and never stored).
    """
    secrets = set(secret_env_vars)
    mounts: dict[str, str] = {}
    plain: dict[str, str] = {}
    index = 0
    while index < len(args) - 1:
        flag, value = args[index], args[index + 1]
        if flag == "-v":
            host_path = value.split(":", 1)[0]
            if host_path:
                mounts[host_path] = host_path
            index += 2
            continue
        if flag == "-e":
            key, separator, plain_value = value.partition("=")
            if separator and key not in secrets:
                plain[key] = plain_value
            index += 2
            continue
        index += 1
    return mounts, plain


async def _build_plan(
    entry: MarketEntry,
    config: dict[str, Any],
    *,
    key: str,
    display_name: str,
    market_service: MarketService,
    secret_store: SecretStore,
) -> InstallPlan:
    if entry.kind == "remote":
        if entry.source.type == "url":
            return _build_http_plan(
                entry,
                config,
                key=key,
                display_name=display_name,
                url=entry.source.value,
                secret_store=secret_store,
            )
        if entry.source.type == "registry_ref":
            return await _resolve_registry_ref_plan(
                entry,
                config,
                key=key,
                display_name=display_name,
                market_service=market_service,
                secret_store=secret_store,
            )
        raise MarketInstallError(
            f"a 'remote' entry cannot install from a {entry.source.type!r} source."
        )
    if entry.kind == "container":
        return await _resolve_container_plan(
            entry,
            config,
            key=key,
            display_name=display_name,
            secret_store=secret_store,
        )
    label = _KIND_LABELS.get(entry.kind, entry.kind)
    raise MarketInstallError(
        f"{entry.name!r} is {label} — install it from the connect page instead; "
        "the marketplace only lists it here."
    )


def _derive_upstream_key(entry_id: str) -> str:
    lowered = entry_id.lower()
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in lowered)
    cleaned = cleaned.strip("-_") or "addon"
    if not (cleaned[0].isalnum()):
        cleaned = f"a{cleaned}"
    return cleaned[:64]


# ------------------------------------------------------------------- REST


class PlanPreview(BaseModel):
    """What installing an entry would actually run or connect to (issue #349).

    ``GET /api/market/entry/{id}/plan`` renders it on the consent screen;
    the consent token is bound to ``plan_hash``, and the install re-derives
    the same hash from the plan it built — a registry listing that changed
    between the two is refused rather than run.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stdio", "http", "container"]
    #: For ``stdio``: the exact executable and arguments, e.g. ``npx`` and
    #: ``["-y", "@acme/tool@1.2.0"]``.
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    #: For ``http``: the address the hub will connect to.
    url: str | None = None
    #: For ``container``: the image that will be pulled and run.
    image: str | None = None
    plan_hash: str


def _plan_hash(
    kind: str, *, command: str | None, args: Sequence[str], url: str | None, image: str | None
) -> str:
    canonical = json.dumps(
        {"kind": kind, "command": command, "args": list(args), "url": url, "image": image},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _preview(kind: str, **fields: Any) -> PlanPreview:
    command = fields.get("command")
    args = list(fields.get("args") or [])
    url = fields.get("url")
    image = fields.get("image")
    return PlanPreview(
        kind=kind,  # type: ignore[arg-type]
        command=command,
        args=args,
        url=url,
        image=image,
        plan_hash=_plan_hash(kind, command=command, args=args, url=url, image=image),
    )


def _plan_identity(plan: InstallPlan) -> str:
    """The hash of what ``plan`` runs — the same function the preview used."""
    if plan.image is not None:
        return _plan_hash("container", command=None, args=(), url=None, image=plan.image)
    upstream = plan.upstream
    if upstream.kind == "stdio":
        return _plan_hash(
            "stdio", command=upstream.command, args=upstream.args, url=None, image=None
        )
    return _plan_hash("http", command=None, args=(), url=upstream.url, image=None)


class ConsentTokenOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str
    expires_at: float
    #: Issue #349: what this token consents to — shown once more to the
    #: owner, and the thing the install must still match.
    preview: PlanPreview


class InstallRequest(BaseModel):
    """``POST /api/market/entry/{id}/install`` — the consent token proves
    the consent screen (deliverable #3) was actually shown; without a valid
    one this endpoint always refuses (see :class:`ConsentStore`)."""

    model_config = ConfigDict(extra="forbid")

    consent_token: str
    config: dict[str, Any] = Field(default_factory=dict)
    profiles: list[str] = Field(default_factory=list)
    display_name: str | None = None


class InstalledAddonOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream_key: str
    entry_id: str
    name: str
    kind: EntryKind
    provenance: str
    installed_ref: str
    current_ref: str | None
    update_available: bool
    up: bool
    status: str
    profiles: list[str]
    installed_at: float


class InstallService:
    """Ties entry resolution to the existing upstream/gateway machinery.

    Args:
        market_service: where an entry (and, for a ``registry_ref``, the
            official registry's raw ``server.json``) comes from.
        dynamic_gateway: the live gateway an install connects to and a
            profile is mounted on — the exact same instance SPEC-302's
            ``/api/gateway/upstreams`` router uses.
        upstream_service: the registry/health side of the same servers.
        secret_store: where a ``config_schema`` ``secret`` field's value
            goes. ``None`` refuses any entry whose config declares one.
        home: where ``config.yaml`` lives, for the write-back.
        config: the running :class:`~palaia_hub.config.HubConfig` (read
            only, for its ``gateway.vaults`` identity overrides — see
            :func:`~palaia_hub.gateway.settings_bridge.
            snapshot_gateway_settings`).
        installed_store: persisted install records backing the update
            surface and ``GET /api/market/installed``.
        publish: optional ``(event, data)`` sink for ``addon.*`` events.
    """

    def __init__(
        self,
        *,
        market_service: MarketService,
        dynamic_gateway: DynamicGateway,
        upstream_service: UpstreamService,
        secret_store: SecretStore,
        home: Path,
        config: HubConfig,
        installed_store: InstalledAddonStore | None = None,
        publish: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.market_service = market_service
        self.dynamic_gateway = dynamic_gateway
        self.upstream_service = upstream_service
        self.secret_store = secret_store
        self.config_path = config_file_path(home)
        self.config = config
        self.installed_store = installed_store or InstalledAddonStore(
            home / "market_installed.json"
        )
        self.consent = ConsentStore()
        self._publish = publish or (lambda event, data: None)

    # ---------------------------------------------------------- consent

    async def _preview_for(self, entry: MarketEntry) -> PlanPreview:
        """What installing ``entry`` would run — without installing, pulling
        or storing anything (issue #349)."""
        if entry.kind == "remote" and entry.source.type == "url":
            return _preview("http", url=entry.source.value)
        if entry.kind == "remote" and entry.source.type == "registry_ref":
            target = await _resolve_registry_target(entry, market_service=self.market_service)
            if target.url is not None:
                return _preview("http", url=target.url)
            return _preview("stdio", command=target.command, args=target.args)
        if entry.kind == "container":
            if not entry.source.value:
                raise MarketInstallError(f"{entry.name!r} has no image declared to install.")
            return _preview("container", image=entry.source.value)
        if entry.kind == "remote":
            raise MarketInstallError(
                f"a 'remote' entry cannot install from a {entry.source.type!r} source."
            )
        label = _KIND_LABELS.get(entry.kind, entry.kind)
        raise MarketInstallError(
            f"{entry.name!r} is {label} — install it from the connect page instead; "
            "the marketplace only lists it here."
        )

    async def preview(self, entry_id: str) -> PlanPreview:
        entry = await self.market_service.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no marketplace entry {entry_id!r}")
        try:
            return await self._preview_for(entry)
        except MarketInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def issue_consent(self, entry_id: str) -> ConsentTokenOut:
        preview = await self.preview(entry_id)
        token, expires_at = self.consent.issue(entry_id, plan_hash=preview.plan_hash)
        return ConsentTokenOut(token=token, expires_at=expires_at, preview=preview)

    # ---------------------------------------------------------- install

    async def install(self, entry_id: str, request: InstallRequest) -> InstalledAddonOut:
        entry = await self.market_service.get_entry(entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no marketplace entry {entry_id!r}")
        try:
            consented_hash = self.consent.consume(request.consent_token, entry_id)
        except MarketInstallError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        key = _derive_upstream_key(entry_id)
        if key in self.upstream_service.configs:
            raise HTTPException(
                status_code=400,
                detail=f"{entry.name!r} is already installed. Uninstall it first, or update it.",
            )
        display_name = request.display_name or entry.name
        # Issue #351: a bad profile path used to surface only after the
        # upstream was registered, leaving an orphan behind. Check first.
        self._check_profiles(request.profiles)

        try:
            plan = await _build_plan(
                entry,
                request.config,
                key=key,
                display_name=display_name,
                market_service=self.market_service,
                secret_store=self.secret_store,
            )
        except (MarketInstallError, docker_runtime.DockerError, SecretStoreError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if _plan_identity(plan) != consented_hash:
            # Issue #349: the registry (or the entry) now says something
            # else than what the owner reviewed and consented to.
            raise HTTPException(
                status_code=409,
                detail=f"what {entry.name!r} would install changed since you reviewed it. "
                "Fix: open the entry again, read the consent screen, and confirm again.",
            )

        try:
            await self.dynamic_gateway.register_upstream(plan.upstream)
        except (UpstreamConflictError, ValidationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            await self.upstream_service.register(plan.upstream)
            await self._mount_on(key, request.profiles)
            await self.dynamic_gateway.refresh_upstreams([key])
            self._persist()
        except BaseException as exc:
            # Issue #351: nothing about this install has been persisted yet,
            # so nothing about it may stay in memory either — otherwise a
            # retry answers "already installed" for an add-on the installed
            # list does not show.
            await self._forget_registration(key)
            if isinstance(exc, GatewayConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

        record = InstalledAddonRecord(
            upstream_key=key,
            entry_id=entry_id,
            name=entry.name,
            kind=entry.kind,
            provenance=entry.provenance,
            installed_ref=entry.source.value,
            image=plan.image,
            container_name=plan.container_name,
            installed_at=time.time(),
            mounts=plan.mounts,
            plain_env=plan.plain_env,
        )
        self.installed_store.put(record)
        self._publish(
            "addon.installed",
            {"entry_id": entry_id, "upstream_key": key, "kind": entry.kind, "name": entry.name},
        )
        return await self._out(record)

    def _check_profiles(self, profile_paths: list[str]) -> None:
        """Refuse a profile list :meth:`_mount_on` would refuse — before
        anything has been registered (issue #351)."""
        for path in profile_paths:
            if path == CURATOR_PROFILE_PATH:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "the curator profile never mounts an external server: it "
                        "runs a model over your own notes, and an outside tool in "
                        "that session could exfiltrate them."
                    ),
                )
            if not any(p.path == path for p in self.dynamic_gateway.config.profiles):
                raise HTTPException(status_code=404, detail=f"no profile at path {path!r}")

    async def _forget_registration(self, key: str) -> None:
        """Undo an in-memory registration whose install did not complete."""
        try:
            await self.dynamic_gateway.remove_upstream(key)
        except KeyError:
            pass
        except Exception:  # noqa: BLE001 - best effort, the original error is what matters
            logger.exception("could not roll back the gateway registration of %s", key)
        try:
            await self.upstream_service.unregister(key)
        except Exception:  # noqa: BLE001 - best effort
            logger.exception("could not roll back the upstream registration of %s", key)

    async def _mount_on(self, key: str, profile_paths: list[str]) -> None:
        self._check_profiles(profile_paths)
        for path in profile_paths:
            current = next(
                (p for p in self.dynamic_gateway.config.profiles if p.path == path), None
            )
            if current is None:  # pragma: no cover - _check_profiles ran first
                raise HTTPException(status_code=404, detail=f"no profile at path {path!r}")
            if key in current.upstreams:
                continue
            # Issue #324: only the upstream list changes; every other profile
            # field (hidden_tools, messenger, semantic_routing, ...) is kept.
            await self.dynamic_gateway.set_profile_upstreams(path, [*current.upstreams, key])

    def _persist(self) -> None:
        persist_gateway_settings(
            self.config_path, snapshot_gateway_settings(self.dynamic_gateway, self.config)
        )

    # -------------------------------------------------------- installed

    async def _out(
        self, record: InstalledAddonRecord, *, curated: CuratedIndexResult | None = None
    ) -> InstalledAddonOut:
        """One record's REST shape. ``curated`` is the index fetched once
        for a whole listing (see :meth:`list_installed`); left ``None`` for
        a single-record answer such as an install's own response."""
        try:
            status = self.upstream_service.status(record.upstream_key)
            up, detail = status.up, status.detail
        except UpstreamNotConfiguredError:
            # The generic `/api/gateway/upstreams` surface can disconnect a
            # server this store still remembers installing (it is a
            # separate write path — see the module docstring). Reported
            # honestly rather than a 500: this entry needs reinstalling or
            # removing from the list, not a crash.
            up, detail = False, "No longer connected — reinstall it, or remove it below."
        current_ref: str | None = None
        entry = await self.market_service.get_entry(record.entry_id, curated=curated)
        if entry is not None:
            current_ref = entry.source.value
        profiles = sorted(
            p.path
            for p in self.dynamic_gateway.config.profiles
            if record.upstream_key in p.upstreams
        )
        return InstalledAddonOut(
            upstream_key=record.upstream_key,
            entry_id=record.entry_id,
            name=record.name,
            kind=record.kind,  # type: ignore[arg-type]
            provenance=record.provenance,
            installed_ref=record.installed_ref,
            current_ref=current_ref,
            update_available=(
                current_ref is not None
                and current_ref != record.installed_ref
                and record.kind == "container"
            ),
            up=up,
            status=detail,
            profiles=profiles,
            installed_at=record.installed_at,
        )

    async def _outs(self) -> list[InstalledAddonOut]:
        """Every installed record's REST shape, resolving all of them
        against **one** curated-index fetch rather than one per record
        (issue #321: ``GET /api/market/installed`` used to pay a full
        index round-trip — up to its 8 s timeout — per installed add-on)."""
        records = self.installed_store.list()
        if not records:
            return []
        curated = await self.market_service.curated_client.fetch()
        return [await self._out(record, curated=curated) for record in records]

    async def list_installed(self) -> list[InstalledAddonOut]:
        return await self._outs()

    async def update(self, upstream_key: str) -> InstalledAddonOut:
        record = self.installed_store.get(upstream_key)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"no add-on installed under {upstream_key!r}"
            )
        if record.kind != "container":
            raise HTTPException(
                status_code=400,
                detail="only a container add-on can be updated one-click — reconnect a "
                "remote/stdio server through its own edit form instead.",
            )
        entry = await self.market_service.get_entry(record.entry_id)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail=f"the marketplace no longer lists {record.entry_id!r} — cannot update.",
            )
        new_image = entry.source.value
        try:
            await docker_runtime.ensure_image(new_image)
        except docker_runtime.DockerError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            current = self.upstream_service.config(upstream_key)
        except UpstreamNotConfiguredError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Issue #344: the mounts and plain settings live in the run argv, not
        # in `current.env` (which is empty by construction for a container
        # add-on), so rebuilding from `env` alone started a bare container.
        # Prefer the plan persisted at install time; a record from before
        # that field existed recovers it from the argv this hub wrote.
        mounts, plain_env = record.mounts, record.plain_env
        if not mounts and not plain_env:
            mounts, plain_env = _plan_from_run_args(
                current.args, secret_env_vars=current.env_secrets.keys()
            )
        run_args = docker_runtime.build_stdio_run_args(
            new_image,
            container_name=record.container_name or _container_name(upstream_key),
            mounts=mounts,
            plain_env=plain_env,
            secret_env_vars=list(current.env_secrets.keys()),
            permissions=entry.permissions,
        )
        # `model_copy` skips validators (same caveat SPEC-302's own
        # `PATCH /api/gateway/upstreams/{key}` documents) — re-construct so
        # a now-invalid combination is refused rather than mounted.
        updated = UpstreamConfig.model_validate(
            current.model_copy(
                update={"command": run_args.command, "args": run_args.args}
            ).model_dump()
        )
        await self.dynamic_gateway.register_upstream(updated)
        await self.upstream_service.register(updated)
        await self.dynamic_gateway.refresh_upstreams([upstream_key])
        self._persist()

        new_record = InstalledAddonRecord(
            upstream_key=record.upstream_key,
            entry_id=record.entry_id,
            name=record.name,
            kind=record.kind,
            provenance=record.provenance,
            installed_ref=new_image,
            image=new_image,
            container_name=record.container_name,
            installed_at=record.installed_at,
            mounts=mounts,
            plain_env=plain_env,
        )
        self.installed_store.put(new_record)
        self._publish(
            "addon.updated",
            {"entry_id": record.entry_id, "upstream_key": upstream_key, "installed_ref": new_image},
        )
        return await self._out(new_record)

    async def uninstall(self, upstream_key: str) -> None:
        record = self.installed_store.get(upstream_key)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"no add-on installed under {upstream_key!r}"
            )
        try:
            await self.dynamic_gateway.remove_upstream(upstream_key)
        except KeyError:
            pass
        await self.upstream_service.unregister(upstream_key)
        if record.container_name is not None:
            # Best-effort: `docker run --rm` already reaps a cleanly-exited
            # container the moment its stdio child process closes (which
            # `unregister` above just triggered) — this only cleans up the
            # rare case where it did not exit cleanly, so uninstall never
            # leaves one behind (SPEC-304 acceptance criterion).
            await docker_runtime.remove_container(record.container_name)
        self._persist()
        self.installed_store.delete(upstream_key)
        self._publish(
            "addon.uninstalled", {"entry_id": record.entry_id, "upstream_key": upstream_key}
        )

    async def check_updates(self) -> list[InstalledAddonOut]:
        """Recompute every installed container's update status and publish
        ``addon.update_available`` for one whose availability just turned
        on — called after the curated index refreshes (deliverable #4)."""
        changed: list[InstalledAddonOut] = []
        for out in await self._outs():
            if out.update_available:
                changed.append(out)
                self._publish(
                    "addon.update_available",
                    {
                        "entry_id": out.entry_id,
                        "upstream_key": out.upstream_key,
                        "installed_ref": out.installed_ref,
                        "available_ref": out.current_ref,
                    },
                )
        return changed


def build_market_install_router(service: InstallService) -> APIRouter:
    router = APIRouter(prefix="/api/market", tags=["market"])

    @router.get("/entry/{entry_id}/plan", response_model=PlanPreview)
    async def plan_preview(entry_id: str) -> PlanPreview:
        """What installing this entry would run — for the consent screen (#349)."""
        return await service.preview(entry_id)

    @router.post("/entry/{entry_id}/consent", response_model=ConsentTokenOut)
    async def issue_consent(entry_id: str) -> ConsentTokenOut:
        return await service.issue_consent(entry_id)

    @router.post("/entry/{entry_id}/install", response_model=InstalledAddonOut)
    async def install_entry(entry_id: str, body: InstallRequest) -> InstalledAddonOut:
        return await service.install(entry_id, body)

    @router.get("/installed", response_model=list[InstalledAddonOut])
    async def list_installed() -> list[InstalledAddonOut]:
        return await service.list_installed()

    @router.post("/installed/{upstream_key}/update", response_model=InstalledAddonOut)
    async def update_installed(upstream_key: str) -> InstalledAddonOut:
        return await service.update(upstream_key)

    @router.post("/installed/check_updates", response_model=list[InstalledAddonOut])
    async def check_updates() -> list[InstalledAddonOut]:
        return await service.check_updates()

    @router.delete("/installed/{upstream_key}", status_code=204)
    async def uninstall_installed(upstream_key: str) -> None:
        await service.uninstall(upstream_key)

    return router


def wire_market_index_updates(event_bus: EventBus, service: InstallService) -> Callable[[], None]:
    """Subscribe ``service.check_updates()`` onto ``market.index.updated``
    (deliverable #4: "addon.update_available event, curated index version
    vs installed"). ``EventBus.on`` callbacks are synchronous, so the
    actual (async) check is scheduled as a background task — a failure in
    it is logged, never raised into the publisher (same posture every
    other bus subscriber in this codebase takes)."""

    def _on_event(envelope: Envelope) -> None:
        if envelope.event != "market.index.updated":
            return

        async def _run() -> None:
            try:
                await service.check_updates()
            except Exception:  # noqa: BLE001 - a failed check must not break the bus
                logger.exception("checking for marketplace add-on updates failed")

        asyncio.create_task(_run())

    return event_bus.on(_on_event)


__all__ = [
    "CONSENT_TTL_SECONDS",
    "ConsentStore",
    "ConsentTokenOut",
    "InstallPlan",
    "InstallRequest",
    "InstallService",
    "InstalledAddonOut",
    "MarketInstallError",
    "build_market_install_router",
    "wire_market_index_updates",
]
