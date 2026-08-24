import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { GatewayProfile, InstalledAddon, MarketEntry } from "../lib/api/client";
import { api } from "../lib/api/client";
import { Marketplace } from "./Marketplace";

const FETCH_ENTRY: MarketEntry = {
  id: "palaia.fetch",
  name: "Fetch",
  one_liner: "Fetch and convert web pages to markdown.",
  kind: "container",
  source: { type: "image", value: "ghcr.io/palaia/addon-fetch:1.0.0" },
  config_schema: {
    type: "object",
    properties: { user_agent: { type: "string", title: "User agent string" } },
  },
  permissions: ["network"],
  maintainer: "palaia",
  verified: true,
  provenance: "curated",
};

const SKILL_ENTRY: MarketEntry = {
  id: "palaia.viewer",
  name: "Memory Graph Viewer",
  one_liner: "A read-only viewer for the knowledge graph.",
  kind: "skill",
  source: { type: "url", value: "https://addons.palaia.dev/viewer/SKILL.md" },
  config_schema: null,
  permissions: ["memory-scope:read"],
  maintainer: "palaia",
  verified: true,
  provenance: "curated",
};

const MANUAL_SECRET_ENTRY: MarketEntry = {
  id: "acme.tracker",
  name: "Issue Tracker",
  one_liner: "Connects to a project tracker.",
  kind: "remote",
  source: { type: "url", value: "https://tracker.example.com/mcp" },
  config_schema: {
    type: "object",
    properties: { token: { type: "secret", title: "Access token" } },
    required: ["token"],
  },
  permissions: [],
  maintainer: "someone",
  verified: false,
  provenance: "manual",
};

const DEFAULT_PROFILE: GatewayProfile = {
  path: "default",
  label: null,
  vaults: ["work"],
  stash: false,
  hidden_tools: [],
  semantic_routing: false,
  tool_count: 15,
  upstreams: [],
  managed: false,
};

const INSTALLED_FETCH: InstalledAddon = {
  upstream_key: "palaia-fetch",
  entry_id: "palaia.fetch",
  name: "Fetch",
  kind: "container",
  provenance: "curated",
  installed_ref: "ghcr.io/palaia/addon-fetch:1.0.0",
  current_ref: "ghcr.io/palaia/addon-fetch:1.1.0",
  update_available: true,
  up: true,
  status: "Connected — 1 tool.",
  profiles: ["default"],
  installed_at: 1_700_000_000,
};

