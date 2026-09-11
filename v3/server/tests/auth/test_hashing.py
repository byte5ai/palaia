"""Issue #396: `verify_secret` never raises for a caller-facing reason."""

from __future__ import annotations

import pytest

from palaia_hub.auth.hashing import hash_secret, verify_secret


@pytest.mark.parametrize("stored", ["", "not-a-hash", "$argon2id$v=19$m=1,t=1,p=1$$"])
def test_a_malformed_stored_hash_is_a_mismatch_not_an_exception(stored: str) -> None:
    assert verify_secret("pw", stored) is False


def test_a_real_hash_still_verifies() -> None:
    assert verify_secret("pw", hash_secret("pw")) is True
    assert verify_secret("other", hash_secret("pw")) is False
