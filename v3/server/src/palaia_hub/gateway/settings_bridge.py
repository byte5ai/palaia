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

from collections.abc import Sequence
from pathlib import Path

import yaml

from ..config import GatewaySettings, HubConfig
from ..modes.patch import replace_config_section
from .config import ProfileConfig, VaultMountConfig


class GatewaySettingsError(ValueError):
    """``config.yaml``'s ``gateway:`` section is structurally fine (it is
    already a valid :class:`~palaia_hub.config.GatewaySettings`) but
    disagrees with reality — e.g. a profile names a vault key that is not
    actually registered. Distinct from the :class:`pydantic.ValidationError`
    the settings model itself already raises for a malformed section.
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
) -> list[ProfileConfig]:
    """The ordinary (non-curator) profiles this hub serves.

    No ``gateway:`` section, or one with an empty ``profiles`` list:
    today's zero-config default — one profile (``default_profile``) over
    every vault in ``vault_keys``, or no profiles at all when there are no
    vaults yet. A populated ``profiles`` list is authoritative instead.

    Raises:
        GatewaySettingsError: a configured profile names a vault key not in
            ``vault_keys`` (a vault that either never existed or was
            renamed/removed since the section was written).
    """
    if settings is None or not settings.profiles:
        if not vault_keys:
            return []
        return [ProfileConfig(path=default_profile, vaults=list(vault_keys))]

    known = set(vault_keys)
    resolved: list[ProfileConfig] = []
    for profile in settings.profiles:
        unknown = [v for v in profile.vaults if v not in known]
        if unknown:
            raise GatewaySettingsError(
                f"config.yaml: gateway.profiles[path={profile.path!r}] references "
                f"vault key(s) {unknown} that are not registered on this hub (it "
                f"has: {sorted(known) or 'none'}). Fix: create the vault first, or "
                f"remove it from this profile's `vaults` list in config.yaml."
            )
        resolved.append(
            ProfileConfig(
                path=profile.path,
                label=profile.label,
                vaults=list(profile.vaults),
                stash=profile.stash,
                hidden_tools=list(profile.hidden_tools),
                semantic_routing=profile.semantic_routing,
            )
        )
    return resolved


def resolve_full_gateway_profiles(
    config: HubConfig,
    vault_keys: Sequence[str],
    *,
    default_profile: str,
) -> list[ProfileConfig]:
    """:func:`resolve_profiles` plus the curator's own profile, when it runs.

    The one function both ``palaia_hub.cli`` (building the OAuth server,
    which needs to know every resource up front) and
    ``palaia_hub.serve.build_production_app`` (building the real gateway)
    call, so the two never compute a different profile list for the same
    config (SPEC-301 deliverable #3's "one source of truth").
    """
    profiles = resolve_profiles(config.gateway, vault_keys, default_profile=default_profile)
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


__all__ = [
    "GatewaySettingsError",
    "apply_vault_overrides",
    "persist_gateway_settings",
    "render_gateway_section",
    "resolve_full_gateway_profiles",
    "resolve_profiles",
]
