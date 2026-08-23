"""Composition helpers for the inbox/capture contract (SPEC-107).

Reference: ``v3/docs/vault-format.md`` §7 — a capture is a note a busy agent
can drop without knowing the vault taxonomy. This module owns the *shape* of
that note (frontmatter extras, canonical body, ``capture_id`` derivation,
exact-duplicate hashing) as pure functions with no I/O.

Deliberately free of any ``palaia_hub.vault`` import — same isolation rule as
:mod:`palaia_hub.gateway.vault_protocol` (see that module's docstring): both
:class:`~palaia_hub.gateway.fake_vault.FakeVaultService` and a future real
adapter over :class:`palaia_hub.vault.engine.VaultEngine` (SPEC-113) call
into these functions so the composed note has exactly one definition. The
real-engine integration test (``tests/gateway/test_inbox_real_vault.py``)
drives ``VaultEngine.write_note`` directly with this module's output to prove
the result is format-spec valid end to end, without this package depending
on the vault engine itself.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

#: Format spec §7: ``capture_id = "cap-" + sha256(permalink)[:10]``.
CAPTURE_ID_PREFIX = "cap-"

#: The three mandatory ``capture`` tool fields (deliverable #1). ``source``
#: is optional and defaults via :func:`default_source`.
MANDATORY_CAPTURE_FIELDS: tuple[str, ...] = ("what_it_concerns", "why_keep", "content")

_EXAMPLE_CALL = (
    "capture(what_it_concerns='API Gateway', "
    "why_keep='The rate limit was chosen deliberately; future work will trip over "
    "it otherwise.', "
    "content='We capped ingest at 100 req/min because the embed queue saturates "
    "above that; raising it requires batching first.')"
)

# The `[capture_hash]` bullet this module appends to every capture body (see
# `compose_capture_body`) so an exact-duplicate re-capture can be recognized
# just by reading a note back — no side index needed, and no schema key the
# format spec does not already reserve as free-form body content.
_CAPTURE_HASH_RE = re.compile(r"^- \[capture_hash\] (?P<hash>[0-9a-f]+)\s*$", re.MULTILINE)


def missing_capture_fields(
    *, what_it_concerns: str | None, why_keep: str | None, content: str | None
) -> list[str]:
    """Return the mandatory capture fields that are missing or blank, in order."""
    values = {
        "what_it_concerns": what_it_concerns,
        "why_keep": why_keep,
        "content": content,
    }
    return [name for name in MANDATORY_CAPTURE_FIELDS if not (values[name] or "").strip()]


def missing_fields_message(missing: list[str]) -> str:
    """A helpful error naming the missing field(s) plus a worked example.

    Acceptance criterion: "missing mandatory field -> helpful error naming
    the field and an example."
    """
    joined = ", ".join(missing)
    return (
        f"capture is missing mandatory field(s): {joined}. what_it_concerns, "
        f"why_keep and content are all required — capture never guesses at "
        f"them. Example: {_EXAMPLE_CALL}"
    )


def capture_id_for(permalink: str) -> str:
    """``capture_id`` = ``"cap-" + sha256(permalink)[:10]`` (format spec §7)."""
    digest = hashlib.sha256(permalink.encode("utf-8")).hexdigest()
    return f"{CAPTURE_ID_PREFIX}{digest[:10]}"


def content_hash_for(what_it_concerns: str, why_keep: str, content: str) -> str:
    """A cheap hash of the three mandatory fields for exact-duplicate detection.

    Normalizes case/whitespace so trivially-reformatted resubmits still
    count as the same capture. Not a format-spec frontmatter key — recovered
    from the body's ``[capture_hash]`` bullet by :func:`extract_capture_hash`.
    """
    normalized = "\x1f".join(part.strip().lower() for part in (what_it_concerns, why_keep, content))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def default_source(now: datetime | None = None) -> str:
    """Default ``[source]`` text when the caller omits one (deliverable #1).

    Today's gateway tool call carries no richer per-request client identity
    than what :class:`~palaia_hub.gateway.vault_protocol.VaultService`
    already exposes, so the default is deliberately plain: "agent capture,
    <date>". A future SPEC that threads MCP client/session identity through
    to tool calls can sharpen this without changing the contract.
    """
    when = (now or datetime.now(UTC)).date().isoformat()
    return f"agent capture, {when}"


def compose_capture_body(
    *,
    what_it_concerns: str,
    why_keep: str,
    content: str,
    source: str,
    content_hash: str,
) -> str:
    """The canonical inbox note body (format spec §7 example shape)."""
    return (
        f"{why_keep}\n\n"
        f"- [entity] {what_it_concerns}\n"
        f"- [why] {why_keep}\n"
        f"- [raw] {content}\n"
        f"- [source] {source}\n"
        f"- [capture_hash] {content_hash}\n"
    )


def extract_capture_hash(body: str) -> str | None:
    """Recover the ``[capture_hash]`` bullet written by :func:`compose_capture_body`."""
    match = _CAPTURE_HASH_RE.search(body)
    return match.group("hash") if match else None


def capture_frontmatter(*, capture_id: str) -> dict[str, object]:
    """Frontmatter keys a capture note needs beyond the identity ones every
    writer already sets (``title``/``permalink``/``created``/``modified``).

    ``type: capture``, ``tags: [inbox]``, ``status: uncurated`` and
    ``capture_id`` all match format spec §7's canonical form.
    """
    return {
        "type": "capture",
        "tags": ["inbox"],
        "status": "uncurated",
        "capture_id": capture_id,
    }


__all__ = [
    "CAPTURE_ID_PREFIX",
    "MANDATORY_CAPTURE_FIELDS",
    "capture_frontmatter",
    "capture_id_for",
    "compose_capture_body",
    "content_hash_for",
    "default_source",
    "extract_capture_hash",
    "missing_capture_fields",
    "missing_fields_message",
]
