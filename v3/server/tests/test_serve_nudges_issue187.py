"""Issue #187: ``build_production_app`` hands the ``nudges:`` section to every
vault's service — a setting that parses but never reaches the adapter is a
setting that silently does nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from palaia_hub import serve
from palaia_hub.config import load_config
from palaia_hub.serve import build_production_app
from palaia_hub.vault import VaultRegistry


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ("nudges:\n  similar_note_threshold: 0.8\n", 0.8),
        ("nudges:\n  similar_note_check: false\n", None),
    ],
)
async def test_the_nudges_section_reaches_every_vault_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, section: str, expected: float | None
) -> None:
    registry = VaultRegistry(tmp_path)
    await registry.create("work", tmp_path / "vaults" / "work", purpose="work vault.")
    (tmp_path / "config.yaml").write_text(
        "mode: locked\nauth_enabled: false\n" + section, encoding="utf-8"
    )
    config = load_config(home=tmp_path, create_if_missing=False)

    built: list[dict[str, Any]] = []
    real = serve.EngineVaultService

    def spy(*args: Any, **kwargs: Any) -> Any:
        built.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(serve, "EngineVaultService", spy)
    production = await build_production_app(config, home=tmp_path)
    try:
        assert [kwargs.get("similar_note_threshold", "unset") for kwargs in built] == [expected]
    finally:
        await production.dynamic_gateway.aclose()
        if production.stash_store is not None:
            production.stash_store.close()
        if production.directory_store is not None:
            production.directory_store.close()
        if production.messenger_store is not None:
            production.messenger_store.close()
        for index in production.indexes.values():
            await index.close()
