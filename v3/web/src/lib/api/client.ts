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

export const api = {
  health: () => getJson<HealthResponse>("/api/health"),
  info: () => getJson<InfoResponse>("/api/info"),
  /** Same-origin URL for the SSE stream — passed straight to `EventSource`
   * by `useEventStream` (./events.ts), never fetched with `fetch`. */
  eventsUrl: () => `${API_BASE}/api/events`,
};
