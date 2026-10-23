import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import { api } from "../lib/api/client";
import type { ExposureStatus, ModeStatus, SetupStatus } from "../lib/api/client";
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

const LOCKED: ModeStatus = {
  active_mode: "locked",
  configured_mode: "locked",
  restart_required: false,
  host: "127.0.0.1",
  auth_enabled: true,
  oauth_enabled: false,
  oauth_issuer: null,
  dashboard_require_sign_in: null,
  public_url: null,
  tunnel: null,
};

const OPEN: ModeStatus = {
  ...LOCKED,
  active_mode: "open",
  configured_mode: "open",
  host: "0.0.0.0",
  oauth_enabled: true,
  oauth_issuer: "https://hub.example.com",
  public_url: "https://hub.example.com",
  tunnel: "tailscale",
};

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
  restart_supported: true,
  cloud_ready: false,
  client_connected: true,
  first_memory_saved: true,
  problems: [],
  skipped: [],
};

const OPEN_EXPOSURE: ExposureStatus = {
  status: OPEN,
  detected: { tailscale: true, cloudflared: false },
  checklist: [
    {
      id: "auth_mandatory",
      title: "Authentication is required",
      detail: "Every MCP client must present a bearer token or an OAuth access token.",
      auto: true,
      passed: true,
    },
    {
      id: "owner_account",
      title: "The owner account has its own password",
      detail: "A local owner account is configured.",
      auto: true,
      passed: true,
    },
    {
      id: "tls",
      title: "The public URL serves valid TLS",
      detail: "Run the self-test below to confirm — not checked yet.",
      auto: false,
      passed: null,
    },
    {
      id: "dashboard_exposure_acknowledged",
      title: "You understand the admin dashboard itself is now public",
      detail: "Only pick this mode if you mean it.",
      auto: false,
      passed: null,
    },
  ],
};

const GUIDANCE = {
  label: "Tailscale Funnel",
  config: "",
  commands: ["sudo tailscale funnel --bg http://127.0.0.1:8422"],
  note: "Makes only palaia's AI connection reachable at https://hub.example.com/.",
};

beforeEach(() => {
  vi.spyOn(api, "setupStatus").mockResolvedValue(SETUP);
  vi.spyOn(api, "ownerAccount").mockResolvedValue({ configured: true });
  vi.spyOn(api, "tunnelGuidance").mockResolvedValue(GUIDANCE);
  vi.spyOn(api, "exposure").mockResolvedValue(OPEN_EXPOSURE);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Access & sign-in: loading", () => {
  it("says it couldn't load, never sits on a spinner, and tries again (issue 378)", async () => {
    const mode = vi.spyOn(api, "mode").mockRejectedValue(new Error("no hub in this test"));

    mount();

    expect(await screen.findByText(/couldn't load how palaia is reached/i)).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: /access mode/i })).not.toBeInTheDocument();

    mode.mockResolvedValue(LOCKED);
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByRole("radiogroup", { name: /access mode/i })).toBeInTheDocument();
  });
});

describe("Access & sign-in: the two sign-in switches (issue 571, report §5.2)", () => {
  it("shows the mode with its outcome, and the dashboard and AI-app switches separately", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    mount();

    const summary = await screen.findByTestId("access-summary");
    expect(summary).toHaveTextContent("Private");
    expect(summary).toHaveTextContent(/only devices on your network or vpn/i);
    expect(summary).toHaveTextContent("Dashboard sign-in off");
    expect(summary).toHaveTextContent("AI apps need an access key");

    const dashboard = screen.getByRole("switch", { name: "Require sign-in for this dashboard" });
    const keys = screen.getByRole("switch", { name: "AI apps need an access key" });
    expect(dashboard).toHaveAttribute("aria-checked", "false");
    expect(keys).toHaveAttribute("aria-checked", "true");
  });

  it("turns on the dashboard's sign-in with its sign-in server, then offers the restart", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    const change = vi.spyOn(api, "changeMode").mockResolvedValue({
      ...LOCKED,
      oauth_enabled: true,
      oauth_issuer: window.location.origin,
      dashboard_require_sign_in: true,
      restart_required: true,
    });
    mount();

    fireEvent.click(await screen.findByRole("switch", { name: "Require sign-in for this dashboard" }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith({
        dashboard_require_sign_in: true,
        oauth_enabled: true,
        oauth_issuer: window.location.origin,
      }),
    );
    expect(await screen.findByText("Restart palaia to apply your changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /restart now/i })).toBeInTheDocument();
    // The access-key switch was never touched.
    expect(change).toHaveBeenCalledTimes(1);
  });

  it("asks for the owner account before the dashboard can require it", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    vi.spyOn(api, "ownerAccount").mockResolvedValue({ configured: false });
    mount();

    expect(await screen.findByText("Create the owner account first")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Require sign-in for this dashboard" })).toBeDisabled();
  });

  it("confirms before AI apps can connect without a key, and changes nothing on Cancel", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    const change = vi
      .spyOn(api, "changeMode")
      .mockResolvedValue({ ...LOCKED, auth_enabled: false, restart_required: true });
    mount();

    fireEvent.click(await screen.findByRole("switch", { name: "AI apps need an access key" }));
    const dialog = screen.getByRole("dialog", { name: /without an access key/i });
    expect(dialog).toHaveTextContent(/anyone on your network could read and change your memories/i);
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(change).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("switch", { name: "AI apps need an access key" }));
    fireEvent.click(screen.getByRole("button", { name: "Turn off access keys" }));
    await waitFor(() => expect(change).toHaveBeenCalledWith({ auth_enabled: false }));
  });

  it("shows the hub's reason in place when it refuses a change", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    const { ApiError } = await import("../lib/api/client");
    vi.spyOn(api, "changeMode").mockRejectedValue(
      new ApiError("/api/mode", 400, {
        detail: "Create your first memory before turning on sign-in.",
      }),
    );
    mount();

    fireEvent.click(await screen.findByRole("switch", { name: "Require sign-in for this dashboard" }));
    expect(
      await screen.findByText("Create your first memory before turning on sign-in."),
    ).toBeInTheDocument();
  });
});

