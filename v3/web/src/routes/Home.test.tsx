import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type {
  BackupTargetsResponse,
  FunnelStatus,
  RecentChange,
  SetupStatus,
  TokenInfo,
  VaultSummary,
} from "../lib/api/client";
import { api, ApiError } from "../lib/api/client";
import type { EventStreamState } from "../lib/events";
import { Home } from "./Home";

const RUNNING: EventStreamState = {
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

const USED_TOKEN: TokenInfo = {
  id: "t1",
  name: "Claude Code CLI",
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

const SETUP = { restart_required: false, restart_supported: false } as SetupStatus;

function mount(stream: EventStreamState = RUNNING) {
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
  return render(
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>,
  );
}

function mockApi(
  overrides: {
    vaults?: VaultSummary[] | Error;
    tokens?: TokenInfo[];
    inbox?: number;
    funnel?: FunnelStatus;
    backups?: BackupTargetsResponse | Error;
    recent?: RecentChange[];
    setup?: Partial<SetupStatus>;
  } = {},
) {
  if (overrides.vaults instanceof Error) {
    vi.spyOn(api, "listVaults").mockRejectedValue(overrides.vaults);
  } else {
    vi.spyOn(api, "listVaults").mockResolvedValue(overrides.vaults ?? [A_VAULT]);
  }
  vi.spyOn(api, "inboxStatus").mockResolvedValue({
    count: overrides.inbox ?? 0,
    oldest_capture_id: null,
    oldest_age_seconds: null,
    last_capture_id: null,
    last_captured_at: null,
  });
  vi.spyOn(api, "indexStatus").mockRejectedValue(new Error("not needed"));
  vi.spyOn(api, "listTokens").mockResolvedValue(overrides.tokens ?? [USED_TOKEN]);
  vi.spyOn(api, "funnelStatus").mockResolvedValue(overrides.funnel ?? NO_FUNNEL);
  vi.spyOn(api, "recentActivity").mockResolvedValue(overrides.recent ?? []);
  vi.spyOn(api, "setupStatus").mockResolvedValue({ ...SETUP, ...overrides.setup });
  if (overrides.backups instanceof Error) {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(overrides.backups);
  } else {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue(
      overrides.backups ?? { targets: [], schedule: null },
    );
  }
}

beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    // ignore
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Overview — the verdict comes first (issue 570)", () => {
  it("says palaia is running and summarises the state in pills", async () => {
    mockApi({ inbox: 1 });
    mount();

    expect(await screen.findByRole("heading", { name: "palaia is running" })).toBeInTheDocument();
    expect(await screen.findByText("1 memory · 3 notes")).toBeInTheDocument();
    expect(screen.getByText("1 AI app connected")).toBeInTheDocument();
    expect(await screen.findByText("1 note to file")).toBeInTheDocument();
    // Connected already: no "connect" call to action competes with the verdict.
    expect(screen.queryByRole("link", { name: "Connect an AI app" })).toBeNull();
  });

  it("points a hub without a memory at setup, as the one primary action", async () => {
    mockApi({ vaults: [] });
    mount();

    expect(await screen.findByRole("heading", { name: "Finish setting up palaia" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue setup" })).toHaveAttribute("href", "/onboarding");
    expect(screen.queryByRole("link", { name: "Connect an AI app" })).toBeNull();
  });

  it("asks for an AI app once a memory exists and none has connected", async () => {
    mockApi({ tokens: [{ ...USED_TOKEN, last_used_at: null }] });
    mount();

    expect(await screen.findByRole("link", { name: "Connect an AI app" })).toHaveAttribute("href", "/apps");
    expect(await screen.findByText("Waiting for first use")).toBeInTheDocument();
  });

  it("does not claim anything while the memories are still loading (issue 378)", () => {
    vi.spyOn(api, "listVaults").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "listTokens").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "setupStatus").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "listBackupTargets").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "recentActivity").mockReturnValue(new Promise(() => {}));
    vi.spyOn(api, "funnelStatus").mockReturnValue(new Promise(() => {}));
    mount();

    expect(screen.getByRole("heading", { name: "Connecting to palaia…" })).toBeInTheDocument();
    expect(screen.queryByText(/finish setting up/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /continue setup|connect an ai app/i })).toBeNull();
  });

  it("an error is an error, never an empty hub, and Try again asks again", async () => {
    mockApi({ vaults: new ApiError("/api/vaults", 500, { detail: "the index is locked" }) });
    mount();

    expect(await screen.findByRole("heading", { name: "Couldn't load your memories" })).toBeInTheDocument();
    expect(screen.getByText(/the index is locked/)).toBeInTheDocument();
    expect(screen.queryByText(/finish setting up/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(api.listVaults).toHaveBeenCalledTimes(2));
  });

  it("says when palaia can't be reached, in the sidebar's words", async () => {
    mockApi();
    mount({ ...RUNNING, connection: "reconnecting" });

    expect(await screen.findByRole("heading", { name: "Can't reach palaia" })).toBeInTheDocument();
  });

  it("says palaia needs attention when its health is degraded", async () => {
    mockApi();
    mount({ ...RUNNING, health: { status: "degraded", components: { index: "degraded" } } });

    expect(await screen.findByRole("heading", { name: "palaia needs attention" })).toBeInTheDocument();
  });

  it("shows a due restart with its action", async () => {
    mockApi({ setup: { restart_required: true, restart_supported: true } });
    mount();

    expect(await screen.findByText("Restart palaia to apply your changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /restart now/i })).toBeInTheDocument();
  });
});

describe("Overview — first saved note (SPEC-504)", () => {
  const CELEBRATING: FunnelStatus = {
    hub_started_at: 1000,
    vault_created_at: 1050,
    client_connected_at: 1100,
    first_memory_at: 1252,
    time_to_first_memory_seconds: 252,
    time_to_first_memory_display: "4m12s",
  };

  it("shows nothing before the first note", async () => {
    mockApi();
    mount();
    await screen.findByRole("heading", { name: "palaia is running" });
    expect(screen.queryByTestId("first-memory-celebration")).toBeNull();
  });

  it("says how long setup took, in words, once — and can be dismissed for good", async () => {
    mockApi({ funnel: CELEBRATING });
    const { unmount } = mount();

    const banner = await screen.findByTestId("first-memory-celebration");
    expect(banner).toHaveTextContent("First note saved — setup took 4 min 12 s.");
    expect(banner).not.toHaveTextContent(/\b(hub|vault|funnel|client)\b/i);
    fireEvent.click(within(banner).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("first-memory-celebration")).toBeNull();
    unmount();

    mount();
    await screen.findByRole("heading", { name: "palaia is running" });
    expect(screen.queryByTestId("first-memory-celebration")).toBeNull();
  });
});

describe("Overview — backup is a row, not an explanation (issue 571)", () => {
  it("without dashboard sign-in it says what to do and links to Backups", async () => {
    mockApi({ backups: new ApiError("/api/backup/targets", 403, {}) });
    mount();

    expect(await screen.findByText("Turn on dashboard sign-in to download backups.")).toBeInTheDocument();
    expect(screen.getByText("Needs sign-in")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Backups" })).toHaveAttribute("href", "/settings/backups");
    expect(screen.queryByText(/this file can act as your hub/i)).toBeNull();
    expect(screen.queryByText(/downloads one file with everything/i)).toBeNull();
  });

  it("shows when the last automatic backup ran", async () => {
    mockApi({
      backups: {
        schedule: null,
        targets: [
          {
            name: "usb",
            kind: "local_dir",
            destination: "/mnt/usb",
            carries_full_archive: true,
            secret_safe: false,
            running: false,
            last_run: {
              finished_at: Date.now() / 1000 - 7200,
              ok: true,
              trigger: "schedule",
              artifact: "a.tar.gz",
              bytes_written: 10,
              pruned: 0,
              duration_seconds: 1,
              reason: null,
            },
          },
        ],
      },
    });
    mount();

    expect(await screen.findByText("Last backup 2 h ago.")).toBeInTheDocument();
    expect(screen.getByText("Backed up")).toBeInTheDocument();
  });
});

describe("Overview — the activity feed", () => {
  it("names what changed before the page was opened, in words", async () => {
    mockApi({
      recent: [
        {
          vault: "work",
          permalink: "projects/website/release-process",
          title: "Release process",
          modified: new Date(Date.now() - 5 * 60_000).toISOString(),
        } as RecentChange,
      ],
    });
    mount();

    const feed = await screen.findByRole("list", { name: "Recent activity" });
    expect(feed).toHaveTextContent("Saved Release process");
    expect(feed).toHaveTextContent("work · 5 min ago");
    expect(feed).not.toHaveTextContent("projects/website");
  });

  it("says plainly when nothing has happened yet", async () => {
    mockApi();
    mount();
    expect(await screen.findByText("No activity yet. New and changed notes appear here.")).toBeInTheDocument();
  });
});

describe("Overview copy — no in-house words (system.md §3)", () => {
  it("never says vault, token, client or hub on a running palaia", async () => {
    mockApi({ inbox: 2 });
    mount();
    await screen.findByText("2 notes to file");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/\b(vaults?|tokens?|clients?|hub)\b/i);
  });
});

describe("Overview — no answer at all is 'can't reach', not an error answer", () => {
  it("says Can't reach palaia when the memory list gets no response", async () => {
    mockApi({ vaults: new TypeError("Failed to fetch") });
    mount();

    expect(await screen.findByRole("heading", { name: "Can't reach palaia" })).toBeInTheDocument();
    expect(screen.queryByText(/answered with an error/i)).toBeNull();
  });
});

describe("Overview — no empty feed when palaia can't be read", () => {
  it("hides the activity feed behind an error instead of saying nothing happened", async () => {
    mockApi({ vaults: new ApiError("/api/vaults", 500, {}) });
    mount();
    await screen.findByRole("heading", { name: "Couldn't load your memories" });
    expect(screen.queryByText(/no activity yet/i)).toBeNull();
  });
});
