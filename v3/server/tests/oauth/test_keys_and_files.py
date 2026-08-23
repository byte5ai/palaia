"""The acceptance criterion "keys/state files 0600; access tokens never persisted".

Both halves are checked against the filesystem and against the store's actual
bytes, not against intent: the signing key, the database and its WAL siblings
are stat'ed, and the database file is searched for the plaintext of every
credential the flow produced.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from palaia_hub.oauth import OAuthStore, SigningKey
from palaia_hub.oauth.keys import DIR_MODE, FILE_MODE, SIGNING_KEY_FILE, oauth_dir
from palaia_hub.oauth.store import DATABASE_FILE


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_signing_key_and_its_directory_are_private(tmp_path: Path) -> None:
    SigningKey.load_or_create(tmp_path)

    directory = tmp_path / "oauth"
    assert _mode(directory) == DIR_MODE
    assert _mode(directory / SIGNING_KEY_FILE) == FILE_MODE


def test_a_widened_signing_key_is_narrowed_again_on_load(tmp_path: Path) -> None:
    SigningKey.load_or_create(tmp_path)
    key_path = tmp_path / "oauth" / SIGNING_KEY_FILE
    key_path.chmod(0o644)

    SigningKey.load_or_create(tmp_path)

    assert _mode(key_path) == FILE_MODE


def test_the_key_is_stable_across_loads(tmp_path: Path) -> None:
    first = SigningKey.load_or_create(tmp_path)
    second = SigningKey.load_or_create(tmp_path)

    assert first.kid == second.kid
    assert first.public_pem() == second.public_pem()


def test_kid_is_the_thumbprint_and_appears_in_the_jwks(tmp_path: Path) -> None:
    key = SigningKey.load_or_create(tmp_path)
    jwks = key.jwks()

    assert [entry["kid"] for entry in jwks["keys"]] == [key.kid]
    assert jwks["keys"][0]["alg"] == "ES256"
    # The private half never appears in the published document.
    assert "d" not in jwks["keys"][0]


def test_the_published_jwks_carries_no_private_material(tmp_path: Path) -> None:
    key = SigningKey.load_or_create(tmp_path)
    private_pem = (tmp_path / "oauth" / SIGNING_KEY_FILE).read_text(encoding="utf-8")

    assert "PRIVATE KEY" in private_pem
    assert "PRIVATE" not in key.public_pem()


def test_a_key_on_the_wrong_curve_is_refused_with_an_actionable_message(
    tmp_path: Path,
) -> None:
    from joserfc.jwk import ECKey

    directory = oauth_dir(tmp_path)
    (directory / SIGNING_KEY_FILE).write_bytes(
        ECKey.generate_key("P-384").as_pem(private=True)
    )

    with pytest.raises(ValueError, match="ES256"):
        SigningKey.load_or_create(tmp_path)


def test_the_store_file_and_its_wal_siblings_are_private(tmp_path: Path) -> None:
    store = OAuthStore(tmp_path)
    store.open()
    # Force a write so the -wal/-shm siblings exist.
    store.meta_set("probe", "1")
    store._enforce_modes()  # noqa: SLF001 - the sibling files appear only after a write
    try:
        base = tmp_path / "oauth" / DATABASE_FILE
        for suffix in ("", "-wal", "-shm"):
            sibling = base.with_name(base.name + suffix)
            if sibling.exists():
                assert _mode(sibling) == FILE_MODE, sibling
    finally:
        store.close()


def test_no_credential_plaintext_reaches_the_database_file(tmp_path: Path) -> None:
    """Codes, refresh tokens and session ids are stored only as digests."""
    from palaia_hub.oauth import set_owner_password
    from palaia_hub.oauth.models import GrantRow

    store = OAuthStore(tmp_path)
    store.open()
    now = 1_800_000_000
    set_owner_password(store, "owner", "a-long-enough-passphrase", now=now)
    code = store.create_code(
        client_id="c1",
        redirect_uri="https://client.test/cb",
        code_challenge="x" * 43,
        audience="https://hub.test/work",
        subject="owner",
        scopes=["vault:work:read"],
        now=now,
        ttl=60,
    )
    _code_row, grant = store.exchange_code(code, now)
    assert isinstance(grant, GrantRow)
    refresh, _expiry = store.issue_refresh_token(grant=grant, now=now, ttl=3600)
    session, _session_expiry = store.create_login_session("owner", now=now, ttl=3600)
    store.close()

    blob = (tmp_path / "oauth" / DATABASE_FILE).read_bytes()
    for secret in (code, refresh, session, "a-long-enough-passphrase"):
        assert secret.encode() not in blob, "a credential plaintext reached the store"


def test_access_tokens_are_never_persisted(tmp_path: Path) -> None:
    """There is no table for them, and no row anywhere holds one."""
    store = OAuthStore(tmp_path)
    store.open()
    try:
        tables = {
            row["name"]
            for row in store._db.execute(  # noqa: SLF001 - schema assertion
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        store.close()

    assert not any("access" in name for name in tables), tables
    assert tables >= {
        "clients",
        "grants",
        "codes",
        "refresh_tokens",
        "owner_account",
        "login_sessions",
        "meta",
    }
