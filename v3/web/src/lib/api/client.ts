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

import type { components, paths } from "./schema.gen";

export type HealthResponse =
  paths["/api/health"]["get"]["responses"][200]["content"]["application/json"];
export type InfoResponse =
  paths["/api/info"]["get"]["responses"][200]["content"]["application/json"];

/** SPEC-205's exposure-wizard surface — generated (unlike the wizard/
 * explorer types below), since `/api/mode` and `/api/exposure` are mounted
 * unconditionally, same as `/api/health`/`/api/info`. */
export type ModeStatus =
  paths["/api/mode"]["get"]["responses"][200]["content"]["application/json"];
export type ModeChangeRequest =
  paths["/api/mode"]["post"]["requestBody"]["content"]["application/json"];
export type ExposureStatus =
  paths["/api/exposure"]["get"]["responses"][200]["content"]["application/json"];
export type ChecklistItem = components["schemas"]["ChecklistItemOut"];
export type TunnelGuidance =
  paths["/api/exposure/tunnel"]["post"]["responses"][200]["content"]["application/json"];
export type SelfTestResult =
  paths["/api/exposure/selftest"]["post"]["responses"][200]["content"]["application/json"];

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

/** SPEC-305's profile editor — opt-in on the hub (present only when a
 * `DynamicGateway` is attached to `create_app`, same reasoning as the
 * types above for why this is hand-written rather than generated). Mirrors
 * `palaia_hub.gateway.api.GatewayProfileOut`. */
export interface GatewayProfile {
  path: string;
  label: string | null;
  vaults: string[];
  stash: boolean;
  hidden_tools: string[];
  semantic_routing: boolean;
  tool_count: number;
  /** External servers (SPEC-302) this profile mounts, by key. */
  upstreams: string[];
  managed: boolean;
}

/** SPEC-302's external-server registry, as the profile editor reads it to
 * offer upstream-server checkboxes (SPEC-304 follow-up) — mirrors
 * `palaia_hub.upstream.api.UpstreamOut`. */
export interface GatewayUpstream {
  key: string;
  kind: "http" | "stdio";
  display_name: string;
  namespace: string;
  enabled: boolean;
  target: string;
  profiles: string[];
  up: boolean;
  status: string;
  checked_at: number | null;
  tools: string[];
  secret_names: string[];
  tool_renames: Record<string, string>;
}

/** `palaia_hub.gateway.api.GatewayToolOut`. */
export interface GatewayTool {
  name: string;
  description: string | null;
  hidden: boolean;
}

/** `palaia_hub.gateway.api.RenameSanitizationOut`. */
export interface RenameSanitization {
  action: string;
  requested: string;
  applied: string;
}

