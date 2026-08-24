"""External MCP servers behind the gateway (SPEC-302).

**No imports here, on purpose.** :mod:`palaia_hub.config` imports
:class:`palaia_hub.upstream.models.UpstreamConfig` directly, and config
loading must never drag fastmcp or a transport layer in behind it (see
``models.py``'s docstring). Importing this package therefore costs nothing;
callers reach for the submodule they actually need:

- :mod:`palaia_hub.upstream.models` — the config schema (fastmcp-free).
- :mod:`palaia_hub.upstream.secrets` — the encrypted credential store.
- :mod:`palaia_hub.upstream.service` — connecting, probing and proxying
  (this one pulls fastmcp).
- :mod:`palaia_hub.upstream.monitor` — the periodic health probe.
- :mod:`palaia_hub.upstream.api` — the REST surface.
"""

from __future__ import annotations
