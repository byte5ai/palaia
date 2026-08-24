#!/usr/bin/env node
/**
 * palaia-proxy — the thin stdio↔hub bridge packaged inside the MCPB bundle
 * (SPEC-306 deliverable #1).
 *
 * Claude Desktop launches this script as a plain stdio MCP server (it
 * ships a Node runtime, so no dependency install is needed — this file is
 * self-contained: only Node's own builtins are imported, nothing from
 * `node_modules`). Every JSON-RPC message palaia-proxy reads from stdin is
 * forwarded, unmodified, as one MCP *streamable HTTP* request to the real
 * hub named by its config; every response the hub sends back is written,
 * unmodified, to stdout. Claude Desktop / Claude Code never know they are
 * not talking to the hub directly.
 *
 * Configuration arrives as environment variables — the values Claude
 * Desktop's `user_config`-driven settings UI resolves from
 * `manifest.json` (see `../manifest.template.json`) into
 * `mcp_config.env`, or the values `/api/connect/mcpb` bakes into a
 * personalized manifest before signing and streaming it (see
 * `palaia_hub.mcpb.builder`):
 *
 *   PALAIA_HUB_URL      required. The profile's MCP endpoint, e.g.
 *                        "https://hub.example.com/mcp/default/".
 *   PALAIA_TOKEN         a bearer token (SPEC-108). Mutually exclusive
 *                        with PALAIA_OAUTH — token mode wins if both are
 *                        somehow set, since an explicit secret is a
 *                        stronger signal than a flag.
 *   PALAIA_OAUTH         "1" to use OAuth 2.1 + PKCE (SPEC-203) instead of
 *                        a static token. Requires PALAIA_ISSUER.
 *   PALAIA_ISSUER        the authorization server's issuer origin, e.g.
 *                        "https://hub.example.com". OAuth mode only.
 *   PALAIA_PROFILE       the gateway profile name (used as the OAuth
 *                        `resource` indicator and to key the on-disk
 *                        credential cache). Defaults to "default".
 *   PALAIA_CREDENTIALS_FILE
 *                        override the on-disk path OAuth tokens are
 *                        cached at. Defaults under the OS config dir —
 *                        see `defaultCredentialsPath()`.
 *   PALAIA_LOG_LEVEL     "debug" for verbose stderr diagnostics. Default:
 *                        only warnings/errors are printed.
 *
 * Nothing here ever writes to stdout except a forwarded JSON-RPC message —
 * stdout *is* the MCP transport, so a stray `console.log` would corrupt
 * the stream from the client's point of view. Every diagnostic goes to
 * stderr (`log()` below), which is exactly what the acceptance criterion
 * ("clear stderr diagnostics", "no stack trace vomit") asks for.
 */

import { createServer as createHttpServer } from "node:http";
import http from "node:http";
import https from "node:https";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";

// --------------------------------------------------------------------------
// Small helpers
// --------------------------------------------------------------------------

const LOG_LEVEL = (process.env.PALAIA_LOG_LEVEL || "info").toLowerCase();

/** Every diagnostic goes to stderr — stdout is the MCP wire, never a log. */
export function log(level, message) {
  if (level === "debug" && LOG_LEVEL !== "debug") return;
  process.stderr.write(`palaia-proxy: ${message}\n`);
}

/** Exponential backoff with a cap, deterministic (no jitter) so it is
 * trivial to assert on in a test. Attempt 0 -> baseMs, capped at maxMs. */
