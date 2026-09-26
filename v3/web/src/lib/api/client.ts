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

/** `GET`/`POST /api/auth/owner` (issue 342): whether the one owner account
 * exists. Hand-written like `SignInInfo` — the generator's hub has no
 * sign-in server, so the route is not in the committed schema. */
export interface OwnerAccountState {
  configured: boolean;
}

/**
 * `GET /api/update/check` (SPEC-501). Hand-written for the same reason as
 * `SignInInfo` above: the route returns `dict[str, Any]` (no Pydantic
 * response model — see `palaia_hub.app`'s `update_check` handler), so the
 * generator types it as `{[key: string]: unknown}`.
 */
export interface UpdateGuidance {
  kind: "store" | "command" | "manual";
  message: string;
  commands: string[];
}
export interface UpdateCheckResponse {
  state: "up_to_date" | "update_available" | "cannot_check";
  channel: "edge" | "beta" | "stable";
  current_version: string;
  latest_version: string | null;
  checked_at: number;
  deployment: string;
  reason: string | null;
  guidance: UpdateGuidance;
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

/** One curator maintenance proposal waiting for the owner's decision —
 * mirrors `palaia_hub.gateway.vault_protocol.ProposalSummary`. */
export interface ProposalSummary {
  permalink: string;
  title: string;
  status: string;
  created: string;
  /** The proposal's full markdown: the explanation, the plan, pre-images. */
  body: string;
}

export interface ReviewQueueResult {
  proposals: ProposalSummary[];
  decide_tool: string;
}

export interface ReviewDecideResult {
  permalink: string;
  status: string;
}

export interface InboxStatus {
  count: number;
  oldest_capture_id: string | null;
  oldest_age_seconds: number | null;
  last_capture_id: string | null;
  last_captured_at: string | null;
}

/** SPEC-504 deliverable #3: the local-only first-run funnel's read side.
 * Every `*_at` field is a Unix timestamp (seconds) or `null` until that
 * step happens on this hub — see `palaia_hub.funnel`'s module docstring
 * for why this is never transmitted anywhere beyond this one hub. */
export interface FunnelStatus {
  hub_started_at: number | null;
  vault_created_at: number | null;
  client_connected_at: number | null;
  first_memory_at: number | null;
  time_to_first_memory_seconds: number | null;
  time_to_first_memory_display: string | null;
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
  /** Whether the profile carries the Telegram tools (issue 411). What it
   * may send is the Telegram screen's grants, default-deny. */
  telegram: boolean;
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
export type MarketEntryKind =
  | "remote"
  | "container"
  | "mcpb"
  | "skill"
  | "plugin";
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

/** What installing an entry would actually run or connect to (issue 349) —
 * the consent screen shows it before asking, and the token the hub issues
 * is bound to `plan_hash`: an install whose plan no longer matches is
 * refused with a 409. */
export interface PlanPreview {
  kind: "stdio" | "http" | "container";
  /** `stdio`: the exact executable and its arguments. */
  command: string | null;
  args: string[];
  /** `http`: the address the hub will connect to. */
  url: string | null;
  /** `container`: the image that will be pulled and run. */
  image: string | null;
  plan_hash: string;
}

export interface ConsentToken {
  token: string;
  expires_at: number;
  preview: PlanPreview;
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

export type MessageType =
  | "request"
  | "inform"
  | "question"
  | "handoff"
  | "broadcast";
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

/** Issue 439's Telegram panel and issue 463's editor — hand-written for
 * the same reason as the directory/messenger types above. Mirrors
 * `palaia_hub.telegram.dashboard_api` and the `BotCheck`/`RecentMessage`/
 * `TelegramDestination`/`TelegramGrant` models in
 * `palaia_hub.telegram.models`. No field here can carry a token or a
 * message's text — the hub's models have none. A bot names the secret its
 * token is filed under; the token itself goes to `storeSecret`. */
export type TelegramTransport = "polling" | "webhook";

export interface TelegramPollingState {
  running: boolean;
  last_ok_at: number | null;
  last_error: string | null;
  last_error_at: number | null;
  consecutive_failures: number;
}

export interface TelegramBotCheck {
  ok: boolean;
  username: string | null;
  checked_at: number;
  error: string | null;
}

export interface TelegramBotStatus {
  key: string;
  /** The configured label, or the key when there is none. */
  label: string;
  /** The configured label itself; `null` when there is none. */
  configured_label: string | null;
  transport: TelegramTransport;
  enabled: boolean;
  /** The secret-store name the token is filed under — never the token. */
  token_secret: string;
  /** Webhook bots only: the name of the secret Telegram echoes. */
  webhook_secret: string | null;
  token_stored: boolean;
  /** Webhook bots only; `null` for a polling bot. */
  webhook_secret_stored: boolean | null;
  /** `null` for a webhook bot or a switched-off one. */
  polling: TelegramPollingState | null;
  last_update_at: number | null;
  last_check: TelegramBotCheck | null;
}

export type TelegramDestinationKind = "messenger" | "inbox" | "event";

export type TelegramMessageType =
  | "request"
  | "inform"
  | "question"
  | "handoff"
  | "broadcast";

export type TelegramUrgency = "low" | "normal" | "high";

/** Where a rule sends a message, as configured. */
export interface TelegramDestination {
  kind: TelegramDestinationKind;
  /** `messenger`: the recipient handle or broadcast query. */
  to?: string | null;
  message_type?: TelegramMessageType;
  urgency?: TelegramUrgency;
  /** `inbox`: the vault whose inbox it lands in. */
  vault?: string | null;
  /** `event`: a label carried as `data.label`. */
  label?: string | null;
}

export interface TelegramRoute {
  bot: string;
  /** A numeric chat id, a public `@name`, or `*` for every chat. */
  chat: string;
  kind: TelegramDestinationKind;
  /** `messenger:<to>`, `inbox:<vault>` or `event`. */
  destination: string;
  /** The destination as configured, for the editor. */
  target: TelegramDestination;
}

/** A rule as the editor sends it. */
export interface TelegramRouteInput {
  bot: string;
  chat: string;
  destination: TelegramDestination;
}

/** What one MCP profile may send to. `*` = every one; `[]` = none. */
export interface TelegramGrant {
  profile: string;
  bots: string[];
  chats: string[];
}

export interface TelegramBotInput {
  key: string;
  label?: string | null;
  transport?: TelegramTransport;
  enabled?: boolean;
  token_secret?: string | null;
  webhook_secret?: string | null;
}

export interface TelegramBotPatch {
  label?: string | null;
  transport?: TelegramTransport;
  enabled?: boolean;
  token_secret?: string | null;
  webhook_secret?: string | null;
}

export interface TelegramRecentMessage {
  at: number;
  bot: string;
  chat_id: number;
  chat_type: string;
  chat_username: string | null;
  message_id: number;
  text_chars: number;
  routed: boolean;
  destination: string | null;
  delivered: boolean;
  detail: string;
  /** A dropped message only: the chat keys a rule could have used. */
  candidates: string[] | null;
}

export interface TelegramStatus {
  bots: TelegramBotStatus[];
  routes: TelegramRoute[];
  grants: TelegramGrant[];
  /** Newest first. */
  recent: TelegramRecentMessage[];
  /** Vaults an inbox rule can deliver into right now. */
  vaults: string[];
  /** Whether a messenger rule has a messenger to deliver to. */
  messenger: boolean;
  /** Rules and bots the config accepts but this hub cannot serve. */
  warnings: string[];
  /** Whether the editor can save (false only without a config.yaml). */
  editable: boolean;
}

/** Issue 438's backup screen — hand-written like `UpdateCheckResponse`:
 * the routes return `dict[str, Any]`, and the committed schema predates
 * them. Mirrors `palaia_hub.backup_api` (the list), `BackupTarget.describe`
 * and `palaia_hub.backup_schedule.TargetRunRecord`/`BackupScheduler.status`.
 * Times are seconds since the epoch. No field carries anything from inside
 * an archive. */
export interface BackupLastRun {
  finished_at: number;
  ok: boolean;
  trigger: "manual" | "schedule";
  artifact: string | null;
  bytes_written: number | null;
  pruned: number;
  duration_seconds: number | null;
  /** Why a failed run failed, in the hub's own words. */
  reason: string | null;
}

export interface BackupTargetInfo {
  name: string;
  kind: string;
  destination: string;
  carries_full_archive: boolean;
  secret_safe: boolean;
  /** Local-directory targets only: how many archives it keeps. */
  keep_last?: number | null;
  running: boolean;
  last_run: BackupLastRun | null;
}

export interface BackupSchedule {
  interval_hours: number;
  /** `null` while a scheduled pass is running. */
  next_run_at: number | null;
  last_pass_at: number | null;
  running: boolean;
}

export interface BackupTargetsResponse {
  targets: BackupTargetInfo[];
  /** `null` when `backup.interval_hours` is not set. */
  schedule: BackupSchedule | null;
}

/** `POST /api/backup/targets/{name}/run` — `BackupRun.to_json`. */
export interface BackupRunResult {
  target: string;
  kind: string;
  destination: string;
  artifact: string;
  bytes_written: number;
  pruned: string[];
  duration_seconds: number;
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
  /** Issue 384: lets a screen cancel a request its next keystroke made stale. */
  signal?: AbortSignal;
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
    ...(options.signal ? { signal: options.signal } : {}),
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

function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { signal });
}

/** A file the hub served: its bytes and the name it suggested, if any. */
export interface DownloadedFile {
  blob: Blob;
  filename: string | null;
}

function filenameFrom(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(disposition);
  return match ? decodeURIComponent(match[1]) : null;
}

/**
 * Fetch a file through the same door as every JSON call (issue 382): a
 * plain `<a href>` to a gated endpoint saved the gate's JSON refusal as
 * the download, and a raw `fetch` skipped the 401 → sign-in redirect the
 * rest of the dashboard relies on.
 */
async function requestBlob(path: string): Promise<DownloadedFile> {
  const response = await fetch(`${API_BASE}${path}`);
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
  const headers: Headers | undefined = response.headers;
  return {
    blob: await response.blob(),
    filename: filenameFrom(headers?.get?.("content-disposition") ?? null),
  };
}

function postJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<T> {
  return request<T>(path, { method: "POST", body, signal });
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

function deleteJson<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** One path segment (a vault key, a profile path, an id): percent-encoded
 * so a `#`, `?` or `/` in the value cannot rewrite the request (issue 399). */
function seg(value: string | number): string {
  return encodeURIComponent(String(value));
}

/** A permalink is a `/`-joined path — each segment encoded, the slashes kept. */
function permalinkPath(permalink: string): string {
  return permalink.split("/").map(encodeURIComponent).join("/");
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

/** Issue 384: the shell's mode indicator, the sidebar and Home all ask for
 * `/api/info` on mount. One request answers everyone asking at the same
 * moment; the next call after it settles fetches afresh, so nothing goes
 * stale. */
let infoInFlight: Promise<InfoResponse> | null = null;

export const api = {
  health: () => getJson<HealthResponse>("/api/health"),
  info: (): Promise<InfoResponse> => {
    if (!infoInFlight) {
      infoInFlight = getJson<InfoResponse>("/api/info").finally(() => {
        infoInFlight = null;
      });
    }
    return infoInFlight;
  },
  /** SPEC-501: "up to date" / "update available" / "could not check", plus
   * per-deployment guidance for the dashboard's update banner. */
  updateCheck: () => getJson<UpdateCheckResponse>("/api/update/check"),

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
   * is part of the sign-in flow itself, which lives at `/oauth/logout`.
   *
   * Carries the double-submit token like every other state-changing call:
   * SPEC-502 put one on `/oauth/logout` too, because it sits outside the
   * `/api/*` prefix the session middleware covers and was therefore the one
   * state-changing surface any page on the internet could trigger. */
  signOut: () => {
    const headers: Record<string, string> = { Accept: "application/json" };
    const token = readCookie(CSRF_COOKIE);
    if (token) headers[CSRF_HEADER] = token;
    return fetch(`${API_BASE}/oauth/logout`, {
      method: "POST",
      headers,
    }).then((response) => {
      if (!response.ok)
        throw new ApiError("/oauth/logout", response.status, undefined);
    });
  },
  /** Same-origin URL for the SSE stream — passed straight to `EventSource`
   * by `useEventStream` (./events.ts), never fetched with `fetch`. */
  eventsUrl: () => `${API_BASE}/api/events`,
  /** SPEC-604: same-origin URL for the "Back up" download — a plain `<a
   * href download>` in `Home.tsx`, never fetched with `fetch`. It is a
   * `GET`, so no CSRF token is needed (`SAFE_METHODS` above); the browser
   * navigation carries the session cookie the same way any same-origin GET
   * does, and the admin gate answers 401 (redirecting to sign-in) exactly
   * like it would for a fetch call if that session is missing. */
  backupUrl: () => `${API_BASE}/api/backup`,
  /** The archive itself, fetched like every other call (issue 382). */
  downloadBackup: () => requestBlob("/api/backup"),
  /** Issue 438: the folders this hub writes its backup into by itself,
   * how each one's last run went, and the schedule if there is one. */
  listBackupTargets: () =>
    getJson<BackupTargetsResponse>("/api/backup/targets"),
  /** Write one backup into that folder now. 409 while one is already being
   * written; 500 with the reason when the folder could not take it. */
  runBackupTarget: (name: string) =>
    postJson<BackupRunResult>(`/api/backup/targets/${seg(name)}/run`, {}),
  /** Any hub-served file by its dashboard-relative path — the Claude
   * Desktop bundle, for one. */
  downloadFile: (path: string) => requestBlob(path),

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
      `/api/vaults/${seg(vaultKey)}/notes${queryString({ folder })}`,
    ),
  readNote: (vaultKey: string, permalink: string) =>
    getJson<NoteRecord>(
      `/api/vaults/${seg(vaultKey)}/notes/${permalinkPath(permalink)}`,
    ),
  noteHistory: (vaultKey: string, permalink: string) =>
    getJson<CommitSummary[]>(
      `/api/vaults/${seg(vaultKey)}/notes/${permalinkPath(permalink)}/history`,
    ),
  noteGraph: (vaultKey: string, permalink: string) =>
    getJson<LocalGraph>(
      `/api/vaults/${seg(vaultKey)}/notes/${permalinkPath(permalink)}/graph`,
    ),
  search: (vaultKey: string, q: string, signal?: AbortSignal) =>
    getJson<SearchHit[]>(
      `/api/vaults/${seg(vaultKey)}/search${queryString({ q })}`,
      signal,
    ),
  inboxStatus: (vaultKey: string) =>
    getJson<InboxStatus>(`/api/vaults/${seg(vaultKey)}/inbox_status`),
  /** The review queue's dashboard mirror (SPEC-208, issue 375): the same
   * proposals and the same decision the review-queue app makes in a client. */
  listReviewQueue: (vaultKey: string) =>
    getJson<ReviewQueueResult>(`/api/vaults/${seg(vaultKey)}/review`),
  decideReview: (
    vaultKey: string,
    permalink: string,
    decision: "approved" | "rejected",
  ) =>
    postJson<ReviewDecideResult>(
      `/api/vaults/${seg(vaultKey)}/review/${permalinkPath(permalink)}/decision`,
      { decision },
    ),
  indexStatus: (vaultKey: string) =>
    getJson<IndexStatus>(`/api/vaults/${seg(vaultKey)}/index_status`),

  // ---- SPEC-504: the local-only first-run funnel ----
  funnelStatus: () => getJson<FunnelStatus>("/api/funnel/status"),

  // ---- issue 342: the wizard's owner-account step ----
  /** Whether this hub has its one owner account. 404 on a hub with no
   * sign-in server at all — the wizard reads that as "nothing to set up". */
  ownerAccount: () => getJson<OwnerAccountState>("/api/auth/owner"),
  /** Create the owner account — accepted only while none exists (409
   * after) — and sign this browser in with it. */
  createOwnerAccount: (body: { username: string; password: string }) =>
    postJson<OwnerAccountState>("/api/auth/owner", body),

  // ---- SPEC-305: the tool-profile editor ----
  listGatewayProfiles: () => getJson<GatewayProfile[]>("/api/gateway/profiles"),
  listGatewayProfileTools: (profilePath: string) =>
    getJson<GatewayTool[]>(`/api/gateway/profiles/${seg(profilePath)}/tools`),
  createGatewayProfile: (body: {
    path: string;
    label?: string | null;
    vaults?: string[];
    stash?: boolean;
    telegram?: boolean;
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
      telegram?: boolean;
      hidden_tools?: string[];
      semantic_routing?: boolean;
      upstreams?: string[];
    },
  ) =>
    patchJson<GatewayProfile>(
      `/api/gateway/profiles/${seg(profilePath)}`,
      body,
    ),
  deleteGatewayProfile: (profilePath: string) =>
    deleteRequest(`/api/gateway/profiles/${seg(profilePath)}`),
  listGatewayVaults: () =>
    getJson<GatewayVaultIdentity[]>("/api/gateway/vaults"),
  updateGatewayVault: (
    vaultKey: string,
    body: {
      name?: string;
      purpose?: string;
      tool_renames?: Record<string, string>;
    },
  ) =>
    patchJson<GatewayVaultIdentity>(
      `/api/gateway/vaults/${seg(vaultKey)}`,
      body,
    ),
  // SPEC-302's registry, read here so the profile editor (SPEC-304 follow-up)
  // can offer an upstream-server checkbox next to the vault checkboxes.
  listGatewayUpstreams: () =>
    getJson<GatewayUpstream[]>("/api/gateway/upstreams"),

  // ---- SPEC-108's token surface, consumed here for "connected clients" ----
  listTokens: () => getJson<TokenInfo[]>("/api/auth/tokens"),
  createToken: (body: { name: string; profile: string; scopes?: string[] }) =>
    postJson<CreatedToken>("/api/auth/tokens", { scopes: [], ...body }),
  revokeToken: (tokenId: string) =>
    deleteRequest(`/api/auth/tokens/${seg(tokenId)}`),

  // ---- SPEC-201's webhook surface ----
  listHooks: () => getJson<HookInfo[]>("/api/hooks"),
  createHook: (body: { url: string; events?: string[] }) =>
    postJson<CreatedHook>("/api/hooks", body),
  setHookEnabled: (hookId: string, enabled: boolean) =>
    patchJson<HookInfo>(`/api/hooks/${seg(hookId)}`, { enabled }),
  deleteHook: (hookId: string) => deleteRequest(`/api/hooks/${seg(hookId)}`),
  hookDeadLetters: (hookId: string) =>
    getJson<DeadLetter[]>(`/api/hooks/${seg(hookId)}/dead_letters`),

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
  ) => putJson<AutomationInfo>(`/api/automations/${seg(automationId)}`, body),
  setAutomationEnabled: (automationId: string, enabled: boolean) =>
    patchJson<AutomationInfo>(`/api/automations/${seg(automationId)}`, {
      enabled,
    }),
  deleteAutomation: (automationId: string) =>
    deleteRequest(`/api/automations/${seg(automationId)}`),
  automationDeliveries: (automationId: string) =>
    getJson<DeliveryLogEntry[]>(
      `/api/automations/${seg(automationId)}/deliveries`,
    ),
  testFireAutomation: (
    automationId: string,
    data: Record<string, unknown> = {},
  ) =>
    postJson<DeliveryLogEntry>(
      `/api/automations/${seg(automationId)}/test_fire`,
      {
        data,
      },
    ),

  // ---- SPEC-307's notification center ----
  listNotifications: (unreadOnly = false) =>
    getJson<NotificationRecord[]>(
      `/api/notifications${queryString({ unread_only: unreadOnly ? "true" : undefined })}`,
    ),
  unreadNotificationCount: () =>
    getJson<{ count: number }>("/api/notifications/unread_count"),
  markNotificationRead: (notificationId: number) =>
    postJson<NotificationRecord>(
      `/api/notifications/${seg(notificationId)}/read`,
      {},
    ),
  markAllNotificationsRead: () =>
    postJson<{ status: string }>("/api/notifications/read_all", {}),

  // ---- SPEC-205: the exposure wizard ----
  mode: () => getJson<ModeStatus>("/api/mode"),
  changeMode: (body: ModeChangeRequest) =>
    postJson<ModeStatus>("/api/mode", body),
  exposure: () => getJson<ExposureStatus>("/api/exposure"),
  tunnelGuidance: (
    body: {
      kind: "tailscale" | "cloudflared";
      local_port?: number;
      hostname?: string;
    },
    signal?: AbortSignal,
  ) => postJson<TunnelGuidance>("/api/exposure/tunnel", body, signal),
  selfTest: (publicUrl: string) =>
    postJson<SelfTestResult>("/api/exposure/selftest", {
      public_url: publicUrl,
    }),

  // ---- SPEC-303/304: the marketplace ----
  searchMarket: (q = "", source?: MarketProvenance, signal?: AbortSignal) =>
    getJson<MarketSearchResult>(
      `/api/market/search${queryString({ q, source })}`,
      signal,
    ),
  getMarketEntry: (entryId: string) =>
    getJson<MarketEntry>(`/api/market/entry/${seg(entryId)}`),
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
  /** What an install would run or connect to, derived before anything
   * happens (issue 349) — the consent screen renders it. */
  getMarketPlan: (entryId: string) =>
    getJson<PlanPreview>(`/api/market/entry/${seg(entryId)}/plan`),
  /** The consent screen's own POST (SPEC-304 deliverable #3) — the token
   * it returns is what `installMarketEntry` below must be given; there is
   * no install path that skips this call. */
  issueMarketConsent: (entryId: string) =>
    postJson<ConsentToken>(`/api/market/entry/${seg(entryId)}/consent`, {}),
  installMarketEntry: (
    entryId: string,
    body: {
      consent_token: string;
      config?: Record<string, string | number | boolean>;
      profiles?: string[];
      display_name?: string | null;
    },
  ) =>
    postJson<InstalledAddon>(`/api/market/entry/${seg(entryId)}/install`, body),
  listInstalledAddons: () => getJson<InstalledAddon[]>("/api/market/installed"),
  updateInstalledAddon: (upstreamKey: string) =>
    postJson<InstalledAddon>(
      `/api/market/installed/${seg(upstreamKey)}/update`,
      {},
    ),
  uninstallAddon: (upstreamKey: string) =>
    deleteRequest(`/api/market/installed/${seg(upstreamKey)}`),

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
    postJson<DeregisterResult>(`/api/directory/${seg(handle)}/deregister`, {}),

  // ---- SPEC-403/405: the messenger ----
  messageFlows: (
    params: {
      handle?: string;
      type?: MessageType;
      state?: DeliveryState;
      limit?: number;
    } = {},
  ) => getJson<MessageFlowsResult>(`/api/messenger/${queryString(params)}`),
  messageThread: (envelopeId: string) =>
    getJson<ThreadMetadataResult>(`/api/messenger/threads/${seg(envelopeId)}`),
  /** The owner's body-bearing read (deliverable #1: "body on expand") —
   * the one route on this mirror that ever returns a body. */
  envelopeDetail: (envelopeId: string) =>
    getJson<EnvelopeDetailResult>(
      `/api/messenger/envelopes/${seg(envelopeId)}`,
    ),
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
    postJson<EndConversationResult>(
      `/api/messenger/threads/${seg(envelopeId)}/end`,
      {},
    ),

  // ---- issue 439: the Telegram panel ----
  /** Answered from the hub's memory — never reaches Telegram, so the panel
   * can refetch it on every `telegram.*` event. 404 only from a hub older
   * than issue 463, which mounted the panel only with a `telegram:`
   * section. */
  telegramStatus: () => getJson<TelegramStatus>("/api/telegram/status"),
  /** The panel's one outbound call: ask Telegram whether this bot's token
   * works. A refused token is a 200 with `last_check.ok === false`. */
  checkTelegramBot: (key: string) =>
    postJson<TelegramBotStatus>(`/api/telegram/bots/${seg(key)}/check`, {}),
  // ---- issue 463: the Telegram editor. Every write answers with the
  // whole status, already applied to the running hub and saved. ----
  createTelegramBot: (body: TelegramBotInput) =>
    postJson<TelegramStatus>("/api/telegram/bots", body),
  updateTelegramBot: (key: string, body: TelegramBotPatch) =>
    patchJson<TelegramStatus>(`/api/telegram/bots/${seg(key)}`, body),
  deleteTelegramBot: (key: string) =>
    deleteJson<TelegramStatus>(`/api/telegram/bots/${seg(key)}`),
  createTelegramRoute: (body: TelegramRouteInput) =>
    postJson<TelegramStatus>("/api/telegram/routes", body),
  replaceTelegramRoute: (bot: string, chat: string, body: TelegramRouteInput) =>
    putJson<TelegramStatus>(
      `/api/telegram/routes/${seg(bot)}/${seg(chat)}`,
      body,
    ),
  deleteTelegramRoute: (bot: string, chat: string) =>
    deleteJson<TelegramStatus>(`/api/telegram/routes/${seg(bot)}/${seg(chat)}`),
  putTelegramGrant: (profile: string, body: { bots: string[]; chats: string[] }) =>
    putJson<TelegramStatus>(`/api/telegram/grants/${seg(profile)}`, body),
  deleteTelegramGrant: (profile: string) =>
    deleteJson<TelegramStatus>(`/api/telegram/grants/${seg(profile)}`),
  /** The write-only secret store (SPEC-302): the one place a credential
   * travels inbound. The answer confirms *that* it was stored, never what. */
  storeSecret: (name: string, value: string) =>
    putJson<{ name: string; created_at: number; updated_at: number }>(
      `/api/secrets/${seg(name)}`,
      { value },
    ),
};
