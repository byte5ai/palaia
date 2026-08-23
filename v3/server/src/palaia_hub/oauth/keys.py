"""The authorization server's signing key: one ES256 keypair on disk.

**Why ES256 and not Ed25519.** SPEC-203 deliverable #3 names Ed25519, and
deliverable #4 requires the resource side to be fastmcp's own ``JWTVerifier``
("do not write your own JWT validation on the resource side"). Those two
cannot both be honored with fastmcp 3.4.7: its ``JWTVerifier`` accepts only
HS/RS/ES/PS algorithms — ``EdDSA`` is rejected by its constructor, and its
JWKS loader explicitly skips ``OKP`` keys. Reaching EdDSA would mean
reimplementing ``JWTVerifier.load_access_token`` (signature, ``exp``,
``iss``, ``aud``, scope checks) in this repository, which is precisely the
thing the SPEC forbids. So the resource-side mandate wins and the signature
algorithm is **ES256** (NIST P-256 ECDSA, RFC 7518 §3.4): asymmetric, the
private key never leaves this file, the public half is published as a JWKS,
and tokens stay short. This deviation is called out in the PR rather than
hidden here.

**On-disk shape.** ``<home>/oauth/signing-key.pem`` holds the PKCS#8 private
key, created ``0600`` in a ``0700`` directory, both enforced on every load
(a key that was widened by hand is narrowed again rather than trusted). The
file is created with ``O_CREAT | O_EXCL`` and an explicit mode so the key
material is never briefly world-readable between ``open`` and ``chmod``.

**Rotation** is deliberately not automated in this SPEC: ``kid`` is the
key's RFC 7638 thumbprint, so a new key gets a new ``kid`` and the JWKS can
carry both during an overlap — but deciding when to rotate is an operator
action (a Phase-2 follow-up), not something to do behind their back.
"""

from __future__ import annotations

import logging
import os
import stat
import time
from pathlib import Path
from typing import Any

from joserfc import jwt
from joserfc.jwk import ECKey

logger = logging.getLogger("palaia_hub.oauth.keys")

#: The JWS algorithm every palaia access token is signed with. Both the
#: minting side (:meth:`SigningKey.sign`) and the verifying side
#: (:func:`palaia_hub.oauth.verifier.build_jwt_verifier`) read it from here,
#: so they cannot drift apart.
ALGORITHM = "ES256"
CURVE = "P-256"

#: Everything this package persists lives under ``<palaia home>/oauth/``.
OAUTH_DIR_NAME = "oauth"
SIGNING_KEY_FILE = "signing-key.pem"

DIR_MODE = 0o700
FILE_MODE = 0o600


def oauth_dir(home: Path) -> Path:
    """Return ``<home>/oauth``, created ``0700`` if it does not exist."""
    path = Path(home) / OAUTH_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    enforce_private_mode(path, DIR_MODE)
    return path


def enforce_private_mode(path: Path, mode: int) -> None:
    """Narrow ``path`` to ``mode`` if it is currently wider.

    Called on every load, not only at creation: a key or database whose
    permissions were widened (an ``rsync -a`` from a laxer box, a manual
    ``chmod``) is quietly narrowed again. Failures are logged rather than
    raised — a filesystem that cannot represent POSIX modes at all (some
    network and container mounts) must not stop the hub from starting, but
    the operator should see it in the log.
    """
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != mode:
            path.chmod(mode)
    except OSError as exc:  # pragma: no cover - platform dependent
        logger.warning("could not enforce mode %o on %s: %s", mode, path, exc)


class SigningKey:
    """The ES256 keypair palaia signs access tokens with.

    Load it with :meth:`load_or_create`; nothing else in this package
    constructs one, and nothing outside this class touches the private PEM.
    """

    def __init__(self, key: ECKey) -> None:
        self._key = key
        # RFC 7638 JWK thumbprint: derived from the public key itself, so the
        # same key always advertises the same `kid` and a different key
        # cannot accidentally reuse one.
        self._kid = key.thumbprint()

    # ------------------------------------------------------------- lifecycle

    @classmethod
    def load_or_create(cls, home: Path) -> SigningKey:
        """Load ``<home>/oauth/signing-key.pem``, generating it if absent."""
        directory = oauth_dir(home)
        path = directory / SIGNING_KEY_FILE
        if path.exists():
            enforce_private_mode(path, FILE_MODE)
            key = ECKey.import_key(path.read_bytes())
            if key.curve_name != CURVE:
                raise ValueError(
                    f"{path}: signing key uses curve {key.curve_name!r}, but palaia "
                    f"signs with {ALGORITHM} on {CURVE}. Fix: move the file aside and "
                    f"let the hub generate a new key (every issued access token stops "
                    f"verifying, so connected clients refresh once)."
                )
            return cls(key)
        key = ECKey.generate_key(CURVE)
        pem = key.as_pem(private=True)
        # O_EXCL: never overwrite an existing key, and never let the file
        # exist with default (umask-derived) permissions even momentarily.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)
        enforce_private_mode(path, FILE_MODE)
        logger.info("generated a new %s signing key at %s", ALGORITHM, path)
        return cls(key)

    # ---------------------------------------------------------------- surface

    @property
    def kid(self) -> str:
        """This key's RFC 7638 thumbprint — its ``kid`` in headers and JWKS."""
        return self._kid

    def public_pem(self) -> str:
        """The public half, PEM-encoded — what the resource side verifies with."""
        return self._key.as_pem(private=False).decode("ascii")

    def jwks(self) -> dict[str, Any]:
        """The public key as a one-entry JWKS document (RFC 7517)."""
        entry = dict(self._key.as_dict(private=False))
        entry.update({"kid": self._kid, "use": "sig", "alg": ALGORITHM})
        return {"keys": [entry]}

    def sign(self, claims: dict[str, Any]) -> str:
        """Sign ``claims`` as a compact JWS (a JWT) with this key."""
        header = {"alg": ALGORITHM, "typ": "JWT", "kid": self._kid}
        return jwt.encode(header, claims, self._key)


def now_seconds() -> int:
    """Current POSIX time, whole seconds — the unit every claim/column uses."""
    return int(time.time())


__all__ = [
    "ALGORITHM",
    "CURVE",
    "DIR_MODE",
    "FILE_MODE",
    "OAUTH_DIR_NAME",
    "SIGNING_KEY_FILE",
    "SigningKey",
    "enforce_private_mode",
    "now_seconds",
    "oauth_dir",
]
