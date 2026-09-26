/**
 * Tests for pre-compaction capture (#185).
 *
 * Host behaviour these tests model (OpenClaw v2026.5.7 … v2026.9.6):
 * - before_compaction handlers are awaited (30 s default timeout).
 * - When a ContextEngine owns compaction (palaia does), the host fires
 *   before_compaction with `{ messageCount: -1, sessionFile }` — no
 *   messages — and then calls the engine's compact().
 * - The host calls afterTurn() instead of ingest() when an engine defines
 *   afterTurn(), and may resolve a fresh engine instance per call.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("../src/runner.js", () => ({
  runJson: vi.fn().mockResolvedValue({ results: [] }),
  run: vi.fn().mockResolvedValue(""),
  detectBinary: vi.fn().mockResolvedValue("palaia"),
  recover: vi.fn().mockResolvedValue({ replayed: 0, errors: 0 }),
  resetCache: vi.fn(),
  getEmbedServerManager: vi.fn().mockReturnValue({ start: vi.fn(), query: vi.fn() }),
}));

vi.mock("../src/priorities.js", () => ({
  loadPriorities: vi.fn().mockResolvedValue({}),
  resolvePriorities: vi.fn().mockReturnValue({
    recallTypeWeight: {},
    recallMinScore: 0.1,
    maxInjectedChars: 4000,
    tier: "hot",
    blocked: [],
  }),
  filterBlocked: vi.fn((entries: any[]) => entries),
}));

vi.mock("../src/hooks/capture.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/hooks/capture.js")>();
  return {
    ...actual,
    extractWithLLM: vi.fn().mockResolvedValue([{ content: "LLM summary of the conversation" }]),
    loadProjects: vi.fn().mockResolvedValue([]),
  };
});

// Wrap captureBeforeContextLoss so a test can make it reject when called
// from the ContextEngine. registerSessionHooks() uses the module-internal
// binding and is unaffected.
vi.mock("../src/hooks/session.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/hooks/session.js")>();
  return { ...actual, captureBeforeContextLoss: vi.fn(actual.captureBeforeContextLoss) };
});

import {
  registerSessionHooks,
  captureSessionSummary,
  captureBeforeContextLoss,
  FORCED_CAPTURE_COOLDOWN_MS,
} from "../src/hooks/session.js";
import { createPalaiaContextEngine } from "../src/context-engine.js";
import { getOrCreateSessionState, sessionStateByKey, RECENT_MESSAGE_CAP } from "../src/hooks/state.js";
import { extractWithLLM } from "../src/hooks/capture.js";
import { resolveConfig, DEFAULT_CONFIG, type PalaiaPluginConfig } from "../src/config.js";
import { run } from "../src/runner.js";
import palaiaPlugin from "../index.js";

const mockRun = vi.mocked(run);
const mockExtract = vi.mocked(extractWithLLM);
const mockCaptureBeforeContextLoss = vi.mocked(captureBeforeContextLoss);

const KEY = "agent:main:test";

function makeConfig(overrides: Partial<PalaiaPluginConfig> = {}): PalaiaPluginConfig {
  return resolveConfig({
    workspace: "/tmp/palaia-test",
    embeddingServer: false,
    captureToolObservations: false,
    ...overrides,
  });
}

function createMockApi(extra: Record<string, unknown> = {}) {
  return {
    logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    config: {},
    on: vi.fn(),
    registerTool: vi.fn(),
    runtime: undefined,
    ...extra,
  } as any;
}

function handlerFor(api: any, hook: string): ((event: any, ctx: any) => Promise<void>) | undefined {
  return api.on.mock.calls.find((c: any[]) => c[0] === hook)?.[1];
}

function writeCalls(): string[][] {
  return mockRun.mock.calls.map((c) => c[0] as string[]).filter((a) => a[0] === "write");
}

function tagsOf(args: string[]): string {
  return args[args.indexOf("--tags") + 1];
}

const conversation = [
  { role: "user", content: "Let's move the ingest job to a nightly schedule." },
  { role: "assistant", content: "Agreed — nightly at 02:00 UTC, with a retry at 03:00." },
  { role: "user", content: "And alert #ops if both runs fail." },
  { role: "assistant", content: "Noted: alert #ops only when both the 02:00 and 03:00 runs fail." },
];

const observation = {
  toolName: "bash",
  paramsSummary: "cmd=ls",
  resultSummary: "README.md src tests",
  durationMs: 5,
  timestamp: Date.now(),
};

beforeEach(() => {
  vi.clearAllMocks();
  mockRun.mockResolvedValue("");
  mockExtract.mockResolvedValue([{ content: "LLM summary of the conversation" } as any]);
  sessionStateByKey.clear();
});

// ── Registration ──────────────────────────────────────────────────────────

describe("before_compaction registration", () => {
  it("defaults captureOnCompaction to true", () => {
    expect(DEFAULT_CONFIG.captureOnCompaction).toBe(true);
    expect(resolveConfig({}).captureOnCompaction).toBe(true);
  });

  it("1. registers a before_compaction handler when captureOnCompaction is true", () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig({ captureOnCompaction: true }));
    expect(handlerFor(api, "before_compaction")).toBeTypeOf("function");
  });

  it("2. does not register it when captureOnCompaction is false", () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig({ captureOnCompaction: false }));
    expect(handlerFor(api, "before_compaction")).toBeUndefined();
  });

  it("3. registers it on the ContextEngine path too (not only in legacy registerHooks)", () => {
    const api = createMockApi({
      pluginConfig: { workspace: "/tmp/palaia-test", embeddingServer: false },
      registerContextEngine: vi.fn(),
    });
    palaiaPlugin.register(api);
    expect(api.registerContextEngine).toHaveBeenCalledWith("palaia", expect.any(Function));
    expect(handlerFor(api, "before_compaction")).toBeTypeOf("function");
    // The legacy agent_end hook is NOT registered on this path.
    expect(handlerFor(api, "agent_end")).toBeUndefined();
  });
});

// ── Force semantics ───────────────────────────────────────────────────────

describe("captureSessionSummary force flag", () => {
  it("4. force bypasses the summarySaved guard", async () => {
    getOrCreateSessionState(KEY).summarySaved = true;
    const wrote = await captureSessionSummary(conversation, KEY, createMockApi(), makeConfig(), createMockApi().logger, { force: true });
    expect(wrote).toBe(true);
    expect(writeCalls()).toHaveLength(1);
  });

  it("5. without force, summarySaved blocks the write", async () => {
    getOrCreateSessionState(KEY).summarySaved = true;
    const wrote = await captureSessionSummary(conversation, KEY, createMockApi(), makeConfig(), createMockApi().logger);
    expect(wrote).toBe(false);
    expect(writeCalls()).toHaveLength(0);
  });

  it("6. a forced write leaves summarySaved false, so session_end still writes", async () => {
    const api = createMockApi();
    const config = makeConfig();
    registerSessionHooks(api, config);

    await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test");
    const state = getOrCreateSessionState(KEY);
    expect(state.summarySaved).toBe(false);
    expect(state.lastForcedCaptureAt).toBeGreaterThan(0);

    // session_end has no messages; it summarises tool observations.
    state.toolObservations.push(observation);
    await handlerFor(api, "session_end")!({ sessionId: "s1", messageCount: 12 }, { sessionKey: KEY });
    const writes = writeCalls();
    expect(writes).toHaveLength(2);
    expect(tagsOf(writes[1])).toBe("session-summary,auto-capture");
  });

  it("7. pre-compaction tags are exactly session-summary,pre-compaction,auto-capture", async () => {
    const api = createMockApi();
    await captureBeforeContextLoss(conversation, KEY, api, makeConfig(), api.logger, "test");
    expect(tagsOf(writeCalls()[0])).toBe("session-summary,pre-compaction,auto-capture");
  });

  it("8. cooldown: a second forced capture within the window is skipped, after it writes again", async () => {
    const api = createMockApi();
    const config = makeConfig();
    expect(await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test")).toBe(true);
    expect(await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test")).toBe(false);
    expect(writeCalls()).toHaveLength(1);

    getOrCreateSessionState(KEY).lastForcedCaptureAt = Date.now() - FORCED_CAPTURE_COOLDOWN_MS - 1;
    expect(await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test")).toBe(true);
    expect(writeCalls()).toHaveLength(2);
  });

  it("a failed forced write does not arm the cooldown", async () => {
    const api = createMockApi();
    const config = makeConfig();
    mockRun.mockRejectedValueOnce(new Error("disk full"));
    expect(await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test")).toBe(false);
    expect(getOrCreateSessionState(KEY).lastForcedCaptureAt).toBe(0);
    expect(await captureBeforeContextLoss(conversation, KEY, api, config, api.logger, "test")).toBe(true);
  });
});

// ── Guards ────────────────────────────────────────────────────────────────

describe("before_compaction guards", () => {
  it("9. no sessionKey in ctx: no write, no throw", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    await expect(
      handlerFor(api, "before_compaction")!({ messageCount: 4, messages: conversation }, {}),
    ).resolves.toBeUndefined();
    expect(mockRun).not.toHaveBeenCalled();
  });

  it("10. no messages, no buffer, no tool observations: no write", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    await handlerFor(api, "before_compaction")!({ messageCount: -1, sessionFile: "/tmp/s.jsonl" }, { sessionKey: KEY });
    expect(writeCalls()).toHaveLength(0);
  });

  it("11. no messages but tool observations: writes the observation summary", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    getOrCreateSessionState(KEY).toolObservations.push(observation);
    await handlerFor(api, "before_compaction")!({ messageCount: -1 }, { sessionKey: KEY });
    const writes = writeCalls();
    expect(writes).toHaveLength(1);
    expect(writes[0][1]).toContain("bash: README.md src tests");
    expect(mockExtract).not.toHaveBeenCalled();
  });

  it("uses event.messages when the host provides them", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    await handlerFor(api, "before_compaction")!(
      { messageCount: conversation.length, messages: conversation },
      { sessionKey: KEY },
    );
    expect(mockExtract).toHaveBeenCalledWith(conversation, expect.anything(), expect.anything(), []);
    expect(writeCalls()[0][1]).toBe("LLM summary of the conversation");
  });

  it("a capture that throws never escapes the hook handler", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    const poisoned = [{ get role(): string { throw new Error("bad message"); } }];
    mockExtract.mockRejectedValueOnce(new Error("no LLM"));
    await expect(
      handlerFor(api, "before_compaction")!({ messageCount: 1, messages: poisoned }, { sessionKey: KEY }),
    ).resolves.toBeUndefined();
    expect(api.logger.warn).toHaveBeenCalled();
    expect(getOrCreateSessionState(KEY).forcedCaptureInFlight).toBeNull();
  });
});

// ── ContextEngine path ────────────────────────────────────────────────────

describe("ContextEngine compact() pre-compaction capture", () => {
  it("12. compact() captures before running gc", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, makeConfig());
    await engine.afterTurn!({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl", messages: conversation, prePromptMessageCount: 0 });
    vi.clearAllMocks();
    mockRun.mockResolvedValue("");

    const result = await engine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });
    const verbs = mockRun.mock.calls.map((c) => (c[0] as string[])[0]);
    expect(verbs).toEqual(["write", "gc"]);
    expect(tagsOf(writeCalls()[0])).toBe("session-summary,pre-compaction,auto-capture");
    expect(result.ok).toBe(true);
  });

  it("13. compact() still runs gc and returns ok when capture rejects", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, makeConfig());
    mockCaptureBeforeContextLoss.mockRejectedValueOnce(new Error("capture exploded"));

    const result = await engine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });
    expect(mockRun.mock.calls.map((c) => (c[0] as string[])[0])).toEqual(["gc"]);
    expect(result.ok).toBe(true);
    expect(api.logger.warn).toHaveBeenCalledWith(expect.stringContaining("Pre-compaction capture failed"));
  });

  it("compact() skips capture when captureOnCompaction is false", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, makeConfig({ captureOnCompaction: false }));
    getOrCreateSessionState(KEY).recentMessages = [...conversation];
    await engine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });
    expect(mockRun.mock.calls.map((c) => (c[0] as string[])[0])).toEqual(["gc"]);
  });

  it("14a. afterTurn() fills the per-session message buffer (capped)", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, makeConfig({ autoCapture: false }));
    const many = Array.from({ length: RECENT_MESSAGE_CAP + 25 }, (_, i) => ({ role: "user", content: `m${i}` }));
    await engine.afterTurn!({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl", messages: many, prePromptMessageCount: 0 });
    const buf = getOrCreateSessionState(KEY).recentMessages;
    expect(buf).toHaveLength(RECENT_MESSAGE_CAP);
    expect(buf[buf.length - 1]).toEqual({ role: "user", content: `m${RECENT_MESSAGE_CAP + 24}` });
    expect(buf[0]).toEqual({ role: "user", content: "m25" });
  });

  it("ingest() also feeds the buffer for hosts that do not call afterTurn()", async () => {
    const api = createMockApi();
    const engine = createPalaiaContextEngine(api, makeConfig());
    for (const message of conversation) {
      await engine.ingest({ sessionId: "s1", sessionKey: KEY, message });
    }
    expect(getOrCreateSessionState(KEY).recentMessages).toEqual(conversation);
  });

  it("14b. compact() on a fresh engine instance still captures from session state", async () => {
    const api = createMockApi();
    const runEngine = createPalaiaContextEngine(api, makeConfig({ autoCapture: false }));
    await runEngine.afterTurn!({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl", messages: conversation, prePromptMessageCount: 0 });

    // Queued compaction: the host resolves a new engine instance.
    const compactEngine = createPalaiaContextEngine(api, makeConfig({ autoCapture: false }));
    await compactEngine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });

    expect(mockExtract).toHaveBeenCalledWith(conversation, expect.anything(), expect.anything(), []);
    expect(writeCalls()[0][1]).toBe("LLM summary of the conversation");
  });

  it("14c. ownsCompaction payload ({messageCount:-1, sessionFile}) uses the buffer, not the observation fallback", async () => {
    const api = createMockApi();
    registerSessionHooks(api, makeConfig());
    const state = getOrCreateSessionState(KEY);
    state.recentMessages = [...conversation];
    state.toolObservations.push(observation);

    await handlerFor(api, "before_compaction")!({ messageCount: -1, sessionFile: "/tmp/s.jsonl" }, { sessionKey: KEY });

    const writes = writeCalls();
    expect(writes).toHaveLength(1);
    expect(writes[0][1]).toBe("LLM summary of the conversation");
    expect(writes[0][1]).not.toContain("bash:");
  });

  it("host sequence before_compaction → compact() writes exactly one entry", async () => {
    const api = createMockApi();
    const config = makeConfig({ autoCapture: false });
    registerSessionHooks(api, config);
    const engine = createPalaiaContextEngine(api, config);
    await engine.afterTurn!({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl", messages: conversation, prePromptMessageCount: 0 });

    await handlerFor(api, "before_compaction")!({ messageCount: -1, sessionFile: "/tmp/s.jsonl" }, { sessionKey: KEY });
    await engine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });

    expect(writeCalls()).toHaveLength(1);
    expect(mockRun.mock.calls.map((c) => (c[0] as string[])[0])).toEqual(["write", "gc"]);
  });

  it("in-flight guard: compact() does not start a second capture while the hook's is running", async () => {
    const api = createMockApi();
    const config = makeConfig({ autoCapture: false });
    registerSessionHooks(api, config);
    const engine = createPalaiaContextEngine(api, config);
    getOrCreateSessionState(KEY).recentMessages = [...conversation];

    // Simulate a slow LLM extraction: the host's 30 s hook timeout fires and
    // it proceeds to compact() while the hook's capture is still running.
    let release!: (v: any) => void;
    mockExtract.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    const hookRun = handlerFor(api, "before_compaction")!({ messageCount: -1 }, { sessionKey: KEY });
    await vi.waitFor(() => expect(mockExtract).toHaveBeenCalledTimes(1));

    await engine.compact({ sessionId: "s1", sessionKey: KEY, sessionFile: "/tmp/s.jsonl" });
    expect(mockExtract).toHaveBeenCalledTimes(1);
    expect(mockRun.mock.calls.map((c) => (c[0] as string[])[0])).toEqual(["gc"]);

    release([{ content: "LLM summary of the conversation" }]);
    await hookRun;
    expect(writeCalls()).toHaveLength(1);
    expect(getOrCreateSessionState(KEY).forcedCaptureInFlight).toBeNull();
  });
});
