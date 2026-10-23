/**
 * The first-run setup against a fake hub that keeps real state: the wizard's
 * position and ticks must come from `/api/setup`, a reload must resume where
 * the hub stands, and the cloud path must use the public address, never the
 * dashboard's own origin (issues 559, 561, 562, 563, 565).
 */
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../../components/Toast";
import type { SetupStatus } from "../../lib/api/client";
import { Onboarding } from "./Onboarding";

const PUBLIC = "https://palaia-hub.tail1234.ts.net";

function freshStatus(overrides: Partial<SetupStatus> = {}): SetupStatus {
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
    cloud_url_hint: PUBLIC,
    restart_required: false,
    restart_supported: true,
    cloud_ready: false,
    cloud_verified: false,
    client_connected: false,
    first_memory_saved: false,
    problems: [],
    ...overrides,
  };
}

interface Call {
  method: string;
  path: string;
  body: unknown;
}

/** A hub in memory: the endpoints the wizard uses change `state` the way the
 * real ones change the hub. */
function fakeHub(initial: SetupStatus) {
  // `unreachable`: how many self-tests fail before the address answers (a
  // new tunnel or Funnel address that is not reachable yet).
  const state = { status: initial, unreachable: 0 };
  const calls: Call[] = [];
  const json = (body: unknown, status = 200) =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://100.64.0.1:8420");
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, path: url.pathname, body });
    const s = state.status;
    switch (`${method} ${url.pathname}`) {
      case "GET /api/setup":
        return json(s);
      case "PUT /api/setup":
        state.status = { ...s, ...body };
        return json(state.status);
      case "POST /api/vaults":
        state.status = { ...s, vaults: [body.key], profiles: ["default"] };
        return json({ key: body.key }, 201);
      case "POST /api/auth/owner":
        state.status = { ...s, owner_configured: true };
        return json({ configured: true }, 201);
      case "POST /api/mode":
        state.status = {
          ...s,
          configured_mode: body.mode ?? s.configured_mode,
          configured_sign_in: body.oauth_enabled ?? s.configured_sign_in,
          configured_issuer: body.oauth_issuer ?? s.configured_issuer,
          public_url: body.public_url ?? s.public_url,
          restart_required: true,
        };
        return json({ restart_required: true });
      case "POST /api/hub/restart":
        return json({ restarting: true }, 202);
      case "POST /api/exposure/selftest":
        if (state.unreachable > 0) {
          state.unreachable -= 1;
          return json({
            checked_url: body.public_url,
            reachable: false,
            status_code: 0,
            latency_ms: 0,
            error: "the address did not answer.",
            checks: [{ id: "discovery", passed: false, detail: "no answer." }],
          });
        }
        state.status = { ...s, cloud_verified: true };
        return json({
          checked_url: body.public_url,
          reachable: true,
          status_code: 200,
          latency_ms: 80,
          error: "",
          checks: [
            { id: "discovery", passed: true, detail: "sign-in details found." },
            {
              id: "mcp",
              passed: true,
              detail: "the AI connection answers and asks for sign-in.",
            },
            {
              id: "admin_private",
              passed: true,
              detail: "the admin API stays private.",
            },
            {
              id: "dashboard_private",
              passed: true,
              detail: "the dashboard stays private.",
            },
          ],
        });
      default:
        return json({ detail: "not in this fake" }, 404);
    }
  });
  vi.stubGlobal("fetch", fetchMock);
  return { state, calls };
}

function renderWizard(at = "/onboarding") {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <ToastProvider>
        <Onboarding />
      </ToastProvider>
    </MemoryRouter>,
  );
}

function rail() {
  return within(screen.getByRole("list", { name: /^steps$/i }));
}

