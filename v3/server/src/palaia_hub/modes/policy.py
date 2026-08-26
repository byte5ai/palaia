"""Precondition validation for a mode/exposure change (SPEC-205 deliverable #1).

The wizard's whole point is to turn a config mistake that would otherwise
surface as a failed restart (:mod:`palaia_hub.config`'s own
``_check_operating_mode_policy``) into an *actionable, in-dashboard*
refusal before anything is written to disk. :func:`build_candidate_config`
does exactly what :mod:`palaia_hub.config` already does at load time —
merge the requested change onto the current configuration and run it
through :class:`~palaia_hub.config.HubConfig`'s own validators — plus two
checks that config-file loading has no reason to make (they are about
*wizard* inputs, not about a hand-edited file): an ``oauth.enabled`` with
no ``issuer``, and a ``public_url`` that is not ``https://`` (every client
this wizard is for — claude.ai, ChatGPT, a phone — refuses plaintext).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..config import ConfigError, HubConfig
from .errors import ModeChangeError


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge ``overrides`` onto ``base``, recursing into nested mappings.

    A ``None`` in ``overrides`` clears the key back to its model default
    (by omission) rather than setting it to ``None`` literally — used by
    the wizard to let go of ``oauth.issuer``/``exposure.public_url`` without
    the caller needing to know their model defaults.
    """
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def build_candidate_config(current: HubConfig, overrides: dict[str, Any]) -> HubConfig:
    """Return the ``HubConfig`` that would result from applying ``overrides``.

    Raises:
        ModeChangeError: the merged configuration fails validation — either
            :class:`~palaia_hub.config.HubConfig`'s own per-mode auth policy,
            or one of this module's wizard-level checks below. The message
            always names the fix, same as ``ConfigError``.
    """
    merged = _deep_merge(current.model_dump(mode="json"), overrides)
    try:
        candidate = HubConfig.model_validate(merged)
    except ValidationError as exc:
        raise ModeChangeError(_format_validation_error(exc)) from exc
    except ConfigError as exc:  # pragma: no cover - HubConfig raises ValidationError, not this
        raise ModeChangeError(str(exc)) from exc
    _check_wizard_level_preconditions(candidate)
    return candidate


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        msg = error["msg"].removeprefix("Value error, ")
        loc = ".".join(str(part) for part in error["loc"]) or "<root>"
        lines.append(msg if "Fix:" in msg else f"'{loc}': {msg}")
    return "; ".join(lines)


def _check_wizard_level_preconditions(candidate: HubConfig) -> None:
    oauth_on_without_issuer = candidate.oauth.enabled and not candidate.oauth.issuer
    if candidate.mode in ("cloud", "open") and oauth_on_without_issuer:
        raise ModeChangeError(
            f"mode {candidate.mode!r} with oauth.enabled=true also needs an "
            f"`oauth.issuer` — the public https URL clients get redirected "
            f"to. Fix: set `oauth.issuer` to the public URL this hub will be "
            f"reachable at (e.g. from the tunnel guidance step), or turn "
            f"`oauth.enabled` off and rely on `auth_enabled` (per-client "
            f"tokens) instead."
        )
    public_url = candidate.exposure.public_url
    if public_url is not None and not public_url.startswith("https://"):
        raise ModeChangeError(
            f"exposure.public_url {public_url!r} must be an https:// URL — "
            f"claude.ai, ChatGPT and a phone all refuse a plaintext "
            f"connector. Fix: put this hub behind a tunnel or reverse proxy "
            f"that terminates TLS, then set `exposure.public_url` to its "
            f"https address."
        )


__all__ = ["ModeChangeError", "build_candidate_config"]
