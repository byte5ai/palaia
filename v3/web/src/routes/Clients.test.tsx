import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "../components/Toast";
import type { CreatedToken, GatewayProfile, ModeStatus } from "../lib/api/client";
import { api } from "../lib/api/client";
import { Clients } from "./Clients";

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

const CODEX_ONLY_PROFILE: GatewayProfile = { ...DEFAULT_PROFILE, path: "codex-only", tool_count: 4 };

describe("Clients (connect-a-client)", () => {
  it("lists every §6-matrix client and explains a not-yet one when selected", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: /claude code cli/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^chatgpt/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^chatgpt/i }));

    // A not-yet client never dead-ends: it gets a truthful, specific reason.
    expect(await screen.findByText(/not available yet/i)).toBeInTheDocument();
  });

  it("selects a guided client by default and offers to issue it a token", async () => {
    render(
      <MemoryRouter>
        <ToastProvider>
          <Clients />
        </ToastProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: /issue token/i })).toBeInTheDocument();
  });

  describe("the tool-profile picker (issue 373)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    it("issues the token for the profile picked, not for the default", async () => {
      vi.spyOn(api, "mode").mockResolvedValue({
        active_mode: "locked",
        configured_mode: "locked",
        restart_required: false,
        oauth_enabled: false,
        oauth_issuer: null,
      } as unknown as ModeStatus);
      vi.spyOn(api, "listTokens").mockResolvedValue([]);
      vi.spyOn(api, "listGatewayProfiles").mockResolvedValue([DEFAULT_PROFILE, CODEX_ONLY_PROFILE]);
      const created = vi.spyOn(api, "createToken").mockImplementation(async (body) => ({
        info: {
          id: "t-new",
          name: body.name,
          profile: body.profile,
          scopes: body.scopes ?? [],
          created_at: new Date().toISOString(),
          last_used_at: null,
          revoked_at: null,
        },
        token: "plaintext-token",
      }) as CreatedToken);

      render(
        <MemoryRouter>
          <ToastProvider>
            <Clients />
          </ToastProvider>
        </MemoryRouter>,
      );

      const picker = await screen.findByLabelText(/tool profile for/i);
      fireEvent.change(picker, { target: { value: "codex-only" } });
      fireEvent.click(await screen.findByRole("button", { name: /issue token/i }));

      await waitFor(() => expect(created).toHaveBeenCalled());
      expect(created).toHaveBeenCalledWith(expect.objectContaining({ profile: "codex-only" }));
    });
  });

  describe("Claude Desktop — the one-click download (SPEC-306)", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("downloads a real bundle on click, no copy/paste step", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        blob: async () => new Blob(["fake mcpb bytes"]),
      });
      vi.stubGlobal("fetch", fetchMock);
      const clickSpy = vi.fn();
      const originalClick = HTMLAnchorElement.prototype.click;
      HTMLAnchorElement.prototype.click = clickSpy;

      render(
        <MemoryRouter>
          <ToastProvider>
            <Clients />
          </ToastProvider>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /claude code \(desktop app\)/i }));
      const downloadButton = await screen.findByRole("button", { name: /download bundle/i });
      fireEvent.click(downloadButton);

      // The dashboard's own mount-time calls (mode/listTokens) share this
      // same mocked `fetch` — the assertion is that *a* call named the
      // bundle endpoint, not that it was the only call.
      await waitFor(() => {
        const urls = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(urls.some((url) => url.includes("/api/connect/mcpb"))).toBe(true);
      });
      await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));

      HTMLAnchorElement.prototype.click = originalClick;
    });

    it("shows the hub's own error instead of a dead end when it cannot build one", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
          ok: false,
          status: 501,
          json: async () => ({ detail: "no client-authentication method is configured" }),
        }),
      );

      render(
        <MemoryRouter>
          <ToastProvider>
            <Clients />
          </ToastProvider>
        </MemoryRouter>,
      );

      fireEvent.click(screen.getByRole("button", { name: /claude code \(desktop app\)/i }));
      fireEvent.click(await screen.findByRole("button", { name: /download bundle/i }));

      expect(
        await screen.findByText(/no client-authentication method is configured/i),
      ).toBeInTheDocument();
    });
  });
});
