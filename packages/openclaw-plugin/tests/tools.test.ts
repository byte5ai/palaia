/**
 * Tests for src/tools.ts — memory_search, memory_get, memory_write with mock runner.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Mock the runner module
const mockQuery = vi.fn();
vi.mock("../src/runner.js", () => ({
  runJson: vi.fn(),
  run: vi.fn(),
  detectBinary: vi.fn().mockResolvedValue("palaia"),
  recover: vi.fn().mockResolvedValue({ replayed: 0, errors: 0 }),
  resetCache: vi.fn(),
  getEmbedServerManager: vi.fn(() => ({ query: mockQuery })),
}));

// The real priorities module, with resolvePriorities wrapped so tests can
// inspect its arguments or make it throw.
vi.mock("../src/priorities.js", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/priorities.js")>();
  return { ...actual, resolvePriorities: vi.fn(actual.resolvePriorities) };
});

import { Value } from "@sinclair/typebox/value";
import { registerTools } from "../src/tools.js";
import { runJson } from "../src/runner.js";
import { DEFAULT_CONFIG } from "../src/config.js";
import { resolvePriorities, resetPrioritiesCache } from "../src/priorities.js";

const mockRunJson = vi.mocked(runJson);
const mockResolvePriorities = vi.mocked(resolvePriorities);

/**
 * Fake plugin API that captures registered tools.
 */
function createMockApi() {
  const tools: Record<string, { def: any; opts?: any }> = {};
  return {
    tools,
    registerTool(def: any, opts?: any) {
      tools[def.name] = { def, opts };
    },
  };
}

