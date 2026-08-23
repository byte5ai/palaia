"""``anyio_backend`` fixture for the ``@pytest.mark.anyio`` async tests below."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