describe("first-run setup", () => {
  beforeEach(() => {
    vi.useRealTimers();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts with the goal, recommends cloud access, and stores the choice on the hub", async () => {
    const hub = fakeHub(freshStatus());
    renderWizard();

    expect(
      await screen.findByRole("heading", {
        name: /how do you want to use palaia/i,
      }),
    ).toBeInTheDocument();
    const cloud = screen.getByRole("radio", {
      name: /with chatgpt and claude/i,
    });
    expect(cloud).toHaveAttribute("aria-checked", "true");
    expect(within(cloud).getByText(/recommended/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    expect(
      await screen.findByRole("heading", { name: /create your first memory/i }),
    ).toBeInTheDocument();
    expect(hub.calls).toContainEqual({
      method: "PUT",
      path: "/api/setup",
      body: { goal: "cloud" },
    });
  });

  it("marks the optional fields, uses a neutral example and sends no empty description", async () => {
    const hub = fakeHub(freshStatus({ goal: "cloud" }));
    renderWizard();

    expect(
      await screen.findByRole("heading", { name: /create your first memory/i }),
    ).toBeInTheDocument();
    const purpose = screen.getByLabelText(/what it's for/i);
    expect(screen.getAllByText("Optional").length).toBeGreaterThanOrEqual(1);
    expect(purpose).toHaveAttribute(
      "placeholder",
      "Projects, decisions and notes",
    );
    expect(document.body.textContent).not.toMatch(/byte5/i);

    fireEvent.click(screen.getByRole("button", { name: /create memory/i }));
    expect(
      await screen.findByRole("heading", { name: /create your account/i }),
    ).toBeInTheDocument();
    const create = hub.calls.find((c) => c.path === "/api/vaults");
    expect(create?.body).toEqual({ key: "work", template: false });
  });

  it("ticks a step only when the hub has it, and resumes there after a reload", async () => {
    fakeHub(
      freshStatus({ goal: "cloud", vaults: ["work"], profiles: ["default"] }),
    );
    const first = renderWizard();

    // The memory exists, the account does not: the wizard opens at the
    // account, with the memory ticked and the account not.
    expect(
      await screen.findByRole("heading", { name: /create your account/i }),
    ).toBeInTheDocument();
    expect(
      rail().getByRole("button", { name: /your first memory \(done\)/i }),
    ).toBeInTheDocument();
    expect(
      rail().queryByRole("button", { name: /your account \(done\)/i }),
    ).not.toBeInTheDocument();

    first.unmount();
    renderWizard();
    expect(
      await screen.findByRole("heading", { name: /create your account/i }),
    ).toBeInTheDocument();
  });

  it("creates the account before cloud access, then turns cloud on with the public address", async () => {
    const hub = fakeHub(
      freshStatus({ goal: "cloud", vaults: ["work"], profiles: ["default"] }),
    );
    renderWizard();

    await screen.findByRole("heading", { name: /create your account/i });
    fireEvent.change(screen.getByLabelText(/^username/i), {
      target: { value: "owner" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "a-long-passphrase" },
    });
    fireEvent.change(screen.getByLabelText(/repeat the password/i), {
      target: { value: "a-long-passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByRole("heading", { name: /turn on cloud access/i }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/public address/i)).toHaveValue(PUBLIC);
    // The account was created without turning the sign-in server on first:
    // no restart, no trip back to an earlier step.
    expect(hub.calls.filter((c) => c.path === "/api/mode")).toHaveLength(0);

    fireEvent.click(
      screen.getByRole("button", { name: /turn on cloud access/i }),
    );
    expect(
      await screen.findByRole("heading", {
        name: /restart palaia to turn on cloud access/i,
      }),
    ).toBeInTheDocument();
    const mode = hub.calls.find((c) => c.path === "/api/mode");
    expect(mode?.body).toEqual({
      mode: "cloud",
      oauth_enabled: true,
      oauth_issuer: PUBLIC,
      public_url: PUBLIC,
      tunnel: "tailscale",
    });
    expect(JSON.stringify(mode?.body)).not.toContain(window.location.origin);
    // The step itself says what the restart does: one click restarts,
    // without a second "Restart palaia?" question.
    fireEvent.click(screen.getByRole("button", { name: /restart palaia/i }));
    await waitFor(() =>
      expect(
        hub.calls.some((c) => c.method === "POST" && c.path === "/api/hub/restart"),
      ).toBe(true),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("refuses a plain http address before sending anything", async () => {
    const hub = fakeHub(
      freshStatus({
        goal: "cloud",
        vaults: ["work"],
        profiles: ["default"],
        owner_configured: true,
        cloud_url_hint: null,
      }),
    );
    renderWizard();

    const field = await screen.findByLabelText(/public address/i);
    fireEvent.change(field, { target: { value: "http://100.64.0.1:8420" } });
    expect(
      screen.getByText(/use the https:\/\/ address only/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /turn on cloud access/i }),
    ).toBeDisabled();
    expect(hub.calls.some((c) => c.path === "/api/mode")).toBe(false);
  });

  it("after the restart, checks the public address and then offers the Claude app", async () => {
    fakeHub(
      freshStatus({
        goal: "cloud",
        vaults: ["work"],
        profiles: ["default"],
        owner_configured: true,
        mode: "cloud",
        configured_mode: "cloud",
        sign_in_active: true,
        configured_sign_in: true,
        issuer: PUBLIC,
        configured_issuer: PUBLIC,
        public_url: PUBLIC,
        cloud_ready: true,
      }),
    );
    renderWizard();

    expect(
      await screen.findByRole("heading", { name: /cloud access works/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Dashboard stays private")).toBeInTheDocument();
  });

  it("keeps checking a new public address by itself until it answers", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const hub = fakeHub(
        freshStatus({
          goal: "cloud",
          vaults: ["work"],
          profiles: ["default"],
          owner_configured: true,
          mode: "cloud",
          configured_mode: "cloud",
          sign_in_active: true,
          configured_sign_in: true,
          issuer: PUBLIC,
          configured_issuer: PUBLIC,
          public_url: PUBLIC,
          cloud_ready: true,
        }),
      );
      hub.state.unreachable = 1;
      renderWizard();

      expect(await screen.findByText(/not reachable yet/i)).toBeInTheDocument();
      expect(screen.queryByText(/not working yet/i)).not.toBeInTheDocument();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(
        await screen.findByRole("heading", { name: /cloud access works/i }),
      ).toBeInTheDocument();
      expect(
        hub.calls.filter((c) => c.path === "/api/exposure/selftest"),
      ).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("offers the Claude app and ChatGPT first for the cloud goal, ready with the public address", async () => {
    fakeHub(
      freshStatus({
        goal: "cloud",
        vaults: ["work"],
        profiles: ["default"],
        owner_configured: true,
        mode: "cloud",
        configured_mode: "cloud",
        sign_in_active: true,
        configured_sign_in: true,
        issuer: PUBLIC,
        configured_issuer: PUBLIC,
        public_url: PUBLIC,
        cloud_ready: true,
        cloud_verified: true,
      }),
    );
    renderWizard();

    expect(
      await screen.findByRole("heading", { name: /connect your ai app/i }),
    ).toBeInTheDocument();
    const apps = screen.getAllByRole("radio").map((r) => r.textContent ?? "");
    expect(apps[0]).toMatch(/^Claude/);
    expect(apps[1]).toMatch(/^ChatGPT/);
    expect(apps.some((a) => /Claude Code CLI/.test(a))).toBe(true);
    expect(screen.getByText(`${PUBLIC}/mcp/default`)).toBeInTheDocument();
    expect(screen.getByText(/settings → connectors/i)).toBeInTheDocument();
  });

  it("keeps a private hub's cloud apps visible but says what they need", async () => {
    fakeHub(
      freshStatus({
        goal: "private",
        vaults: ["work"],
        profiles: ["default"],
        skipped: ["account"],
      }),
    );
    renderWizard();

    expect(
      await screen.findByRole("heading", { name: /connect your ai app/i }),
    ).toBeInTheDocument();
    const claude = screen
      .getAllByRole("radio")
      .find((r) => /^Claude(?! Desktop| Code)/.test(r.textContent ?? ""));
    expect(claude).toHaveTextContent(/needs cloud access/i);
    fireEvent.click(claude!);
    expect(
      screen.getByRole("button", { name: /turn on cloud access/i }),
    ).toBeInTheDocument();
    expect(
      rail().getByRole("button", { name: /your account \(skipped\)/i }),
    ).toBeInTheDocument();
  });

  it("finishes into Home and remembers it on the hub", async () => {
    const hub = fakeHub(
      freshStatus({
        goal: "private",
        vaults: ["work"],
        profiles: ["default"],
        owner_configured: true,
        sign_in_active: true,
        configured_sign_in: true,
        client_connected: true,
      }),
    );
    renderWizard();

    expect(
      await screen.findByRole("heading", { name: /you're set up/i }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /open palaia/i }));
    await waitFor(() =>
      expect(hub.calls).toContainEqual({
        method: "PUT",
        path: "/api/setup",
        body: { completed: true },
      }),
    );
  });

  it("a private account keeps its step open until sign-in is on, through the restart", async () => {
    const hub = fakeHub(
      freshStatus({ goal: "private", vaults: ["work"], profiles: ["default"] }),
    );
    const first = renderWizard();

    await screen.findByRole("heading", { name: /create your account/i });
    fireEvent.change(screen.getByLabelText(/^username/i), { target: { value: "owner" } });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "a-long-passphrase" },
    });
    fireEvent.change(screen.getByLabelText(/repeat the password/i), {
      target: { value: "a-long-passphrase" },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByRole("heading", { name: /restart palaia to turn on sign-in/i }),
    ).toBeInTheDocument();
    expect(hub.state.status.owner_configured).toBe(true);
    expect(hub.state.status.configured_sign_in).toBe(true);

    // A reload before the restart opens there again, not past it.
    first.unmount();
    renderWizard();
    expect(
      await screen.findByRole("heading", { name: /restart palaia to turn on sign-in/i }),
    ).toBeInTheDocument();
  });

  it("choosing private after cloud access was turned on turns it off and shows the restart", async () => {
    const hub = fakeHub(
      freshStatus({
        goal: "cloud",
        vaults: ["work"],
        profiles: ["default"],
        owner_configured: true,
        mode: "cloud",
        configured_mode: "cloud",
        sign_in_active: true,
        configured_sign_in: true,
        issuer: PUBLIC,
        configured_issuer: PUBLIC,
        public_url: PUBLIC,
        cloud_ready: true,
        cloud_verified: true,
        client_connected: true,
      }),
    );
    renderWizard();

    await screen.findByRole("heading", { name: /you're set up/i });
    fireEvent.click(rail().getByRole("button", { name: /how you'll use palaia/i }));
    fireEvent.click(await screen.findByRole("radio", { name: /only on my own devices/i }));
    expect(screen.getByText(/this turns off access from the internet/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));

    await waitFor(() =>
      expect(hub.calls).toContainEqual({
        method: "POST",
        path: "/api/mode",
        // As Settings › Switch to Private sends it (issue 588): the sign-in
        // server moves off the public address, which answers nothing in Private.
        body: {
          mode: "locked",
          dashboard_require_sign_in: true,
          oauth_issuer: window.location.origin,
        },
      }),
    );
    expect(hub.calls).toContainEqual({ method: "PUT", path: "/api/setup", body: { goal: "private" } });
    expect(hub.state.status.configured_mode).toBe("locked");
    expect(await screen.findByText(/restart palaia to apply your changes/i)).toBeInTheDocument();
    expect(screen.getByText(/can still be reached from the internet/i)).toBeInTheDocument();
  });

  it("keeps cloud access when the goal stays cloud", async () => {
    const hub = fakeHub(
      freshStatus({ goal: null, configured_mode: "cloud", configured_sign_in: true }),
    );
    renderWizard();

    await screen.findByRole("heading", { name: /how do you want to use palaia/i });
    expect(screen.queryByText(/this turns off access from the internet/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^continue$/i }));
    await screen.findByRole("heading", { name: /create your first memory/i });
    expect(hub.calls.some((c) => c.path === "/api/mode")).toBe(false);
  });

  it("opens the step a link asks for, also one skipped before", async () => {
    fakeHub(
      freshStatus({
        completed: true,
        goal: "private",
        vaults: ["work"],
        profiles: ["default"],
        skipped: ["account"],
        client_connected: true,
      }),
    );
    const first = renderWizard();
    // Without the link: every step is done or skipped.
    await screen.findByRole("heading", { name: /you're set up/i });
    first.unmount();

    renderWizard("/onboarding?step=account");
    expect(
      await screen.findByRole("heading", { name: /create your account/i }),
    ).toBeInTheDocument();
  });

  it("Finish without a first request saves the step for later and moves on", async () => {
    const hub = fakeHub(
      freshStatus({
        goal: "private",
        vaults: ["work"],
        profiles: ["default"],
        skipped: ["account"],
      }),
    );
    renderWizard();

    await screen.findByRole("heading", { name: /connect your ai app/i });
    fireEvent.click(screen.getByRole("button", { name: /^finish$/i }));

    expect(await screen.findByRole("heading", { name: /you're set up/i })).toBeInTheDocument();
    expect(hub.calls).toContainEqual({
      method: "PUT",
      path: "/api/setup",
      body: { skipped: ["account", "client"] },
    });
  });
});
