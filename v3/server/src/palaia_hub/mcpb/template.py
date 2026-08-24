"""Locates the MCPB build tooling: the packaged template and the `mcpb` CLI.

``/api/connect/mcpb`` (:mod:`palaia_hub.mcpb.routes`) does not carry its
own copy of the proxy script, the manifest template, the icon, or the
`mcpb` CLI — it reuses exactly what CI builds and validates
(``v3/tools/build-mcpb``, SPEC-306 deliverable #2), which is what
deliverable #4's "assembled server-side from the packaged template" means:
one template, two consumers (a CI job that signs it once for the record,
and the hub that personalizes-and-signs a fresh copy per download).

Two ways this directory reaches a running hub:

- **Dev / editable install**: ``palaia_hub`` runs straight out of the
  repository checkout (``uv sync``'s default), so
  ``v3/tools/build-mcpb`` is a fixed number of parents up from this file —
  :func:`_repo_relative_guess` below.
- **The packaged Docker image** (SPEC-112/deploy): the hub's venv is built
  ``--no-editable`` and copied to a path with no repository around it at
  all, so the Dockerfile ``COPY``s ``v3/tools/build-mcpb`` alongside it and
  ``PALAIA_MCPB_TEMPLATE_DIR`` names exactly where — set once in the
  image, never guessed.

``PALAIA_MCPB_TEMPLATE_DIR`` always wins when set; the dev-checkout guess
is the fallback, so nothing here silently succeeds against a stale or
unrelated directory — a checkout that fails the guess (e.g. this file
copied elsewhere without the rest of the repo) raises a clear error naming
the fix, rather than shipping an empty or wrong bundle.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class TemplateNotFoundError(Exception):
    """Raised when the MCPB build template cannot be located."""


def _repo_relative_guess() -> Path:
    """``v3/tools/build-mcpb``, assuming this file still lives under
    ``v3/server/src/palaia_hub/mcpb/`` in a checkout of the repository."""
    # parents: [0] mcpb/, [1] palaia_hub/, [2] src/, [3] server/, [4] v3/
    return Path(__file__).resolve().parents[4] / "tools" / "build-mcpb"


def template_dir(env: dict[str, str] | None = None) -> Path:
    """The directory holding ``manifest.template.json``, ``proxy/``, ``icon.png``.

    Raises:
        TemplateNotFoundError: neither ``PALAIA_MCPB_TEMPLATE_DIR`` nor the
            dev-checkout guess names a directory containing
            ``manifest.template.json``.
    """
    env = env if env is not None else dict(os.environ)
    override = env.get("PALAIA_MCPB_TEMPLATE_DIR")
    candidates = [Path(override)] if override else [_repo_relative_guess()]
    for candidate in candidates:
        if (candidate / "manifest.template.json").is_file():
            return candidate
    raise TemplateNotFoundError(
        "could not find the MCPB build template (manifest.template.json, proxy/, "
        f"icon.png). Looked in: {[str(c) for c in candidates]}. Fix: set "
        "PALAIA_MCPB_TEMPLATE_DIR to v3/tools/build-mcpb (or wherever it was "
        "copied to in this deployment)."
    )


def mcpb_binary(template: Path, env: dict[str, str] | None = None) -> str:
    """Path to the `mcpb` CLI: a local devDependency install first (``npm
    ci`` in ``template``), else whatever `mcpb` is on ``PATH``.

    Raises:
        TemplateNotFoundError: neither is available.
    """
    env = env if env is not None else dict(os.environ)
    override = env.get("PALAIA_MCPB_BIN")
    if override:
        return override
    local = template / "node_modules" / ".bin" / "mcpb"
    if local.exists():
        return str(local)
    found = shutil.which("mcpb")
    if found:
        return found
    raise TemplateNotFoundError(
        f"the `mcpb` CLI is not available (checked {local} and PATH). Fix: run "
        f"`npm ci` in {template}, or set PALAIA_MCPB_BIN to an `mcpb` executable."
    )


__all__ = ["TemplateNotFoundError", "mcpb_binary", "template_dir"]
