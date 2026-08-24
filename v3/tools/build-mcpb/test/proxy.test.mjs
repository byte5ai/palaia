// Unit + local-integration tests for palaia-proxy.mjs, run with the
// built-in Node test runner (`node --test`, no dependency needed — SPEC-306
// keeps the proxy itself dependency-free, and these tests follow suit).
//
// Scope: everything that does not need a real palaia hub or OAuth server —
// those are covered by the Python e2e suite
// (`v3/server/tests/e2e/test_mcpb_proxy.py`), which spawns this exact
// script as a subprocess against a real hub. What lives here: the pure
// helpers (PKCE, backoff, config parsing, error messages) and a fake HTTP
// server standing in for the hub, to exercise `HubConnection`'s wire
// handling (session ids, SSE framing, 401s, reconnect-after-restart)
// without a Python process in the loop.

import assert from "node:assert/strict";
import { createServer } from "node:http";
import test from "node:test";

import {
  HubConnection,
  backoffDelayMs,
  codeChallengeFor,
  defaultCredentialsPath,
  describeError,
  newCodeVerifier,
  readConfigFromEnv,
} from "../proxy/palaia-proxy.mjs";

test("backoffDelayMs doubles and caps", () => {
  assert.equal(backoffDelayMs(0), 250);
  assert.equal(backoffDelayMs(1), 500);
  assert.equal(backoffDelayMs(2), 1000);
  assert.equal(backoffDelayMs(10), 5000);
});

test("PKCE: the verifier and its S256 challenge are both base64url, no padding", () => {
  const verifier = newCodeVerifier();
  assert.match(verifier, /^[A-Za-z0-9_-]+$/);
  const challenge = codeChallengeFor(verifier);
  assert.match(challenge, /^[A-Za-z0-9_-]+$/);
  // Deterministic: the same verifier always produces the same challenge.
  assert.equal(codeChallengeFor(verifier), challenge);
});

test("defaultCredentialsPath is stable for the same URL and differs across URLs", () => {
  const a = defaultCredentialsPath("https://hub.example.com/mcp/default/");
  const b = defaultCredentialsPath("https://hub.example.com/mcp/default/");
  const c = defaultCredentialsPath("https://hub.example.com/mcp/other/");
  assert.equal(a, b);
  assert.notEqual(a, c);
  assert.match(a, /mcpb-credentials/);
});

test("readConfigFromEnv requires PALAIA_HUB_URL", () => {
  assert.throws(() => readConfigFromEnv({}), /PALAIA_HUB_URL/);
});

test("readConfigFromEnv: token mode", () => {
  const config = readConfigFromEnv({
    PALAIA_HUB_URL: "https://hub.example.com/mcp/default/",
    PALAIA_TOKEN: "palaia_abc.def",
  });
  assert.equal(config.token, "palaia_abc.def");
  assert.equal(config.oauth, false);
});

test("readConfigFromEnv: oauth mode needs an issuer", () => {
  assert.throws(
    () => readConfigFromEnv({ PALAIA_HUB_URL: "https://hub.example.com/mcp/default/", PALAIA_OAUTH: "1" }),
    /PALAIA_ISSUER/,
  );
  const config = readConfigFromEnv({
    PALAIA_HUB_URL: "https://hub.example.com/mcp/default/",
    PALAIA_OAUTH: "1",
    PALAIA_ISSUER: "https://hub.example.com",
  });
  assert.equal(config.oauth, true);
  assert.equal(config.issuer, "https://hub.example.com");
});

test("readConfigFromEnv: an explicit token wins over PALAIA_OAUTH=1", () => {
  const config = readConfigFromEnv({
    PALAIA_HUB_URL: "https://hub.example.com/mcp/default/",
    PALAIA_TOKEN: "palaia_abc.def",
    PALAIA_OAUTH: "1",
    PALAIA_ISSUER: "https://hub.example.com",
  });
  assert.equal(config.oauth, false);
});

