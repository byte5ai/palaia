"""Issue #409: no curated index is configured by default — the marketplace
serves the bundled entries, says so, and never asks a non-existent host."""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from palaia_hub.config import MarketSettings
from palaia_hub.market.curated import (
    NO_INDEX_NOTE,
    CuratedIndexClient,
    check_index_shape,
    load_starter_index,
)

V3_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.anyio
async def test_no_index_url_serves_the_bundled_entries_without_touching_the_network(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"no request expected, got {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = CuratedIndexClient(client=http, last_good_path=tmp_path / "last_good.json")
        result = await client.fetch()
        again = await client.fetch(force=True)

    assert result.stale is False
    assert result.warning == NO_INDEX_NOTE
    assert [entry.id for entry in result.entries] == ["palaia.fetch", "palaia.filesystem"]
    assert again.entries == result.entries


def test_a_url_without_its_key_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="public key"):
        CuratedIndexClient(index_url="https://index.example.test/market-index.json")


def test_the_bundled_starter_index_is_unsigned_and_well_formed() -> None:
    document = load_starter_index()
    assert "signature" not in document
    check_index_shape(document)
    assert all(entry["kind"] == "container" for entry in document["entries"])


@pytest.mark.parametrize(
    "settings",
    [
        {"index_url": "https://index.example.test/market-index.json"},
        {"public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="},
    ],
)
def test_market_settings_need_url_and_key_together(settings: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="go together"):
        MarketSettings(**settings)


def test_no_placeholder_domain_remains_in_v3() -> None:
    """Acceptance criterion of #409: `palaia.dev` (a domain that does not exist)
    appears nowhere in the shipped tree. The rc1 review document that found it
    is the record of the finding and is left out."""
    # Spelled in two pieces so this file does not match itself.
    pattern = re.compile("palaia" + r"\.dev\b")
    offenders: list[str] = []
    for path in V3_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".py",
            ".json",
            ".md",
            ".ts",
            ".tsx",
            ".yaml",
            ".yml",
            ".mjs",
            ".toml",
            ".html",
        }:
            continue
        parts = path.relative_to(V3_ROOT).parts
        if any(part in {".venv", "node_modules", "dist", "__pycache__"} for part in parts):
            continue
        if path.name.startswith("release-review-") or path == Path(__file__):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(V3_ROOT)))
    assert offenders == []
