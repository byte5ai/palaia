"""``palaia-addon validate``: the manifest against the SPEC-303 entry
shape, the SPEC-304 ``config_schema`` subset, permission declarations, and
the SPEC-207 jargon lint — every failure named plainly enough to fix
without re-reading this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from .jargon import find_jargon
from .models import CONFIG_FIELD_KINDS, KNOWN_PERMISSIONS, AddonManifest, EntryKind

SUPPORTED_KINDS: tuple[str, ...] = get_args(EntryKind)

MANIFEST_FILENAME = "manifest.json"


@dataclass(frozen=True)
class Issue:
    """One validation failure."""

    where: str
    message: str

    def __str__(self) -> str:
        return f"{self.where}: {self.message}"


def _manifest_path(target: Path) -> Path:
    return target / MANIFEST_FILENAME if target.is_dir() else target


def load_manifest_raw(target: Path) -> tuple[dict[str, Any] | None, list[Issue]]:
    """Read and JSON-parse the manifest at ``target`` (a directory
    containing ``manifest.json``, or a path to the file itself)."""
    path = _manifest_path(target)
    where = str(path)
    if not path.is_file():
        return None, [Issue(where, f"no {MANIFEST_FILENAME} found")]
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [Issue(where, f"not valid JSON: {exc}")]
    if not isinstance(raw, dict):
        return None, [Issue(where, "the manifest must be a JSON object")]
    return raw, []


def _kind_error_message(error: Mapping[str, Any]) -> str | None:
    loc = error.get("loc") or ()
    if tuple(loc) == ("kind",) and error.get("type") in {"literal_error", "enum"}:
        supported = ", ".join(SUPPORTED_KINDS)
        return f"kind {error.get('input')!r} is not one of the supported kinds ({supported})"
    return None


def _schema_error_issues(where: str, exc: ValidationError) -> list[Issue]:
    issues: list[Issue] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error.get("loc", ())) or "(root)"
        message = _kind_error_message(error) or f"{loc}: {error['msg']}"
        issues.append(Issue(where, message))
    return issues


def _check_permissions(where: str, permissions: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for permission in permissions:
        if permission not in KNOWN_PERMISSIONS:
            issues.append(
                Issue(
                    where,
                    f"unknown permission {permission!r} — declare one of "
                    f"{sorted(KNOWN_PERMISSIONS)}",
                )
            )
    return issues


def _check_config_schema(where: str, config_schema: Any) -> list[Issue]:
    if config_schema is None:
        return []
    if not isinstance(config_schema, dict):
        return [Issue(where, "config_schema must be a JSON object")]
    properties = config_schema.get("properties", {})
    if not isinstance(properties, dict):
        return [Issue(where, "config_schema.properties must be a JSON object")]
    issues: list[Issue] = []
    for field_name, prop in properties.items():
        if not isinstance(prop, dict):
            issues.append(Issue(where, f"config_schema field {field_name!r} must be an object"))
            continue
        kind = prop.get("type")
        if kind not in CONFIG_FIELD_KINDS:
            issues.append(
                Issue(
                    where,
                    f"config_schema field {field_name!r} has type {kind!r}, outside the "
                    f"supported subset {sorted(CONFIG_FIELD_KINDS)} — a picklist is a "
                    f"'string' field with an 'enum' list, not a type of its own",
                )
            )
        title = prop.get("title")
        if isinstance(title, str):
            for word in find_jargon(title):
                issues.append(
                    Issue(
                        where,
                        f"config_schema field {field_name!r} title uses in-house word "
                        f"{word!r} — this label is shown to whoever installs the add-on",
                    )
                )
    return issues


def _check_jargon(where: str, manifest: AddonManifest) -> list[Issue]:
    issues: list[Issue] = []
    for field_name, value in (("name", manifest.name), ("one_liner", manifest.one_liner)):
        for word in find_jargon(value):
            issues.append(Issue(where, f"{field_name} uses in-house word {word!r}"))
    return issues


def validate_manifest(target: Path) -> list[Issue]:
    """Every SPEC-406 validation rule, applied to the manifest at ``target``."""
    raw, issues = load_manifest_raw(target)
    where = str(_manifest_path(target))
    if raw is None:
        return issues

    try:
        manifest = AddonManifest.model_validate(raw)
    except ValidationError as exc:
        return [*issues, *_schema_error_issues(where, exc)]

    issues.extend(_check_permissions(where, manifest.permissions))
    issues.extend(_check_config_schema(where, raw.get("config_schema")))
    issues.extend(_check_jargon(where, manifest))
    return issues


__all__ = ["MANIFEST_FILENAME", "Issue", "load_manifest_raw", "validate_manifest"]