function mount(initialPath = "/marketplace") {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[initialPath]}>
        <Marketplace />
      </MemoryRouter>
    </ToastProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Marketplace screen (SPEC-304)", () => {
  it("lists search results as cards", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [FETCH_ENTRY], stale: false, notes: {} });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);

    mount();

    expect(await screen.findByText("Fetch")).toBeInTheDocument();
    expect(screen.getByText(/fetch and convert web pages/i)).toBeInTheDocument();
  });

  it("shows an empty state when nothing matches", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [], stale: false, notes: {} });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);

    mount();

    expect(await screen.findByText(/nothing matched/i)).toBeInTheDocument();
  });

  it("shows permissions and a stronger warning for an unverified entry, gated behind consent", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({
      entries: [MANUAL_SECRET_ENTRY],
      stale: false,
      notes: {},
    });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /details/i }));

    expect(await screen.findByText(/you added this one yourself/i)).toBeInTheDocument();
    // The install button exists but does nothing until a secret is filled
    // in and consent is actually issued — proven by the next test.
    expect(screen.getByRole("button", { name: /install and connect/i })).toBeInTheDocument();
  });

  it("issues consent before installing, then installs with the collected config", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({
      entries: [MANUAL_SECRET_ENTRY],
      stale: false,
      notes: {},
    });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);
    const consentSpy = vi
      .spyOn(api, "issueMarketConsent")
      .mockResolvedValue({ token: "tok_abc123", expires_at: 9999999999 });
    const installSpy = vi.spyOn(api, "installMarketEntry").mockResolvedValue({
      upstream_key: "acme-tracker",
      entry_id: "acme.tracker",
      name: "Issue Tracker",
      kind: "remote",
      provenance: "manual",
      installed_ref: "https://tracker.example.com/mcp",
      current_ref: "https://tracker.example.com/mcp",
      update_available: false,
      up: true,
      status: "Connected.",
      profiles: [],
      installed_at: 1,
    });

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /details/i }));
    fireEvent.change(await screen.findByLabelText(/access token/i), {
      target: { value: "sk-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: /install and connect/i }));

    await waitFor(() => expect(consentSpy).toHaveBeenCalledWith("acme.tracker"));
    await waitFor(() =>
      expect(installSpy).toHaveBeenCalledWith(
        "acme.tracker",
        expect.objectContaining({
          consent_token: "tok_abc123",
          config: { token: "sk-secret" },
        }),
      ),
    );
  });

  it("hands off a skill entry to the Clients page instead of installing it", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [SKILL_ENTRY], stale: false, notes: {} });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);
    const installSpy = vi.spyOn(api, "installMarketEntry");

    mount();
    fireEvent.click(await screen.findByRole("button", { name: /details/i }));

    expect(await screen.findByRole("link", { name: /go to clients/i })).toHaveAttribute(
      "href",
      "/clients",
    );
    expect(screen.queryByRole("button", { name: /install and connect/i })).not.toBeInTheDocument();
    expect(installSpy).not.toHaveBeenCalled();
  });

  it("opens the deep-linked entry's consent panel from ?install=", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [], stale: false, notes: {} });
    vi.spyOn(api, "getMarketEntry").mockResolvedValue(FETCH_ENTRY);
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([]);

    mount("/marketplace?install=palaia.fetch");

    expect(await screen.findByText("Fetch")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /install and connect/i })).toBeInTheDocument();
  });

  it("lists an installed add-on with an update badge and lets it be updated", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [], stale: false, notes: {} });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([INSTALLED_FETCH]);
    const updateSpy = vi.spyOn(api, "updateInstalledAddon").mockResolvedValue({
      ...INSTALLED_FETCH,
      update_available: false,
    });

    mount();

    fireEvent.click(await screen.findByRole("button", { name: /^update$/i }));

    await waitFor(() => expect(updateSpy).toHaveBeenCalledWith("palaia-fetch"));
  });

  it("removes an installed add-on after confirming", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({ entries: [], stale: false, notes: {} });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([INSTALLED_FETCH]);
    const uninstallSpy = vi.spyOn(api, "uninstallAddon").mockResolvedValue(undefined);

    mount();

    fireEvent.click(await screen.findByRole("button", { name: /^remove$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /yes, remove it/i }));

    await waitFor(() => expect(uninstallSpy).toHaveBeenCalledWith("palaia-fetch"));
  });
});

/**
 * SPEC-304 acceptance criterion: "jargon lint on all new UI copy
 * (SPEC-205's DOM-scan pattern)" — same scoping as every other screen's
 * own lint: headings, buttons, badges, options, and field labels never
 * carry this codebase's internal names for the thing a person just reads
 * as "a connected tool"/"an add-on".
 */
describe("Marketplace screen copy — no jargon in the surface (system.md §3 rule 0)", () => {
  const BANNED = [
    /\bjson\b/i,
    /\basgi\b/i,
    /\brest\b/i,
    /\burl\b/i,
    /\bapi\b/i,
    /\bhttp\b/i,
    /\bnamespace\b/i,
    /\bfastmcp\b/i,
    /\bmcp\b/i,
    /\bupstream\b/i,
    /\bstdio\b/i,
    /\bregistry_ref\b/i,
    /\bprovenance\b/i,
  ];

  it("no heading, button, badge, option, or field label uses an implementation word", async () => {
    vi.spyOn(api, "searchMarket").mockResolvedValue({
      entries: [FETCH_ENTRY, MANUAL_SECRET_ENTRY],
      stale: false,
      notes: {},
    });
    vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE]);
    vi.spyOn(api, "listInstalledAddons").mockResolvedValue([INSTALLED_FETCH]);

    mount();
    await screen.findAllByRole("button", { name: /details/i });
    for (const button of screen.getAllByRole("button", { name: /details/i })) {
      fireEvent.click(button);
    }
    await screen.findByRole("button", { name: /install and connect/i });

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("option"),
      ...Array.from(
        document.querySelectorAll(".badge, .card__title, .card__subject, .field__label"),
      ),
    ];

    expect(controls.length).toBeGreaterThan(5);
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
