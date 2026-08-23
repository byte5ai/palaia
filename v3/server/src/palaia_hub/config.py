"""Hub configuration: a single ``config.yaml`` in a platform data dir.

Precedence (lowest to highest): built-in defaults < ``config.yaml`` < env
vars (``PALAIA_*``). Zero-config first run creates a commented default file
and starts fine. An invalid file or env value fails startup with a message
naming the file, the offending key, and how to fix it.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

APP_NAME = "palaia-hub"

_ENV_PREFIX = "PALAIA_"

# The config keys that may be overridden by PALAIA_<KEY> env vars. Kept as an
# explicit tuple (rather than deriving from model fields at import time) so
# the mapping from env var name to config key is easy to read and to grep.
_ENV_KEYS = (
    "mode",
    "host",
    "port",
    "log_level",
    "log_format",
    "graceful_shutdown_timeout",
    "auth_enabled",
)

DEFAULT_CONFIG_TEMPLATE = """\
# palaia hub configuration
#
# Generated automatically on first run. Edit freely — invalid values are
# rejected at startup with a message naming this file, the offending key,
# and a fix.
#
# Every setting below may also be overridden by an environment variable
# named PALAIA_<SETTING> (e.g. PALAIA_MODE=cloud), which takes precedence
# over whatever is written here.

# Operating mode: locked | cloud | open
#   locked (default) - MCP + dashboard reachable only over VPN/tailnet
#   cloud             - MCP reachable publicly via a tunnel (Tailscale
#                        Funnel, cloudflared) terminating on a private
#                        `host` below; dashboard stays VPN-only; auth
#                        mandatory. Binding `host` directly to a public
#                        address isn't supported yet — use 'open' for that.
#   open              - both public, `host` may be a public/wildcard bind;
#                        auth mandatory + hardening checklist
mode: locked

# Host/port the hub binds to. In 'cloud' mode this must be a private/VPN
# address (e.g. 127.0.0.1 or a tailnet IP) — see 'mode' above.
host: 127.0.0.1
port: 8420

# Logging: level is one of debug|info|warning|error; format is human|json.
log_level: info
log_format: human

# Seconds to wait for in-flight requests to finish before exiting on
# shutdown (e.g. SIGTERM).
graceful_shutdown_timeout: 30

# Whether MCP clients must present a bearer token (SPEC-108).
#   locked mode - optional; defaults to on anyway (turn off only if every
#                 client on your VPN/tailnet is already trusted).
#   cloud/open  - mandatory; the hub refuses to start MCP endpoints
#                 otherwise. Cannot be turned off in these modes.
auth_enabled: true
"""


class ConfigError(RuntimeError):
    """Raised when the hub configuration cannot be loaded or is invalid.

    The message always names the config file path, the offending key, and a
    concrete fix, per SPEC-101's acceptance criteria.
    """


# RFC 6598 shared address space (100.64.0.0/10) — the CGNAT range Tailscale
# and similar tailnets hand out. Not covered by ipaddress.is_private, so it
# is checked separately below.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")


def _is_private_bind_host(host: str) -> bool:
    """Is ``host`` a bind address that stays off the public internet?

    True for loopback, RFC1918 private ranges, link-local, and the
    Tailscale/tailnet CGNAT range. False for a wildcard bind (``0.0.0.0``/
    ``::`` — reachable on every interface a box has, public ones included),
    an unrecognized literal address, or anything that is not a literal IP
    (a hostname cannot be checked without a DNS lookup, so it is rejected
    rather than trusted).
    """
    if host.lower() == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if addr.is_unspecified:
        return False
    if addr in _SHARED_ADDRESS_SPACE:
        return True
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


class HubConfig(BaseModel):
    """Validated hub configuration, merged from defaults/file/env."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["locked", "cloud", "open"] = "locked"
    host: str = "127.0.0.1"
    port: int = 8420
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["human", "json"] = "human"
    graceful_shutdown_timeout: float = 30.0
    auth_enabled: bool = True

    @model_validator(mode="after")
    def _check_operating_mode_policy(self) -> HubConfig:
        """MASTERPLAN §5.5's per-mode auth policy, enforced in code (SPEC-108).

        ``cloud``/``open`` MUST have auth on — those modes exist to make MCP
        endpoints reachable off the operator's own network, and the hub must
        never serve one that way with no token check. ``cloud`` additionally
        keeps its bind address private: the hub has one listener for both
        the MCP endpoints and the admin dashboard, and the dashboard must
        stay VPN/tailnet-only in ``cloud`` mode (masterplan's mode table) —
        so for Phase 1 (no dual-listener/reverse-proxy split yet), reaching
        the public internet in ``cloud`` mode means a tunnel (Tailscale
        Funnel, cloudflared) terminating on a private address, not a direct
        public/wildcard bind. ``open`` mode has no such restriction — its
        whole point is that the dashboard itself is public too.
        """
        if self.mode in ("cloud", "open") and not self.auth_enabled:
            raise ValueError(
                f"mode '{self.mode}' requires auth_enabled=true — MCP endpoints "
                f"would otherwise be reachable over the network with no token "
                f"check at all. Fix: set `auth_enabled: true` in config.yaml (or "
                f"PALAIA_AUTH_ENABLED=true), or set `mode: locked` if every "
                f"client only ever reaches this hub over your own VPN/tailnet."
            )
        if self.mode == "cloud" and not _is_private_bind_host(self.host):
            raise ValueError(
                f"mode 'cloud' requires a private/VPN bind address so the admin "
                f"dashboard never becomes reachable through the same listener "
                f"MCP is exposed on (host is currently {self.host!r}). Fix: set "
                f"`host` to a private address (e.g. 127.0.0.1, or your "
                f"tailnet/Tailscale IP) in config.yaml and reach it publicly via "
                f"a tunnel (Tailscale Funnel, cloudflared); or set `mode: open` "
                f"if you intend the dashboard itself to be public."
            )
        return self