/** `palaia_hub.gateway.api.GatewayVaultOut`. */
export interface GatewayVaultIdentity {
  key: string;
  name: string;
  purpose: string;
  tool_renames: Record<string, string>;
  namespace: string;
  sanitized: RenameSanitization[];
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

/** SPEC-307's automations editor — opt-in on the hub (present only when an
 * `automation_store` is given to `create_app`), hand-written for the same
 * reason the hooks/token types above are. */
export type ConditionOp = "equals" | "contains" | "prefix";

export interface ConditionClause {
  field: string;
  op: ConditionOp;
  value: string;
}

export interface MemoryWriteAction {
  kind: "memory_write";
  vault: string;
  what_it_concerns_template: string;
  why_keep_template: string;
  content_template: string;
  source_template?: string | null;
}

export interface StashSetAction {
  kind: "stash_set";
  namespace: string;
  key_template: string;
  value_template: string;
}

export interface NotificationAction {
  kind: "notification";
  title_template: string;
  body_template?: string;
}

export type AutomationAction =
  | MemoryWriteAction
  | StashSetAction
  | NotificationAction;

export interface AutomationInfo {
  id: string;
  name: string;
  trigger_event: string;
  condition: ConditionClause[];
  action: AutomationAction;
  enabled: boolean;
  created_at: string;
}

export type DeliveryStatus =
  | "pending"
  | "delivered"
  | "dead"
  | "condition_not_matched";

export interface DeliveryLogEntry {
  id: number;
  automation_id: string;
  event_id: string;
  event_name: string;
  status: DeliveryStatus;
  attempts: number;
  last_error: string;
  created_at: string;
  test: boolean;
}

/** SPEC-307's notification center — opt-in on the hub. */
export interface NotificationRecord {
  id: number;
  title: string;
  body: string;
  source: string;
  created_at: string;
  read: boolean;
}

/** SPEC-303/304's marketplace — opt-in on the hub (present only when a
 * `market_service` is given to `create_app`), hand-written for the same
 * reason the other opt-in surfaces above are. Mirrors
 * `palaia_hub.market.models.MarketEntry`. */
export type MarketEntryKind = "remote" | "container" | "mcpb" | "skill" | "plugin";
export type MarketProvenance = "registry" | "curated" | "manual";
export type MarketSourceType = "registry_ref" | "image" | "url";

export interface MarketSourceLocator {
  type: MarketSourceType;
  value: string;
}

/** A `config_schema` property (SPEC-304 deliverable #2's fixed subset).
 * `type: "secret"` is palaia's own extension, not a JSON Schema primitive
 * — the one signal the form renderer needs to route a value to the
 * secret store instead of a plain field. `format: "path"` on a string
 * marks a declared container mount. */
export interface MarketConfigProperty {
  type?: "string" | "number" | "boolean" | "secret";
  title?: string;
  enum?: string[];
  format?: string;
}

export interface MarketConfigSchema {
  type?: "object";
  properties?: Record<string, MarketConfigProperty>;
  required?: string[];
}

export interface MarketEntry {
  id: string;
  name: string;
  one_liner: string;
  kind: MarketEntryKind;
  source: MarketSourceLocator;
  config_schema: MarketConfigSchema | null;
  permissions: string[];
  maintainer: string;
  verified: boolean;
  provenance: MarketProvenance;
}

export interface MarketSearchResult {
  entries: MarketEntry[];
  stale: boolean;
  notes: Record<string, string>;
}

export interface ConsentToken {
  token: string;
  expires_at: number;
}

export interface InstalledAddon {
  upstream_key: string;
  entry_id: string;
  name: string;
  kind: MarketEntryKind;
  provenance: MarketProvenance;
  installed_ref: string;
  current_ref: string | null;
  update_available: boolean;
  up: boolean;
  status: string;
  profiles: string[];
  installed_at: number;
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

async function putJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
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

function queryString(
  params: Record<string, string | number | undefined>,
): string {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== "",
  );
  if (entries.length === 0) return "";
  const search = new URLSearchParams(
    entries.map(([key, value]) => [key, String(value)]),
  );
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
  createVault: (body: {
    key: string;
    purpose?: string;
    path?: string;
    template?: boolean;
  }) => postJson<VaultSummary>("/api/vaults", body),
  listNotes: (vaultKey: string, folder = "") =>
    getJson<NoteSummary[]>(
      `/api/vaults/${vaultKey}/notes${queryString({ folder })}`,
    ),
  readNote: (vaultKey: string, permalink: string) =>
    getJson<NoteRecord>(`/api/vaults/${vaultKey}/notes/${permalink}`),
  noteHistory: (vaultKey: string, permalink: string) =>
    getJson<CommitSummary[]>(
      `/api/vaults/${vaultKey}/notes/${permalink}/history`,
    ),
  noteGraph: (vaultKey: string, permalink: string) =>
    getJson<LocalGraph>(`/api/vaults/${vaultKey}/notes/${permalink}/graph`),
  search: (vaultKey: string, q: string) =>
    getJson<SearchHit[]>(`/api/vaults/${vaultKey}/search${queryString({ q })}`),
  inboxStatus: (vaultKey: string) =>
    getJson<InboxStatus>(`/api/vaults/${vaultKey}/inbox_status`),
  indexStatus: (vaultKey: string) =>
    getJson<IndexStatus>(`/api/vaults/${vaultKey}/index_status`),

