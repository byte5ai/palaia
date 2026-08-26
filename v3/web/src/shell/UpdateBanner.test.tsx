import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { api } from "../lib/api/client";
import type { UpdateCheckResponse } from "../lib/api/client";
import { UpdateBanner } from "./UpdateBanner";

function mount() {
  return render(
    <ToastProvider>
      <UpdateBanner />
    </ToastProvider>,
  );
}

const UPDATE_AVAILABLE: UpdateCheckResponse = {
  state: "update_available",
  channel: "stable",
  current_version: "0.1.0",
  latest_version: "0.2.0",
  checked_at: 0,
  deployment: "compose",
  reason: null,
  guidance: {
    kind: "command",
    message: "Run the update helper, then restart:",
    commands: ["palaia-hub update", "docker compose pull", "docker compose up -d"],
  },
};

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("UpdateBanner", () => {
  it("renders nothing while the check has not resolved yet", () => {
    vi.spyOn(api, "updateCheck").mockReturnValue(new Promise(() => {}));

    mount();

    expect(screen.queryByText("Update available")).not.toBeInTheDocument();
  });

  it("renders nothing when the hub is already up to date", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue({
      ...UPDATE_AVAILABLE,
      state: "up_to_date",
      latest_version: "0.1.0",
    });

    mount();

    await waitFor(() => expect(api.updateCheck).toHaveBeenCalled());
    expect(screen.queryByText("Update available")).not.toBeInTheDocument();
  });

  it("renders nothing when the hub could not check", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue({
      ...UPDATE_AVAILABLE,
      state: "cannot_check",
      latest_version: null,
      reason: "network error",
    });

    mount();

    await waitFor(() => expect(api.updateCheck).toHaveBeenCalled());
    expect(screen.queryByText("Update available")).not.toBeInTheDocument();
  });

  it("shows the banner, versions, and guidance commands when an update exists", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue(UPDATE_AVAILABLE);

    mount();

    expect(await screen.findByText("Update available")).toBeInTheDocument();
    expect(screen.getByText(/0\.1\.0/)).toBeInTheDocument();
    expect(screen.getByText(/0\.2\.0/)).toBeInTheDocument();
    expect(screen.getByText(/run the update helper, then restart/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /palaia-hub update/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /docker compose pull/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /docker compose up -d/i })).toBeInTheDocument();
  });

  it("a store deployment shows no commands, just the store's own name", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue({
      ...UPDATE_AVAILABLE,
      deployment: "umbrel",
      guidance: {
        kind: "store",
        message: "Umbrel manages updates for this install — open it there to update.",
        commands: [],
      },
    });

    mount();

    expect(await screen.findByText(/umbrel manages updates/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /docker/i })).not.toBeInTheDocument();
  });

  it("dismissing hides the banner and remembers the version across a remount", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue(UPDATE_AVAILABLE);

    const { unmount } = mount();
    await screen.findByText("Update available");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(() => expect(screen.queryByText("Update available")).not.toBeInTheDocument());
    unmount();

    vi.spyOn(api, "updateCheck").mockResolvedValue(UPDATE_AVAILABLE);
    mount();
    await waitFor(() => expect(api.updateCheck).toHaveBeenCalled());
    expect(screen.queryByText("Update available")).not.toBeInTheDocument();
  });

  it("a newer version after a dismissal shows the banner again", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue(UPDATE_AVAILABLE);
    const { unmount } = mount();
    await screen.findByText("Update available");
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.queryByText("Update available")).not.toBeInTheDocument());
    unmount();

    vi.spyOn(api, "updateCheck").mockResolvedValue({
      ...UPDATE_AVAILABLE,
      latest_version: "0.3.0",
    });
    mount();

    expect(await screen.findByText(/0\.3\.0/)).toBeInTheDocument();
  });
});

/**
 * SPEC-501 acceptance criterion: "jargon lint on all new user-facing
 * copy". system.md §3 rule 0 — no protocol name, standard, acronym,
 * transport or implementation word in visible copy. GHCR/OCI-flavored
 * words in particular, since this banner's own backend talks to a
 * container registry — none of that belongs on screen.
 */
describe("UpdateBanner copy — no jargon (system.md §3 rule 0)", () => {
  const BANNED = [
    /\bghcr\b/i,
    /\boci\b/i,
    /\bapi\b/i,
    /\bjson\b/i,
    /\bmanifest\b/i,
    /\bdigest\b/i,
    /\bregistry\b/i,
    /\bannotation\b/i,
    /\bhttp\b/i,
  ];

  it("no visible text in the banner uses registry/protocol jargon", async () => {
    vi.spyOn(api, "updateCheck").mockResolvedValue(UPDATE_AVAILABLE);

    mount();
    await screen.findByText("Update available");
    const banner = document.querySelector(".update-banner");
    const text = banner?.textContent ?? "";

    for (const pattern of BANNED) {
      expect(text).not.toMatch(pattern);
    }
  });
});
