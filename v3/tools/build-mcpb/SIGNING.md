# MCPB signing — what we attach, and what Claude Desktop enforces

SPEC-306 asks this to be documented "with no hand-waving." Everything below
was checked against the primary sources (the MCPB spec repository's
`MANIFEST.md`/`CLI.md`, the `@anthropic-ai/mcpb` v2.1.2 CLI's own source,
Anthropic's "Build a desktop extension with MCPB" guide, and the original
Desktop Extensions announcement) and, where the docs were silent, against
the actual installed tooling — never assumed.

## What we attach

Every `.mcpb` this project produces — the CI-built generic template
(`build.mjs`) and every personalized per-download bundle
(`palaia_hub.mcpb.builder`) — is signed with the official `mcpb sign`
command: a real, detached **PKCS#7 (CMS) signature**, computed over the
whole packed zip and appended as a trailer (`MCPB_SIG_V1`…`MCPB_SIG_END`
markers, confirmed by reading `@anthropic-ai/mcpb`'s
`dist/node/sign.js`). Nothing here reimplements that format — every pack
and sign step shells out to the real CLI.

By default the signing identity is **self-signed**: an RSA-4096 keypair
this project generates once and persists (CI: a checked-in-nowhere
identity generated fresh per pipeline unless `PALAIA_MCPB_CERT`/
`PALAIA_MCPB_KEY` name a real cert; the hub at runtime: persisted under
`<PALAIA_HOME>/mcpb/`, so an operator's identity survives a container
rebuild — see `palaia_hub/mcpb/signing.py`).

## What that signature is actually worth, verified by running the tools

**A self-signed `.mcpb` fails `mcpb verify`/`mcpb info` on every platform,
out of the box.** This is not a guess: signing a bundle with `mcpb sign
--self-signed` and immediately running `mcpb verify` on the exact same
file, in this repository's own CI-equivalent environment, prints `ERROR:
Extension is not signed` — despite the PKCS#7 block genuinely being
present and byte-verifiable in the file (confirmed independently in
Python: `b"MCPB_SIG_V1" in data` is true). Reading `sign.js`'s
`verifyCertificateChain()` explains why: `mcpb verify` doesn't just check
that the signature is *cryptographically valid* — it separately checks
that the signing certificate chains to something the **operating system's
own trust store** accepts, using:

- macOS: `security verify-cert -c chain.pem -p codeSign`
- Windows: `System.Security.Cryptography.X509Certificates.X509Chain.Build`
  with the code-signing application policy
- Linux: `openssl verify -purpose codesigning -CApath /etc/ssl/certs`

A self-signed certificate — by definition not issued by anything in any
of those trust stores — fails all three, and the CLI's `verify`/`info`
commands report the file as **unsigned**, not "signed but untrusted."
`mcpb sign`'s own post-signing self-check (which calls the same
`verifyMcpbFile`) hits the exact same wall, which is why `mcpb sign
--self-signed` still prints "Successfully signed" (the write succeeded)
without ever printing the "Signed by: / Issuer:" lines that a
trust-chain-valid signature gets.

**What this does *not* affect:** a plain zip reader (Python's `zipfile`,
`mcpb unpack`, and — by every indication in the public docs — Claude
Desktop's own installer, which reads the manifest and packed files, not
the trailer) opens a self-signed-signed `.mcpb` exactly like an unsigned
one; the appended trailer sits past the zip's own end-of-central-directory
record and both this repository's tests (`test_builder.py`) and a plain
`python -c "import zipfile; zipfile.ZipFile(...)"` read it back cleanly.

## What Claude Desktop itself enforces — genuinely undocumented

Every primary source checked for this SPEC (`README.md`, `MANIFEST.md`,
`CLI.md` in the `modelcontextprotocol/mcpb` repository; Anthropic's
`docs/connectors/building/mcpb` guide; the original "Desktop Extensions"
engineering blog post) is **silent** on whether Claude Desktop's installer
checks a bundle's signature at all, and if it does, whether an
untrusted/self-signed one is blocked, shown with a warning, or treated
identically to no signature. `research/mcp-landscape-2026.md` §MCPB
already flagged this as unverified before this SPEC started, and nothing
found while implementing it resolved that — so this document does not
claim an enforcement behavior it cannot show a source for. **The safest
assumption, given the `verifyCertificateChain` logic above and ordinary
code-signing practice on both platforms, is that an OS-level Gatekeeper/
SmartScreen-style check (if Claude Desktop performs one at all) would
treat a self-signed `.mcpb` the same way `mcpb verify` does: no worse than
an unsigned file, not a hard block** — but that is an inference from how
the underlying platforms generally behave, not a fact this project
observed Claude Desktop doing.

## The deliberate, disclosed trade-off

Self-signed is the default because this project has no CA-issued
code-signing certificate today — getting one is an operational step (cost,
identity verification) outside this SPEC's scope. `PALAIA_MCPB_CERT`/
`PALAIA_MCPB_KEY` (`build.mjs`, `palaia_hub/mcpb/signing.py`) let an
operator who does have one swap it in without any code change, at which
point `mcpb verify`/`mcpb info` — and whatever Claude Desktop's own check
turns out to be — see a real, trust-chain-valid signature. Until then,
every bundle this project produces really is signed (a real, checkable
PKCS#7 block, over the real content), it is simply signed by an identity
nothing outside this project vouches for yet — the same position every
self-signed code-signing certificate is in, on every platform, always.