  // ---- SPEC-305: the tool-profile editor ----
  listGatewayProfiles: () => getJson<GatewayProfile[]>("/api/gateway/profiles"),
  listGatewayProfileTools: (profilePath: string) =>
    getJson<GatewayTool[]>(`/api/gateway/profiles/${profilePath}/tools`),
  createGatewayProfile: (body: {
    path: string;
    label?: string | null;
    vaults?: string[];
    stash?: boolean;
    hidden_tools?: string[];
    semantic_routing?: boolean;
    upstreams?: string[];
  }) => postJson<GatewayProfile>("/api/gateway/profiles", body),
  updateGatewayProfile: (
    profilePath: string,
    body: {
      label?: string | null;
      vaults?: string[];
      stash?: boolean;
      hidden_tools?: string[];
      semantic_routing?: boolean;
      upstreams?: string[];
    },
  ) => patchJson<GatewayProfile>(`/api/gateway/profiles/${profilePath}`, body),
  deleteGatewayProfile: (profilePath: string) =>
    fetch(`${API_BASE}/api/gateway/profiles/${profilePath}`, {
      method: "DELETE",
    }).then((response) => {
      if (!response.ok)
        throw new ApiError("/api/gateway/profiles", response.status, undefined);
    }),
  listGatewayVaults: () => getJson<GatewayVaultIdentity[]>("/api/gateway/vaults"),
  updateGatewayVault: (
    vaultKey: string,
    body: { name?: string; purpose?: string; tool_renames?: Record<string, string> },
  ) => patchJson<GatewayVaultIdentity>(`/api/gateway/vaults/${vaultKey}`, body),
  // SPEC-302's registry, read here so the profile editor (SPEC-304 follow-up)
  // can offer an upstream-server checkbox next to the vault checkboxes.
  listGatewayUpstreams: () => getJson<GatewayUpstream[]>("/api/gateway/upstreams"),

  // ---- SPEC-108's token surface, consumed here for "connected clients" ----
  listTokens: () => getJson<TokenInfo[]>("/api/auth/tokens"),
  createToken: (body: { name: string; profile: string; scopes?: string[] }) =>
    postJson<CreatedToken>("/api/auth/tokens", { scopes: [], ...body }),
  revokeToken: (tokenId: string) =>
    fetch(`${API_BASE}/api/auth/tokens/${tokenId}`, { method: "DELETE" }).then(
      (response) => {
        if (!response.ok)
          throw new ApiError("/api/auth/tokens", response.status, undefined);
      },
    ),

  // ---- SPEC-201's webhook surface ----
  listHooks: () => getJson<HookInfo[]>("/api/hooks"),
  createHook: (body: { url: string; events?: string[] }) =>
    postJson<CreatedHook>("/api/hooks", body),
  setHookEnabled: (hookId: string, enabled: boolean) =>
    patchJson<HookInfo>(`/api/hooks/${hookId}`, { enabled }),
  deleteHook: (hookId: string) =>
    fetch(`${API_BASE}/api/hooks/${hookId}`, { method: "DELETE" }).then(
      (response) => {
        if (!response.ok)
          throw new ApiError("/api/hooks", response.status, undefined);
      },
    ),
  hookDeadLetters: (hookId: string) =>
    getJson<DeadLetter[]>(`/api/hooks/${hookId}/dead_letters`),

