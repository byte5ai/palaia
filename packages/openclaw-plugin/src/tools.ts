/**
 * Agent tools: memory_search, memory_get, memory_write.
 *
 * These tools are the core of the palaia OpenClaw integration.
 * They shell out to the palaia CLI with --json and return results
 * in the format OpenClaw agents expect.
 */

import { Type } from "@sinclair/typebox";
import { run, runJson, getEmbedServerManager, type RunnerOpts } from "./runner.js";
import type { PalaiaPluginConfig } from "./config.js";
import { sanitizeScope, isValidScope } from "./hooks/index.js";
import { loadPriorities, resolvePriorities } from "./priorities.js";
import type { OpenClawPluginApi } from "./types.js";

/** Shape returned by `palaia query --json` */
interface QueryResult {
  results: Array<{
    id: string;
    content?: string;
    body?: string;
    score: number;
    tier: string;
    scope: string;
    title?: string;
    tags?: string[];
    path?: string;
    decay_score?: number;
    /** Raw embedding cosine similarity to the query; 0 without embeddings */
    embed_score?: number;
    /** ISO-8601 creation timestamp (absent from palaia CLIs before #466) */
    created?: string;
  }>;
}

/** Shape returned by `palaia get --json` */
interface GetResult {
  id: string;
  content: string;
  meta: {
    scope: string;
    tier: string;
    title?: string;
    tags?: string[];
    [key: string]: unknown;
  };
}

/** Shape returned by `palaia write --json` */
interface WriteResult {
  id: string;
  tier: string;
  scope: string;
  deduplicated: boolean;
}

/**
 * Build RunnerOpts from plugin config.
 */
function buildRunnerOpts(config: PalaiaPluginConfig): RunnerOpts {
  return {
    binaryPath: config.binaryPath,
    workspace: config.workspace,
    timeoutMs: config.timeoutMs,
  };
}

/**
 * memory_search's CLI-fallback budget; it includes process spawn overhead.
 * Quoted in docs/openclaw-active-memory.md (checked by docs-active-memory.test.ts).
 */
const SEARCH_CLI_TIMEOUT_MS = 15000;

/**
 * Search palaia: embed server first, CLI fallback.
 *
 * The embed server keeps the model loaded, and its queue does not count wait
 * time against the timeout. The CLI fallback spawns a fresh process (which
 * may itself wait for an embed server to start), so each caller picks the
 * budget it can afford via `cliTimeoutMs`.
 */
async function searchEntries(
  query: { text: string; limit: number; includeCold: boolean; type?: string },
  config: PalaiaPluginConfig,
  opts: RunnerOpts,
  cliTimeoutMs: number,
): Promise<QueryResult> {
  if (config.embeddingServer) {
    try {
      const mgr = getEmbedServerManager(opts);
      const resp = await mgr.query({
        text: query.text,
        top_k: query.limit,
        include_cold: query.includeCold,
        ...(query.type ? { type: query.type } : {}),
      }, config.timeoutMs || 3000);
      if (resp?.result?.results && Array.isArray(resp.result.results)) {
        return { results: resp.result.results };
      }
    } catch {
      // Fall through to CLI
    }
  }

  const args: string[] = ["query", query.text, "--limit", String(query.limit)];
  if (query.includeCold) {
    args.push("--all");
  }
  if (query.type) {
    args.push("--type", query.type);
  }
  return runJson<QueryResult>(args, { ...opts, timeoutMs: cliTimeoutMs });
}

// memory_write's duplicate guard blocks on a hit whose embedding similarity
// exceeds DUPLICATE_MIN_SIMILARITY and that was created within
// DUPLICATE_WINDOW_MS. It cannot use the ranking `score`: palaia normalizes
// BM25 to the best hit, so with BM25-only search the top hit always scores
// 1.0, however unrelated it is. `embed_score` is the raw cosine similarity.
// Calibrated through a real embed server with the default fastembed model
// (bge-small-en-v1.5), querying with duplicateQueryText(): near-duplicates
// (reworded, or one step added) 0.90-0.97 — at least 0.95 when they share
// the title — paraphrases 0.84-0.88, same topic but different content
// 0.75-0.83. 0.89 splits near-duplicates from paraphrases.
const DUPLICATE_MIN_SIMILARITY = 0.89;
const DUPLICATE_WINDOW_MS = 24 * 60 * 60 * 1000;
// Short CLI-fallback budget, so the guard never stalls a write
const DUPLICATE_CLI_TIMEOUT_MS = 2000;

