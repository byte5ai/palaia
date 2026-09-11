import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { api } from "../lib/api/client";
import type { ExposureStatus, ModeStatus } from "../lib/api/client";
import { Exposure } from "./Exposure";

function mount() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <Exposure />
      </ToastProvider>
    </MemoryRouter>,
  );
}

const OPEN_MODE_STATUS: ModeStatus = {
  active_mode: "open",
  configured_mode: "open",
  restart_required: false,
  host: "0.0.0.0",
  auth_enabled: true,
  oauth_enabled: false,
  oauth_issuer: null,
  public_url: "https://hub.example.com",
  tunnel: "tailscale",
};

const OPEN_EXPOSURE_STATUS: ExposureStatus = {
  status: OPEN_MODE_STATUS,
  detected: { tailscale: true, cloudflared: false },
  checklist: [
    {
      id: "auth_mandatory",
      title: "Sign-in is required",
      detail: "Every client must present a token or sign-in account.",
      auto: true,
      passed: true,
    },
    {
      id: "dashboard_exposure_acknowledged",
      title: "You understand the dashboard itself is now public",
      detail: "Only pick this mode if you mean it.",
      auto: false,
      passed: null,
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Exposure", () => {
  it("says so and offers a retry when the mode cannot be loaded (issue 378)", async () => {
    // It used to sit on "Loading your current access mode…" for good.
    const mode = vi.spyOn(api, "mode").mockRejectedValue(new Error("no hub in this test"));

    mount();

    expect(await screen.findByText(/could not load your current access mode/i)).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: /access mode/i })).not.toBeInTheDocument();

    mode.mockResolvedValue(OPEN_MODE_STATUS);
    vi.spyOn(api, "exposure").mockResolvedValue(OPEN_EXPOSURE_STATUS);
    vi.spyOn(api, "tunnelGuidance").mockResolvedValue({
      kind: "tailscale",
      config: "tailscale funnel 8420",
      commands: [],
      note: "",
    } as never);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByRole("radiogroup", { name: /access mode/i })).toBeInTheDocument();
  });

  it("renders the current mode, the tunnel guidance, and the hardening checklist", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(OPEN_MODE_STATUS);
    vi.spyOn(api, "exposure").mockResolvedValue(OPEN_EXPOSURE_STATUS);
    vi.spyOn(api, "tunnelGuidance").mockResolvedValue({
      label: "Tailscale Serve + Funnel",
      config: '{"Web": {}}',
      commands: ["tailscale funnel 443 on"],
      note: "Exposes the whole hub, including the dashboard, at https://hub.example.com/.",
    });

    mount();

    expect(await screen.findByText(/everything is reachable from the internet/i)).toBeInTheDocument();
    expect(screen.getByText(/reach it from outside your network/i)).toBeInTheDocument();
    expect(await screen.findByText(/tailscale funnel 443 on/)).toBeInTheDocument();
    expect(screen.getByText(/before you open the dashboard itself/i)).toBeInTheDocument();
    expect(screen.getByText("Sign-in is required")).toBeInTheDocument();
    expect(screen.getByText(/you understand the dashboard itself is now public/i)).toBeInTheDocument();
  });
});

/**
 * SPEC-205 acceptance criterion #5: "no jargon in wizard copy (lint)".
 * system.md §3 rule 0 — no protocol name, standard, acronym, transport or
 * implementation word in a label, heading, button, badge, status line or
 * option name. This scans exactly those control surfaces (not full body
 * paragraphs, where the rule explicitly allows the term to live as
 * explanatory prose) against the terms rule 0's own Don't/Do table bans
 * from view.
 */
describe("Exposure — the sign-in switch (issue 374)", () => {
  const LOCKED_MODE_STATUS: ModeStatus = {
    ...OPEN_MODE_STATUS,
    active_mode: "locked",
    configured_mode: "locked",
    host: "127.0.0.1",
    auth_enabled: true,
    public_url: null,
    tunnel: null,
  };

  it("can be saved on its own", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED_MODE_STATUS);
    const change = vi
      .spyOn(api, "changeMode")
      .mockResolvedValue({ ...LOCKED_MODE_STATUS, auth_enabled: false });

    mount();
    const save = await screen.findByRole("button", { name: /no changes to save/i });
    expect(save).toBeDisabled();

    fireEvent.click(screen.getByRole("switch", { name: /require sign-in/i }));

    const armed = screen.getByRole("button", { name: /save this access mode/i });
    expect(armed).toBeEnabled();
    fireEvent.click(armed);

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith({ mode: "locked", auth_enabled: false }),
    );
    // Saved: the switch's new position is the baseline again.
    expect(await screen.findByRole("button", { name: /no changes to save/i })).toBeDisabled();
  });
});

describe("Exposure wizard copy — no jargon in the surface (system.md §3 rule 0)", () => {
  const BANNED = [
    /\boidc\b/i,
    /\boauth\b/i,
    /\bjwt\b/i,
    /\bpkce\b/i,
    /\bcimd\b/i,
    /\bdcr\b/i,
    /\btailnet\b/i,
    /\basgi\b/i,
    /\brfc\s*\d/i,
    /\bbearer\b/i,
  ];

  it("no heading, button, badge, or option name uses a protocol name or acronym", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(OPEN_MODE_STATUS);
    vi.spyOn(api, "exposure").mockResolvedValue(OPEN_EXPOSURE_STATUS);
    vi.spyOn(api, "tunnelGuidance").mockResolvedValue({
      label: "Tailscale Serve + Funnel",
      config: "{}",
      commands: ["tailscale funnel 443 on"],
      note: "Exposes the whole hub, including the dashboard, at https://hub.example.com/.",
    });

    mount();
    await screen.findByText(/everything is reachable from the internet/i);
    await screen.findByText("Sign-in is required");

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("radio"),
      ...Array.from(document.querySelectorAll(".badge, .card__title, .card__subject, .field__label")),
    ];

    expect(controls.length).toBeGreaterThan(5); // the scan actually saw real content
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