  // ---- SPEC-307's automations editor ----
  listAutomations: () => getJson<AutomationInfo[]>("/api/automations"),
  createAutomation: (body: {
    name: string;
    trigger_event: string;
    action: AutomationAction;
    condition?: ConditionClause[];
  }) =>
    postJson<AutomationInfo>("/api/automations", { condition: [], ...body }),
  updateAutomation: (
    automationId: string,
    body: {
      name?: string;
      trigger_event?: string;
      action?: AutomationAction;
      condition?: ConditionClause[];
    },
  ) => putJson<AutomationInfo>(`/api/automations/${automationId}`, body),
  setAutomationEnabled: (automationId: string, enabled: boolean) =>
    patchJson<AutomationInfo>(`/api/automations/${automationId}`, { enabled }),
  deleteAutomation: (automationId: string) =>
    fetch(`${API_BASE}/api/automations/${automationId}`, {
      method: "DELETE",
    }).then((response) => {
      if (!response.ok)
        throw new ApiError("/api/automations", response.status, undefined);
    }),
  automationDeliveries: (automationId: string) =>
    getJson<DeliveryLogEntry[]>(`/api/automations/${automationId}/deliveries`),
  testFireAutomation: (
    automationId: string,
    data: Record<string, unknown> = {},
  ) =>
    postJson<DeliveryLogEntry>(`/api/automations/${automationId}/test_fire`, {
      data,
    }),

  // ---- SPEC-307's notification center ----
  listNotifications: (unreadOnly = false) =>
    getJson<NotificationRecord[]>(
      `/api/notifications${queryString({ unread_only: unreadOnly ? "true" : undefined })}`,
    ),
  unreadNotificationCount: () =>
    getJson<{ count: number }>("/api/notifications/unread_count"),
  markNotificationRead: (notificationId: number) =>
    postJson<NotificationRecord>(
      `/api/notifications/${notificationId}/read`,
      {},
    ),
  markAllNotificationsRead: () =>
    postJson<{ status: string }>("/api/notifications/read_all", {}),

  // ---- SPEC-205: the exposure wizard ----
  mode: () => getJson<ModeStatus>("/api/mode"),
  changeMode: (body: ModeChangeRequest) =>
    postJson<ModeStatus>("/api/mode", body),
  exposure: () => getJson<ExposureStatus>("/api/exposure"),
  tunnelGuidance: (body: {
    kind: "tailscale" | "cloudflared";
    local_port?: number;
    hostname?: string;
  }) => postJson<TunnelGuidance>("/api/exposure/tunnel", body),
  selfTest: (publicUrl: string) =>
    postJson<SelfTestResult>("/api/exposure/selftest", {
      public_url: publicUrl,
    }),

  // ---- SPEC-303/304: the marketplace ----
  searchMarket: (q = "", source?: MarketProvenance) =>
    getJson<MarketSearchResult>(`/api/market/search${queryString({ q, source })}`),
  getMarketEntry: (entryId: string) => getJson<MarketEntry>(`/api/market/entry/${entryId}`),
  createManualMarketEntry: (body: {
    id: string;
    name: string;
    one_liner: string;
    kind: MarketEntryKind;
    source: MarketSourceLocator;
    config_schema?: MarketConfigSchema | null;
    permissions?: string[];
    maintainer: string;
  }) => postJson<MarketEntry>("/api/market/manual", body),
  /** The consent screen's own POST (SPEC-304 deliverable #3) — the token
   * it returns is what `installMarketEntry` below must be given; there is
   * no install path that skips this call. */
  issueMarketConsent: (entryId: string) =>
    postJson<ConsentToken>(`/api/market/entry/${entryId}/consent`, {}),
  installMarketEntry: (
    entryId: string,
    body: {
      consent_token: string;
      config?: Record<string, string | number | boolean>;
      profiles?: string[];
      display_name?: string | null;
    },
  ) => postJson<InstalledAddon>(`/api/market/entry/${entryId}/install`, body),
  listInstalledAddons: () => getJson<InstalledAddon[]>("/api/market/installed"),
  updateInstalledAddon: (upstreamKey: string) =>
    postJson<InstalledAddon>(`/api/market/installed/${upstreamKey}/update`, {}),
  uninstallAddon: (upstreamKey: string) =>
    fetch(`${API_BASE}/api/market/installed/${upstreamKey}`, { method: "DELETE" }).then(
      (response) => {
        if (!response.ok)
          throw new ApiError("/api/market/installed", response.status, undefined);
      },
    ),
};
