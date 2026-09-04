# v3/tools

Operational scripts that are not part of the running hub — they are run
by hand (or in CI) by whoever operates the palaia curated marketplace
index, not by `palaia-hub` itself.

## `sign_market_index.py` — curated index signing (SPEC-303)

The curated add-on index (MASTERPLAN §5.3, `palaia_hub.market.curated`) is
a signed JSON document. The hub only ever holds the **public** half of
the keypair (`palaia_hub.market.curated.DEFAULT_PUBLIC_KEY_B64`, baked
into the source, or `market.public_key` in an owner's `config.yaml`) and
refuses any document that doesn't verify against it.

**The private key is intentionally never in this repository.** A trust
anchor that anyone with repo access could re-sign against is not a trust
anchor — it would let a compromised contributor account (or a careless
PR) silently redirect every hub's curated index. The key lives wherever
whoever publishes `index.palaia.dev`'s real index keeps secrets (a
password manager, a KMS, a hardware key) — this script is only the tool
that uses it locally to produce a signed document, then the private key
goes back into storage.

### Current state — read this first (issue #321)

**No hub can verify a fetched index today, so every hub serves the starter
index.** The key pinned in `DEFAULT_PUBLIC_KEY_B64` is the one the bundled
starter index was signed with, and its private half was discarded right
after that signing (see the last paragraph of this section). Nothing
published at `https://index.palaia.dev/market-index.json` can carry a
signature that key accepts, so each hub's fetch is refused (or, while
nothing is published there, fails to connect) and the hub falls back to
`server/src/palaia_hub/market/data/starter-index.json`. Since #321 that
failure is remembered on disk for five minutes
(`palaia_hub.market.curated.DEFAULT_FAILURE_TTL_SECONDS`), so the
marketplace pages stay fast; the *content* is still just the starter list.

Turning the real index on is an **owner action**, done once, in this order:

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

3. **Publish `market-index.json`** at
   `https://index.palaia.dev/market-index.json` (the hub's
   `DEFAULT_INDEX_URL`), over HTTPS, as plain static content. Every hub
   re-fetches it at most once an hour
   (`DEFAULT_TTL_SECONDS`), and only after a hub has verified one document
   does it start enforcing the rollback check against it.

4. **Tell hubs the new public key**, either way:

   - **Per hub, now** — in that hub's `config.yaml`:

     ```yaml
     market:
       index_url: https://index.palaia.dev/market-index.json   # or your own URL
       public_key: <the printed public key>
     ```

     The key is validated at load (base64, 32 raw bytes) and is deliberately
     settable *only* in this owner-only file — no REST route or dashboard
     control can move a hub's trust anchor.

   - **For every hub, permanently** — replace
     `DEFAULT_PUBLIC_KEY_B64` in `server/src/palaia_hub/market/curated.py`
     in a follow-up PR (a new key = a new hub release, deliberately, per that
     constant's own docstring). Hubs that set `market.public_key`
     themselves keep their own value.

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
