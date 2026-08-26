#!/usr/bin/env python3
"""Sign (or generate a keypair for) the palaia curated marketplace index.

SPEC-303 deliverable #2: the curated index is a signed JSON document
``{schema_version, generated_at, entries[], signature}`` verified against
an Ed25519 public key pinned in
``palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64``. This script is the
only place the matching private key is ever supposed to touch disk on a
publisher's machine — see README.md in this directory for the full story
of why the key itself is never committed to the repo.

Usage::

    # One-time: mint a keypair. Prints the public key to embed in
    # palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64; writes the private
    # key to the given path (chmod 600) — back it up somewhere that is
    # NOT this git repository.
    python3 v3/tools/sign_market_index.py gen-key --out /secure/place/market-index.key

    # Sign an unsigned index document (schema_version/generated_at/entries,
    # no "signature" key) with that private key, writing the signed
    # document ready to publish at the configured index URL.
    python3 v3/tools/sign_market_index.py sign \\
        --key /secure/place/market-index.key \\
        --in unsigned-index.json \\
        --out signed-index.json

    # Verify a signed document against a public key (sanity check before
    # publishing, or to reproduce what the hub itself does on fetch).
    python3 v3/tools/sign_market_index.py verify \\
        --public-key <base64> \\
        --in signed-index.json
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

SCHEMA_VERSION = 1


def canonical_bytes(document: dict) -> bytes:
    """Must match ``palaia_hub.market.curated.canonical_bytes`` exactly —
    the document minus its own ``signature`` key, canonical JSON."""
    payload = {k: v for k, v in document.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def cmd_gen_key(args: argparse.Namespace) -> None:
    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite existing {out_path} (pass --force)", file=sys.stderr)
        raise SystemExit(1)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    out_path.write_bytes(private_bytes)
    out_path.chmod(0o600)
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    print(f"private key written to {out_path} (chmod 600) — keep it OUT of git")
    print("public key (paste into palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64):")
    print(base64.b64encode(public_raw).decode())


def cmd_sign(args: argparse.Namespace) -> None:
    private_key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        print("key file is not an Ed25519 private key", file=sys.stderr)
        raise SystemExit(1)
    document = json.loads(Path(args.in_path).read_text(encoding="utf-8"))
    document.pop("signature", None)
    document.setdefault("schema_version", SCHEMA_VERSION)
    if document["schema_version"] != SCHEMA_VERSION:
        print(f"unexpected schema_version {document['schema_version']!r}", file=sys.stderr)
        raise SystemExit(1)
    for key in ("generated_at", "entries"):
        if key not in document:
            print(f"input document is missing required key '{key}'", file=sys.stderr)
            raise SystemExit(1)
    signature = private_key.sign(canonical_bytes(document))
    document["signature"] = base64.b64encode(signature).decode()
    signed = json.dumps(document, indent=2, sort_keys=True) + "\n"
    Path(args.out).write_text(signed, encoding="utf-8")
    print(f"signed index written to {args.out}")


def cmd_verify(args: argparse.Namespace) -> None:
    document = json.loads(Path(args.in_path).read_text(encoding="utf-8"))
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(args.public_key))
    signature = base64.b64decode(document["signature"])
    try:
        public_key.verify(signature, canonical_bytes(document))
    except InvalidSignature:
        print("INVALID: signature does not match this public key", file=sys.stderr)
        raise SystemExit(1) from None
    print("OK: signature verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen_key = sub.add_parser("gen-key", help="mint a new Ed25519 keypair")
    gen_key.add_argument("--out", required=True, help="path to write the PEM private key to")
    gen_key.add_argument("--force", action="store_true", help="overwrite an existing file at --out")
    gen_key.set_defaults(func=cmd_gen_key)

    sign = sub.add_parser("sign", help="sign an unsigned index document")
    sign.add_argument("--key", required=True, help="path to the PEM private key")
    sign.add_argument("--in", dest="in_path", required=True, help="unsigned index JSON")
    sign.add_argument("--out", required=True, help="where to write the signed index JSON")
    sign.set_defaults(func=cmd_sign)

    verify = sub.add_parser("verify", help="verify a signed index document")
    verify.add_argument("--public-key", required=True, help="base64 Ed25519 public key")
    verify.add_argument("--in", dest="in_path", required=True, help="signed index JSON")
    verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