test("describeError never leaks a stack trace", () => {
  const message = describeError(new Error("boom"));
  assert.doesNotMatch(message, /\n\s+at /); // no stack frames
});

test("describeError: connection refused names the likely cause", () => {
  const message = describeError({ code: "ECONNREFUSED", message: "connect ECONNREFUSED" });
  assert.match(message, /could not reach the hub/);
});

// --------------------------------------------------------------------------
// HubConnection against a fake hub (plain node:http), covering the wire
// shapes mcp/server/streamable_http.py actually produces.
// --------------------------------------------------------------------------

function listen(server) {
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server.address().port)));
}

test("HubConnection: a single application/json reply is forwarded once", async () => {
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const msg = JSON.parse(body);
      res.writeHead(200, { "content-type": "application/json", "mcp-session-id": "sess-1" });
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { ok: true } }));
    });
  });
  const port = await listen(server);
  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });
  await conn.send({ jsonrpc: "2.0", id: 1, method: "tools/list" });
  assert.equal(received.length, 1);
  assert.equal(received[0].result.ok, true);
  assert.equal(conn.sessionId, "sess-1");
  server.close();
});

test("HubConnection: an SSE reply streams each data: frame as its own message", async () => {
  const server = createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/event-stream", "mcp-session-id": "sess-2" });
    res.write(`data: ${JSON.stringify({ jsonrpc: "2.0", method: "notifications/progress", params: {} })}\n\n`);
    res.write(`data: ${JSON.stringify({ jsonrpc: "2.0", id: 7, result: { done: true } })}\n\n`);
    res.end();
  });
  const port = await listen(server);
  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });
  await conn.send({ jsonrpc: "2.0", id: 7, method: "tools/call" });
  assert.equal(received.length, 2);
  assert.equal(received[0].method, "notifications/progress");
  assert.equal(received[1].result.done, true);
  server.close();
});

test("HubConnection: an SSE reply framed with CRLF (sse-starlette's actual wire format) still parses", async () => {
  // Regression test: mcp's Python server (sse-starlette) frames SSE events
  // with CRLF, not LF — found by running the real proxy against a real
  // hub (see the SPEC-306 PR notes). A naive `\n\n`-only frame splitter
  // never finds a boundary and the response silently never arrives.
  const server = createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/event-stream", "mcp-session-id": "sess-crlf" });
    const frame = `event: message\r\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: 1, result: { ok: true } })}\r\n\r\n`;
    res.end(frame);
  });
  const port = await listen(server);
  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });
  await conn.send({ jsonrpc: "2.0", id: 1, method: "initialize" });
  assert.equal(received.length, 1);
  assert.equal(received[0].result.ok, true);
  server.close();
});

test("HubConnection: a CRLF frame split exactly at a chunk boundary still parses", async () => {
  const server = createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/event-stream" });
    const payload = JSON.stringify({ jsonrpc: "2.0", id: 1, result: { ok: true } });
    const frame = `event: message\r\ndata: ${payload}\r\n\r\n`;
    // Split right in the middle of the terminating CRLFCRLF.
    const splitAt = frame.length - 2;
    res.write(frame.slice(0, splitAt));
    setTimeout(() => res.end(frame.slice(splitAt)), 20);
  });
  const port = await listen(server);
  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });
  await conn.send({ jsonrpc: "2.0", id: 1, method: "initialize" });
  assert.equal(received.length, 1);
  assert.equal(received[0].result.ok, true);
  server.close();
});

test("HubConnection: a session id, once assigned, is sent on every later request", async () => {
  const seenSessionHeaders = [];
  const server = createServer((req, res) => {
    seenSessionHeaders.push(req.headers["mcp-session-id"] || null);
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const msg = JSON.parse(body);
      res.writeHead(200, { "content-type": "application/json", "mcp-session-id": "sess-3" });
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: {} }));
    });
  });
  const port = await listen(server);
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: () => {},
  });
  await conn.send({ jsonrpc: "2.0", id: 1, method: "initialize" });
  await conn.send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
  assert.deepEqual(seenSessionHeaders, [null, "sess-3"]);
  server.close();
});

