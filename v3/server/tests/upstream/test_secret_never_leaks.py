"""SPEC-302 acceptance criterion #2, the redaction half: a stored value never
appears in a log line, an error message, or an event payload.

The hub's own :class:`~palaia_hub.logging.RedactionFilter` is a *second* line
of defense; the first is that nothing in the upstream package ever passes a
value to a logger or an exception in the first place. Both are asserted here:
the raw records captured during a full connect-probe-call cycle, and the same
records after the production filter has run over them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from palaia_hub.logging import RedactionFilter, redact
from palaia_hub.upstream.models import UpstreamAuthConfig, UpstreamConfig
from palaia_hub.upstream.secrets import SecretStore
from palaia_hub.upstream.service import UpstreamService

from .conftest import FIXTURE_BEARER_TOKEN, HttpUpstream

pytestmark = pytest.mark.anyio

SECRET = "sk-canary-value-must-never-be-logged-31337"


async def test_no_log_line_from_a_full_cycle_contains_the_value(
    tmp_path: Path, http_upstream_with_token: HttpUpstream, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    store = SecretStore(tmp_path / "home")
    store.put("fixture-token", FIXTURE_BEARER_TOKEN)
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream_with_token.url,
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
    )
    service = UpstreamService([upstream], secret_store=store)
    try:
        status = await service.probe("fixture")
        assert status.up is True
        await service.proxy_for("fixture")
    finally:
        await service.aclose()
        store.close()

    messages = [record.getMessage() for record in caplog.records]
    joined = "\n".join(messages)
    assert FIXTURE_BEARER_TOKEN not in joined
    # And the production filter would have caught it even if it had been
    # there — asserted on a deliberately leaky line so the test proves the
    # filter works rather than merely that nothing leaked.
    assert FIXTURE_BEARER_TOKEN not in redact(
        f"Authorization: Bearer {FIXTURE_BEARER_TOKEN}"
    )
    filtered = RedactionFilter()
    for record in caplog.records:
        assert filtered.filter(record) is True
        assert FIXTURE_BEARER_TOKEN not in record.getMessage()


async def test_a_failure_message_names_the_secret_not_its_value(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "home")
    store.put("fixture-token", SECRET)
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        # Nothing listening — the failure text is what is under test.
        url="http://127.0.0.1:9/mcp/",
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
        connect_timeout=2.0,
    )
    service = UpstreamService([upstream], secret_store=store)
    try:
        status = await service.probe("fixture")
    finally:
        await service.aclose()
        store.close()

    assert status.up is False
    assert SECRET not in status.detail


async def test_no_event_payload_carries_a_value(
    tmp_path: Path, http_upstream_with_token: HttpUpstream
) -> None:
    published: list[tuple[str, dict[str, object]]] = []
    store = SecretStore(tmp_path / "home")
    store.put("fixture-token", FIXTURE_BEARER_TOKEN)
    upstream = UpstreamConfig(
        key="fixture",
        kind="http",
        display_name="Fixture server",
        url=http_upstream_with_token.url,
        auth=UpstreamAuthConfig(secret_name="fixture-token"),
    )
    service = UpstreamService(
        [upstream],
        secret_store=store,
        publish=lambda event, data: published.append((event, data)),
    )
    try:
        await service.probe("fixture")
    finally:
        await service.aclose()
        store.close()

    assert published
    assert FIXTURE_BEARER_TOKEN not in repr(published)


async def test_the_status_shape_has_nowhere_to_put_a_value(
    tmp_path: Path, http_upstream: HttpUpstream
) -> None:
    """Structural, not behavioral: the status dataclass's field set is fixed,
    so a future change cannot start carrying a credential by accident."""
    from palaia_hub.upstream.service import UpstreamStatus

    assert set(UpstreamStatus.__dataclass_fields__) == {
        "key",
        "display_name",
        "namespace",
        "kind",
        "enabled",
        "target",
        "up",
        "detail",
        "checked_at",
        "tools",
    }
