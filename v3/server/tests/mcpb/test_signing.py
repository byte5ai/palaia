"""The hub's own persistent MCPB signing identity."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from cryptography import x509

from palaia_hub.mcpb.signing import (
    CERT_FILE,
    KEY_FILE,
    SigningConfigError,
    mcpb_dir,
    signing_cert_paths,
)


def test_generates_a_cert_and_key_on_first_call(tmp_path: Path) -> None:
    cert_path, key_path = signing_cert_paths(tmp_path)

    assert cert_path == mcpb_dir(tmp_path) / CERT_FILE
    assert key_path == mcpb_dir(tmp_path) / KEY_FILE
    assert cert_path.exists()
    assert key_path.exists()

    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert cert.subject == cert.issuer  # self-signed


def test_reuses_the_same_identity_across_calls(tmp_path: Path) -> None:
    cert_path, key_path = signing_cert_paths(tmp_path)
    first_cert_bytes = cert_path.read_bytes()
    first_key_bytes = key_path.read_bytes()

    signing_cert_paths(tmp_path)

    assert cert_path.read_bytes() == first_cert_bytes
    assert key_path.read_bytes() == first_key_bytes


def test_key_file_is_private(tmp_path: Path) -> None:
    _, key_path = signing_cert_paths(tmp_path)
    mode = key_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_env_override_requires_both_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PALAIA_MCPB_CERT", str(tmp_path / "cert.pem"))
    monkeypatch.delenv("PALAIA_MCPB_KEY", raising=False)

    with pytest.raises(SigningConfigError, match="must both be set"):
        signing_cert_paths(tmp_path)


def test_env_override_requires_files_to_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PALAIA_MCPB_CERT", str(tmp_path / "missing-cert.pem"))
    monkeypatch.setenv("PALAIA_MCPB_KEY", str(tmp_path / "missing-key.pem"))

    with pytest.raises(SigningConfigError, match="does not exist"):
        signing_cert_paths(tmp_path)


def test_env_override_is_honored_when_both_files_exist(tmp_path: Path) -> None:
    cert_path = tmp_path / "operator-cert.pem"
    key_path = tmp_path / "operator-key.pem"
    cert_path.write_text("fake cert")
    key_path.write_text("fake key")
    old_cert, old_key = os.environ.get("PALAIA_MCPB_CERT"), os.environ.get("PALAIA_MCPB_KEY")
    os.environ["PALAIA_MCPB_CERT"] = str(cert_path)
    os.environ["PALAIA_MCPB_KEY"] = str(key_path)
    try:
        resolved_cert, resolved_key = signing_cert_paths(tmp_path)
        assert resolved_cert == cert_path
        assert resolved_key == key_path
        # The self-signed pair under <home>/mcpb/ is never created when an
        # override is honored.
        assert not (mcpb_dir(tmp_path) / CERT_FILE).exists()
    finally:
        for name, value in (("PALAIA_MCPB_CERT", old_cert), ("PALAIA_MCPB_KEY", old_key)):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
