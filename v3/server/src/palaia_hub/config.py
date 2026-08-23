"""Hub configuration: a single ``config.yaml`` in a platform data dir.

Precedence (lowest to highest): built-in defaults < ``config.yaml`` < env
vars (``PALAIA_*``). Zero-config first run creates a commented default file
and starts fine. An invalid file or env value fails startup with a message
naming the file, the offending key, and how to fix it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, ValidationError

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
#   cloud             - MCP reachable publicly (tunnel/open port);
#                        dashboard stays VPN-only; auth mandatory
#   open              - both public; auth mandatory + hardening checklist
mode: locked

# Host/port the hub binds to.
host: 127.0.0.1
port: 8420

# Logging: level is one of debug|info|warning|error; format is human|json.
log_level: info
log_format: human

# Seconds to wait for in-flight requests to finish before exiting on
# shutdown (e.g. SIGTERM).
graceful_shutdown_timeout: 30
"""


class ConfigError(RuntimeError):
    """Raised when the hub configuration cannot be loaded or is invalid.

    The message always names the config file path, the offending key, and a
    concrete fix, per SPEC-101's acceptance criteria.
    """


class HubConfig(BaseModel):
    """Validated hub configuration, merged from defaults/file/env."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["locked", "cloud", "open"] = "locked"
    host: str = "127.0.0.1"
    port: int = 8420
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    log_format: Literal["human", "json"] = "human"
    graceful_shutdown_timeout: float = 30.0


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
        env_name = f"{_ENV_PREFIX}{loc.upper()}"
        lines.append(
            f"{path}: key '{loc}' — {error['msg']}. "
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