export function backoffDelayMs(attempt, { baseMs = 250, maxMs = 5000 } = {}) {
  return Math.min(maxMs, baseMs * 2 ** attempt);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Where OAuth tokens are cached, keyed by hub URL so two profiles on the
 * same machine never collide. Kept out of the bundle's own install
 * directory (which Claude Desktop can wipe/replace on update) — under the
 * user's own config-style directory instead. */
export function defaultCredentialsPath(hubUrl) {
  const key = crypto.createHash("sha256").update(hubUrl).digest("hex").slice(0, 16);
  const base =
    process.env.XDG_CONFIG_HOME ||
    (process.platform === "darwin"
      ? path.join(os.homedir(), "Library", "Application Support")
      : process.platform === "win32"
        ? process.env.APPDATA || path.join(os.homedir(), "AppData", "Roaming")
        : path.join(os.homedir(), ".config"));
  return path.join(base, "palaia", "mcpb-credentials", `${key}.json`);
}

// --------------------------------------------------------------------------
// PKCE (RFC 7636) — pure functions, unit-testable with no network at all.
// --------------------------------------------------------------------------

export function base64url(buffer) {
  return buffer
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

export function newCodeVerifier() {
  return base64url(crypto.randomBytes(32));
}

export function codeChallengeFor(verifier) {
  return base64url(crypto.createHash("sha256").update(verifier).digest());
}

// --------------------------------------------------------------------------
// A minimal streamable-HTTP client — POST JSON-RPC, read back either a
// single `application/json` body or a `text/event-stream` of one or more
// JSON-RPC messages (mcp/server/streamable_http.py's own two response
// shapes — see that module for the exact header names this mirrors).
// --------------------------------------------------------------------------

class HttpError extends Error {
  constructor(status, body) {
    super(`hub answered ${status}`);
    this.status = status;
    this.body = body;
  }
}

/** One streamable-HTTP session against one hub endpoint. */
export class HubConnection {
  constructor(url, { getAuthHeader, onMessage }) {
    this.url = new URL(url);
    this.getAuthHeader = getAuthHeader;
    this.onMessage = onMessage;
    this.sessionId = null;
    this._transport = this.url.protocol === "https:" ? https : http;
    // The most recent `initialize` message this connection sent — cached
    // so a restarted hub (which has forgotten every session id, and 404s
    // the next request over the old one) can be transparently
    // re-initialized without the upstream MCP client (which still
    // believes its original handshake holds) ever finding out. See the
    // 404 branch in `send()` below.
    this._lastInitialize = null;
  }

  /** POST one JSON-RPC message; resolves once the hub's reply (if any) has
   * been delivered to `onMessage`. Retries connection-level failures with
   * backoff. A 404 on a session id the hub no longer recognizes (a
   * restart) triggers one transparent re-initialize + retry; any other
   * HTTP-level error (401, 5xx, …) is not retried here — the caller
   * decides (e.g. a 401 triggers a token refresh + one retry in OAuth
   * mode; see `run()` below). */
  async send(message, { maxAttempts = 5 } = {}) {
    if (message && message.method === "initialize") {
      this._lastInitialize = message;
    }
    try {
      return await this._sendWithRetry(message, maxAttempts);
    } catch (err) {
      const sessionWasStale =
        err instanceof HttpError &&
        err.status === 404 &&
        this.sessionId !== null &&
        this._lastInitialize !== null &&
        message.method !== "initialize";
      if (!sessionWasStale) throw err;
      log("info", "the hub no longer recognizes this session (it likely restarted); reconnecting.");
      this.sessionId = null;
      // Replay the original handshake so the new hub process has a
      // session at all, but never deliver *this* reply — the real client
      // already consumed the reply to its own, earlier `initialize` call
      // and has no idea this one exists.
      await this._sendWithRetry(this._lastInitialize, maxAttempts, { deliver: false });
      return await this._sendWithRetry(message, maxAttempts);
    }
  }

  async _sendWithRetry(message, maxAttempts, { deliver = true } = {}) {
    let lastError;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        return await this._sendOnce(message, { deliver });
      } catch (err) {
        if (err instanceof HttpError) throw err; // not a connection failure
        lastError = err;
        const delay = backoffDelayMs(attempt);
        log(
          "debug",
          `connection attempt ${attempt + 1}/${maxAttempts} to ${this.url.origin} failed ` +
            `(${err.code || err.message}); retrying in ${delay}ms`,
        );
        await sleep(delay);
      }
    }
    throw lastError;
  }

  async _sendOnce(message, { deliver = true } = {}) {
    const body = Buffer.from(JSON.stringify(message), "utf8");
    const headers = {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      "content-length": String(body.length),
    };
    const auth = await this.getAuthHeader();
    if (auth) headers.authorization = auth;
    if (this.sessionId) headers["mcp-session-id"] = this.sessionId;

    const response = await new Promise((resolve, reject) => {
      const req = this._transport.request(
        this.url,
        { method: "POST", headers },
        (res) => resolve(res),
      );
      req.on("error", reject);
      req.write(body);
      req.end();
    });

    const sid = response.headers["mcp-session-id"];
    if (sid) this.sessionId = sid;

    if (response.statusCode && response.statusCode >= 400) {
      const chunks = [];
      for await (const chunk of response) chunks.push(chunk);
      throw new HttpError(response.statusCode, Buffer.concat(chunks).toString("utf8"));
    }

    // 202 Accepted with no body: the hub is acknowledging a notification
    // or a JSON-RPC *response* we sent it (e.g. the client's own reply to
    // a server-initiated request) — nothing to forward.
    if (response.statusCode === 202) {
      response.resume();
      return;
    }

    const contentType = String(response.headers["content-type"] || "");
    const deliverTo = deliver ? this.onMessage : () => {};
    if (contentType.startsWith("text/event-stream")) {
      await this._consumeSse(response, deliverTo);
    } else {
      const chunks = [];
      for await (const chunk of response) chunks.push(chunk);
      const text = Buffer.concat(chunks).toString("utf8").trim();
      if (text) deliverTo(JSON.parse(text));
    }
  }

  /** Parse an SSE body into individual `data:` frames, forwarding each
   * parsed JSON-RPC message as it arrives (not batched to the end) — a
   * `tools/call` that streams progress notifications ahead of its final
   * response must not make the client wait for the whole thing. */
  async _consumeSse(response, deliverTo = this.onMessage) {
    let buffer = "";
    for await (const chunk of response) {
      // The SSE line terminator is CRLF, CR, or LF (the spec allows all
      // three; sse-starlette — what mcp's Python SDK uses server-side —
      // emits CRLF). Normalizing the whole accumulated buffer (not just
      // the newest chunk) on every append means a CRLF split across two
      // chunk boundaries still ends up correct once the second chunk
      // arrives, rather than leaving a stray bare `\r` behind.
      buffer = (buffer + chunk.toString("utf8")).replace(/\r\n/g, "\n");
      let sep;
      // SSE frames are separated by a blank line.
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        for (const line of frame.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const data = line.slice(5).trim();
          if (!data) continue;
          deliverTo(JSON.parse(data));
        }
      }
    }
  }

  /** Best-effort standalone GET SSE stream for server-initiated pushes
   * (streamable-http's other half — a server may send a request or
   * notification with no matching client POST in flight). Not every
   * server implements this; a non-2xx here is logged once and otherwise
   * ignored; palaia's own memory tools do not push anything unsolicited
   * today, so this is forward-looking, not load-bearing. */
  async openPushStream() {
    for (let attempt = 0; ; attempt++) {
      try {
        await this._pushStreamOnce();
        attempt = 0; // a clean read to completion resets backoff
      } catch (err) {
        log("debug", `push stream ended (${err.message}); reconnecting`);
      }
      await sleep(backoffDelayMs(Math.min(attempt, 6)));
    }
  }

  async _pushStreamOnce() {
    const headers = { accept: "text/event-stream" };
    const auth = await this.getAuthHeader();
    if (auth) headers.authorization = auth;
    if (this.sessionId) headers["mcp-session-id"] = this.sessionId;

    const response = await new Promise((resolve, reject) => {
      const req = this._transport.request(this.url, { method: "GET", headers }, resolve);
      req.on("error", reject);
      req.end();
    });
    if (response.statusCode && response.statusCode >= 400) {
      response.resume();
      throw new Error(`push stream not available (status ${response.statusCode})`);
    }
    await this._consumeSse(response);
    throw new Error("push stream closed by hub");
  }
}

