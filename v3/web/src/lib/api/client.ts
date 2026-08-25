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
  /** SPEC-401: whether this hub's admin surface requires a session at all
   * (mandatory when the dashboard is public, off on a private network). */
  required?: boolean;
  /** Where the one sign-in door is — the password form, or the configured
   * provider's start. `null` when this hub has no sign-in server. */
  sign_in_url?: string | null;
}

/** `GET /api/session` (SPEC-401 deliverable #6) — mirrors the route in
 * `palaia_hub.app`. */
export interface SessionState {
  signed_in: boolean;
  username: string | null;
  required: boolean;
  sign_in_url: string;
  session_ttl_seconds: number;
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

/** SPEC-402/403/405's session directory and messenger — opt-in on the hub
 * (present only when `directory_service`/`messenger_service` are given to
 * `create_app`), hand-written for the same reason the token/hook/
 * automation types above are: the generator runs `create_app(HubConfig())`
 * with neither wired, so the schema never sees these routes. Mirrors
 * `palaia_hub.directory.models`/`palaia_hub.messenger.models`. */
export type SessionStatus = "active" | "idle" | "stale";

export interface SessionRecord {
  handle: string;
  scope: string;
  host: string;
  platform: string;
  agent_kind: string;
  model: string;
  status: SessionStatus;
  capabilities: string[];
  registered_at: number;
  last_seen_at: number;
  ttl_seconds: number;
}

export interface SessionListResult {
  sessions: SessionRecord[];
}

export interface DeregisterResult {
  handle: string;
  deregistered: boolean;
}

export type MessageType = "request" | "inform" | "question" | "handoff" | "broadcast";
export type Urgency = "low" | "normal" | "high";
export type DeliveryState = "pending" | "delivered" | "acked";

/** An envelope with its body withheld, plus delivery state — the shape
 * every messenger listing route returns (`palaia_hub.messenger.models.
 * EnvelopeMetadata`). `from` is a reserved-looking name in the wire shape
 * (mirroring the Python model's own `from_`/`from` split) but a perfectly
 * ordinary TypeScript property key. */
export interface EnvelopeMetadata {
  id: string;
  type: MessageType;
  from: string;
  to: string;
  recipient: string;
  subject: string;
  urgency: Urgency;
  expects_reply: boolean;
  refs: string[];
  reply_to: string | null;
  created_at: number;
  expires_at: number;
  state: DeliveryState;
  body_bytes: number;
}

export interface MessageFlowsResult {
  flows: EnvelopeMetadata[];
}

export interface ThreadMetadataResult {
  root_id: string;
  flows: EnvelopeMetadata[];
}

/** The envelope shape a send actually returns (with a body, unlike the
 * metadata-only listing shapes above) — mirrors
 * `palaia_hub.messenger.models.Envelope`. */
export interface Envelope {
  id: string;
  type: MessageType;
  from: string;
  to: string;
  subject: string;
  urgency: Urgency;
  expects_reply: boolean;
  body: string;
  refs: string[];
  reply_to: string | null;
  created_at: number;
  expires_at: number;
}

export interface SendResult {
  envelopes: Envelope[];
  recipients: string[];
  broadcast_query: string | null;
}

export interface EndConversationResult {
  root_id: string;
  expired: EnvelopeMetadata[];
}

/** One envelope copy **with** its body — the owner's read (mirrors
 * `palaia_hub.messenger.models.InboxItem`/`EnvelopeDetailResult`). The one
 * shape the Agents screen fetches on expanding a message row (deliverable
 * #1: "metadata first, body on expand — owner-only surface"). */
export interface InboxItem {
  envelope: Envelope;
  recipient: string;
  state: DeliveryState;
  delivered_at: number | null;
  acked_at: number | null;
}

export interface EnvelopeDetailResult {
  item: InboxItem;
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

/**
 * SPEC-401 deliverable #3: the hub requires this header on every
 * state-changing call under `/api/*`, carrying the value of the cookie its
 * sign-in flow set (a double-submit pair — see
 * `palaia_hub.admin_session`). Read fresh per request rather than cached at
 * module load: signing in replaces the cookie, and a value cached from
 * before that would be stale for the rest of the page's life.
 */
const CSRF_COOKIE = "palaia_oauth_csrf";
const CSRF_HEADER = "X-Palaia-CSRF";

/** Methods the hub lets through with no token, because they change nothing. */
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function readCookie(name: string): string {
  // `document.cookie` is a single "a=1; b=2" string; the session cookie
  // itself is HttpOnly and deliberately invisible here.
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return "";
}

/** One redirect per page life, however many calls fail at once. */
let signInRedirectStarted = false;

/** Test seam: forget that a redirect already happened. */
export function resetSignInRedirect(): void {
  signInRedirectStarted = false;
}

/**
 * Send the browser to the hub's one sign-in door, and come back here.
 *
 * `signInUrl` comes from the hub's own 401 body, so the password form and
 * the identity-provider start are handled by the same code path (the hub
 * decides which one exists). The screen the operator was on travels along as
 * `next`, which is why a session expiring mid-use costs one redirect and
 * not their place in the app.
 */
function redirectToSignIn(signInUrl: string): void {
  if (signInRedirectStarted) return;
  signInRedirectStarted = true;
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.assign(`${signInUrl}?next=${encodeURIComponent(next)}`);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  /** Set false for a call with no response body to parse (a 204 DELETE). */
  expectJson?: boolean;
}

function signInUrlFrom(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const candidate = (body as { sign_in_url?: unknown }).sign_in_url;
  return typeof candidate === "string" && candidate ? candidate : null;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE_METHODS.has(method)) {
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    ...(options.body === undefined
      ? {}
      : { body: JSON.stringify(options.body) }),
  });
  if (!response.ok) {
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = "";
    }
    if (response.status === 401) {
      const signInUrl = signInUrlFrom(body);
      if (signInUrl) redirectToSignIn(signInUrl);
    }
    throw new ApiError(path, response.status, body);
  }
  if (options.expectJson === false) return undefined as T;
  return (await response.json()) as T;
}

