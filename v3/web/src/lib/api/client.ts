/**
 * Typed API client (SPEC-109), generated against the hub's own OpenAPI
 * schema — see `schema.gen.ts` (produced by `npm run gen:api`, which runs
 * `scripts/generate-openapi-schema.py` against `palaia_hub.app.create_app`
 * and then `openapi-typescript`; both files are committed so a plain
 * `npm ci && npm run build` never needs Python or a running hub).
 *
 * Every REST call in the dashboard goes through this module rather than a
 * bare `fetch`, so a change to the hub's schema becomes a TypeScript error
 * here instead of a runtime surprise in a component.
 */

import type { paths } from "./schema.gen";

export type HealthResponse =
  paths["/api/health"]["get"]["responses"][200]["content"]["application/json"];
export type InfoResponse =
  paths["/api/info"]["get"]["responses"][200]["content"]["application/json"];

/**
 * `/api/info`'s `sign_in` field (SPEC-204 deliverable #4). Hand-written for
 * the same reason as the block below: `create_app(HubConfig())` — what the
 * generator runs — never has an OAuth server attached, so the committed
 * schema types this field as `unknown` rather than this shape.
 */
export interface SignInInfo {
  method: "password" | "idp" | "none";
  provider_name: string | null;
}

/**
 * SPEC-110's dashboard endpoints (wizard vault creation, memory explorer,
 * token last-seen) are opt-in on the hub (see `palaia_hub.dashboard_api` /
 * `palaia_hub.auth.routes`) and so are absent from the committed
 * `schema.gen.ts` snapshot — the same reason `/api/auth/tokens` was never
 * added there either (see this file's header comment: the generator runs
 * `create_app(HubConfig())` with none of the opt-in stores attached). These
 * types are hand-written against the response models in
 * `dashboard_api.py`/`auth/models.py` instead of generated; keep them in
 * sync by hand if those models change.
 */
export interface VaultSummary {
  key: string;
  purpose: string | null;
  path: string;
  writable: boolean;
  note_count: number;
}

export interface NoteSummary {
  permalink: string;
  title: string;
  type: string;
  tags: string[];
  folder: string;
  modified: string;
  status: string;
  capture_id: string;
}

export interface NoteRecord extends NoteSummary {
  body: string;
  created: string;
}

export interface SearchHit {
  permalink: string;
  title: string;
  snippet: string;
  score: number;
}

export interface CommitSummary {
  sha: string;
  subject: string;
  author_name: string;
  committed_at: string;
}

export interface GraphNode {
  permalink: string;
  title: string;
}

export interface LocalGraph {
  outbound: GraphNode[];
  inbound: GraphNode[];
}

export interface InboxStatus {
  count: number;
  oldest_capture_id: string | null;
  oldest_age_seconds: number | null;
  last_capture_id: string | null;
  last_captured_at: string | null;
}

/** SPEC-210 deliverable #3: one vault's index status, as
 * `palaia_hub.dashboard_api.IndexStatusOut` returns it. */
export interface EmbedStatus {
  enabled: boolean;
  available: boolean;
  model: string;
  dim: number;
  total: number;
  ready: number;
  pending: number;
  failed: number;
  reason: string;
}

export interface IndexStatus {
  vault: string;
  schema_version: number;
  notes: number;
  observations: number;
  relations: number;
  unresolved_relations: number;
  embeds: EmbedStatus;
  embed_progress_percent: number;
  embed_summary: string;
}

export interface TokenInfo {
  id: string;
  name: string;
  profile: string;
  scopes: string[];
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface CreatedToken {
  info: TokenInfo;
  /** Shown once — the caller must display it now, it cannot be recovered
   * from the store afterward. */
  token: string;
}

/** SPEC-201's webhook management surface — opt-in on the hub (present only
 * when a `hook_store` is given to `create_app`), same reasoning as the
 * token types above for why this is hand-written rather than generated. */
export interface HookInfo {
  id: string;
  url: string;
  events: string[];
  enabled: boolean;
  created_at: string;
}

export interface CreatedHook {
  info: HookInfo;
  /** Shown once — signs every delivery; cannot be recovered afterward. */
  secret: string;
}

export interface DeadLetter {
  id: number;
  hook_id: string;
  event_id: string;
  event_name: string;
  attempts: number;
  last_error: string;
  created_at: string;
}

/** Base URL for API calls. Empty string = same-origin (the hub serves the
 * dashboard build itself, per this SPEC's static-serving deliverable), so
 * this only needs a value in local dev against a hub on another port. */
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  readonly path: string;
  readonly status: number;
  readonly body: unknown;