// --------------------------------------------------------------------------
// OAuth 2.1 + PKCE + DCR — the client half of SPEC-203, run once (or once
// per expired refresh token) rather than per request.
// --------------------------------------------------------------------------

function httpJson(method, url, { body, headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const target = new URL(url);
    const transport = target.protocol === "https:" ? https : http;
    const payload = body ? Buffer.from(body, "utf8") : null;
    const req = transport.request(
      target,
      { method, headers: payload ? { ...headers, "content-length": String(payload.length) } : headers },
      (res) => {
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({ status: res.statusCode, headers: res.headers, text });
        });
      },
    );
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

/** Fetches RFC 8414 authorization-server metadata. */
async function discoverAuthServer(issuer) {
  const res = await httpJson("GET", `${issuer.replace(/\/$/, "")}/.well-known/oauth-authorization-server`);
  if (res.status !== 200) {
    throw new Error(`could not read authorization-server metadata (status ${res.status})`);
  }
  return JSON.parse(res.text);
}

/** RFC 7591 dynamic client registration with a loopback redirect URI on
 * the given port — the exact shape `palaia_hub.oauth.clients.register_dcr_client`
 * accepts, and the redirect URI Claude Code's own escape hatch
 * (`--callback-port`) uses, documented in
 * `v3/docs/client-matrix-results.md` §2.3. */
async function registerClient(metadata, redirectUri) {
  const res = await httpJson("POST", metadata.registration_endpoint, {
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ client_name: "palaia-proxy", redirect_uris: [redirectUri] }),
  });
  if (res.status !== 201) throw new Error(`dynamic client registration failed (status ${res.status})`);
  return JSON.parse(res.text).client_id;
}

