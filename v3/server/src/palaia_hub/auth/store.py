"""The token store: named per-client tokens, hashed at rest.

Persisted as ``tokens.yaml`` under the hub's home directory (same directory
as ``config.yaml`` and the vault registry's ``vaults.yaml`` — see
:mod:`palaia_hub.config` / :mod:`palaia_hub.vault.registry`), written with
the same atomic-write primitive the vault engine uses
(:func:`palaia_hub.vault.atomic.atomic_write_text`) so a crash mid-write
never leaves a half-written store. Only the argon2id hash of each token's
secret half is ever written to that file — never the plaintext, never a
reversible encoding of it.

**Token shape**: ``plt_<id>.<secret>``. ``id`` is a public, non-secret
identifier — like a username, or a Stripe/GitHub API key's visible prefix —
used only to look up *which* record's hash to check; it carries no
authentication weight itself. ``secret`` is the actual credential: 32 bytes
of ``secrets.token_urlsafe`` entropy, never stored anywhere except as its
argon2id hash. Splitting the two avoids the alternative (argon2-verifying
the presented token against every stored hash to find a match), which would
make each request's cost scale with the number of issued tokens; looking
the id up first keeps verification O(1) regardless of how many tokens
exist, with the *secret* half still checked by argon2's constant-time
compare (:mod:`palaia_hub.auth.hashing`) — the only half that needs it.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ..config import palaia_home
from ..vault.atomic import atomic_write_text
from .hashing import hash_secret, spend_constant_time_miss, verify_secret
from .models import CreatedToken, TokenInfo, TokenRecord

logger = logging.getLogger("palaia_hub.auth.store")

TOKENS_FILE = "tokens.yaml"
TOKEN_PREFIX = "plt"

# vault:<key>:read|write — the only scope shape store.create() accepts.
# Deliberately not importing the gateway's key charset validator: the auth
# package must not depend on the gateway package (see the module docstring
# of palaia_hub.gateway.vault_protocol for the mirror-image rule), so this
# is its own narrow, self-contained check.
_SCOPE_RE = re.compile(r"^vault:[a-z0-9_-]+:(read|write)$")

_TOKEN_RE = re.compile(rf"^{TOKEN_PREFIX}_([A-Za-z0-9_-]{{8,}})\.([A-Za-z0-9_-]{{16,}})$")

_HEADER = (
    "# palaia client tokens — argon2id hashes only. Never edit the 'hash'\n"
    "# field by hand; use `palaia-hub token create/revoke` or the REST API.\n"
)


class TokenError(RuntimeError):
    """Raised for a caller-facing token-store failure (bad scope, no such id)."""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_scopes(scopes: Sequence[str]) -> list[str]:
    bad = [s for s in scopes if not _SCOPE_RE.match(s)]
    if bad:
        raise TokenError(
            f"invalid scope(s) {bad!r}. Fix: use 'vault:<key>:read' or "
            f"'vault:<key>:write' — see palaia_hub.auth.scopes.vault_scope()."
        )
    return list(scopes)


def _parse_token(token: str) -> tuple[str, str] | None:
    match = _TOKEN_RE.match(token)
    if match is None:
        return None
    return match.group(1), match.group(2)


class TokenStore:
    """Create, list, revoke, and verify named per-client tokens.

    Args:
        home: directory holding ``tokens.yaml``. Defaults to the hub's data
            directory (``PALAIA_HOME`` or the platform data dir) so a
            `palaia-hub token ...` CLI invocation and the running hub agree
            on where tokens live without extra wiring — mirrors
            :class:`palaia_hub.vault.registry.VaultRegistry`.
    """

    def __init__(self, home: Path | None = None) -> None:
        self.home = Path(home).expanduser() if home is not None else palaia_home()
        self._records: dict[str, TokenRecord] = {}
        self._load()

    @property
    def store_path(self) -> Path:
        """Path to ``tokens.yaml``."""
        return self.home / TOKENS_FILE

    # ------------------------------------------------------------- persistence

    def _load(self) -> None:
        path = self.store_path
        if not path.exists():
            return
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TokenError(
                f"{path}: could not parse YAML ({exc}). Fix: correct the syntax, or "
                f"delete the file to start with no tokens (every client will need a "
                f"new one)."
            ) from exc
        if not raw:
            return
        if not isinstance(raw, Mapping) or not isinstance(raw.get("tokens"), list):
            raise TokenError(
                f"{path}: expected a 'tokens:' list of records. Fix: correct the "
                f"file, or delete it to start over."
            )
        for item in raw["tokens"]:
            record = TokenRecord.model_validate(item)
            self._records[record.id] = record

    def _save(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        payload = {
            "tokens": [r.model_dump(mode="json") for r in self._records.values()]
        }
        text = _HEADER + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        atomic_write_text(self.store_path, text)
        with contextlib.suppress(OSError):  # pragma: no cover - platform dependent
            self.store_path.chmod(0o600)

    # ----------------------------------------------------------------- queries

    def list_tokens(self) -> list[TokenInfo]:
        """Every token, in creation order — never includes a hash or secret.

        Named ``list_tokens`` rather than ``list`` at the Python level for
        the same reason :meth:`palaia_hub.gateway.vault_protocol.VaultService.
        list_notes` is: a method literally named ``list`` would shadow the
        builtin for every subsequent ``list[...]`` annotation in this class
        body.
        """
        return [TokenInfo.from_record(r) for r in self._records.values()]

    def get(self, token_id: str) -> TokenInfo:
        record = self._records.get(token_id)
        if record is None:
            raise TokenError(
                f"no token with id {token_id!r}. Fix: check the id with list_tokens()."
            )
        return TokenInfo.from_record(record)

    # ------------------------------------------------------------- mutations

    def create(self, name: str, profile: str, scopes: Sequence[str]) -> CreatedToken:
        """Issue a new token bound to ``profile`` with ``scopes``.

        Returns the plaintext exactly once, alongside the stored (hash-free)
        info — the caller (REST handler, CLI command) must show it to the
        operator immediately; it cannot be recovered afterward.
        """
        if not name:
            raise TokenError("token name must not be empty. Fix: pass a descriptive --name.")
        if not profile:
            raise TokenError("token profile must not be empty. Fix: pass --profile <path>.")
        validated_scopes = _validate_scopes(scopes)

        token_id = secrets.token_urlsafe(9)
        secret = secrets.token_urlsafe(32)
        record = TokenRecord(
            id=token_id,
            name=name,
            profile=profile,
            scopes=validated_scopes,
            hash=hash_secret(secret),
            created_at=_now(),
        )
        self._records[token_id] = record
        self._save()
        logger.info("created token %r (id=%s, profile=%s)", name, token_id, profile)
        return CreatedToken(
            info=TokenInfo.from_record(record), token=f"{TOKEN_PREFIX}_{token_id}.{secret}"
        )

    def revoke(self, token_id: str) -> TokenInfo:
        """Revoke a token. Idempotent: revoking an already-revoked token is a no-op."""
        record = self._records.get(token_id)
        if record is None:
            raise TokenError(
                f"no token with id {token_id!r}. Fix: check the id with list_tokens()."
            )
        if record.is_revoked:
            return TokenInfo.from_record(record)
        updated = record.model_copy(update={"revoked_at": _now()})
        self._records[token_id] = updated
        self._save()
        logger.info("revoked token %r (id=%s)", updated.name, token_id)
        return TokenInfo.from_record(updated)

    # ------------------------------------------------------------- verification

    def verify(self, token: str) -> TokenRecord | None:
        """Verify a presented token; return its record if valid and live.

        ``None`` covers every rejection reason alike (malformed, unknown id,
        wrong secret, revoked) — the caller (an
        :class:`~palaia_hub.auth.verifier.PalaiaTokenVerifier`) turns that
        into the same 401 either way, never distinguishing *why* a token
        failed to a client.
        """
        parsed = _parse_token(token)
        if parsed is None:
            spend_constant_time_miss()
            return None
        token_id, secret = parsed
        record = self._records.get(token_id)
        if record is None:
            spend_constant_time_miss()
            return None
        if not verify_secret(secret, record.hash):
            return None
        if record.is_revoked:
            return None
        return record


__all__ = ["TOKEN_PREFIX", "TokenError", "TokenStore"]