test("HubConnection: a 401 raises an HttpError the caller can act on, not a crash", async () => {
  const server = createServer((req, res) => {
    req.resume();
    res.writeHead(401, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "invalid_token" }));
  });
  const port = await listen(server);
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => "Bearer wrong",
    onMessage: () => {},
  });
  await assert.rejects(
    conn.send({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
    (err) => err.status === 401,
  );
  server.close();
});

test("HubConnection: a 404 on a stale session transparently re-initializes and retries", async () => {
  // Simulates a hub restart from the connection's point of view: the exact
  // same port answers, but it no longer recognizes the previous session
  // id (a fresh process has no memory of it) — a real 404, not a
  // connection failure. The client library only ever sees its original
  // `initialize` call and the one it actually asked for; the synthetic
  // re-initialize is invisible.
  let sessionCounter = 0;
  let currentSession = null;
  const seenMessages = [];
  const server = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const msg = JSON.parse(body);
      seenMessages.push({ method: msg.method, session: req.headers["mcp-session-id"] || null });
      if (msg.method !== "initialize") {
        const clientSession = req.headers["mcp-session-id"];
        if (!clientSession || clientSession !== currentSession) {
          res.writeHead(404, { "content-type": "application/json" });
          res.end(JSON.stringify({ error: "session not found" }));
          return;
        }
      } else {
        sessionCounter += 1;
        currentSession = `sess-${sessionCounter}`;
      }
      res.writeHead(200, { "content-type": "application/json", "mcp-session-id": currentSession });
      res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { forMethod: msg.method } }));
    });
  });
  const port = await listen(server);
  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });

  await conn.send({ jsonrpc: "2.0", id: 1, method: "initialize" });
  assert.equal(received.length, 1);
  assert.equal(conn.sessionId, "sess-1");

  // Simulate the "hub restarted" moment: a brand new session counter, as
  // if this were a fresh process — done here by directly clearing the
  // fake server's notion of the old session without telling the client.
  currentSession = null;

  await conn.send({ jsonrpc: "2.0", id: 2, method: "tools/call" });

  // The real client only ever saw two replies: to its own initialize (id
  // 1) and to its own tools/call (id 2) — never a reply for the
  // synthetic, internal re-initialize.
  assert.deepEqual(
    received.map((m) => m.id),
    [1, 2],
  );
  assert.equal(received[1].result.forMethod, "tools/call");
  // But the server really did see three requests: original initialize,
  // one failed tools/call (404), a silent re-initialize, then the retried
  // tools/call.
  assert.equal(seenMessages.filter((m) => m.method === "initialize").length, 2);
  server.close();
});

test("HubConnection: survives the hub being down, then back up (restart)", async () => {
  // Bind a server, learn its port, close it (nothing is listening there
  // now), send — the connection retries with backoff — then bring a new
  // server up on the *same* port before the retries are exhausted.
  const probe = createServer((req, res) => res.end());
  const port = await listen(probe);
  await new Promise((resolve) => probe.close(resolve));

  let server;
  setTimeout(async () => {
    server = createServer((req, res) => {
      let body = "";
      req.on("data", (c) => (body += c));
      req.on("end", () => {
        const msg = JSON.parse(body);
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({ jsonrpc: "2.0", id: msg.id, result: { recovered: true } }));
      });
    });
    await listen0(server, port);
  }, 300);

  function listen0(srv, p) {
    return new Promise((resolve) => srv.listen(p, "127.0.0.1", resolve));
  }

  const received = [];
  const conn = new HubConnection(`http://127.0.0.1:${port}/mcp/default/`, {
    getAuthHeader: async () => null,
    onMessage: (m) => received.push(m),
  });
  await conn.send({ jsonrpc: "2.0", id: 1, method: "tools/list" }, { maxAttempts: 6 });
  assert.equal(received[0].result.recovered, true);
  server.close();
});
