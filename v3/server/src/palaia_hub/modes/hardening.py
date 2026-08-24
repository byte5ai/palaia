"""Open-mode hardening checklist (SPEC-205 deliverable #4).

MASTERPLAN §5.5: 'open' mode is the one where the operator "consciously
wants the dashboard itself on the internet" — its auth table entry reads
"Mandatory + hardening checklist". Each item below is either checked for
real against the running hub's own config/state (``auto=True``) or stated
honestly as something only the operator can confirm (``auto=False``,
``passed=None``) — this module never marks an item green it did not
actually check, matching the wizard's public-URL self-test's own "no fake
green" rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import HubConfig
from .selftest import SelfTestResult


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    id: str
    title: str
    detail: str
    #: True: the hub checked this itself, ``passed`` is authoritative.
    #: False: the hub cannot check this — the operator must confirm it
    #: manually, and ``passed`` is always ``None``.
    auto: bool
    passed: bool | None


def build_checklist(
    config: HubConfig,
    *,
    rate_limiting_active: bool,
    last_self_test: SelfTestResult | None = None,
    owner_account_configured: bool | None = None,
) -> list[ChecklistItem]:
    """Build the checklist for ``config``'s current/candidate mode.

    Args:
        rate_limiting_active: whether the rate-limit middleware is actually
            mounted on the running app (:mod:`palaia_hub.modes.rate_limit`)
            — always true for a hub built in cloud/open, so this is really
            "did the caller pass the live app's own answer", not a config
            re-derivation.
        last_self_test: the most recent public-URL self-test result, if the
            wizard has run one this session. ``None`` renders as "not run
            yet" rather than as a failure.
        owner_account_configured: whether a local owner account exists
            (``palaia-hub oauth set-password``) — the caller looks this up
            against the OAuth store, since this module has no store access
            of its own. ``None`` when the caller cannot check (no OAuth
            store mounted), rendered as manual.
    """
    items: list[ChecklistItem] = []

    items.append(
        ChecklistItem(
            id="auth_mandatory",
            title="Authentication is required",
            detail="Every MCP client must present a bearer token or an OAuth access token.",
            auto=True,
            passed=config.auth_enabled or config.oauth.enabled,
        )
    )
    items.append(
        ChecklistItem(
            id="rate_limited",
            title="Auth endpoints are rate-limited",
            detail="Sign-in, token, and client-registration endpoints throttle repeated attempts.",
            auto=True,
            passed=rate_limiting_active,
        )
    )

    if last_self_test is None:
        items.append(
            ChecklistItem(
                id="tls",
                title="The public URL serves valid TLS",
                detail="Run the self-test below to confirm — not checked yet.",
                auto=False,
                passed=None,
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="tls",
                title="The public URL serves valid TLS",
                detail=(
                    f"Last self-test against {last_self_test.checked_url}: "
                    + ("reachable over a valid TLS handshake." if last_self_test.reachable else
                       f"not reachable ({last_self_test.error})")
                ),
                auto=True,
                passed=last_self_test.reachable,
            )
        )

    if owner_account_configured is None:
        items.append(
            ChecklistItem(
                id="owner_account",
                title="The owner account has its own password",
                detail=(
                    "Confirm you have run `palaia-hub oauth set-password` yourself and are "
                    "not relying on a default credential."
                ),
                auto=False,
                passed=None,
            )
        )
    else:
        items.append(
            ChecklistItem(
                id="owner_account",
                title="The owner account has its own password",
                detail="A local owner account is configured.",
                auto=True,
                passed=owner_account_configured,
            )
        )

    items.append(
        ChecklistItem(
            id="dashboard_exposure_acknowledged",
            title="You understand the admin dashboard itself is now public",
            detail=(
                "'open' mode puts vault contents, tokens, and hooks management on the public "
                "internet, not just the memory endpoints. Only pick this mode if you mean it — "
                "'cloud' mode gives claude.ai/ChatGPT/phone access while keeping the dashboard "
                "on your VPN/tailnet."
            ),
            auto=False,
            passed=None,
        )
    )
    return items


__all__ = ["ChecklistItem", "build_checklist"]
