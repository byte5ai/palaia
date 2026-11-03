"""The hub drops exactly one MCP library error report, nothing else (issue #627).

``server/tests/e2e/test_session_end_log.py`` shows the report gone from a
real hub's log; these tests pin how narrow the filter is.
"""

from __future__ import annotations

import logging

import anyio
import pytest

from palaia_hub.config import HubConfig
from palaia_hub.logging import MCP_TRANSPORT_LOGGER_NAME, setup_logging

_MESSAGE = "Error in standalone SSE writer"


def _log_with(exc: BaseException, message: str = _MESSAGE) -> None:
    try:
        raise exc
    except BaseException:
        logging.getLogger(MCP_TRANSPORT_LOGGER_NAME).exception(message)


@pytest.fixture(autouse=True)
def _hub_logging() -> None:
    setup_logging(HubConfig())


def test_the_session_end_report_is_dropped(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR, logger=MCP_TRANSPORT_LOGGER_NAME):
        _log_with(anyio.ClosedResourceError())
    assert caplog.records == []


def test_the_same_report_with_another_exception_still_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger=MCP_TRANSPORT_LOGGER_NAME):
        _log_with(RuntimeError("the writer broke"))
    assert [r.getMessage() for r in caplog.records] == [_MESSAGE]


def test_a_closed_stream_elsewhere_in_the_transport_still_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger=MCP_TRANSPORT_LOGGER_NAME):
        _log_with(anyio.ClosedResourceError(), message="Error in standalone SSE response")
    assert [r.getMessage() for r in caplog.records] == ["Error in standalone SSE response"]
