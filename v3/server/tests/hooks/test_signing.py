from __future__ import annotations

from palaia_hub.hooks.signing import sign, verify


def test_sign_is_deterministic_and_prefixed() -> None:
    signature = sign("s3cret", b'{"a":1}')

    assert signature.startswith("sha256=")
    assert signature == sign("s3cret", b'{"a":1}')


def test_verify_accepts_a_matching_signature() -> None:
    body = b'{"event":"hub.started"}'
    signature = sign("s3cret", body)

    assert verify("s3cret", body, signature)


def test_verify_rejects_a_wrong_secret_or_tampered_body() -> None:
    body = b'{"event":"hub.started"}'
    signature = sign("s3cret", body)

    assert not verify("other-secret", body, signature)
    assert not verify("s3cret", body + b"x", signature)
