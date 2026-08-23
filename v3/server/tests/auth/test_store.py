"""TokenStore: create/list/revoke/verify, hashing, rotation, persistence."""

from __future__ import annotations

from pathlib import Path

import pytest

from palaia_hub.auth.store import TokenError, TokenStore


def test_create_returns_plaintext_once_and_it_verifies(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)

    created = store.create("Codex on devbox", "default", ["vault:work:read"])

    assert created.token.startswith("plt_")
    assert created.info.name == "Codex on devbox"
    assert created.info.profile == "default"
    assert created.info.scopes == ["vault:work:read"]
    assert created.info.revoked_at is None

    record = store.verify(created.token)
    assert record is not None
    assert record.id == created.info.id
    assert record.name == "Codex on devbox"


def test_only_the_hash_is_ever_written_to_disk(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("Codex on devbox", "default", ["vault:work:read"])

    raw = store.store_path.read_text(encoding="utf-8")

    # The plaintext token and its bare secret half never appear in storage.
    assert created.token not in raw
    secret_half = created.token.split(".", 1)[1]
    assert secret_half not in raw
    # ...but an argon2id hash does.
    assert "$argon2id$" in raw


def test_wrong_secret_does_not_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    token_id = created.token.removeprefix("plt_").split(".", 1)[0]

    forged = f"plt_{token_id}.wrong-secret-wrong-secret-wrong12"

    assert store.verify(forged) is None


def test_unknown_token_id_does_not_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    store.create("client", "default", [])

    assert store.verify("plt_totally-unknown-id.some-secret-value-here") is None


def test_malformed_token_does_not_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    assert store.verify("not-a-palaia-token") is None
    assert store.verify("") is None


def test_rotation_new_token_works_old_fails_immediately(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    old = store.create("client", "default", ["vault:work:read"])

    assert store.verify(old.token) is not None

    new = store.create("client (rotated)", "default", ["vault:work:read"])
    store.revoke(old.info.id)

    assert store.verify(old.token) is None
    assert store.verify(new.token) is not None


def test_revoke_is_idempotent(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])

    first = store.revoke(created.info.id)
    second = store.revoke(created.info.id)

    assert first.revoked_at is not None
    assert second.revoked_at == first.revoked_at


def test_revoke_unknown_id_raises_token_error(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    with pytest.raises(TokenError, match="no token with id"):
        store.revoke("does-not-exist")


def test_list_tokens_never_exposes_hash_or_secret(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    store.create("client", "default", ["vault:work:read"])

    infos = store.list_tokens()

    assert len(infos) == 1
    assert not hasattr(infos[0], "hash")
    assert "hash" not in infos[0].model_dump()


def test_invalid_scope_format_is_rejected(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    with pytest.raises(TokenError, match="invalid scope"):
        store.create("client", "default", ["not-a-real-scope"])


def test_empty_name_or_profile_is_rejected(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    with pytest.raises(TokenError):
        store.create("", "default", [])
    with pytest.raises(TokenError):
        store.create("client", "", [])


def test_store_persists_across_instances(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", ["vault:work:write"])

    reloaded = TokenStore(home=tmp_path)

    record = reloaded.verify(created.token)
    assert record is not None
    assert record.name == "client"


def test_list_tokens_reports_last_used_only_after_a_successful_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])

    before = store.list_tokens()[0]
    assert before.last_used_at is None

    store.verify(created.token)

    after = store.get(created.info.id)
    assert after.last_used_at is not None


def test_last_used_at_is_not_persisted_to_disk(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    store.verify(created.token)
    assert store.get(created.info.id).last_used_at is not None

    reloaded = TokenStore(home=tmp_path)

    assert reloaded.get(created.info.id).last_used_at is None


def test_failed_verify_does_not_stamp_last_used(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    token_id = created.token.removeprefix("plt_").split(".", 1)[0]

    store.verify(f"plt_{token_id}.wrong-secret-wrong-secret-wrong12")

    assert store.get(created.info.id).last_used_at is None


def test_malformed_store_file_reports_fix(tmp_path: Path) -> None:
    (tmp_path / "tokens.yaml").write_text("not: [a, valid, token, file\n", encoding="utf-8")

    with pytest.raises(TokenError, match="Fix"):
        TokenStore(home=tmp_path)


# --- SPEC-201: the "client.connected" hub-event hook point --------------


def test_on_verified_fires_only_on_the_first_successful_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    calls: list[tuple[str, bool]] = []
    store.on_verified = lambda record, is_first: calls.append((record.id, is_first))

    store.verify(created.token)
    store.verify(created.token)

    assert calls == [(created.info.id, True), (created.info.id, False)]


def test_on_verified_does_not_fire_on_a_failed_verify(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])
    token_id = created.token.removeprefix("plt_").split(".", 1)[0]
    calls: list[tuple[str, bool]] = []
    store.on_verified = lambda record, is_first: calls.append((record.id, is_first))

    store.verify(f"plt_{token_id}.wrong-secret-wrong-secret-wrong12")

    assert calls == []


def test_a_raising_on_verified_hook_does_not_break_verification(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)
    created = store.create("client", "default", [])

    def bad(_record: object, _is_first: bool) -> None:
        raise RuntimeError("boom")

    store.on_verified = bad

    record = store.verify(created.token)

    assert record is not None
    assert record.id == created.info.id
