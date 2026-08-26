import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FunnelStatus, InfoResponse, TokenInfo, VaultSummary } from "../lib/api/client";
import { api } from "../lib/api/client";
import type { EventStreamState } from "../lib/events";
import { Home } from "./Home";

const BASE_STREAM: EventStreamState = {
  connection: "open",
  health: { status: "ok" },
  healthAt: Date.now(),
  vaultChangeCount: 0,
  lastVaultChange: null,
  recentChanges: [],
  agentActivityCount: 0,
};

const A_VAULT: VaultSummary = {
  key: "work",
  purpose: "Work notes.",
  path: "/x",
  writable: true,
  note_count: 3,
};

const A_TOKEN: TokenInfo = {
  id: "t1",
  name: "claude-code",
  profile: "default",
  scopes: ["vault:work:read", "vault:work:write"],
  created_at: new Date().toISOString(),
  last_used_at: new Date().toISOString(),
  revoked_at: null,
};

const NO_FUNNEL: FunnelStatus = {
  hub_started_at: Date.now() / 1000,
  vault_created_at: null,
  client_connected_at: null,
  first_memory_at: null,
  time_to_first_memory_seconds: null,
  time_to_first_memory_display: null,
};

const CELEBRATING_FUNNEL: FunnelStatus = {
  hub_started_at: 1000,
  vault_created_at: 1050,
  client_connected_at: 1100,
  first_memory_at: 1252,
  time_to_first_memory_seconds: 252,
  time_to_first_memory_display: "4m12s",
};

function mount(stream: EventStreamState = BASE_STREAM) {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <Outlet context={stream} />,
        children: [{ index: true, element: <Home /> }],
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(<RouterProvider router={router} />);
}

function mockApi(overrides: { funnel?: FunnelStatus } = {}) {
  vi.spyOn(api, "info").mockResolvedValue({ version: "3.0.0", mode: "locked" } as InfoResponse);
  vi.spyOn(api, "listVaults").mockResolvedValue([A_VAULT]);
  vi.spyOn(api, "inboxStatus").mockResolvedValue({
    count: 0,
    oldest_capture_id: null,
    oldest_age_seconds: null,
    last_capture_id: null,
    last_captured_at: null,
  });
  vi.spyOn(api, "indexStatus").mockResolvedValue({
    vault: "work",
    schema_version: 1,
    notes: 3,
    observations: 0,
    relations: 0,
    unresolved_relations: 0,
    embeds: {
      enabled: false,
      available: false,
      model: "",
      dim: 0,
      total: 0,
      ready: 0,
      pending: 0,
      failed: 0,
      reason: "disabled",
    },
    embed_progress_percent: 100,
    embed_summary: "disabled",
  });
  vi.spyOn(api, "listTokens").mockResolvedValue([A_TOKEN]);
  vi.spyOn(api, "funnelStatus").mockResolvedValue(overrides.funnel ?? NO_FUNNEL);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Home — SPEC-504 first-memory celebration", () => {
  it("shows nothing extra before the first memory is recorded", async () => {
    mockApi({ funnel: NO_FUNNEL });

    mount();

    await screen.findByText(/1 vault/i);
    expect(screen.queryByTestId("first-memory-celebration")).not.toBeInTheDocument();
  });

  it("celebrates once the funnel reports a first memory, showing the elapsed time", async () => {
    mockApi({ funnel: CELEBRATING_FUNNEL });

    mount();

    const banner = await screen.findByTestId("first-memory-celebration");
    expect(banner).toHaveTextContent("Your first memory is in.");
    expect(banner).toHaveTextContent("4m12s");
  });

  it("does not blow up when the funnel endpoint is unreachable", async () => {
    vi.spyOn(api, "info").mockResolvedValue({ version: "3.0.0", mode: "locked" } as InfoResponse);
    vi.spyOn(api, "listVaults").mockResolvedValue([A_VAULT]);
    vi.spyOn(api, "inboxStatus").mockResolvedValue({
      count: 0,
      oldest_capture_id: null,
      oldest_age_seconds: null,
      last_capture_id: null,
      last_captured_at: null,
    });
    vi.spyOn(api, "indexStatus").mockResolvedValue({
      vault: "work",
      schema_version: 1,
      notes: 3,
      observations: 0,
      relations: 0,
      unresolved_relations: 0,
      embeds: {
        enabled: false,
        available: false,
        model: "",
        dim: 0,
        total: 0,
        ready: 0,
        pending: 0,
        failed: 0,
        reason: "disabled",
      },
      embed_progress_percent: 100,
      embed_summary: "disabled",
    });
    vi.spyOn(api, "listTokens").mockResolvedValue([A_TOKEN]);
    vi.spyOn(api, "funnelStatus").mockRejectedValue(new Error("no funnel store reachable"));

    mount();

    await screen.findByText(/1 vault/i);
    await waitFor(() => expect(screen.queryByTestId("first-memory-celebration")).not.toBeInTheDocument());
  });

  it("never says 'this number never leaves this hub' without also naming what the number is", async () => {
    // SPEC-504 §10 privacy-copy sanity check, not a jargon lint (see below
    // for that one) — the celebration explicitly states the local-only
    // promise inline, so a reader never has to guess.
    mockApi({ funnel: CELEBRATING_FUNNEL });

    mount();

    const banner = await screen.findByTestId("first-memory-celebration");
    expect(banner).toHaveTextContent(/never leaves this hub/i);
  });
});

/**
 * Same jargon-lint shape as `Agents.test.tsx`'s own — no protocol name,
 * standard, acronym or implementation word in the celebration banner's
 * visible text.
 */
describe("first-memory celebration copy — no jargon (system.md §3 rule 0)", () => {
  const BANNED = [
    /\bmcp\b/i,
    /\boauth\b/i,
    /\bjwt\b/i,
    /\basgi\b/i,
    /\bapi\b/i,
    /\bjson\b/i,
    /\bvault\b/i,
    /\bfunnel\b/i,
  ];

  it("the banner's text uses no in-house word", async () => {
    mockApi({ funnel: CELEBRATING_FUNNEL });

    mount();

    const banner = await screen.findByTestId("first-memory-celebration");
    const text = banner.textContent ?? "";
    for (const pattern of BANNED) {
      expect(text).not.toMatch(pattern);
    }
  });
});