describe("tools", () => {
  let api: ReturnType<typeof createMockApi>;

  beforeEach(() => {
    vi.clearAllMocks();
    api = createMockApi();
    registerTools(api, DEFAULT_CONFIG);
  });

  it("registers memory_search, memory_get, memory_write", () => {
    expect(api.tools["memory_search"]).toBeDefined();
    expect(api.tools["memory_get"]).toBeDefined();
    expect(api.tools["memory_write"]).toBeDefined();
  });

  it("memory_write is optional", () => {
    expect(api.tools["memory_write"].opts).toEqual({ optional: true });
  });

  it("memory_search and memory_get are required (no optional flag)", () => {
    expect(api.tools["memory_search"].opts).toBeUndefined();
    expect(api.tools["memory_get"].opts).toBeUndefined();
  });

  describe("memory_search", () => {
    it("returns formatted results via embed server", async () => {
      mockQuery.mockResolvedValueOnce({
        result: {
          results: [
            {
              id: "abc-123",
              body: "Test memory content",
              score: 0.92,
              tier: "hot",
              scope: "team",
              title: "Test Entry",
              path: "hot/abc-123.md",
            },
          ],
        },
      });

      const execute = api.tools["memory_search"].def.execute;
      const result = await execute("call-1", { query: "test" });

      expect(result.content).toHaveLength(1);
      expect(result.content[0].type).toBe("text");
      expect(result.content[0].text).toContain("Test memory content");
      expect(result.content[0].text).toContain("Source: hot/abc-123.md");
      expect(result.content[0].text).toContain("score: 0.92");

      // Should use embed server, not CLI
      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ text: "test", top_k: 10 }),
        expect.any(Number)
      );
      expect(mockRunJson).not.toHaveBeenCalled();
    });

    it("falls back to CLI when embed server fails", async () => {
      mockQuery.mockRejectedValueOnce(new Error("server down"));
      mockRunJson.mockResolvedValueOnce({
        results: [
          {
            id: "abc-123",
            body: "Fallback content",
            score: 0.85,
            tier: "hot",
            scope: "team",
            path: "hot/abc-123.md",
          },
        ],
      });

      const result = await api.tools["memory_search"].def.execute("call-fb", {
        query: "test",
      });

      expect(result.content[0].text).toContain("Fallback content");
      expect(mockRunJson).toHaveBeenCalledWith(
        ["query", "test", "--limit", "10"],
        expect.objectContaining({ timeoutMs: 15000 })
      );
    });

    it("respects maxResults param", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      await api.tools["memory_search"].def.execute("call-2", {
        query: "test",
        maxResults: 20,
      });

      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ top_k: 20 }),
        expect.any(Number)
      );
    });

    it("falls back to the configured maxResults when the param is omitted", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      await api.tools["memory_search"].def.execute("call-2b", {
        query: "test",
      });

      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ top_k: DEFAULT_CONFIG.maxResults }),
        expect.any(Number)
      );
    });

    it("declares no schema default for maxResults, so hosts cannot override the config (#465)", () => {
      const maxResults = api.tools["memory_search"].def.parameters.properties.maxResults;
      expect(maxResults.default).toBeUndefined();
    });

    describe("maxResults accepts only integers from 1 to the maximum (#483)", () => {
      function searchSchema() {
        return api.tools["memory_search"].def.parameters;
      }

      it("declares maxResults as an integer with minimum 1 and a maximum", () => {
        const { maxResults } = searchSchema().properties;
        expect(maxResults.type).toBe("integer");
        expect(maxResults.minimum).toBe(1);
        expect(maxResults.maximum).toBe(100);
        expect(maxResults.description).toContain("1 to 100");
      });

      it.each([0, -3, 2.5, 101])("the schema rejects maxResults %s", (value) => {
        expect(Value.Check(searchSchema(), { query: "test", maxResults: value })).toBe(false);
      });

      it.each([1, 7, 100])("the schema accepts maxResults %s", (value) => {
        expect(Value.Check(searchSchema(), { query: "test", maxResults: value })).toBe(true);
      });

      it.each([0, -3, 2.5, 101, "5"])(
        "execute() rejects maxResults %s without searching",
        async (value) => {
          const result = await api.tools["memory_search"].def.execute("call-483", {
            query: "test",
            maxResults: value,
          });

          expect(result.content[0].text).toBe(
            `Invalid maxResults ${JSON.stringify(value)}: must be an integer from 1 to 100.`
          );
          expect(mockQuery).not.toHaveBeenCalled();
          expect(mockRunJson).not.toHaveBeenCalled();
        }
      );

      it.each([1, 100])("execute() passes maxResults %s through unchanged", async (value) => {
        mockQuery.mockRejectedValueOnce(new Error("server down"));
        mockRunJson.mockResolvedValueOnce({ results: [] });

        await api.tools["memory_search"].def.execute("call-483b", {
          query: "test",
          maxResults: value,
        });

        expect(mockQuery).toHaveBeenCalledWith(
          expect.objectContaining({ top_k: value }),
          expect.any(Number)
        );
        expect(mockRunJson).toHaveBeenCalledWith(
          ["query", "test", "--limit", String(value)],
          expect.any(Object)
        );
      });

      it("raises the maximum to a larger configured maxResults, so the default stays valid", () => {
        const custom = createMockApi();
        registerTools(custom, { ...DEFAULT_CONFIG, maxResults: 250 });
        const { maxResults } = custom.tools["memory_search"].def.parameters.properties;
        expect(maxResults.maximum).toBe(250);
        expect(maxResults.description).toContain("default: 250");
      });

      it.each([0, -3, 2.5])(
        "falls back to the built-in default for an invalid configured maxResults %s",
        async (value) => {
          const custom = createMockApi();
          registerTools(custom, { ...DEFAULT_CONFIG, maxResults: value });
          const def = custom.tools["memory_search"].def;
          expect(def.parameters.properties.maxResults.description).toContain(
            `default: ${DEFAULT_CONFIG.maxResults}`
          );

          mockQuery.mockResolvedValueOnce({ result: { results: [] } });
          await def.execute("call-483c", { query: "test" });
          expect(mockQuery).toHaveBeenCalledWith(
            expect.objectContaining({ top_k: DEFAULT_CONFIG.maxResults }),
            expect.any(Number)
          );
        }
      );
    });

    describe("schema descriptions follow the resolved config (#465)", () => {
      function registerWith(overrides: Partial<typeof DEFAULT_CONFIG>) {
        const custom = createMockApi();
        registerTools(custom, { ...DEFAULT_CONFIG, ...overrides });
        return custom.tools["memory_search"].def;
      }

      it("states the default maxResults", () => {
        const { maxResults } = api.tools["memory_search"].def.parameters.properties;
        expect(maxResults.description).toContain(`default: ${DEFAULT_CONFIG.maxResults}`);
      });

      it("states a configured maxResults, and execute() uses that same value", async () => {
        const def = registerWith({ maxResults: 25 });
        expect(def.parameters.properties.maxResults.description).toContain("default: 25");

        mockQuery.mockResolvedValueOnce({ result: { results: [] } });
        await def.execute("call-2c", { query: "test" });
        expect(mockQuery).toHaveBeenCalledWith(
          expect.objectContaining({ top_k: 25 }),
          expect.any(Number)
        );
      });

      it("describes tier as the switch for cold entries by default", () => {
        const { tier } = api.tools["memory_search"].def.parameters.properties;
        expect(tier.description).toContain('Pass "all" to include cold');
      });

      it("says tier has no effect when the plugin tier setting is already \"all\"", async () => {
        const def = registerWith({ tier: "all" });
        expect(def.parameters.properties.tier.description).toContain("no effect");

        mockQuery.mockResolvedValueOnce({ result: { results: [] } });
        await def.execute("call-3b", { query: "test", tier: "hot" });
        expect(mockQuery).toHaveBeenCalledWith(
          expect.objectContaining({ include_cold: true }),
          expect.any(Number)
        );
      });
    });

    it("passes include_cold for tier=all", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      await api.tools["memory_search"].def.execute("call-3", {
        query: "test",
        tier: "all",
      });

      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ include_cold: true }),
        expect.any(Number)
      );
    });

    it("returns 'No results found.' when empty", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      const result = await api.tools["memory_search"].def.execute("call-4", {
        query: "nothing",
      });

      expect(result.content[0].text).toBe("No results found.");
    });
  });

  describe("memory_search resolves the tier like auto-recall (#482)", () => {
    let workspace: string;
    const savedAgent = process.env.PALAIA_AGENT;

    function writePriorities(prio: object) {
      mkdirSync(join(workspace, ".palaia"), { recursive: true });
      writeFileSync(join(workspace, ".palaia", "priorities.json"), JSON.stringify(prio));
    }

    async function searchIncludesCold(
      overrides: Partial<typeof DEFAULT_CONFIG>,
      params: Record<string, unknown> = {},
    ): Promise<boolean> {
      const custom = createMockApi();
      registerTools(custom, { ...DEFAULT_CONFIG, workspace, ...overrides });
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });
      await custom.tools["memory_search"].def.execute("call-482", { query: "test", ...params });
      return mockQuery.mock.calls.at(-1)![0].include_cold;
    }

    beforeEach(() => {
      workspace = mkdtempSync(join(tmpdir(), "palaia-tools-482-"));
      resetPrioritiesCache();
      process.env.PALAIA_AGENT = "alice";
    });

    afterEach(() => {
      rmSync(workspace, { recursive: true, force: true });
      resetPrioritiesCache();
      if (savedAgent === undefined) delete process.env.PALAIA_AGENT;
      else process.env.PALAIA_AGENT = savedAgent;
    });

    it("includes cold entries when this agent's override sets tier \"all\"", async () => {
      writePriorities({ version: 1, blocked: [], agents: { alice: { tier: "all" } } });
      expect(await searchIncludesCold({ tier: "hot" })).toBe(true);
    });

    it("ignores another agent's tier override", async () => {
      writePriorities({ version: 1, blocked: [], agents: { bob: { tier: "all" } } });
      expect(await searchIncludesCold({ tier: "hot" })).toBe(false);
    });

    it("includes cold entries when the global override sets tier \"all\"", async () => {
      writePriorities({ version: 1, blocked: [], tier: "all" });
      expect(await searchIncludesCold({ tier: "hot" })).toBe(true);
    });

    it("lets an agent override narrow a plugin tier of \"all\"; tier: \"all\" still widens it", async () => {
      writePriorities({ version: 1, blocked: [], agents: { alice: { tier: "hot" } } });
      expect(await searchIncludesCold({ tier: "all" })).toBe(false);
      expect(await searchIncludesCold({ tier: "all" }, { tier: "all" })).toBe(true);
    });

    it("resolves with the configured captureProject, as recall does", async () => {
      writePriorities({ version: 1, blocked: [], projects: { alpha: { recallTypeWeight: { task: 2 } } } });
      await searchIncludesCold({ captureProject: "alpha" });
      expect(mockResolvePriorities).toHaveBeenLastCalledWith(
        expect.objectContaining({ projects: expect.any(Object) }),
        expect.objectContaining({ tier: DEFAULT_CONFIG.tier }),
        "alice",
        "alpha",
      );
    });

    it("matches recall for a project-level tier: projects carry no tier override", async () => {
      // resolvePriorities applies only blocked and recallTypeWeight per project,
      // so recall ignores this entry and memory_search must too.
      writePriorities({ version: 1, blocked: [], projects: { alpha: { tier: "all" } } });
      expect(await searchIncludesCold({ tier: "hot", captureProject: "alpha" })).toBe(false);
    });

    it("applies this agent's scopeVisibility together with the project", async () => {
      writePriorities({
        version: 1,
        blocked: [],
        agents: { alice: { scopeVisibility: ["private"] } },
        projects: { alpha: { blocked: [] } },
      });
      const custom = createMockApi();
      registerTools(custom, { ...DEFAULT_CONFIG, workspace, captureProject: "alpha" });
      mockQuery.mockResolvedValueOnce({
        result: {
          results: [
            { id: "a", body: "mine", score: 1, tier: "hot", scope: "private" },
            { id: "b", body: "team entry", score: 0.9, tier: "hot", scope: "team" },
          ],
        },
      });
      const result = await custom.tools["memory_search"].def.execute("call-482b", { query: "test" });
      expect(result.content[0].text).toContain("mine");
      expect(result.content[0].text).not.toContain("team entry");
    });

    it.each([
      ["all", true],
      ["hot", false],
    ])("falls back to the plugin tier %s when resolving priorities fails", async (tier, cold) => {
      mockResolvePriorities.mockImplementationOnce(() => {
        throw new Error("broken priorities");
      });
      expect(await searchIncludesCold({ tier })).toBe(cold);
    });

    it("the tier description names the priorities override", () => {
      for (const tier of ["hot", "all"]) {
        const custom = createMockApi();
        registerTools(custom, { ...DEFAULT_CONFIG, tier });
        const { tier: tierParam } = custom.tools["memory_search"].def.parameters.properties;
        expect(tierParam.description).toContain(".palaia/priorities.json");
      }
    });
  });

  describe("memory_get", () => {
    it("returns entry content", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "abc-123",
        content: "Full entry content here",
        meta: { scope: "team", tier: "hot" },
      });

      const result = await api.tools["memory_get"].def.execute("call-5", {
        path: "abc-123",
      });

      expect(result.content[0].text).toBe("Full entry content here");
      expect(mockRunJson).toHaveBeenCalledWith(
        ["get", "abc-123"],
        expect.any(Object)
      );
    });

    it("passes --from and --lines", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "abc-123",
        content: "Line 5\nLine 6",
        meta: { scope: "team", tier: "hot" },
      });

      await api.tools["memory_get"].def.execute("call-6", {
        path: "abc-123",
        from: 5,
        lines: 2,
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        ["get", "abc-123", "--from", "5", "--lines", "2"],
        expect.any(Object)
      );
    });

    describe("from and lines accept only integers >= 1 (#483)", () => {
      function getSchema() {
        return api.tools["memory_get"].def.parameters;
      }

      it("declares from and lines as integers with minimum 1", () => {
        const { from, lines } = getSchema().properties;
        expect(from).toMatchObject({ type: "integer", minimum: 1 });
        expect(lines).toMatchObject({ type: "integer", minimum: 1 });
      });

      it.each([
        ["from", 0],
        ["from", -1],
        ["from", 1.5],
        ["lines", 0],
        ["lines", -3],
        ["lines", 2.5],
      ])("the schema rejects %s = %s", (name, value) => {
        expect(Value.Check(getSchema(), { path: "abc-123", [name]: value })).toBe(false);
      });

      it("the schema accepts from and lines of 1 and above", () => {
        expect(Value.Check(getSchema(), { path: "abc-123", from: 1, lines: 1 })).toBe(true);
        expect(Value.Check(getSchema(), { path: "abc-123", from: 40, lines: 500 })).toBe(true);
      });

      it.each([
        ["from", 0],
        ["from", -1],
        ["from", 1.5],
        ["lines", 0],
        ["lines", -3],
        ["lines", 2.5],
        ["lines", "2"],
      ])("execute() rejects %s = %s without calling the CLI", async (name, value) => {
        const result = await api.tools["memory_get"].def.execute("call-483d", {
          path: "abc-123",
          [name]: value,
        });

        expect(result.content[0].text).toBe(
          `Invalid ${name} ${JSON.stringify(value)}: must be an integer >= 1.`
        );
        expect(mockRunJson).not.toHaveBeenCalled();
      });
    });
  });

  describe("memory_write", () => {
    it("writes and returns confirmation", async () => {
      // First call: duplicate guard query (returns no duplicates)
      mockRunJson.mockResolvedValueOnce({ results: [] });
      // Second call: actual write
      mockRunJson.mockResolvedValueOnce({
        id: "new-456",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      const result = await api.tools["memory_write"].def.execute("call-7", {
        content: "Important note",
        scope: "team",
        tags: ["project", "idea"],
      });

      expect(result.content[0].text).toContain("new-456");
      expect(result.content[0].text).toContain("hot");
      expect(mockRunJson).toHaveBeenCalledWith(
        ["write", "Important note", "--scope", "team", "--tags", "project,idea"],
        expect.any(Object)
      );
    });

    it("works without optional params", async () => {
      // Duplicate guard query
      mockRunJson.mockResolvedValueOnce({ results: [] });
      mockRunJson.mockResolvedValueOnce({
        id: "new-789",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      await api.tools["memory_write"].def.execute("call-8", {
        content: "Simple note",
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        ["write", "Simple note"],
        expect.any(Object)
      );
    });

    it("passes --type, --project, --title params (Issue #82)", async () => {
      // Duplicate guard query
      mockRunJson.mockResolvedValueOnce({ results: [] });
      mockRunJson.mockResolvedValueOnce({
        id: "new-type-1",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      const result = await api.tools["memory_write"].def.execute("call-82", {
        content: "Deploy checklist",
        type: "process",
        project: "myapp",
        title: "Deploy Steps",
        scope: "team",
        tags: ["deploy"],
      });

      expect(result.content[0].text).toContain("new-type-1");
      expect(mockRunJson).toHaveBeenCalledWith(
        [
          "write", "Deploy checklist",
          "--scope", "team",
          "--tags", "deploy",
          "--type", "process",
          "--project", "myapp",
          "--title", "Deploy Steps",
        ],
        expect.any(Object)
      );
    });

    /**
     * A `palaia query --json` hit. `created` uses palaia's own format —
     * Python's isoformat(): microseconds and a "+00:00" offset. `score` is
     * palaia's hybrid ranking score (0.4 * relative BM25 + 0.6 * cosine);
     * `embed_score` is the raw cosine similarity, 0 without embeddings.
     */
    function queryHit(
      createdMsAgo: number | null,
      { embedScore = 0.95, bm25Score = 1.0 }: { embedScore?: number; bm25Score?: number } = {},
    ) {
      const created =
        createdMsAgo === null
          ? undefined
          : new Date(Date.now() - createdMsAgo).toISOString().replace(/\.(\d{3})Z$/, ".$1000+00:00");
      return {
        id: "dup-1",
        body: "Deploy checklist",
        score: embedScore > 0 ? 0.4 * bm25Score + 0.6 * embedScore : bm25Score,
        bm25_score: bm25Score,
        embed_score: embedScore,
        tier: "hot",
        scope: "team",
        title: "Deploy Steps",
        ...(created === undefined ? {} : { created }),
      };
    }

    /** Embed-server response wrapping the given query hits. */
    function serverResults(...results: unknown[]) {
      return { result: { results } };
    }

    const written = { id: "new-1", tier: "hot", scope: "team", deduplicated: false };

    it("duplicate guard blocks a similar entry from the last 24h and points the retry at force (Issue #466)", async () => {
      mockQuery.mockResolvedValueOnce(serverResults(queryHit(60 * 60 * 1000)));

      const result = await api.tools["memory_write"].def.execute("call-466", {
        content: "Deploy checklist",
      });

      const text = result.content[0].text;
      expect(text).toContain("Similar entry already exists");
      expect(text).toContain("dup-1");
      expect(text).toContain("similarity: 0.95");
      expect(text).toContain("force: true");
      expect(text).not.toContain("--force");
      // The guard asked the warm embed server; no CLI query, nothing written
      expect(mockQuery).toHaveBeenCalledWith(
        { text: "Deploy checklist", top_k: 5, include_cold: false },
        3000
      );
      expect(mockRunJson).not.toHaveBeenCalled();
    });

    it("duplicate guard lets the write through without a CLI query when the embed server finds nothing", async () => {
      mockQuery.mockResolvedValueOnce(serverResults());
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466e", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
      expect(mockRunJson).toHaveBeenCalledTimes(1);
      expect(mockRunJson).toHaveBeenCalledWith(["write", "Deploy checklist"], expect.any(Object));
    });

    it("duplicate guard falls back to a short CLI query when the embed server fails", async () => {
      mockQuery.mockRejectedValueOnce(new Error("server down"));
      mockRunJson.mockResolvedValueOnce({ results: [queryHit(60 * 60 * 1000)] });

      const result = await api.tools["memory_write"].def.execute("call-466f", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Similar entry already exists");
      expect(mockRunJson).toHaveBeenCalledTimes(1);
      expect(mockRunJson).toHaveBeenCalledWith(
        ["query", "Deploy checklist", "--limit", "5"],
        expect.objectContaining({ timeoutMs: 2000 })
      );
    });

    it("duplicate guard queries with title, tags and content, as palaia indexes entries", async () => {
      mockQuery.mockResolvedValueOnce(serverResults());
      mockRunJson.mockResolvedValueOnce(written);

      await api.tools["memory_write"].def.execute("call-466j", {
        content: "Run migrations, then restart workers",
        title: "Deploy checklist",
        tags: ["deploy", "ops"],
      });

      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ text: "Deploy checklist deploy ops Run migrations, then restart workers" }),
        3000
      );
    });

    it("duplicate guard lets the write through when every search path fails", async () => {
      mockQuery.mockRejectedValueOnce(new Error("server down"));
      mockRunJson.mockRejectedValueOnce(new Error("palaia command timed out after 2000ms"));
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466g", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
    });

    it("duplicate guard ignores a recent hit at or below the similarity threshold", async () => {
      // Hybrid score 0.934 would have passed the old `score > 0.8` check
      mockQuery.mockResolvedValueOnce(serverResults(queryHit(60 * 60 * 1000, { embedScore: 0.89 })));
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466h", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
    });

    it("duplicate guard never blocks on BM25-only results, whose top hit always scores 1.0", async () => {
      // BM25 scores are normalized to the best hit: an unrelated entry sharing
      // one word ranks first with score 1.0. Without embeddings there is no
      // absolute similarity, so the guard must not fire.
      mockQuery.mockResolvedValueOnce(serverResults(queryHit(60 * 60 * 1000, { embedScore: 0 })));
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466i", {
        content: "Quarterly finance report checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
    });

    it("duplicate guard ignores a similar entry older than 24h", async () => {
      mockQuery.mockResolvedValueOnce(serverResults(queryHit(25 * 60 * 60 * 1000)));
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466c", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
    });

    it("duplicate guard lets the write through when the hit has no created timestamp", async () => {
      // palaia versions before #466 did not include `created` in query results
      mockQuery.mockResolvedValueOnce(serverResults(queryHit(null)));
      mockRunJson.mockResolvedValueOnce(written);

      const result = await api.tools["memory_write"].def.execute("call-466d", {
        content: "Deploy checklist",
      });

      expect(result.content[0].text).toContain("Memory written: new-1");
    });

    it("force: true skips the duplicate guard", async () => {
      mockRunJson.mockResolvedValueOnce({
        id: "forced-1",
        tier: "hot",
        scope: "team",
        deduplicated: false,
      });

      await api.tools["memory_write"].def.execute("call-466b", {
        content: "Deploy checklist",
        force: true,
      });

      expect(mockQuery).not.toHaveBeenCalled();
      expect(mockRunJson).toHaveBeenCalledTimes(1);
      expect(mockRunJson).toHaveBeenCalledWith(
        ["write", "Deploy checklist"],
        expect.any(Object)
      );
    });
  });

  describe("memory_search type filter (Issue #82)", () => {
    it("passes type filter to embed server", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      await api.tools["memory_search"].def.execute("call-type-1", {
        query: "tasks",
        type: "task",
      });

      expect(mockQuery).toHaveBeenCalledWith(
        expect.objectContaining({ type: "task" }),
        expect.any(Number)
      );
    });

    it("omits type when not set", async () => {
      mockQuery.mockResolvedValueOnce({ result: { results: [] } });

      await api.tools["memory_search"].def.execute("call-type-2", {
        query: "anything",
      });

      const queryParams = mockQuery.mock.calls[0][0];
      expect(queryParams).not.toHaveProperty("type");
    });

    it("passes --type to CLI fallback", async () => {
      mockQuery.mockRejectedValueOnce(new Error("server down"));
      mockRunJson.mockResolvedValueOnce({ results: [] });

      await api.tools["memory_search"].def.execute("call-type-3", {
        query: "tasks",
        type: "task",
      });

      expect(mockRunJson).toHaveBeenCalledWith(
        expect.arrayContaining(["--type", "task"]),
        expect.any(Object)
      );
    });
  });
});
