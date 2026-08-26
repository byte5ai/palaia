"""palaia-addon-sdk: the third-party add-on author's toolkit (SPEC-406).

Deliberately thin: the manifest an add-on ships *is* the SPEC-303 curated
index entry shape (see :mod:`palaia_addon_sdk.models`), so this package's
job is scaffolding (``init``), validation (``validate``) and an honest
local test loop (``test``) — not a parallel data model. It has no
dependency on ``palaia_hub``; a parity test in the server's own test suite
(``server/tests/market/test_sdk_schema_parity.py``) guards against the two
copies drifting apart.
"""

from __future__ import annotations

__version__ = "0.1.0"
