"""SPEC-302 deliverables #1/#5: the upstream schema and loud conflicts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from palaia_hub.gateway.config import GatewayConfig, ProfileConfig, VaultMountConfig
from palaia_hub.upstream.models import (
    UpstreamAuthConfig,
    UpstreamConfig,
    UpstreamConflictError,
    check_namespace_conflicts,
)


def _http(**kwargs: object) -> UpstreamConfig:
    payload: dict[str, object] = {
        "key": "fixture",
        "kind": "http",
        "display_name": "Fixture",
        "url": "https://example.invalid/mcp",
    }
    payload.update(kwargs)
    return UpstreamConfig.model_validate(payload)


def test_the_namespace_defaults_to_the_key_with_dashes_turned_into_underscores() -> None:
    assert _http(key="my-server").mount_namespace == "my_server"
    assert _http(namespace="linear").mount_namespace == "linear"


def test_an_http_upstream_needs_a_url_and_refuses_a_command() -> None:
    with pytest.raises(ValidationError):
        UpstreamConfig(key="x", kind="http", display_name="X")
    with pytest.raises(ValidationError):
        _http(command="/bin/true")


def test_a_stdio_upstream_needs_a_command_and_refuses_url_or_headers() -> None:
    with pytest.raises(ValidationError):
        UpstreamConfig(key="x", kind="stdio", display_name="X")
    with pytest.raises(ValidationError):
        UpstreamConfig(
            key="x",
            kind="stdio",
            display_name="X",
            command="/bin/true",
            url="https://example.invalid/mcp",
        )
    with pytest.raises(ValidationError):
        UpstreamConfig(
            key="x",
            kind="stdio",
            display_name="X",
            command="/bin/true",
            auth=UpstreamAuthConfig(secret_name="t"),
        )


def test_env_secrets_are_refused_on_an_http_upstream() -> None:
    with pytest.raises(ValidationError):
        _http(env_secrets={"TOKEN": "t"})


def test_a_bad_namespace_is_an_error_not_a_silent_sanitization() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _http(namespace="My Server!")
    assert "namespace" in str(excinfo.value)


def test_an_auth_template_must_say_where_the_secret_goes() -> None:
    with pytest.raises(ValidationError):
        UpstreamAuthConfig(secret_name="t", value_template="Bearer nothing-here")


def test_the_target_line_is_credential_free() -> None:
    http = _http(auth=UpstreamAuthConfig(secret_name="linear-token"))
    assert http.target == "https://example.invalid/mcp"
    stdio = UpstreamConfig(
        key="box",
        kind="stdio",
        display_name="Box",
        command="/usr/bin/mcp",
        args=["--stdio"],
        env_secrets={"TOKEN": "box-token"},
    )
    assert stdio.target == "/usr/bin/mcp --stdio"
    assert "box-token" not in stdio.target


def test_two_upstreams_claiming_one_namespace_are_refused_loudly() -> None:
    with pytest.raises(UpstreamConflictError) as excinfo:
        check_namespace_conflicts(
            [_http(key="a", namespace="shared"), _http(key="b", namespace="shared")]
        )
    assert "shared" in str(excinfo.value)
    assert "'a'" in str(excinfo.value) and "'b'" in str(excinfo.value)


def test_an_upstream_may_not_shadow_a_vault_tool_family() -> None:
    with pytest.raises(ValidationError) as excinfo:
        GatewayConfig(
            vaults=[VaultMountConfig(key="work", name="work", purpose="Work.")],
            upstreams=[_http(namespace="work_memory")],
        )
    assert "work_memory" in str(excinfo.value)


def test_a_disabled_upstream_still_owns_its_namespace() -> None:
    """Otherwise switching it back on later would surprise someone with a
    conflict that was not there when they configured the second server."""
    with pytest.raises(UpstreamConflictError):
        check_namespace_conflicts(
            [
                _http(key="a", namespace="shared", enabled=False),
                _http(key="b", namespace="shared"),
            ]
        )


def test_a_profile_may_not_reference_an_unknown_upstream() -> None:
    with pytest.raises(ValidationError) as excinfo:
        GatewayConfig(
            profiles=[ProfileConfig(path="default", upstreams=["ghost"])],
        )
    assert "ghost" in str(excinfo.value)


def test_duplicate_upstream_keys_are_refused() -> None:
    with pytest.raises(ValidationError):
        GatewayConfig(upstreams=[_http(key="a"), _http(key="a", namespace="other")])
