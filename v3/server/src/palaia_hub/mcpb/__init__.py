"""MCPB bundle packaging and the connect page's Claude Desktop download.

SPEC-306. Public surface:

- :func:`~palaia_hub.mcpb.builder.build_bundle` / :class:`~palaia_hub.mcpb.
  builder.BundleRequest` — personalize the packaged template into one
  signed `.mcpb`, via the official `mcpb` CLI (never a hand-rolled zip or
  signature format).
- :func:`~palaia_hub.mcpb.routes.build_mcpb_router` — the
  ``/api/connect/mcpb`` download endpoint, mounted by
  :func:`palaia_hub.app.create_app`.
- :mod:`palaia_hub.mcpb.signing` — the hub's own persistent MCPB signing
  identity.
- :mod:`palaia_hub.mcpb.template` — locates ``v3/tools/build-mcpb`` (the
  proxy script, manifest template, icon, and `mcpb` CLI) from a running
  hub process, in both a dev checkout and the packaged Docker image.
"""

from __future__ import annotations

from .builder import BundleBuildError, BundleRequest, build_bundle
from .routes import MCPB_PATH, build_mcpb_router
from .template import TemplateNotFoundError, mcpb_binary, template_dir

__all__ = [
    "MCPB_PATH",
    "BundleBuildError",
    "BundleRequest",
    "TemplateNotFoundError",
    "build_bundle",
    "build_mcpb_router",
    "mcpb_binary",
    "template_dir",
]