/**
 * The text to compare a new entry by: palaia indexes and embeds each entry
 * as "title tags body" (palaia/search.py, build_index), so the query must be
 * built the same way. Querying with the body alone scores a titled
 * near-duplicate 0.85-0.87 — below the threshold — instead of 0.95+.
 */
function duplicateQueryText(entry: { content: string; title?: string; tags?: string[] }): string {
  return [entry.title, ...(entry.tags ?? []), entry.content].filter(Boolean).join(" ");
}

/**
 * Find a near-duplicate entry created in the last 24 hours, or null.
 *
 * Needs embeddings: hits without an embedding similarity (BM25-only search,
 * or an embed server still warming up) never block. Best-effort: if the
 * search fails or times out, the write proceeds.
 */
async function findRecentDuplicate(
  text: string,
  config: PalaiaPluginConfig,
  opts: RunnerOpts,
): Promise<{ entry: QueryResult["results"][number]; similarity: number; created: Date } | null> {
  let result: QueryResult;
  try {
    result = await searchEntries(
      { text, limit: 5, includeCold: false },
      config,
      opts,
      DUPLICATE_CLI_TIMEOUT_MS,
    );
  } catch {
    return null;
  }
  if (!Array.isArray(result?.results)) return null;

  const now = Date.now();
  for (const r of result.results) {
    const similarity = r.embed_score ?? 0;
    if (similarity > DUPLICATE_MIN_SIMILARITY && r.created) {
      const created = new Date(r.created);
      if (!isNaN(created.getTime()) && now - created.getTime() < DUPLICATE_WINDOW_MS) {
        return { entry: r, similarity, created };
      }
    }
  }
  return null;
}

/**
 * Register all palaia agent tools on the given plugin API.
 */
