from __future__ import annotations

from pathlib import Path

from palaia_hub.auth.store import TokenStore
from palaia_hub.auth.verifier import PalaiaTokenVerifier
from palaia_hub.auth.wiring import build_profile_verifiers


def test_builds_one_verifier_per_profile_path_sharing_the_store(tmp_path: Path) -> None:
    store = TokenStore(home=tmp_path)

    verifiers = build_profile_verifiers(["alpha", "beta"], store)

    assert set(verifiers) == {"alpha", "beta"}
    assert all(isinstance(v, PalaiaTokenVerifier) for v in verifiers.values())
    assert verifiers["alpha"]._store is store
    assert verifiers["alpha"]._profile == "alpha"
    assert verifiers["beta"]._profile == "beta"
