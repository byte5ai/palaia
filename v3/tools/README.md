# v3/tools

Operational scripts that are not part of the running hub — they are run
by hand (or in CI) by whoever operates the palaia curated marketplace
index, not by `palaia-hub` itself.

## `sign_market_index.py` — curated index signing (SPEC-303)

The curated add-on index (MASTERPLAN §5.3, `palaia_hub.market.curated`) is
a signed JSON document. The hub only ever holds the **public** half of
the keypair (`market.public_key` in an owner's `config.yaml`, set together
with `market.index_url`) and refuses any fetched document that doesn't
verify against it.

**The private key is intentionally never in this repository.** A trust
anchor that anyone with repo access could re-sign against is not a trust
anchor — it would let a compromised contributor account (or a careless
PR) silently redirect every hub's curated index. The key lives wherever
whoever publishes the real index keeps secrets (a
password manager, a KMS, a hardware key) — this script is only the tool
that uses it locally to produce a signed document, then the private key
goes back into storage.

### Current state — read this first (issues #321, #409)

**palaia publishes no curated index for 3.0.0, and no hub looks for one by
default.** `DEFAULT_INDEX_URL` is `None`: a hub with no `market.index_url`
serves `server/src/palaia_hub/market/data/starter-index.json` — the
add-ons bundled with the release — and the marketplace page says exactly
that. The starter index carries no signature: it ships inside the package,
so it is trusted the way the code is, and the key its old signature used
had no private half anywhere (it was discarded after signing), which made
that signature a formality rather than a check. Only a *fetched* index is
signature-verified.

Two things in the starter index are the owner's to confirm before 3.0.0
ships them as "bundled add-ons": the container entries point at
`ghcr.io/palaia/addon-fetch:1.0.0` and `ghcr.io/palaia/addon-filesystem:1.0.0`,
which this repository's CI never pulls — check they exist and are yours, or
remove them (the skill entry that pointed at a non-existent
`addons.` host is already gone).

Publishing a real index is an **owner action**, done once, in this order.
Where the index lives is also the owner's call — the natural place is next
to the docs (`https://palaia.byte5.ai/market-index.json`, served by the
palaia-homepage repo); the steps below say `<index-url>` for it.

1. **Mint the real keypair** — on the publisher's own machine, never in CI
   and never inside this repository:

   ```bash
   python3 v3/tools/sign_market_index.py gen-key --out ~/secure/market-index.key
   ```

   Back `market-index.key` up where the project's other secrets live (a
   password manager, a KMS, a hardware key). Keep the printed **public**
   key; it is not secret.

2. **Sign the index** you want to publish (an unsigned document with
   `schema_version`, `generated_at`, `entries` — the starter index minus
   its `signature` is a valid template):

   ```bash
   python3 v3/tools/sign_market_index.py sign \
       --key ~/secure/market-index.key \
       --in unsigned-index.json \
       --out market-index.json
   python3 v3/tools/sign_market_index.py verify \
       --public-key <the printed public key> \
       --in market-index.json
   ```

   `generated_at` must be **later** than the previous published document's
   — a hub refuses an older one as a rollback.

3. **Publish `market-index.json`** at `<index-url>`, over HTTPS, as plain
   static content. Every hub
   re-fetches it at most once an hour
   (`DEFAULT_TTL_SECONDS`), and only after a hub has verified one document
   does it start enforcing the rollback check against it.

4. **Tell hubs the new public key**, either way:

   - **Per hub, now** — in that hub's `config.yaml`:

     ```yaml
     market:
       index_url: <index-url>
       public_key: <the printed public key>
     ```

     The key is validated at load (base64, 32 raw bytes) and is deliberately
     settable *only* in this owner-only file — no REST route or dashboard
     control can move a hub's trust anchor.

   - **For every hub, permanently** — make the URL and key the package
     defaults (`DEFAULT_INDEX_URL` in
     `server/src/palaia_hub/market/curated.py`, plus a default public key
     next to it) in a follow-up PR: a new default = a new hub release,
     deliberately. Hubs that set `market.*` themselves keep their values.

Every later publish repeats steps 2–3 only. Rotating the key repeats all
four (and, until the release with the new default is out, hubs that have
not set `market.public_key` see the old signature as "signed with the wrong
key" and stay on their last verified copy).

### The starter index

The starter index shipped at
`server/src/palaia_hub/market/data/starter-index.json` was produced with
this script against a keypair generated solely for that purpose, whose
private key was discarded after signing — it exists to give a fresh hub
something real to browse and to exercise the verification path in tests,
not as the production palaia index. Until the owner action above has
happened, it is also what every hub's marketplace shows.