/** Opens a one-shot loopback HTTP server on an ephemeral port to catch the
 * authorize redirect, exactly the pattern RFC 8252 §7.3 describes (and
 * that #233, fixed server-side, made work on the default path). Exposes
 * the assigned port before the callback lands (the authorize URL needs
 * that port in its `redirect_uri` before the browser is opened), and
 * resolves `code` once a request lands on `/callback`. */
function startCallbackServer() {
  let resolveCode;
  let rejectCode;
  const codePromise = new Promise((resolve, reject) => {
    resolveCode = resolve;
    rejectCode = reject;
  });
  const server = createHttpServer((req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    res.writeHead(200, { "content-type": "text/html" });
    res.end("<p>palaia: you can close this window and return to your MCP client.</p>");
    const code = url.searchParams.get("code");
    const error = url.searchParams.get("error");
    server.close();
    if (error) rejectCode(new Error(`authorization was not granted (${error})`));
    else if (code) resolveCode(code);
    else rejectCode(new Error("no authorization code in the redirect"));
  });
  const listening = new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
  return { port: listening, code: codePromise };
}

function openBrowser(url) {
  const platform = process.platform;
  const [cmd, args] = platform === "darwin" ? ["open", [url]] : platform === "win32" ? ["cmd", ["/c", "start", "", url]] : ["xdg-open", [url]];
  execFile(cmd, args, () => {
    // Best-effort only. A headless install (no display) fails here silently;
    // the authorize URL printed to stderr is the real fallback.
  });
}

/** Runs the full OAuth 2.1 + PKCE + DCR code flow once, returns fresh
 * tokens. Prints the authorize URL to stderr unconditionally — a headless
 * environment (no browser, no display) still has a way forward: copy the
 * URL into any browser by hand. */
async function loginWithOAuth({ issuer, profile }) {
  const metadata = await discoverAuthServer(issuer);
  const { port, code } = startCallbackServer();
  const boundPort = await port;
  const redirectUri = `http://127.0.0.1:${boundPort}/callback`;
  const clientId = await registerClient(metadata, redirectUri);

  const verifier = newCodeVerifier();
  const state = base64url(crypto.randomBytes(16));
  const authorizeUrl = new URL(metadata.authorization_endpoint);
  authorizeUrl.searchParams.set("response_type", "code");
  authorizeUrl.searchParams.set("client_id", clientId);
  authorizeUrl.searchParams.set("redirect_uri", redirectUri);
  authorizeUrl.searchParams.set("code_challenge", codeChallengeFor(verifier));
  authorizeUrl.searchParams.set("code_challenge_method", "S256");
  authorizeUrl.searchParams.set("state", state);
  authorizeUrl.searchParams.set("resource", `${issuer.replace(/\/$/, "")}/mcp/${profile}/`);

  log("info", "sign-in required. Opening your browser — if nothing opens, visit:");
  log("info", authorizeUrl.toString());
  openBrowser(authorizeUrl.toString());

  const authorizationCode = await code;
  const tokenRes = await httpJson("POST", metadata.token_endpoint, {
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code: authorizationCode,
      client_id: clientId,
      redirect_uri: redirectUri,
      code_verifier: verifier,
    }).toString(),
  });
  if (tokenRes.status !== 200) throw new Error(`token exchange failed (status ${tokenRes.status})`);
  const tokens = JSON.parse(tokenRes.text);
  return { ...tokens, client_id: clientId, obtained_at: Date.now() };
}

async function refreshOAuthToken({ issuer, refreshToken, clientId }) {
  const metadata = await discoverAuthServer(issuer);
  const res = await httpJson("POST", metadata.token_endpoint, {
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId,
    }).toString(),
  });
  if (res.status !== 200) return null;
  const tokens = JSON.parse(res.text);
  return { ...tokens, client_id: clientId, obtained_at: Date.now() };
}

function loadCredentials(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function saveCredentials(file, credentials) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(credentials, null, 2), { mode: 0o600 });
}

/** Builds the `getAuthHeader()` closure `HubConnection` calls before every
 * request — token mode returns a constant header; OAuth mode logs in (or
 * refreshes) lazily, on the first call, and again whenever the cached
 * access token is expired. */