export function registerTools(api: OpenClawPluginApi, config: PalaiaPluginConfig): void {
  const opts = buildRunnerOpts(config);

  // ── memory_search ──────────────────────────────────────────────
  api.registerTool({
    name: "memory_search",
    description:
      "Search palaia memory for entries relevant to a query (semantic + keyword ranking; keyword-only when no embedding provider is available). Returns matching entries as text, each with its source path, score and tier, filtered to the scopes this agent may see. Use memory_get with a returned path to read one entry.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
      maxResults: Type.Optional(
        Type.Number({
          description:
            "Maximum results. Defaults to the plugin's maxResults setting (10 unless configured).",
        })
      ),
      tier: Type.Optional(
        Type.String({
          description:
            "Pass \"all\" to include cold (archived) entries; any other value searches hot and warm (unless the plugin's tier setting is \"all\").",
        })
      ),
      type: Type.Optional(
        Type.String({
          description: "Filter by entry type: memory|process|task",
        })
      ),
    }),
    async execute(
      _id: string,
      params: {
        query: string;
        maxResults?: number;
        tier?: string;
        type?: string;
      }
    ) {
      // Load scope visibility from priorities (Issue #145: agent isolation)
      let scopeVisibility: string[] | null = null;
      try {
        const prio = await loadPriorities(config.workspace || "");
        const agentId = process.env.PALAIA_AGENT || undefined;
        const resolvedPrio = resolvePriorities(prio, {
          recallTypeWeight: config.recallTypeWeight,
          recallMinScore: config.recallMinScore,
          maxInjectedChars: config.maxInjectedChars,
          tier: config.tier,
        }, agentId);
        scopeVisibility = resolvedPrio.scopeVisibility;
      } catch {
        // Non-fatal: proceed without scope filtering
      }

      const limit = params.maxResults || config.maxResults || 5;
      const includeCold = params.tier === "all" || config.tier === "all";

      const result = await searchEntries(
        { text: params.query, limit, includeCold, type: params.type },
        config,
        opts,
        SEARCH_CLI_TIMEOUT_MS,
      );

      // Apply scope visibility filter (Issue #145: agent isolation)
      let filteredResults = result.results || [];
      if (scopeVisibility) {
        filteredResults = filteredResults.filter((r) => {
          const scope = r.scope || "team";
          // Legacy shared:X entries are treated as team
          const effectiveScope = scope.startsWith("shared:") ? "team" : scope;
          return scopeVisibility!.includes(effectiveScope);
        });
      }

      // Format as memory_search compatible output
      const snippets = filteredResults.map((r) => {
        const body = r.content || r.body || "";
        const path = r.path || `${r.tier}/${r.id}.md`;
        return {
          text: body,
          path,
          score: r.score,
          tier: r.tier,
          scope: r.scope,
        };
      });

      // Build text output compatible with memory-core format
      const textParts = snippets.map(
        (s) =>
          `${s.text}\n— Source: ${s.path} (score: ${s.score}, tier: ${s.tier})`
      );
      const text =
        textParts.length > 0
          ? textParts.join("\n\n")
          : "No results found.";

      return {
        content: [{ type: "text" as const, text }],
      };
    },
  });

  // ── memory_get ─────────────────────────────────────────────────
  api.registerTool({
    name: "memory_get",
    description: "Read a specific palaia memory entry by path or id.",
    parameters: Type.Object({
      path: Type.String({ description: "Memory path or UUID" }),
      from: Type.Optional(
        Type.Number({ description: "Start from line number (1-indexed)" })
      ),
      lines: Type.Optional(
        Type.Number({ description: "Number of lines to return" })
      ),
    }),
    async execute(
      _id: string,
      params: { path: string; from?: number; lines?: number }
    ) {
      const args: string[] = ["get", params.path];
      if (params.from != null) {
        args.push("--from", String(params.from));
      }
      if (params.lines != null) {
        args.push("--lines", String(params.lines));
      }

      const result = await runJson<GetResult>(args, opts);

      return {
        content: [
          {
            type: "text" as const,
            text: result.content,
          },
        ],
      };
    },
  });

  // ── memory_write (optional, opt-in) ───────────────────────────
  api.registerTool(
    {
      name: "memory_write",
      description:
        "Write a new entry to palaia (WAL-backed, crash-safe). Intended for processes/SOPs and tasks; conversation knowledge is captured automatically. Unless force is true, a near-duplicate entry created in the last 24 hours blocks the write and is reported instead; update that entry, or retry with force: true. Near-duplicates are detected by embedding similarity, so without an embedding provider the check is skipped.",
      parameters: Type.Object({
        content: Type.String({ description: "Memory content to write" }),
        scope: Type.Optional(
          Type.String({
            description: "Scope: private|team|public (default: team)",
            default: "team",
          })
        ),
        tags: Type.Optional(
          Type.Array(Type.String(), {
            description: "Tags for categorization",
          })
        ),
        type: Type.Optional(
          Type.String({
            description: "Entry type: memory|process|task (default: memory)",
          })
        ),
        project: Type.Optional(
          Type.String({
            description: "Project name to associate this entry with",
          })
        ),
        title: Type.Optional(
          Type.String({
            description: "Title for the entry",
          })
        ),
        force: Type.Optional(
          Type.Boolean({
            description: "Skip duplicate check and write anyway",
            default: false,
          })
        ),
      }),
      async execute(
        _id: string,
        params: {
          content: string;
          scope?: string;
          tags?: string[];
          type?: string;
          project?: string;
          title?: string;
          force?: boolean;
        }
      ) {
        // Duplicate guard: check for similar recent entries before writing
        if (!params.force) {
          const dup = await findRecentDuplicate(duplicateQueryText(params), config, opts);
          if (dup) {
            const { entry: r, similarity, created } = dup;
            const title = r.title || (r.content || r.body || "").slice(0, 60);
            const dateStr = created.toISOString().split("T")[0];
            return {
              content: [
                {
                  type: "text" as const,
                  text: `Similar entry already exists (similarity: ${similarity.toFixed(2)}, created: ${dateStr}): '${title}'. Use palaia edit ${r.id} to update, or call again with force: true to write anyway.`,
                },
              ],
            };
          }
        }

        const args: string[] = ["write", params.content];
        if (params.scope) {
          if (!isValidScope(params.scope)) {
            return {
              content: [
                {
                  type: "text" as const,
                  text: `Invalid scope "${params.scope}". Valid scopes: private, team, public`,
                },
              ],
            };
          }
          args.push("--scope", sanitizeScope(params.scope));
        }
        if (params.tags && params.tags.length > 0) {
          args.push("--tags", params.tags.join(","));
        }
        if (params.type) {
          args.push("--type", params.type);
        }
        if (params.project) {
          args.push("--project", params.project);
        }
        if (params.title) {
          args.push("--title", params.title);
        }

        const result = await runJson<WriteResult>(args, opts);

        return {
          content: [
            {
              type: "text" as const,
              text: `Memory written: ${result.id} (tier: ${result.tier}, scope: ${result.scope})`,
            },
          ],
        };
      },
    },
    { optional: true }
  );
}