describe("Access & sign-in: where palaia can be reached", () => {
  it("sets up Cloud with one public address for sign-in and the AI connection", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    const change = vi
      .spyOn(api, "changeMode")
      .mockResolvedValue({ ...LOCKED, configured_mode: "cloud", restart_required: true });
    mount();

    fireEvent.click(await screen.findByRole("radio", { name: /^cloud/i }));
    const address = screen.getByLabelText("Public address");
    fireEvent.change(address, { target: { value: "hub.example.com" } });
    expect(screen.getByText(/use the full https:\/\/ address/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Switch to Cloud" })).toBeDisabled();

    fireEvent.change(address, { target: { value: "https://hub.example.com/" } });
    fireEvent.click(screen.getByRole("button", { name: "Switch to Cloud" }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith({
        mode: "cloud",
        oauth_enabled: true,
        oauth_issuer: "https://hub.example.com",
        public_url: "https://hub.example.com",
        tunnel: "tailscale",
      }),
    );
  });

  it("asks before going back to Private", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(OPEN);
    const change = vi.spyOn(api, "changeMode").mockResolvedValue({ ...OPEN, configured_mode: "locked" });
    mount();

    fireEvent.click(await screen.findByRole("radio", { name: /^private/i }));
    fireEvent.click(screen.getByRole("button", { name: "Switch to Private" }));
    expect(screen.getByRole("dialog", { name: "Switch to Private?" })).toHaveTextContent(
      /claude\.ai, chatgpt/i,
    );
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Switch to Private" }));
    await waitFor(() => expect(change).toHaveBeenCalledWith({ mode: "locked" }));
  });

  it("Public lists what palaia checked itself, in plain words, and needs an acknowledgement", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    mount();

    fireEvent.click(await screen.findByRole("radio", { name: /^public/i }));
    const checklist = await screen.findByTestId("public-checklist");
    expect(await within(checklist).findByText("AI apps need a key or sign-in")).toBeInTheDocument();
    expect(within(checklist).getByText("The owner account has its own password")).toBeInTheDocument();
    expect(within(checklist).getAllByText("Done")).toHaveLength(2);
    expect(within(checklist).getByText("Check yourself")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Public address"), {
      target: { value: "https://hub.example.com" },
    });
    const button = screen.getByRole("button", { name: "Switch to Public" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(button).toBeEnabled();
  });

  it("checks a configured public address from the internet and shows each result", async () => {
    vi.spyOn(api, "mode").mockResolvedValue({
      ...OPEN,
      active_mode: "cloud",
      configured_mode: "cloud",
    });
    vi.spyOn(api, "selfTest").mockResolvedValue({
      checked_url: "https://hub.example.com",
      reachable: false,
      status_code: 200,
      latency_ms: 40,
      error: "the dashboard answers there",
      checks: [
        { id: "discovery", passed: true, detail: "sign-in details found." },
        { id: "dashboard_private", passed: false, detail: "the dashboard answers there." },
      ],
    });
    mount();

    fireEvent.click(await screen.findByRole("button", { name: "Check it from the internet" }));
    const test = screen.getByTestId("self-test");
    expect(await within(test).findByText("Doesn't work yet")).toBeInTheDocument();
    expect(within(test).getByText("Sign-in details")).toBeInTheDocument();
    expect(within(test).getByText("Dashboard stays private")).toBeInTheDocument();
  });
});

describe("Access & sign-in copy — no jargon in the surface (system.md §3)", () => {
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
    /\btoken\b/i,
    /\bvault\b/i,
    /\bmcp\b/i,
  ];

  it("no heading, button, pill, option or label uses a protocol name or an internal word", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(OPEN);
    mount();
    await screen.findByTestId("public-checklist");
    await screen.findByText("AI apps need a key or sign-in");

    const controls = [
      ...screen.queryAllByRole("heading"),
      ...screen.queryAllByRole("button"),
      ...screen.queryAllByRole("radio"),
      ...screen.queryAllByRole("switch"),
      ...Array.from(
        document.querySelectorAll(
          ".pill, .badge, .card__title, .listrow__title, .field__label, .check-list__title",
        ),
      ),
    ];

    expect(controls.length).toBeGreaterThan(10); // the scan actually saw real content
    for (const element of controls) {
      const text = element.textContent ?? "";
      for (const pattern of BANNED) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});

describe("tunnel guidance requests (issue 384)", () => {
  it("asks for guidance once the address holds still, not on every keystroke", async () => {
    vi.spyOn(api, "mode").mockResolvedValue(LOCKED);
    const guidance = vi.spyOn(api, "tunnelGuidance").mockResolvedValue(GUIDANCE);

    mount();
    fireEvent.click(await screen.findByRole("radio", { name: /^cloud/i }));
    await waitFor(() => expect(guidance).toHaveBeenCalledTimes(1));

    const box = screen.getByLabelText("Public address");
    fireEvent.change(box, { target: { value: "https://h" } });
    fireEvent.change(box, { target: { value: "https://hu" } });
    fireEvent.change(box, { target: { value: "https://hub" } });

    await waitFor(() =>
      expect(guidance).toHaveBeenLastCalledWith(
        { kind: "tailscale", hostname: "hub" },
        expect.any(AbortSignal),
      ),
    );
    const hostnames = guidance.mock.calls.map((call) => call[0].hostname);
    expect(hostnames).toEqual([undefined, "hub"]);
  });
});
