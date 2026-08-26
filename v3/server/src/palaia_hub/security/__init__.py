"""Cross-cutting security machinery (SPEC-502).

Three small modules, each the single place one hardening rule is written
down so no caller re-derives it:

* :mod:`palaia_hub.security.files` — the on-disk posture every store shares
  (``0600`` files in a ``0700`` home, SQLite write-ahead siblings included).
* :mod:`palaia_hub.security.headers` — the response headers the browser
  surfaces answer with (content security policy, sniffing, referrer,
  framing, and HSTS where the hub is reachable over TLS).
* :mod:`palaia_hub.security.client_ip` — who a request is *from*, which the
  failed-attempt limiter keys on and which a reverse proxy in front of the
  hub otherwise flattens to one address.

Nothing here holds state or opens anything: this package is policy, applied
by the modules that own the resources.
"""

from __future__ import annotations

from .client_ip import client_ip_for_scope
from .files import (
    DIR_MODE,
    FILE_MODE,
    SQLITE_SIBLING_SUFFIXES,
    enforce_private_mode,
    harden_directory,
    harden_file,
    harden_sqlite_database,
)
from .headers import (
    DASHBOARD_CSP,
    OAUTH_PAGE_CSP,
    SecurityHeadersMiddleware,
)

__all__ = [
    "DASHBOARD_CSP",
    "DIR_MODE",
    "FILE_MODE",
    "OAUTH_PAGE_CSP",
    "SQLITE_SIBLING_SUFFIXES",
    "SecurityHeadersMiddleware",
    "client_ip_for_scope",
    "enforce_private_mode",
    "harden_directory",
    "harden_file",
    "harden_sqlite_database",
]
