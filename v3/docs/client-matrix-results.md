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
