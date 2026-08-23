"""Structured logging for the hub, with mandatory secret redaction.

Two output formats (human-readable default, JSON opt-in), per-component log
levels via the standard logging hierarchy (``palaia_hub.<component>``), and
a filter that redacts anything that looks like a token/key/secret/password
before it reaches a handler — tokens must never appear in log output.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any

from .config import HubConfig

ROOT_LOGGER_NAME = "palaia_hub"

REDACTED = "***REDACTED***"

# `Authorization: Bearer <token>` (and bare `Bearer <token>`) mentions.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.=]{8,}")

# `key=value` / `key: value` / `key="value"` where the key name looks
# secret-ish (token, api key, secret, password, authorization header, ...).
_KV_SECRET_RE = re.compile(
    r"(?i)\b(token|api[_-]?key|secret|password|authorization)\b"
    r"(\s*[:=]\s*)"
    r"(\"|')?"
    r"([^\s\"',}]{3,})"
    r"(\3)?"
)


def redact(message: str) -> str:
    """Return ``message`` with any token/key/secret-shaped substrings masked."""
    message = _BEARER_RE.sub(f"Bearer {REDACTED}", message)
    message = _KV_SECRET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{m.group(3) or ''}{REDACTED}{m.group(3) or ''}",
        message,
    )
    return message


class RedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from the fully-formatted message.

    Formats the record eagerly (``record.getMessage()``), redacts the
    result, and — if anything changed — replaces ``record.msg`` with the
    redacted string and clears ``record.args`` so later formatting (by a
    ``Formatter``) does not re-apply ``%``-substitution to already-formatted
    text.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - malformed log call
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    """Renders a log record as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_HUMAN_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"

_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def setup_logging(config: HubConfig, *, component_levels: dict[str, str] | None = None) -> None:
    """Configure the ``palaia_hub`` logger tree from ``config``.

    Idempotent: safe to call more than once (e.g. from tests) — it replaces
    the root handler each time rather than accumulating duplicates.

    Args:
        config: hub config; ``log_level``/``log_format`` set the default.
        component_levels: optional per-component overrides, e.g.
            ``{"vault": "debug"}`` sets ``palaia_hub.vault`` to DEBUG while
            everything else stays at ``config.log_level``.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.handlers.clear()
    root.filters.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = JsonFormatter() if config.log_format == "json" else logging.Formatter(_HUMAN_FORMAT)
    handler.setFormatter(formatter)
    handler.addFilter(RedactionFilter())

    root.addHandler(handler)
    root.setLevel(_LEVELS[config.log_level])
    root.propagate = False

    for component, level in (component_levels or {}).items():
        logging.getLogger(f"{ROOT_LOGGER_NAME}.{component}").setLevel(_LEVELS[level])
