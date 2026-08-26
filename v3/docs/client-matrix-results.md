# Client integration matrix — validation results

> **Normative evidence log.** Implements [SPEC-209](../specs/SPEC-209-client-matrix.md):
> proof (and honest non-proof) for every row of [MASTERPLAN §6](../MASTERPLAN.md#6-client-integration-matrix),
> against a real Cloud-mode (`mode: cloud`, `oauth.enabled: true`) hub. The
> honesty rule from the SPEC is binding here too: **"not verified" is an
> acceptable cell value; a green cell requires evidence** (a command, and
> its actually-observed output). Nothing below is asserted from memory of
> how a client "should" behave.
>
> Scripted evidence lives in
> [`v3/server/tests/e2e/test_spec209_client_matrix.py`](../server/tests/e2e/test_spec209_client_matrix.py)
> (real hub, real `claude` CLI 2.1.241) and the pre-existing
> [`v3/server/tests/oauth/test_flow_e2e.py`](../server/tests/oauth/test_flow_e2e.py)
> (SPEC-203's own scripted OAuth client, exercising the DCR and CIMD paths
> every remote client in the matrix uses one of). Both suites were run for
> real while writing this document (see §0).

## 0. What was actually run, and when

```
$ cd v3 && uv run pytest server/tests/e2e/test_spec209_client_matrix.py -q
...                                                                      [100%]
3 passed in 74.10s (0:01:14)
```
Run twice in a row (74.10s, then 77.38s) with no flakes.

```
$ claude --version
2.1.241 (Claude Code)
```

Environment note carried through every cell below: this sandbox routes all
outbound HTTPS through a pre-configured proxy. The hub subprocess in the
test fixture sets `FASTMCP_SSRF_TRUST_PROXY=1` so FastMCP's SSRF-safe
fetcher (used for CIMD document fetches) can reach the real internet at all
— see [byte5ai/palaia#233](https://github.com/byte5ai/palaia/issues/233).
Without that variable, every CIMD-based login (claude.ai, ChatGPT, Codex,
Claude Code) fails at the metadata-fetch step in an egress-proxied
deployment, not just in this sandbox — worth a line in palaia's own ops
docs, tracked in that issue.

No other client binary (`codex`, `gemini`, an LM Studio/Open WebUI/llama.cpp
install, a ChatGPT or Grok account) was available in this environment. Those
rows are evidenced by (a) SPEC-203's own scripted-client test suite, which
exercises the exact wire-level behavior their published client SDKs use
(DCR, CIMD, resource-indicator variants, scope enforcement), and (b) web
research against each vendor's current documentation, cited per row — never
by running the real binary. That distinction is called out explicitly in
every such row.

## 1. Matrix

| # | Client | Cell | Verified how |
|---|---|---|---|
| 1 | Claude Code (CLI) | **Green, with two filed quirks** — §2 | Scripted, real CLI |
| 2 | Claude Desktop | **Green for the proxy's wire protocol; the MCPB install dialog itself unverified** — §6 (SPEC-306) | Scripted (real proxy subprocess, real hub) + docs |
| 3 | claude.ai (web/desktop/mobile/Cowork) | Not verified (no account in this environment); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 4 | ChatGPT | Not verified (no account); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 5 | Codex (CLI/IDE/desktop) | Not verified (binary unavailable); OAuth wire protocol (CIMD) shared with row 1 is green; **one connect-page correction shipped** — §3 | Scripted (shared code path) + docs |
| 6 | Antigravity / Gemini CLI | Not verified (binary unavailable); config shape confirmed correct against current docs | Docs |
| 7 | Grok | Not verified (no account); OAuth wire protocol shared with row 1 is green | Scripted (shared code path) + docs |
| 8 | OpenClaw | Not verified — not a v3 target (v2 serves it, per MASTERPLAN) | N/A |
| 9 | Local LLM frontends (LM Studio / Open WebUI / llama.cpp) | Not verified (no install available); **one connect-page correction shipped** (LM Studio) — §3 | Docs |

Every row has a filled cell; none of "not verified" above is silent —
each names exactly what would turn it green (a real account/binary in a
future validation run) and points at the evidence that *does* exist today.

## 2. Claude Code CLI — the full trace

Three real runs, in increasing depth, all against
`v3/server/tests/e2e/support/hub_server_oauth.py` — a real `VaultEngine`,
a real `AuthorizationServer` (SPEC-203), a real `uvicorn` socket, `mode:
cloud` (satisfies `HubConfig`'s own cloud-mode policy: private bind +
`oauth.enabled`). The one thing this sandbox cannot add on top is an actual
public tunnel — a network-reachability fact about Tailscale/cloudflared,
not part of the OAuth code path a *local* CLI client exercises. Claude Code
never goes through a vendor cloud in the first place, so it reaches this
loopback listener exactly as it would reach a tunnel's local termination
point.

### 2.1 A real OAuth token, real tool round trip

`test_a_real_oauth_token_lets_claude_code_round_trip_write_search_read`:
a scripted OAuth 2.1 + PKCE client (same protocol steps as
`test_flow_e2e.py`'s `ScriptedClient`, driven over a real `httpx.Client`
against a live TCP socket instead of the ASGI shortcut) completes a real
code flow — 401 → RFC 9728 discovery → RFC 8414 discovery → DCR → real
password sign-in → authorize → token exchange — against the real hub. The
resulting access token is handed to the real `claude` CLI via
`claude mcp add --transport http ... --header "Authorization: Bearer
<token>"`. `claude mcp get` reports `√ Connected`, and a real `claude -p`
session round-trips:

```
write : Call the mcp__palaia-spec209-e2e__work_memory_write tool with
        title='OAuth E2E' body='real oauth token round trip' → …
        {"permalink":"oauth-e2e","title":"OAuth E2E", …}
search: work_memory_search query='round trip' → hits: [{"permalink":"oauth-e2e", …}]
read  : work_memory_read permalink='oauth-e2e' → "real oauth token round trip"
```

This is real evidence that OAuth issuance and the resource server's
per-tool scope enforcement both work end to end with the actual CLI as the
MCP client — SPEC-203's engine and SPEC-209's client both proven together,
over a real socket.

### 2.2 A real, but non-blocking, status-display bug — filed as #232

`test_claude_mcp_get_reports_failed_to_connect_before_any_token_exists`:
before any token exists for a profile, `claude mcp get <name>` runs its own
connectivity probe and reports:

```
Status: × Failed to connect
Issue: Protected resource http://127.0.0.1:<port>/default does not match
       expected http://127.0.0.1:<port>/mcp/default/ (or origin)
```

Root cause: palaia's canonical audience shape
(`palaia_hub.oauth.resources.ResourceRegistry.audience` — deliberately
`<issuer>/<profile>`, fixing a named production incident, see that
module's docstring) never equals the gateway's actual mount URL,
`<issuer>/mcp/<profile>/`. Confirmed **not** a login blocker — §2.3 logs in
against the exact same profile moments later and `mcp get` then reports
`√ Connected` for it. Filed as
[byte5ai/palaia#232](https://github.com/byte5ai/palaia/issues/232) as a
UX/trust issue (a user who checks status before signing in sees a
scary-sounding, wrong verdict on a hub that works fine), not a functional
one.

### 2.3 The default-path login blocker — filed as #233, now fixed

`test_claude_code_cli_native_oauth_login_completes_on_the_default_path`
(skipped, not failed, when this sandbox cannot reach `claude.ai` — the
CIMD document fetch needs real internet):

**Part 1, the default zero-flag path** (`claude mcp add --transport http
... ` then `claude mcp login <name> --no-browser`, exactly the connect-page's
advertised one-liner): the CLI fetches Claude Code's own real, published
CIMD document (`https://claude.ai/oauth/claude-code-client-metadata`),
prints a real authorize URL, and — signed in for real as the owner — the
authorize request now completes with a `303` to the CLI's loopback
callback, and the login finishes (`Authenticated with …`, exit 0).

The blocker this section originally documented: Anthropic's CIMD document
registers a **portless** loopback redirect URI
(`http://localhost/callback`) while the CLI's real request always carries
a live ephemeral port, and `palaia_hub.oauth.cimd.match_redirect_uri` was
byte-exact with no RFC 8252 §7.3 loopback-port exemption — so every
default, zero-flag login failed with `400 invalid_redirect_uri`. Filed as
[byte5ai/palaia#233](https://github.com/byte5ai/palaia/issues/233) and
fixed by adding exactly that exemption: an `http` loopback redirect URI
matches a registered one when scheme, hostname, path and query all agree,
ignoring only the port; nothing else about exact matching changed
(`tests/oauth/test_cimd_and_pkce.py` pins both halves).

**Part 2, the CLI's fixed-port escape hatch, completed for real** (kept
green as the DCR-path regression test — this was the pre-fix workaround):
Claude
Code's own `mcp add --help` names exactly this scenario ("`--callback-port`:
Fixed port for OAuth callback, for servers requiring pre-registered
redirect URIs"). The test pre-registers a real DCR client with a literal,
fixed-port redirect URI, then:

```
$ claude mcp add --transport http palaia <url> \
    --client-id <that DCR client id> --callback-port <that port>
$ claude mcp login palaia --no-browser
Starting authentication for "palaia"…
Visit this URL to authorize: http://127.0.0.1:<port>/oauth/authorize?...
Waiting for authorization… (^C to cancel)
Or paste the redirect URL here: http://localhost:<port>/callback?code=...
Authenticated with "palaia". Its tools are now available in Claude Code.
$ claude mcp get palaia
Status: √ Connected
$ claude -p "call work_memory_write …" --allowedTools mcp__palaia__work_memory_write
{"permalink":"native-login-e2e","title":"Native Login E2E", …}
```

Exit code `0`. Together the two parts prove the resource server, PKCE,
CIMD, DCR, and the CLI's own OAuth plumbing end to end — on the default
path and on the fixed-port path.

## 3. Connect-page corrections shipped in this PR

Both found by checking `v3/web/src/lib/clients.ts`'s one-liners against
each vendor's current real documentation (§0's "no binary available"
caveat applies — corrected against docs, not a live binary):

- **Codex**: was `codex mcp add palaia --transport http <url>` — Codex CLI
  has no `--transport` flag for `mcp add`; the real syntax (confirmed via
  [openai/codex#4904](https://github.com/openai/codex/pull/4904) and
  current third-party Codex CLI MCP guides) is
  `codex mcp add <name> --url <url> [--bearer-token-env-var VAR]`. Fixed to
  `codex mcp add palaia --url <url>`.
- **LM Studio**: was `{"palaia": {"url": "<url>"}}` with no enclosing
  `mcpServers` key at all — not a valid `mcp.json`. LM Studio's own docs
  ([lmstudio.ai/docs/app/mcp](https://lmstudio.ai/docs/app/mcp)) show
  `{"mcpServers": {"<name>": {"type": "streamable-http", "url": "<url>"}}}`
  for a streamable-HTTP server specifically (the plain `"url"`-only shape
  in their examples is for SSE). Fixed to include the `mcpServers` wrapper
  and `"type": "streamable-http"`.

Checked and found already correct, no change:

- **Claude Code CLI**: `claude mcp add --transport http palaia <url>` —
  matches exactly (§2 ran this literal command against a real hub).
- **Antigravity / Gemini CLI**: `~/.gemini/settings.json`'s `mcpServers.*.httpUrl`
  — confirmed against [geminicli.com/docs/tools/mcp-server](https://geminicli.com/docs/tools/mcp-server/)
  and the upstream `google-gemini/gemini-cli` docs.

## 4. Rows not exercised with a real vendor account/binary

For claude.ai, ChatGPT, Grok and Codex, no real account or binary was
available in this environment (§0). What *is* real evidence for these
rows: every one of them connects as a "remote MCP server" client following
the same RFC 9728 discovery → RFC 8414 discovery → DCR-or-CIMD →
PKCE-code-flow → bearer-token protocol that §2 just proved end to end with
Claude Code, and that `test_flow_e2e.py` (SPEC-203, pre-existing, still
green) exercises directly:

- `test_dcr_client_completes_the_whole_flow_and_calls_a_tool` — the classic
  RFC 7591 DCR path (ChatGPT/Grok's documented custom-connector flow, per
  `research/mcp-landscape-2026.md` §6).
- `test_cimd_client_needs_no_registration_step_at_all` — the MCP
  2026-07-28 CIMD path (Codex's documented `codex mcp login`, per the same
  research; also what Claude Code itself turned out to use — §2.3).
- `test_the_resource_indicator_with_a_trailing_mcp_segment_works_end_to_end`
  and `test_a_read_only_grant_cannot_call_a_write_tool` — the
  resource-indicator-shape and scope-enforcement behaviors any of these
  clients could hit.

Byte5ai/palaia#233's redirect_uri finding (§2.3) — now fixed by the
RFC 8252 §7.3 loopback-port exemption — would have affected any of these
clients whose published CIMD/DCR redirect URI is a portless loopback
address the way Claude Code's is; with the exemption in place they get the
same behavior. ChatGPT and Grok are browser/mobile-first (not
loopback-native-app clients in the RFC 8252 sense), so the exemption is
unlikely to matter for them;
Codex, being another native CLI, is the one worth checking first once a
real Codex install is available.

## 5. Rows out of scope for this validation

- **OpenClaw**: not a v3 launch target (v2's plugin serves it) — nothing
  to validate under SPEC-209.
- **Local LLM frontends** (LM Studio, Open WebUI, llama.cpp): no install
  available (§0); LM Studio's connect-page snippet was corrected (§3)
  against current docs. Open WebUI (via its MCPO proxy) and llama.cpp's
  MCP client are not in `clients.ts` as guided rows yet and were not
  otherwise touched by this SPEC.

## 6. Claude Desktop — SPEC-306's proxy, and what remains unverified

SPEC-306 built the row 2 cell this document previously called "not built".
What is real evidence, and what is not:

**Green, with a real subprocess proof:**
`v3/server/tests/e2e/test_mcpb_proxy.py` spawns the actual
`v3/tools/build-mcpb/proxy/palaia-proxy.mjs` as a Node child process
(never a stub), drives it with `fastmcp.Client` over a genuine stdio
transport, and that proxy speaks genuine streamable HTTP to a real hub
subprocess (real `VaultEngine`, real SPEC-108 `TokenVerifier`, real
`uvicorn` socket) over a real loopback TCP connection. Three things are
proven this way: tools list and a memory tool round-trips through the
proxy; the proxy survives the hub being killed and restarted on the same
port (a transparent re-initialize on the resulting `404`, invisible to the
MCP client); and a revoked token produces a clear, non-stack-trace error
message on the resource side. Finding along the way: `mcp`'s Python
server frames its per-request SSE reply with CRLF line endings, not LF —
the proxy's frame parser normalizes both (`test/proxy.test.mjs` pins the
regression).

**Not verified, and said so rather than assumed:** no real Claude Desktop
application was available in this environment (it is macOS/Windows-only,
per `MANIFEST.md`'s `compatibility.platforms`). Two things that
specifically depend on the real application, not on this SPEC's own code,
remain open:

- Whether Claude Desktop's install dialog renders `manifest.json`'s
  `user_config` defaults pre-filled the way the spec describes, and
  whether double-clicking a `/api/connect/mcpb` download actually launches
  `palaia-proxy.mjs` the way `mcp_config` says.
- What, if anything, Claude Desktop's installer does with the bundle's
  PKCS#7 signature — genuinely undocumented upstream; see
  `v3/tools/build-mcpb/SIGNING.md` for exactly what was checked (three
  primary sources, plus running the official `mcpb verify`/`info` commands
  against a self-signed bundle) and what remains an open question.

A real macOS or Windows machine with Claude Desktop installed, downloading
a bundle from a reachable hub and double-clicking it, would close both
gaps — the same "needs a real device/account this sandbox cannot fake
honestly" situation §0 and the Phase-2 gate note already describe for the
phone-Claude half of the exit criterion.

## 7. Phase-3 gate: tools follow the profile (SPEC-308, 2026-08-24)

The Phase-3 exit criterion is narrower than the client matrix above and
was checked separately: **install a tool once (marketplace), and it is
available to every connected AI — different clients, different profiles,
no per-client setup.** Scripted evidence lives in
[`v3/server/tests/e2e/test_spec308_phase3_gate.py`](../server/tests/e2e/test_spec308_phase3_gate.py),
against a new hub subprocess,
[`support/hub_server_market.py`](../server/tests/e2e/support/hub_server_market.py),
that wires `palaia_hub.serve.build_production_app` exactly the way
`palaia-hub serve` does — real `VaultEngine`, real `AuthorizationServer`,
real marketplace/install machinery, two gateway profiles (`default`,
`mobile`) both accepting OAuth *and* SPEC-108 `plt_` tokens at once — over
a real `uvicorn` socket.

### 7.1 What was actually run

```
$ cd v3 && uv run pytest server/tests/e2e/test_spec308_phase3_gate.py -q
..                                                                       [100%]
2 passed in 32.84s
```
Run three times in a row (32.84s, 30.39s, 35.38s) with no flakes. The full
`tests/e2e/` directory (33 tests, including SPEC-209's and SPEC-306's own
suites) was also run twice end-to-end with this new file added, both green
(176.40s, 174.65s) — no regression in the pre-existing harness.

### 7.2 One install, two differently-authenticated clients, two profiles

`test_one_install_answers_on_two_differently_authenticated_clients`:

1. A **curated-index entry** — a genuinely Ed25519-signed one-entry
   document (a freshly-generated, throwaway signing key; see
   `hub_server_market.py`'s docstring for why that is honest evidence for
   "a signed curated document verifies" without needing palaia's real,
   non-public index key) naming a real second FastMCP server
   (`tests/upstream/fixture_http_server.py`, SPEC-302's own fixture) as a
   `remote` upstream — is fetched and verified through the real
   `GET /api/market/search?source=curated`.
2. `POST /api/market/entry/{id}/consent` → `POST
   /api/market/entry/{id}/install` with `profiles: ["default", "mobile"]`
   — the same consent-token-gated REST flow SPEC-304's own tests exercise,
   run here for real over a live socket. One call, both profiles:
   ```
   {"upstream_key": "acme-spec308-fixture", ..., "up": true,
    "profiles": ["default", "mobile"], ...}
   ```
3. **Client A — a scripted `fastmcp.Client` with a real SPEC-108 `plt_`
   token** (minted through `POST /api/auth/tokens`, zero client-side tool
   configuration), against the `mobile` profile: `list_tools()` already
   contains `acme_spec308_fixture_echo`; calling it returns
   `"hello from the plt_ client"`.
4. **Client B — the real `claude` CLI**, over a real scripted OAuth 2.1 +
   PKCE code flow (SPEC-209's own machinery, reused verbatim) against the
   `default` profile: `claude mcp add --transport http ... --header
   "Authorization: Bearer <token>"`, `claude mcp get` reports `√
   Connected`, and `claude -p "Call
   mcp__palaia-spec308-e2e__acme_spec308_fixture_echo ..."` returns
   `"hello from claude CLI"`.

Same upstream, same tool, one install call — reached by two clients with
completely different credential shapes, on two different profiles, with no
client-side tool declaration on either side. This is the exit criterion,
demonstrated for real, on the same loopback-hub basis §2's note already
explains (a local CLI/scripted client never goes through a vendor cloud in
the first place, so it reaches this listener exactly as it would reach a
tunnel's local termination point).

### 7.3 The same install, through the SPEC-306 stdio proxy, no bundle change

`test_the_install_is_visible_through_the_mcpb_stdio_proxy_without_bundle_changes`:
the real `palaia-proxy.mjs` (Node subprocess, real stdio transport — same
proof shape as `test_mcpb_proxy.py`) is pointed at the `mobile` profile
with a freshly-minted `plt_` token, **after** the install above, with no
change to the proxy script, no rebuild, no bundle edit. `list_tools()`
already contains `acme_spec308_fixture_echo`; calling it through the proxy
returns `"hello through the stdio proxy"`. The stdio path is not a
separately-curated tool list — it mirrors whatever the profile serves,
live, exactly as the HTTP paths do.

### 7.4 Honest gaps

- **The dashboard's own UI** was not driven for this evidence — only the
  REST surface it calls. Whether the marketplace page's own React state
  updates live (rather than needing a reload) after an install is
  unverified here; SPEC-304's own dashboard work is the place that would
  be checked, not this gate.
- **A real public tunnel** in front of the hub was not part of this
  evidence, for the same reason §2's note gives: this sandbox cannot add
  one honestly, and none of the three clients above go through a vendor
  cloud to reach a *local* hub anyway.
- **Claude Desktop's own MCPB install dialog** remains exactly as
  unverified as §6 already says — SPEC-308 adds no new evidence there; the
  stdio proxy itself (§7.3) is the part of that path this sandbox can
  drive for real.
- No quirks were found while writing this evidence (unlike SPEC-209's
  #232/#233) — the existing `build_production_app`/`build_profile_auth`
  combination (SPEC-301) and the marketplace install flow (SPEC-304) both
  worked exactly as documented on the first real run against two profiles
  at once.

## 8. Phase-4 gate: messenger (SPEC-407, 2026-08-25)

The Phase-4 exit criterion is **two agents on different providers hand off
work through palaia**: a handoff envelope with a vault reference, sent by
one, picked up and acted on by the other. Scripted evidence lives in
[`v3/server/tests/e2e/test_spec407_phase4_gate.py`](../server/tests/e2e/test_spec407_phase4_gate.py),
against a new hub subprocess,
[`support/hub_server_messenger.py`](../server/tests/e2e/support/hub_server_messenger.py),
that wires `palaia_hub.serve.build_production_app` exactly the way
`palaia-hub serve` does — real `VaultEngine`, real `AuthorizationServer`,
real directory/messenger services, two gateway profiles (`default`,
`mobile`) both carrying the one shared vault plus `directory: true`/
`messenger: true` — over a real `uvicorn` socket.

### 8.1 What was actually run

```
$ cd v3 && uv run pytest server/tests/e2e/test_spec407_phase4_gate.py -q
.                                                                        [100%]
1 passed in 33.36s
```
Run four times in a row (33.36s, 37.85s, 32.59s, 33.44s), no flakes. The
full `tests/e2e/` directory (36 tests total, including SPEC-209's,
SPEC-306's and SPEC-308's own suites) was also run once end-to-end with
this new file added: green, 36 passed in 186.85s — no regression in any
pre-existing harness. The full `server/tests` suite (1986 tests) was also
run green, 1986 passed / 23 skipped in 429.13s.

### 8.2 The two-agents handoff, and the directory half

`test_two_agents_on_different_providers_hand_off_work_through_palaia`:

1. **Session B** — a scripted `fastmcp.Client` carrying a real SPEC-108
   `plt_` token, minted through `POST /api/auth/tokens` — registers first,
   on the `mobile` profile, with `scope="the Q3 billing rate-limiter
   incident"`. This sandbox has no `codex` binary, so a second-provider-
   shaped scripted client is the honest stand-in for "the other provider"
   here, the same wire-level substitution SPEC-209 already pinned for "a
   client that is not the real claude CLI".
2. **Session A** — the real `claude` CLI, over a real scripted OAuth 2.1 +
   PKCE code flow (SPEC-209's own machinery, reused verbatim, no `scope`
   requested — see §8.4 on what that exercises), against the `default`
   profile — is driven by one mechanical task prompt: register with the
   directory, save a specific fact to memory with the vault's `write`
   tool, find the peer via `directory_query(scope_contains="the Q3 billing
   rate-limiter incident")` (**never told B's handle anywhere** — not in
   the prompt, not in `--mcp-config`, not in the environment: directory
   handles are fresh, random 16-character tokens, so the only way A's
   `messenger_send` call can address B correctly is to have actually
   called `directory_query` and read the handle back out of the result),
   then `messenger_send` a `type="handoff"` envelope to that discovered
   handle with `refs=["memory://<the permalink just written>"]` and a body
   that does **not** repeat the fact.
3. **Session B** calls `messenger_check` on its own handle/secret, finds
   the handoff, and follows `refs[0]` with `recall` — a full
   `memory://...` reference, the exact form `recall`'s own tool
   description says it accepts.
4. The assertion that matters: B's real, literal `recall` output contains
   A's exact fact string
   (`"The billing retry batch is capped at 200 items because a larger
   batch trips the downstream rate limiter; raising it needs the request
   queue split first."`) — the handoff carried knowledge, not just an
   envelope, and B found it through the directory, not a hardcoded handle.

### 8.3 A real quirk, fixed in this PR: [#257](https://github.com/byte5ai/palaia/issues/257)

Minting session B's `plt_` token with `directory:read`/`directory:write`/
`messenger:read`/`messenger:send` scopes failed outright on the first real
run: `POST /api/auth/tokens` rejected every one of them as an "invalid
scope", because `palaia_hub.auth.store._validate_scopes`'s regex had only
ever matched `vault:<key>:read|write` — even though the gateway's own
enforcement layer has recognized `directory:*`/`messenger:*` (and
`stash:*`) scopes since SPEC-402/403. This is the `plt_`-token-side twin of
the OAuth scope-ceiling bug `palaia_hub.cli._profile_scopes`'s own
docstring already documents fixing on the OAuth side (found during
SPEC-403) — the twin bug meant no non-OAuth client could ever be minted a
token that could use the directory or messenger at all, through the real
REST surface. Fixed in this PR (`server/src/palaia_hub/auth/store.py`,
regression test in `server/tests/auth/test_store.py`); this SPEC's own
acceptance depended on the fix, so it went straight in rather than into a
follow-up — see the issue for the full trace.

### 8.4 Skill-driven variant (SPEC-404's harness, env-gated)

SPEC-407 deliverable #3 asks a harder question than §8.2's scripted
mechanism proof: with only the task and the `palaia-messenger` skill
loaded — the prompt never names a tool, "the messenger", or "the
directory" — does a real agent reach for the handoff on its own? Reusing
SPEC-404's own harness (`server/tests/effectiveness/messaging_harness.py`,
its `HANDOFF_PROMPT`/`CHECK_PROMPT` probes) rather than inventing a second
one, run for real via
`server/tests/effectiveness/test_spec407_skill_driven_handoff.py`
(`PALAIA_EFFECTIVENESS=1`, this SPEC's stated budget of 3 real attempts per
probe) — reported as a rate, per the SPEC's own instruction, **not
hard-asserted** either way (SPEC-404's own suite already hard-asserts "at
least one hit in N attempts" for the same prompts; this run is gate
evidence about the unprompted rate, not a second regression test for the
skill):

```
$ cd v3 && PALAIA_EFFECTIVENESS=1 uv run pytest \
    server/tests/effectiveness/test_spec407_skill_driven_handoff.py -s -v
...
### SPEC-407 gate evidence — skill-driven handoff, unprompted
- attempts: 3
- registered with the directory: 3/3
- sent a handoff carrying a memory:// ref (not a pasted copy): 3/3
...
### SPEC-407 gate evidence — skill-driven check-on-start, unprompted
- attempts: 3
- checked its inbox unprompted: 3/3
2 passed in 231.09s (0:03:51)
```

Run once, for real, on 2026-08-25 (real model calls, real money — $0.9767
total across the six attempts: three handoff attempts at $0.1225/$0.1178/
$0.1185, three check-on-start attempts at $0.2486/$0.1852/$0.1842). Both
probes hit every single attempt:

- **Handoff probe** (task: "end of your shift ... hand the branch off to
  whichever other session is already working on the billing service" —
  never names a tool): all three attempts called `directory_register`,
  `directory_query`, then `messenger_send` with `message_type="handoff"`
  and a `memory://inbox/...` reference in `refs` (never the fact pasted
  into the body) — 3/3 registered, 3/3 handed off with a real reference.
- **Check-on-start probe** (task: "another session ... may have left you
  something ... get yourself oriented" — never says "message" or
  "inbox"): all three attempts called `messenger_check` before doing
  anything else — 3/3.

Six real runs is a small sample, honestly — the SPEC's own stated budget
is 3 attempts per probe, and this is exactly that, not a claim that the
skill fires 100% of the time in general. SPEC-404's own effectiveness
suite (`test_messenger_effectiveness.py`, a separate, already-green
regression test with its own hard assert) is the place a lower future rate
would first show up as a real regression; this run is Phase-4 gate
evidence about the unprompted rate on one real day, not a substitute for
that suite.

### 8.5 Honest gaps

- **A real second provider (e.g. a real `codex` binary)** was not part of
  this evidence — this sandbox has none, and none of palaia's own protocol
  surface (the envelope shape, the directory query grammar, the session
  secret) is provider-specific, so a scripted `fastmcp.Client` is the same
  substitution SPEC-209/308 already made for "not the real claude CLI",
  reused here for "not a second real provider" too.
- **A real public tunnel** in front of the hub was not part of this
  evidence, for the same reason §2's and §7.4's notes give.
- **Claude Desktop's/claude.ai's own UI** was not exercised here — §6/§7.4
  already carry that gap, and SPEC-407 adds nothing new to it; the owner's
  standing phone test remains the item that would close it, per this
  SPEC's own non-goals.
- **Claude Code's `claude/channel` push capability** (a live push into an
  already-open session rather than pull-based `messenger_check`) is not
  exercised — `docs/messenger.md` §8 already says why: the pinned `fastmcp`
  3.4.7 has no support for declaring it. Pull-based delivery (`messenger_
  check`) is what both §8.2 and §8.4 exercise, and it is the universal
  baseline the SPEC itself treats as sufficient.

## 9. RC validation: the Phase-5 gate (SPEC-506, 2026-08-26)

The Phase-5 exit criterion is **a non-developer completes install → first
shared memory unaided**. The literal criterion needs a real person this
sandbox does not have — `v3/docs/usability-test-protocol.md` is the
owner's script for that session. This section is everything scriptable:
the funnel's mechanical twin, timed, plus what could and could not be
checked about the shipped Docker one-liner in this environment.

### 9.1 What was actually run

```
$ cd v3 && uv run pytest server/tests/e2e/test_spec506_phase5_gate.py -q -s
```
run twice, each against a fresh hub subprocess and a genuinely empty home
directory (`assert not (home / "vaults.yaml").exists()` in the fixture).
Both green, no flakes:

- Run 1: `1 passed in 16.27s` — wall clock (fresh home → B's recall):
  **12.25s**; hub-side `time_to_first_memory_seconds`: **8.53s** (displayed
  "9s").
- Run 2: `1 passed in 14.79s` — wall clock: **10.57s**; hub-side
  `time_to_first_memory_seconds`: **7.15s** (displayed "7s").

Both numbers, both runs, are more than an order of magnitude inside
MASTERPLAN §13's <5 minute (300s) machine-time target. (Three more runs
taken while building this test landed at 10.58s/7.07s, 10.81s/7.29s and
11.47s/7.75s — quoted here for context, not as a third "official" run;
the two above are the ones this SPEC's acceptance criterion asks for.)
The hub-side number is the one that matters for §13 — it is computed
server-side, event-driven, from `hub_started_at` to `first_memory_at`
(`palaia_hub.funnel.FunnelSnapshot`), never from a client-reported
timestamp; the wall-clock number additionally includes this test's own
Python-side OAuth/PKCE scripting and subprocess overhead around the real
`claude` CLI invocation, so it is always a little higher and is reported
alongside honestly rather than presented as the metric.

### 9.2 The scenario

`test_full_funnel_fresh_home_to_second_client_recall`
(`v3/server/tests/e2e/test_spec506_phase5_gate.py`), against a new hub
subprocess, `support/hub_server_funnel.py`:

1. **Fresh home.** A hub subprocess boots against an empty `PALAIA_HOME`
   (no `vaults.yaml`), Cloud mode, OAuth enabled from the first line — see
   §9.3 for why the OAuth scopes are pre-declared for a vault key ("work")
   that does not exist yet at that point, and why that is not a shortcut.
2. **Wizard → vault.** `GET /api/info` (unauthenticated, the sign-in
   gate's own allowlist), then a signed-in dashboard session (Cloud mode's
   default `dashboard.require_sign_in: true`) drives `GET /api/funnel/
   status` and `POST /api/vaults` — the exact REST surface `Onboarding.
   tsx` step 3 calls, identical to `test_s7_spec504_first_run_funnel.py`'s
   own wizard walk (SPEC-504).
3. **Connect client A: the real `claude` CLI, OAuth's own default path.**
   A real, scripted OAuth 2.1 + PKCE code flow (the same machinery
   `test_spec209_client_matrix.py`/`test_spec308_phase3_gate.py`/
   `test_spec407_phase4_gate.py` already established, reused rather than
   reinvented) mints an access token with no `scope` requested — the
   resource's full grantable set, RFC 6749 §3.3's server default. The real
   `claude` CLI then runs with that token pre-filled in `--mcp-config`
   (never typed by a person — the "your AI configures itself" promise
   `docs/connect/clients/claude-code-cli.md` makes) and writes the funnel's
   first memory: `work_memory_write` with a distinctive fact.
4. **`GET /api/funnel/status`** confirms `first_memory_at` is now set —
   the real claude CLI's own write, not a seed note (the wizard's
   template-notes switch stays off, same funnel-audit reasoning
   `test_s7`'s own file documents).
5. **Connect client B: a `plt_` token, scripted.** `POST /api/auth/tokens`
   mints a real SPEC-108 token; a scripted `fastmcp.Client` carrying it
   calls `work_memory_recall` — a different credential shape than A's, on
   the same profile, reaching the vault A just wrote to with zero
   client-side reconfiguration.
6. The assertion that matters: B's real, literal recall output contains
   A's exact fact string, proving the shared-memory half of the exit
   criterion end to end, mechanically.

### 9.3 A design note, not a shortcut: pre-declared OAuth scopes

`AuthorizationServer` freezes its grantable-scopes-per-profile dict at
construction (`palaia_hub/oauth/service.py`) — production's own CLI path
(`palaia_hub.cli._maybe_oauth_server`) keeps this honest by refusing to
start the OAuth server at all until a vault already exists. This test's
support script legitimately takes the case that guard protects against as
its own scenario: an operator who chooses Cloud mode from the very first
boot, already knowing the vault key ("work") the wizard is about to
create — the scope dict names it up front, but the vault itself is
created only later, over the real wizard REST call, exactly as this
section's step 2 describes. Nothing about this required a production code
change; the *runtime* verification side (`_auth_provider_for` in
`palaia_hub.serve`, a SPEC-504 fix) already builds a real OAuth+`plt_`
verifier for a vault the moment it mounts dynamically, no restart needed
— this script only had to supply the scope dict a real `_maybe_oauth_
server`-driven boot could not, for the reason named above. Two real,
honest product gaps were found and filed rather than fixed in this PR
(neither blocks this SPEC's acceptance criteria):
[#272](https://github.com/byte5ai/palaia/issues/272) (OAuth-authenticated
clients never fire `client.connected`/`client_connected_at` — confirmed in
this very test: `client_connected_at` stays `null` after A's OAuth
connection and only becomes non-null once B's `plt_` token verifies,
asserted explicitly rather than hidden) and
[#273](https://github.com/byte5ai/palaia/issues/273) (an operator cannot
express "Cloud mode from boot, for a vault I'm about to create" through
`config.yaml` today — only this test's own direct `AuthorizationServer.
build()` call can).

### 9.4 Docker one-liner smoke: env-gated, honestly skipped here

```
$ cd v3 && uv run pytest server/tests/e2e/test_docker_one_liner_smoke.py -q -rs
.s
1 passed, 1 skipped in 2.22s
SKIPPED [1] server/tests/e2e/test_docker_one_liner_smoke.py:95: no reachable docker daemon in this environment
```

This sandbox has the `docker` CLI on `PATH` but no reachable daemon
(`docker info` fails: "Cannot connect to the Docker daemon at
unix:///var/run/docker.sock"), the same real check
`server/tests/market/test_install_container.py` already gates on
(`palaia_hub.market.docker_runtime.docker_available`, reused here rather
than reinvented) — so the actual "build the image, run it with
`install.sh`'s exact hardening flags, check `GET /`/`GET /api/health`"
smoke skips honestly rather than being faked. The one part of this test
that *does* run everywhere — a pure text check that its hardening flags
(`--security-opt no-new-privileges:true`, `--cap-drop ALL`, `--read-only`,
two `--tmpfs` mounts) still match `deploy/install.sh`'s real content
verbatim — passed.

What this sandbox's skip rests on instead, honestly, per this SPEC's own
task: **SPEC-112's existing evidence**
(`v3/specs/SPEC-112-packaging.md`'s acceptance criterion, "fresh Linux VM:
`docker run` one-liner → wizard reachable, data survives restart") plus
the working, hardened `docker run` one-liner itself
(`v3/deploy/README.md`'s Quick start, byte-for-byte what
`v3/site/docs`'s onboarding page renders — `onboarding.test.ts` already
proves that match) and the `v3-release.yml` CI workflow's own arm64 QEMU
smoke step (`docker run` + polled `/api/health`, on every image build,
`v3/server/tests/test_release_workflow.py` pins its structure) are the
standing, real, already-green evidence for "the image starts and answers
health" — this SPEC's own smoke test is additional coverage for the
*specific hardening flags*, not the only evidence the one-liner works at
all.

### 9.5 Honest gaps

- **The literal exit criterion** (a real non-developer, unaided) is not
  and cannot be part of this scripted evidence — `v3/docs/usability-test-
  protocol.md` is the owner's script for that session; §5/§8's standing
  gaps (a real phone/claude.ai account, a real `codex` binary, a real
  public tunnel) are unaffected by this SPEC and carry forward unchanged.
- **The rc image itself** was not built and smoke-tested against a real
  docker daemon in this environment (§9.4) — the version/changelog drift
  test (`server/tests/test_version_drift.py`) and the real `npm run
  build` transcript in this PR's description are what stands in for that
  here: every artifact (server, web, sdk, the mcpb bundle) reports
  `3.0.0-rc1` from the same `v3/VERSION` source, checked mechanically.
- **Claude Desktop's own UI**, a real public tunnel, and the dashboard's
  own click-through UI remain out of scope here exactly as §6/§7.4/§8.5
  already say — this SPEC adds nothing new to those gaps.
