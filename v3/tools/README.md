# v3/tools

Operational scripts that are not part of the running hub — they are run
by hand (or in CI) by whoever operates the palaia curated marketplace
index, not by `palaia-hub` itself.

## `sign_market_index.py` — curated index signing (SPEC-303)

The curated add-on index (MASTERPLAN §5.3, `palaia_hub.market.curated`) is
a signed JSON document. The hub only ever holds the **public** half of
the keypair (`palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64`, baked
into the source) and refuses any document that doesn't verify against it.

**The private key is intentionally never in this repository.** A trust
anchor that anyone with repo access could re-sign against is not a trust
anchor — it would let a compromised contributor account (or a careless
PR) silently redirect every hub's curated index. The key lives wherever
whoever publishes `index.palaia.dev`'s real index keeps secrets (a
password manager, a KMS, a hardware key) — this script is only the tool
that uses it locally to produce a signed document, then the private key
goes back into storage.

```bash
# One-time (or on rotation): mint a keypair.
python3 v3/tools/sign_market_index.py gen-key --out ~/secure/market-index.key
# -> paste the printed public key into
#    server/src/palaia_hub/market/curated.py's DEFAULT_PUBLIC_KEY_B64
#    (a new key = a new hub release, deliberately, per that constant's
#    own docstring)

# Every publish: sign the day's curated-index content.
python3 v3/tools/sign_market_index.py sign \
    --key ~/secure/market-index.key \
    --in unsigned-index.json \
    --out signed-index.json
# -> upload signed-index.json to whatever index_url the hub is
#    configured to fetch (config.yaml's market.index_url, or
#    the DEFAULT_INDEX_URL default)

# Sanity check before publishing (or to reproduce what the hub does):
python3 v3/tools/sign_market_index.py verify \
    --public-key <the base64 public key> \
    --in signed-index.json
```

The starter index shipped at
`server/src/palaia_hub/market/data/starter-index.json` was produced with
this script against a keypair generated solely for that purpose, whose
private key was discarded after signing — it exists to give a fresh hub
something real to browse and to exercise the verification path in tests,
not as the production palaia index.
