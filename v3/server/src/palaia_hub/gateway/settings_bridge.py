"""Bridges the ``config.yaml`` ``gateway:`` section into the gateway's own
runtime shapes, and back (SPEC-301).

:mod:`palaia_hub.config` defines :class:`~palaia_hub.config.GatewaySettings`
as a *duplicate*, fastmcp-free schema (see that class's docstring) — this
module is the one place that converts between it and
:class:`~.config.GatewayConfig`/:class:`~.config.ProfileConfig`/
:class:`~.config.VaultMountConfig`, in both directions:

- :func:`apply_vault_overrides` / :func:`resolve_profiles` /
  :func:`resolve_full_gateway_profiles` — config.yaml → the shapes
  :func:`palaia_hub.serve.build_production_app` and ``palaia_hub.cli`` hand
  to the gateway and the OAuth server. Both call sites use the *same*
  functions, so "which resources exist" (SPEC-301 deliverable #3) is one
  computation, not two that could drift.
- :func:`persist_gateway_settings` — the reverse, for the runtime profile
  CRUD surface (:mod:`palaia_hub.gateway.api`): after a live edit, write the
  new shape back to ``config.yaml`` using the same surgical, comment-
  preserving text patch :mod:`palaia_hub.modes.patch` already established.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from ..config import GatewayProfileSettings, GatewaySettings, GatewayVaultSettings, HubConfig
from ..modes.patch import replace_config_section
from ..upstream.models import UpstreamConfig
from .config import CURATOR_PROFILE_PATH, ProfileConfig, VaultMountConfig

logger = logging.getLogger("palaia_hub.gateway.settings_bridge")


class GatewaySettingsError(ValueError):
    """``config.yaml``'s ``gateway:`` section is structurally fine (it is
    already a valid :class:`~palaia_hub.config.GatewaySettings`) but
    disagrees with reality — e.g. a profile names an external server key
    that is not listed under ``gateway.upstreams``. Distinct from the
    :class:`pydantic.ValidationError` the settings model itself already
    raises for a malformed section, and — since #273 — no longer raised for
    a profile's vault key that simply does not exist *yet*: see
    :func:`resolve_profiles`'s docstring for why that case is a legitimate
    pre-declaration, not an error.
    """


def apply_vault_overrides(
    mounts: Sequence[VaultMountConfig], settings: GatewaySettings | None
) -> list[VaultMountConfig]:
    """Overlay ``gateway.vaults`` identity overrides onto ``mounts``.

    A mount whose key has no entry in ``settings.vaults`` (or ``settings``
    is ``None``) passes through unchanged. A field left ``None`` on the
    override (``name``/``purpose``) keeps the mount's own value; an empty
    ``tool_renames`` on the override is *not* special-cased — an operator
    who lists a vault under ``gateway.vaults`` with no ``tool_renames`` at
    all still gets the default empty dict, same as omitting it entirely.
    """
    if settings is None or not settings.vaults:
        return list(mounts)
    overrides = {v.key: v for v in settings.vaults}
    resolved: list[VaultMountConfig] = []
    for mount in mounts:
        override = overrides.get(mount.key)
        if override is None:
            resolved.append(mount)
            continue
        resolved.append(
            mount.model_copy(
                update={
                    "name": override.name if override.name is not None else mount.name,
                    "purpose": (
                        override.purpose if override.purpose is not None else mount.purpose
                    ),
                    "tool_renames": dict(override.tool_renames),
                }
            )
        )
    return resolved


def resolve_profiles(
    settings: GatewaySettings | None,
    vault_keys: Sequence[str],
    *,
    default_profile: str,
    include_pending: bool = False,
) -> list[ProfileConfig]:
    """The ordinary (non-curator) profiles this hub serves.

    No ``gateway:`` section, or one with an empty ``profiles`` list:
    today's zero-config default — one profile (``default_profile``) over
    every vault in ``vault_keys``, or no profiles at all when there are no
    vaults yet. A populated ``profiles`` list is authoritative instead.

    **Pre-declared vaults (#273).** A configured profile's ``vaults`` may
    name a key that is not (yet) in ``vault_keys`` — an operator writing
    ``gateway.profiles`` before ever running the first-run wizard, saying
    "the ``default`` profile will serve a vault named ``work``, create it
    in a minute." That is never an error (this function used to raise
    :class:`GatewaySettingsError` for it; it no longer does — see that
    class's docstring). Instead, ``include_pending`` picks which of two
    views of the same declared shape this call returns, because this
    function's two production callers each need a different one:

    * ``include_pending=False`` (the default —
      :func:`palaia_hub.serve.build_production_app`'s use, via
      :func:`resolve_full_gateway_profiles`): the *mountable* shape. A
      pending vault key is left out of the returned
      ``ProfileConfig.vaults`` — there is nothing to mount yet, and
      :class:`~palaia_hub.gateway.config.GatewayConfig`'s own validator
      would refuse a profile naming a vault absent from its ``vaults``
      list regardless. Logged once at ``INFO``, not raised: the config is
      not wrong, only ahead of vault creation. Nothing further has to
      happen for it to catch up — the moment the vault is registered
      (``POST /api/vaults``), :meth:`~palaia_hub.gateway.dynamic.
      DynamicGateway.add_vault` appends its key straight onto this same
      profile's *live* vault list, no restart and no second call to this
      function required.
    * ``include_pending=True`` (:func:`palaia_hub.cli.
      _gateway_profiles_for_oauth`'s use): the *declared* shape — every
      vault key the profile names, mounted or not. This is what the
      OAuth authorization server's grantable-scope ceiling
      (:func:`palaia_hub.cli._profile_scopes`) is computed from, because
      :class:`~palaia_hub.oauth.service.AuthorizationServer` freezes that
      ceiling at construction and never mutates it afterward (see its
      class docstring): a pending vault's scopes have to be decided now,
      before the wizard creates it, or Cloud mode + OAuth simply cannot
      be turned on before the first vault exists.

    Granting a scope for a vault that is not mounted yet never widens
    anything a live token can actually do: nothing enforces the scope
    until the vault is mounted (there is no tool on the wire to invoke,
    and :mod:`palaia_hub.auth.enforcement` has nothing to check it
    against before then). By the time a client could present such a
    token to a real tool call, the vault has to already be mounted —
    which happens only once its key is registered, at which point the
    pre-declared ceiling and the real mount already agree, by
    construction: the declaration is what the mount converges to, never
    the other way around, so there is nothing to reconcile at
    vault-creation time.

    Raises:
        GatewaySettingsError: a configured profile names an *external
            server* key not in ``gateway.upstreams``. Unlike a vault, an
            upstream has no wizard-driven "not created yet" story — there
            is no asynchronous flow that will register it later — so an
            unknown upstream key stays a hard, loud config error.
    """
    if settings is None or not settings.profiles:
        if not vault_keys:
            return []
        return [ProfileConfig(path=default_profile, vaults=list(vault_keys))]

    known = set(vault_keys)
    known_upstreams = {u.key for u in settings.upstreams}
    resolved: list[ProfileConfig] = []
    for profile in settings.profiles:
        pending = [v for v in profile.vaults if v not in known]
        if pending and not include_pending:
            logger.info(
                "config.yaml: gateway.profiles[path=%r] pre-declares vault "
                "key(s) %s not yet registered on this hub — its tools stay "
                "absent until the vault is created (the dashboard wizard, "
                "or `palaia-hub import ...`), but its OAuth scopes (if "
                "oauth.enabled) are already reserved for this profile.",
                profile.path,
                sorted(pending),
            )
        vaults = (
            list(profile.vaults) if include_pending else [v for v in profile.vaults if v in known]
        )
        unknown_upstreams = [u for u in profile.upstreams if u not in known_upstreams]
        if unknown_upstreams:
            raise GatewaySettingsError(
                f"config.yaml: gateway.profiles[path={profile.path!r}] references "
                f"external server(s) {unknown_upstreams} that are not listed under "
                f"`gateway.upstreams` (it lists: {sorted(known_upstreams) or 'none'}). "
                "Fix: add the server there, or remove it from this profile's "
                "`upstreams` list."
            )
        resolved.append(
            ProfileConfig(
                path=profile.path,
                label=profile.label,
                vaults=vaults,
                stash=profile.stash,
                directory=profile.directory,
                messenger=profile.messenger,
                hidden_tools=list(profile.hidden_tools),
                semantic_routing=profile.semantic_routing,
                upstreams=list(profile.upstreams),
            )
        )
    return resolved


def resolve_upstreams(settings: GatewaySettings | None) -> list[UpstreamConfig]:
    """The external servers ``config.yaml`` connects (SPEC-302 deliverable #1).

    No ``gateway:`` section, or one with no ``upstreams``: an empty list —
    a hub with no external servers, which is every hub until someone
    connects one. The models are already validated (they *are*
    :class:`~palaia_hub.upstream.models.UpstreamConfig` — see
    :class:`palaia_hub.config.GatewaySettings`), so this is a pass-through
    that exists to keep every caller reading the section through this one
    module rather than reaching into ``config.gateway`` themselves.
    """
    if settings is None:
        return []
    return list(settings.upstreams)


def resolve_full_gateway_profiles(
    config: HubConfig,
    vault_keys: Sequence[str],
    *,
    default_profile: str,
    include_pending: bool = False,
) -> list[ProfileConfig]:
    """:func:`resolve_profiles` plus the curator's own profile, when it runs.

    The one function both ``palaia_hub.cli`` (building the OAuth server,
    which needs to know every resource up front) and
    ``palaia_hub.serve.build_production_app`` (building the real gateway)
    call, so the two never compute a different profile list for the same
    config (SPEC-301 deliverable #3's "one source of truth") — they differ
    only in ``include_pending`` (see :func:`resolve_profiles`), never in
    which profiles exist or what else each one carries.

    The curator's own profile is exempt from ``include_pending``: it is
    always synthesized from the vaults *actually* registered
    (``vault_keys``), never from a pre-declaration — the curator has no
    config surface of its own naming vaults ahead of their creation, and
    synthesizing it from a pending key would let curation start on a vault
    that does not exist.
    """
    profiles = resolve_profiles(
        config.gateway, vault_keys, default_profile=default_profile, include_pending=include_pending
    )
    if config.curator.enabled and vault_keys:
        # Deferred import: the curator package pulls in fastmcp, which this
        # module otherwise has no need for (it only touches config.py's
        # fastmcp-free settings and gateway.config's plain pydantic models).
        from ..curator.profile import curator_profile

        profiles = [*profiles, curator_profile(list(vault_keys))]
    return profiles


def render_gateway_section(settings: GatewaySettings) -> str:
    """Render the ``gateway:`` section body exactly as ``config.yaml``
    expects it: everything indented two spaces under the header, header
    itself excluded (:func:`~palaia_hub.modes.patch.replace_config_section`
    supplies that)."""
    payload = settings.model_dump(mode="json")
    dumped = yaml.safe_dump({"gateway": payload}, default_flow_style=False, sort_keys=False)
    _, _, body = dumped.partition("\n")
    if body and not body.endswith("\n"):
        body += "\n"
    return body or "  vaults: []\n  profiles: []\n"


def persist_gateway_settings(path: Path, settings: GatewaySettings) -> None:
    """Write ``settings`` back to ``config.yaml`` at ``path``, preserving
    every other line (comments included) exactly as it was — the runtime
    profile CRUD surface's write-back half (SPEC-301 deliverable #2)."""
    replace_config_section(path, "gateway", render_gateway_section(settings))


def snapshot_gateway_settings(dynamic_gateway: Any, config: HubConfig) -> GatewaySettings:
    """The gateway's current live shape, in ``config.yaml``'s own
    :class:`GatewaySettings` schema — the "live-then-persisted" snapshot
    every REST surface that mutates the gateway writes back after applying
    a change (SPEC-301's own profile CRUD builds this inline; SPEC-304's
    marketplace install flow reuses this shared version instead of a third
    hand-copy — see that module for why). ``dynamic_gateway`` is typed
    ``Any`` here rather than
    :class:`~palaia_hub.gateway.dynamic.DynamicGateway` to avoid a circular
    import (``dynamic.py`` itself imports this module); only ``.config`` is
    ever read off it.

    The curator's own profile is excluded (synthesized from ``curator:``,
    never itself persisted).

    Vault identities come from the *live* gateway (issue #325): a vault
    renamed through ``PATCH /api/gateway/vaults/{key}`` lives in
    ``dynamic_gateway.config.vaults``, not in the ``config.gateway.vaults``
    snapshot this process booted with — persisting the snapshot reverted
    every such rename on the next upstream edit or add-on install. An
    override in ``config.gateway.vaults`` for a vault that is *not* mounted
    (pre-declared for the wizard to create later, #273) has no live
    counterpart and is carried through untouched.
    """
    declared = config.gateway.vaults if config.gateway is not None else []
    live_vaults = [
        GatewayVaultSettings(
            key=v.key, name=v.name, purpose=v.purpose, tool_renames=dict(v.tool_renames)
        )
        for v in dynamic_gateway.config.vaults
    ]
    live_keys = {v.key for v in live_vaults}
    vaults = [*live_vaults, *(v for v in declared if v.key not in live_keys)]
    profiles = [p for p in dynamic_gateway.config.profiles if p.path != CURATOR_PROFILE_PATH]
    return GatewaySettings(
        vaults=vaults,
        profiles=[
            GatewayProfileSettings(
                path=p.path,
                label=p.label,
                vaults=list(p.vaults),
                stash=p.stash,
                directory=p.directory,
                messenger=p.messenger,
                hidden_tools=list(p.hidden_tools),
                semantic_routing=p.semantic_routing,
                upstreams=list(p.upstreams),
            )
            for p in profiles
        ],
        upstreams=list(dynamic_gateway.config.upstreams),
    )


__all__ = [
    "GatewaySettingsError",
    "apply_vault_overrides",
    "persist_gateway_settings",
    "render_gateway_section",
    "resolve_full_gateway_profiles",
    "resolve_profiles",
    "resolve_upstreams",
    "snapshot_gateway_settings",
]
