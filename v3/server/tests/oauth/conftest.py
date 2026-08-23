"""Shared fixtures for the SPEC-203 tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from palaia_hub.oauth import OAuthStore, SigningKey

from .harness import Harness, build_harness


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def harness(tmp_path: Path) -> Iterator[Harness]:
    built = build_harness(tmp_path)
    try:
        yield built
    finally:
        built.store.close()


@pytest.fixture
def store(tmp_path: Path) -> Iterator[OAuthStore]:
    """A bare, opened store for the unit-level tests."""
    opened = OAuthStore(tmp_path)
    opened.open()
    try:
        yield opened
    finally:
        opened.close()


@pytest.fixture
def signing_key(tmp_path: Path) -> SigningKey:
    return SigningKey.load_or_create(tmp_path)
