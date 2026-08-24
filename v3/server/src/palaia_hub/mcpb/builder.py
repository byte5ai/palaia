"""Personalizes and (re)signs one MCPB bundle per download (deliverable #4).

``build_bundle`` is deliberately synchronous and blocking (three
subprocess calls to the `mcpb` CLI, plus a copy) — :mod:`palaia_hub.mcpb.routes`
runs it through ``asyncio.to_thread``, the same discipline
:mod:`palaia_hub.oauth.routes` already uses for its own blocking (argon2,
sqlite) calls, so one download does not stall the event loop for every
other request in flight.

Nothing here re-implements the MCPB zip or signature format — every step
is the official `mcpb` CLI (`validate`, `pack`, `sign`), the same tool CI
uses to build and sign the generic template
(``v3/tools/build-mcpb/build.mjs``). What changes per call is only the
staged ``manifest.json``'s ``user_config`` defaults (the hub URL, and
either a token or an OAuth issuer) — never the proxy script or the icon,
which are copied byte-for-byte from the template CI already validated.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .signing import signing_cert_paths
from .template import mcpb_binary, template_dir


class BundleBuildError(Exception):
    """`mcpb validate`/`pack`/`sign` failed. Message includes their output."""


@dataclass(frozen=True)
class BundleRequest:
    """Everything one personalized download needs to know.

    ``token`` and ``issuer`` are mutually exclusive in practice (the router
    sets exactly one, matching ``variant``) — kept as two plain optional
    fields rather than a tagged union because that is exactly what the
    manifest's ``user_config`` shape is: independent fields, only one pair
    populated at a time.
    """

    hub_url: str
    profile: str
    variant: Literal["token", "oauth"]
    version: str
    token: str | None = None
    issuer: str | None = None


def _personalize_manifest(manifest: dict[str, Any], request: BundleRequest) -> dict[str, Any]:
    manifest = dict(manifest)
    manifest["version"] = request.version
    user_config = dict(manifest["user_config"])
    user_config["hub_url"] = {**user_config["hub_url"], "default": request.hub_url}
    user_config["profile"] = {**user_config["profile"], "default": request.profile}
    if request.variant == "oauth":
        user_config["oauth"] = {**user_config["oauth"], "default": True}
        user_config["issuer"] = {**user_config["issuer"], "default": request.issuer}
        # Deliberately no `default` on `token` — the acceptance criterion
        # ("OAuth variant contains no secret at all") is a fact about this
        # dict, checked directly in tests rather than trusted by convention.
    else:
        user_config["oauth"] = {**user_config["oauth"], "default": False}
        user_config["token"] = {**user_config["token"], "default": request.token}
    manifest["user_config"] = user_config
    return manifest


def _run(args: list[str], *, cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise BundleBuildError(
            f"`{' '.join(args)}` failed (exit {result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )


def build_bundle(request: BundleRequest, *, home: Path) -> bytes:
    """Builds, validates, packs and signs one personalized `.mcpb`; returns its bytes."""
    template = template_dir()
    manifest_template = json.loads((template / "manifest.template.json").read_text())
    manifest = _personalize_manifest(manifest_template, request)
    mcpb = mcpb_binary(template)

    with tempfile.TemporaryDirectory(prefix="palaia-mcpb-") as tmp_str:
        tmp = Path(tmp_str)
        staging = tmp / "staging"
        staging.mkdir()
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2))
        shutil.copytree(template / "proxy", staging / "proxy")
        shutil.copy(template / "icon.png", staging / "icon.png")

        _run([mcpb, "validate", str(staging / "manifest.json")], cwd=tmp)

        out_file = tmp / "palaia.mcpb"
        _run([mcpb, "pack", str(staging), str(out_file)], cwd=tmp)

        cert_path, key_path = signing_cert_paths(home)
        _run(
            [mcpb, "sign", "--cert", str(cert_path), "--key", str(key_path), str(out_file)],
            cwd=tmp,
        )

        return out_file.read_bytes()


__all__ = ["BundleBuildError", "BundleRequest", "build_bundle"]
