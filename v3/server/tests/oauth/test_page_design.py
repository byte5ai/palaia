"""The server-rendered sign-in, consent and error pages follow the design
system (issues #570, #571).

They cannot load the dashboard's stylesheet — they are served before any
session exists, possibly without a dashboard build, under a policy that
fetches nothing — so they carry the token values inline. This keeps those
values equal to ``v3/design/tokens.json``, the one source the dashboard and
the docs site are generated from.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from palaia_hub.oauth.errors import OAuthError
from palaia_hub.oauth.routes import (
    _PAGE_COLORS,
    _authorize_error_page,
    _login_page,
)

TOKENS = Path(__file__).resolve().parents[3] / "design" / "tokens.json"


def _token_colors() -> dict[str, tuple[str, str]]:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    return {
        token["name"]: (token["value"]["light"], token["value"]["dark"])
        for token in data["color"]["tokens"]
    }


def test_every_page_colour_is_the_design_token_of_the_same_name() -> None:
    tokens = _token_colors()
    for name, (light, dark) in _PAGE_COLORS.items():
        assert name in tokens, f"{name} is not a token in tokens.json"
        assert (light, dark) == tokens[name], name


def test_the_sign_in_page_is_styled_for_light_and_dark_and_fetches_nothing() -> None:
    page = _login_page(next_url="/", csrf="x", error="")
    assert "prefers-color-scheme: dark" in page
    for name, (light, dark) in _PAGE_COLORS.items():
        assert f"--{name}: {light};" in page
        assert f"--{name}: {dark};" in page
    # Inline styles and inline SVG only: nothing for OAUTH_PAGE_CSP to block.
    assert "<script" not in page
    assert re.search(r'(src|href)="https?://', page) is None
    assert "@import" not in page and "url(" not in page


def test_the_sign_in_page_says_how_to_reset_a_forgotten_password() -> None:
    page = _login_page(next_url="/", csrf="x", error="")
    assert "<summary>Forgot your password?</summary>" in page
    assert "palaia oauth set-password --username" in page
    assert "docker exec -it palaia palaia oauth set-password" in page


def test_the_error_page_leads_with_the_explanation_not_the_code() -> None:
    response = _authorize_error_page(
        OAuthError("invalid_request", "this sign-in link is invalid. Fix: start again.")
    )
    body = bytes(response.body).decode("utf-8")
    assert body.index("this sign-in link is invalid") < body.index("invalid_request")
    assert "<h1>Can&#x27;t continue</h1>" in body or "<h1>Can't continue</h1>" in body


def test_the_sign_in_page_uses_the_typeface_and_the_radii_of_the_tokens() -> None:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    typeface = data["type"]["families"]["sans"].split(",")[0].strip().strip('"')
    radii = {token["value"] for token in data["radius"]["tokens"]}
    page = _login_page(next_url="/", csrf="x", error="")
    assert f'"{typeface}", system-ui' in page
    used = set(re.findall(r"border-radius:\s*([0-9.]+px)", page))
    assert used, "the page states no radius at all"
    assert used <= radii, f"radii outside tokens.json: {sorted(used - radii)}"


def test_the_sign_in_page_uses_the_sizes_of_the_tokens() -> None:
    """Title, control height and the phone control height come from
    ``tokens.json`` like everything else on the page."""
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    styles = {s["name"]: s for group in data["type"]["groups"] for s in group["styles"]}
    sizes = {token["name"]: token for token in data["size"]["tokens"]}
    title = styles["title-1"]
    control = sizes["control-height"]
    phone = next(b for b in data["breakpoints"] if b["name"] == "phone")
    page = _login_page(next_url="/", csrf="x", error="")
    assert (
        f"h1 {{ font-size: {title['fontSize']}; line-height: {title['lineHeight']}; "
        f"font-weight: {title['fontWeight']};"
    ) in page
    assert f"height: {control['value']}; margin-top" in page
    assert f"button {{ height: {control['value']};" in page
    phone_rule = f"input, button {{ height: {control['phone']}; }}"
    assert f"@media (max-width: {phone['max']}px) {{ {phone_rule} }}" in page
