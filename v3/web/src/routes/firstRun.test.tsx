/**
 * The way into and out of first-run setup, through the real route table:
 * the app shell sends an unfinished setup to the wizard — also when an old
 * address redirects before `/api/setup` answers — and the wizard's way out
 * to AI apps saves setup as finished first, so the shell lets that page be.
 */
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { SetupStatus } from "../lib/api/client";
import { api } from "../lib/api/client";
import { ThemeProvider } from "../lib/theme";
import { routes } from "./index";

function status(overrides: Partial<SetupStatus> = {}): SetupStatus {
  return {
    completed: false,
    goal: null,
    skipped: [],
    owner_configured: false,
    vaults: [],
    profiles: [],
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
    client_connected: false,
    first_memory_saved: false,
    problems: [],
    ...overrides,
  };
}

function mountAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <ThemeProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </ThemeProvider>,
  );
  return router;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("first-run setup and the app shell", () => {
  it("an old address that redirects before setup answers still opens setup", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub in this test"));
    let answer: (value: SetupStatus) => void = () => {};
    vi.spyOn(api, "setupStatus").mockReturnValue(
      new Promise<SetupStatus>((resolve) => {
        answer = resolve;
      }),
    );

    const router = mountAt("/clients");
    // The AI apps page is on screen — the shell has rendered the new
    // address — before palaia answers.
    expect(await screen.findByRole("heading", { name: "AI apps" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/apps");
    await act(async () => {
      answer(status());
    });

    await waitFor(() => expect(router.state.location.pathname).toBe("/onboarding"));
  });

  it("Connect another AI app on the last step opens AI apps and stays there", async () => {
    vi.spyOn(api, "info").mockRejectedValue(new Error("no hub in this test"));
    let hub = status({
      goal: "private",
      vaults: ["work"],
      profiles: ["default"],
      skipped: ["account"],
      client_connected: true,
    });
    const asked = vi.spyOn(api, "setupStatus").mockImplementation(async () => hub);
    const update = vi.spyOn(api, "updateSetup").mockImplementation(async (body) => {
      hub = { ...hub, ...body } as SetupStatus;
      return hub;
    });

    const router = mountAt("/onboarding");
    const leave = await screen.findByRole("button", { name: /connect another ai app/i });
    const before = asked.mock.calls.length;
    fireEvent.click(leave);

    await waitFor(() => expect(router.state.location.pathname).toBe("/apps"));
    expect(update).toHaveBeenCalledWith({ completed: true });
    // The shell asks once it opens; the answer must leave the page alone.
    await waitFor(() => expect(asked.mock.calls.length).toBeGreaterThan(before));
    await act(async () => {
      await Promise.resolve();
    });
    expect(router.state.location.pathname).toBe("/apps");
  });
});
