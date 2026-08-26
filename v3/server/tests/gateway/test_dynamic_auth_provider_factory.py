"""SPEC-504 first-run funnel audit fix: :class:`DynamicGateway`'s
``auth_provider_factory`` (see that class's own docstring, and
``palaia_hub.serve.build_production_app``'s ``_auth_provider_for``, for the
bug this closes: a brand-new profile path — the wizard's very first vault,
on every fresh install — mounted with no verifier at all, silently
unauthenticated, because ``token_verifiers`` built at construction time
could not have known about a path that did not exist yet).
"""

from __future__ import annotations

import pytest
from fastmcp.server.auth import AccessToken, TokenVerifier

from palaia_hub.gateway.config import GatewayConfig, VaultMountConfig
from palaia_hub.gateway.dynamic import DynamicGateway
from palaia_hub.gateway.fake_vault import FakeVaultService

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _StubVerifier(TokenVerifier):
    """A minimal real ``TokenVerifier`` (fastmcp mounts it onto a live
    ``FastMCP`` server via ``AuthProvider.get_middleware()``, so a bare
    stand-in object is not enough) — this suite never sends a request
    through it, only checks whether :class:`DynamicGateway` decided to
    attach one."""

    async def verify_token(self, token: str) -> AccessToken | None:
        return None


async def test_a_brand_new_profile_path_asks_the_factory() -> None:
    calls: list[str] = []

    def factory(path: str) -> _StubVerifier:
        calls.append(path)
        return _StubVerifier()

    gateway = DynamicGateway(GatewayConfig(), {}, auth_provider_factory=factory)
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work", purpose="Work vault."),
        FakeVaultService(),
        profile_paths=["default"],
    )

    assert calls == ["default"]
    assert isinstance(gateway._token_verifiers["default"], _StubVerifier)  # noqa: SLF001

    await gateway.aclose()


async def test_the_factory_is_called_once_then_cached() -> None:
    calls: list[str] = []

    def factory(path: str) -> _StubVerifier:
        calls.append(path)
        return _StubVerifier()

    gateway = DynamicGateway(GatewayConfig(), {}, auth_provider_factory=factory)
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work"), FakeVaultService(), profile_paths=["default"]
    )
    await gateway.add_vault(
        VaultMountConfig(key="personal", name="personal"),
        FakeVaultService(),
        profile_paths=["default"],
    )

    # Same path, added to twice — the factory is consulted only the first
    # time a path has no verifier yet, never again once one is cached.
    assert calls == ["default"]

    await gateway.aclose()


async def test_a_factory_returning_none_leaves_the_path_unauthenticated() -> None:
    """The pre-SPEC-504 posture (``auth_enabled: false``) must keep
    working exactly as before: the factory itself decides "nothing to
    verify with" by returning ``None``, and this class must not invent a
    verifier it was not given."""

    def factory(path: str) -> None:
        return None

    gateway = DynamicGateway(GatewayConfig(), {}, auth_provider_factory=factory)
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work"), FakeVaultService(), profile_paths=["default"]
    )

    assert "default" not in gateway._token_verifiers  # noqa: SLF001

    await gateway.aclose()


async def test_no_factory_at_all_preserves_pre_spec504_behavior() -> None:
    """``auth_provider_factory`` is optional — every call site that never
    passes one (every direct ``DynamicGateway(...)`` construction in this
    test suite, and any future one) must see exactly the old behavior: a
    brand-new path simply has no verifier."""
    gateway = DynamicGateway(GatewayConfig(), {})
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work"), FakeVaultService(), profile_paths=["default"]
    )

    assert "default" not in gateway._token_verifiers  # noqa: SLF001

    await gateway.aclose()


async def test_an_existing_verifier_is_never_overwritten_by_the_factory() -> None:
    """Editing an already-authenticated profile (adding a second vault to
    it) must not silently swap in a different verifier instance — the
    factory is only ever consulted for a path with *no* entry yet."""
    calls: list[str] = []

    def factory(path: str) -> _StubVerifier:
        calls.append(path)
        return _StubVerifier()

    preexisting = _StubVerifier()
    gateway = DynamicGateway(
        GatewayConfig(),
        {},
        token_verifiers={"default": preexisting},  # type: ignore[dict-item]
        auth_provider_factory=factory,
    )
    await gateway.start()

    await gateway.add_vault(
        VaultMountConfig(key="work", name="work"), FakeVaultService(), profile_paths=["default"]
    )

    assert calls == []
    assert gateway._token_verifiers["default"] is preexisting  # noqa: SLF001

    await gateway.aclose()