function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body });
}

function patchJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PATCH", body });
}

function putJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body });
}

function deleteRequest(path: string): Promise<void> {
  return request<void>(path, { method: "DELETE", expectJson: false });
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

  // ---- SPEC-401: the admin session ----
  /** Who is signed in on this browser, and whether this hub requires it.
   *
   * A hub whose gate is off answers 200 with `signed_in: false`, so a 401
   * here means one thing only — this hub requires a session and this
   * browser has none — and it redirects like any other call. That is what
   * makes the shell bounce straight to the sign-in page even on a screen
   * whose own data happens to come from a sign-in-free endpoint. */
  session: () => request<SessionState>("/api/session"),
  /** End the session and drop its cookies. Not under `/api/*`: signing out
   * is part of the sign-in flow itself, which lives at `/oauth/logout`. */
  signOut: () =>
    fetch(`${API_BASE}/oauth/logout`, {
      method: "POST",
      headers: { Accept: "application/json" },
    }).then((response) => {
      if (!response.ok)
        throw new ApiError("/oauth/logout", response.status, undefined);
    }),
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
    deleteRequest(`/api/gateway/profiles/${profilePath}`),
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
    deleteRequest(`/api/auth/tokens/${tokenId}`),

  // ---- SPEC-201's webhook surface ----
  listHooks: () => getJson<HookInfo[]>("/api/hooks"),
  createHook: (body: { url: string; events?: string[] }) =>
    postJson<CreatedHook>("/api/hooks", body),
  setHookEnabled: (hookId: string, enabled: boolean) =>
    patchJson<HookInfo>(`/api/hooks/${hookId}`, { enabled }),
  deleteHook: (hookId: string) => deleteRequest(`/api/hooks/${hookId}`),
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
    deleteRequest(`/api/automations/${automationId}`),
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
    deleteRequest(`/api/market/installed/${upstreamKey}`),

  // ---- SPEC-402/405: the session directory ----
  listSessions: (params: { status?: SessionStatus; platform?: string } = {}) =>
    getJson<SessionListResult>(`/api/directory/${queryString(params)}`),
  querySessions: (scopeContains: string) =>
    getJson<SessionListResult>(
      `/api/directory/query${queryString({ scope_contains: scopeContains })}`,
    ),
  /** Owner control (SPEC-405 deliverable #2): deregister a session with no
   * secret. Idempotent — an already-gone handle answers
   * `deregistered: false`, not an error. */
  deregisterSession: (handle: string) =>
    postJson<DeregisterResult>(`/api/directory/${handle}/deregister`, {}),

  // ---- SPEC-403/405: the messenger ----
  messageFlows: (
    params: { handle?: string; type?: MessageType; state?: DeliveryState; limit?: number } = {},
  ) => getJson<MessageFlowsResult>(`/api/messenger/${queryString(params)}`),
  messageThread: (envelopeId: string) =>
    getJson<ThreadMetadataResult>(`/api/messenger/threads/${envelopeId}`),
  /** The owner's body-bearing read (deliverable #1: "body on expand") —
   * the one route on this mirror that ever returns a body. */
  envelopeDetail: (envelopeId: string) =>
    getJson<EnvelopeDetailResult>(`/api/messenger/envelopes/${envelopeId}`),
  /** Owner control (SPEC-405 deliverable #2): compose and send as the
   * owner. No handle/secret in the body — the owner has neither; the
   * signed-in session and its CSRF token are the proof of identity. */
  sendAsOwner: (body: {
    type?: MessageType;
    to: string;
    subject: string;
    body?: string;
    urgency?: Urgency;
    expects_reply?: boolean;
    refs?: string[];
    reply_to?: string | null;
    ttl_seconds?: number | null;
  }) => postJson<SendResult>("/api/messenger/send", body),
  /** Owner control (SPEC-405 deliverable #2): end a conversation — expires
   * the thread's still-undelivered envelopes. */
  endConversation: (envelopeId: string) =>
    postJson<EndConversationResult>(`/api/messenger/threads/${envelopeId}/end`, {}),
};
