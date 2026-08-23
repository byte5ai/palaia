"""Fixtures for the importer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def v2_store_fixture() -> Path:
    return FIXTURES / "import-v2"


@pytest.fixture
def bm_vault_fixture() -> Path:
    return FIXTURES / "import-basic-memory"
