"""Shared test fixtures across the whole suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from webhook_receiver import LocalReceiver


@pytest.fixture
def local_receiver() -> Iterator[LocalReceiver]:
    receiver = LocalReceiver()
    receiver.start()
    try:
        yield receiver
    finally:
        receiver.stop()