  constructor(path: string, status: number, body: unknown) {
    super(`${path} responded ${status}`);
    this.name = "ApiError";
    this.path = path;
    this.status = status;
    this.body = body;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = await response.text();
    }
    throw new ApiError(path, response.status, body);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let responseBody: unknown;
    try {
      responseBody = await response.json();
    } catch {
      responseBody = await response.text();
    }
    throw new ApiError(path, response.status, responseBody);
  }
  return (await response.json()) as T;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let responseBody: unknown;
    try {
      responseBody = await response.json();
    } catch {
      responseBody = await response.text();
    }
    throw new ApiError(path, response.status, responseBody);
  }
  return (await response.json()) as T;
}

function queryString(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== "");
  if (entries.length === 0) return "";
  const search = new URLSearchParams(entries.map(([key, value]) => [key, String(value)]));
  return `?${search.toString()}`;
}

export const api = {
  health: () => getJson<HealthResponse>("/api/health"),
  info: () => getJson<InfoResponse>("/api/info"),
  /** Same-origin URL for the SSE stream — passed straight to `EventSource`
   * by `useEventStream` (./events.ts), never fetched with `fetch`. */
  eventsUrl: () => `${API_BASE}/api/events`,

  // ---- SPEC-110: wizard + memory explorer ----
  listVaults: () => getJson<VaultSummary[]>("/api/vaults"),
  createVault: (body: { key: string; purpose?: string; path?: string; template?: boolean }) =>
    postJson<VaultSummary>("/api/vaults", body),
  listNotes: (vaultKey: string, folder = "") =>
    getJson<NoteSummary[]>(`/api/vaults/${vaultKey}/notes${queryString({ folder })}`),
  readNote: (vaultKey: string, permalink: string) =>
    getJson<NoteRecord>(`/api/vaults/${vaultKey}/notes/${permalink}`),
  noteHistory: (vaultKey: string, permalink: string) =>
    getJson<CommitSummary[]>(`/api/vaults/${vaultKey}/notes/${permalink}/history`),
  noteGraph: (vaultKey: string, permalink: string) =>
    getJson<LocalGraph>(`/api/vaults/${vaultKey}/notes/${permalink}/graph`),
  search: (vaultKey: string, q: string) =>
    getJson<SearchHit[]>(`/api/vaults/${vaultKey}/search${queryString({ q })}`),
  inboxStatus: (vaultKey: string) =>
    getJson<InboxStatus>(`/api/vaults/${vaultKey}/inbox_status`),
  indexStatus: (vaultKey: string) =>
    getJson<IndexStatus>(`/api/vaults/${vaultKey}/index_status`),

  // ---- SPEC-108's token surface, consumed here for "connected clients" ----
  listTokens: () => getJson<TokenInfo[]>("/api/auth/tokens"),
  createToken: (body: { name: string; profile: string; scopes?: string[] }) =>
    postJson<CreatedToken>("/api/auth/tokens", { scopes: [], ...body }),
  revokeToken: (tokenId: string) =>
    fetch(`${API_BASE}/api/auth/tokens/${tokenId}`, { method: "DELETE" }).then((response) => {
      if (!response.ok) throw new ApiError("/api/auth/tokens", response.status, undefined);
    }),

  // ---- SPEC-201's webhook surface ----
  listHooks: () => getJson<HookInfo[]>("/api/hooks"),
  createHook: (body: { url: string; events?: string[] }) =>
    postJson<CreatedHook>("/api/hooks", body),
  setHookEnabled: (hookId: string, enabled: boolean) =>
    patchJson<HookInfo>(`/api/hooks/${hookId}`, { enabled }),
  deleteHook: (hookId: string) =>
    fetch(`${API_BASE}/api/hooks/${hookId}`, { method: "DELETE" }).then((response) => {
      if (!response.ok) throw new ApiError("/api/hooks", response.status, undefined);
    }),
  hookDeadLetters: (hookId: string) =>
    getJson<DeadLetter[]>(`/api/hooks/${hookId}/dead_letters`),
};
