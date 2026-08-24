"""The hub's own MCPB signing identity (SPEC-306 deliverable #2/#4).

**Why the hub needs a signing key of its own at all.** `/api/connect/mcpb`
(:mod:`palaia_hub.mcpb.routes`) bakes a specific hub URL, and either a
freshly minted token or an OAuth issuer, into `manifest.json` on every
download — the artifact is personalized per click, so it cannot be the one
CI signed once (any edit to a signed `.mcpb` invalidates that signature;
see ``../../../tools/build-mcpb/SIGNING.md``). The hub therefore signs its
own, freshly repacked copy on every download, through the same official
`mcpb sign` command CI uses (:mod:`palaia_hub.mcpb.builder` shells out to
it) — never a hand-rolled substitute for the PKCS#7 signing tool.

**Self-signed, persisted, not regenerated per request.** A real CA-issued
code-signing certificate is not something this project has (see
SIGNING.md's honest accounting of what a self-signed certificate does and
does not buy); ``PALAIA_MCPB_CERT``/``PALAIA_MCPB_KEY`` let an operator who
does have one point at it instead (see :func:`signing_cert_paths` below).
Absent that, this module generates one self-signed RSA-4096 keypair (RSA,
not the ES256 curve :mod:`palaia_hub.oauth.keys` uses for JWTs — the
signing tool's PKCS#7 implementation, ``node-forge``, needs RSA) the first
time a bundle is requested, and reuses it for every download after that —
under ``<home>/mcpb/``, which is the hub's own persistent data directory
(a mounted volume in the Docker image), so the signing identity survives a
container rebuild the same way the OAuth signing key does. What changes
between downloads is the *signature over each newly personalized file*,
never the certificate's identity — the same relationship any code-signing
setup has between "one identity" and "many signed artifacts."
"""

from __future__ import annotations

import datetime
import logging
import os
import stat
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("palaia_hub.mcpb.signing")

MCPB_DIR_NAME = "mcpb"
CERT_FILE = "signing-cert.pem"
KEY_FILE = "signing-key.pem"

DIR_MODE = 0o700
KEY_FILE_MODE = 0o600
CERT_FILE_MODE = 0o644

#: How long the self-signed cert is valid for — matching the official
#: `mcpb` CLI's own `--self-signed` convenience certificate (`-days 3650`),
#: so this deviates from upstream practice in duration by exactly nothing.
VALIDITY_DAYS = 3650


def mcpb_dir(home: Path) -> Path:
    """``<home>/mcpb``, created ``0700`` if it does not exist."""
    path = Path(home) / MCPB_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    _enforce_mode(path, DIR_MODE)
    return path


def _enforce_mode(path: Path, mode: int) -> None:
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != mode:
            path.chmod(mode)
    except OSError as exc:  # pragma: no cover - platform dependent
        logger.warning("could not enforce mode %o on %s: %s", mode, path, exc)


def signing_cert_paths(home: Path) -> tuple[Path, Path]:
    """``(cert_path, key_path)`` the hub signs MCPB downloads with.

    Honors ``PALAIA_MCPB_CERT``/``PALAIA_MCPB_KEY`` (both must be set
    together, and must already exist) for an operator supplying a real
    CA-issued code-signing certificate; generates and persists a
    self-signed one under ``<home>/mcpb/`` otherwise. Called on every
    download request — cheap (existence checks only) after the first call,
    which is the only one that ever writes anything.
    """
    cert_env = os.environ.get("PALAIA_MCPB_CERT")
    key_env = os.environ.get("PALAIA_MCPB_KEY")
    if cert_env or key_env:
        if not (cert_env and key_env):
            raise SigningConfigError(
                "PALAIA_MCPB_CERT and PALAIA_MCPB_KEY must both be set, or neither. "
                "Fix: set both to point at your CA-issued certificate and its private key."
            )
        cert_path, key_path = Path(cert_env), Path(key_env)
        if not cert_path.exists() or not key_path.exists():
            raise SigningConfigError(
                f"PALAIA_MCPB_CERT/PALAIA_MCPB_KEY name a file that does not exist "
                f"({cert_path}, {key_path}). Fix: check the paths, or unset both to fall "
                f"back to the hub's own self-signed certificate."
            )
        return cert_path, key_path

    directory = mcpb_dir(home)
    cert_path = directory / CERT_FILE
    key_path = directory / KEY_FILE
    if not cert_path.exists() or not key_path.exists():
        _generate_self_signed(cert_path, key_path)
    else:
        _enforce_mode(key_path, KEY_FILE_MODE)
    return cert_path, key_path


def _generate_self_signed(cert_path: Path, key_path: Path) -> None:
    """Writes a fresh self-signed RSA-4096 cert+key pair to disk.

    ``O_CREAT | O_EXCL`` for the private key, same discipline as
    :mod:`palaia_hub.oauth.keys`: never overwrite one that already exists
    (a concurrent request racing this one loses, and reads what the winner
    wrote), and never leave it world-readable even momentarily.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "palaia MCPB Self-Signed Certificate"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "palaia"),
        ]
    )
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)  # self-signed: issuer == subject
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CODE_SIGNING]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, KEY_FILE_MODE)
    try:
        os.write(fd, key_pem)
    finally:
        os.close(fd)
    _enforce_mode(key_path, KEY_FILE_MODE)

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_pem)
    _enforce_mode(cert_path, CERT_FILE_MODE)
    logger.info("generated a new self-signed MCPB signing certificate at %s", cert_path)


class SigningConfigError(Exception):
    """A ``PALAIA_MCPB_CERT``/``PALAIA_MCPB_KEY`` misconfiguration."""


__all__ = [
    "CERT_FILE",
    "KEY_FILE",
    "MCPB_DIR_NAME",
    "SigningConfigError",
    "mcpb_dir",
    "signing_cert_paths",
]