def palaia_home() -> Path:
    """Return the platform data dir for the hub, honoring ``PALAIA_HOME``."""
    override = os.environ.get("PALAIA_HOME")
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir(APP_NAME, appauthor=False))


def config_file_path(home: Path | None = None) -> Path:
    """Return the path to ``config.yaml`` under ``home`` (or the default)."""
    return (home or palaia_home()) / "config.yaml"


def ensure_default_config(path: Path) -> None:
    """Write a commented default config file at ``path`` if none exists."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")


def _read_file_values(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{path}: could not parse YAML ({exc}). Fix: correct the syntax "
            f"in {path}, or delete it to regenerate the default file."
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path}: key '<root>' — expected a mapping of settings, got "
            f"{type(raw).__name__}. Fix: use `key: value` lines in {path}."
        )
    return raw


def _read_env_values() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in _ENV_KEYS:
        env_name = f"{_ENV_PREFIX}{key.upper()}"
        if env_name in os.environ:
            values[key] = os.environ[env_name]
    return values


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "<root>"
        msg = error["msg"]
        if loc == "<root>" and "Fix:" in msg:
            # A cross-field validator (e.g. _check_operating_mode_policy)
            # already spelled out its own actionable fix — appending the
            # generic "correct '<root>' ... override via PALAIA_<ROOT>"
            # suffix below would only make its message confusing.
            lines.append(f"{path}: {msg.removeprefix('Value error, ')}")
            continue
        env_name = f"{_ENV_PREFIX}{loc.upper()}"
        lines.append(
            f"{path}: key '{loc}' — {msg}. "
            f"Fix: correct '{loc}' in {path}, or override it via {env_name}."
        )
    return "\n".join(lines)


def load_config(home: Path | None = None, *, create_if_missing: bool = True) -> HubConfig:
    """Load and validate the hub config with defaults < file < env precedence.

    Raises:
        ConfigError: the file is unparsable, malformed, or a value (from the
            file or from an env override) fails validation. The message
            names the file, the key, and a fix.
    """
    resolved_home = home or palaia_home()
    path = config_file_path(resolved_home)
    if create_if_missing:
        ensure_default_config(path)

    file_values = _read_file_values(path)
    env_values = _read_env_values()
    merged: dict[str, Any] = {**file_values, **env_values}

    try:
        return HubConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(path, exc)) from exc
