import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/Toast";
import type { InfoResponse, ModeStatus, SetupStatus, UpdateCheckResponse } from "../../lib/api/client";
import { api, ApiError } from "../../lib/api/client";
import { ThemeProvider } from "../../lib/theme";
import { SettingsHub } from "./SettingsHub";

const SETUP: SetupStatus = {
  completed: true,
  goal: "private",
  owner_configured: true,
  vaults: ["work"],
  profiles: ["default"],
  mode: "locked",
  sign_in_active: false,
  issuer: null,
  configured_mode: "locked",
  configured_sign_in: false,
  configured_issuer: null,
  public_url: null,
  cloud_url_hint: null,
  restart_required: false,
  restart_supported: false,
  cloud_ready: false,
  cloud_verified: false,
  client_connected: true,
  first_memory_saved: true,
  problems: [],
  skipped: [],
};

function stub(setup: Partial<SetupStatus> = {}, backups: "ok" | "gated" = "gated") {
  vi.spyOn(api, "info").mockResolvedValue({
    version: "3.0.0",
    channel: "beta",
    mode: "locked",
    sign_in: { method: "password", provider_name: null, required: false },
  } as unknown as InfoResponse);
  vi.spyOn(api, "setupStatus").mockResolvedValue({ ...SETUP, ...setup });
  vi.spyOn(api, "mode").mockResolvedValue({ active_mode: "locked" } as unknown as ModeStatus);
  vi.spyOn(api, "telegramStatus").mockRejectedValue(new ApiError("/api/telegram/status", 404, {}));
  vi.spyOn(api, "updateCheck").mockResolvedValue({
    state: "up_to_date",
  } as unknown as UpdateCheckResponse);
  vi.spyOn(api, "session").mockRejectedValue(new ApiError("/api/session", 404, {}));
  if (backups === "gated") {
    vi.spyOn(api, "listBackupTargets").mockRejectedValue(new ApiError("/api/backup/targets", 403, {}));
  } else {
    vi.spyOn(api, "listBackupTargets").mockResolvedValue({ targets: [], schedule: null });
  }
}

function mount() {
  return render(
    <ThemeProvider>
      <ToastProvider>
        <MemoryRouter>
          <SettingsHub />
        </MemoryRouter>
      </ToastProvider>
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  try {
    window.localStorage.clear();
  } catch {
    // ignore
  }
});

describe("Settings hub (issue 570)", () => {
  it("shows what this palaia is and every area with its state", async () => {
    stub();
    mount();

    expect(await screen.findByText("palaia 3.0.0")).toBeInTheDocument();
    expect(await screen.findByText("Private · Dashboard sign-in off")).toBeInTheDocument();
    expect(screen.getByText("Turn on dashboard sign-in to download backups")).toBeInTheDocument();
    expect(await screen.findByText("Not set up")).toBeInTheDocument();
    for (const area of ["Access & sign-in", "Backups", "Telegram", "Advanced", "About & updates"]) {
      expect(screen.getByRole("link", { name: new RegExp(area) })).toBeInTheDocument();
    }
  });

  it("offers Restart only where palaia can restart itself", async () => {
    stub({ restart_supported: false });
    const { unmount } = mount();
    await screen.findByText("palaia 3.0.0");
    expect(screen.queryByRole("button", { name: /restart palaia/i })).not.toBeInTheDocument();
    unmount();

    vi.restoreAllMocks();
    stub({ restart_supported: true });
    mount();
    expect(await screen.findByRole("button", { name: /restart palaia/i })).toBeInTheDocument();
  });

  it("says a restart is due, with the server command where the button can't do it", async () => {
    stub({ restart_required: true, restart_supported: false });
    mount();
    expect(await screen.findByText("Restart palaia to apply your changes")).toBeInTheDocument();
    expect(screen.getByText("docker restart palaia-hub")).toBeInTheDocument();
  });

  it("restarts after a confirmation", async () => {
    stub({ restart_supported: true });
    const restart = vi.spyOn(api, "restartHub").mockResolvedValue({ restarting: true });
    vi.spyOn(api, "health").mockRejectedValue(new Error("down"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /restart palaia/i }));
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    await waitFor(() => expect(restart).toHaveBeenCalledOnce());
    expect(await screen.findByRole("button", { name: /restarting/i })).toBeInTheDocument();
  });

  it("switches the appearance", async () => {
    stub();
    mount();
    await screen.findByText("palaia 3.0.0");
    fireEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    fireEvent.click(screen.getByRole("radio", { name: "System" }));
    expect(document.documentElement).not.toHaveAttribute("data-theme");
  });
});