function buildAuthProvider({ token, oauth, issuer, profile, credentialsFile }) {
  if (token) {
    const header = `Bearer ${token}`;
    return async () => header;
  }
  if (!oauth) return async () => null;

  let cached = loadCredentials(credentialsFile);

  async function ensureFresh() {
    const now = Date.now();
    const expiresAt = cached ? cached.obtained_at + cached.expires_in * 1000 : 0;
    if (cached && expiresAt - now > 30_000) return cached;
    if (cached && cached.refresh_token) {
      const refreshed = await refreshOAuthToken({
        issuer,
        refreshToken: cached.refresh_token,
        clientId: cached.client_id,
      });
      if (refreshed) {
        cached = { ...refreshed, refresh_token: refreshed.refresh_token || cached.refresh_token };
        saveCredentials(credentialsFile, cached);
        return cached;
      }
      log("info", "cached refresh token no longer works — signing in again.");
    }
    cached = await loginWithOAuth({ issuer, profile });
    saveCredentials(credentialsFile, cached);
    return cached;
  }

  return async () => {
    const creds = await ensureFresh();
    return `Bearer ${creds.access_token}`;
  };
}

// --------------------------------------------------------------------------
// The stdio<->hub relay loop.
// --------------------------------------------------------------------------

export function readConfigFromEnv(env = process.env) {
  const hubUrl = env.PALAIA_HUB_URL;
  if (!hubUrl) {
    throw new Error(
      "PALAIA_HUB_URL is not set. Fix: reinstall the bundle from your hub's connect page, " +
        "or set it by hand in Claude Desktop's extension settings.",
    );
  }
  const oauth = env.PALAIA_OAUTH === "1" || env.PALAIA_OAUTH === "true";
  const token = env.PALAIA_TOKEN || null;
  if (oauth && !token && !env.PALAIA_ISSUER) {
    throw new Error("PALAIA_OAUTH is set but PALAIA_ISSUER is not. Fix: reinstall the bundle.");
  }
  return {
    hubUrl,
    token,
    oauth: oauth && !token,
    issuer: env.PALAIA_ISSUER || null,
    profile: env.PALAIA_PROFILE || "default",
    credentialsFile: env.PALAIA_CREDENTIALS_FILE || defaultCredentialsPath(hubUrl),
  };
}

export async function run(config, { stdin = process.stdin, stdout = process.stdout } = {}) {
  const getAuthHeader = buildAuthProvider(config);
  let triedRefreshOn401 = false;

  const connection = new HubConnection(config.hubUrl, {
    getAuthHeader,
    onMessage: (message) => {
      stdout.write(`${JSON.stringify(message)}\n`);
    },
  });

  const rl = readline.createInterface({ input: stdin, terminal: false });
  let pushStreamStarted = false;

  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let message;
    try {
      message = JSON.parse(trimmed);
    } catch {
      log("info", "dropped a line from the client that was not valid JSON.");
      return;
    }
    handle(message).catch((err) => {
      log("info", describeError(err));
      if (message && message.id !== undefined) {
        stdout.write(
          `${JSON.stringify({
            jsonrpc: "2.0",
            id: message.id,
            error: { code: -32000, message: describeError(err) },
          })}\n`,
        );
      }
    });
  });

  async function handle(message) {
    try {
      await connection.send(message);
    } catch (err) {
      if (err instanceof HttpError && err.status === 401 && config.oauth && !triedRefreshOn401) {
        triedRefreshOn401 = true;
        log("info", "the hub rejected the current session; signing in again.");
        await connection.send(message);
        return;
      }
      throw err;
    }
    if (!pushStreamStarted && connection.sessionId) {
      pushStreamStarted = true;
      connection.openPushStream().catch(() => {
        // openPushStream never rejects (it loops internally) — this catch
        // exists only so a future change to that contract cannot produce
        // an unhandled rejection.
      });
    }
  }

  await new Promise((resolve) => rl.on("close", resolve));
}

export function describeError(err) {
  if (err instanceof HttpError) {
    if (err.status === 401) {
      return "the hub rejected this token or session (401 Unauthorized). Check the credentials in " +
        "your extension settings, or reinstall the bundle from the connect page.";
    }
    return `the hub answered ${err.status}.`;
  }
  if (err && (err.code === "ECONNREFUSED" || err.code === "ENOTFOUND" || err.code === "ETIMEDOUT")) {
    return `could not reach the hub at the configured address (${err.code}). ` +
      "Check that it is running and reachable, then try again.";
  }
  return `unexpected error: ${err && err.message ? err.message : err}`;
}

// --------------------------------------------------------------------------
// Entry point — not run when this file is imported by a test.
// --------------------------------------------------------------------------

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);
if (isMain) {
  try {
    const config = readConfigFromEnv();
    log("info", `forwarding stdio to ${config.hubUrl} (${config.oauth ? "oauth" : "token"} mode)`);
    run(config).catch((err) => {
      log("info", describeError(err));
      process.exit(1);
    });
  } catch (err) {
    log("info", err.message);
    process.exit(1);
  }
}
